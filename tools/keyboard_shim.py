#!/usr/bin/env python3
"""Wheel/key shim for the Hudiy Diagnostics overlay.

WHY THIS EXISTS
    Hudiy's native input stack never routes physical keys (wheel / knob) into a
    third-party overlay's webview on this build -- proven by CDP trials on
    2026-09-11: zero DOM keydowns and zero hudiy={} bridge callbacks while the
    overlay was visible, with inputFocus/activated staying false no matter what
    the user turned or pressed. KeyEvent injection toggles the page's focus
    flags but does not deliver nav keys either.

    The working channel is the QtWebEngine DevTools socket (127.0.0.1:9222,
    disabled by default; launched by Hudiy itself with --remote-debugging-port).
    Through it we call window.__diagKeyNav(), a hook diag.js exposes for the
    shim, which drives the exact same moveFocus/activate/back functions the
    bridge callbacks use.

WHAT IT READS
    /dev/input/event1 -- the rotary wheel arrives as a USB mouse: EV_REL
    REL_WHEEL (+1 down / -1 up) ticks, REL_X for horizontal. The knob center
    press shows up on the same or sibling event devices as EV_KEY -- detected
    at runtime; any EV_KEY press while the overlay is visible is forwarded as
    "activate", long-press (>=400 ms) is not needed for v1.

VISIBILITY
    Reads the diag control lane (127.0.0.1:44414/status). While the overlay is
    hidden the shim is inert -- it never touches Hudiy's native UI or the
    race-dash overlay.

RUNTIME
    Runs as the car user with a systemd --user unit (hudiy-diag-keys). Reading
    /dev/input needs the `input` group: `sudo usermod -aG input $USER` (done at
    install time by tools/install_key_shim.sh) or a udev rule.
"""
from __future__ import annotations

import json
import os
import select
import signal
import socket
import struct
import subprocess
import sys
import time
import urllib.request

# --- tunables ---------------------------------------------------------------
EV_REL, EV_KEY = 0x02, 0x01
REL_WHEEL, REL_WHEEL_HWHEEL, REL_X = 0x08, 0x0A, 0x00
# Elecrow knob on the head unit (gen4-ESP32 MCU at /dev/input/event4), EV_KEY
# press/release per detent -- remapped from LIVE per-direction captures 11 Sep
# (the earlier 1/2/3 guess was wrong; each direction was captured separately):
#   code 2 (KEY_1)    - one detent LEFT  (CCW / previous)
#   code 3 (KEY_2)    - one detent RIGHT (CW  / next)
#   code 28 (KEY_ENTER) - knob center press (activate)
#   code 1  (KEY_ESC) - treated as back / previous fallback
# (Matches the owner's model: turns = scroll left/right, click = ENTER.)
EVENT_FILE = "/dev/input/event4"
KEY_LEFT_CODE, KEY_RIGHT_CODE, KEY_ENTER_CODE, KEY_BACK_CODE = 2, 3, 28, 1
LANE_STATUS = "http://127.0.0.1:44414/status"
CDP_URL = "http://127.0.0.1:9222/json"
FRAME_FMT = "llHHI"
FRAME_SIZE = struct.calcsize(FRAME_FMT)
POLL_INTERVAL = 2.0          # visibility check cadence while inert
DEBOUNCE_S = 0.05

_wd = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --- visibility -------------------------------------------------------------
def overview_visible() -> bool:
    """True while the diag overlay is showing on screen."""
    try:
        with urllib.request.urlopen(LANE_STATUS, timeout=1.5) as resp:
            status = json.loads(resp.read().decode("utf-8", "replace"))
        hudiy = status.get("hudiy") or {}
        vis = hudiy.get("last_visibility") or {}
        return vis.get("identifier") == "diag" and vis.get("visibility") == "ALWAYS"
    except Exception:
        return False


# --- CDP --------------------------------------------------------------------
def cdp_ws_url() -> str | None:
    try:
        with urllib.request.urlopen(CDP_URL, timeout=1.5) as resp:
            targets = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None
    for target in targets:
        if "diag.html" in target.get("url", ""):
            return target.get("webSocketDebuggerUrl")
    return None


def cdp_eval(ws_url: str, expr: str, timeout: float = 3.0) -> bool:
    """Fire one Runtime.evaluate into the diag webview via CDP."""
    try:
        import websocket  # websocket-client; installed on the Pi
        ws = websocket.create_connection(ws_url, timeout=timeout)
        try:
            ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                "params": {"expression": expr, "returnByValue": True}}))
            deadline = time.time() + timeout
            while time.time() < deadline:
                msg = json.loads(ws.recv())
                if msg.get("id") == 1:
                    return "result" in msg
        finally:
            ws.close()
    except Exception:
        return False
    return False


DBG = os.environ.get("SHIM_DEBUG_LOG", "/tmp/diag_shim_dbg.log")

def dbg(msg: str) -> None:
    try:
        with open(DBG, "a") as f:
            f.write(f"{time.time():.6f} {msg}\n")
    except Exception:
        pass


def nav_step(ws_url_holder: dict, step: str) -> None:
    dbg(f"nav_step {step}")
    url = ws_url_holder.get("url")
    if not url:  # re-resolve lazily; webviews die/reborn with the overlay
        url = cdp_ws_url()
        if not url:
            return
        ws_url_holder["url"] = url
    expr = f"typeof window.__diagKeyNav==='function' && window.__diagKeyNav({step!r})"
    if not cdp_eval(url, expr):
        dbg("first eval failed -> retry")
        # target vanished (page reloaded / overlay closed) - force re-resolve
        ws_url_holder["url"] = None
        fresh = cdp_ws_url()
        if fresh and cdp_eval(fresh, expr):
            ws_url_holder["url"] = fresh


# --- events -----------------------------------------------------------------
def show_recovery(ws_url_holder: dict) -> None:
    """Hudiy RE-SHOWS the singleton diag webview on relaunch (it does not
    reload it). If a previous session ended via Exit, our own teardown state
    (body.exited + hidden #app) survives and paints blank. Force a page reload
    when the overlay transitions hidden -> visible (found live 11 Sep)."""
    url = cdp_ws_url()
    if not url:
        return
    try:
        import websocket  # lazy import
        ws = websocket.create_connection(url, timeout=3.0)
        try:
            # Reload ONLY when the previous session actually exited (blank
            # would otherwise flash white on a normal re-show). */
            ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": "document.body.classList.contains('exited')", "returnByValue": True}}))
            need = None
            deadline = time.time() + 2.0
            while need is None and time.time() < deadline:
                msg = json.loads(ws.recv())
                if msg.get("id") == 1:
                    need = msg.get("result", {}).get("result", {}).get("value")
                    break
            if need is False:
                return
            if need is True:
                ws.send(json.dumps({"id": 2, "method": "Page.reload", "params": {"ignoreCache": False}}))
                time.sleep(0.5)
        finally:
            ws.close()
    except Exception:
        pass
    else:
        ws_url_holder["url"] = None  # target id changes after reload


def scan_events(ws_url_holder: dict) -> None:
    """Read EV_KEY wheel detents + knob press from the head unit MCU."""
    fd = os.open(EVENT_FILE, os.O_RDONLY | os.O_NONBLOCK)
    was_visible = False
    try:
        while True:
            if not overview_visible():
                was_visible = False
                time.sleep(POLL_INTERVAL)
                continue
            if not was_visible:
                was_visible = True
                show_recovery(ws_url_holder)
            r, _, _ = select.select([fd], [], [], 0.25)
            if not r:
                continue
            data = os.read(fd, FRAME_SIZE)
            if len(data) < FRAME_SIZE:
                continue
            _, _, ev_type, ev_code, ev_val = struct.unpack(FRAME_FMT, data)
            if ev_type != EV_KEY or ev_val != 1:  # press edges only
                continue
            if ev_code == KEY_LEFT_CODE:
                nav_step(ws_url_holder, "prev")
            elif ev_code == KEY_RIGHT_CODE:
                nav_step(ws_url_holder, "next")
            elif ev_code == KEY_ENTER_CODE:
                nav_step(ws_url_holder, "activate")
            elif ev_code == KEY_BACK_CODE:
                nav_step(ws_url_holder, "back")
    finally:
        os.close(fd)


def main() -> int:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    log("wheel shim up; waiting for diag overlay")
    holder: dict = {"url": None}
    try:
        scan_events(holder)
    except KeyboardInterrupt:
        log("bye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

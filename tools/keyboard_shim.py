#!/usr/bin/env python3
"""Wheel/key input adapter for the Hudiy Diagnostics overlay.

WHY THIS EXISTS
    Hudiy's control scheme navigates by key events (upstream README, "Supported
    Key Bindings"): scroll left/right are the keyboard keys ``1``/``2``,
    trigger is ``enter``, go back is ``escape``, focus moves are the arrow
    keys. Head-unit knobs and MCU button boards present themselves as exactly
    these kernel keys (the reference Elecrow/gen4-ESP32 knob emits
    KEY_1/KEY_2/KEY_ENTER/KEY_ESC). On builds where Hudiy does not deliver key
    events into a third-party overlay's webview (proven on the reference
    build, 2026-09-11: zero DOM keydowns, zero hudiy={} callbacks), this
    adapter reads the device at the kernel input layer and drives the page's
    own nav hook ``window.__diagKeyNav()`` over the QtWebEngine DevTools
    socket. While the overlay is hidden the adapter is inert -- it never
    touches Hudiy's native UI or the race-dash overlay.

WHAT IT READS (any device speaking Hudiy's navigation vocabulary)
    kernel key -> page step
      KEY_1 / KEY_UP / KEY_LEFT / KEY_SCROLLUP      -> prev      (scroll left)
      KEY_2 / KEY_DOWN / KEY_RIGHT / KEY_SCROLLDOWN -> next      (scroll right)
      KEY_ENTER / KEY_KPENTER / KEY_OK              -> activate  (trigger)
      KEY_ESC / KEY_BACK                            -> back      (go back)
    Mouse-style rotary encoders: REL_WHEEL / REL_HWHEEL (-1 = prev, +1 = next).
    The reference knob's per-direction capture (11 Sep 2026) is the subset
    KEY_1/KEY_2/KEY_ENTER/KEY_ESC.

DEVICE DISCOVERY
    ``DIAG_SHIM_DEVICE`` pins one device path; otherwise the adapter scans
    /dev/input/event* and picks the best candidate (name hints + capability
    scan -- see device_score). ``DIAG_SHIM_MATCH`` adds name substrings,
    ``DIAG_SHIM_EXCLUDE`` rejects them; run the script with ``--scan`` on any
    machine to see the candidates and the choice. ``DIAG_SHIM_DISABLE=1``
    exits immediately (installs that deliver input natively).

VISIBILITY
    Reads the diag control lane (127.0.0.1:44414/status). While the overlay is
    hidden the shim is inert.

RUNTIME
    Runs as the user with a systemd --user unit (hudiy-diag-keys). Reading
    /dev/input needs the `input` group: `sudo usermod -aG input $USER` (the
    installer prints this reminder) or a udev rule. Endpoints are
    env-overridable: DIAG_SHIM_LANE_STATUS (or DIAG_HTTP_PORT), DIAG_SHIM_CDP.
"""
from __future__ import annotations

import fcntl
import glob
import json
import os
import select
import signal
import struct
import sys
import time
import urllib.request

# --- tunables ---------------------------------------------------------------
EV_REL, EV_KEY = 0x02, 0x01
REL_WHEEL, REL_HWHEEL = 0x08, 0x0A

#: kernel key -> page step. Keys `1`/`2` are Hudiy's "scroll left/right"; the
#: arrows drive the same focus walk on our list UI.
KEY_STEPS = {
    2: "prev", 3: "next",                              # KEY_1, KEY_2
    103: "prev", 105: "prev",                          # KEY_UP, KEY_LEFT
    108: "next", 106: "next",                          # KEY_DOWN, KEY_RIGHT
    177: "prev", 178: "next",                          # KEY_SCROLLUP/DOWN
    28: "activate", 96: "activate", 352: "activate",   # ENTER, KPENTER, OK
    1: "back", 158: "back",                            # KEY_ESC, KEY_BACK
}
#: the rotary pair (keys `1`/`2`) -- a strong hint for device scoring.
ROTARY_CODES = {2, 3}
#: default name hints for auto-discovery (lower-case substrings).
MATCH_DEFAULT = ("encoder", "rotary", "knob", "elecrow", "mcu", "esp32", "stm32")

PINNED_DEVICE = os.environ.get("DIAG_SHIM_DEVICE")  # None = auto-detect
_LANE_PORT = os.environ.get("DIAG_HTTP_PORT", "44414")
LANE_STATUS = os.environ.get("DIAG_SHIM_LANE_STATUS",
                             f"http://127.0.0.1:{_LANE_PORT}/status")
CDP_URL = os.environ.get("DIAG_SHIM_CDP", "http://127.0.0.1:9222/json")
FRAME_FMT = "llHHI"
FRAME_SIZE = struct.calcsize(FRAME_FMT)
POLL_INTERVAL = 2.0          # visibility check cadence while inert
RESCAN_S = 10.0              # wait between device-discovery attempts


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


# --- device discovery -------------------------------------------------------
def _eviocgname(fd: int, size: int = 256) -> str:
    buf = bytearray(size)
    fcntl.ioctl(fd, (2 << 30) | (size << 16) | (ord("E") << 8) | 0x06, buf)
    return bytes(buf).split(b"\x00", 1)[0].decode("utf-8", "replace")


def _eviocgbits(fd: int, ev: int, size: int) -> bytearray:
    buf = bytearray(size)
    fcntl.ioctl(fd, (2 << 30) | (size << 16) | (ord("E") << 8) | (0x20 + ev), buf)
    return buf


def _bit(buf, code: int) -> bool:
    return code < len(buf) * 8 and bool((buf[code >> 3] >> (code & 7)) & 1)


def _env_list(name: str):
    raw = os.environ.get(name, "")
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def match_patterns():
    extra = _env_list("DIAG_SHIM_MATCH")
    return tuple(extra) if extra else MATCH_DEFAULT


def device_score(name: str, nav_codes, wheel: bool) -> int:
    """Heuristic score for one input device; 0 = not usable for navigation.

    Prefers devices whose name matches the hint list and that expose the
    rotary pair; down-ranks mice/touchscreens so a desktop pointer can never
    hijack the walk, and keyboards so they stay a fallback only.
    """
    if not nav_codes and not wheel:
        return 0
    lname = (name or "").lower()
    score = 10
    if len(nav_codes) >= 2:              # can walk a list both ways
        score += 20
    if wheel:
        score += 5
    if ROTARY_CODES.issubset(set(nav_codes)):
        score += 10
    for pat in match_patterns():
        if pat in lname:
            score += 100
            break
    if "mouse" in lname:
        score -= 80
    if "touch" in lname:
        score -= 80
    if "keyboard" in lname:
        score -= 25
    return max(score, 0)


def scan_devices():
    """All usable input devices, best first: [(score, path, name, nav, wheel)]."""
    exclude = _env_list("DIAG_SHIM_EXCLUDE")
    found = []
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue                      # not readable (permissions) - skip
        try:
            name = _eviocgname(fd)
            keybits = _eviocgbits(fd, EV_KEY, 96)
            relbits = _eviocgbits(fd, EV_REL, 2)
        except OSError:
            continue
        finally:
            os.close(fd)
        if any(x in name.lower() for x in exclude):
            continue
        nav = sorted(k for k in KEY_STEPS if _bit(keybits, k))
        wheel = _bit(relbits, REL_WHEEL) or _bit(relbits, REL_HWHEEL)
        score = device_score(name, nav, wheel)
        if score > 0:
            found.append((score, path, name, nav, wheel))
    found.sort(key=lambda item: (-item[0], item[1]))
    return found


def choose_device():
    """(path, why) for the device to read; (None, None) when nothing fits."""
    if PINNED_DEVICE:
        return PINNED_DEVICE, "pinned via DIAG_SHIM_DEVICE"
    found = scan_devices()
    if not found:
        return None, None
    score, path, name = found[0][:3]
    return path, f"{name!r} (score {score}, {len(found)} candidate(s))"


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


def classify(ev_type: int, ev_code: int, ev_val: int):
    """One kernel input event -> page step ('prev'|'next'|'activate'|'back')."""
    if ev_type == EV_KEY:
        if ev_val != 1:                  # press edges only
            return None
        return KEY_STEPS.get(ev_code)
    if ev_type == EV_REL and ev_code in (REL_WHEEL, REL_HWHEEL):
        if ev_val > 0:
            return "next"
        if ev_val < 0:
            return "prev"
    return None


def open_event_device() -> int:
    """Open a device speaking Hudiy's scheme; wait quietly when none exists."""
    logged = False
    while True:
        path, why = choose_device()
        if path:
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                log(f"reading {path} - {why}")
                dbg(f"device {path} - {why}")
                return fd
            except OSError as exc:
                if not logged:
                    log(f"cannot open {path}: {exc}; retrying")
                    logged = True
        elif not logged:
            log("no navigation input device found yet; waiting "
                "(set DIAG_SHIM_DEVICE to pin one)")
            logged = True
        time.sleep(RESCAN_S)


def _scan_fd(fd: int, ws_url_holder: dict) -> None:
    """Read events from one open device until it disappears (OSError)."""
    was_visible = False
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
        step = classify(ev_type, ev_code, ev_val)
        if step:
            nav_step(ws_url_holder, step)


def scan_events(ws_url_holder: dict) -> None:
    """Main loop: (re)open the best knob device and forward its events."""
    while True:
        fd = open_event_device()
        try:
            _scan_fd(fd, ws_url_holder)
        except OSError as exc:
            log(f"input device lost ({exc}); re-scanning")
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
        time.sleep(2.0)


def main() -> int:
    if os.environ.get("DIAG_SHIM_DISABLE"):
        log("disabled via DIAG_SHIM_DISABLE")
        return 0
    if "--scan" in sys.argv[1:]:
        print("input devices of interest (score, path, name, nav keys, wheel):")
        for score, path, name, nav, wheel in scan_devices():
            print(f"  {score:4d}  {path:16s}  {name!r}  nav={nav} wheel={wheel}")
        chosen, why = choose_device()
        print("would read:", chosen, "-", why)
        return 0
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

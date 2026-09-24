#!/usr/bin/env python3
"""Playwright smoke for the S11 Mode-04 clear flow (800x480, keyboard-led).

Serves the real page from a replay backend; mocks /scan (fast, with codes).
The happy path drives the REAL POST /clear; 400/409/502 + the slow timeout
stay mocked. Asserts the full two-step walk, knob/shim reachability, both
outcome states, the offline gate, the S11 ack-footer geometry + a real
touch-tap parity proof (t_ef0df5b1), and zero app console errors.
Screenshots land next to this script.

Run from the repo root:  python3 smoke/clear_smoke.py
Needs: replay backend on 127.0.0.1:44419
  python3 -m backend.server --mode replay \\
      --replay-fixtures smoke/replay_clear.json --port 44419
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "http://127.0.0.1:44419/app/diag.html?bridge=dom"

with open(os.path.join(HERE, "scan_codes.json"), encoding="utf-8") as fh:
    SCAN_CODES = fh.read()
with open(os.path.join(HERE, "scan_reread.json"), encoding="utf-8") as fh:
    SCAN_REREAD = fh.read()

CHECKS = []


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name
          + (" -- " + detail if detail and not cond else ""))


def focused_text(page):
    return page.evaluate(
        "(() => { const n = document.querySelector('.focused');"
        " return n ? n.textContent.trim().slice(0, 60) : null; })()")


def arrows_to(page, needle, limit=14):
    for _ in range(limit):
        if focused_text(page) and needle in focused_text(page):
            return True
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(80)
    return focused_text(page) and needle in focused_text(page)


def screen(page):
    return page.evaluate("document.body.getAttribute('data-screen')")


def ack_geometry(page):
    """Rects + hit-test points for the S11 fix-first gate (t_ef0df5b1)."""
    return page.evaluate("""(() => {
      const R = s => { const e = document.querySelector(s);
        if (!e) return null; const r = e.getBoundingClientRect();
        return {top: r.top, bottom: r.bottom, left: r.left, right: r.right}; };
      const b = document.querySelector('#clearFixFirst');
      const r = b ? b.getBoundingClientRect() : null;
      const pts = r ? [[r.left + r.width / 2, r.top + r.height / 2],
                       [r.left + 8, r.top + r.height / 2],
                       [r.right - 8, r.top + r.height / 2],
                       [r.left + r.width / 2, r.top + 8],
                       [r.left + r.width / 2, r.bottom - 8]] : [];
      const hits = pts.map(p => { const h = document.elementFromPoint(p[0], p[1]);
        return h ? (h.id || (h.tagName + '.' + h.className)) : null; });
      return {box: R('#clearFixFirst'), row: R('#clearAck .check-row'),
              statebar: R('#stateBar'), actions: R('#actions'), hits: hits,
              cx: r ? r.left + r.width / 2 : null,
              cy: r ? r.top + r.height / 2 : null};
    })()""")


def check_ack_geometry(page, stage):
    # t_ef0df5b1: the fix-first gate must sit fully visible in the S11 ack
    # footer (below the scroller, above the statebar) - never under an
    # overlay - both at initial open and after the keyboard walk. The old
    # layout failed this: checkbox y 379..401 vs scroller bottom 380 with
    # elementFromPoint hitting SPAN.state-chip, so touch taps never reached
    # the box. (The checkbox intentionally lives OUTSIDE .scroll now, so the
    # assertion is footer-placement, not scroller-containment.)
    g = ack_geometry(page)
    check("s11 ack (%s): row above statebar" % stage,
          g["row"] and g["statebar"]
          and g["row"]["bottom"] <= g["statebar"]["top"],
          repr(g["row"]))
    check("s11 ack (%s): row above actions bar" % stage,
          g["row"] and g["actions"]
          and g["row"]["bottom"] <= g["actions"]["top"],
          repr(g["row"]))
    check("s11 ack (%s): row inside 800x480" % stage,
          g["row"] and g["row"]["top"] >= 0 and g["row"]["bottom"] <= 480,
          repr(g["row"]))
    check("s11 ack (%s): hit test is the checkbox x5" % stage,
          g["hits"] and all(h == "clearFixFirst" for h in g["hits"]),
          repr(g["hits"]))
    return g


def txt(page, sel):
    el = page.query_selector(sel)
    return el.text_content() if el else ""


def submit_clear_and_read_toast(page):
    # The scan toast ("Scan finished...") lingers 5.2 s and the test walk is
    # faster than that: drain it first or the wait below matches stale text.
    page.wait_for_function(
        "document.querySelector('#toast').hidden === true", timeout=8000)
    page.keyboard.press("Enter")
    page.wait_for_function(
        "document.querySelector('#toast:not([hidden])')", timeout=8000)
    return txt(page, "#toast")


def reach_scan_results(page):
    """Keyboard-only: S0 -> scan -> S2 -> S3. Assumes /scan is mocked."""
    page.wait_for_function(
        "document.getElementById('s0State').textContent.includes('connected')",
        timeout=15000)
    # Fresh render paints .focused on the first control already (Start);
    # no arrow needed - and one ArrowDown would step onto Exit.
    check("s0 start focused", focused_text(page)
          and "Start health scan" in focused_text(page), focused_text(page))
    page.keyboard.press("Enter")
    page.wait_for_function(
        "document.body.getAttribute('data-screen')==='S2'", timeout=15000)
    if not arrows_to(page, "Fault codes"):
        check("find Fault codes tile", False, focused_text(page))
        return False
    page.keyboard.press("Enter")
    page.wait_for_function(
        "document.body.getAttribute('data-screen')==='S3'", timeout=8000)
    return True


def open_clear_screen(page):
    if not arrows_to(page, "Clear fault codes"):
        check("find Clear entry (online)", False, focused_text(page))
        return False
    page.keyboard.press("Enter")
    page.wait_for_function(
        "document.body.getAttribute('data-screen')==='S11'", timeout=8000)
    return True


def main():
    from playwright.sync_api import sync_playwright

    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # has_touch: the kiosk is a touch surface; the S11 parity proof taps
        # the real coordinates (t_ef0df5b1). Keyboard/mouse behaviour is
        # unchanged by the flag.
        ctx = browser.new_context(viewport={"width": 800, "height": 480},
                                  has_touch=True)
        state = {"scan_calls": 0, "clear_mode": "ok",
                 "saw_shake": False, "health_mode": "real",
                 "pending_clear": []}

        def on_health(route):
            if state["health_mode"] == "offline":
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(
                                  {"ok": True, "status": "ok",
                                   "obd": {"state": "offline",
                                           "reason": "link down in smoke",
                                           "host": {"hudiy_connected": False,
                                                    "source": "smoke"},
                                           "host_name": "smoke",
                                           "last_ok_age_s": 31.0}}))
            else:
                route.continue_()

        def on_scan(route):
            state["scan_calls"] += 1
            body = SCAN_CODES if state["scan_calls"] == 1 else SCAN_REREAD
            route.fulfill(status=200, content_type="application/json",
                          body=body)

        def on_clear(route):
            # 'live' lets the request reach the real backend (replay
            # fixture); 'hold' parks it unanswered so the working state
            # stays put (timeout path). Never sleep in a handler: a
            # blocking handler stalls this client's event loop and
            # distorts every later wait.
            mode = state["clear_mode"]
            if mode == "live":
                route.continue_()
                return
            if mode == "hold":
                state["pending_clear"].append(route)
                return
            try:
                if mode == "e400":
                    route.fulfill(status=400,
                                  content_type="application/json",
                                  body=json.dumps(
                                      {"ok": False, "status": "bad_request",
                                       "message": "confirm=yes is required"}))
                elif mode == "e409":
                    route.fulfill(status=409,
                                  content_type="application/json",
                                  body=json.dumps(
                                      {"ok": False, "status": "busy",
                                       "message": "a clear is already "
                                                  "running"}))
                else:
                    route.fulfill(status=502,
                                  content_type="application/json",
                                  body=json.dumps(
                                      {"ok": False,
                                       "status": "not_confirmed",
                                       "message": "ECU did not confirm the "
                                                  "reset"}))
            except Exception:
                pass  # client aborted (timeout path) - nothing to fulfil

        ctx.route("**/scan*", on_scan)
        ctx.route("**/clear*", on_clear)
        ctx.route("**/health*", on_health)

        def new_page(query=""):
            page = ctx.new_page()
            page.on("pageerror", lambda exc: errors.append("pageerror: %s"
                                                           % exc))
            def on_console(msg):
                if msg.type == "error" and "Failed to load resource" \
                        not in (msg.text or ""):
                    errors.append("console: %s" % msg.text)
            page.on("console", on_console)
            page.goto(BASE + query)
            return page

        # ---- scenario 1: full success walk, keyboard only ----
        # LIVE /clear against the replay backend (smoke/replay_clear.json:
        # Mode 03 pre-read holds P0401, Mode 04 answers 44). Error paths
        # below stay mocked.
        state.update(scan_calls=0, clear_mode="live", pending_clear=[])
        page = new_page()
        check("lands on S0", screen(page) == "S0", screen(page))
        if not reach_scan_results(page):
            print("ABORT: cannot reach S3")
        elif not open_clear_screen(page):
            print("ABORT: cannot open S11")
        else:
            head = txt(page,"#clearCard .verdict-headline")
            check("screen1 headline counts codes",
                  head and "Clear 3 fault codes?" in head, head)
            items = page.query_selector_all("#clearCard .clear-list li")
            check("screen1 lists 4 consequences", len(items) == 4,
                  "got %d" % len(items))
            body_text = txt(page,"#clearCard")
            for needle in ("freeze-frame", "Not ready",
                           "60 to 90 minutes", "fuel trims",
                           "straight back"):
                check("screen1 consequence: %s" % needle,
                      needle in body_text)
            check("screen1 permanent honesty line",
                  "cannot be erased by any scan tool" in body_text)
            check("screen1 names the codes",
                  "This reset erases: P0301" in txt(page,"#clearWrap")
                  and "P0401" in txt(page,"#clearWrap")
                  and "P0420" in txt(page,"#clearWrap"),
                  txt(page,"#clearWrap")[-200:])
            check("no battery-disconnect advice",
                  not any(adv in body_text.lower() for adv in
                          ("try disconnect", "disconnect the battery to",
                           "or disconnect the", "instead, disconnect")))
            clear_btn = page.query_selector(
                "#actions button.btn-danger")
            check("clear-now gated while unchecked",
                  clear_btn and clear_btn.is_disabled())
            box = page.query_selector("#clearFixFirst")
            check("fix-first starts unchecked",
                  box and not box.is_checked())
            page.screenshot(path=os.path.join(HERE, "clear-screen1.png"))

            # t_ef0df5b1 parity proof, initial-open state: geometry first,
            # then a REAL touch tap on the coordinates (not a click()). The
            # second tap restores unchecked so the keyboard walk below starts
            # exactly where it used to.
            g0 = check_ack_geometry(page, "initial-open")
            page.touchscreen.tap(g0["cx"], g0["cy"])
            page.wait_for_timeout(250)
            check("touch tap toggles the checkbox",
                  page.query_selector("#clearFixFirst").is_checked())
            check("touch tap enables Clear now",
                  not page.query_selector(
                      "#actions button.btn-danger").is_disabled())
            page.touchscreen.tap(g0["cx"], g0["cy"])
            page.wait_for_timeout(250)
            check("touch tap toggles back off",
                  not page.query_selector("#clearFixFirst").is_checked())

            # knob/shim reachability over the same DOM. Clear-now is gated
            # (disabled skips the ring, like every disabled control), so
            # check the box first, then walk: all three stops must appear.
            page.keyboard.press("Space")  # checkbox is focused from load
            page.wait_for_timeout(200)
            check("pre-check via keyboard",
                  page.query_selector("#clearFixFirst").is_checked())
            seen = page.evaluate(
                "(() => { const out = [];"
                " for (let i = 0; i < 8; i++) {"
                " window.__diagKeyNav('next');"
                " const n = document.querySelector('.focused');"
                " out.push(n ? (n.textContent || n.id || n.tagName)"
                " .trim().slice(0, 40) : null); } return out; })()")
            joined = " | ".join(s or "?" for s in seen)
            check("shim reaches checkbox", any("codes will return" in s
                                               for s in seen), joined)
            check("shim reaches back", any("Back to codes" in s
                                           for s in seen), joined)
            check("shim reaches clear-now", any("Clear now" in s
                                                for s in seen), joined)
            # shim 'activate' on the label row toggles the box (the label
            # is the single .ctl stop; label.click() forwards to input).
            page.evaluate("(() => { for (let i = 0; i < 8; i++) {"
                          " window.__diagKeyNav('next');"
                          " const n = document.querySelector('.focused');"
                          " if (n && n.textContent.includes("
                          "'codes will return')) {"
                          " window.__diagKeyNav('activate'); break; } } })()")
            page.wait_for_timeout(200)
            check("shim toggles checkbox",
                  not page.query_selector("#clearFixFirst").is_checked())
            # re-check via keyboard for the submit half of the walk
            page.keyboard.press("Space")
            page.wait_for_timeout(200)

            # keyboard submit half: the box is checked again, focus sits on
            # the row - walk to it explicitly, assert, then submit.
            if not arrows_to(page, "codes will return"):
                check("keyboard finds checkbox", False)
            else:
                check("box checked for submit",
                      page.query_selector("#clearFixFirst").is_checked())
                check("clear-now enables",
                      not page.query_selector(
                          "#actions button.btn-danger").is_disabled())
                # t_ef0df5b1 parity proof, post keyboard-walk state: the gate
                # must still be fully visible and touch-tappable.
                check_ack_geometry(page, "post-walk")
                if not arrows_to(page, "Clear now"):
                    check("keyboard finds Clear now", False)
                else:
                    page.keyboard.press("Enter")
                    # The live backend answers in ~0.5 s: read the spinner
                    # immediately (one round-trip) instead of racing a wait.
                    check("working shows spinner", page.evaluate(
                        "!!document.querySelector('#clearWrap"
                        " .scan-mark.is-busy')"))
                    page.wait_for_selector(
                        "#clearWrap .scan-mark.is-done", timeout=12000)
                    check("success morphs to check", True)
                    follow = txt(page,"#clearWrap")
                    check("live pre-read counted",
                          "1 code(s) held before the reset" in follow,
                          follow[:200])
                    check("live duration shown",
                          "confirmed in" in follow)
                    check("followup message shown",
                          "monitors reset; drive cycle needed" in follow)
                    check("afterClear copy wired",
                          "must prove itself healthy again" in follow)
                    check("server permanent note shown",
                          "cannot be cleared by any tool" in follow)
                    page.wait_for_function(
                        "document.querySelector('#clearWrap')"
                        ".textContent.includes('Readiness re-read')",
                        timeout=15000)
                    reread = txt(page,"#clearWrap")
                    check("auto reread lands inline",
                          "0 stored code(s)" in reread
                          and "2 monitor(s) Not ready" in reread, reread[-160:])
                    page.screenshot(path=os.path.join(
                        HERE, "clear-success.png"))
            # done-stage buttons work by keyboard
            if not arrows_to(page, "Readiness wall"):
                check("keyboard finds wall button", False,
                      focused_text(page))
            else:
                page.keyboard.press("Enter")
                page.wait_for_function(
                    "document.body.getAttribute('data-screen')==='S5'",
                    timeout=8000)
                check("wall opens post-clear",
                      screen(page) == "S5", screen(page))
        page.close()

        # ---- scenario 2: 502 failure -> shake + server message ----
        state.update(scan_calls=0, clear_mode="e502", pending_clear=[])
        page = new_page()
        reach_scan_results(page) and open_clear_screen(page)
        arrows_to(page, "codes will return")
        page.keyboard.press("Space")
        page.wait_for_timeout(150)
        arrows_to(page, "Clear now")
        toast = submit_clear_and_read_toast(page)
        check("502 surfaces server message",
              "ECU did not confirm the reset" in toast, toast)
        shook = False
        for _ in range(20):
            cls = page.evaluate("(() => { const c = document.querySelector"
                                "('#clearCard'); return c ? c.className : ''"
                                " })()")
            if "shake-once" in cls:
                shook = True
                break
            page.wait_for_timeout(50)
        check("502 shakes the confirm card", shook)
        check("502 stays on confirm",
              screen(page) == "S11"
              and "Clear 3 fault codes?" in
              txt(page,"#clearCard .verdict-headline"))
        page.wait_for_timeout(600)  # let the shake settle
        settled = page.evaluate(
            "(() => { const c = document.querySelector('#clearCard');"
            " return c ? getComputedStyle(c).transform : '' })()")
        check("shake settles clean", settled in ("none", ""),
              settled)
        page.screenshot(path=os.path.join(HERE, "clear-failure.png"))
        page.close()

        # ---- scenario 3: 409 contention -> toast only, no shake ----
        state.update(scan_calls=0, clear_mode="e409", pending_clear=[])
        page = new_page()
        reach_scan_results(page) and open_clear_screen(page)
        arrows_to(page, "codes will return")
        page.keyboard.press("Space")
        page.wait_for_timeout(150)
        arrows_to(page, "Clear now")
        check("409 toast names contention",
              "already running" in submit_clear_and_read_toast(page))
        page.wait_for_timeout(700)
        cls = page.evaluate("(() => { const c = document.querySelector"
                            "('#clearCard'); return c ? c.className : ''"
                            " })()")
        check("409 does not shake", "shake-once" not in cls, cls)
        page.close()

        # ---- scenario 4: 400 -> shake + message ----
        state.update(scan_calls=0, clear_mode="e400", pending_clear=[])
        page = new_page()
        reach_scan_results(page) and open_clear_screen(page)
        arrows_to(page, "codes will return")
        page.keyboard.press("Space")
        page.wait_for_timeout(150)
        arrows_to(page, "Clear now")
        check("400 toast carries message",
              "confirm=yes is required" in submit_clear_and_read_toast(page))
        page.close()

        # ---- scenario 5: slow timeout path ----
        state.update(scan_calls=0, clear_mode="hold", pending_clear=[])
        page = new_page("&clearTimeoutMs=1200")
        reach_scan_results(page) and open_clear_screen(page)
        arrows_to(page, "codes will return")
        page.keyboard.press("Space")
        page.wait_for_timeout(150)
        arrows_to(page, "Clear now")
        check("timeout toast is honest",
              "timed out" in submit_clear_and_read_toast(page))
        check("timeout returns to confirm",
              "Clear 3 fault codes?" in
              txt(page,"#clearCard .verdict-headline"))
        page.close()

        # ---- scenario 6: offline lane gates the entry ----
        state.update(scan_calls=0, clear_mode="e502", pending_clear=[],
                     health_mode="offline")
        page = new_page()
        page.wait_for_function(
            "document.getElementById('s0State').textContent"
            ".includes('not answering')", timeout=15000)
        check("offline shows on S0",
              "not answering" in txt(page, "#s0State"))
        # Scan mock still answers (offline is about the live lane, and the
        # entry gate reads the lane, not the cached report).
        page.keyboard.press("Enter")
        page.wait_for_function(
            "document.body.getAttribute('data-screen')==='S2'",
            timeout=15000)
        arrows_to(page, "Fault codes")
        page.keyboard.press("Enter")
        page.wait_for_function(
            "document.body.getAttribute('data-screen')==='S3'",
            timeout=8000)
        dis = page.evaluate(
            "(() => { const bs = Array.from(document.querySelectorAll"
            "('#actions button')); const b = bs.find(x => x.textContent"
            ".includes('Clear fault codes')); return b ? b.disabled :"
            " 'missing'; })()")
        check("offline gate: clear entry disabled", dis is True,
              repr(dis))
        state["health_mode"] = "real"
        page.close()
        browser.close()

    check("zero app console/page errors", not errors, "; ".join(errors[:5]))
    failed = [c for c in CHECKS if not c[1]]
    print("\n==== %d/%d checks passed ====" % (len(CHECKS) - len(failed),
                                              len(CHECKS)))
    for name, ok, detail in CHECKS:
        if not ok:
            print("FAILED: %s %s" % (name, detail))
    sys.exit(1 if failed or errors else 0)


if __name__ == "__main__":
    main()

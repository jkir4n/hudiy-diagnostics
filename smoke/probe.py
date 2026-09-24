#!/usr/bin/env python3
"""Probe: walk to S11, check the box, dump focus state, press Enter."""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "http://127.0.0.1:44419/app/diag.html?bridge=dom"

with open(os.path.join(HERE, "scan_codes.json"), encoding="utf-8") as fh:
    SCAN_CODES = fh.read()


def focused(page):
    return page.evaluate(
        "(() => { const n = document.querySelector('.focused');"
        " return n ? n.textContent.trim().slice(0, 50) : null; })()")


def main():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 480})
        page.route("**/scan*",
                   lambda r: r.fulfill(status=200,
                                       content_type="application/json",
                                       body=SCAN_CODES))
        page.route("**/clear*",
                   lambda r: None)  # park forever: client must time out
        page.on("pageerror", lambda e: print("PAGEERROR:", e))
        page.goto(BASE + "&clearTimeoutMs=1200")
        page.wait_for_function(
            "document.getElementById('s0State').textContent"
            ".includes('connected')", timeout=15000)
        print("s0 focused:", focused(page))
        page.keyboard.press("Enter")
        page.wait_for_function(
            "document.body.getAttribute('data-screen')==='S2'",
            timeout=15000)
        for _ in range(14):
            if focused(page) and "Fault codes" in focused(page):
                break
            page.keyboard.press("ArrowDown")
        print("s2 focused:", focused(page))
        page.keyboard.press("Enter")
        page.wait_for_function(
            "document.body.getAttribute('data-screen')==='S3'",
            timeout=8000)
        for _ in range(14):
            if focused(page) and "Clear fault codes" in focused(page):
                break
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(60)
        print("s3 focused:", focused(page))
        page.keyboard.press("Enter")
        page.wait_for_function(
            "document.body.getAttribute('data-screen')==='S11'",
            timeout=8000)
        print("s11 focused:", focused(page))
        print("box checked:", page.query_selector("#clearFixFirst")
              .is_checked())
        page.keyboard.press("Space")
        page.wait_for_timeout(300)
        print("after space, box:", page.query_selector("#clearFixFirst")
              .is_checked())
        print("after space, focused:", focused(page))
        # exact smoke sequence: shim walk, shim activate, space, arrows
        page.evaluate("(() => { for (let i = 0; i < 8; i++)"
                      " window.__diagKeyNav('next'); })()")
        print("after shim walk, focused:", focused(page))
        page.evaluate("(() => { for (let i = 0; i < 8; i++) {"
                      " window.__diagKeyNav('next');"
                      " const n = document.querySelector('.focused');"
                      " if (n && n.textContent.includes('codes will return'))"
                      " { window.__diagKeyNav('activate'); break; } } })()")
        page.wait_for_timeout(200)
        print("after shim activate, box:", page.query_selector(
            "#clearFixFirst").is_checked())
        page.keyboard.press("Space")
        page.wait_for_timeout(200)
        print("after space2, box:", page.query_selector("#clearFixFirst")
              .is_checked(), "focused:", focused(page),
              "S.focus:", page.evaluate("window.__DIAG.focus"))
        for _ in range(8):
            if focused(page) and focused(page) == "Clear now":
                break
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(60)
        print("pre-enter focused:", focused(page))
        dis = page.evaluate(
            "(() => { const b = Array.from(document.querySelectorAll"
            "('#actions button')).find(x => x.textContent.includes"
            "('Clear now')); return b ? {dis: b.disabled,"
            " cls: b.className} : 'missing'; })()")
        print("clear btn:", dis)
        print("stage before:", page.evaluate("window.__DIAG.clear &&"
                                             " window.__DIAG.clear.stage"),
              "busy:", page.evaluate("window.__DIAG.clearBusy"))
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
        print("stage after:", page.evaluate("window.__DIAG.clear &&"
                                            " window.__DIAG.clear.stage"),
              "busy:", page.evaluate("window.__DIAG.clearBusy"))
        print("timedOut flag:", page.evaluate("window.__DIAG.clear &&"
                                              " window.__DIAG.clear.timedOut"))
        print("timeoutMs:", page.evaluate(
            "window.location.search"))
        page.wait_for_timeout(2500)
        print("stage late:", page.evaluate("window.__DIAG.clear &&"
                                           " window.__DIAG.clear.stage"))
        print("toast:", page.evaluate(
            "(() => { const t = document.querySelector('#toast');"
            " return t ? (t.hidden + '|' + t.textContent) : 'NO TOAST';"
            " })()"))
        print("mark html:", page.evaluate(
            "(() => { const m = document.querySelector('#clearWrap"
            " .scan-mark'); return m ? m.className : 'NO MARK'; })()"))
        print("clearwrap head:", page.evaluate(
            "document.querySelector('#clearWrap').innerHTML.slice(0, 300)"))
        browser.close()


main()

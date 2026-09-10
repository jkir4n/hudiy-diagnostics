# Hudiy Diagnostics - frontend (overlay page)

The whole UI is one overlay page: an 800x480 surface Hudiy can show on top of
whatever the head unit is doing. It talks to the diagnostics lane over HTTP and
ships no framework, no build step and no node_modules - three static files served
by the lane itself.

    frontend/diag.html          the nine screens (S0-S8), empty shells filled by JS
    frontend/diag.css           the 800x480 kiosk skin
    frontend/diag.js            input engine, data layer, renderers
    frontend/hudiy/             Hudiy registration fragments + merge script + note

## Running it

The backend lane serves the page; nothing else is needed.

    DIAG_MODE=replay DIAG_REPLAY_FIXTURES=fixtures/round1_full_capture.json \
        DIAG_HTTP_PORT=44414 python3 -m backend.server
    # then:  http://127.0.0.1:44414/app/diag.html

`/app/<path>` maps to `frontend/<path>` (read-only, traversal-safe, in
`backend/server.py`). Replay mode is the honest way to develop: `/scan` returns
the captured round-1 fixture, so the UI is exercised against real ECU bytes
without touching the car.

An overlay in Hudiy is a normal browser page, so the development loop is a
browser on the same network. `?bridge=dom` forces keyboard navigation when the
page is *not* inside Hudiy (the bridge is absent there), and `?bridge=bridge`
forces it the other way; without a parameter the page auto-detects. The choice is
remembered in `localStorage` and can be flipped on screen S8.

## Screens

    S0  home            link state + the four tiles, disabled until a scan exists
    S1  scanning        section-by-section progress, elapsed timer, cancel
    S2  health summary  verdict, MIL, fault counts, the four tiles
    S3  fault codes     tabs: stored / pending / permanent
    S4  code detail     one code: decoded text, severity, freeze-frame status
    S5  readiness       monitor wall + "how to complete them" guidance
    S6  monitor tests   Mode 06 test results, raw-value toggle
    S7  vehicle         VIN, calibration IDs, ECU name, identifier support
    S8  report          text / csv / json + download, and the settings block

S3, S5, S6, S7 and S8 are tabs off S2 because 800x480 has no room for a nav rail.

## Input parity (V1_SPEC rule 6)

Every action on every screen is reachable three ways: touch, the Hudiy control
bridge, and a browser key fallback for development. Nothing is reachable by one
input only.

| Screen | Action | Touch | Bridge callback | Keys (fallback) |
|---|---|---|---|---|
| all | move ring | tap a control (ring follows) | `onMoveToNextControl` / `onMoveToPreviousControl` | `ArrowDown` / `ArrowUp`, `Tab` |
| all | activate | tap | `onTriggered` | `Enter`, `Space` |
| all | back / leave | swipe right | `onGoBack` | `Escape`, `Backspace` |
| all | next / previous tab | swipe left (S3, S8) | `onGoRight` / `onGoLeft` | `ArrowRight` / `ArrowLeft` |
| S0 | start scan | footer button, or the "Start scan" tile | move + `onTriggered` | move + `Enter` |
| S1 | cancel scan | footer button only (it stays focused) | move + `onTriggered` | `Enter` on it |
| S2 | open S3/S5/S6/S7 | tap a tile | move + `onTriggered` | move + `Enter` |
| S3 | switch stored/pending/permanent | tap tab | `onGoLeft` / `onGoRight` | `ArrowLeft` / `ArrowRight` |
| S3 | open a code | tap row | move + `onTriggered` | move + `Enter` |
| S4 | next / previous code in the tab | footer buttons | `onGoLeft` / `onGoRight` | `ArrowLeft` / `ArrowRight` |
| S5 | show/hide drive-cycle guidance | tap the toggle | move + `onTriggered` | move + `Enter` |
| S6 | raw values on/off | tap the toggle | move + `onTriggered` | move + `Enter` |
| S7 | decode VIN online / offline | footer button | move + `onTriggered` | move + `Enter` |
| S8 | text / csv / json | tap tab | `onGoLeft` / `onGoRight` | `ArrowLeft` / `ArrowRight` |
| S8 | download, scope, bridge mode | tap | move + `onTriggered` | move + `Enter` |

Bridge details:

* `onMoveToNextControl` returns `false` at the end of a list, so Hudiy can take
  the press back (focus leaves the overlay) instead of trapping it. Inside a
  scrollable list it consumes the press and scrolls.
* `onGoBack` returns `false` on S0, which is what lets BACK leave the overlay.
  A vertical swipe scrolls a list; a horizontal swipe right is BACK.
* Both `onMoveToNextControl`/`onMoveToPreviousControl` and `onGoLeft`/`onGoRight`
  are wired, because which one a rotary knob sends is a bench question - the
  page does not care, and neither should the installer.
* The key fallback is inert while the page is running inside Hudiy
  (`bridge` mode and attached): Hudiy owns the keys there, and a second handler
  would double-step the ring.
* The focus ring is only painted once a key or the knob is used, and touch hides
  it again - a touch user never sees a ring they did not ask for.

## Colours carry one meaning only

Severity colours are the colour-blind-safe Okabe-Ito set, and the mapping is
fixed page-wide: green `#009E73` ok, amber `#E69F00` caution, vermilion
`#D55E00` fault, blue `#56B4E9` information, cyan `#0072B2` accents. Nothing else
in the UI is coloured, so a tinted row always means "look here".

Fault severity is a UI heuristic and is labelled as such: the ECU does not give
a severity byte, so the page derives it from the code class, the code category
and the MIL state (see `severityOf()` in `diag.js`):

* permanent (Mode 0A) -> amber, "cannot be cleared by any tool"
* pending -> blue, "the ECU is watching for a repeat"
* stored with MIL on -> vermilion
* stored with MIL off -> amber
* misfire classes (P030x-P03xx) with MIL on -> vermilion plus the catalyst
  warning, because a misfire can damage the catalyst

Readiness verdicts are *not* invented: when the ECU does not answer enough for a
verdict the page says exactly that ("The ECU did not report enough for a
readiness verdict") instead of guessing, and every verdict carries the line that
readiness rules differ by country and model year, so it is not an inspection
result. Never say ready when the ECU does not answer.

## Known gaps (bench items, not code gaps)

* Getting the overlay on screen from the menu action is unproven - see
  `frontend/hudiy/README.md`. The page needs nothing for either path.
* Readiness and Mode 06 screens render whatever the ECU reports; the reference
  car answers neither Mode 02 nor Mode 0A in a useful way, so the empty-state
  copy is the state that was actually verified.
* Decoding a VIN online needs outbound internet; the page defaults to the
  offline decode and treats "no internet" as information, never as an error.

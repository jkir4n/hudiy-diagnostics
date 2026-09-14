# Hudiy Keyboard / D-pad Control Scheme (upstream-verified)

Status: research COMPLETE (10 Sep, from the authoritative `wiboma/hudiy` repo itself
- `api/Api.proto`, `examples/gpio/KeyStrokes.py`, `examples/api/python/KeyStrokes.py`,
`examples/template.html`, `examples/input_scope.html`). Device-level verification (keys
actually reaching our overlay page) is owed by the frontend card's bench test.

## 1. The hardware key vocabulary (`Api.proto` `KeyType` enum)

| Key | Value | Meaning |
|---|---|---|
| UP / DOWN / LEFT / RIGHT | 1-4 | d-pad navigation |
| SCROLL_LEFT / SCROLL_RIGHT | 5-6 | rotary-encoder rotation (the knob) |
| ENTER | 7 | activate / press |
| BACK | 8 | back out |
| HOME | 9 | jump home |
| ANSWER_CALL / PHONE_MENU / HANGUP_CALL | 10-12 | phone |
| PLAY / TOGGLE_PLAY / PAUSE / STOP / PREVIOUS_TRACK / NEXT_TRACK | 13-18 | media |
| MEDIA_MENU / NAVIGATION_MENU / VOICE_COMMAND | 19-21 | menus / voice |
| **TOGGLE_INPUT_FOCUS** | **23** | toggles whether the PAGE or Hudiy's native UI holds input focus |

**Device note (11 Sep, device-observed):** on our head unit the scroll
wheel appears to dispatch **1 and 2** (UP/DOWN semantics) rather than 5-6
(SCROLL_*) - or the wheel's keypresses are translated UP/DOWN somewhere before
the webview. Unresolved until the CDP probe on the overlay webview shows which
key types actually arrive; the page handles both shapes (scroll pairs drive the
same focus walk).

`KeyEvent` messages (UP/DOWN/LEFT/RIGHT/ENTER/BACK/SCROLL_*) are `client->Hudiy`
**injection**: a GPIO controller (upstream `examples/gpio/KeyStrokes.py`) sends
PRESS and RELEASE events for every physical button and every encoder step over
TCP 44405. A physical-keyboard path would arrive the same way (or as Wayland key
events - device trial decides). Either way, the PAGE sees them through the same
contract below.

## 2. The in-page control contract (`hudiy = {}` bridge)

Hudiy does **not** deliver d-pad navigation to pages as raw DOM `keydown`
events. Pages receive it through the `hudiy` JS bridge object (proven by
upstream `examples/template.html` - the canonical widget template - and
`examples/input_scope.html`):

**State fields (read-only, pushed by Hudiy):**
- `hudiy.inputFocus` - the page currently holds input focus
- `hudiy.activated` - the page is the active control target
- `hudiy.colorScheme` - theme palette (`surfaceContainer`, `outline`, ...)

**Callbacks the page must implement:**
| Callback | Fires when | Contract |
|---|---|---|
| `onAttached` | page loaded | re-read initial state |
| `onInputFocusChanged` | `inputFocus` toggled | show/hide focus affordances |
| `onActivatedChanged` | `activated` toggled | enable/disable interaction visuals |
| `onMoveToNextControl` | DOWN (or forward nav) | move focus ring to next control; **return `true` if consumed, `false` if at the last control** (Hudiy then handles it, e.g. scrolls) |
| `onMoveToPreviousControl` | UP (or back nav) | same contract in reverse |
| `onTriggered` | ENTER | activate the focused control |
| `onGoLeft` / `onGoRight` | LEFT / RIGHT | horizontal nav (input_scope flashes an edge highlight) |
| `onGoBack` | BACK | page handles back; **return `true` if consumed, `false` to let Hudiy process BACK itself** (e.g. leave the overlay) |
| `onColorSchemeChanged` | theme change | re-render colors |

The `input_scope.html` example demonstrates the full loop: 4 squares, focus ring
drawn via `hudiy.colorScheme.outline` only when `inputFocus && activated`,
DOWN/UP walk the ring via `onMoveTo(Next|Previous)Control` with true/false
consumption, ENTER pulses the focused square via `onTriggered`, BACK reports
consumed via `onGoBack` return value.

`go_back.html` / `go_back_web.html` / `go_forward_web.html` additionally expose
`hudiy.api` for programmatic webview history (back/forward within the page's own
browsing session).

## 3. What this means for the diagnostics app (corrects V1_SPEC rule 6's wording)

- Our overlay page must implement the **bridge contract**, not just DOM key
  listeners: `onMoveToNextControl`/`onMoveToPreviousControl`/`onTriggered`/
  `onGoBack`/`onGoLeft`/`onGoRight` + focus-ring rendering driven by
  `hudiy.inputFocus`/`hudiy.activated`.
- Consumption semantics are load-bearing: returning `false` from
  `onMoveToNextControl` at the last control hands control back to Hudiy
  (scroll); returning `false` from `onGoBack` lets BACK leave the overlay
  (exactly the knob-always-wins behavior the UI-API inventory's idle rule
  demands).
- The focus ring must render from `hudiy.colorScheme` (theme-aware, the same
  palette the native UI uses).
- Keyboard-nav-keys from any source (BT keyboard, GPIO d-pad, remote) converge
  on this contract - one implementation serves all.
- Touch still works in parallel (bridge is additive; `input_scope` touches
  nothing).
- **Device trial item for the frontend card:** confirm a custom-overlay page
  (not a dashboard widget) receives these bridge callbacks on our Hudiy build -
  template.html/input_scope.html ship as *dashboard widget* examples; overlay
  behavior is presumed identical but unproven until tested. Fallback if the
  overlay lacks the bridge: DOM `keydown` listener (the Wayland webview receives
  real key events from the keyboard; the race-dash toggle's shortcut path proves
  system keys flow).

## 4. Sources

- `wiboma/hudiy` `api/Api.proto` (KeyType enum, KeyEvent message) - enum verified
  11 Sep: UP=1 DOWN=2 LEFT=3 RIGHT=4 SCROLL_LEFT=5 SCROLL_RIGHT=6 ENTER=7 BACK=8
  HOME=9 ... TOGGLE_INPUT_FOCUS=23
- `wiboma/hudiy` `examples/gpio/KeyStrokes.py` (physical d-pad + encoder ->
  KeyEvent injection; the knob = SCROLL_LEFT/SCROLL_RIGHT)
- `wiboma/hudiy` `examples/api/python/KeyStrokes.py` (full key-type list)
- `wiboma/hudiy` `examples/template.html` (canonical bridge skeleton, all 9 callbacks)
- `wiboma/hudiy` `examples/input_scope.html` (canonical focus-ring reference implementation)
- `wiboma/hudiy` `examples/api/js/go_back*.html` (hudiy.api webview history)
- hudiy.eu was geo-blocked from this network (country-block page); the upstream
  repo is the same upstream that ships the car's Hudiy build, so it is treated
  as authoritative.

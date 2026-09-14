# Hudiy Keyboard / D-pad Control Scheme (upstream-verified)

Status: research COMPLETE (10 Sep, from the authoritative `wiboma/hudiy` repo itself
- `api/Api.proto`, `examples/gpio/KeyStrokes.py`, `examples/api/python/KeyStrokes.py`,
`examples/template.html`, `examples/input_scope.html`). Device-level verification ran 11 Sep: on our build **no key events reach a
third-party overlay webview** - the input adapter (`tools/keyboard_shim.py`,
generalized in section 4) covers it.

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

**Device note (resolved 14 Sep):** the wheel emits the **keyboard keys `1`
and `2`** (kernel KEY_1/KEY_2) - which is exactly Hudiy's scheme: its README
binds `1`/`2` to *scroll left / scroll right* (the KeyType SCROLL_* values 5/6
are the API-injection vocabulary, not the physical-key vocabulary). The center
press is `enter` (KEY_ENTER), back is `escape` (KEY_ESC). The 11 Sep CDP probe
then showed no key events reach a third-party overlay webview on this build;
the page-side fallback for that is the input adapter (section 4).

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
- **Device trial (11 Sep, done):** a custom-overlay page receives **no** key
  events on our build - zero DOM keydowns, zero bridge callbacks, `inputFocus`/
  `activated` stay false. The bridge callbacks remain implemented (the right
  thing on any Hudiy where delivery works); on this build the page is driven by
  `tools/keyboard_shim.py` (the input adapter, section 4), which fires the same
  navigation functions the callbacks use.

## 4. Generalizing for any Hudiy install (14 Sep 2026)

Hudiy's navigation is one scheme, and every supported input form speaks it:

| Hudiy action | API key type | Upstream key binding | Kernel representation |
|---|---|---|---|
| scroll left | SCROLL_LEFT (5) | key `1` | KEY_1 (2) |
| scroll right | SCROLL_RIGHT (6) | key `2` | KEY_2 (3) |
| trigger | ENTER (7) | `enter` | KEY_ENTER (28) |
| go back | BACK (8) | `escape` | KEY_ESC (1) |
| focus moves | UP/DOWN/LEFT/RIGHT (1-4) | arrow keys | KEY_UP/DOWN/LEFT/RIGHT (103/108/105/106) |

- External input (GPIO d-pads, MCU knobs) joins Hudiy through **KeyEvent
  injection** over TCP 44405 (upstream `examples/gpio/KeyStrokes.py`; the
  volume variants use `DispatchAction`).
- The physical keys and the API key types are two vocabularies of the same
  scheme. Our adapter (`tools/keyboard_shim.py`) reads the physical layer and
  accepts **any device speaking that vocabulary** - plus the conventional
  extras KEY_SCROLLUP/DOWN, KEY_KPENTER/KEY_OK, KEY_BACK and mouse-style
  `REL_WHEEL`/`REL_HWHEEL` encoders - normalizing all of them to the page's
  prev/next/activate/back.
- Device auto-discovery (name hints + capability scan) replaces the fixed
  `/dev/input/event4`: `DIAG_SHIM_DEVICE` pins a path, `DIAG_SHIM_MATCH` /
  `DIAG_SHIM_EXCLUDE` tune the scan, `python3 tools/keyboard_shim.py --scan`
  prints the candidates on any machine, and `DIAG_SHIM_DISABLE=1` turns the
  adapter off entirely (for installs where Hudiy delivers input natively).
- Related Hudiy settings (upstream `main_configuration.md`):
  `handleKeyboardEvents` (keyboard listening; API injection unaffected),
  `activeBoundaries` (scrolling at scope edges jumps between scopes), and
  `splitWithProjections` for the focus toggle (`t` /
  KEY_TYPE_TOGGLE_INPUT_FOCUS).
- Input coverage in the app - no app-specific scheme, input follows the user:

  | User has | Works via | Extra needed |
  |---|---|---|
  | Touchscreen | native Chromium touch (tap moves the ring + activates) | no |
  | Mouse | click; wheel = the same focus walk (scrollable regions keep native scrolling) | no |
  | Keyboard (Hudiy-routed) | Hudiy's bridge callbacks (`onMoveToNextControl` etc.) | no |
  | Knob / remote / GPIO (Hudiy-routed) | the same bridge callbacks | no |
  | Any of the above on a build that does NOT deliver to overlays | `tools/keyboard_shim.py` fallback (auto-discovers the device, yields when the page holds native focus, `DIAG_SHIM_DISABLE=1` turns it off) | ships in the one-line install |

- One-line install (`install-bootstrap.sh` → `backend/deploy/install.sh`) adds
  only our own files and registers the overlay + menu entry through Hudiy's own
  config files (`frontend/hudiy/merge_config.py`); nothing Hudiy-specific is
  bundled.

## 5. Sources

- `wiboma/hudiy` `api/Api.proto` (KeyType enum, KeyEvent message) - enum verified
  11 Sep: UP=1 DOWN=2 LEFT=3 RIGHT=4 SCROLL_LEFT=5 SCROLL_RIGHT=6 ENTER=7 BACK=8
  HOME=9 ... TOGGLE_INPUT_FOCUS=23
- `wiboma/hudiy` `examples/gpio/KeyStrokes.py` (physical d-pad + encoder ->
  KeyEvent injection; the knob = SCROLL_LEFT/SCROLL_RIGHT)
- `wiboma/hudiy` `examples/api/python/KeyStrokes.py` (full key-type list)
- `wiboma/hudiy` `examples/template.html` (canonical bridge skeleton, all 9 callbacks)
- `wiboma/hudiy` `examples/input_scope.html` (canonical focus-ring reference implementation)
- `wiboma/hudiy` `examples/api/js/go_back*.html` (hudiy.api webview history)
- `wiboma/hudiy` `README.md` "Supported Key Bindings" (kbd `1`/`2` = scroll left/right; `enter` trigger; `escape` back; arrow keys) and "Input events" (web views receive scroll events; left/right/back reserved for applications)
- `wiboma/hudiy` `main_configuration.md` (`handleKeyboardEvents`, `activeBoundaries`, `splitWithProjections`)
- `wiboma/hudiy` `examples/gpio/KeyStrokes.py` + `VolumeRotaryEncoder.py` (the two canonical external-input patterns)
- hudiy.eu was geo-blocked from this network (country-block page); the upstream
  repo is the same upstream that ships the car's Hudiy build, so it is treated
  as authoritative.

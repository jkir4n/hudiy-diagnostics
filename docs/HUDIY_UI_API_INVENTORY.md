# Hudiy app UI/page API inventory — FINDINGS

Task t_5cc15f2e. Question: what can an external app render/control in Hudiy's UI?
Bottom line: Hudiy has NO runtime "create a page" API call. All pages are
FILE CONFIG (JSON under ~/.hudiy/share/config/) + a long-lived local web
backend (Flask) + a tiny protobuf control channel (TCP 44405 / WS 44406).
The proven Race Dash pattern is: overlay URL in overlays.json, menu/shortcut
action in applications_menu.json/shortcuts.json, RegisterAction over protobuf,
SetCustomOverlayVisibility to show/hide, all real UI inside your own web page
with an internal state machine. A full-screen app slot (applications.json)
exists upstream but is NOT used on the car today.

Evidence base (all read directly, nothing guessed):
- Pi /opt/hudiy-obd-charts: common/Api_pb2.py, common/Client.py,
  common/HardenedClient.py, charts.py (624 lines), race_dash_toggle.py
  (528 lines), charts_mock.py, config/applications_menu.json,
  config/dashboards.json, templates/race_dash.html, templates/test_overlay.html
- Live Hudiy config ~/.hudiy/share/config/: overlays.json,
  applications_menu.json (22 items), dashboards.json, applications.json
  (empty), shortcuts.json, main_configuration.json
- Live logs: ~/.hudiy/log/hudiy.*.log ([ApiEntity] lines),
  /tmp/race-dash-toggle.log, /tmp/hudiy-charts.log
- Upstream canonical api/Api.proto (855 lines, API 1.3) + examples in
  https://github.com/wiboma/hudiy (idle_screen, obd_charts, api/python/*,
  api/js, gpio)
- Third-party repos (GitHub API + raw fetch, 2026-09-10): EpicNori/Hudiy-Marketplace,
  noobychris/audi-can-rpi

NOT inspected (limitation): the dev workstation's copy of this repo's docs
(V1_SPEC.md, ARCHITECTURE_NOTES.md) and the Race Dash repo's
mock_hudiy_server.py — no reachable path to that machine from here. OBD-transport
constraint taken as given per task scope. Hudiy itself is closed-source, so
server-side internals below are marked [inferred] where they rest only on
client/log evidence.

---

## 1. Full protobuf message inventory (API 1.3, 51 messages, 53 wire ids)

Pi's generated common/Api_pb2.py exposes 51 message classes and matches the
upstream api/Api.proto exactly (same 51 names, Constants API_MAJOR_VERSION=1,
API_MINOR_VERSION=3, Api.proto lines 5-9; Pi reports API_VERSION 1.3 at
runtime). Wire framing is a 12-byte little-endian header
(len, msg_id, flags) + protobuf payload (common/Client.py lines 145-153),
over plain TCP (port 44405) or WebSocket (port 44406, / path).

"RD" = used by Race Dash today (charts.py = C, toggle daemon = T).

### Connection / keepalive
| Message (id) | Direction | RD | Notes |
|---|---|---|---|
| HelloRequest (1) name, api_version{ major, minor } | client->Hudiy | C,T | First frame after connect (Client.py 187-194) |
| HelloResponse (2) app_version, api_version, result OK/VERSION_MISMATCH/UNKNOWN_ERROR | Hudiy->client | C,T | All local clients send 1.3; toggle log shows registration succeeding right after hello |
| Ping (47) / Pong (48) | both | C,T | Client auto-replies PONG (Client.py 200-201); silence is normal — Hudiy is event-push |
| Byebye (49) | both | C,T | Graceful disconnect; wait_for_message returns False on it |

### THE overlay/action/page surface (the UI layer that matters)
| Message (id) | Direction | RD | Notes |
|---|---|---|---|
| RegisterActionRequest (41) action: string | client->Hudiy | T | "Name must be unique across the entire application" (Api.proto 738-744). Toggle registers "show_race_dash" (race_dash_toggle.py 371-377) |
| RegisterActionResponse (42) action, result: bool | Hudiy->client | T | Toggle log: "Action 'show_race_dash' registered: True" |
| DispatchAction (43) action: string | BOTH | T (rx); example (tx) | Hudiy->client means "your registered action was triggered" (menu/shortcut). Client->Hudiy triggers a built-in action BY NAME — this is the page-navigation primitive (see Q6). Toggle handles it at race_dash_toggle.py 467-470 |
| SetCustomOverlayVisibility (38) identifier: string, visibility: OverlayVisibility | client->Hudiy | T | identifier is the key from overlays.json ("race_dash"). ONLY runtime overlay control. Toggle sends it at race_dash_toggle.py 142-151; Hudiy logs "set custom overlay visibility, id: 2, identifier: race_dash, visibility: 0" |
| OverlayVisibility enum | — | T | NONE=0, ALWAYS=1, NATIVE_UI_ONLY=2, PROJECTION_ONLY=3 (Api.proto 699-704). Manual show uses ALWAYS; idle screensaver uses NATIVE_UI_ONLY (race_dash_toggle.py 173-175) |
| SetNavigationOverlayVisibility (39), SetVolumeOverlayVisibility (40) | client->Hudiy | — | Built-in overlays only, not third-party pages |
| CurrentMenuAction (52) action_name: string | Hudiy->client | T | Push of last-dispatched menu action; requires CURRENT_MENU_ACTION subscription. Toggle treats any change as user activity and force-hides the overlay (race_dash_toggle.py 446-462). Hudiy RE-PUSHES it on every subscribe, so consumers must dedup (MENU_ACTION_DEDUP_S=30s, lines 89-92) |
| KeyEvent (36) key_type (UP/DOWN/LEFT/RIGHT/ENTER/BACK/HOME/media/nav/voice…), event_type | client->Hudiy | — | Remote-control injection (Api.proto 631+). Crowpanel bridge dispatches menu actions rather than keys; audi-can-rpi injects keys via uinput instead (see Q4) |

### Status subscriptions (event-push; full list replaces previous list, Api.proto 104-123)
SetStatusSubscriptions (3): PROJECTION, MEDIA, NAVIGATION, OBD, PHONE,
COVERARTS, CURRENT_MENU_ACTION. Toggle subscribes to PROJECTION+MEDIA+
NAVIGATION+PHONE+CURRENT_MENU_ACTION (race_dash_toggle.py 381-390).
charts.py subscribes OBD only (charts.py 417-425). Push messages:
ProjectionStatus (5), MediaStatus (6), MediaMetadata (7),
NavigationStatus+ManeuverDetails+ManeuverDistance (8/9/10),
ObdConnectionStatus (23), PhoneConnectionStatus (33),
PhoneVoiceCallStatus (34), PhoneLevelsStatus (35). RD uses projection,
media.is_playing, nav state, call state for idle detection.

### OBD device access (NOT UI scope — listed only to keep the boundary clear)
QueryObdDeviceRequest (24) commands[]: string, request_code: int32, and
QueryObdDeviceResponse (25) result, data[], request_code — used ONLY by
charts.py (charts.py 179-194, 427-483). Per task scope and upstream, the
ELM327 path is separate from UI clients (see Q5).

### Notifications / toasts / status-bar icons (available, UNUSED by Race Dash)
RegisterNotificationChannelRequest/Response (15/16) + ShowNotification (18:
channel_id, title, description, icon_font_family, icon_name, action,
play_sound) + Unregister (17). Notification click dispatches `action` —
a second entry point into your app. RegisterToastChannel (19/20) +
ShowToast (22: channel_id, message, icons) + Unregister (21).
RegisterStatusIconRequest/Response (11/12: description, icon_font_family,
icon_name -> id) + ChangeStatusIconState (14: id, visible) + Unregister (13).
Upstream examples: Notification.py, Toast.py, StatusIcon.py. Fonts must be
pre-registered in main_configuration.json (Api.proto 275, 359, 414). A
diagnostics app could use these for "scan complete" toasts/notifications
with zero page UI.

### Audio focus / media / phone / projection control (available, UNUSED by RD)
RegisterAudioFocusReceiver (26/27: name, category, duck_priority -> id),
AudioFocusChangeRequest/Response (29/30), AudioFocusAction (31),
AudioFocusMediaKey (32), Unregister (28). overlays.json has per-overlay
controlAudioFocus + audioStreamCategory fields. MediaMetadata/MediaStatus
are read-only pushes. SetEqualizerPreset (44: name from config file),
SetBassTrebleBoost (53), SetAndroidAutoDayNightMode (50) /
SetAutoboxDayNightMode (51), CoverartRequest (45, client must answer with
CoverartResponse 46 — "register only one COVERARTS subscription app-wide
to avoid races", Api.proto 758-765).

### Display / theme (available, UNUSED by RD)
SetDarkMode (37: enabled), SetReverseCameraStatus (4: visible).
Upstream gpio/ + api/python examples: DarkMode.py, ReverseCamera.py,
Volume.py, BassTrebleBoost.py, Shutdown.py (Shutdown sends Byebye),
HelloWebSocket.py.

What Race Dash does NOT use but could: notifications/toasts (scan-done
alerts), status icon (persistent "diagnostics" icon), DispatchAction TX
(jump Hudiy to a dashboard), KeyEvent (d-pad navigation of its own page).

---

## 2. How Race Dash registers its menu entry + overlay (exact sequence)

There are TWO halves: file config (pages) + protobuf (wiring). Protobuf
cannot create either; it only links and shows/hides them.

FILE HALF (read at Hudiy start; edits need a Hudiy restart — see Q5):
1. Overlay page: ~/.hudiy/share/config/overlays.json declares
   identifier "race_dash", 800x480 at x0 y0, default visibility
   NATIVE_UI_ONLY, url "http://127.0.0.1:44411/race_dash?v=1787516000"
   (only the ?v= cache-buster changed between deploys), controlAudioFocus
   false, visibleOnActions [], staticPosition true. The URL is served by
   charts.py's generic /<page_name> route -> templates/race_dash.html
   (charts.py 202-214).
2. Menu entry: live applications_menu.json lines 220-228, category "Hudiy",
   iconFontFamily "Material Symbols Rounded", iconName "speed", action
   "show_race_dash", label "Race Dash". (The example config in
   /opt/hudiy-obd-charts/config/ has no such entry — the car copy was
   hand-extended. 22 items total, 5 categories: Phone/Music/Android
   Auto/Autobox/Hudiy.)

PROTOBUF HALF (every toggle-daemon connect, race_dash_toggle.py 356-390):
1. TCP connect 127.0.0.1:44405 -> HelloRequest name "RaceDashScreensaver",
   api 1.3 -> HelloResponse (Client.py 187-194).
2. On hello: hide overlay (stale-state reset), RegisterActionRequest
   action="show_race_dash", then SetStatusSubscriptions=[PROJECTION, MEDIA,
   NAVIGATION, PHONE, CURRENT_MENU_ACTION].
3. Hudiy logs "register action, id: N, action: show_race_dash"
   (archived hudiy.*.log, e.g. 2026-08-20 17:32:59, ids 2/3/5/6 across
   reconnects);
   client logs "Action 'show_race_dash' registered: True".

DISPATCH PATH (user taps Race Dash, or knob/shortcut fires the action):
Hudiy -> MESSAGE_DISPATCH_ACTION{action:"show_race_dash"} to the
registering connection -> toggle on_dispatch_action -> show_overlay(force=True)
-> SetCustomOverlayVisibility{identifier:"race_dash", visibility:ALWAYS}
(manual sticky; idle auto-show uses NATIVE_UI_ONLY instead). Touch-dismiss
inside the page is plain web: the page GETs the backend /hide, backend sends
Visibility NONE (test_overlay.html is the 6-line minimal version of this;
race_dash.html uses /hide + /show + EventSource /stream + GET /history +
POST /client-log).

---

## 3. Multiple pages? Tabs? Geometry? Fullscreen vs widget?

- MULTIPLE OVERLAYS: yes, structurally. overlays.json "overlays" is an
  ARRAY of {identifier, action, width, height, x, y, visibility, url,
  controlAudioFocus, audioStreamCategory, visibleOnActions[],
  staticPosition}. Upstream default ships it EMPTY (config/overlays.json);
  the car runs exactly ONE (race_dash). Each overlay gets independent
  runtime visibility by identifier. NOT verified: two overlays visible at
  once (only one ever deployed here), and the overlay-level "action" field
  is empty in every example seen — its effect is unknown, do not depend on it.
- TABS/SUBVIEWS: no such primitive anywhere (no tab message, no tab field
  in any config). Subviews are YOUR HTML's job (Race Dash's 1817-line
  single page does all layout internally).
- GEOMETRY: free x/y/width/height per overlay (race_dash is 800x480@0,0 =
  exactly the 7" display = fullscreen). Upstream idle example is 1024x600@0,0
  with a note to resize to your display (idle_screen README line 56).
  staticPosition:true in both. Widgets inside dashboards use size classes
  (small/medium/large x narrow/wide), not pixels.
- FULLSCREEN vs WIDGET are two different slots: (a) custom overlay = your
  URL full-bleed at any geometry, shown/hidden at runtime; (b) dashboard
  widgets ("web" / "web_static" types pointing at your backend URLs inside
  dashboards.json grids — the car shows OBD chart/gauge/blocks widgets this
  way). "web" vs "web_static" behavioral difference is undocumented —
  observed only that the first widget per dashboard is "web" and the rest
  "web_static". Do not assume interactivity differences.
- FULL-PAGE APP slot (upstream-documented, NOT on the car):
  applications.json entries {action, url (http:// or file://), allowBackground,
  controlAudioFocus, audioStreamCategory, zoomFactor} + a menu item with the
  same action (Marketplace README section 6). Live car applications.json is
  EMPTY, so treat as plan-B needing a device trial, not the proven path.
- Pages/overlays/dashboards/menu entries are ALL file config, none
  creatable over protobuf. visibleOnActions[] can auto-show an overlay on a
  named action (empty in all examples seen).

---

## 4. Third-party usage (concrete repos)

1. OFFICIAL, same API as the car: https://github.com/wiboma/hudiy
   (245 stars, pushed 2026-07-06). examples/obd_charts is the direct
   ancestor of the Pi code (same Flask+protobuf shape; Pi copy adds SSE
   /stream, batch /history, hardening, toggle daemon). examples/idle_screen
   is the canonical overlay+action+menu/shortcut pattern (idle_screen.py +
   config/overlays.json + config/shortcuts.json). examples/api/python has
   one runnable script PER message group (Hello, ObdQuery, DispatchAction,
   ToggleDashboards, CustomOverlayVisibility, CurrentMenuAction,
   Notification, Toast, StatusIcon, MediaData, KeyStrokes, Volume,
   DarkMode, …). examples/api/js is a JS protobuf client (hudiy_client.js)
   for pages. This repo is the frontend card's best reference after this
   document.
2. window.hudiy BRIDGE model (same Hudiy, newer WebView path):
   https://github.com/EpicNori/Hudiy-Marketplace + …-Website +
   …-E2E-Test-Plugin + …-Plugin-OBD2-Dashboard-install (all pushed
   2026-08-11). Marketplace README: "loaded by Hudiy's existing embedded
   Chromium view and connected to Hudiy through the official window.hudiy
   bridge" (README lines 1-5); theme via window.hudiy.colorScheme /
   onColorSchemeChanged (section 7); registration = fragments appended to
   applications.json + applications_menu.json (section 6, exact JSON
   quoted); installer notes "a controlled Hudiy restart is required"
   (Bridge API doc) — independent confirmation that config registration
   needs a restart. Its OBD2 dashboard package assumes a backend at
   127.0.0.1:44411 — i.e. it reuses the obd_charts backend contract.
   Caveat: community project, device-test report dated 2026-08-11 in-repo;
   the window.hudiy object is NOT exercised anywhere on the car today.
3. NO-protobuf integration: https://github.com/noobychris/audi-can-rpi
   (22 stars, tested table "Trixie | Hudiy | 2.16"). Drives Hudiy WITHOUT
   Api_pb2: serves its own HTML (~/scripts/hudiy_api/html_files),
   injects keys via uinput (/hudiy_home, /toggle_hudiy_focus), manages the
   process (pkill), ships .hudiy/share/config copies (pi_control.py lines
   166, 277-300, 355-359). Proves file-config + key-event integration is a
   viable fallback if protobuf ever misbehaves — but it is cruder (key
   injection, not API).
4. No Home Assistant integration and no Api_pb2 consumer beyond the above
   found (GitHub repo search "hudiy", 30 hits, 2026-09-10; the rest are
   name coincidences — users named Hudiy — or car-retrofit logs:
   korni92/RNS-E-Hudiy, LTLNMO/RNS-E-CarPi-Hudiy, bvdberg01/FiatStilo-hudiy,
   a8ksh4/taco_hu, madeliauskasa/hudiy-volvo,
   martis2580/Outdated-Volvo-Nav-Retrofit, sedlons/lr-hudiy-rpi-hat).
   Hosted web search was down during this task; GitHub API + raw fetch
   used instead, so drive-by blog mentions may be missed — none would
   change the API facts above, which come from the Pi itself.

---

## 5. Connection rules for UI clients

- Transports: TCP 127.0.0.1:44405 (length-prefixed protobuf; charts.py,
  toggle) AND WebSocket :44406 (same frames; crowpanel bridge,
  bridge_config.json hudiy_port 44406, hudiy_client.py). Hudiy listens on
  0.0.0.0 for both (ss output); Python backends bind 127.0.0.1 only.
- Handshake: Hello name + api_version 1.3, every connect, both transports
  (Client.py 187-194; bridge sends HELLO_REQUEST 1.3 then subscriptions).
  HelloResponse carries OK / VERSION_MISMATCH / UNKNOWN_ERROR (Api.proto
  87-102). All three local clients speak 1.3 and register fine. Mismatch
  behavior untested locally — code for it, do not reinvent it: always send
  the Pi's constants, never hardcode 1.3 in a new client (import from
  common/Api_pb2.py).
- Coexistence PROVEN, right now: "Chart" (charts.py, OBD sub) +
  "RaceDashScreensaver" (toggle, activity subs) + "crowpanel-nav-bridge"
  (WS, status subs) are simultaneously connected to one Hudiy (all three
  PIDs in ps; Hudiy log shows interleaved client ids 1-10). UI clients are
  NOT subject to any single-client constraint — keep that strictly separate
  from the OBD/ELM327 single-process rule, which lives one layer down
  (charts.py funnels all PID traffic through one Hudiy connection with a
  socket lock + one background poller; a second OBD querier is an OBD-layer
  problem, not a UI-layer problem).
- Action-name uniqueness: "must be unique across the entire application"
  (Api.proto 741-744); RegisterActionResponse.result=false on collision
  [inferred from the bool + MUST statement — no live collision observed].
  Namespace all new actions (e.g. "diag_*") and check result on every
  registration; log it like the toggle does.
- Unknown-message behavior: client side (common/Client.py wait_for_message)
  silently IGNORES unhandled ids. Server side is closed-source; observed
  only that Hudiy logs transport failures as "unknown client error …
  End of file / Connection reset by peer" and survives them (clients
  reconnect constantly — toggle log 00:06/00:58 shows clean re-register
  after Hudiy restarts). No evidence Hudiy punishes unknown ids, but also
  none that it tolerates them: send ONLY documented messages with all
  `required` (proto2) fields set.
- Subscription semantics: each SetStatusSubscriptions REPLACES the whole
  set (Api.proto 109); CURRENT_MENU_ACTION re-pushes on every subscribe
  (dedup needed, race_dash_toggle.py 89-92, 450-462); silence = healthy
  idle, so use generous read timeouts (30s in toggle) or you get reconnect
  storms that reset idle timers (race_dash_toggle.py 83-88).
- Config-vs-runtime split: overlays/menu/dashboards/applications/shortcuts
  JSON are read at Hudiy start. Only evidence of reload cost: the
  Marketplace installer requires "a controlled Hudiy restart" after editing
  them, and the car's own overlay-URL bump (?v=1787512000 -> ?v=1787516000)
  rode a redeploy. Design for restart-required registration; anything
  needing instant availability must go through runtime messages
  (visibility, toast, notification, dispatched action).

## 6. Recommendation for the diagnostics app (scan progress / results cards / report view)

Full-page navigation via protobuf is NOT possible — there is no
"open page X" or "create page" message. The realistic pattern, in
preference order:

A. ONE custom overlay + internal state machine (proven, no Hudiy restart
   for UI iteration). Register ONE overlay (e.g. identifier "diag",
   fullscreen 800x480) + ONE action (e.g. "show_diag") + ONE menu entry
   (copies the show_race_dash wiring exactly). Scan-progress ->
   results-cards -> report views are div-states inside your single page,
   driven by your backend over SSE/WebSocket like charts.py /stream.
   Show with ALWAYS (user-invoked, like manual sticky) or NATIVE_UI_ONLY
   (passive); hide on activity/menu-action exactly like the toggle does.
   Overlay content iteration needs only a backend restart, never Hudiy.
B. Full-screen application entry (applications.json + menu action,
   Marketplace section-6 shape) IF a device trial confirms the car's Hudiy
   build honors applications.json (ours is empty; upstream docs say yes).
   Same single-page state machine inside; nicer lifecycle (allowBackground,
   zoomFactor) than an overlay. Trial it before committing the spec to it.
C. Dashboard widgets (dashboards.json "web"/"web_static" tiles) only as a
   passive at-a-glance complement (e.g. a "Diag status" tile) — tiles are
   small, grid-bound, and file-config-only. Not a home for a 3-screen flow.
D. Notifications/toasts (+ optional status icon) for async events ("scan
   complete — tap to open"), with the notification's `action` set to your
   registered show action. Zero page cost, biggest UX win per line of code.

Do NOT design: per-screen overlays switched by dispatch (unverified that
two overlays compose; one overlay + internal states is strictly simpler),
protobuf-driven page creation (does not exist), or a second OBD-polling
connection (OBD-layer constraint, out of scope but must be respected: reuse
the charts backend's data, do not open a parallel ELM327 path).

---

## Implications for V1_SPEC.md frontend section (binding constraints)

1. UI = ONE overlay (or ONE applications.json app after a device trial),
   NOT N screens: scan / results / report are internal states of a single
   web page served by the app's own loopback backend; no protobuf call
   creates, navigates, or closes pages.
2. Registration is FILE CONFIG + HUDIY RESTART: overlay entry
   (identifier/geometry/url), menu item (category/icon/action/label), and
   optional shortcut/dashboard/application fragments ship as JSON edits;
   the installer must handle backup + restart, never live-patch.
3. Runtime control is exactly THREE messages: RegisterActionRequest once
   per connect, DispatchAction RECEIVED to open, SetCustomOverlayVisibility
   by identifier to show/hide. Everything else visual happens in HTML/JS.
4. Action strings are GLOBAL and UNIQUE: prefix everything ("diag_show",
   "diag_*"), check RegisterActionResponse.result, fail loudly on false.
5. Coexist with Chart + RaceDashScreensaver + crowpanel bridge: distinct
   hello `name`, own subscriptions only (OBD sub ONLY if you query OBD
   yourself — the diagnostics bridge lane already rides the charts app's
   own `POST /diag/obd` route), own Flask port (44411 charts+bridge /
   44413 toggle taken, 44412 upstream idle example; pick another
   127.0.0.1 port — diagnostics defaults to 44414).
6. Subscribe CURRENT_MENU_ACTION and hide/stand-down on any change (with
   ~30s dedup): the knob/remote ALWAYS wins; a sticky overlay that traps
   the user is the failure mode the toggle code explicitly guards against.
7. Touch-dismiss INSIDE the page: every screen needs a visible close/back
   affordance that calls the backend, which sends Visibility NONE — Hudiy
   gives you no window chrome. Design for 800x480, touch, no hover.
8. Async results go through notification/toast channels (click-action =
   your show action), not through polling overlays; optionally a status-bar
   icon. Fonts for any of these must be pre-registered in
   main_configuration.json.
9. Connection hygiene: hello 1.3 via shared Api_pb2 constants (never
   hardcoded), answer PING, treat silence as healthy (long read timeout),
   full re-register on every reconnect, send only documented messages with
   all required fields (proto2).
10. NEVER touch OBD transport from the UI client: no QueryObdDevice from
    the diagnostics frontend unless the spec explicitly takes over the
    poller role; read scan data from the backend side-channel (same
    localhost Flask/SSE pattern charts.py already proves).

---

## Sources (fetch log — re-verify from these, not from memory)

- https://github.com/wiboma/hudiy — official repo (245★): api/Api.proto,
  config/overlays.json, examples/README.md, examples/idle_screen/
  (README, idle_screen.py, config/overlays.json, config/shortcuts.json),
  examples/api/python/*.py, examples/obd_charts/, examples/api/js/
- https://github.com/EpicNori/Hudiy-Marketplace — README §§1/5/6/7,
  docs/MARKETPLACE_BRIDGE.md, docs/OBD2_DASHBOARD_PLUGIN.md
- https://github.com/noobychris/audi-can-rpi — README (Hudiy 2.16 table,
  §§3-4), scripts/pi_control.py
- Pi ground truth: /opt/hudiy-obd-charts/{common/Api_pb2.py,
  common/Client.py, common/HardenedClient.py, charts.py,
  race_dash_toggle.py, charts_mock.py, config/*.json, templates/*.html};
  ~/.hudiy/share/config/{overlays.json, applications_menu.json,
  dashboards.json, applications.json, shortcuts.json,
  main_configuration.json}; ~/.hudiy/log/hudiy.*.log;
  /tmp/race-dash-toggle.log; /tmp/hudiy-charts.log;
  /opt/crowpanel-nav-bridge/{bridge_config.json, bridge_lib/hudiy_client.py}

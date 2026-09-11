# tools/ — probe & capture toolchain (reference, NOT app code)

These scripts captured every fixture in `fixtures/` during Phase 1 (09–10 Sep).
They are archived for future on-car sessions (new cars, new Hudiy versions,
regression checks). They are NOT part of the diagnostics app; the app's proxy
lane will be a clean reimplementation guided by `docs/V1_SPEC.md`.

## The definitive fixture-capture method (charts-copy capture)

Why: Hudiy serves OBD to exactly ONE process (see
`docs/ARCHITECTURE_NOTES.md`). The only client that gets answers is the
race-dash charts process. So to run arbitrary queries, you run a COPY of
charts.py with an injected capture thread.

Files:
- `patch_charts_capture_thread.py` — builds `/opt/hudiy-obd-charts/charts_capture.py`
  from the deployed `charts.py`: (1) hooks `on_query_obd_device_response` to
  dump raw `message.data` for request codes ≥ 910000 to
  `/tmp/capture_inject.jsonl`; (2) adds a capture thread sending
  `["0A","0104","0133","0685","0904","0906"]` with req ids `910000 + cycle*10 + i`,
  6 cycles × 3 s spacing. Edit `CAPTURE_PIDS` for other queries.
- `patch_charts_capture_m02.py` — same, for the Mode-02 probe
  (`["0200","0202","0140","0160","0180","01A0"]`, req ≥ 920000).

Run procedure (validated twice on-car):
1. SSH to Pi (`car@<PI-IP>`). Check charts health FIRST:
   `curl -s http://127.0.0.1:44411/health` — need `hudiy_connected:true` and
   fresh `last_obd_age_s` (else fix that first, see pitfalls).
2. `python3 patch_*.py` (reads the DEPLOYED charts.py, writes the copy) then
   syntax-check: `import ast; ast.parse(open('/opt/hudiy-obd-charts/charts_capture.py').read())`.
3. `systemctl --user stop hudiy-obd-charts` (frees the served-client slot).
4. Launch: `cd /opt/hudiy-obd-charts && setsid nohup python3
   /opt/hudiy-obd-charts/charts_capture.py </dev/null > /tmp/capture_run.log 2>&1 &`
5. Read `/tmp/capture_inject.jsonl` while it cycles (6 cycles ≈ 2.5 min).
6. `pkill -9 -f charts_capture; rm /opt/hudiy-obd-charts/charts_capture.py;
   systemctl --user start hudiy-obd-charts`; verify health again.

## App smoke test (Phase 2c)

- `smoke_control_lane.py` — NOT a probe: it runs the real backend server
  (`python3 -m backend.server`, replay mode) against a fake Hudiy speaking the
  real wire framing, and asserts the control lane end to end — `/health` online,
  a dispatched action re-showing the overlay, `POST /ui/hide` sending `NONE`.
  Needs Hudiy's generated `Api_pb2.py` (the unit tests use a stub):
  `DIAG_HUDIY_API_PB2=/opt/hudiy-obd-charts python3 tools/smoke_control_lane.py`.
  Picks fresh loopback ports for both sockets, so it never touches a live Hudiy.

## Pitfalls (each one cost a debugging cycle — do not re-learn)

1. **Script must live in `/opt/hudiy-obd-charts/`.** Python resolves imports
   from the SCRIPT's directory (`sys.path[0]`), not the cwd. From `/tmp`,
   `import common.Api_pb2` fails with ModuleNotFoundError even with correct
   cwd. (PYTHONPATH env didn't rescue it in testing; copying the file did.)
2. **Backgrounded launches over ssh hang the ssh session** (Tailscale +
   `nohup … &`). The process still starts. Use `timeout`-guarded ssh or
   verify via `pgrep`/log file in a SEPARATE call. Never retry the launch
   blindly — you'll get two capture processes fighting.
3. **Plain `kill` on the Hudiy app can hang in shutdown** (ofono
   'Operation already in progress'): the half-dead app keeps TCP :44405, so a
   relaunch crashes with `bind: Address already in use`. Use `kill -9`, THEN relaunch.
4. **Manual Hudiy relaunch recipe** (after killing the app outside labwc):
   `XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
   LD_LIBRARY_PATH=$HOME/.hudiy/share QT_QPA_PLATFORM=eglfs nohup
   hudiy_startup.sh &` — without LD_LIBRARY_PATH it dies on `libhuinput.so`.
5. **Stale ObdManager after car power-cycle:** BT shows ELM Connected, clients
   subscribed, but every query is silently dropped (health age climbs;
   sometimes `ObdManager cancel id: N` in the newest
   `~/.hudiy/log/hudiy.N.log`). Restarting the charts service does
   NOT fix it. Kill -9 + relaunch Hudiy; device reopens in seconds (car powered).
6. **ELM device-open lag:** after boot it can take minutes (historic worst
   ~39 min). Probes before `device opened.` in the Hudiy log are wasted.
7. **`NO DATA` = empty string** in the captured jsonl (`"data": [""]`) — that
   is a valid negative answer, not a failure.

## Standalone-client reference (for installs WITHOUT race-dash)

- `capture_client_v1.py` — standalone HardenedClient('Chart') + OBD
  subscription + wait-for-device loop. NOTE: this got NO answers on the
  reference install (served-process constraint) — kept as the starting point
  for the standalone mode in `docs/V1_SPEC.md` and as evidence tooling.
- `probe_wait_for_device.py`, `probe_first_requester.py` — the
  first-requester/subscription probes (all negative results); archived as
  evidence for the constraint + as patterns for future regression probes.

## Marginal artifacts

- `/tmp`-sourced `diag_probe3.json` / `diag_probe4.json` (wedge-era empty
  results) are NOT archived here — zero informational value; the negative
  evidence lives in `fixtures/round2_elm_wedge_aftermath.json`.

## keyboard_shim.py — wheel/knob → diagnostics page (part of the APP)

Not a Phase-1 probe: this ships with every install (installer copies
`tools/keyboard_shim.py` + `backend/deploy/hudiy-diag-keys.service`).

Why it exists: this Hudiy build never routes physical input (wheel/knob) to
third-party overlay webviews — proven by CDP trials on 11 Sep (zero DOM
keydowns and zero bridge callbacks while the overlay was visible;
inputFocus/activated stay false). The shim reads the knob at the kernel input
layer and fires the page's own nav hook via the QtWebEngine DevTools socket
(127.0.0.1:9222), gated on overlay visibility, inert when hidden.

Device map (captured per-direction 11 Sep; earlier 1/2/3 guess was WRONG):
- `/dev/input/event4` — gen4-ESP32 MCU (Elecrow knob on the head unit),
  EV_KEY press/release per detent:
  - code 2 (KEY_1): one detent LEFT (previous)
  - code 3 (KEY_2): one detent RIGHT (next)
  - code 28 (KEY_ENTER): knob center press (activate)
  - code 1 (KEY_ESC): back — kept as fallback
- The device chatters: one quick turn can emit 5–6 detents — the shim forwards
  every edge; add debounce only if it ever mis-fires in real use.
- `/dev/input/event1` is a USB mouse — NOT the knob (first shim version's
  mistake, three failed user tests before the per-direction re-capture).

Deployment extras the installer now handles: unit install + `input` group
check (`sudo usermod -aG input $USER` on the reference Pi; done by hand there).
Debug: set `SHIM_DEBUG_LOG=/tmp/diag_shim_dbg.log` — one line per dispatch.

Hudiy visibility-edge behavior (found live 11–12 Sep): Hudiy RE-SHOWS the
singleton overlay webview on menu relaunch instead of recreating it, so a
previous session's Exit teardown (body.exited + hidden #app) persists as a
blank screen. Two countermeasures: diag.js clears exited state on
`window.hudiy.onAttached`, and the shim reloads the page ONLY when it sees
that exited state (reloading blindly flashes white mid-use). Never "fix"
blank-relaunch by reloading on every visibility edge — that is the white
screen bug.


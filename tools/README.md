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

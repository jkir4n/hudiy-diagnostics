# Architecture Notes — Hudiy Diagnostics (Phase 1 findings)

Status: **research-only**. No backend/frontend code exists yet (per plan: repo + data first).

## What this app must be
A Hudiy menu-launched car diagnostics app:
- **No autolaunch** — opened ONLY via the Hudiy applications menu (contrast: Race Dash auto-shows via `show_race_dash` action; this app registers a menu entry like `applications_menu.json` line-226 pattern but only shows its UI on dispatch).
- **Reads all OBD**, checks errors, runs car diagnostics (Modes 01/03/04/06/07/09/0A surface).
- **Universal** — deployable to ANY Hudiy instance; zero vehicle-specific or machine-specific code baked in. All vehicle-specific facts (VIN, PID support, OBDMID map) are DISCOVERED AT RUNTIME via 0100/0120/0140/0160 + 0900 queries, never hardcoded.

## Environment facts (proven on the reference head unit, 09 Sep)
- Hudiy TCP API: `127.0.0.1:44405`, protobuf `common/Api_pb2.py` (ships with hudiy-obd-charts deployment; identical lib available on the Pi).
- OBD path: Hudiy ⇄ ELM327 BT (RFCOMM) ⇄ ISO 15765-4 CAN 11-bit.
- charts.py (race dash) pattern: `Client` + `on_hello_response` → `SetStatusSubscriptions(OBD)` → `QueryObdDeviceRequest` / `on_query_obd_device_response`, request_code matching.
- Hudiy returns `NO DATA` as **empty string**.
- Menu entry file: `~/.hudiy/...applications_menu.json` (Race Dash entry at line 226: Material icon `speed`, Hudiy category, action `show_race_dash`).
- Race dash services are **user units**: `hudiy-obd-charts`, `race-dash-screensaver`. Hudiy app itself runs via labwc autostart (`~/.hudiy/share/hudiy_run.sh`); `hudiy.service` unit is a stub whose ExecCondition (multi-user.target) is unmet under graphical.target — `inactive` is its NORMAL state.
- No journald on the Pi; Hudiy logs at `~/.hudiy/log/hudiy.N.log` (rotated; find newest by mtime).

## HARD CONSTRAINT — single OBD client slot
Post-(re)boot, Hudiy routes OBD query responses **only to its first-boot primed OBD client** (currently charts.py). Verified 09 Sep across 5 probe designs:
- Second client: queries unanswered at 12s and 25s timeouts; after ~7 unanswered requests Hudiy **kills the connection** (broken pipe).
- Killing charts.py and waiting 10–20s does NOT release the slot.
- Round-1 probing (which DID get answers) ran while charts.py had never connected since Hudiy boot.
Consequence: the diagnostics app **cannot blindly open its own OBD client** on any Hudiy instance where another app (race dash or similar) already owns the slot.

### Design options for Phase 2 (decide with user)
1. **Proxy through the owning client** — diagnostics app consumes the race dash charts API (`:44411 /stream`, `/history`) for live PIDs and adds a diagnostics backend that forwards Mode 03/06/07/0A requests through a shared queue inside charts.py's process. Pro: works today, no Hudiy behavior assumptions. Con: couples apps.
2. **Arbiter pattern** — a small shared "OBD arbiter" service owns the Hudiy connection; both apps talk to the arbiter. Pro: clean universality. Con: one more service on every install.
3. **Menu-launched exclusivity** — diagnostics app connects on menu-open and politely asks user to quit race dash (or auto-pauses its poller via its HTTP toggle on :44413). Pro: simplest. Con: can't run simultaneously.
4. **Probe Hudiy for multi-client mode** — maybe a Hudiy setting/flag allows concurrent OBD query clients; needs a Hudiy restart experiment with probe-first ordering (charts never connected). Not yet tested (car went offline).

## ELM327 wedge hazard (Phase 2 safety rules)
- Mode 09 CALID (`0904`) multi-frame read wedged the adapter irrecoverably (reboot only). CVN (`0906`) unproven.
- Rules for the app: long multi-frame reads = single-flight, timeout-guarded (≤15s), one retry max, never issued while live-polling is active, and telemetry must keep flowing even if a diagnostics query hangs (diagnostics lane must not block the dash lane).

## Missing fixtures (to capture when car is next powered + slot ordering solved)
- Clean Mode 0A (permanent DTC) answer
- 0104 engine load, 0133 baro (both supported, never answered)
- Clean 0685 (boost OBDMID) re-read
- 0904 CALID / 0906 CVN (guarded)

## Data on hand
See `docs/DECODED_FIXTURES.md` + `fixtures/round1_full_capture.json` (27/28 queries answered).

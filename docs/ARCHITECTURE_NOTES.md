# Architecture Notes — Hudiy Diagnostics (Phase 1 findings)

Status: **research COMPLETE for architecture decisions** (updated 2026-09-09 late night after live experiments). No backend/frontend code exists yet (per plan: repo + data first).

## What this app must be
A Hudiy menu-launched car diagnostics app:
- **No autolaunch** — opened ONLY via the Hudiy applications menu (contrast: Race Dash auto-shows via `show_race_dash` action; this app registers a menu entry like `applications_menu.json` line-226 pattern but only shows its UI on dispatch).
- **Reads all OBD**, checks errors, runs car diagnostics (Modes 01/03/04/06/07/09/0A surface).
- **Universal** — deployable to ANY Hudiy instance; zero vehicle-specific or machine-specific code baked in. All vehicle-specific facts (VIN, PID support, OBDMID map) are DISCOVERED AT RUNTIME via 0100/0120/0140/0160 + 0900 queries, never hardcoded.

## Environment facts (proven on the reference head unit, 09 Sep)
- Hudiy TCP API: `127.0.0.1:44405`, protobuf `common/Api_pb2.py` (ships with hudiy-obd-charts deployment; identical lib available on the Pi).
- OBD path: Hudiy ⇄ ELM327 BT (RFCOMM) ⇄ ISO 15765-4 CAN 11-bit.
- charts.py (race dash) pattern: `HardenedClient("Chart")` + `on_hello_response` → `SetStatusSubscriptions(OBD)` → `QueryObdDeviceRequest` / `on_query_obd_device_response`, request_code matching.
- Hudiy returns `NO DATA` as **empty string**.
- Menu entry file: `applications_menu.json` (Race Dash entry pattern: Material icon, Hudiy category, action string).
- Race dash services are **user units**: `hudiy-obd-charts`, `race-dash-screensaver` (toggle unit `Wants=hudiy-obd-charts` — disabling charts alone does NOT prevent it starting; disable both). Hudiy app itself runs via labwc autostart (`~/.hudiy/share/hudiy_run.sh` → `hudiy_startup.sh`); `hudiy.service` unit is a stub whose ExecCondition (multi-user.target) is unmet under graphical.target — `inactive` is its NORMAL state.
- No journald on the Pi; Hudiy logs at `~/.hudiy/log/hudiy.N.log` (rotated; find newest by mtime). `ObdManager` lines there are the ground truth for ELM device state (`opening device failed. Retrying...` → `device opened.`) — the ELM BT device can take **minutes** to open after boot (39 min worst observed).
- **Manual Hudiy relaunch recipe** (if the app is ever killed outside labwc): needs session env — `XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus LD_LIBRARY_PATH=$HOME/.hudiy/share QT_QPA_PLATFORM=eglfs` + `nohup hudiy_startup.sh &`. Without `LD_LIBRARY_PATH` it fails on `libhuinput.so`.

## DEFINITIVE CONSTRAINT — Hudiy serves OBD to exactly one process (verified to exhaustion)
Night of 09 Sep, across 8+ probe designs (12s/15s/20s/25s timeouts, subscription/no-subscription, connect-before-open/connect-after-open, charts-running/charts-stopped/charts-disabled-at-boot/charts-never-connected, fresh Hudiy relaunch with probe as first-ever client):
- The probe client is byte-identical to charts.py's client (`HardenedClient("Chart")`, same protobuf shape, same OBD subscription). **It still receives nothing** — not even `ObdManager` cancel logs; a silent black hole.
- In the same conditions charts.py gets instant answers (OBD age 0.11s, all 7 PIDs).
- The discriminator is internal to Hudiy (likely SO_PEERCRED-style socket credential check or a whitelist of the served process). It CANNOT be faked from a second process.
- Earlier "first-querier wins the slot" and "subscription required" theories were DISPROVEN by these experiments.
- Additional hazard (secondary, real): long multi-frame Mode 09 CALID (`0904`) reads can wedge the ELM327 irrecoverably (reboot only). Single-flight, ≤15s timeout, one retry max.
- `NO DATA` arrives as **empty string** through Hudiy.
- Multi-frame responses concatenate `0:…1:…2:…` with variable CF lengths — parse sequentially (frame-count prefix + slice), never regex.

### Consequence for Phase 2 (design decision)
The diagnostics app **cannot open its own OBD client** on any Hudiy instance where a race-dash-like client is served — and even alone, a foreign process is not served. Two viable architectures:

1. **Proxy lane (RECOMMENDED)** — add a controlled diagnostics lane inside the race-dash charts service (or a sibling service in its process group sharing its connection): diagnostics queries ride the already-served client. On installs without race-dash, the diagnostics app runs its own equivalent of charts' connection pattern (same code path) and is then the served client.
   - Pro: works on the current install immediately; one more endpoint, not a new service; the missing fixtures (below) get captured through this lane naturally.
   - Con: couples the diagnostics feature to the charts service's lifecycle.
2. **Full-replacement mode** — diagnostics app implements charts' connection pattern as the sole OBD client; race-dash not installed / paused.
   - Pro: clean universality. Con: not coexistent on the same install.

Universality note: option 1 degrades gracefully — if race-dash is absent, the diagnostics lane code runs standalone; if present, it proxies. Both from the same codebase.

## Missing fixtures (now build-time items, not research gaps)
Because only the served charts process can query OBD, these 5 captures require the proxy lane (or temporary charts-process injection):
- Clean Mode `0A` (permanent DTCs) answer
- `0104` engine load, `0133` barometric pressure (both supported, never answered)
- Clean `0685` boost OBDMID re-read
- `0904` CALID / `0906` CVN (guarded — wedge hazard)

## Data on hand
See `docs/DECODED_FIXTURES.md` + `fixtures/round1_full_capture.json` (27/28 queries answered) + `docs/OBD2_DIAGNOSTICS_RESEARCH.md` (sourced protocol research).

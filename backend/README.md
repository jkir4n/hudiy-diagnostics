# Hudiy Diagnostics - backend

OBD-II diagnostics for a Hudiy car head unit: read every supported PID, pull
stored/pending/permanent fault codes, walk the Mode 06 monitor tests, decode the
readiness monitors and the VIN, and render the lot as text / CSV / JSON.

The backend is **stdlib only** (no pip installs) and has no car-specific
knowledge: everything the car can answer is discovered at runtime from the PID
bitmaps and OBDMID maps the ECU returns. The same install must work on any
Hudiy instance - see `AGENTS.md`.

```
backend/
  server.py          HTTP lane: endpoints, degradation rules, CLI entry point
  diag/
    config.py        every knob, from env (DIAG_*) with safe defaults
    hosts.py         the three ways to reach a car: bridge / standalone / replay
    lane.py          one-scan-at-a-time link + freshness/staleness health
    scan.py          the scan itself (phases: discovery, dtc, pending,
                     readiness, mode06, identity, live)
    decoders.py      OBD bytes -> engine numbers / monitor status
    protocol.py      request framing and response parsing (multi-frame safe)
    vin.py           VIN validation + offline WMI decode (+ optional online)
    dtc.py           fault-code text from the bundled Wal33D SQLite DB
    report.py        text / csv / json renderers
    fixtures.py      Phase 1 capture files -> replayable command map
    verdict.py       readiness verdict, and what "we could not ask" means
  tests/             unittest suites (core decoder tests + HTTP lane tests)
  deploy/            systemd user unit + idempotent install.sh
```

## Run it

```bash
# Replay: no car, no adapter - the recorded reference car, for demos and tests.
DIAG_MODE=replay python3 -m backend.server

# Standalone: open the ELM/adapter ourselves (installs without race-dash).
DIAG_MODE=standalone python3 -m backend.server

# Bridge: when the race-dash charts process owns the OBD slot, ride it. Hudiy
# serves OBD to exactly ONE process (docs/ARCHITECTURE_NOTES.md), so this is the
# correct mode on the reference install.
DIAG_MODE=bridge python3 -m backend.server
```

Then: `curl -s http://127.0.0.1:44414/health`

`DIAG_MODE=auto` (default) picks bridge when the charts bridge answers and
standalone otherwise.

## Endpoints

All are `GET`, all answer `application/json` unless stated. Anything that would
need the car degrades instead of erroring - see the next section.

| Endpoint | Answers |
| --- | --- |
| `/health` (alias `/diag/status`) | `{ok, mode, uptime, obd:{state,reason}, dtc_db, scan, fixture}`. Always 200 while the process is alive. |
| `/scan` | Runs a scan and returns `{ok, status, sections, obd, summary, report}`. `?sections=dtc,readiness` runs only those phases; unknown names -> 400. |
| `/report` | The last report. `?format=text\|csv\|json` (default text). Runs a scan first if none has happened yet. |
| `/dtc` | `?code=P0401[&maker=VOLKSWAGEN]` -> generic + maker-specific text. Missing `code` -> 400. |
| `/vin` | `?vin=WVWZZZ1KZAW555555[&online=1][&maker=...]` -> validated VIN + WMI/model-year. `online=1` adds the bounded nmvtis lookup. |

`/diag/scan`, `/diag/report`, `/diag/report.txt`, `/diag/report.csv` also work
(the names V1_SPEC uses). `GET /` lists the endpoints.

## The degradation contract

A car is asleep, a door is open, the ELM is paired but the ECU is not talking,
or the last power-cycle left Hudiy holding a stale OBD handle. In every one of
those cases the UI must be able to tell *"the car is clean"* from *"I could not
ask"*, so:

- `/health` always 200 and reports `obd.state`:
  `online` | `offline` | `reconnecting` | `stale-handle` | `unknown` |
  `unavailable`, with a `reason` string and the host's own health (`reachable`,
  `hudiy_connected`, age).
- `/scan` returns HTTP 200 with `status:"offline"` / `"unavailable"` and
  `report: null` when the car cannot be reached - never a 500, never a fake
  empty report. `last_scan` carries whatever was last obtained.
- A scan that started but could not finish comes back `status:"partial"` with
  `ok:false` and the engine's `abort_reason`; the phases that did complete are
  still in the report, and unread phases are `null`/empty rather than zeros.
- Concurrent `/scan` calls: the second gets **409** `status:"busy"`.
- Bad input: **400** `status:"bad_request"` with the fix in `message`.
- Only real bugs produce a 500.

The VIN decode's online lookup runs on a bounded budget (`DIAG_VIN_DECODE_TIMEOUT_S`);
if it does not answer in time the request returns the offline decode plus a
reason, and the lookup is not retried (nmvtis is not a dependency: no internet
in a car park is normal).

## Configuration

Everything is env-driven (`backend/diag/config.py`); nothing is hardcoded per
car or per install. The ones worth knowing:

| Variable | Default | Meaning |
| --- | --- | --- |
| `DIAG_MODE` | `auto` | `auto` \| `bridge` \| `standalone` \| `replay` |
| `DIAG_HTTP_HOST` / `DIAG_HTTP_PORT` | `127.0.0.1` / `44414` | Bind address. Loopback by default; there is no authentication, so widening the bind publishes vehicle data to the network. |
| `HUDIY_HOST` / `HUDIY_TCP_PORT` | `127.0.0.1` / `44405` | Hudiy API (standalone mode) |
| `DIAG_CHARTS_BRIDGE_URL` | `http://127.0.0.1:44411/diag/obd` | race-dash OBD bridge (bridge mode; served by the charts app on its existing port) |
| `DIAG_REPLAY_FIXTURES` | `fixtures/round1_full_capture.json` | Replay source: one capture file or a comma-separated list |
| `DIAG_QUERY_TIMEOUT_S` / `DIAG_QUERY_RETRIES` | `15` / `1` | Per-query budget and the single retry |
| `DIAG_QUERY_SPACING_S` | `0.45` | Inter-query spacing on the shared lane |
| `DIAG_SCAN_DEADLINE_S` | `300` | Whole-scan ceiling; the engine aborts cleanly past it |
| `DIAG_STALE_AGE_S` / `DIAG_STALE_CONFIRM` | `12` / `2` | When a connected-but-silent adapter is called stale (the "stale ObdManager" hazard) |
| `DIAG_DTC_DB` / `DIAG_DTC_DEFAULT_MAKER` | bundled Wal33D DB / empty | Fault-code text; absent DB degrades to code-only, it does not fail |
| `DIAG_VIN_DECODE` / `DIAG_VIN_DECODE_TIMEOUT_S` | `1` / `6` | Online VIN lookup and its bound |
| `DIAG_LOG_LEVEL` | `INFO` | Stdlib logging to stderr |

A full list with comments is the top of `backend/diag/config.py`.

## Tests

```bash
python3 -m unittest discover -s backend -t .        # from the repo root
```

`backend/tests/test_diag_core.py` covers framing/decoding against captured
fixtures (positive *and* negative). `backend/tests/test_diag_server.py` drives
the HTTP lane over a real loopback socket in replay mode and then asserts the
degradation contract with fake links (asleep car, stale handle, missing fixture,
concurrent scan, bad input). No car and no network are required.

## The overlay page (`frontend/`)

`GET /app/<path>` serves the read-only `frontend/` tree, so one process covers
both halves of the product:

    /app/diag.htm...[truncated]

```bash
./backend/deploy/install.sh              # install/update + start (no root)
./backend/deploy/install.sh --dry-run    # show what it would do
./backend/deploy/install.sh --uninstall  # stop + remove the unit
```

The installer copies `backend/` + `frontend/` + `fixtures/` into
`~/.local/share/hudiy-diagnostics`, installs the **user** unit
`hudiy-diagnostics.service` (same pattern as the race-dash units: no root, no
autolaunch - nothing starts it until the app is opened from the Hudiy menu),
enables it, then polls `/health` and prints the result. Per-instance settings
live in `~/.config/hudiy-diagnostics/env`; the installer creates that file only
if it is missing. Re-run it after every `git pull` - it is idempotent and
replaces the copied trees.

### Hudiy registration (menu entry + overlay)

Hudiy reads `overlays.json` and `applications_menu.json` **once at start**, so
registration is a two-step operation and the second step is a restart:

1. The installer merges the fragments under `frontend/hudiy/` into the live
   config, but only if the config layout is actually present
   (`~/.hudiy/share/config`; override with `DIAG_HUDIY_CONFIG_DIR`). On an
   install without that directory it prints the command to run by hand and
   changes nothing. The merge **never overwrites** the file: it inserts the
   `diag` overlay and the Diagnostics menu item, leaves every other entry
   alone, and writes a timestamped backup first
   (`applications_menu.json.bak-YYYYmmdd-HHMMSS`). Re-running is a no-op
   (`already present`).
2. **Restart Hudiy** for the new menu entry to appear - the files are loaded at
   start, so a running Hudiy keeps serving its old menu. Back up the config
   (the merge already did) and restart the process; never live-patch or
   hot-reload the config, and never write into `~/.hudiy/share/config` outside
   this step.

Ports: race-dash occupies 44411 (charts SSE **and** the `/diag/obd` bridge
route) and 44413 (toggle), so diagnostics defaults to **44414**. The bridge
adds no listener of its own - it is a route on the charts app.

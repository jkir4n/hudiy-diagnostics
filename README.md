# Hudiy Diagnostics

Car diagnostics app for Hudiy — reads OBD data, checks for errors, runs vehicle diagnostics. Menu-launched (no autolaunch). Universal: deployable to any Hudiy instance, no vehicle- or machine-specific code.

Independent companion for [Hudiy](https://hudiy.eu) — not affiliated; ships no Hudiy code; requires your own Hudiy install.

## Install (one line, no root)

```
git clone https://github.com/jkir4n/hudiy-diagnostics.git && cd hudiy-diagnostics && bash install-bootstrap.sh
```
or, without cloning:
```
bash <(curl -fsSL https://raw.githubusercontent.com/jkir4n/hudiy-diagnostics/master/install-bootstrap.sh)
```
Installs user units + the wheel/knob shim, registers the Hudiy menu entry, health-checks `:44414`, then reboots so every change is picked up on the fresh boot (Hudiy reads its config at start). `--no-reboot` skips the reboot; `--dry-run` shows everything without touching anything. The one thing it cannot do for you is printed at the end (the `input` group for the knob shim). Underneath it runs `backend/deploy/install.sh`.

## Uninstall (one line, no root)

```
bash <(curl -fsSL https://raw.githubusercontent.com/jkir4n/hudiy-diagnostics/master/uninstall-bootstrap.sh)
```
or, from a clone: `bash uninstall-bootstrap.sh` (flags pass through, e.g. `--no-reboot`, `--dry-run`).

Removes both user units, reverses the Hudiy menu/overlay merge (other apps' entries untouched), deletes the copied tree (only if it looks like ours) and the env file, then reboots so the menu entry disappears. Leaves the `input` group, install backups (`*.bak-*`), race-dash, logs — and prints exactly what it kept. Idempotent: safe to re-run; a clean machine reports skipped/not-present and exits 0.

## Repository layout
```
docs/
  OBD2_DIAGNOSTICS_RESEARCH.md   # 576-line sourced protocol research (SAE J1979, ELM327, ISO 16565-4)
  ARCHITECTURE_NOTES.md          # environment facts, hard constraints, Phase-2 design options
  DECODED_FIXTURES.md            # round-1 live capture, decoded (VIN, PID map, Mode 06, DTCs)
fixtures/
  round1_full_capture.json       # 27/28 live OBD queries + answers (2026-09-09, engine running)
  round2_elm_wedge_aftermath.json# negative evidence: ELM327 wedge post-mortem state
  round5_second_client_routing_evidence.json  # Hudiy kills a starving second OBD client
  probe_round5_method.py         # probe client method (Hudiy protobuf, strict abort-on-timeout)
```

## HTTP lane (`python3 -m backend.server`, default `127.0.0.1:44414`)

`GET /health` (aka `/diag/status`), `GET /scan`, `GET /report?format=text|csv|json`,
`GET /capability`, `GET /dtc?code=`, `GET /vin?vin=`, `POST /ui/hide` (overlay Exit),
and the one car-changing call: `POST /clear` (or `/diag/clear`) with `confirm=yes`
in the query string or the POST body (form or JSON). Without the confirm flag the
lane answers 400 naming the consequence list (codes + freeze frame + readiness +
Mode 06 results erased, monitors reset so no emissions pass until a drive cycle,
possible re-learn roughness, fix-first guidance per `docs/FEATURE_SURVEY_FINDINGS.md`
section 5); permanent Mode 0A codes are never clearable by any tool. A confirmed
clear answers the seam contract (`mode04_positive`, `codes_seen_before`, `followup`,
`permanent_codes_note`), a silent/refusing ECU gets a structured
`unsupported`/`refused` answer, and a timeout is a 502 saying the codes were NOT
confirmed cleared. Overlay side shipped and gated: the Fault codes screen (S3)
carries a `Clear fault codes` entry (enabled only while the lane is online)
opening the S11 two-screen confirm (consequence list + fix-first checkbox,
then result + readiness follow-up with automatic wall re-read).

## The vehicle (this capture only — the APP must discover these at runtime)
- VIN `WVWZZZ1KZAW555555` (synthetic placeholder — the capture was anonymised), ECM "ECM-EngineControl", diesel monitor map.
- Supported PIDs & OBDMIDs: see `docs/DECODED_FIXTURES.md`.

## Known hard constraints (from live probing)
1. Hudiy serves OBD query responses to a single primed client per boot (see `docs/ARCHITECTURE_NOTES.md`).
2. ELM327 adapter can wedge on long multi-frame reads (Mode 09 CALID) — needs single-flight + timeout + one-retry design.
3. `NO DATA` arrives as empty string through Hudiy.
4. Response frames concatenate as `0:…1:…2:…` with variable CF lengths — parse sequentially, never regex.

## License

MIT — see [`LICENSE`](LICENSE).

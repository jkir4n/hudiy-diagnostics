# Changelog — Hudiy Diagnostics

All notable changes. Format: date — phase — what.

## 2026-09-09 — Phase 1: research & data gathering

### Added
- Initial repository (per owner's plan: gather data first, create repo, build later).
- `docs/OBD2_DIAGNOSTICS_RESEARCH.md` — 576-line sourced OBD-II protocol research (SAE J1979 services/PIDs, ISO 15765-4 transport, ELM327 command behavior, VW diesel specifics, Mode 06 OBDMID tables, fixture-verification note).
- `docs/ARCHITECTURE_NOTES.md` — environment facts, hard constraints (single OBD client slot, ELM wedge hazard, empty-string NO DATA, multi-frame parsing), Phase-2 design options.
- `docs/DECODED_FIXTURES.md` — round-1 live capture decoded.
- `fixtures/round1_full_capture.json` — 27/28 live OBD queries answered on-car (engine running): VIN, ECU name, PID support bitmaps (0100/0120), Mode 09 INFOTYPE map, Mode 06 OBDMID data, stored+pending DTC responses, live sensor values.
- `fixtures/round2_elm_wedge_aftermath.json` — negative evidence after the ELM327 wedge (all queries unanswered, then broken pipe).
- `fixtures/round5_second_client_routing_evidence.json` — evidence of the Hudiy single-OBD-client constraint (7 unanswered queries then connection kill).
- `fixtures/probe_round5_method.py` — probe client reference implementation.

### Learned (key findings)
- VIN `WVWZZZ1KZAW555555`; ECM "ECM-EngineControl" (diesel VW).
- Supported PIDs (round-1 capture): 01 04 05 0B 0C 0D 0F 10 11 13 1C 1F 20 / 21 23 24 2C 2D 30 31 33 40.
- Mode 09 supports INFOTYPEs 02 (VIN), 04 (CALID), 06 (CVN), 0A (ECU name).
- Mode 03 + 07 clean at capture (no DTCs); Mode 06 monitor data captured for O2/EGR/boost OBDMIDs.
- Hudiy OBD: single primed client per boot; second client starves and gets disconnected (~7 unanswered queries).
- ELM327 wedges irrecoverably on long multi-frame Mode 09 CALID reads.

### Deferred (owner instruction)
- Backend + frontend build — starts only after data gathering confirmed complete. Split FE/BE to specialist cards, backend first.

## 2026-09-10 — Phase 1 close-out: definitive constraint + all fixtures + v1 spec

### Added
- `fixtures/capture_final_fixtures.jsonl` + `fixtures/decoded_final_fixtures.json` — served-client capture route (charts.py copy + injected capture thread): clean `0104` (0% idle), `0133` (101 kPa), clean multi-frame `0685`, `0904` CAL-ID `'00Z000000Z  0000'`, `0906` CVN `0xA5A5A5A5` (5–6 consistent cycles each).
- `fixtures/m02_freezeframe_probe.jsonl` + `fixtures/m02_freezeframe_decoded.json` — Mode 02 probe: freeze frame **not supported** (0200/0202 empty 6/6); `0140`=`CC D2 00 00` completes the support map (PIDs 41/42/45/46/49/4A/4C/4F; nothing beyond 0x5F).
- `docs/FEATURE_SURVEY_FINDINGS.md` — researcher-card survey: 9 consumer apps, 14 OSS projects, 31 sources; DTC-text source = Wal33D/dtc-database (MIT SQLite, bundled offline); vPIC VIN decode verified live (Indian VW coverage weak — decode is best-effort).
- `docs/V1_SPEC.md` — build-ready spec: hard rules, feature table mapped to fixtures, backend/frontend shape, build order.

### Changed (corrections to earlier entries)
- **"ELM327 wedges irrecoverably on long multi-frame CALID reads" is RETRACTED.** The round-2/3 wedge was Hudiy ObdManager starving an unserved client, not ELM fragility. Multi-frame reads (`0904`) are safe through the served client (proven repeatedly 10 Sep).
- **"Single primed client per boot" refined to the definitive model**: Hudiy serves OBD to exactly ONE process (the charts process). A byte-identical probe client gets silent nothing — not timing, not subscription, not connection order. Likely internal (SO_PEERCRED-style) discrimination. Design consequence: diagnostics must proxy through the charts process; standalone mode when race-dash absent.
- Status: Phase 1 (research + data gathering) **COMPLETE**. Phase 2 build order unchanged: backend specialist card first, then frontend.

## 2026-09-10 — Research round 2 + readiness fixture (pre-build close-out)

### Added
- `docs/HUDIY_UI_API_INVENTORY.md` — 51-message protobuf API map (1.3), overlay/action registration sequence, single-overlay + internal-state-machine pattern, 10 binding frontend constraints (researcher card t_5cc15f2e).
- `docs/KIOSK_UX_FINDINGS.md` — NHTSA 2s-glance / Google 32dp-76dp-4.5:1 / WCAG 2.2 anchored design numbers; Okabe-Ito colorblind-safe severity palette; per-mode scan checklist; S0–S8 screen flow for all 9 v1 features; two-screen clear-codes safety flow; reconnect resilience patterns (t_7375eac8).
- `docs/DIESEL_READINESS_FINDINGS.md` — TDI monitor table anchored on VW TSB 01-15-18 + CA BAR rules; reset/re-completion timelines; top-5 TDI not-ready causes; paste-ready British-English copy blocks; 4-input verdict arithmetic (t_19bee37d).
- `fixtures/readiness_m0101_m0141.jsonl` + `readiness_m0101_decoded.json` — live readiness capture: MIL off, diesel engine-type bit set, boost + exhaust-gas-sensor + EGR available & complete, two-group wall (0101 + 0141) verified.
- `tools/patch_charts_capture_m02.py` equivalent for readiness (`patch_rd.py` archived as part of the capture toolchain).
- `docs/DECODED_FIXTURES.md` — session-2 decode: final 6-mode fixtures, M02 negative, 0140 support-map completion, readiness decode; ELM-wedge claim formally retracted.

### Research phase verdict
- 4 researcher cards complete (feature survey, UI API inventory, kiosk UX, diesel readiness); all findings committed and QA-gated (load-bearing claims verified live: Wal33D repo, vPIC, VW TSB PDF, CA BAR, Api.proto, overlays.json, NHTSA Federal Register, Google Design for Driving).
- Ready for Phase 2: backend specialist card first (constraint block = docs/), then frontend.

## 2026-09-10 — Phase 2b (backend): HTTP lane + scan phases + deploy

### Added
- `backend/server.py` — the diagnostics HTTP lane (stdlib only): `GET /health` (alias `/diag/status`), `/scan[?sections=...]`, `/report[?format=text|csv|json]`, `/dtc?code=&maker=`, `/vin?vin=&online=`, `GET /` index. Also `/diag/report.txt|.csv` (V1_SPEC names). CLI: `python3 -m backend.server`, binds 127.0.0.1:44414 by default.
- Degradation contract, so the UI can always tell "the car is clean" from "I could not ask": `/health` always 200 with `obd.state` (`online|offline|reconnecting|stale-handle|unknown|unavailable`) + reason; `/scan` answers 200 with `status:"offline"|"unavailable"` and `report:null` (never a 500 or a fake empty report); a started-but-unfinished scan is `status:"partial"` with the engine's `abort_reason` and only the phases that completed; concurrent scans get 409; bad input 400; only real bugs 500.
- `backend/diag/fixtures.py` — Phase 1 capture files -> replayable command map (JSON object / JSONL, `.decoded.json` skipped, multi-file merge, per-command metadata); powers `DIAG_MODE=replay` (default source `fixtures/round1_full_capture.json`).
- `backend/tests/test_diag_server.py` — 21 tests: the replay car over a real loopback socket, plus the degradation contract with fake links (asleep car, stale ObdManager, missing fixture, concurrent scan, bad sections/format/code).
- `backend/deploy/hudiy-diagnostics.service` + `backend/deploy/install.sh` — user units (race-dash pattern, no root, nothing autolaunches: the app is started from the Hudiy menu), idempotent installer (`--dry-run`, `--uninstall`) that copies `backend/`+`fixtures/`, enables the unit and polls `/health`; per-instance settings in `~/.config/hudiy-diagnostics/env`.
- `backend/README.md` — run modes, endpoint table, degradation rules, env reference, tests, deploy.
- `GET /scan?sections=` — run one phase on its own (`discovery`, `dtc`, `pending`, `readiness`, `mode06`, `identity`, `live`); no filter = full scan (unchanged behaviour).

### Fixed
- `report.py` text/csv renderers crashed on every real report: they treated the PID-support *map* (`{"0100": [4,5,...]}`) as a flat list and formatted its keys with `0x%02X`. Now rendered via `_hex_list` (int or pre-formatted), and CSV gained the support/`self-test` rows it was missing, so a CSV reader can also see what the car answered.
- `scan.py` reported link-lifetime totals as per-scan traffic. `scan.queries/timeouts/retries/failures` are now deltas measured across the scan — on a long-lived service the old numbers grew with every scan and read as if one scan had sent them.
- `scan.py` called `decoders.summarize_codes()` with the flat stored/pending/permanent code lists instead of the decoded `dtc_list()` mappings it buckets on; and with no fault phase run it no longer fabricates a "0 codes, clear" summary (it passes `None`, which degrades the verdict to unknown rather than falsely reporting the car as ready).


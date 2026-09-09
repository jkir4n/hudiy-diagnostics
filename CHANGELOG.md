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

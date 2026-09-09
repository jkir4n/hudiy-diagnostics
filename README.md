# Hudiy Diagnostics

Car diagnostics app for Hudiy — reads OBD data, checks for errors, runs vehicle diagnostics. Menu-launched (no autolaunch). Universal: deployable to any Hudiy instance, no vehicle- or machine-specific code.

**Status: Phase 1 — research & data gathering (backend/frontend deliberately deferred).**

## Repository layout
```
docs/
  OBD2_DIAGNOSTICS_RESEARCH.md   # 576-line sourced protocol research (SAE J1979, ELM327, ISO 15765-4)
  ARCHITECTURE_NOTES.md          # environment facts, hard constraints, Phase-2 design options
  DECODED_FIXTURES.md            # round-1 live capture, decoded (VIN, PID map, Mode 06, DTCs)
fixtures/
  round1_full_capture.json       # 27/28 live OBD queries + answers (2026-09-09, engine running)
  round2_elm_wedge_aftermath.json# negative evidence: ELM327 wedge post-mortem state
  round5_second_client_routing_evidence.json  # Hudiy kills a starving second OBD client
  probe_round5_method.py         # probe client method (Hudiy protobuf, strict abort-on-timeout)
```

## The vehicle (this capture only — the APP must discover these at runtime)
- VIN `WVWZZZ1KZAW555555`, ECM "ECM-EngineControl", diesel monitor map.
- Supported PIDs & OBDMIDs: see `docs/DECODED_FIXTURES.md`.

## Known hard constraints (from live probing)
1. Hudiy serves OBD query responses to a single primed client per boot (see `docs/ARCHITECTURE_NOTES.md`).
2. ELM327 adapter can wedge on long multi-frame reads (Mode 09 CALID) — needs single-flight + timeout + one-retry design.
3. `NO DATA` arrives as empty string through Hudiy.
4. Response frames concatenate as `0:…1:…2:…` with variable CF lengths — parse sequentially, never regex.

## Next phases (pending)
- Phase 2a: settle OBD client-slot design (arbiter vs proxy vs exclusivity) — options documented.
- Phase 2b: backend + frontend (split to specialist cards; backend first).


---

**Update 2026-09-10:** Phase 1 complete. All fixtures captured (including negative fixtures: freeze-frame and Mode 0A not supported on the reference car — handled by runtime discovery). Definitive transport constraint + v1 build spec in `docs/V1_SPEC.md`; feature survey in `docs/FEATURE_SURVEY_FINDINGS.md`. Phase 2: backend specialist first, then frontend.


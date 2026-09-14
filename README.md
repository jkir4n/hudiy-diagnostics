# Hudiy Diagnostics

Car diagnostics app for Hudiy — reads OBD data, checks for errors, runs vehicle diagnostics. Menu-launched (no autolaunch). Universal: deployable to any Hudiy instance, no vehicle- or machine-specific code.

**Status: live on the reference car (Phases 1–2c). Publication-ready; not yet published — see `docs/GITHUB_PUBLISH_PRIVACY_GATE.md`.**

## Install (one line, no root)

```
git clone <this repo> && cd Hudiy-Diagnostics && bash install-bootstrap.sh
```
or, once published:
```
bash <(curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/master/install-bootstrap.sh)
```
Installs user units + the wheel/knob shim, registers the Hudiy menu entry, health-checks `:44414`. The two things it cannot do for you are printed at the end (`input` group, Hudiy restart). Underneath it runs `backend/deploy/install.sh` (`--dry-run` supported).

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
- VIN `WVWZZZ1KZAW555555` (synthetic placeholder — the capture was anonymised), ECM "ECM-EngineControl", diesel monitor map.
- Supported PIDs & OBDMIDs: see `docs/DECODED_FIXTURES.md`.

## Known hard constraints (from live probing)
1. Hudiy serves OBD query responses to a single primed client per boot (see `docs/ARCHITECTURE_NOTES.md`).
2. ELM327 adapter can wedge on long multi-frame reads (Mode 09 CALID) — needs single-flight + timeout + one-retry design.
3. `NO DATA` arrives as empty string through Hudiy.
4. Response frames concatenate as `0:…1:…2:…` with variable CF lengths — parse sequentially, never regex.

## Status & docs
Phases 1–2c complete: the app is live on the reference head unit (backend + frontend + wheel/knob shim; deploy via `install-bootstrap.sh`). History: `CHANGELOG.md`. Publication readiness: `docs/GITHUB_PUBLISH_PRIVACY_GATE.md`.


---

**Update 2026-09-10:** Phase 1 complete. All fixtures captured (including negative fixtures: freeze-frame and Mode 0A not supported on the reference car — handled by runtime discovery). Definitive transport constraint + v1 build spec in `docs/V1_SPEC.md`; feature survey in `docs/FEATURE_SURVEY_FINDINGS.md`. Phase 2: backend specialist first, then frontend.

**Update 2026-09-11:** The app is live on the car. Wheel/knob navigation shipped: this Hudiy build routes no physical input to third-party overlay webviews, so `tools/keyboard_shim.py` (unit `hudiy-diag-keys`, installed by `backend/deploy/install.sh`) reads the Elecrow knob at the input layer and drives the page's `window.__diagKeyNav()` via the QtWebEngine DevTools socket — inert unless the overlay is visible. Overlay lifecycle: Hudiy re-shows the singleton webview on relaunch, so the page undoes its exit teardown on attach (anything else = blank relaunch or white-flash; details in `tools/README.md`). Privacy: gate **executed 2026-09-14** (synthetic VIN/CAL-ID/CVN in fixtures + docs; topology genericised; shim made device-configurable). Repo is publication-ready; not yet published.


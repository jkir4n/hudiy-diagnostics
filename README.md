# Hudiy Diagnostics

Car diagnostics app for Hudiy — reads OBD data, checks for errors, runs vehicle diagnostics. Menu-launched (no autolaunch). Universal: deployable to any Hudiy instance, no vehicle- or machine-specific code.

**Status: live on the reference car (Phases 1–2c). Published 17 Sep 2026 — https://github.com/jkir4n/hudiy-diagnostics (privacy gate: see `docs/GITHUB_PUBLISH_PRIVACY_GATE.md`).**

## Install (one line, no root)

```
git clone https://github.com/jkir4n/hudiy-diagnostics.git && cd hudiy-diagnostics && bash install-bootstrap.sh
```
or, without cloning:
```
bash <(curl -fsSL https://raw.githubusercontent.com/jkir4n/hudiy-diagnostics/master/install-bootstrap.sh)
```
Installs user units + the wheel/knob shim, registers the Hudiy menu entry, health-checks `:44414`, then reboots so every change is picked up on the fresh boot (Hudiy reads its config at start). `--no-reboot` skips the reboot; `--dry-run` shows everything without touching anything. The one thing it cannot do for you is printed at the end (the `input` group for the knob shim). Underneath it runs `backend/deploy/install.sh`.

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

**Update 2026-09-11:** The app is live on the car. Wheel/knob navigation shipped: this Hudiy build routes no physical input to third-party overlay webviews, so `tools/keyboard_shim.py` (unit `hudiy-diag-keys`, installed by `backend/deploy/install.sh`) reads the head-unit knob at the input layer (auto-discovered - any device speaking Hudiy's key scheme works) and drives the page's `window.__diagKeyNav()` via the QtWebEngine DevTools socket — inert unless the overlay is visible. Overlay lifecycle: Hudiy re-shows the singleton webview on relaunch, so the page undoes its exit teardown on attach (anything else = blank relaunch or white-flash; details in `tools/README.md`). Privacy: gate **executed 2026-09-14** (synthetic VIN/CAL-ID/CVN in fixtures + docs; topology genericised; shim made device-configurable). Repo published 17 Sep 2026 (MIT).

**Update 2026-09-14 (input):** the app takes input however the user has it - touch and mouse natively, knobs/keyboards/remotes through Hudiy's own bridge contract (Hudiy's scheme, not an app-specific one). A compatibility fallback (`tools/keyboard_shim.py`; auto-discovery, yields to native delivery, `DIAG_SHIM_DISABLE=1` to turn off) covers builds that do not deliver key events to overlay webviews. See `docs/HUDIY_KEYBOARD_CONTROL_SCHEME.md` section 4.

**Update 2026-09-16:** installer finalized and bench-trialed end-to-end on the reference unit — ssh-safe systemd bus probe, services restarted on update (the copied code is what runs), knob shim started on fresh installs, atomic Hudiy config merge with backups, and an automatic closing reboot so everything is live on the next boot (`--no-reboot` optional). Bench finding baked in: a custom overlay's `visibleOnActions` must stay empty — a non-empty list silently suppresses the overlay paint.

**Update 2026-09-17:** Published publicly: **https://github.com/jkir4n/hudiy-diagnostics** — MIT license. One-liner: `bash <(curl -fsSL https://raw.githubusercontent.com/jkir4n/hudiy-diagnostics/master/install-bootstrap.sh)`.

## License

MIT — see [`LICENSE`](LICENSE).

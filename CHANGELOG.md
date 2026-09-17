# Changelog — Hudiy Diagnostics

All notable changes. Format: date — phase — what.

## 2026-09-17 — Max-data pack (frontend, Phase 3b)

### Added
- S9 Deep scan (`frontend/diag.html`, `diag.js` `renderDeep`): entry from the S2 footer (or any time — it runs its own discovery), progress on the shared S1 screen with a discovery+allpids legend, then a results grid — decoded values where the table knows them, bare-hex rows for unscaled answers, `no data` where the ECU stayed silent, plus a decoded/raw/silent breakdown. A deep run lands in its own store and never clobbers the cached health report; a full scan already carries the same rows, so S9 reads those when no deep run exists.
- S6 full Mode 06 view: every enumerated block renders, including unanswered ones (honest `Not answered (…)` with advertised-vs-probed note); every test row is an expander (tap / knob / key) revealing the raw record, raw value/min/max and the scaling note; unknown-scalings show raw ints instead of dashes.
- S10 Compatibility (`renderCompat` + `loadCap`): capability dump from `GET /capability` — PID banks, Mode 06 MID list, observed mode support, captured identity, app version + coverage — plus the paste-ready sheet text with Copy (clipboard + fallback) and Download `.txt` export actions, entered from the S8 footer.
- S1 legend gains the `allpids` chip; S8 download link joins the knob focus ring (was touch-only).

### Verified
- Replay backend (`DIAG_MODE=replay`, port 44414): every new route curl-verified (`/scan?sections=discovery,allpids` → 20 rows; `/capability` JSON + text; `/diag/capability` alias).
- Scripted browser walk (`?bridge=dom`, 31 checks, zero console errors): full scan → S2; deep scan → S9 (decoded rpm renders, silence stays `no data`); S6 expander opens raw records; S10 shows VIN/banks/MIDs/sheet text after a full scan and honest `partial scan (allpids, discovery)` + `not reported` identity after a deep-only scan; `window.__diagKeyNav` reaches and fires Deep scan pointer-free; arrow-key fallback re-runs it. Screenshots reviewed (one real find fixed: headline/breakdown counting + a duplicated raw-hex value).

## 2026-09-17 — Max-data pack (backend, Phase 3a)

### Added
- `allpids` scan section (`GET /scan?sections=allpids`, in the full scan): reads every advertised PID once, decoded with the existing PID table; PIDs without a decoder render as raw-hex rows under their hex id, NO DATA stays an empty answer. Report text/CSV render the new block.
- Bitmap-chain discovery: the Mode 01 walk (0100 -> 0120 -> ...) and the Mode 06 page walk (0600 -> 0620 -> ...) follow each bitmap's next-range bit (max 8 pages each; `DIAG_MODE06_WALK_RANGES=0` pins Mode 06 to 0600). Cars with PIDs/monitors past the old fixed depth are now fully mapped; cars without them cost fewer queries.
- `GET /capability` (`?format=json|text`): compatibility sheet from the last report without touching the car — PID banks, Mode 06 MID list, observed mode support (02/05/0A as probed; 05 honestly "not probed"), captured identity, app version + timestamp + data source (live|replay). Text form pastes into a GitHub issue as-is.
- `backend/tests/test_diag_maxdata.py`: 18 tests (chain walking incl. early-stop and walk-off, undecoded/unnamed rows, full Mode 06 enumeration of an unknown MID, capability shape + partial-scan flagging, `/capability` routes + alias + bad format).

### Verified
- Suite 115 passed / 2 skipped (baseline 97 / 2; skips are the pre-existing real-`Api_pb2` ones), plus replay manual check: full scan (61 queries, 22 PIDs advertised, EGR/boost via probe, 02/0A not-supported as recorded) and `/capability` JSON + text curl-verified against `DIAG_MODE=replay` on port 44499.

## 2026-09-17 — Published publicly (MIT)

### Changed
- **Public release**: https://github.com/jkir4n/hudiy-diagnostics — MIT license added; clone/curl one-liners now carry the real URL; `install-bootstrap.sh` piped mode defaults its clone source to the public repo.
- Final pre-publish privacy gate: all 19 checks zero (generic + local identifier patterns), working tree AND full history; suite 97 passed / 2 skipped (real-`Api_pb2` tests skip when absent).
- `docs/GITHUB_PUBLISH_PRIVACY_GATE.md` updated from "not published" to the published record.

## 2026-09-16 — Input: ghost-navigation fix (hidden-time knob events were replayed on open)

### Fixed
- `tools/keyboard_shim.py`: false input on open (user-reported live). While the overlay was hidden the shim never read the knob device, so Hudiy-menu navigation (scrolls + the click that opens the app) accumulated in the kernel queue and was replayed into the freshly-shown page: the selection cycled, a stray activate landed on Scan or the exit path, and a later open could look normal (timing-dependent). The shim now drains (discards) the device queue the entire time the overlay is hidden, plus a short (~0.35 s) settle window after each show; only events made while the page is up are forwarded. Exit is covered by the same rule (hidden = discard).
- `backend/tests/test_keyboard_shim.py`: drain tests (pipe-driven; press-only counting, empty-queue no-op).

### Verified
- Reference unit, live: 40+ menu steps discarded between shows (0 leaked), 2 in-flight events caught at the show-flip, in-page navigation delivered 1:1 afterwards, post-exit menu activity discarded.

## 2026-09-16 — Installer bench trial: auto-reboot, ssh-safety, overlay-config hardening

### Added
- `backend/deploy/install.sh`: auto-reboot at the end of a successful install (detached `setsid`, ~3 s delay — survives the ssh session drop) so every change is picked up on the fresh boot; Hudiy reads its menu/overlay config only at start. `--no-reboot` skips it; without passwordless sudo a manual command is printed instead; a failed health check never reboots.

### Fixed
- `need_systemctl_user()` false-negatived on every non-interactive ssh run (bailed on an unset `XDG_RUNTIME_DIR` before even trying) — it now recovers `/run/user/$(id -u)` and probes the user bus directly.
- Re-running the installer is an update: services are now restarted after the file sync so the copied code is what runs (`enable --now` alone left an already-running old process in place until reboot).
- The wheel-key shim unit is now enabled + started by the installer — fresh installs previously ended with the unit copied but never active. Safe everywhere: without a matching device, or before the `input` group re-login, it idles and re-scans instead of crashing.
- `frontend/hudiy/merge_config.py`: config writes are now atomic (temp file + `os.replace`) and reads tolerate a UTF-8 BOM; a no-change run no longer prints the "restart Hudiy" hint. `--uninstall` now states explicitly that the Hudiy menu/overlay entries are left in place.

### Bench findings (reference car, live)
- **`visibleOnActions` must stay `[]` on a custom overlay.** With `["diag_show"]` every step *succeeds* — Hudiy dispatches, the lane logs the dispatch, `SetCustomOverlayVisibility(ALWAYS)` is accepted, the webview is created and fully loads — but the overlay never paints. Reverting to `[]` + a Hudiy restart restores it immediately. `merge_config.py` pins `[]` (self-healing configs written by the earlier version), the fragment + a new test assert the rule, and `docs/HUDIY_UI_API_INVENTORY.md` carries the caution.
- Full rehearsal on the live tuned install: default run → auto-reboot → back in ~50 s → all green (services active, menu entries, overlay opens, reboot-button re-arms); `--no-reboot` run → clean idempotent no-op. Backend test suite green.

### Docs
- `frontend/hudiy/README.md`: bench section rewritten as resolved. `install-bootstrap.sh`: passes flags through (e.g. `--no-reboot`) and notes the closing reboot covers the Hudiy restart. Root `README.md` updated.

## 2026-09-14 — Git history purge (pre-publication privacy pass)

### Changed
- All 48 commits rewritten in place (`git filter-repo`): the original VIN / CAL-ID / CVN / tailnet address / paths / name mentions were replaced in every historical blob and commit message; one fixture typo-fix commit collapsed to empty and was auto-pruned (47 commits remain). Verified zero residuals across all refs (blobs + messages); the working tree is byte-identical to before the rewrite. The original history is archived offline only — never uploaded.
- A plain `git push` of `master` is now safe for publication; the pre-scrub marker tag has been retired. See `docs/GITHUB_PUBLISH_PRIVACY_GATE.md`.

## 2026-09-14 — Input follows the user: wheel support, cooperative fallback, install fix

### Added
- `frontend/diag.js`: mouse-wheel navigation (same focus walk as keyboard/knob; genuinely scrollable regions such as the report `<pre>` keep native scrolling). Header comment reframed: Hudiy's bridge is the primary input path - nothing app-specific.
- `tools/keyboard_shim.py`: the fallback now yields whenever the page reports native input focus (`window.hudiy.inputFocus === true`) - on installs where Hudiy delivers input to overlays it stays out of the way entirely.

### Fixed
- `backend/deploy/install.sh` never copied `tools/` into the installed tree, so a fresh install left the shim unit pointing at a missing file. The installer now copies `tools/` (replace-style, like the other trees).

### Docs
- `docs/HUDIY_KEYBOARD_CONTROL_SCHEME.md` section 4: input coverage matrix (touch / mouse / keyboard / knob / fallback) + one-line-install note; `tools/README.md` reframes the shim as the compatibility fallback.

## 2026-09-14 — Knob input generalized to Hudiy's control scheme (universal adapter)

### Changed
- `tools/keyboard_shim.py` is now a Hudiy-scheme input adapter: it recognizes the full navigation vocabulary - keys `1`/`2` (Hudiy's scroll left/right), arrow keys, `enter`, `escape`, plus `KEY_SCROLLUP/DOWN`, `KEY_KPENTER`/`KEY_OK`, `KEY_BACK` and mouse-style `REL_WHEEL`/`REL_HWHEEL` encoders - and normalizes any of them to the page's prev/next/activate/back. Device auto-discovery (name hints + capability scan) replaces the fixed `/dev/input/event4`; `DIAG_SHIM_DEVICE`, `DIAG_SHIM_MATCH`, `DIAG_SHIM_EXCLUDE`, `DIAG_SHIM_DISABLE` tune it; `--scan` prints device candidates and exits.
- `backend/tests/test_keyboard_shim.py` - translation-table and device-scoring tests (pure logic; no hardware needed).
- `docs/HUDIY_KEYBOARD_CONTROL_SCHEME.md` - the scheme is now explained from upstream (keyboard `1`/`2` = scroll left/right; the old "1 and 2 vs 5-6" device note is resolved) with the adapter's translation table (section 4). `tools/README.md`, `README.md` updated to match.

### Notes
- Reference-car behavior unchanged (same device and mapping; discovery picks it).

## 2026-09-14 — Publish readiness: privacy gate executed + universality pass (NOT published)

### Changed (privacy scrub — see `docs/GITHUB_PUBLISH_PRIVACY_GATE.md`)
- Reference-vehicle identity scrubbed: VIN / CAL-ID / CVN replaced with synthetic placeholders across raw + decoded fixtures, `docs/DECODED_FIXTURES.md`, `docs/V1_SPEC.md`, tests, README and this changelog; multi-frame hex payloads recomputed byte-consistently.
- Topology genericised: tailnet address -> `car@<PI-IP>` placeholder; `/home/<user>/...` -> `~/...`; owner name/handles and dev-machine references removed from docs and comments.
- `docs/GITHUB_PUBLISH_PRIVACY_GATE.md` rewritten as an executed checklist with re-audit tooling (`tools/privacy_audit.sh` + local-only `tools/privacy-patterns.local`, gitignored) and the fresh-history push recipe (pre-scrub tag: `pre-scrub-2026-09-14`).
- `tools/keyboard_shim.py` universalised: `DIAG_SHIM_DEVICE`, `DIAG_SHIM_LANE_STATUS` / `DIAG_HTTP_PORT`, `DIAG_SHIM_CDP` overrides; an absent knob device now waits quietly instead of exiting (no restart loop on knobless installs).
- Minor: stale vehicle-model remark removed from `decoders.py`; stale shim install note corrected.

### Verified
- Backend test suite green — same counts as pre-scrub (2 skipped: real `Api_pb2` only where present); re-audit greps all zero; replay smoke serves `/health`, `/app/*`, and a report whose VIN is the synthetic placeholder.

## 2026-09-14 — link chip froze at "unknown" on the car (frontend hotfix)

### Fixed
- `frontend/diag.js`:
  - `pollAllowed()` no longer gates health polling on the bridge's `activated`
    flag: this Hudiy build keeps `activated=false` even while the overlay is
    shown (same input-routing quirk as the wheel), so the gate silently froze
    all `/health` polling and the link chip stayed at "Link state unknown".
    Polling now follows page visibility only.
  - `H.onActivatedChanged` no longer stops polling on `activated=false`; it
    calls `restartPolling()`, which re-evaluates visibility.
  - `LINK_WORD`/`STATE_SEV` now spell the wire value `stale-handle` (hyphen,
    matching `backend/diag/lane.py`). Previously `stale_handle`/`stale`, so a
    stale link rendered as raw "Link: stale-handle" with no severity mapping.
- `frontend/diag.css`: pill/hero warning selectors match
  `[data-state="stale-handle"]`.

## 2026-09-14 — Material 3 colour-token layer (frontend theming)

### Changed
- `frontend/diag.css`: every colour is now a token reference. New `--m3-*`
  M3 scheme layer (~50 custom properties covering all 61 bridge
  colourScheme roles + fixed variants) with a static dark Okabe-Ito
  fallback scheme; `--ok/--warn/--bad/--info/--blue` and the surface/text
  vars bind to it. Translucent severity tints (`--ok-line/-bg`,
  `--warn-line/-bg`, `--bad-line/-bg`) replace inline `rgba(...)` literals.
  `body.scheme-light` now carries a static light fallback scheme instead
  of hardcoded greys. Focus ring is 3px per the M3 focus-indicator spec.
- `frontend/diag.js`: `applyScheme()` consumes all string hex tokens on
  `hudiy.colorScheme` (was 3 of 61) into the `--m3-*` layer, re-derives
  severity tints (ok=tertiary, warn=tertiaryContainer, bad=error,
  info=primary), toggles `body.scheme-light` from `darkThemeEnabled`, and
  restores Okabe-Ito tints when the bridge is absent (TEST-BOTH-PATHS).

### Not done (documented in docs/M3_UI_RESEARCH.md §5)
- Component geometry, typography scale tokens, elevation tokens.

## 2026-09-11 — one-line install path

### Added
- `install-bootstrap.sh` (repo root): entire install now one command —
  `git clone https://github.com/jkir4n/hudiy-diagnostics.git && cd hudiy-diagnostics && bash install-bootstrap.sh`.
  Handles the piped `curl | bash` case (clones `DIAG_REPO_REMOTE` into a temp
  dir), then wraps `backend/deploy/install.sh`. Ends by printing the two
  manual extras (input group, Hudiy restart). Verified: in-repo dry-run and a
  piped full install (lane answered :44414/health) — both clean.
- README: Quickstart at the top.

## 2026-09-11 — wheel/knob input + overlay lifecycle fixes (uncommitted batch landed)

### Added
- `tools/keyboard_shim.py` + `backend/deploy/hudiy-diag-keys.service` (new):
  wheel/knob -> diagnostics page shim. This Hudiy build never routes physical
  input to third-party overlay webviews (CDP-proven), so the shim reads the
  Elecrow knob at /dev/input/event4 and fires `window.__diagKeyNav()` via CDP
  :9222, gated on overlay visibility. Installer now deploys the unit and
  checks the `input` group.
- True knob map captured per-direction (the earlier 1/2/3-chain guess was
  wrong): code 2 = detent LEFT (prev), code 3 = detent RIGHT (next), code 28
  (ENTER) = knob center press, code 1 (ESC) = back fallback. Device = Elecrow
  knob (owner-observed); turns are scroll left/right, click is enter.
- `frontend/diag.js`: self-contained `window.__diagKeyNav()` — walks the
  active screen's visible `.ctl` nodes + the global `#actions` bar + the
  top-bar `#back` button, paints the `.focused` ring, wraps around, activates
  on enter, handles back. The closure's moveFocus returned false with visible
  buttons present (its root search missed the `#actions` bar), so the shim
  path must not depend on page state.
- `frontend/diag.css`: `.icon-btn.focused` joins the focus-ring selector —
  the top-bar back button was walkable but never painted its ring.

### Fixed
- `backend/diag/config.py`: DIAG_MODE="bridge" silently fell back to
  auto->standalone and broke scans ("No scan data"); accepted as an alias of
  proxy (deployment env file already used it).
- Exit -> menu relaunch painted BLANK: Hudiy keeps one webview alive per
  overlay url and merely re-shows it, so the exit teardown
  (body.exited + hidden #app) survived. diag.js now clears that state in
  `window.hudiy.onAttached`; the shim additionally reloads the page on
  visible-edge ONLY when the exited state is present.
- White-screen flash mid-use: the shim's earlier unconditional reload on
  every visibility edge was the cause; replaced by the exited-state check.
- tools/keyboard_shim.py debug knob: SHIM_DEBUG_LOG=... (one line per
  dispatch). Double-enter suspicion on 11 Sep resolved by instrumentation:
  one press -> one dispatch -> one click; early "doubles" were rapid
  re-presses (the knob chatters, one turn can emit 5-6 detents).

### Docs
- tools/README.md: keyboard-shim section (device map, installer deploys it,
  visibility-edge behavior + why blind reload is forbidden).
- docs/HUDIY_KEYBOARD_CONTROL_SCHEME.md: per-direction device-observed table.

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
- VIN `WVWZZZ1KZAW555555` (synthetic placeholder — scrubbed); ECM "ECM-EngineControl" (diesel VW).
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
- Proxy-lane bridge, end to end: the race-dash charts app gained `POST /diag/obd` (a route on the listener it already owns, so no second port and no second OBD client) and the diagnostics side now defaults to it — `DIAG_MODE=bridge` + `DIAG_CHARTS_BRIDGE_URL=http://127.0.0.1:44411/diag/obd` in `backend/diag/config.py`, the `install.sh` env template, `backend/README.md` and `docs/HUDIY_UI_API_INVENTORY.md`. Deployed to the reference install after confirming the live `charts.py` matched the captured copy byte-for-byte (backed up to `~/backups/charts.py.pre-diag-bridge.bak`, card path `/tmp/charts.py.bak-2026-09-10`); `~/.config/hudiy-diagnostics/env` written with the bridge mode, unit deliberately left unstarted. Verified live by driving the lane's own `BridgeHost` + decoders through the bridge against the running engine (support bitmap, rpm, multi-frame VIN reassembly, 0 DTCs, `0A00` = no data) with the charts SSE stream serving concurrently. Race-dash change is branch `diag-bridge` in the race-dash repo (patch exported — the dev-workstation checkout is the upstream of record).

### Fixed
- `report.py` text/csv renderers crashed on every real report: they treated the PID-support *map* (`{"0100": [4,5,...]}`) as a flat list and formatted its keys with `0x%02X`. Now rendered via `_hex_list` (int or pre-formatted), and CSV gained the support/`self-test` rows it was missing, so a CSV reader can also see what the car answered.
- `scan.py` reported link-lifetime totals as per-scan traffic. `scan.queries/timeouts/retries/failures` are now deltas measured across the scan — on a long-lived service the old numbers grew with every scan and read as if one scan had sent them.
- `scan.py` called `decoders.summarize_codes()` with the flat stored/pending/permanent code lists instead of the decoded `dtc_list()` mappings it buckets on; and with no fault phase run it no longer fabricates a "0 codes, clear" summary (it passes `None`, which degrades the verdict to unknown rather than falsely reporting the car as ready).

## 2026-09-10 — Phase 2c (backend + frontend): the Hudiy control lane (overlay show/hide)

### Added
- `backend/diag/hudiy_control.py` — a Hudiy TCP API client (stdlib `socket` + `struct`, protobuf only for the messages) that owns our slot on `127.0.0.1:44405`: `MESSAGE_HELLO_REQUEST` (name `HudiyDiagnostics`, API 1.3) then `MESSAGE_REGISTER_ACTION_REQUEST` for our menu action, both on the *same* session, answered by a daemon thread that also keeps `MESSAGE_PING` alive. When Hudiy dispatches *our* action it re-asserts the overlay by sending `SetCustomOverlayVisibility` on every dispatch (Hudiy never re-shows a custom overlay on its own); another app's action is counted as ignored, never acted on. Happy path never touches this lane.
- `POST /ui/hide` in `backend/server.py` — the page's Exit path. It reports `ok` ("the request was handled") separately from `sent` ("Hudiy actually got the message"), so a dead control link cannot read as a failed request; `/health` grew a `hudiy` block (state, `registered`, `sessions`, `dispatches`, `last_visibility`, `reason`) and `cfg.hudiy_control_enabled` / `--no-hudiy-control` turn the lane off.
- `frontend/diag.js` — the exit path: a footer **Exit** button (S0) and **Back on S0** both `POST /ui/hide`, then add `body.exited` and detach our own DOM, so the car shows through even if the ask never lands (a 400 ms timer is the belt). Hudiy provides no close of its own, so this is the only way out of a custom overlay.
- `backend/tests/test_hudiy_control.py` — 25 tests: a fake Hudiy speaking the real wire framing over a loopback socket (hello-before-register ordering, refused hello/registration retried and loud, show-on-dispatch ×3, foreign action ignored, hide sends `NONE`, reconnect + re-register after a drop), degradation with no `Api_pb2` (`state: unavailable`, `start()` false, no false claim of hiding), `locate_api_file` resolution, and two compatibility tests that load the box's real `Api_pb2.py` (skipped when absent, run via `DIAG_HUDIY_API_PB2`).
- `tools/smoke_control_lane.py` — end-to-end smoke: the real server + Hudiy's real `Api_pb2.py` over fresh loopback sockets, driving `/health`, a dispatched action and `POST /ui/hide`, and asserting the frames that actually reach Hudiy. Exists because the unit tests build their messages from a stub module; this is the only check that runs the generated protobuf (required proto2 fields included) through a real socket and the real route.

### Notes
- The control lane is discovered, never assumed: `Api_pb2` is located at runtime (`DIAG_HUDIY_API_PB2`, then `~/.local/share/hudiy-diagnostics`, `/opt/hudiy-diag`, `/opt/hudiy-obd-charts`). With no module the lane stays `unavailable` and logs why — the app still serves `/health` and every read-only endpoint. Nothing autolaunches; the lane starts with the app and reconnects with 2.0 s → ×1.5 → 30 s capped backoff plus 0.1–1.0 s jitter.
- Suite now 86/86 (61 + 25). With Hudiy's real `Api_pb2.py` importable the two real-API tests run against the actual generated module instead of skipping; `docs/GITHUB_PUBLISH_PRIVACY_GATE.md` test-floor line updated to match.
- Verified end-to-end against the box's real `Api_pb2.py`, not just the stub: 13/13 checks in `tools/smoke_control_lane.py` (`DIAG_HUDIY_API_PB2=/tmp/hudiy_api python3 tools/smoke_control_lane.py`). The frames that reached the fake Hudiy were `HELLO_REQUEST`, `REGISTER_ACTION_REQUEST`, `SetCustomOverlayVisibility` NONE (the registration reset), NONE→ALWAYS on dispatch, and NONE on `POST /ui/hide` — which answered `{"ok": true, "sent": true}`. The real module's proto2 messages carry required fields (`HelloResponse.app_version`/`api_version`, `RegisterActionResponse.action`); every message this lane *sends* sets its required fields, so no partial-send is possible.

## 2026-09-10 — Phase 2b (frontend): the diag overlay page S0–S8

### Added
- `frontend/diag.html` + `frontend/diag.css` — the single overlay page: fixed 800×480, nine screens (S0 home, S1 scanning, S2 health summary, S3 fault-code list, S4 code detail, S5 readiness wall, S6 Mode 06 tests, S7 identity, S8 report/settings), severity colours restricted to the Okabe-Ito set, one meaning per colour.
- `frontend/diag.js` — the state machine and lane client: `/health` on a 5 s poll (paused while the page is hidden or detached), user-triggered `/scan` (full or `?sections=` quick), lazy `/dtc` lookups, `/report` text/csv/json into a `<pre>`, VIN decode. Rule-6 input parity: the `hudiy={}` bridge (`onMoveToNext/PreviousControl`, `onTriggered`, `onGoBack`/`onGoLeft`/`onGoRight`, `inputFocus`/`activated`), a DOM keydown fallback for development, tap targets ≥48 px, swipe-right = BACK, swipe-left = tab, vertical swipe = list scroll. `?bridge=dom|bridge` forces either path (`window.__DIAG_BRIDGE_MODE`); no autolaunch, nothing OBD-facing leaves the backend.
- `frontend/hudiy/` — install-time Hudiy templates (`overlays.json` identifier `diag`, `applications_menu.json` Diagnostics entry, Race Dash pattern) plus `merge_config.py`, which MERGES the fragments into a live config (never overwrites), backs the file up first and is a no-op on re-run. `API_BRIDGE`-free: registration is file-config only.
- `GET /app/*` static route in `backend/server.py` (read-only, stdlib only) and 20 new endpoint tests; 61/61 green.
- `frontend/README.md` — screens, the rule-6 parity table (every screen × touch/keys/gestures), colour rules, the readiness-verdict honesty rule and the bench-question (not code) gaps.

### Fixed
- S1's Cancel button was wired with inverted enablement (`!S.busy` passed as the `enabled` argument), so it was disabled for exactly as long as a scan was running — the one state where it is the only way out of the screen. It now enables while a scan is in flight, and the cancel path was verified in the browser (abort fires once, the page returns to S2, or S0 with no cached report, and says the backend read finishes on its own).
- S1's section chips read as a dead stepper; they are a legend of what the scan reads, so they are now labelled, and the README states why the progress bar is an indeterminate sweep (the lane answers `/scan` as one request, so no in-flight section signal exists — the page does not invent a percentage).
- `renderTiles()` carried a dead `host` variable. `frontend/README.md` claimed S0 shows the four tiles (they live on S2 only) and described S1 as "section-by-section progress".
- `backend/README.md` said the installer copies `backend/` + `fixtures/` only, and never documented the Hudiy registration step or the controlled-restart requirement; both are now documented (merge-not-overwrite, timestamped backup, no live-patching, restart to pick up the menu entry).


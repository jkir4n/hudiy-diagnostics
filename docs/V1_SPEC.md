# Hudiy Diagnostics â€” v1 Spec (research-complete, build-ready)

This is the single entry point for Phase 2 implement cards. Everything here is
backed by files in this repo: protocol research (`OBD2_DIAGNOSTICS_RESEARCH.md`),
constraint decisions (`ARCHITECTURE_NOTES.md`), feature survey
(`FEATURE_SURVEY_FINDINGS.md`), and live-car evidence (`fixtures/`).

## Hard rules (violating any of these = wrong)

1. **Universal**: zero vehicle/machine-specific code. Every vehicle fact
   (PID support, OBDMID map, DTC support) discovered at runtime via
   0100/0120/0140/0160 + 0900/0200 probing. A feature whose support bit is
   absent is rendered as not-supported â€” never assumed, never hidden.
2. **Menu-launched only**: no autolaunch. Registered in
   `applications_menu.json` (see race-dash entry pattern).
3. **OBD access**: the app CANNOT open its own OBD client. Hudiy serves OBD
   responses to exactly one process (proven to exhaustion, 10 Sep â€”
   `ARCHITECTURE_NOTES.md`). v1 backend = diagnostics lane proxied through
   the race-dash charts process (its `send_obd_query` path); graceful
   standalone mode when race-dash is not installed.
4. **ELM-safe query discipline**: single-flight (one outstanding query),
   timeout â‰¤ 15 s, one retry max. Multi-frame responses are SAFE through the
   served client (the round-2/3 'wedge' was a starved-client artifact â€”
   corrected 10 Sep). `NO DATA` arrives as an EMPTY STRING.
5. **Transport quirk**: after a car power-cycle, Hudiy's ObdManager can go
   stale (ELM BT 'Connected', clients subscribed, but every query silently
   dropped; sometimes visible as `ObdManager cancel id: N` log lines).
   Detection = OBD age climbing while BT connected. Recovery = Hudiy app
   restart (kill -9 + relaunch; validated 2x). The diagnostics UI must show
   an 'ECU reconnecting' state in this window, never a hang.

6. **Input modalities — touch + keys + gestures, feature parity**: the app
   is fully operable through (a) touchscreen, (b) keyboard navigation keys
   (UP/DOWN/LEFT/RIGHT move a visible focus ring, ENTER activates,
   ESC goes back - the key vocabulary is the KeyType enum in Api.proto:
   UP/DOWN/LEFT/RIGHT, SCROLL_LEFT/RIGHT = the knob, ENTER, BACK, HOME,
   TOGGLE_INPUT_FOCUS. Pages receive keys through the hudiy={} JS bridge
   contract - onMoveToNextControl/onMoveToPreviousControl return true=consumed,
   onTriggered = ENTER, onGoBack false = Hudiy handles back (knob always wins),
   focus ring renders from hudiy.colorScheme; see
   docs/HUDIY_KEYBOARD_CONTROL_SCHEME.md, and (c) gestures (horizontal swipe = back, vertical =
   scroll). Every interactive element is a real focusable control with a
   tap handler AND a key activation path; nothing is click-only or
   gesture-only. Frontend acceptance: every screen operated three ways —
   taps only, keys only, gestures.
## v1 feature set (from FEATURE_SURVEY_FINDINGS Â§6, fixture-mapped)

| # | Feature | Data | Fixture status | App behavior on this car |
|---|---------|------|----------------|--------------------------|
| 1 | One-tap health scan | Modes 03, 07, 0A + Mode 01 MIL/readiness | 03=4300, 07=4700 (clean) captured; 0A NOT SUPPORTED (bitmap + stale echoes) | scan runs the 4 queries as one sequence; permanent-DTC section renders 'not supported' |
| 2 | DTC list + text + severity | Mode 03/07 codes; Wal33D/dtc-database SQLite (MIT, 18,805 rows, bundled offline) | DTC response shape captured | generic lookup first; maker-context lookup; unknown manufacturer code shows raw code + 'manufacturer-specific' fallback copy |
| 3 | Freeze frame per DTC | Mode 02 | **NOT SUPPORTED** (0200/0202 empty, 6/6 cycles, 10 Sep) | feature hidden with 'not supported by this ECU'; report uses 0145/0149 (time since DTCs cleared / MIL on) instead â€” both supported |
| 4 | Emission readiness card wall | Mode 01 (two monitor groups) + Mode 06 | readiness + Mode 06 O2/EGR/boost captured round-1 | green/red/gray chips (Complete/Incomplete/Disabled), one verdict line |
| 5 | Mode 06 monitor summary | Mode 06 OBDMID/TIDs | O2/EGR/boost TID data captured | value-vs-limits pass/fail rows, named monitors when known (EGR/boost/PM filter), raw expander for unnamed |
| 6 | Vehicle/ECU identity | Mode 09 (VIN/CALID/CVVN/ECU name) | VIN, 'ECM-EngineControl', CALID '00Z000000Z  0000', CVN 0xA5A5A5A5 captured | identity panel shows raw values; optional vPIC decode is best-effort (Indian VW coverage weak: verified live 10 Sep â€” model fields empty) |
| 7 | Clear DTCs (Mode 04) | Mode 04 | response shape known (protocol research) | two-screen safety confirm (consequence list + fix-first checkbox, OBDAD pattern); permanent-code honesty note |
| 8 | Scan report export | all of the above | â€” | text + CSV, mechanic-shareable |
| 9 | Runtime discovery | 0100/0120/0140/0160/0200 + 0900 | full support map COMPLETE for this car (through 01A0; nothing beyond 0x5F) | runs at every scan start; feature availability follows the live bitmaps |

Complete PID support map for this car (all captured):
01-20: 01 04 05 0B 0C 0D 0F 10 11 13 1C 1F 20 Â· 21-40: 21 23 24 2C 2D 30 31
33 40 Â· 41-60 (from 0140=CC D2 00 00): 41 42 45 46 49 4A 4C 4F Â· 61+: none
Â· Mode 02: not supported Â· Mode 0A: not supported.

## Explicitly OUT of v1 (from FEATURE_SURVEY_FINDINGS)

- Live gauges/trip computer/graphs/HUD/0-60/track recorder â€” race-dash owns
  live telemetry. This app is purely diagnostic.
- Coding/flashing, subscriptions, cloud DTC lookup, vendor-locked anything.
- Mode 08 service routines (DPF regen): display readiness only, later.
- Multi-ECU/all-module scan: engine ECU only in v1 (our transport reaches
  the engine ELM path); brand-deep module scan is FORScan/OBDeleven territory.

## Backend shape (proxy lane, Phase 2b slice 1)

- Lives inside/alongside the race-dash charts process (single served client).
- Endpoints (served by charts or sibling in same process group):
  - `GET /diag/scan` â€” runs the full scan sequence, returns structured JSON
  - `GET /diag/status` â€” scanner state (idle/scanning/stale-handle/reconnecting)
  - `GET /diag/report.(txt|csv)` â€” generated report
  - `POST /diag/clear` - Mode 04 clear, gated on `confirm=yes` (query or
    POST body, form or JSON); answers the seam contract
    (`ok/status/mode04_positive/duration_s/codes_seen_before/followup/` +
    `permanent_codes_note`), `unsupported`/`refused` structured 200s, or a
    502 that always says the codes were NOT confirmed cleared
- Sequence discipline: one request at a time through `obd_lock`, 1.5 s
  inter-query spacing (charts poller precedent), abort-on-first-timeout for
  the scan set, guarded single attempt for 0904/0906.
- Never gate the charts telemetry poller on the diagnostics lane (race-dash
  architectural rule: polling never depends on presentation health).

## Frontend shape (Phase 2b slice 2, consumes the contract above)

- Menu-launched page, mobile/kiosk layout (labwc/DSI screen).
- States: idle â†’ scanning (progress per mode) â†’ results (cards per feature,
  honoring support bits) â†’ report share.
- Copy patterns: FIXD severity verdict line, OBDAD consequence list for
  clear-DTCs, BlueDriver 'what was happening' framing where applicable.

## Build order (standing directive)

Backend specialist card first (this spec + ARCHITECTURE_NOTES + fixtures as
constraint block), frontend card second consuming the backend contract.

## Phase 3a — max-data pack (backend, 2026-09-17)

Same hard rules as v1 (universal, menu-launched, proxy lane, query
discipline, degraded-never-500). What it adds on top of the v1 scan:

- **Full-PID read** — new `allpids` scan section (`GET
  /scan?sections=allpids`, included in the full scan). Discovery walks the
  Mode 01 bitmap chain (0100 -> 0120 -> ... following each bitmap's
  next-range bit, max 8 pages) and `allpids` reads every advertised PID once
  (bitmap queries skipped - already decoded), decoded with the existing PID
  table; PIDs without a decoder render as raw-hex rows under their hex id,
  NO DATA stays an empty answer.
- **Full Mode 06 enumeration** — discovery walks the OBDMID pages the same
  way (0600 -> 0620 -> ... until a page clears its next-page bit;
  `DIAG_MODE06_WALK_RANGES=0` pins it to 0600). The mode06 phase queries every
  advertised OBDMID plus the probe list, so unlisted-but-answering monitors
  are enumerated; unnamed monitors stay raw (hex OBDMID/TID).
- **Capability dump** — `GET /capability` (JSON) and
  `GET /capability?format=text` (plain text for GitHub issues): PID banks,
  Mode 06 MID list, observed mode support (02/05/0A as probed), captured
  identity, app version + timestamp + data source (live|replay). Built from
  the last report without touching the car.

# AGENTS.md — Hudiy Diagnostics

**Last updated:** 2026-09-17 (published; licensing/provenance note added)

## 1. What this project is
A Hudiy **menu-launched** car diagnostics app. Backend, frontend and the wheel/knob shim are built and live on the reference head unit. Published publicly 17 Sep 2026 — github.com/jkir4n/hudiy-diagnostics, MIT (privacy gate 2026-09-14). Installer bench-trialed 2026-09-16 on the reference unit: ssh-safe, auto-reboot at the end, atomic config merge with backups.

Non-negotiable requirements (owner's verbatim constraints):
1. **No autolaunch.** Opened ONLY via the Hudiy settings/applications menu.
2. **Universal.** "It should be able to deployed to any hudiy instance, so it should be universal." No system-specific code baked in — vehicle capabilities are DISCOVERED at runtime (PID bitmap, OBDMID map, VIN via Mode 09), never hardcoded.
3. Read all OBD, check for errors, run diagnostics.

## 2. Environment facts (verified on the reference head unit, 2026-09-09)
- Hudiy TCP API `127.0.0.1:44405`, protobuf messages in `common/Api_pb2.py`.
- OBD chain: Hudiy ⇄ ELM327 Bluetooth (RFCOMM) ⇄ ISO 15765-4 CAN 11-bit (VW).
- Race Dash (deployed sibling): charts.py :44411 (SSE API), toggle daemon :44413, user systemd units `hudiy-obd-charts`, `race-dash-screensaver`.
- Hudiy app lifecycle: labwc autostart only (`~/.hudiy/share/hudiy_run.sh`). `hudiy.service` is a stub (ExecCondition unmet under graphical.target) — `inactive` is NORMAL.
- Pi: ssh `car@<PI-IP>` (Tailscale), passwordless sudo, user units, LF files, no journald — Hudiy logs `~/.hudiy/log/hudiy.N.log` (newest by mtime; rotation index grows).
- Clock: can lag by minutes right after a boot until time sync (observed 22 Sep 2026) — minute-level forensics near a boot can mislead.
- Menu entries: `applications_menu.json` (Race Dash pattern at line 226: Material icon, Hudiy category, action string).

## 3. HARD CONSTRAINTS (from live probing — do not re-learn the hard way)
1. **Single served OBD process (definitive, 09 Sep night).** Hudiy serves OBD query responses to exactly ONE process — the race-dash charts process. A byte-identical probe client (same class, same name pattern, same subscription, connected first on a fresh Hudiy with charts disabled at boot) receives NOTHING — silently, not even ObdManager cancels. Theories disproven: first-querier-wins, subscription-gated, timing-based. Likely socket-credential (SO_PEERCRED) or internal whitelist. Consequence: diagnostics MUST proxy through the charts process (or own the slot on installs without race-dash). See `docs/ARCHITECTURE_NOTES.md` §DEFINITIVE CONSTRAINT.
2. **Query discipline (wedge claim RETRACTED 10 Sep).** The round-2/3 'ELM wedge' was ObdManager starving an unserved client — NOT ELM fragility. Multi-frame reads (`0904`) are safe through the served client (proven repeatedly). Keep the discipline anyway: single-flight, ≤15s timeout, one retry max, telemetry lane never blocked by diagnostics queries.
3. **`NO DATA` arrives as empty string** through Hudiy — treat empty as a valid negative answer, not an error.
4. **Multi-frame parsing.** Response frames concatenate `0:…1:…2:…` with variable hex lengths. Parse sequentially (frame-count prefix + slice). NEVER regex — `7E8\d+:` patterns swallow data digits (caused an infinite loop + gateway OOM once).
5. **Loop discipline in agent tooling:** no unbounded while-loops around `str.find()` in tool cells (find() returns -1 forever on miss → memory runaway).
6. **Overlay config (bench 16 Sep 2026).** A custom overlay's `visibleOnActions` must stay `[]` — a non-empty list (e.g. `["diag_show"]`) lets the whole API chain succeed silently (dispatch logged, visibility set, webview created+loaded) but the overlay NEVER paints. Same family as the `action`-field rule (`action` must stay `""`). Runtime `SetCustomOverlayVisibility` is the only show path; `merge_config.py` pins and self-heals this.

## 4. Phase plan
- **Phase 1 (DONE 10 Sep):** protocol research + ALL fixtures (positive AND negative) + feature survey + `docs/V1_SPEC.md` (build-ready).
- **Phase 2a (DECIDED):** proxy lane through the charts process; standalone mode when race-dash absent. No other option needed.
- **Phase 2b (NEXT):** backend then frontend, split to specialist cards (standing directive: FE+BE → separate specialist cards, backend first). Backend card constraint block = `docs/V1_SPEC.md` + `docs/ARCHITECTURE_NOTES.md` + `fixtures/`.

## 4a. Vehicle-state hazards (verified 10 Sep)
- **Stale ObdManager after car power-cycle:** ELM BT shows 'Connected', clients subscribed, but every query silently dropped (health `last_obd_age_s` climbs; sometimes `ObdManager cancel id: N` in Hudiy log). Recovery = kill -9 Hudiy + relaunch (device reopens in seconds when car powered; validated 2x). The diagnostics UI must show 'ECU reconnecting', never hang.
- **Negative fixtures are real data:** Mode 0A and Mode 02 (freeze frame) are NOT supported on the reference ECU. v1 handles this via runtime support bits — the same rules make it correct on any car.

## 5. Verification culture
- Every protocol claim in docs must trace to a fixture JSON or a cited source in `docs/OBD2_DIAGNOSTICS_RESEARCH.md`.
- Any new probe: strict abort-on-first-timeout, capped loops, connection killed cleanly after.
- Never probe OBD while assuming charts.py state — check `:44411/health` first (`hudiy_connected`, `last_obd_age_s`).

## 6. Wheel/knob input (11 Sep, live-proven)
- This Hudiy build routes NO physical input to third-party overlay webviews (CDP-proven). The shim `tools/keyboard_shim.py` (unit `hudiy-diag-keys`) reads the head-unit knob (auto-discovered; reference hardware: Elecrow/gen4-ESP32 at /dev/input/event4) and drives `window.__diagKeyNav()` via CDP 127.0.0.1:9222. Installer deploys, enables and starts the unit (it idles without a knob) + checks the `input` group.
- True detent map (captured per-direction): 2=left/prev, 3=right/next, 28=center/enter, 1=back. The knob chatters (one turn can emit 5-6 detents).
- **Ghost-input rule (16 Sep 2026, fixed live).** While the overlay is hidden the shim DISCARDS knob events (the same knob drives Hudiy's menu; hidden-time events replayed into the page = focus cycling, self-starting scans, self-exit), then settles ~0.35 s after each show. Only visible-time input is forwarded.
- Hudiy RE-SHOWS the singleton overlay webview on relaunch (never recreates); Exit teardown persists as blank unless the page clears it on `onAttached`. Reload-on-visible-edge = white-screen bug; only reload on the exited state.
- The knob's routing of physical events does NOT change the input-parity rule: touch + bridge keys + gestures still all work in-page.
- Every protocol claim in docs must trace to a fixture JSON or a cited source in `docs/OBD2_DIAGNOSTICS_RESEARCH.md`.
- Any new probe: strict abort-on-first-timeout, capped loops, connection killed cleanly after.
- Never probe OBD while assuming charts.py state — check `:44411/health` first (`hudiy_connected`, `last_obd_age_s`).

## 7. Licensing & provenance
- This project ships no Hudiy code: interop is runtime-only against the user's own Hudiy install (Api_pb2 is discovered, never bundled).
- Hudiy's public repo (github.com/wiboma/hudiy - docs/examples) carries no license: read it for interface facts, never copy code from it.
- Vendored third-party artifacts must carry their license next to them (see backend/third_party/dtc-database/).

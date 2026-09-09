# AGENTS.md — Hudiy Diagnostics

**Last updated:** 2026-09-09 (Phase 1)

## 1. What this project is
A Hudiy **menu-launched** car diagnostics app. Phase 1 = research + captured data only. Backend and frontend are deliberately NOT started (owner's explicit instruction: gather data first, build later).

Non-negotiable requirements (owner's verbatim constraints):
1. **No autolaunch.** Opened ONLY via the Hudiy settings/applications menu.
2. **Universal.** "It should be able to deployed to any hudiy instance, so it should be universal." No system-specific code baked in — vehicle capabilities are DISCOVERED at runtime (PID bitmap, OBDMID map, VIN via Mode 09), never hardcoded.
3. Read all OBD, check for errors, run diagnostics.

## 2. Environment facts (verified on the reference head unit 2026-09-09)
- Hudiy TCP API `127.0.0.1:44405`, protobuf messages in `common/Api_pb2.py`.
- OBD chain: Hudiy ⇄ ELM327 Bluetooth (RFCOMM) ⇄ ISO 15765-4 CAN 11-bit (VW).
- Race Dash (deployed sibling): charts.py :44411 (SSE API), toggle daemon :44413, user systemd units `hudiy-obd-charts`, `race-dash-screensaver`.
- Hudiy app lifecycle: labwc autostart only (`~/.hudiy/share/hudiy_run.sh`). `hudiy.service` is a stub (ExecCondition unmet under graphical.target) — `inactive` is NORMAL.
- Pi: ssh `car@<PI-IP>` (Tailscale), passwordless sudo, user units, LF files, no journald — Hudiy logs `~/.hudiy/log/hudiy.N.log` (newest by mtime; rotation index grows).
- Menu entries: `applications_menu.json` (Race Dash pattern at line 226: Material icon, Hudiy category, action string).

## 3. HARD CONSTRAINTS (from live probing — do not re-learn the hard way)
1. **Single OBD client slot.** Hudiy routes OBD query responses to ONE client per boot (the first that primes the OBD pipeline). A second client starves: no answers at 12s/25s timeouts, and Hudiy **kills its connection after ~7 unanswered queries**. Stopping the first client does NOT release the slot (verified 10–20s settle). Design options in `docs/ARCHITECTURE_NOTES.md`.
2. **ELM327 wedge hazard.** A Mode 09 CALID (`0904`) multi-frame read wedged the adapter irrecoverably (only a Pi reboot recovered it). Rules: long multi-frame reads = single-flight, ≤15s timeout, one retry max, never concurrent with live polling, telemetry lane never blocked by a diagnostics query.
3. **`NO DATA` arrives as empty string** through Hudiy — treat empty as a valid negative answer, not an error.
4. **Multi-frame parsing.** Response frames concatenate `0:…1:…2:…` with variable hex lengths. Parse sequentially (frame-count prefix + slice). NEVER regex — `7E8\d+:` patterns swallow data digits (caused an infinite loop + gateway OOM once).
5. **Loop discipline in agent tooling:** no unbounded while-loops around `str.find()` in tool cells (find() returns -1 forever on miss → memory runaway).

## 4. Phase plan
- **Phase 1 (DONE):** protocol research + live fixtures + this repo.
- **Phase 2a (NEXT):** settle the OBD client-slot design (arbiter / proxy-through-charts / menu-exclusivity / Hudiy multi-client probe). Owner decides with data.
- **Phase 2b:** backend then frontend, split to specialist cards (standing directive: FE+BE → separate specialist cards, backend first).
- Missing fixtures to capture when next on-car: clean Mode `0A`, `0104`, `0133`, clean `0685`, `0904`/`0906` (guarded).

## 5. Verification culture
- Every protocol claim in docs must trace to a fixture JSON or a cited source in `docs/OBD2_DIAGNOSTICS_RESEARCH.md`.
- Any new probe: strict abort-on-first-timeout, capped loops, connection killed cleanly after.
- Never probe OBD while assuming charts.py state — check `:44411/health` first (`hudiy_connected`, `last_obd_age_s`).

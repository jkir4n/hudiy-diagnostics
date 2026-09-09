# Decoded Fixture Analysis — Round 1 (2026-09-09 20:22 IST)

Car: Volkswagen (VIN below), ELM327 Bluetooth (RFCOMM) → Hudiy OBD bridge → Hudiy TCP API `127.0.0.1:44405`.
Transport evidence: `probe_meta.link = "ELM327 BT RFCOMM, ISO 15765-4 CAN 11-bit"`.

All values below are decoded from `fixtures/round1_full_capture.json` raw strings.

## Identity
- **VIN (Mode 09 0x02)**: `WVWZZZ1KZAW555555`
  - raw: `0:490201575657 1:5A5A5A314B5A41 2:57353535353535`
  - FF payload `575657` = "WVW" + CFs `5A5A5A314B5A41` "ZZZ1KZA" + `57353535353535` "W555555"
- **ECU name (Mode 09 0x0A)**: `ECM-EngineControl`
  - decoded from `0:490A004543 1:4D2D456E67696E 2:65436F6E74726F 3:6C0000000000` → bytes 0x45.. `ECM-EngineControl` + AA padding
- **Mode 09 supported INFOTYPES (0900)**: raw `490054400000` → A-bits: 0x02 (VIN), 0x04 (CALID), 0x06 (CVN), 0x0A (ECU name). **CALID+CVN supported but uncaptured** (multi-frame reads are the ELM327 wedge suspect).

## PID support
- **0100** raw `4100983BA013` → A=0x98 B=0x3B C=0xA0 D=0x13
  - PIDs 01–20 supported: `01 04 05 0B 0C 0D 0F 10 11 13 1C 1F 20`
- **0120** raw `41209xxxxxxxxxxx` (see fixture; full bit-decode in repo tooling phase)
  - PIDs 21–40 supported: `21 23 24 2C 2D 30 31 33 40`
- Notable: **0104 (load) and 0133 (baro) are SUPPORTED but response uncaptured** — probe rounds 4/5/8 blocked by the second-client routing constraint.

## Live values (engine running at capture)
- 010C RPM, 0142 voltage, 012F fuel level, 015C engine oil temp, 0105 coolant, 010B MAP, 0110 MAF, 010F intake temp, 0111 throttle, 0123 EGR — raw frames preserved in fixture.

## Emissions / DTC
- **Mode 03 (stored DTCs)**: `4300` → **0 DTCs, clean**
- **Mode 07 (pending DTCs)**: `4700` → **0 DTCs, clean**
- **Mode 0A (permanent DTCs)**: round-1 answer `4700` is SUSPECT (identical to 07; possibly Hudiy/ELM aliasing). Uncaptured clean answer.
- **Mode 01 PID 01 (MIL + readiness)**: captured — diesel monitor map decoded in research note; MIL off at capture.

## Mode 06 (OBDMIDs supported: 01, 21, 31, 81, 85, and 06B2 seen)
- OBDMID 01 (O2 sensor bank 1): test results captured
- OBDMID 21/31 (EGR system): captured
- OBDMID 81/85 (boost pressure system): captured; **0685 response needs clean re-read** (2-group parse was ambiguous in round 1)
- Full TID/UVALW tests decoded in research note §Mode-06.

## Transport quirks (protocol-level, for the app)
1. **NO DATA = empty string** (Hudiy returns `""`, not the ELM text `NO DATA`) — treat empty as authoritative negative.
2. **Multi-frame responses** concatenate frames as `0:… 1:… 2:…` with **variable hex-length CFs** — parse by frame-count prefix + sequential slicing, NEVER regex (regex `7E8\d+:` swallows data digits).
3. **Second-client starvation**: post-reboot, Hudiy routes OBD query responses only to its first-boot primed OBD client (charts.py). A second TCP client's queries are silently dropped and the client is killed after ~7 unanswered requests. → diagnostics app design constraint, see `docs/ARCHITECTURE_NOTES.md`.
4. **ELM wedge hazard**: a multi-frame Mode 09 CALID query (`0904`) wedged the ELM327 hard; only a full Pi reboot recovered it. Multi-frame long reads must be single-flight, timeout-guarded, one-retry-max in the app.

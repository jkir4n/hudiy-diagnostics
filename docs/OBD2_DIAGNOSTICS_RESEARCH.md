# OBD-II / EOBD Diagnostics Research Note
## Target: 2012 VW Polo 1.2 TDI (CFWA, Delphi DCM3.7, 75 PS) via Bluetooth ELM327 clone, ISO 15765-4 CAN 11-bit / 500 kbit/s

**Purpose:** reference for adding a read-only diagnostics feature (fault list + monitor checks + suggested fixes) to the Raspberry Pi OBD daemon that sends raw OBD command strings (e.g. `010D`) and receives hex payloads.

**Scope of the link assumed:** ISO 15765-4 DoCAN, 11-bit CAN IDs, 500 kbit/s. Functional request ID `7DFh`; ECU responses `7E8h`–`7EFh` (ECU physical request IDs `7E0h`–`7E7h`, response = physical + 8). Every CAN frame carries an 8-byte data field; ISO 15765-2 recommends padding unused bytes with `CCh` ([Wikipedia: OBD-II PIDs § CAN (11-bit) bus format](https://en.wikipedia.org/wiki/OBD-II_PIDs#CAN_(11-bit)_bus_format)).

**Terminology:** OBD-II "modes" = SAE J1979 / ISO 15031-5 *services*. J1979 §4.3 reserves service IDs `$00`–`$0F` for SAE/ISO; UDS (ISO 14229-1) services start at `0x10` to avoid overlap ([SAE J1979:2002 §4.3](https://archive.org/stream/gov.law.sae.j1979.2002/sae.j1979.2002_djvu.txt), [Wikipedia: OBD-II PIDs § Services/Modes](https://en.wikipedia.org/wiki/OBD-II_PIDs#Services_/_Modes)). Positive response SID = request SID + `0x40` in **all** cases (J1979 §4.2.3; [Wikipedia](https://en.wikipedia.org/wiki/OBD-II_PIDs#Response)).

**One rule that dominates everything below:** over ISO 15765-4, for a *functional* request (ID `7DFh`) an ECU that does not support the requested service, PID, OBDMID, TID or INFOTYPE **is not allowed to send a negative response** — you get silence, which the ELM327 renders as `NO DATA`. Only a supported service with currently-unavailable data produces a negative response (NRC `$22`), and for service `$06` even `$22` is forbidden ([SAE J1979:2002 §4.1.4.2](https://archive.org/stream/gov.law.sae.j1979.2002/sae.j1979.2002_djvu.txt)).

---

## 1. Diagnostic services (modes) — request/response bytes, read-only status, VW diesel support

### 1.1 Master table

| Mode | Req SID | Pos. resp SID | Returns | Read-only? | Support on 2010–2014 VW diesel (EOBD) | Concrete example (request → response) |
|---|---|---|---|---|---|---|
| **01** | `01` | `41` | Current data, addressed by 1-byte PID | **Yes** | **Full** — mandatory EOBD service | `01 0C` → `41 0C 1F 40` (RPM 2000) |
| **02** | `02` | `42` | Freeze-frame snapshot, same PIDs as 01 + frame number byte | **Yes** | **Yes** — VW service manual documents "Mode 02 – Read Operating Conditions" | `02 0C 00` → `42 0C 00 1F 40` |
| **03** | `03` | `43` | Confirmed (stored) emissions DTCs | **Yes** | **Yes** | `03` → `43 02 02 34 01 43` (2 DTCs: P0234, P0143) |
| **04** | `04` | `44` | Clears DTCs + **all** emissions diagnostic data, readiness bits, freeze frames, adaptations | **NO — destructive** | **Yes** (see §7) | `04` → `44` |
| **05** | `05` | `45` | O2-sensor monitoring test results by TID (legacy, **non-CAN only**) | Yes | **N/A on CAN** — J1979 puts O2 test results in Mode 06 for ISO 15765-4 | on CAN: silence → `NO DATA`, or `7F 05 11` |
| **06** | `06` | `46` | On-board monitoring test results (OBDMID/TID/UAS + value/min/max) | **Yes** | **Yes** — VW manual lists a diesel Monitor-ID set (see §5) | `06 01` → `46 01 01 0A 12 34 10 00 20 00` |
| **07** | `07` | `47` | Pending DTCs (detected this/last driving cycle) | **Yes** | **Yes** — VW documents "Mode 07 – Read Faults Detected During the Current or Last Driving Cycle" | `07` → `47 01 02 34` or `47 00` |
| **08** | `08` | `48` | Bidirectional control / actuator test by TID | **NO — actuation** | Present in VW manuals; **must not be used** by this daemon | `08 01` → `48 01 …` |
| **09** | `09` | `49` | Vehicle info: VIN, Calibration ID, CVN, ECU name (by INFOTYPE) | **Yes** | **Yes** | `09 02` → `49 02 01 <17 ASCII bytes>` |
| **0A** | `0A` | `4A` | Permanent DTCs (US CARB MY2010+ requirement) | **Yes** | **Usually NOT supported on EOBD** — VW's own TDI manual documents Modes 01–09 only; expect `7F 0A 11` or `NO DATA` | `0A` → `7F 0A 11` |

Sources: [Wikipedia: OBD-II PIDs § Services](https://en.wikipedia.org/wiki/OBD-II_PIDs#Services_/_Modes), [SAE J1979:2002 §5 and §6](https://archive.org/stream/gov.law.sae.j1979.2002/sae.j1979.2002_djvu.txt), [VW TDI (CJAA) service manual "Diagnostic Modes 01 – 09"](https://charm.li/Volkswagen/2011/Jetta%20SportWagen%20%28AJ5%29%20L4-2.0L%20DSL%20Turbo%20%28CJAA%29/Repair%20and%20Diagnosis/Powertrain%20Management/Computers%20and%20Control%20Systems/Testing%20and%20Inspection/Scan%20Tool%20Testing%20and%20Procedures/Diagnostic%20Modes%2001%20-%2009/Diagnostic%20Modes%2001%20-%2009/).

### 1.2 Mode 01 — Show current data

- Request: `01 <PID>` (2 bytes; the ELM327 adds the PCI/length byte for you with `ATCAF1`).
- Response: `41 <PID> <A> [B] [C] [D]`.
- Example: `01 0D` → `41 0D 5A` = 90 km/h. `01 05` → `41 05 7B` = 0x7B−40 = 83 °C coolant.
- Multi-PID requests are allowed in one message over CAN (`01 0C 0D 05`), but ECUs answer with the supported subset only; the ELM327 clone + this daemon should keep issuing one PID per request.

### 1.3 Mode 02 — Freeze frame

- Request: `02 <PID> <frame#>` — the **frame number byte is mandatory** (`$00` = the mandated freeze frame; manufacturers may store extra frames).
- Response: `42 <PID> <frame#> <data…>`.
- **`02 02`** returns the DTC that caused the freeze frame, decoded exactly like Mode 03. If no freeze frame is stored the ECU reports `00 00` and **all other Mode 02 data is meaningless** ([SAE J1979:2002 §5.2.1](https://archive.org/stream/gov.law.sae.j1979.2002/sae.j1979.2002_djvu.txt), [Wikipedia: Service 02](https://en.wikipedia.org/wiki/OBD-II_PIDs#Service_02_-_Show_freeze_frame_data)).

### 1.4 Mode 03 — Stored DTCs (see §3 for encoding)

- Request: `03` (1 byte).
- CAN response: `43 <count> <DTC1 hi> <DTC1 lo> … <DTCn hi> <DTCn lo>`, padded with `00 00`.
- Example: `03` → `43 02 02 34 01 43` = 2 DTCs, P0234 and P0143.
- Non-CAN protocols have **no count byte** and repeat `43` on every frame — a parser that only ever sees CAN must not assume this, but it must not mis-read the count byte as a DTC either ([ScanTool.net forum, "Trouble code parsing"](https://www.scantool.net/forum/index.php?topic=7722.msg28932)).

### 1.5 Mode 04 — Clear/reset emissions diagnostic information (see §7)

- Request: `04`; response `44` (one byte, no parameters).
- Not read-only. Erases DTCs, freeze frame, readiness bits, Mode 06 results, MIL status, warm-up/distance counters — and on VW, "the adaptation values may also be reset" ([VW service manual, Diagnostic Mode 04](https://charm.li/Volkswagen/2010/Golf%20%285K1%29%20L5-2.5L%20%28CBUA%29/Repair%20and%20Diagnosis/Powertrain%20Management/Computers%20and%20Control%20Systems/Testing%20and%20Inspection/Reading%20and%20Clearing%20Diagnostic%20Trouble%20Codes/Diagnostic%20Mode%2004%20-%20Erase%20DTC%20Memory/); [SAE J1979:2002 §5.4.1](https://archive.org/stream/gov.law.sae.j1979.2002/sae.j1979.2002_djvu.txt)).
- J1979 requires all ECUs to respond with **ignition ON and engine not running**; with the engine running some ECUs ignore the request or return NRC `$22` (`conditionsNotCorrect`).

### 1.6 Mode 05 — O2 sensor monitoring test results (legacy)

- Request: `05 <TID> <O2 sensor#>`; response `45 <TID> <O2 sensor#> <data…>`.
- **Non-CAN only.** Wikipedia states Mode 06 is "Test results, oxygen sensor monitoring for CAN only" ([Wikipedia § Services](https://en.wikipedia.org/wiki/OBD-II_PIDs#Services_/_Modes)). On ISO 15765-4 expect `NO DATA`.
- Do not implement for this vehicle; use Mode 06 instead.

### 1.7 Mode 06 — On-board monitoring test results (see §5)

- Request: `06 <OBDMID>`; response: `46 <OBDMID> <TID> <UASID> <value hi> <value lo> <min hi> <min lo> <max hi> <max lo>` (repeat the 8-byte group for further test results).
- Read-only.

### 1.8 Mode 07 — Pending DTCs

- Request: `07`; response `47 <count> <DTC…>` over CAN (same layout as Mode 03 with `47` as the SID).
- VW behaviour: a pending DTC is stored the first time a fault is detected; if the fault recurs before the end of the next driving cycle it becomes confirmed (Mode 03) and lights the MIL; if not, it is deleted at the end of the cycle ([VW TDI manual, Diagnostic Mode 07](https://charm.li/Volkswagen/2011/Jetta%20SportWagen%20%28AJ5%29%20L4-2.0L%20DSL%20Turbo%20%28CJAA%29/Repair%20and%20Diagnosis/Powertrain%20Management/Computers%20and%20Control%20Systems/Testing%20and%20Inspection/Scan%20Tool%20Testing%20and%20Procedures/Diagnostic%20Modes%2001%20-%2009/Diagnostic%20Mode%2007%20-%20Read%20Faults%20Detected%20During%20the%20Current%20or%20Last%20Driving%20Cycle/)).

### 1.9 Mode 08 — Bidirectional control

- Request: `08 <TID> …`; response `48 …`. **Not read-only.** Keep it out of the daemon's command allowlist entirely.

### 1.10 Mode 09 — Vehicle information (INFOTYPEs)

| INFOTYPE | Meaning | Bytes | Notes |
|---|---|---|---|
| `00` | Supported INFOTYPEs `$01–$20` bitmap | 4 | Same bit encoding as PID `$00` |
| `02` | VIN | 17 ASCII | Over CAN the "message count" INFOTYPE `01` is **not used** |
| `04` | Calibration ID (CALID) | 16 ASCII per ID | Usually multi-frame |
| `06` | Calibration Verification Number (CVN) | 4 bytes per CVN | Hex |
| `0A` | ECU name | 20 ASCII | Right-padded with `00` |
| `01`,`03`,`05`,`07`,`09` | Message-count INFOTYPEs | 1 | **Only for ISO 9141-2 / ISO 14230-4 / J1850** — do not use on CAN |

Request `09 02` → `49 02 01 31 44 34 47 50 30 30 52 35 35 42 31 32 33 34 35 36` = VIN "1D4GP00R55B123456" (this is the canonical ELM327 multi-frame example — see §4). Sources: [Wikipedia: Service 09](https://en.wikipedia.org/wiki/OBD-II_PIDs#Service_09_-_Request_vehicle_information), [ScanTool.net staff example](https://www.scantool.net/forum/index.php?topic=5605.msg20662).

### 1.11 Mode 0A — Permanent DTCs

- Request: `0A`; response `4A <count> <DTC…>`.
- Semantics (US CARB CCR 1968.2): permanent DTCs are *confirmed DTCs that are currently activating the MIL*; they cannot be erased by Mode 04 or by disconnecting the battery, and they are only cleared after the fault is corrected (PASS result + minimum trip conditions met). **"Mode 0A may only be supported exclusively by OBD control modules in US vehicles. Mode 0A may not be supported in EOBD vehicles, meaning the control module may not send a response here."** A vehicle with permanent DTCs reported via `$0A` fails I/M ([VW/Audi service manual, Diagnostic Mode 0A](https://charm.li/Audi/2011/S4%20Quattro%20Sedan%20%288K2%29%20V6-3.0L%20SC%20%28CCBA%29/Repair%20and%20Diagnosis/Powertrain%20Management/Computers%20and%20Control%20Systems/Testing%20and%20Inspection/Scan%20Tool%20Testing%20and%20Procedures/Diagnostic%20Mode%200A%20-%20Check%20Permanent%20DTC%20Memory/)).
- Observed behaviour on a generic scanner: `0A` → `7F 0A 11` (serviceNotSupported) when there are no permanent codes or the ECU does not implement the service ([ScanTool.net forum](https://www.scantool.net/forum/index.php?topic=7722.msg31564)).
- The VW TDI (CJAA) service manual documents Modes 01–09 only, while the petrol VW/Audi manuals document 0A — consistent with 0A being US-only.

### 1.12 Negative-response format (all modes)

```
7F <request SID> <NRC>
```
Byte 1 `7F` = negative response SID; byte 2 = the SID that was requested; byte 3 = response code (J1979 §4.2.3.4 Table 9, [source](https://archive.org/stream/gov.law.sae.j1979.2002/sae.j1979.2002_djvu.txt)). Example: `7F 0A 11`, `7F 06 12`.

---

## 2. Mode 01 PID `01` — Monitor status since DTCs cleared

Returns **4 data bytes A, B, C, D** (`41 01 A B C D`). Bit numbering: bit 7 = MSB, bit 0 = LSB (J1979 §4.2.10).

### 2.1 Byte A

| Bits | Meaning |
|---|---|
| `A7` | MIL / CEL **on (1) / off (0)** |
| `A6`–`A0` | Number of confirmed emissions-related DTCs available for display (0–127) |

### 2.2 Byte B — common (not engine-type specific) monitors

| Bits | Meaning |
|---|---|
| `B7` | Reserved (0) |
| `B6`–`B4` | Completeness bitmap of **common** tests |
| `B3` | **Engine type: 0 = spark ignition, 1 = compression ignition (diesel)** |
| `B2`–`B0` | Availability bitmap of **common** tests |

| Common test | Availability | Completeness |
|---|---|---|
| Components | `B2` | `B6` |
| Fuel System | `B1` | `B5` |
| Misfire | `B0` | `B4` |

> **Semantics trap:** for **availability** bits, `1` = supported/available. For **completeness** bits, `0` = test complete (i.e. readiness bit "set"). Getting this backwards is the single most common PID 01 bug.

### 2.3 Bytes C and D — compression ignition (diesel) monitors

Byte C = **availability**, byte D = **completeness**, same bit positions.

| Monitor | Availability | Completeness |
|---|---|---|
| EGR and/or VVT system | `C7` | `D7` |
| **PM filter monitoring** | `C6` | `D6` |
| Exhaust gas sensor | `C5` | `D5` |
| *Reserved* | `C4` | `D4` |
| **Boost pressure** | `C3` | `D3` |
| *Reserved* | `C2` | `D2` |
| **NOx / SCR monitor** | `C1` | `D1` |
| NMHC catalyst | `C0` | `D0` |

For comparison, the **spark-ignition** map for C/D is: C7/D7 EGR & VVT, C6/D6 O2 sensor heater, C5/D5 O2 sensor, C4/D4 gasoline particulate filter, C3/D3 secondary air, C2/D2 evaporative system, C1/D1 heated catalyst, C0/D0 catalyst. Sources: [Wikipedia: Service 01 PID 01](https://en.wikipedia.org/wiki/OBD-II_PIDs#Service_01_PID_01_-_Monitor_status_since_DTCs_cleared); J1979 §5.1 / Table 24-25 examples (`41 01 81 33 FF 63`, `41 01 01 44 00 00`) in the [J1979 full text](https://archive.org/stream/gov.law.sae.j1979.2002/sae.j1979.2002_djvu.txt).

### 2.4 Worked example (illustrative, diesel)

`41 01 00 7F E8 E8`

- `A = 00` → MIL off, 0 confirmed DTCs.
- `B = 7F = 0111 1111` → `B7=0` reserved; `B6..B4 = 111` → components/fuel/misfire **all complete**; `B3 = 1` → **compression ignition (diesel)**; `B2..B0 = 111` → all three common monitors supported.
- `C = E8 = 1110 1000` → EGR/VVT (C7), PM filter (C6), exhaust gas sensor (C5), boost pressure (C3) **supported**; C4/C2 reserved; NOx/SCR (C1) and NMHC catalyst (C0) **not supported** (correct for a Euro 5 diesel without SCR).
- `D = E8` → those four monitors are **complete**.

Contrast a not-yet-ready car after a Mode 04 clear: `41 01 00 0F E8 00` — common monitors supported (`B2..B0=111`) but none complete (`B6..B4=000`), and no diesel-specific monitor complete (`D = 00`).

### 2.5 PID `41` — Monitor status **this drive cycle**

- Request `01 41` → response `41 41 A B C D`.
- Identical encoding to PID `01` **except byte A is always zero** — the MIL state and DTC count are not repeated ([Wikipedia: Service 01 PID 41](https://en.wikipedia.org/wiki/OBD-II_PIDs#Service_01_PID_41_-_Monitor_status_this_drive_cycle)).
- Practical use: `01 41` shows which monitors have already run since key-on; `01 01` shows the since-cleared readiness state.

### 2.6 PID `02` — DTC that caused the freeze frame to be stored

- `01 02` (or `02 02 00`) → `41 02 <DTC hi> <DTC lo>`, decoded exactly like Mode 03.
- No freeze frame stored → `41 02 00 00`; all other Mode 02 data is then meaningless.
- Example: `41 02 01 43` → P0143.

### 2.7 PID `30` — Warm-ups since codes cleared

- `01 30` → `41 30 A`, `A` = count 0–255. Example `41 30 17` = 23 warm-up cycles.
- A "warm-up cycle" requires coolant to rise by ≥ 22 K (≈ 40 °F) and reach ≥ 71 °C (160 °F) per OBD definitions — the counter only increments once per such cycle.

### 2.8 PID `31` — Distance travelled since codes cleared

- `01 31` → `41 31 A B`, value = `256·A + B` **km**, 0–65535 km. Example `41 31 01 F4` = 500 km.

### 2.9 Related Mode 01 PIDs worth surfacing in a diagnostics UI

| PID | Meaning | Formula |
|---|---|---|
| `01 1C` | OBD standard complied with | 1 byte enum; **`06` = EOBD (Europe)** — the expected value for this Polo ([Wikipedia: PID 1C](https://en.wikipedia.org/wiki/OBD-II_PIDs#Service_01_PID_1C_-_OBD_standards_this_vehicle_conforms_to)) |
| `01 21` | Distance travelled with MIL on | `256A+B` km |
| `01 4D` | Time run with MIL on | `256A+B` min |
| `01 4E` | Time since DTCs cleared | `256A+B` min |
| `01 51` | Fuel type | 1 byte enum (diesel codes) |
| `01 5C` | Engine oil temperature | `A − 40` °C (useful — the repo currently notes "no oil-temp PID"; PID 5C exists on many CR diesels but support must be probed) |
| `01 7A` | **DPF differential pressure** | standardised, 7 bytes, almost never exposed by VW over generic OBD (see §6) |
| `01 7B` | **DPF** | standardised, 7 bytes |
| `01 7C` | **DPF temperature** | `(256A+B)/10 − 40` °C, 9 bytes |
| `01 78`/`79` | EGT bank 1 / 2 | byte A = sensor-support bitmap (A0..A3 = sensors 1–4), then four 16-bit temps `(A·256+B)/10 − 40` °C ([Wikipedia: PID 78/79](https://en.wikipedia.org/wiki/OBD-II_PIDs#Service_01_PID_78_and_79_-_Exhaust_Gas_temperature_(EGT)_Bank_1_and_Bank_2)) |

---

## 3. DTC encoding (ISO 15031-6 / SAE J2012)

### 3.1 Two-byte layout

Each DTC is exactly **2 bytes**. The **first 2 bits of byte A** are the category; the **remaining 14 bits** are the code number.

| `A7 A6` | Category |
|---|---|
| `00` | **P** — Powertrain |
| `01` | **C** — Chassis |
| `10` | **B** — Body |
| `11` | **U** — Network / (originally "undefined") |

Decoded display form = `CATEGORY` + the 14-bit number as **4 hex digits** (so the second character can only ever be `0`–`3`). Source: [Wikipedia: Service 03 DTC decoding](https://en.wikipedia.org/wiki/OBD-II_PIDs#Service_03_(no_PID_required)_-_Show_stored_Diagnostic_Trouble_Codes).

### 3.2 Worked examples

| Bytes (hi, lo) | A7..A0 / B7..B0 | Category | Number | Displayed DTC |
|---|---|---|---|---|
| `C1 58` | `1100 0001` `0101 1000` | `11` → **U** | `0158` | **U0158** (Wikipedia's worked example) |
| `01 43` | `0000 0001` `0100 0011` | `00` → **P** | `0143` | **P0143** |
| `02 34` | | `00` → P | `0234` | **P0234** |
| `0A 24` | | `00` → P | `0A24` | **P0A24** |
| `02 CD` | | `00` → P | `02CD` | **P02CD** |
| `43 00` | `0100 0011` … | `01` → **C** | `0300` | **C0300** |
| `82 00` | `1000 0010` … | `10` → **B** | `0200` | **B0200** |
| `C1 00` | `1100 0001` … | `11` → **U** | `0100` | **U0100** |

(The P/C/B/U set above is the exact decode of the `43 06 01 00 02 00 03 00 43 00 82 00 C1 00 …` frame in the [ScanTool.net "Trouble code parsing" thread](https://www.scantool.net/forum/index.php?topic=7722.msg28932).)

Pseudo-rule: `first_char = "PCBU"[(A >> 6) & 0x03]`, `rest = ((A & 0x3F) << 8 | B)` formatted as 4 uppercase hex digits.

### 3.3 Multi-DTC response layout over ISO 15765-4

```
43 <count> <DTC1 hi> <DTC1 lo> <DTC2 hi> <DTC2 lo> … <DTCn hi> <DTCn lo>  [00 00 …]
```

- `count` is a single byte **present only on CAN** (ISO 15765-4). Non-CAN protocols repeat `43` on each frame with no count.
- The DTC list is padded with `00 00` to fill the last CAN frame — **`00 00` is padding, not a DTC**.
- Real example (headers off, multi-line): `SEARCHING... 00E 0: 43 06 01 00 02 00 1: 03 00 43 00 82 00 C1 2: 00 00 00 00 00 00 00` → 6 DTCs = P0100, P0200, P0300, C0300, B0200, U0100.
- Same request with `ATH1` (29-bit example from the same thread): `18 DA F1 10 10 0E 43 06 01 00 02 00 / 18 DA F1 10 21 03 00 43 00 82 00 C1 / 18 DA F1 10 22 00 00 00 00 00 00 00 / 18 DA F1 18 04 43 01 01 01 00 00 00`. Note the **second ECU** (`…F1 18`) answering with its own single-frame `43 01 01 01` = P0101 — a naive parser that concatenates all lines will corrupt the DTC list. **Always split by CAN ID / line.**

### 3.4 How "no DTCs" is reported

| Situation | What the ELM327 prints | What it means |
|---|---|---|
| ECU answers, count = 0 | `43 00` (sometimes `43 00 00 00 …`) | Valid response: **no stored DTCs**. Count byte `00`. |
| ECU does not implement Mode 03 | `NO DATA` (after `SEARCHING...`) | Functional request + unsupported service ⇒ **no negative response permitted** (J1979 §4.1.4.2) |
| Mode 0A on a non-US ECU / no permanent DTCs | `7F 0A 11` | `serviceNotSupported` |
| Bus/protocol problem | `UNABLE TO CONNECT`, `CAN ERROR`, `BUS INIT: ERROR`, `STOPPED`, `BUFFER FULL` | Transport-level failure, not a diagnostic answer |

**Parser rule:** treat `NO DATA` as "unknown/unsupported", *not* as "no faults". Distinguish `43 00` (clean) from `NO DATA` (could not ask). Same for `47 00` vs `NO DATA` in Mode 07.

---

## 4. ELM327 framing, headers, ISO-TP reassembly and negative responses

### 4.1 Relevant AT commands

| Command | Effect | Default |
|---|---|---|
| `ATH0` / `ATH1` | Headers **off** / **on** (CAN ID shown) | `ATH0` |
| `ATS0` / `ATS1` | Spaces between bytes off/on | `ATS1` |
| `ATCAF0` / `ATCAF1` | CAN auto-formatting **off** / **on** — `CAF1` makes the ELM327 generate PCI bytes on transmit and strip them on receive; `CAF0` shows raw frames including PCI | `ATCAF1` |
| `ATD0` / `ATD1` | Data-length byte off/on | `ATD0` |
| `ATSP6` | Force ISO 15765-4 CAN **11-bit / 500 kbit/s** | `ATSP0` auto |
| `ATSP7` | Force ISO 15765-4 CAN **29-bit / 500 kbit/s** | — |
| `ATCRA hhh` / `ATCRA hhhhhhhh` | Set CAN receive address filter (e.g. `ATCRA 7E8`) | off |
| `ATSH hhh` | Set CAN transmit header (e.g. `ATSH 7E0` physical ECU, `ATSH 7DF` functional) | — |
| `ATFCSH` / `ATFCSD` / `ATFCSM` | Flow-control header / data / mode for manual ISO-TP | off |
| `ATST hh`, `ATAT0/1/2` | Timeout; adaptive timing | `ATAT1` |
| `ATE0` | Echo off (recommended for a daemon) | echo on |
| `ATDP` / `ATDPN` | Describe protocol (needs a prior request to initialise in auto mode) | — |

The datasheet's `ATCAF0/CAF1` text is explicit: *"With CAN Automatic Formatting enabled (CAF1), the IC will automatically generate formatting (PCI) bytes for you when sending, and will remove them when receiving… Note that turning the display of headers on (with AT H1) will override some of the CAF1 formatting of the received data frames, so that the received bytes will appear much like in the CAF0 mode (ie. as received)."* ([ELM327 datasheet OCR text, AT Commands section](http://www.ic-on-line.net/view_online.php?id=1213444&file=0127%5Celm3271_1236855.pdf); protocol list also at [Wikipedia: ELM327](https://en.wikipedia.org/wiki/ELM327)).

### 4.2 The three output forms of the same answer — canonical example

Request `09 02` (VIN) on CAN. The ECU sends one long message; the ELM327 splits it. Verified example from ScanTool.net staff ([source](https://www.scantool.net/forum/index.php?topic=5605.msg20662)):

**(a) Raw CAN frames on the bus**
```
7E8 49 02 01 31 47 31 4A 43 35 34 34 34 52 37 32 35 32 33 36 37
```

**(b) ELM327 → host, headers OFF (`ATH0`), auto-formatting ON (`ATCAF1`, default)** — lines are prefixed `0:`, `1:`, `2:` and the total payload length is printed first in hex:
```
014
0: 49 02 01 31 47 31
1: 4A 43 35 34 34 34 52
2: 37 32 35 32 33 36 37
```
- `014` = `0x14` = 20 = 3 payload bytes (SID `49`, INFOTYPE `02`, item count `01`) + 17 VIN characters.
- The `N:` prefixes are **line counters, not CAN IDs and not PCI bytes**.

**(c) `ATH1` (headers on) or `ATCAF0` (auto-formatting off)** — raw ISO-TP frames with the CAN ID and the PCI bytes visible:
```
7E8 10 14 49 02 01 31 47 31
7E8 21 4A 43 35 34 34 34 52
7E8 22 37 32 35 32 33 36 37
```

### 4.3 ISO-TP PCI bytes (ISO 15765-2)

| Frame type | PCI code | Layout |
|---|---|---|
| Single frame (SF) | `0x0` | byte0 = `0L` where `L` = payload length 1–7, then data |
| First frame (FF) | `0x1` | byte0 = `1H`, byte1 = `L` ⇒ **12-bit total length** = `(H<<8)|L` (excludes PCI bytes), then first 6 data bytes |
| Consecutive frame (CF) | `0x2` | byte0 = `2N`, `N` = sequence number starting at 1, wrapping `F → 0`; then 7 data bytes |
| Flow control (FC) | `0x3` | byte0 = `3F` (`F`: 0 = CTS, 1 = WAIT, 2 = OVERFLOW), byte1 = block size, byte2 = STmin |

Sources: [Wikipedia: ISO 15765-2](https://en.wikipedia.org/wiki/ISO_15765-2); J1979 §4.2.7 confirms that for ISO 15765-4 the first data byte after the CAN ID in a single frame / first frame is the PCI, **then** the service ID.

**Reassembly algorithm (headers-on form):**
1. Group lines by CAN ID; discard any line whose CAN ID is not in `7E8`–`7EF`.
2. On the first line, read `10 H L` → expected total length `(H<<8)|L`; append the 6 data bytes after the PCI.
3. On each subsequent `2N` line, append 7 data bytes. Verify `N` increments (1,2,…,F,0,…).
4. Truncate to the declared length. The result is the application payload: `<resp SID> <PID/INFOTYPE> <data…>`.
5. If a single frame, byte0 is `0L` — strip it and take `L` bytes.

**Reassembly for the headers-off (`0:`/`1:`/`2:`) form:** concatenate the numbered lines in numeric order; the leading 3-hex-digit count line (e.g. `014`) gives the payload length. Then parse `<resp SID> <PID> …`.

**Gotcha:** with `ATH1` + `ATCAF1`, ELM327 shows the received bytes "much like in CAF0 mode" — i.e. **you will see PCI bytes**. If you want CAF1's automatic stripping, keep headers off. Pick one convention and validate it.

### 4.4 Detecting a negative response

Positive responses start with `request SID + 0x40`. A negative response is `7F <requested SID> <NRC>` and may be:
- the *only* line of the reply (`7F 06 12`), or
- interleaved with other ECUs' positive answers when multiple ECUs respond.

Detection rule for the daemon: after stripping PCI/headers, if `payload[0] == 0x7F` then `payload[1]` = the SID we asked for and `payload[2]` = NRC → report a structured error, do **not** try to decode it as data.

### 4.5 Common Negative Response Codes

| NRC | Mnemonic | Meaning (ISO 14229-1) | Practical reading on this vehicle |
|---|---|---|---|
| `0x10` | GR | generalReject | Generic rejection; rare |
| `0x11` | SNS | serviceNotSupported | Mode 0A / Mode 05 on this ECU (`7F 0A 11`) |
| `0x12` | SFNS | subFunctionNotSupported | Bad/unsupported PID-TID sub-function or format |
| `0x13` | IMLOIF | incorrectMessageLengthOrInvalidFormat | Request byte count wrong |
| `0x14` | RTL | responseTooLong | — |
| `0x21` | BRR | busyRepeatRequest | ECU busy (mainly protocol init) |
| `0x22` | CNC | conditionsNotCorrect | Engine running for Mode 04, etc. **Not permitted for service `$06`** |
| `0x24` | RSE | requestSequenceError | Wrong ordering (session/security) |
| `0x31` | ROOR | requestOutOfRange | **DID / routine / parameter not supported** — the normal answer to an unknown UDS 0x22 DID |
| `0x33` | SAD | securityAccessDenied | Needs a 0x27 security unlock |
| `0x35`/`0x36`/`0x37` | IK / ENOA / RTDNE | invalidKey / too many attempts / delay not expired | Security access failures |
| `0x78` | RCRRP | requestCorrectlyReceived – responsePending | **Not an error**: the ECU needs more time; ELM327 v2.1+ processes this automatically, older clones may show it. Wait for the final response. |
| `0x7E` / `0x7F` | SFNSIAS / SNSIAS | sub-function / service not supported in active session | Wrong UDS session (e.g. needs 0x10 0x03) |
| `0x81`–`0x93` | RTH/RTL/EIR/EINR/…/VTH/VTL | condition checks (RPM, engine state, temperature, speed, voltage) | Actuator tests blocked by conditions |
| `0xF0`–`0xFE` | — | manufacturer-specific conditions | — |

Full table: [autosar.dev — NRC (Negative Response Code)](https://autosar.dev/UDS_(Unified_Diagnostic_Services)/NRC_(Negative_Response_Code)); J1979 §4.2.4 Table 10 for the OBD subset (`$10`, `$11`, `$12`, `$21`, `$22`, `$78`).

**Important:** `NO DATA` ≠ `7F …`. `NO DATA` means *nobody answered*, which per J1979 is the correct behaviour for an unsupported service/PID on a functional request. Your UI should say "not supported by this ECU", not "fault".

### 4.6 What ELM327 clones actually support

- The genuine ELM327 firmware ended at **v2.3**; ELM Electronics closed in June 2022. Clones are almost all based on the leaked **v1.4** microcode and frequently misreport a higher version; their real feature set is v1.4's ([Wikipedia: ELM327 § Other versions](https://en.wikipedia.org/wiki/ELM327#Other_versions)).
- 29-bit CAN (`ATSP7`) is nominally in the ELM327 protocol list, but many clones do not implement 29-bit addressing correctly or at all; the Wikipedia protocol list includes both 11-bit and 29-bit ISO 15765-4 at 250/500 kbit/s ([Wikipedia: ELM327 § Protocols supported](https://en.wikipedia.org/wiki/ELM327#Protocols_supported)).
- v1.1 added **Flow Control commands** (`ATFCSH`/`ATFCSD`/`ATFCSM`); v2.3 added three CAN flow-control modes. If a clone does not implement these, manual multi-frame *sends* to a physical ECU address will hang (no FC, no consecutive frames) — a hard limit for UDS 0x22 reads of long DIDs.
- v2.1 added processing of `7F xx 78` (Response Pending). v1.4-based clones may surface `78` to your parser.
- Modes 03/07/09 are the practical generic set on this vehicle. Mode 06 is supported by the ECU (VW documents Monitor-IDs) but the clone's handling of the resulting multi-frame/`NO DATA` cases must be tested per clone. Mode 0A is normally absent on EOBD.

---

## 5. Mode 06 — on-board monitoring test results

### 5.1 Message structure

- **Request:** `06 <OBDMID>` (OBDMID = On-Board Monitor ID, 1 byte, analogous to a PID). `06 00` is the "supported OBDMIDs" query in J1979 Appendix D (bit-encoded like PID `$00`).
- **Positive response:** `46 <OBDMID>` followed by one or more **8-byte test-result groups**:

```
46 OBDMID | TID | UASID | Value Hi | Value Lo | Min Hi | Min Lo | Max Hi | Max Lo
```

| Field | Size | Meaning |
|---|---|---|
| `46` | 1 | Positive response to service `$06` |
| OBDMID | 1 | Which monitor (catalyst, O2, EGR, misfire, PM filter, …) |
| **TID** | 1 | Test ID within that monitor (which test result) |
| **UASID** | 1 | Unit & Scaling ID — selects the unit, scale factor and offset applied to Value/Min/Max (J1979 Appendix E; unsigned and signed variants) |
| Value | 2 | Measured test value, raw |
| Min | 2 | Minimum limit for a healthy system |
| Max | 2 | Maximum limit for a healthy system |

- **Pass/fail rule:** the monitor passes when `Min ≤ Value ≤ Max`, interpreted in the units/scaling given by UASID. `Min`/`Max` represent the boundaries of a *properly operating* system; VW explicitly notes that scan-tool vendors may round them ([VW service manual, Diagnostic Mode 06](https://charm.li/Volkswagen/2011/Jetta%20SportWagen%20%28AJ5%29%20L4-2.0L%20DSL%20Turbo%20%28CJAA%29/Repair%20and%20Diagnosis/Powertrain%20Management/Computers%20and%20Control%20Systems/Testing%20and%20Inspection/Scan%20Tool%20Testing%20and%20Procedures/Diagnostic%20Modes%2001%20-%2009/Diagnostic%20Mode%2006%20-%20Read%20Test%20Results%20For%20Specific%20Diagnostic%20Functions/)).
- **The UASID is a separate byte, not encoded inside OBDMID.** OBDMID selects the monitor; TID selects the test; UASID selects the scaling. (Some vendor documentation conflates them — verify against the actual bytes on the vehicle.)
- Data is retained across ignition-off until a newer result is available **or the DTC memory is erased (Mode 04)**.
- **Critical for support detection:** if the test has not run since results were cleared, or the monitor is unsupported, J1979 forbids a `$22` negative response for `$06` — you will simply get **no answer / `NO DATA`**. Do not interpret that as a fault.

### 5.2 Realistic Mode 06 monitor set on a small VW TDI

VW's own service manual for the 2.0 TDI (CJAA, 2011, Euro 5) documents the following Monitor-IDs — this is the closest published proxy for what a DCM3.7-era VW diesel exposes ([source](https://charm.li/Volkswagen/2011/Jetta%20SportWagen%20%28AJ5%29%20L4-2.0L%20DSL%20Turbo%20%28CJAA%29/Repair%20and%20Diagnosis/Powertrain%20Management/Computers%20and%20Control%20Systems/Testing%20and%20Inspection/Scan%20Tool%20Testing%20and%20Procedures/Diagnostic%20Modes%2001%20-%2009/Diagnostic%20Mode%2006%20-%20Read%20Test%20Results%20For%20Specific%20Diagnostic%20Functions/)):

| OBDMID | Monitor | Typical on VW diesel |
|---|---|---|
| `$01` | Oxygen sensor monitor bank 1 – sensor 1 (wideband lambda) | **Yes** |
| `$02` | Oxygen sensor monitor bank 1 – sensor 2 | **Yes** (if fitted) |
| `$21` | Catalytic converter monitoring (DOC) | **Yes** |
| `$31` | EGR control loop | **Yes** |
| `$81` | Zero-fuel calibration monitor | **Yes** (diesel-specific) |
| `$85` | Boost pressure control loop | **Yes** |
| `$90` | NOx absorber | Only on models with NOx aftertreatment (CJAA has an LNT; a CFWA Euro 5 Polo typically does not) |
| `$A2`–`$A5` | Misfire cylinder 1–4 data | VW documents these, but the Polo is a **3-cylinder** — expect `$A2`–`$A4` at most |
| `$B2` | Particulate matter trap efficiency (DPF) | **Yes** where a DPF is fitted (CFWA Euro 5 has one) |

**Typically NOT exposed on this class of vehicle:** evaporative/EVAP leak monitors (petrol-only; the VW petrol manuals list `$3A`/`$3B`/`$3C`/`$3D` EVAP monitors, absent from the diesel list), secondary air (`$71`/`$72`, petrol), O2 heater monitors `$41`–`$46` (petrol listings), SCR/NOx reagent monitors (Euro 6), and NMHC catalyst. The `01 01` readiness byte C/D should be used to *predict* which monitors the ECU claims to support before you query them.

**Practical implementation advice**
- Probe with `01 01` first: bits `C7/C6/C5/C3` (EGR, PM filter, exhaust gas sensor, boost) tell you which Mode 06 OBDMIDs are worth asking for.
- Issue `06 <OBDMID>` one at a time, with a generous timeout; expect `NO DATA` for unsupported monitors.
- Cache results: they persist across ignition cycles until a new result arrives or Mode 04 clears them, so Mode 06 is *not* a live data source — it is a "last monitor outcome" source.
- Do not surface raw Min/Max without UASID scaling; without it the numbers are meaningless.

---

## 6. What generic OBD-II cannot read on this vehicle

### 6.1 The architectural limit

Generic OBD (J1979/ISO 15031-5) is a **functional-address, emissions-only** interface. Over ISO 15765-4 it only answers on `7DFh` and only for the services in §1, from **emissions-related ECUs only** (ECM/TCM). Anything else requires:

- **physical addressing** to a specific module (`7E0h`+ or a 29-bit ID),
- **UDS (ISO 14229-1)** services such as `0x22` ReadDataByIdentifier, `0x19` ReadDTCInformation, `0x10` DiagnosticSessionControl, `0x27` SecurityAccess, `0x2E`/`0x31`,
- or the older **KWP2000 (ISO 14230-4 / VAG TP2.0)** on legacy modules,
- plus, very often, a **security access seed/key** before the ECU will return the data.

J1979 explicitly allows manufacturers to add services above `$09` (Wikipedia notes "service 22 as defined by SAE J2190… service 21 for Toyota"), and VW's own extended diagnostics live in exactly that space ([Wikipedia: Services/Modes](https://en.wikipedia.org/wiki/OBD-II_PIDs#Services_/_Modes)).

### 6.2 Items the user wants that generic OBD cannot provide

| Wanted | Generic OBD status | Why / what is needed |
|---|---|---|
| **DPF soot mass / ash load** | **Not available.** PID `01 7B` ("DPF") and `01 7A` (DPF differential pressure) are standardised but essentially never implemented by VW over generic OBD | VW measuring-block / UDS `0x22` DID read; needs VCDS/ODIS-class tooling |
| **EGR valve position commanded vs actual** | **Not available.** PID `01 2C` (commanded EGR %) and `01 2D` (EGR error %) exist in J1979 but VW diesels typically do not publish them | UDS `0x22` DID or VW measuring blocks |
| **Injector correction / IMA coding** | **Not available** | UDS `0x22`/`0x2E` with security access; calibration data |
| **Rail pressure setpoint vs actual** | **Only actual** — PID `01 23` (fuel rail gauge pressure, `10·(256A+B)` kPa) is what the repo already polls as `0123`. The **setpoint** and the closed-loop deviation are not in generic OBD | UDS `0x22` DID / measuring blocks |
| **Boost setpoint** | **Only actual** — PID `01 0B` (MAP) / `01 70` (boost pressure control, multi-byte, rarely implemented). Setpoint not available | UDS `0x22` DID |
| **Turbo actuator / VGT position** | PID `01 71` (VGT control) is standardised but not published by VW over generic OBD | UDS `0x22` DID |
| **VW 5-digit fault codes** | **Not available.** Generic Mode 03/07 returns only the 2-byte ISO 15031-6 DTC (e.g. `P0234`). VW's 5-digit workshop codes are a separate numbering scheme reported by VW protocol | VCDS/ODIS/OBDeleven; UDS `0x19` with VW-specific DTC format / KWP2000 |
| **ABS / airbag / BCM / instrument cluster faults** | **Not available.** These modules are not emissions-related and do not answer `7DFh` | Physical addressing to each module's CAN ID + UDS `0x19`, and usually session/security handling |
| **Readiness/monitor data beyond emissions** | Not available | — |

### 6.3 Can this generic ELM327 + daemon reach any of it?

**Partly, in principle — but not reliably, and not without new capabilities.**

| Requirement | ELM327 clone reality |
|---|---|
| Send arbitrary hex payloads | **Yes** — the ELM327 passes any even-length hex string straight to the bus; it does not validate OBD semantics ("it makes no attempt to assess the OBD messages for validity"). Raw hex is exactly what the daemon already sends. |
| Show raw CAN IDs / PCI | **Yes** with `ATH1` / `ATCAF0` |
| 11-bit physical addressing (`7E0h`, `7E1h`, …) | **Yes** with `ATSH 7E0` + `ATCRA 7E8` |
| 29-bit addressing (`18DA10F1`, …) | **Nominal only.** `ATSP7` exists, but clone implementations are unreliable; also the vehicle's modules may use VW's own addressing scheme. Must be tested on the actual car. |
| Manual ISO-TP flow control for long responses | **v1.1+** (`ATFCSH`/`ATFCSD`/`ATFCSM`); v1.4-based clones may not implement it correctly, so long `0x22` reads can hang |
| `0x78` response-pending handling | **v2.1+**; older clones may expose `78` to the parser |
| Security access (`0x27` seed/key) | The ELM327 can carry the bytes, but the **algorithm is VW-proprietary** and not published; without it most interesting DIDs return `0x33 securityAccessDenied` |
| KWP2000 / VAG TP2.0 modules | ELM327 supports ISO 14230-4, but VW's TP2.0 is a distinct transport; community reports are mixed and depend on clone firmware |

**Bottom line for the project:** a read-only feature built on Modes `01/02/03/06/07/09` is achievable today with the existing daemon and clone. DPF soot mass, EGR setpoint, injector coding, rail-pressure setpoint, boost setpoint, VW 5-digit codes and non-powertrain modules are **out of reach of generic OBD**; reaching them requires a VW-aware stack (UDS `0x22`/`0x19` over physical/29-bit addressing, security access, and a VW DID database), i.e. VCDS/ODIS/OBDeleven-class tooling or a purpose-built VW diagnostic implementation. Treat any DID list circulating in forums as unverified unless it is confirmed on the actual ECU.

---

## 7. Safety, legality and bus-load considerations

### 7.1 Is Mode 04 dangerous?

**It is not mechanically dangerous, but it is destructive of diagnostic state and it is not a "readiness reset" — it is a full emissions-data wipe.**

J1979 §5.4.1 defines exactly what `$04` clears ([source](https://archive.org/stream/gov.law.sae.j1979.2002/sae.j1979.2002_djvu.txt)):

- number of DTCs, the DTCs themselves
- the DTC that caused the freeze frame, and the freeze frame data
- oxygen-sensor test data, status of system monitoring tests, on-board monitoring test results
- distance travelled while MIL is activated, number of warm-ups since cleared, distance since cleared, minutes run with MIL on, time since cleared

VW's implementation adds "the adaptation values may also be reset" ([VW service manual, Mode 04](https://charm.li/Volkswagen/2010/Golf%20%285K1%29%20L5-2.5L%20%28CBUA%29/Repair%20and%20Diagnosis/Powertrain%20Management/Computers%20and%20Control%20Systems/Testing%20and%20Inspection/Reading%20and%20Clearing%20Diagnostic%20Trouble%20Codes/Diagnostic%20Mode%2004%20-%20Erase%20DTC%20Memory/)). That means:

- **All readiness bits go back to "not complete"** → the car cannot pass an OBD-based emissions inspection until a full drive cycle re-runs the monitors.
- **Adaptive values (idle/fuel/EGR/DPF learned values) may be lost** → rough idle, changed shift feel, or a DPF regeneration pattern that has to re-learn. This is the real functional risk, not hardware damage.
- **Freeze-frame evidence is destroyed** → the fault context is gone. Clear only after reading Mode 02.
- **Permanent DTCs (Mode 0A) are NOT cleared** by `$04` or by disconnecting the battery; they only clear after the fault is fixed and a PASS + minimum trip conditions are met ([VW/Audi Mode 0A manual](https://charm.li/Audi/2011/S4%20Quattro%20Sedan%20%288K2%29%20V6-3.0L%20SC%20%28CCBA%29/Repair%20and%20Diagnosis/Powertrain%20Management/Computers%20and%20Control%20Systems/Testing%20and%20Inspection/Scan%20Tool%20Testing%20and%20Procedures/Diagnostic%20Mode%200A%20-%20Check%20Permanent%20DTC%20Memory/)).

**Recommendation for this project:** Mode 04 must be **opt-in, gated behind a confirmation, never automatic, and never on a schedule**. Ideally the daemon should not implement it at all in a "screensaver" feature; if it is added, log who/what/when and require an explicit operator action.

### 7.2 Legal / emissions implications

- Clearing DTCs immediately before an inspection to hide an active fault is **emissions tampering**; EPA's enforcement position is that tampering and aftermarket defeat devices are illegal (Clean Air Act §203(a)(3)) — see [EPA: Aftermarket Defeat Devices and Tampering are Illegal](https://www.epa.gov/sites/default/files/2020-12/documents/tamperinganddefeatdevices-enfalert.pdf).
- Even without intent, **"code-free but not ready" fails the test**: readiness monitors reset by `$04` (or by battery disconnect) leave the vehicle "Not Ready", which is an automatic OBD-inspection failure in jurisdictions with I/M programs.
- Where permanent DTCs exist, **a vehicle reporting them via `$0A` will not pass I/M** ([VW/Audi Mode 0A manual](https://charm.li/Audi/2011/S4%20Quattro%20Sedan%20%288K2%29%20V6-3.0L%20SC%20%28CCBA%29/Repair%20and%20Diagnosis/Powertrain%20Management/Computers%20and%20Control%20Systems/Testing%20and%20Inspection/Scan%20Tool%20Testing%20and%20Procedures/Diagnostic%20Mode%200A%20-%20Check%20Permanent%20DTC%20Memory/)).
- For the Polo (EU, EOBD), Mode 0A is typically unsupported, but the readiness-reset consequence of Mode 04 still applies to EU roadworthiness/emissions checks.

### 7.3 Risks of read-only Mode 03/07/06/09 polling while driving

| Concern | Assessment |
|---|---|
| **Bus load** | Negligible. A request frame is 8 bytes; at 500 kbit/s a frame is ~130–150 µs on the wire. Even 10 requests/s is < 0.2 % utilisation. The real cost is **ELM327 serial latency**, not CAN load: measured on this project's Pi, a single PID round-trip is 1.0–5.3 s through the Bluetooth RFCOMM + Hudiy WS chain. |
| **Minimum time between requests** | J1979 defines `P3` as the minimum time between the end of an ECU's response and the next tester request (K-line minimum 55 ms). Respecting the ECU's response completion before the next request is the correct discipline; do not pipeline requests into the ELM327 (it has a single command buffer). |
| **ECU response timing / `0x78`** | Long services (Mode 06, Mode 09 CALID/CVN) may answer with `7F <sid> 78` (response pending). ELM327 v2.1+ handles it internally; older clones may surface it. Never treat `78` as an error and never re-issue the request on `78`. |
| **DTC/MIL state changes** | Modes 03/07/0A are pure reads; they cannot set or clear DTCs. Reading them does not affect the MIL. |
| **Mode 06 while driving** | Read-only, but results are snapshots; polling it rapidly gains nothing and lengthens multi-frame traffic. Poll it at ignition-on or on demand, not in the telemetry loop. |
| **Mode 09 while driving** | J1979 notes Mode 09 data may be unavailable while the engine is running (valid data not guaranteed) — expect `NO DATA`. Query at key-on. |
| **Interference with the existing 7-PID poller** | The daemon already polls 7 PIDs at ~0.35 s + 0.5 s lap. Adding diagnostic queries into that loop will starve telemetry. **Diagnostics should run on a separate, low-priority, serialised queue** — one outstanding ELM327 command at a time, with the telemetry poller paused or deprioritised during a diagnostic sweep. |
| **Bluetooth link stability** | Long multi-frame answers (VIN, CALID, Mode 06 blocks) are the most likely to be truncated by RFCOMM congestion; verify reassembly length against the ISO-TP FF length field and retry once on mismatch rather than emitting partial data. |

### 7.4 Practical guardrails for the new feature

1. **Allowlist** of request strings: `01 xx`, `02 xx 00`, `03`, `07`, `09 02`, `09 04`, `09 06`, `09 0A`, `06 xx`. **Exclude `04` and `08` by default.**
2. **Never** auto-run Mode 04; require an explicit two-step confirmation.
3. **Distinguish** `43 00` (clean) from `NO DATA` (unsupported/no answer) from `7F xx nn` (negative response) in the data model and the UI.
4. **Serialise** diagnostic requests behind the telemetry poller; pause telemetry during a full fault sweep.
5. **Read Mode 02 before ever offering Mode 04** — clearing destroys the freeze-frame evidence.
6. **Show readiness explicitly** (PID `01 01` bits) so the operator can see the consequence of any clear.
7. **Label unsupported data honestly** — "not available via generic OBD" beats a fabricated value, especially for DPF/EGR/rail-pressure setpoints (§6).

---

## 8. Quick reference — hex recipes for the daemon

| Goal | Request | Expected positive response shape |
|---|---|---|
| MIL + DTC count + readiness | `0101` | `41 01 A B C D` |
| Readiness this drive cycle | `0141` | `41 41 00 B C D` |
| Freeze-frame DTC | `0102` | `41 02 xx xx` |
| Stored DTCs | `03` | `43 <n> <DTC pairs…>` |
| Pending DTCs | `07` | `47 <n> <DTC pairs…>` |
| Permanent DTCs | `0A` | `4A <n> …` or `7F 0A 11` |
| VIN | `0902` | `49 02 01 <17 ASCII>` (multi-frame) |
| Calibration ID | `0904` | `49 04 <16 ASCII per ID>` |
| CVN | `0906` | `49 06 <4 bytes per CVN>` |
| ECU name | `090A` | `49 0A <20 ASCII>` |
| Mode 06 test result | `06 <OBDMID>` | `46 <OBDMID> <TID> <UAS> <val> <min> <max>` |
| Warm-ups since cleared | `0130` | `41 30 <count>` |
| Distance since cleared | `0131` | `41 31 <km hi> <km lo>` |
| OBD standard | `011C` | `41 1C 06` (= EOBD) |
| Distance/time with MIL on | `0121` / `014D` | `41 21 …` / `41 4D …` |

---

## 9. Sources

**Primary / standards**
- [SAE J1979:2002 "E/E Diagnostic Test Modes" — full text (Internet Archive)](https://archive.org/stream/gov.law.sae.j1979.2002/sae.j1979.2002_djvu.txt) — service definitions §5 (ISO 9141-2/14230-4/J1850) and §6 (ISO 15765-4), negative-response format and codes §4.2.3.4/§4.2.4, data-not-available rules §4.1.4.2, Mode 04 clear list §5.4.1, PCI note §4.2.7.
- [Wikipedia: OBD-II PIDs](https://en.wikipedia.org/wiki/OBD-II_PIDs) — services list, PID 01/41 bit maps (spark and compression ignition), DTC bit decoding, CAN 11-bit frame format, PID tables incl. diesel PIDs 70–7F.
- [Wikipedia: ISO 15765-2](https://en.wikipedia.org/wiki/ISO_15765-2) — ISO-TP PCI frame types, first/consecutive/flow-control layouts.
- [autosar.dev: NRC (Negative Response Code)](https://autosar.dev/UDS_(Unified_Diagnostic_Services)/NRC_(Negative_Response_Code)) — full ISO 14229-1 NRC table with descriptions.

**ELM327**
- [ELM327 datasheet OCR text (AT commands, CAF0/CAF1, AL, AR, adaptive timing)](http://www.ic-on-line.net/view_online.php?id=1213444&file=0127%5Celm3271_1236855.pdf)
- [Wikipedia: ELM327](https://en.wikipedia.org/wiki/ELM327) — protocols, command set, clone/v1.4 firmware situation, version history (v1.1 flow control, v2.1 `7F xx 78`, v2.3 flow-control modes).
- [ScanTool.net staff: multi-frame response formats (ATH0 `0:`/`1:`/`2:` vs ATH1 raw ISO-TP)](https://www.scantool.net/forum/index.php?topic=5605.msg20662)
- [ScanTool.net: trouble-code parsing on CAN vs non-CAN, 29-bit example, Mode 0A `7F 0A 11`](https://www.scantool.net/forum/index.php?topic=7722.msg28932)
- [ELM327 response-format handling notes (real multi-frame trace)](https://github.com/marius-coding/obd2_tool/blob/main/docs/ELM327_RESPONSE_FORMATS.md)

**Volkswagen / vehicle-specific**
- [VW 2.0 TDI (CJAA) service manual — Diagnostic Modes 01–09](https://charm.li/Volkswagen/2011/Jetta%20SportWagen%20%28AJ5%29%20L4-2.0L%20DSL%20Turbo%20%28CJAA%29/Repair%20and%20Diagnosis/Powertrain%20Management/Computers%20and%20Control%20Systems/Testing%20and%20Inspection/Scan%20Tool%20Testing%20and%20Procedures/Diagnostic%20Modes%2001%20-%2009/Diagnostic%20Modes%2001%20-%2009/)
- [VW TDI manual — Diagnostic Mode 06 (Monitor-ID list for a VW diesel)](https://charm.li/Volkswagen/2011/Jetta%20SportWagen%20%28AJ5%29%20L4-2.0L%20DSL%20Turbo%20%28CJAA%29/Repair%20and%20Diagnosis/Powertrain%20Management/Computers%20and%20Control%20Systems/Testing%20and%20Inspection/Scan%20Tool%20Testing%20and%20Procedures/Diagnostic%20Modes%2001%20-%2009/Diagnostic%20Mode%2006%20-%20Read%20Test%20Results%20For%20Specific%20Diagnostic%20Functions/)
- [VW TDI manual — Diagnostic Mode 07 (pending DTC lifecycle)](https://charm.li/Volkswagen/2011/Jetta%20SportWagen%20%28AJ5%29%20L4-2.0L%20DSL%20Turbo%20%28CJAA%29/Repair%20and%20Diagnosis/Powertrain%20Management/Computers%20and%20Control%20Systems/Testing%20and%20Inspection/Scan%20Tool%20Testing%20and%20Procedures/Diagnostic%20Modes%2001%20-%2009/Diagnostic%20Mode%2007%20-%20Read%20Faults%20Detected%20During%20the%20Current%20or%20Last%20Driving%20Cycle/)
- [VW manual — Diagnostic Mode 04 (what a clear erases, adaptation reset)](https://charm.li/Volkswagen/2010/Golf%20%285K1%29%20L5-2.5L%20%28CBUA%29/Repair%20and%20Diagnosis/Powertrain%20Management/Computers%20and%20Control%20Systems/Testing%20and%20Inspection/Reading%20and%20Clearing%20Diagnostic%20Trouble%20Codes/Diagnostic%20Mode%2004%20-%20Erase%20DTC%20Memory/)
- [VW/Audi manual — Diagnostic Mode 0A (permanent DTC rules, US-only, I/M failure)](https://charm.li/Audi/2011/S4%20Quattro%20Sedan%20%288K2%29%20V6-3.0L%20SC%20%28CCBA%29/Repair%20and%20Diagnosis/Powertrain%20Management/Computers%20and%20Control%20Systems/Testing%20and%20Inspection/Scan%20Tool%20Testing%20and%20Procedures/Diagnostic%20Mode%200A%20-%20Check%20Permanent%20DTC%20Memory/)

**Emissions / legal**
- [EPA: Aftermarket Defeat Devices and Tampering are Illegal](https://www.epa.gov/sites/default/files/2020-12/documents/tamperinganddefeatdevices-enfalert.pdf)
- [CARB: First Phase OBD Readiness Criteria](http://ww2.arb.ca.gov/es/node/37821/printable/print)

---

### Confidence and gaps

- **High confidence:** service/mode definitions and hex framing, PID 01/41/02/30/31 bit layouts, DTC decoding, ELM327 output forms, NRC list, Mode 04 clear list, Mode 0A US-only rule.
- **Medium confidence:** the exact VW Polo CFWA Mode 06 OBDMID set (inferred from the VW 2.0 TDI CJAA manual plus the `01 01` readiness bits — must be probed on the actual car), and whether the specific ELM327 clone implements `ATSP7`/flow-control commands.
- **Explicitly unverified:** any specific VW UDS `0x22` DID numbers for DPF soot mass, EGR commanded position, injector IMA values, rail-pressure setpoint or boost setpoint. These are not published in official VW service literature; community DID lists circulate but none were confirmed against a DCM3.7 ECU in this research. Treat them as unverified until measured on the vehicle.
- **Not measured here:** actual responses from this specific clone. Every "expected" response above should be confirmed once against the car and captured as a fixture.

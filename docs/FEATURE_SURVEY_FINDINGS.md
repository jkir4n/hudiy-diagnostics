# Hudiy Diagnostics — v1 Feature Survey (researcher card t_8e0218be)

> Committed verbatim from the research run (10 Sep 2026, 31 inline sources).
> Provenance: 9 consumer apps surveyed + 14 OSS projects via GitHub API;
> DTC-source (Wal33D/dtc-database) and vPIC API claims independently re-probed
> live by the orchestrator before acceptance. This file is the constraint
> block for Phase 2 implement cards.

# Hudiy Diagnostics v1 — Feature Survey + OSS Findings

Task t_8e0218be. Goal: define the feature scope of the Hudiy menu-launched
Diagnostics dashboard (purely diagnostic; race-dash owns live telemetry).
Protocol layer is already settled in `docs/OBD2_DIAGNOSTICS_RESEARCH.md`;
this note covers only the app-feature surface and reusable OSS ideas.
Constraints assumed throughout: universal (runtime discovery, no hardcoded
vehicle facts), OBD only via the charts-process proxy lane (single served
client), ELM327-clone-safe (single-flight, timeouts, one retry),
menu-launched, NO autolaunch.

Method note: the hosted web-search backend returned empty results for the
whole run, so discovery went through the GitHub REST API plus direct page
extraction (official sites, Play listings, repo pages). Every factual claim
below carries an inline source id; Play ratings are as of 2026-09-10.

## 1. Feature matrix — what diagnostic apps actually do (diagnostic only)

Legend: Y = present, - = absent/not advertised, ~ = partial/limited.
"Dash" (Chariot/Dash Labs OBD app) could not be verified from any citable
source this run and is left out of the matrix rather than guessed.

| Diagnostic feature | Torque Pro | Car Scanner | OBD Auto Doctor | BlueDriver | FIXD | OBD Fusion | Carly | OBDeleven | FORScan |
|---|---|---|---|---|---|---|---|---|---|
| Stored DTC read (Mode 03) | Y | Y | Y | Y | Y | Y | Y | Y | Y (all modules) |
| Pending DTC (Mode 07) | Y[12] | Y[11] | Y[6] | Y[3] | - | Y[10] | Y[13] | Y[25] | Y[4] |
| Permanent DTC (Mode 0A) | - | - | Y[6] | - | - | - | - | - | Y[4] |
| Clear DTC / MIL (Mode 04) | Y[12] | Y[11] | Y[6] | Y[3] | - | Y[10] | Y[13] | Y (non-critical, 1 tap)[25] | Y[4] |
| Freeze frame (Mode 02) | - | Y[11] | Y[6] | Y[3] | - | Y[10] | - | - | - |
| Readiness monitors (Mode 01) | - | Y (emission test check)[11] | Y (2 groups, color-coded)[6] | Y (smog check)[3] | - | Y[10] | Y (emission check)[13] | - | - |
| Mode 06 onboard-monitor results | - | Y[11] | Y (named + raw)[6] | Y[3] | - | Y[10] | - | - | - |
| Mode 05 O2 sensor tests | - | - | Y (legacy protocols)[6] | - | - | Y (O2 results)[10] | - | - | - |
| Offline built-in DTC database | Y (massive)[12] | Y (huge)[11] | Y (18k+ codes)[6] | Y (9k+ codes)[3] | Y (7k+, plain English)[8] | - | Y (repair guides)[13] | - | - |
| Sensor snapshot at scan | - | Y (all sensors, one screen)[11] | Y (export .txt/.csv)[6] | - | - | Y (diagnostic report)[10] | - | - | - |
| VIN / CALID / CVN decode (Mode 09) | - | - | Y[6] | - | - | Y[10] | - | - | - |
| Plain-language severity (safe to drive?) | - | - | ~ (MIL guide)[20] | Y (repair reports)[3] | Y (minor/major)[8] | - | Y[13] | - | - |
| Report export / share | Y (CSV/KML)[12] | - | Y (.txt DTC, .csv sensors)[6] | - | - | Y (save + send to mechanic)[10] | - | Y (share codes)[25] | - |
| Multi-ECU / all-module scan | - | ~ (brand profiles)[11] | ~ (engine + transmission)[6] | - | - | - | Y (all ECUs)[13] | Y (all control units)[25] | Y (all modules)[4] |

Per-app notes (scale for calibration, then diagnostic specifics):

- Torque Pro (Ian Hawkins, 4.2 stars / 81.3K reviews / 1M+ downloads, updated
  Feb 2025)[12]: the reference generic-OBD app. Diagnostic core is
  show-and-reset DTC "like a scantool" plus a massive manufacturer fault-code
  database for lookup.[12] Everything else it does (custom dashboards,
  track recorder, HUD, 0-60, alarms) is telemetry/entertainment and belongs
  to race-dash, not us (its homepage frames the same split: find problems,
  see live ECU data, fix simple faults).[2][12] Notable adoptable-adjacent ideas: a developer
  telnet/AIDL interface to the adapter[12] (our analogue is the proxy lane
  API), and explicit warnings that cheap ELM327 clones are unreliable[12]
  (we should say the same in our docs, given our clone adapter).
- Car Scanner ELM OBD2 (4.5 stars / 358K reviews / 10M+ downloads)[11]: the
  closest model to our v1. Diagnostic set: show/reset DTC with a huge
  description DB, freeze-frame read ("sensors state when DTC is saved"),
  Mode 06 self-monitoring results, emission-test readiness, all-sensors
  one-screen view, custom/extended PIDs, and per-brand connection profiles
  including Volkswagen, Skoda, Seat, Audi.[11] Its homepage pitches the same core
 loop we want: watch parameters to find problems before the MIL lights,
 then read the code plus its description to judge severity.[1] The brand-profile idea maps
  directly onto our runtime-discovery rule: probe what the car supports,
  then pick the decode path — never hardcode.
- OBD Auto Doctor reports 6.7M+ downloads.[5] It is the best-documented diagnostic UX
  and the richest citable source. Confirmed/pending/permanent DTC tabs,
  freeze frame with causing-DTC + parameter recording, 18k+ offline DTC DB,
  export to text, readiness in two groups (since-DTC-cleared + this-drive-cycle)
  with Complete/Incomplete/Disabled states, Mode 05 + Mode 06 with result,
  limits and pass/fail, ECU info (name, VIN, CALID, CVN, supported sensors),
  Mode 08 service routines incl. DPF regeneration, in-use performance
  tracking, and an advanced-user console for raw commands.[6] Its tutorial set
  doubles as UX copy we can learn from (see sections 4-5).
- BlueDriver (1.1M+ devices, 60k reviews, 9k codes)[3]: the plain-language
  benchmark. Translates codes to plain language, repair reports from
  "millions of verified fixes", Mode 6 framed as "catch issues before they
  become problems", freeze frame as "what was happening when the code was
  triggered", smog check as "know if you'll pass before you go".[3] Adopt
  the framing, not the cloud dependency (we are offline-first).
- FIXD (3M+ sensors, 10k 5-star reviews)[8]: the non-expert benchmark.
  7000+ codes in plain English, issue severity (minor vs major, i.e. safe to
  keep driving or not), maintenance alerts by make/model/mileage.[8] Adopt
  the severity verdict; maintenance alerts are out of scope (no cloud, no
  history server in v1).
- OBD Fusion (OCTech, CarPlay + Android Auto)[10]: Diagnostics tab (codes,
  freeze frame, live PID, full diagnostic report to save/send to a
  mechanic), Monitors tab (emissions readiness, O2 results, Mode 06, VIN and
  calibration IDs), custom PIDs, CSV logging with Dropbox upload.[10] The
  "diagnostic report to send to a mechanic" is the export feature to copy.
- Carly (4.2 stars / 34K reviews / 1M+ downloads, updated Sep 2026)[13]:
  free tier is OBD diagnostics + live data + emission check; paid tier adds
  all-ECU codes, severity, repair guides, battery check, coding, mileage
  (used-car) check, service reset.[13] Its positioning is "diagnose and code
  your car"[9] with a proprietary
  scanner and yearly subscription[13] — the anti-model for our universal,
  no-vendor-lock-in tool. Adopt only the used-car-check idea (later).
- OBDeleven (6M+ vehicles, VW/BMW/Toyota/Ford/Mercedes licensed)[7]:
  advanced brand diagnostics (scan all control units, diagnose/clear/share
  codes incl. engine, transmission, ABS, airbag, multimedia, A/C) plus a
  generic OBD2 mode for other brands (engine + transmission faults, clear
  non-critical codes with a single tap).[25] Proprietary device + credits;
  adopt the "share fault codes" flow and the critical/non-critical clear
  distinction, nothing else.
- FORScan (Ford/Mazda/Lincoln/Mercury only)[4]: all-module DTC read/reset,
  network-configuration detection, module PIDs, service procedures,
  programming on Windows with extended license.[4] Two lessons: (a) it no
  longer recommends ELM327 clones at all and pushes OBDLink/ELS27/J2534
  hardware[4] — a data point for our clone-reliability caveats; (b) deep
  brand-specific function is exactly what our universal scope excludes.
  (Note: its public v2 documentation is still thin — only PID display
  settings published so far[24] — so v1-era behavior above is the citable
  surface.)

## 2. OSS projects — adopt ideas, never import code

| Project | Stars / state (2026-09-10) | License | Adoptable idea for us | URL |
|---|---|---|---|---|
| brendan-w/python-OBD | 1307 stars, 427 forks, last push Apr 2025, 95 open issues (cooling) | GPL-2.0 [16] | Command-table structure (PID -> decode fn + unit), auto-protocol connect, Pint-style unit conversion concept | https://github.com/brendan-w/python-OBD [16] |
| Pbartek/pyobd-pi | 425 stars, pushed Feb 2024 | GPL-2.0 | Pi-specific serial/BT fixes lineage (historical reference only) | https://github.com/Pbartek/pyobd-pi [27] |
| peterh/pyobd | 469 stars, pushed Dec 2018 (stale) | GPL-2.0 | Lineage root only; do not use | https://github.com/peterh/pyobd [28] |
| commaai/opendbc | 3400 stars, 2.2k forks, pushed 2026-09-09 (very active) | MIT [17] | DBC signal-decode table structure + per-car fingerprinting concept (identify car from bus behavior, then select decode data) | https://github.com/commaai/opendbc [17] |
| openxc/openxc-python | 119 stars, pushed Mar 2022 (stale) | BSD-3-Clause | Vehicle-signal abstraction idea only; stale, Ford-centric | https://github.com/openxc/openxc-python [26] |
| fenugrec/freediag | Old C project, CLI only, NO CAN/ISO-15765 support, "development mostly at a standstill" | OSS (see repo) [19] | Scantool manual's J1979 framing knowledge (cross-check for our research note); KWP1281/VAG-over-K-line note for pre-CAN VAG archaeology only | https://freediag.sourceforge.net [19] |
| Wal33D/dtc-database | 47 stars, 14 forks, pushed Feb 2026 | MIT [14] | THE DTC-data source (see section 3): offline SQLite, zero-dep wrappers | https://github.com/Wal33D/dtc-database [14] |
| sathya1495/obd2-dtc-database | 1 star, 1 commit, 60 P-codes only | MIT (readme) [18] | Too small; skip (listed so nobody re-evaluates it) | https://github.com/sathya1495/obd2-dtc-database [18] |
| iUnreallx/ReDrive | 127 stars, 256 commits, active Sep 2026 (2 days old at survey) | GPL-3.0 | UI/UX-first no-ads diagnostic layout; BT/WiFi/USB + auto-reconnect; tested polling controller; ELM327 v1.5-on-PIC advice | https://github.com/iUnreallx/ReDrive [15] |
| iUnreallx/ELM327-Emulator | 10 stars | MIT | Offline dev/test harness: emulate ELM327 answers without hardware | https://github.com/iUnreallx/ELM327-Emulator [29] |
| Paul-HenryP/PyOBD-Dashboard | 10 stars, pushed Jul 2026 | unspecified | Second data point that Python+ELM327 desktop diagnostic layout is viable | https://github.com/Paul-HenryP/PyOBD-Dashboard [30] |
| 2KAbhishek/CarBoard | 7 stars, pushed Feb 2023 | GPL-3.0 | Name only; dashboard-scope, stale | https://github.com/2KAbhishek/CarBoard [31] |
| yubun241/obd2-dashboard | 0 stars, May 2026 | unspecified | Web Bluetooth + PWA dashboard precedent (web-tech UI is feasible) | (GitHub search result, id in evidence/gh_summary.json) [unverified] |
| alisk2004/car-diagnostic-assistant | 0 stars, Jul 2026 | unspecified | Rule-based symptom-to-fault expert system — the "later" triage idea | (GitHub search result, id in evidence/gh_summary.json) [unverified] |

License guardrail: python-OBD (GPL-2.0)[16] and ReDrive (GPL-3.0)[15] are
ideas-only sources; nothing GPL-derived goes into our tree. MIT/BSD sources
(opendbc[17], Wal33D[14], emulator[29]) are bundle candidates, but per the
task brief we adopt ideas, never import code. freediag's explicit
no-CAN statement[19] confirms it has nothing for our ISO 15765-4 path.

## 3. DTC text-meaning data

Where apps get it: they all bundle offline databases and treat that as a
feature — "massive fault code database" (Torque)[12], "huge database of DTC
descriptions" (Car Scanner)[11], "offline DTC database... over 18000 trouble
codes" (OBD Auto Doctor)[6], "9,000+ diagnostic codes" (BlueDriver)[3],
"7000+ error codes into plain English" (FIXD)[8]. Generic P/B/C/U meanings
derive from SAE J2012 (the standard itself is paywalled; apps ship
paraphrased definitions — which is also why offline paraphrase DBs are the
norm, not the standard text).

Recommendation — bundle Wal33D/dtc-database data (MIT)[14]:
offline-first SQLite (`data/dtc_codes.db`), zero-dependency wrappers for
Python/Java/Android/TypeScript, current snapshot 18,805 rows / 12,128 unique
codes: 9,415 generic + 9,390 manufacturer-specific across 33 brands, split
P 14,821 / B 1,465 / C 985 / U 1,534.[14] Lookup is code + optional
manufacturer context (e.g. `get_dtc("P1690", "FORD")`).[14] Sister projects
cover NHTSA VIN decode and recall lookup with cross-project examples.[14]
Pre-build verification items: spot-check VW P1xxx coverage against our
fixtures, and confirm the .db size is acceptable for the Pi image.

Vendor-specific handling (v1): generic lookup first; manufacturer-specific
codes show the make-contextual definition when present, else the raw code
plus "manufacturer-specific, meaning varies by make" fallback copy (same
honesty pattern as OBD Auto Doctor showing raw OBDMID/TID for unnamed
manufacturer Mode 06 monitors — see section 4). No brand-locked packs, no
cloud lookup: that is the Carly/OBDeleven model we explicitly reject.[13][7]

VIN decode: NHTSA vPIC offers a free HTTP API (XML/CSV/JSON DecodeVin incl.
flat and extended forms, partial-VIN support) plus downloadable standalone
databases for offline use, behind automated rate control.[23] It is
US-manufacturer-submittal data, so verify Indian-market VW coverage at build
time; the downloadable DB is the offline-first answer if coverage holds.
(Wal33D's nhtsa-vin-decoder sister project wraps the same source.)[14]

## 4. Readiness + Mode 06 UX (what "good" looks like to non-experts)

- Readiness as colored status cards: OBD Auto Doctor shows both monitor
  groups — status-since-DTCs-cleared AND status-this-drive-cycle — with
  Complete (green) / Incomplete (red) / Disabled (gray), and frames the
  whole screen as "check emission readiness yourself" against EPA
  incomplete-monitor allowances.[6] BlueDriver's Smog Check is the same idea
  in one line: "know if you'll pass before you go", scanning emissions
  systems and readiness monitors.[3] Carly ships a plain "Emission Check" in
  the free tier.[13] OBD Fusion's Monitors tab groups readiness + O2 results
  + Mode 06 + VIN/CALIDs in one place.[10] Recommendation: one "Emission
  readiness" card wall (per-monitor pass/fail/incomplete chips + one verdict
  line), never raw PID 01 bit tables.
- Mode 06 as result + limits + pass/fail: OBD Auto Doctor presents test
  value vs minimum/maximum limits with a pass/fail verdict, under plain
  monitor names (Catalyst, EGR, Boost Pressure, NOx/SCR, PM Filter, misfire
  data — the diesel-relevant set for our TDI), and for unnamed manufacturer
  monitors shows raw OBDMID/TID/values with a look-it-up pointer instead of
  guessing.[22] It sells Mode 06 on four concrete jobs: catch emerging
  problems before a code sets, explain runnability issues without codes,
  show whether a code was a hard or marginal failure, verify a repair
  without waiting days for self-tests.[22] BlueDriver uses the same pitch in
  one line ("catch issues before they become problems").[3] Recommendation:
  per-monitor pass/fail rows with test-vs-limit numbers, marginal-failure
  highlighting, raw-detail expander for experts.
- Severity verdict: FIXD's minor/major "safe to keep driving?" flag[8] and
  Carly's health + severity tracking[13] beat raw code lists. OBD Auto
  Doctor's MIL guide gives the copy template: occasional flash vs steady-on
  vs constant flashing (misfire — stop immediately, catalyst/fire
  risk).[20] Recommendation: every scan ends in one verdict line.

## 5. Mode 04 (clear DTCs) safety UX

The reputable pattern is OBD Auto Doctor's reset tutorial, and we should
copy its structure outright[21]:

1. Fix-first guidance: "diagnostic trouble codes appear for a good reason...
  Only after fixing, proceed to resetting"; unfixed codes "might come back
  immediately"; random-failure clears are the stated exception, with "ensure
  no problems every time before reset".[21]
2. Explicit consequence list at the acknowledge step: reset clears codes AND
  freeze frame AND test-result status; the car "may run poorly while it
  performs re-calibration"; readiness monitors reset too, so the car "will
  not pass emissions inspection immediately after the reset... the smog
  device will fail your car".[21] Both desktop ("Clear the DTCs" button)
  and mobile ("Reset trouble codes and MIL") require reading and
  acknowledging the info screen before the command is sent.[21]
3. Never suggest the battery-disconnect shortcut: "new vehicles can have
  systems that need constant battery voltage... the car theft system or
  infotainment system might be reset"; OBD-tool reset "is how the
  professional mechanics do it".[21]

OBDeleven adds the critical/non-critical distinction (single-tap clear for
non-critical codes only).[25] Recommendation: a two-screen confirm flow —
screen 1: consequence list (freeze frame lost, readiness reset, smog fail,
re-calibration roughness) + fix-first checkbox; screen 2: result + "monitors
incomplete, drive cycle needed" follow-up state. Permanent (Mode 0A) codes
get an explicit "cannot be cleared by any tool, ECU clears them" note (OBD
Auto Doctor documents them as system-cleared).[6]

## 6. v1 recommendation (under our constraints)

Must-have (Phase 2b backend slice):
1. One-tap health scan: Modes 03/07/0A + Mode 01 MIL/readiness (the same
   three-DTC-type + readiness coverage OBD Auto Doctor ships)[6], run as ONE
   queued proxy-lane sequence (single-flight, timeout-guarded; NO DATA =
   empty is a valid negative per our fixtures).
2. DTC list with bundled offline text (Wal33D data, section 3)[14] + per-code
   plain-language severity verdict (FIXD-style safe-to-drive flag).[8]
3. Freeze frame per DTC (Mode 02 + causing-code PID), the BlueDriver
   "what was happening when it triggered" framing.[3]
4. Emission-readiness card wall (both monitor groups, green/red/gray) with
   one pass/fail verdict (OBDAD + BlueDriver pattern).[6][3]
5. Vehicle/ECU identity: VIN + ECU name + CALID/CVN (Mode 09, guarded —
   CALID multi-frame is the ELM wedge trigger, so single-flight + <=15 s +
   one retry max), the same identity set OBD Auto Doctor and OBD Fusion
   surface,[6][10] with vPIC-style decode presentation.[23]
6. Mode 04 clear with the section-5 two-screen safety flow[21]; permanent-code
   honesty note (system-cleared only).[6]
7. Mode 06 monitor summary (pass/fail per named monitor incl. EGR/boost/PM
   filter for the TDI; raw OBDMID/TID expander, never guessed names).[22]
8. Scan report export/share (text + CSV) for the mechanic/forum — the OBD
   Fusion "diagnostic report" and OBDAD export pattern.[10][6]
9. Runtime discovery throughout (0100/0120/0900 probing, never hardcoded
   PIDs) — the Car Scanner brand-profile idea done right.[11]

Should-have: Mode 06 per-test limit detail + marginal-failure flags (the
repair-verification job OBD Auto Doctor documents);[22] sensor snapshot
captured at scan time (Car Scanner's all-sensors screen);[11] distance and
warm-ups since clear on the report (standard Mode 01 PIDs); used-car
inspection framing (Carly's mileage check as inspiration, OBD-only
signals).[13]

Later (explicit): Mode 08 service routines (DPF regen control — display
readiness only in v1, since even OBD Auto Doctor gates these as
bi-directional controls);[6] Mode 05 legacy; in-use performance
counters;[6] cloud repair guides; maintenance alerts (FIXD-style alerts need
a history server we don't have in v1);[8] symptom-guided triage
(expert-system idea);[unverified] multi-ECU brand-deep functions
(FORScan/OBDeleven territory).[4][25]

Never (belongs to race-dash or violates scope): live gauges/dashboards,
trip computer, logging/graphing/oscilloscope, HUD mode, 0-60/perf timers,
track recorder, alarms, CarPlay/Android Auto, themes.[12][11][10] And never:
coding/one-click apps, programming, subscriptions or vendor-locked
scanners.[13][7]

## Sources

[1] https://www.carscanner.info
[2] https://torque-bhp.com
[3] https://www.bluedriver.com
[4] https://forscan.org/home.html
[5] https://www.obdautodoctor.com
[6] https://www.obdautodoctor.com/features
[7] https://obdeleven.com
[8] https://www.fixd.com
[9] https://www.mycarly.com
[10] https://www.obdsoftware.net/software/obdfusion
[11] https://play.google.com/store/apps/details?id=com.ovz.carscanner
[12] https://play.google.com/store/apps/details?id=org.prowl.torque
[13] https://play.google.com/store/apps/details?id=com.iViNi.bmwhatLite
[14] https://github.com/Wal33D/dtc-database
[15] https://github.com/iUnreallx/ReDrive
[16] https://github.com/brendan-w/python-OBD
[17] https://github.com/commaai/opendbc
[18] https://github.com/sathya1495/obd2-dtc-database
[19] https://freediag.sourceforge.net
[20] https://www.obdautodoctor.com/blog/what-to-do-when-malfunction-indicator-light-illuminates
[21] https://www.obdautodoctor.com/tutorials/how-to-read-and-reset-the-check-engine-light
[22] https://www.obdautodoctor.com/tutorials/using-obd2-mode-06-for-advanced-car-diagnostics
[23] https://vpic.nhtsa.dot.gov/api
[24] https://forscan.org/documentation.html
[25] https://obdeleven.com/diagnostics
[26] https://github.com/openxc/openxc-python
[27] https://github.com/Pbartek/pyobd-pi
[28] https://github.com/peterh/pyobd
[29] https://github.com/iUnreallx/ELM327-Emulator
[30] https://github.com/Paul-HenryP/PyOBD-Dashboard
[31] https://github.com/2KAbhishek/CarBoard

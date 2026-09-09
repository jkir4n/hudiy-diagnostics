# Diesel drive-cycle + readiness completion — findings
### Hudiy Diagnostics readiness wall · reference car: VW Polo TDI diesel (~2010s era)

Scope: the explanation-copy layer and diesel-specific readiness behaviour behind the
readiness wall (monitors shown as Complete / Incomplete). What to show was covered by the
feature survey; this document covers what each state *means*, how monitors complete on a
TDI-era diesel, and what honest copy to put in front of a non-expert driver. No code.

Short version: a TDI-era diesel runs six non-continuous emission self-tests (EGR, boost
pressure, PM filter, exhaust gas sensor, NMHC catalyst, NOx aftertreatment) plus three
continuous ones (misfire, fuel system, comprehensive components).[1][2] Clearing codes or
disconnecting the battery wipes all of them back to Incomplete by design, and on a diesel
getting them back can take a 60–90 minute structured drive — or hundreds of miles when the
soot filter or NOx system is being stubborn.[9][10] Incomplete with the engine warning
light off is usually a *driving-pattern* problem, not a broken car.[10]

## 1. Which monitors a TDI-era diesel runs, and what completes each

A modern compression-ignition (diesel) vehicle reports a different monitor set from a
petrol car: NMHC catalyst, NOx/SCR aftertreatment, boost pressure, exhaust gas sensor, PM
filter, and EGR/VVT, alongside the continuous misfire, fuel system and comprehensive
component monitors.[1][2] The continuous three run constantly whenever the engine runs;
the six diesel ones are non-continuous, meaning each runs at most once per trip and only
when its entry conditions line up.[1][2]

| Monitor | What it checks, in plain terms | What typically completes it |
|---|---|---|
| Misfire (continuous) | Detects cylinders failing to fire, via crankshaft-speed wobble.[1] | Runs constantly; ready almost immediately on a healthy engine.[3][9] |
| Fuel system (continuous) | Checks fuel-trim corrections (the ECU adding/subtracting fuel to hold the right mixture) stay within bounds.[1] | Runs constantly once warm; needs stable operating temperature.[14] |
| Comprehensive components (continuous) | Sanity-checks every emissions-relevant sensor and actuator for opens, shorts, out-of-range and implausible values.[1] | Runs constantly; almost always ready.[3] |
| EGR system | Checks exhaust-gas-recirculation flow (used to keep combustion temperatures down and NOx in check) at preset points in a trip.[1] | Specific engine load/RPM windows plus closed-throttle deceleration (foot fully off, fuel cut active).[14][15] VW's TDI procedure adds steady-speed holds and a defined coast phase.[10] |
| Boost pressure | Checks the turbo system builds the commanded intake pressure and its parts are intact; runs once per trip.[1] | Steady cruise at moderate load (e.g. 50–60 mph held for minutes), no hard throttle.[14][15] |
| PM (soot) filter | Checks the filter traps soot *and* can burn it off (regenerate).[1] | The hard one: it needs a full cycle of soot building up, then a sustained hot burn — typically 30–45 minutes at a constant 50–70 mph in a high gear.[10] Switching off mid-regeneration aborts it.[10] |
| Exhaust gas sensor | Checks the exhaust-content sensors other monitors depend on.[1] | Warmed-up exhaust plus specific acceleration/coast steps; VW lists idle holds, a pull to ~2500 rpm with a sharp lift-off, and a 10-second coast at 3000 rpm in 4th.[10] Owners report this as the most stubborn bit after a reset.[7] |
| NMHC catalyst | Checks the oxidation catalyst converts leftover hydrocarbons and is hot enough to support PM regeneration.[1] | Sustained hot highway running; it and the PM monitor mature together.[1][10] |
| NOx/SCR aftertreatment | Checks the NOx trap or urea-SCR (AdBlue) system keeps tailpipe NOx within limits.[1] | Long constant-speed running (30–40 minutes at 50–70 mph in VW's procedure); setting is delayed in cold/winter conditions and needs much longer driving.[10] |

Three labelling traps for the wall. First, generic scan tools show *petrol* names
(Catalyst, O2 Sensor, Heated Catalyst) for what on a diesel are really the NMHC, NOx/SCR
and exhaust-gas-sensor bits — owners get confused by exactly this.[7] VCDS is noted for
decoding diesel readiness properly, including common-rail TDI engines.[9] A Ross-Tech
forum case shows the aliasing trap live: a V6 Touareg reported "Catalyst" and "Oxygen
sensor heater" incomplete — petrol names for diesel bits — immediately after its owner
cleared an EGR code.[8] Second, each
monitor is reported as supported/not-supported *and* complete/incomplete; an unsupported
monitor (e.g. secondary air on a car without that pump) must never count against the
verdict.[6][13] Third, some tools also report a Disabled state when conditions make a
test unrunnable for the rest of the cycle (e.g. temperature out of range), which is
different from failed.[2]

## 2. Why monitors reset, how long re-completion takes, and what the verdict hinges on

Clearing codes (Mode $04) or disconnecting the battery resets every testable readiness
bit to Fail/Incomplete — VCDS, OBD Auto Doctor and Steer all describe this identically,
and it is deliberate anti-tamper design so a fault cannot be hidden the day before a
test.[2][3][9] Volkswagen tells dealers the same thing: after DTCs are erased, a TDI
simply needs more driving under varied conditions, and this alone indicates no technical
problem with the car.[10]

How long that takes depends on the car and the driving. On a healthy car, Ross-Tech's
rule of thumb is 2–3 days of driving including at least one short highway trip.[9] VW's
own TDI setting procedure takes roughly 60–90 minutes of structured driving — *if* the
entry conditions cooperate — and warns that driver profile and environment can extend it
far beyond that.[10] In practice TDI owners report hundreds of miles: ~800 miles with the
exhaust-gas-sensor bit still stuck, and 1,000–1,700 mile sagas for NOx/PM bits after
repairs.[7] Note the unit that matters is *proper cold starts*, not distance: one 200-mile
trip gives exactly one cold start, while catalyst-type monitors may need two or three
full cycles with an overnight soak between them.[14]

"Incomplete" vs "not ready" is terminology, not two different states: Complete/Ready
means the self-test has run and passed since the last reset; Incomplete/Not Ready means
it has not run yet, usually because the car has not seen the right conditions.[2][6]
What matters for the verdict line is therefore not the words but the arithmetic the
inspection station performs: it reads Mode $01 PID $01 (warning-light state, stored-code
count, per-monitor status) and counts *supported-but-incomplete* monitors against the
local allowance, with the warning light off and no stored codes as co-conditions.[4][13]

Allowances the wall must encode as configurable rules, not hard-code: the common US
pattern is up to two incomplete monitors for 1996–2000 and one for 2001+ cars.[2][3][6]
California is stricter and diesel-specific: 1998–2006 diesels must show zero incomplete,
while 2007-and-newer diesels may show the particulate-filter and NMHC monitors
incomplete (revised July 2023).[4][5] California also tightened petrol rules toward
all-monitors-complete from late 2025, which signals the direction of travel — keep the
rule table server- or config-driven and check local requirements before wording any
"you will pass" promise.[6]

## 3. Top 5 reasons a TDI sits "not ready" with no fault codes

1. Short trips only. The PM monitor needs a sustained hot regeneration run (tens of
minutes at highway speed); a car doing two-mile hops never gets there, and the same
applies to catalyst-type tests that need steady cruise.[10][14] "Simply covering two
hundred highway miles usually does not work" either, if it lacks cold starts and varied
stages.[14]
2. Interrupted regenerations. The DPF cycle is soot build-up *then* burn-off; stopping
the engine mid-burn aborts it and the monitor waits for the next full cycle.[10] Owners
learn to recognise an active regeneration (cooling fans, high idle, hot smell) and not
switch off mid-way — worth a wall hint drawn from this mechanism.
3. Servicing or clearing codes right before the test. Any reset restarts the whole
clock, so VW advises customers not to service the car directly before inspection.[10]
One owner's 800 miles of progress was wiped by a cheap scan tool that reset the monitors
without confirmation while merely graphing live data — so the wall should warn before
any code-clear action.[7]
4. Cold weather and never-fully-warm running. VW states NOx-aftertreatment readiness is
delayed in winter and needs much longer driving.[10] EGR and sensor tests likewise need
full operating temperature and specific load windows, so a car that never warms through
(or has a lazy thermostat keeping it cool) will hold those bits incomplete with no code
stored.[14][15]
5. Fresh exhaust parts, low AdBlue, or a test still failing silently. After a DOC/DPF
replacement the exhaust-gas-sensor monitor can stay incomplete for 6,000–10,000 miles
while the new catalyst "degreens" (documented on Ford diesels; the mechanism is
diesel-general).[4] On SCR/AdBlue cars the NOx monitor needs its long steady cruise,
and a stored-or-even-pending fault inhibits monitors from running at all — so "no fault
codes" should always be re-verified, including pending codes, before blaming driving
style.[10][15]

## 4. Paste-ready copy blocks (British English)

Each block is 3–4 sentences, written for a driver with no technical background. Jargon is
glossed on first use. Derived from the findings above; keep the wording stable and put
any rule numbers (e.g. "one monitor allowed") behind the configurable rule table, not in
the strings.

(a) Monitors incomplete after a code clear.
> Your car's self-checks were reset when the fault codes were cleared, so each emissions
> system must prove itself healthy again before the car can report it as Ready. This is
> normal and does not mean anything is broken — the checks (called readiness monitors)
> simply have not run yet. It usually takes a few days of mixed town and motorway driving,
> including starting the car from fully cold, before they all complete. Avoid clearing the
> codes again in the meantime, as that restarts the whole waiting period from zero.

(b) Why the EGR or boost monitor is still not ready.
> The exhaust-gas-recirculation (EGR) check and the turbo-boost check only run when the
> engine is fully warmed up and sees particular kinds of driving, such as steady cruising
> followed by easing off the accelerator without braking. Short trips around town almost
> never include those moments, so these two monitors are often the last to turn Ready.
> Give the car a longer run with some steady motorway cruising and gentle slow-downs, and
> they will usually complete on their own. If they still refuse after several such drives,
> the system may be finding a real fault and it is worth having it diagnosed rather than
> driving further.

(c) Drive-cycle tips to complete monitors faster.
> Start with the car parked overnight so the engine is genuinely cold, keep the fuel tank
> between a quarter and three quarters full, and check no warning lights or fault codes
> are present. Then drive a mix: a few minutes of gentle town driving, about ten minutes
> of steady motorway cruising using cruise control if you have it, one long ease off the
> accelerator without braking, and a couple of minutes idling at the end. Repeat with
> another cold start the next day rather than doing one giant trip, because most checks
> need to see two or three cold starts to sign off. If a single monitor is still not Ready
> after three such drives, stop repeating the cycle and get that system checked — the test
> is probably running and failing, not waiting for better driving.

## 5. Warning-light and code semantics, and how inspections treat them (honest severity copy)

Codes come in three flavours. A *pending* code means a test failed once: the warning
light (MIL, the engine-shaped "check engine" lamp) stays off and no snapshot of engine
data is stored; if the fault repeats on the next trip the light comes on and the code
becomes *stored/confirmed*, and if it does not repeat the pending code is erased.[12]
Most emission monitors are "two-trip" like this — first failure stores pending, second
consecutive failure lights the lamp and stores the code — while severe faults (e.g. a
misfire bad enough to damage the catalyst) light or even flash the lamp on the first
trip.[1][12] The lamp then stays on until three consecutive clean trips turn it off, but
the codes linger in memory for 40 warm-up cycles (80 for fuel and misfire faults) before
self-erasing.[12]

*Permanent* codes (PDTCs) are the trap for copy writers: they cannot be erased by any
scan tool or battery disconnect and clear only when the ECU itself verifies the repair
over subsequent driving.[4] California fails 2010-and-newer cars with any permanent code
present *regardless of whether the warning light is on or off*, excusing them only after
15 warm-up cycles plus 200 miles since the last clear — and some Audi TDI permanent fuel
codes are officially acknowledged as uncleared with no remedy, ignored by the test
equipment.[4] So "light off, therefore fine" is not a promise the wall can make wherever
PDTC rules apply.

Inspection treatment, distilled for severity copy: warning light on with the engine
running is a fail everywhere.[4] Too many incomplete monitors is *also* a fail even with
the light off and no codes — which is why "no faults found" must never be worded as
"will pass inspection".[5] Pending codes alone are generally tolerated at inspection
(some rules explicitly allow testing with only pending codes present), but VW's own
guidance says ignore pending codes for *repair* decisions while also warning that active
faults stop monitors completing — so the wall should show pending as "being watched,
not yet a failure".[10][11] For "safe to drive?" wording: incomplete monitors with the
light off are an admin/inspection matter, not danger; a steady warning light means an
emissions fault to get diagnosed soon with gentle driving; a flashing warning light
means a severe misfire that can destroy the catalyst — back off and stop as soon as it
is safe.[1]

## Implications for the readiness wall

- Label diesel monitors with diesel names (NMHC catalyst, NOx/SCR aftertreatment, boost
  pressure, exhaust gas sensor, PM filter, EGR) — never the petrol aliases some adapters
  report — and add one-line glosses, since mislabelled bits are a documented source of
  owner confusion.[7][9]
- Compute the verdict from four inputs together (supported-but-incomplete count vs the
  selected region rule, warning-light state, stored codes, permanent codes) and show
  which input is failing; "Ready/Not ready" alone is not a verdict.[4][5]
- Attach a per-monitor "how to complete" hint (steady cruise, cold start + coast, long
  hot run for PM/NOx) drawn from section 1, so Incomplete always comes with a next
  action.[10][14]
- Gate the "clear codes" action behind a confirmation that names the cost (all monitors
  restart; hundreds of miles possible on a diesel) and suggest clearing only just after,
  never just before, an inspection.[7][10]
- Render Not Supported and Disabled as neutral grey states that never count against the
  verdict, visually distinct from amber Incomplete.[2][13]
- Track cold starts and sustained-cruise minutes, not just kilometres, as the progress
  metric — distance without cold starts does not complete monitors.[14]
- Show pending codes as a "being watched" state with VW's own advice attached (don't
  repair on pending alone, don't reset because of it), rather than as pass or fail.[10]
- Keep every region allowance (US default, California diesel PM+NMHC, future
  all-complete rules) in a configurable table with a "check your local rules" footnote,
  since California has already moved once in 2023 and is moving again.[4][6]

## Sources

[1] https://pro.repairsolutions.com/article/monitors — RepairSolutionsPRO OBD II monitors (continuous/non-continuous incl diesel NMHC NOx boost PM)
[2] https://www.obdautodoctor.com/tutorials/obd-readiness-monitors-explained — OBD Auto Doctor readiness monitors explained (diesel list, drive cycle)
[3] https://steer.so/blog/obd2-readiness-monitors-explained — Steer OBD2 readiness monitors inspection guide
[4] https://www.bar.ca.gov/obd-test-reference — California BAR OBD Test Reference (readiness/MIL/PDTC standards)
[5] https://asktheref.org/information/monitor-readiness-concerns — AskTheRef OBDII monitor readiness concerns (CA diesel allowances)
[6] https://carcodefinder.com/tools/monitor-readiness-status — CarCodeFinder OBD-II monitor readiness status (SAE J1979, allowances)
[7] https://forums.tdiclub.com/index.php?threads/about-obd-readiness-monitors-and-drive-cycles-for-state-inspections-of-tdi-models.542651 — TDIClub forum: OBD readiness + drive cycles for TDI state inspections (anecdote)
[8] https://forums.ross-tech.com/index.php?threads/31379 — Ross-Tech forum: TDI OBD drive cycle thread (anecdote)
[9] https://www.ross-tech.com/vcds/tour/readiness.php — Ross-Tech VCDS readiness tour (diesel readiness decode, drive time)
[10] https://pics.tdiclub.com/data/500/tt011518_diesel_readiness.pdf — VW TSB 01-15-18 TDI Clean Diesel I/M readiness not set (2023591/4)
[11] https://pro.repairsolutions.com/article/i-m-readiness — RepairSolutionsPRO I/M readiness monitor status
[12] https://pro.repairsolutions.com/article/diagnostic-trouble-codes — RepairSolutionsPRO diagnostic trouble codes (confirmed/pending/permanent, MIL logic)
[13] https://obdllm.com/en/docs/readiness-monitors — OBDLLM readiness monitors reference
[14] https://obdllm.com/en/blog/obd-drive-cycle-how-to-complete — OBDLLM drive cycle guide (cold starts, per-monitor stuck causes)
[15] https://vehicleruns.com/maintenance-repair/exhaust-emissions/complete-drive-cycle — VehicleRuns drive cycle and readiness guide

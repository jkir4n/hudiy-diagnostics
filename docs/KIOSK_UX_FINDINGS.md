# Hudiy Diagnostics — Kiosk UX Findings (frontend design input)

Task t_7375eac8. Angle is LAYOUT/UX only — the feature surface is already fixed
by V1_SPEC.md (9 features) and FEATURE_SURVEY_FINDINGS.md (competitor matrix).
This note answers the 6 UX questions with cited sources, then proposes a
concrete screen flow for exactly those 9 v1 features. Plain language, no code.

Key fixture realities from V1_SPEC.md that shape every recommendation below:
Mode 02 freeze frame is NOT supported by this ECU (render the feature as
not-supported, report substitutes PIDs 0145/0149); Mode 0A permanent DTCs are
NOT supported (section renders not-supported); after a car power-cycle the OBD
path can go stale while BT still shows connected, and the UI must show an
"ECU reconnecting" state, never a hang. Backend states available to the
frontend: idle / scanning / stale-handle / reconnecting, plus per-mode scan
progress and txt+csv report endpoints.

Method note: the hosted web-search backend returned empty results for the whole
run (same as the prior survey card), so this research went through direct page
extraction, the Federal Register API, GitHub page extraction, and visual
inspection of vendor tutorial screenshots. Every factual claim below carries an
inline source id. Un-cited paragraphs are analysis and recommendation.

## 1. Glanceable-information design: what the guidelines imply

NHTSA's Phase 1 visual-manual distraction guidelines (Federal Register notice
2013-09883, published April 2013) proposed that driving-suitable tasks be
completable with mean glance duration of 2 seconds or less, 85 percent of
glances 2 seconds or less, and cumulative eyes-off-road time of 12 seconds or
less.[1] The alternate occlusion test used 1.5-second glance bursts with a
9-second cumulative cap, later amended to 12 seconds to match the 12-second
total eyes-off-road (TEORT) criterion.[1] The final guidelines added a
long-glance rule: for at least 21 of 24 test participants, no more than 15
percent of glances away from the road may exceed 2.0 seconds.[1] Tasks that
fail are to be made inaccessible while driving, and inherently distracting
activities (non-driving video, auto-scrolling text, manual text entry,
reading books/web/social content) are per-se lockouts.[1] Supporting research
cited in the notice puts in-driving reading speed at roughly 15 characters per
second.[1]

Google's Design for Driving visual principles turn the same idea into concrete
numbers: primary text 32dp, secondary text 24dp, text items capped at 120
characters, contrast at least 4.5:1 for text, icons and anything carrying
information, and negative polarity (light on dark) mandatory at night.[2]
Touch targets must be at least 76x76dp with at least 23dp between them and no
overlap, and the UI must visibly distinguish allowed from disallowed features
while in motion (e.g. dimming or hiding what cannot be used while driving).[2]
The interaction principles add: content readable within 2 seconds, input
acknowledged within 0.25 seconds, any load over 2 seconds gets a spinner or
equivalent, malfunctions and safety status shown in real time, and sequences
interruptible and resumable at the driver's pace.[3]

Our session starts from a settings-menu launch with the user parked or idling,
which matters: Google explicitly allows richer experiences (video, browsing,
gaming-style content) for parked and passenger scenarios rather than the
restricted driving templates.[4] Apple takes the same two-tier approach with
CarPlay: template-constrained, "smarter, safer" interaction while driving,
glanceable widgets and Live Activities that deliver status without drawing
focus, and video only when parked.[5]

The accessibility floor under all of this is WCAG 2.2: color must never be the
only means of conveying information (Level A), interactive targets must be at
least 24x24 CSS pixels (the AA minimum — our kiosk target is far larger, see
below), and non-text indicators such as status icons need 3:1 contrast against
adjacent colors.[6]

What this implies for our diagnostics app, concretely: body copy at secondary
size or larger with 120 characters as the per-block ceiling; every status
readable in one 2-second glance (one verdict line per screen, details one tap
deeper); all primary actions at car-grade size (76dp-class, never below the
24px WCAG floor); dark theme as the default night-safe polarity with 4.5:1
text contrast; and a strict parked-vs-driving split — full detail while
parked, but any screen that could be open while idling in traffic must keep
the verdict line glance-sized and never demand reading a paragraph.

## 2. Scan-flow UX: progress, partials, errors

No surveyed app advertises per-mode progress bars; the established pattern is
static results plus an explicit refresh. OBD Auto Doctor's desktop Trouble
Codes view is the clearest example: left nav (Summary / Trouble Codes /
Diagnostics / Monitoring / Extras), a header banner with an ECU selector
dropdown, tabs for Confirmed / Pending / Permanent / Freeze Frame / DTC
Database, a four-column code table (Code, System, Manufacturer, Description),
and bottom buttons Clear the DTCs / Export / Refresh — the tutorial's Windows
screenshot shows a finished list with no scanning indicator at all.[9] Its
readiness screen follows the same static pattern: a monitor list with two
status columns (since-DTCs-cleared and this-driving-cycle) and Refresh as the
only re-scan affordance.[10] Car Scanner's listing describes the same shape in
words: show and reset DTCs, freeze frame as "sensors state when DTC is saved",
Mode 06 self-test results, emission readiness, and all sensors on one
screen.[15] Torque Pro frames diagnostics as "show and reset a DTC like a
scantool" inside a widget dashboard, with CSV/KML logging for later
analysis.[16] ReDrive states its philosophy outright — UI/UX first, no visual
clutter, only the data needed right now — with DTC scanning plus detailed
decoding and automatic connection recovery as the headline behaviors.[19]
OBD Auto Doctor notes a full check takes under 5 minutes, which sets user
expectations for scan duration.[13]

Recommendation for our scanner, mapped to the backend's per-mode progress:
show a per-mode checklist (Discovery, Stored, Pending, Permanent, Readiness,
Mode 06, Identity) rather than one indeterminate bar, because the backend
already exposes per-mode state and each step maps to one OBD query the user
can understand. Stream partial results into their cards as each mode completes
with a per-section timestamp, so a slow Mode 06 never blocks reading the DTCs.
Follow the platform rule: anything over 2 seconds shows a spinner or
equivalent state change.[3] Error and retry states get three fixed wordings:
adapter-level failure ("Adapter not found — check the ELM327 connection",
with Retry), ECU silence ("ECU did not answer — ignition may be off", with
Retry and Back), and the stale-handle case ("ECU reconnecting…", auto-retry,
Back always available — never a dead end; see section 6). Cancel must be
present on every scan step and must land back on idle with whatever partials
were already collected.

## 3. Results presentation: layout, severity colors, not-supported states

The two proven layouts are tabs and card walls, and the best apps use each
where it fits. OBD Auto Doctor uses tabs for the four DTC flavors plus freeze
frame and the DTC database, and a card-wall-style monitor list for readiness
with Complete (green check), Incomplete (red/orange exclamation) and Disabled
(gray) states in two groups — status since DTCs cleared and status this drive
cycle — including an EPA-allowance note on how many incomplete monitors an
inspection tolerates.[10] Our V1_SPEC already mandates the card wall for
readiness with green/red/gray chips plus one verdict line, which matches this
pattern exactly. For DTCs, keep OBDAD's tab split (Confirmed / Pending /
Permanent) since our scan returns exactly those three modes, and keep its
four-column row anatomy (code, system, manufacturer, plain description).[9]

Severity needs a plain-language verdict, not just codes. FIXD's model is
minor vs major framed as "safe to keep driving", backed by 7000+ codes in
plain English.[18] BlueDriver's model is verified-fix repair reports in plain
language over 9000+ codes.[17] Our v1 has no cloud repair data by design, so
the honest version is a three-level local verdict per code (e.g. stop soon /
schedule service / monitor) computed from the bundled text plus MIL state,
always shown as icon + words together.

Severity colors must be colorblind-safe, because the classic red/green pair
fails roughly 1 in 20 users, most of them on red-green confusion lines.[7]
Do not use red and green as the only contrasting pair; magenta-plus-green
survives far better, and the robust answer is a tested palette.[7] The
Okabe-Ito barrier-free palette gives us exact hexes: black, orange #E69F00,
sky blue #56B4E9, bluish green #009E73, yellow #F0E442, blue #0072B2,
vermillion #D55E00, reddish purple #CC79A7.[7] Practical mapping for our three
readiness/severity states: vermillion + warning triangle for bad, sky blue or
bluish green + check for good, gray + minus/pause glyph for disabled or
unknown — never color alone, always an icon and a word, which satisfies both
the palette guidance and the WCAG color-use rule.[6][7] Vary shape as well as
hue for any multi-category display so plots and chips survive grayscale too.[8]

"Not supported by this ECU" must read as a vehicle fact, never as an app bug.
Three citable precedents: Car Scanner tells users outright that it cannot show
anything the car does not provide, and warns that cheap clone adapters have
bugs.[15] OBD Auto Doctor marks unsupported monitors NA/Disabled in gray and,
for unnamed manufacturer Mode 06 monitors, shows raw OBDMID/TID values with a
look-it-up pointer instead of guessing names.[10][11] DTC definitions
themselves split cleanly into generic (first digit 0) and manufacturer
specific (first digit 1) codes, which is why a make-contextual lookup with a
"manufacturer-specific, meaning varies by make" fallback is the honest
pattern.[12] Our rendering rule per V1_SPEC: every unsupported item gets a
gray "Not supported by this ECU" row with one line of why (e.g. "Mode 0A not
answered by this ECU"), raw codes shown verbatim wherever a name is unknown,
and no silent hiding except the freeze-frame card, which the spec hides with
its not-supported notice while the report substitutes the supported 0145/0149
time-since-clear PIDs.

## 4. Clear-DTC safety flow

The best-in-class automotive pattern is OBD Auto Doctor's reset tutorial and
our flow should copy its structure outright.[9] Fix-first guidance comes
before any button: codes appear for a reason, only reset after fixing, and
unfixed codes may return immediately (random-failure clears are the stated
exception, with "make sure nothing is wrong first" every time).[9] The
acknowledge step lists explicit consequences: reset clears codes AND freeze
frame AND test-result status, the car may run poorly during re-calibration,
and readiness monitors reset so the car will fail an emissions inspection
until a drive cycle completes.[9] Both desktop ("Clear the DTCs") and mobile
("Reset trouble codes and MIL") require reading and acknowledging that info
screen before the command is sent.[9] The tutorial also warns never to use the
battery-disconnect shortcut (it can reset theft and infotainment systems) and
says OBD-tool reset is how professional mechanics do it.[9] OBDeleven adds one
refinement worth copying: distinguish critical from non-critical codes, with
single-tap clear only for the non-critical kind (per FEATURE_SURVEY_FINDINGS
section 1). Permanent Mode 0A codes get an explicit honesty note that no tool
can clear them — only the ECU clears them after its own drive cycles (per
FEATURE_SURVEY_FINDINGS section 5).

Recommended two-screen flow for our Mode 04: screen one shows the consequence
list (freeze frame lost, readiness reset, smog fail until drive cycle,
possible rough running) plus a fix-first checkbox the user must tick; screen
two confirms the result and lands in a "monitors incomplete — drive cycle
needed" follow-up state rather than a bare success toast. Keep Back available
on screen one and require the checkbox before the destructive button arms.

## 5. Report/export UX

The established report shape is "everything from this scan, in send-to-a-
mechanic order". OBD Auto Doctor's desktop client exports codes plus freeze
frame to a text file, and its mobile app shares the same bundle through the
system share sheet.[9] OBD Fusion ships a full diagnostic report the user can
save and send to a mechanic, groups readiness with O2 results, Mode 06 data
and VIN/calibration IDs under a Monitors tab, and uploads CSV logs for deeper
analysis.[14] Torque Pro sends CSV/KML logs to the web or email for
spreadsheet analysis.[16] OBD Auto Doctor's maintenance flow assumes the user
researches the specific code in model forums afterward, which is why the exact
code strings plus freeze-frame context must survive verbatim into the
export.[12][13]

Recommended report for our kiosk, in order: one-line verdict, vehicle block
(VIN, ECU name, CALID/CVN, scan date, app version), DTC sections (confirmed,
pending, permanent incl. the not-supported note where applicable) with code +
system + description + severity, readiness card states, Mode 06 pass/fail
summary with test-vs-limit numbers, and scan metadata (which modes answered,
which timed out). Offer text and CSV from one Export screen with car-grade
touch targets.[2] Filenames should carry date plus VIN suffix so repeat visits
do not overwrite each other. For the kiosk constraint (no phone in hand, no
cloud account), add a QR code encoding the report payload or a local retrieval
pointer on the Export screen — none of the surveyed offline tools do this, so
it is our own recommendation, not a copied pattern: it gives the
mechanic-shareable handoff without accounts, pairing, or typing long codes.

## 6. State resilience: reconnect without dead ends

Three precedents combine here. ReDrive ships automatic connection recovery
across Bluetooth, Wi-Fi and USB as a headline feature.[19] OBD Auto Doctor
treats connection as step zero of diagnostics — right dongle, right software,
platform-specific connect procedure — before any code is read.[9][13] Our own
transport reality is harsher: after a car power-cycle the ELM link can report
connected while every query is silently dropped, detectable only by OBD age
climbing, with app restart as the validated recovery — and V1_SPEC rule 5
requires the UI to show "ECU reconnecting" in that window, never a hang.

The UI pattern that satisfies all three: a persistent connection pill in the
top chrome (BT state dot + ECU state word: Connected / Scanning /
Reconnecting / Not found) so state is always glanceable, following the
real-time malfunction-display principle.[3] On stale-handle detection, freeze
the scan checklist in place, banner the reconnecting state with auto-retry,
keep Back and Cancel live, and never discard already-collected partials —
sequences must be interruptible and resumable, never restart-or-nothing.[3]
Keep the last good results cached and viewable behind the banner so the user
is never stranded on a spinner. Copy discipline: say what happened, say what
the app is doing, say what the user can do ("ECU stopped answering — retrying
(2/3). Check ignition is ON. [Retry now] [Back to results]"). Adapter-missing
at launch gets its own idle-state card, not an error dialog, with the single
Retry action at car-grade size.[2]

## Layout recommendation for our 9 v1 features

One menu-launched stack, single-column kiosk layout, dark by default. A
persistent top bar carries the connection pill (section 6) and a back chevron;
a persistent bottom zone carries exactly one primary action per screen at
76dp-class size.[2] Eight screens cover the nine features (discovery runs
silently inside the scan):

- S0 Home (idle). Big connection card (adapter + ECU state), one "Start health
  scan" primary button, secondary "View last report" when a cached scan
  exists, small "About this car" link to identity. Covers nothing directly;
  it is the calm entry point the menu-launch rule wants.
- S1 Scanning (features 9 + 1 in progress). Per-mode checklist with live
  states (waiting / querying with spinner / done with count / skipped as
  not-supported / failed with inline retry), partial counts streaming in,
  Cancel always live. Runtime discovery (feature 9) is the first checklist
  row; its bitmaps visibly gate the rows below, which teaches the honesty
  model from section 3.
- S2 Verdict hub (feature 1 completed). The one glanceable screen: MIL state,
  code counts by tab, readiness verdict, and the single safe-to-drive line in
  icon + words. Four cards lead deeper: Fault codes, Readiness, Advanced
  (Mode 06), Vehicle. Nothing here exceeds the 2-second readability budget.[3]
- S3 Fault codes (feature 2). Tabs Confirmed / Pending / Permanent; rows show
  severity chip (icon + word), code, short description; tapping a row opens
  S3b detail (full bundled text, generic vs manufacturer-specific note,
  severity reasoning, related Mode 06 hint where present). The Permanent tab
  on this ECU shows the gray not-supported row per the spec.
- S4 Readiness wall (feature 4). Green/red/gray chips per monitor in both
  groups (since-cleared + this-cycle), the one-line pass/fail verdict, and the
  drive-cycle guidance line for incomplete monitors.[10]
- S5 Advanced monitors (feature 5). Per-monitor pass/fail rows with
  test-vs-limit numbers, named diesel monitors (EGR, boost, PM filter, NOx)
  first, raw OBDMID/TID expander for unnamed ones with the look-it-up pointer
  instead of guessed names.[11]
- S6 Vehicle (feature 6). VIN, ECU name, CALID, CVN as copyable rows; decode
  shown best-effort with the weak-Indian-VW-coverage caveat inline, never as a
  failure state.
- S7 Clear codes (feature 7). Reached only from S3 via a clearly destructive
  button; the two-screen confirm from section 4; lands back on S1 (fresh scan)
  or S2 with the monitors-incomplete follow-up state.
- S8 Report (feature 8). Verdict-first preview in the section order of
  section 5, Export .txt / Export .csv buttons, QR handoff, filename showing
  date + VIN suffix.

Freeze frame (feature 3) has no card on this ECU — its S3b slot shows the
not-supported notice and the report carries the 0145/0149 substitute values,
exactly as V1_SPEC's feature table directs. Every screen keeps Back alive,
every destructive step keeps its consequences on the same screen as its
button, and no screen anywhere shows a bare spinner without a named state and
an exit.

## Sources

[1] https://www.federalregister.gov/documents/2013/04/26/2013-09883/visual-manual-nhtsa-driver-distraction-guidelines-for-in-vehicle-electronic-devices
[2] https://developers.google.com/cars/design/design-foundations/visual-principles
[3] https://developers.google.com/cars/design/design-foundations/interaction-principles
[4] https://developers.google.com/cars/design/create-apps/app-types/parked-passenger
[5] https://developer.apple.com/carplay
[6] https://www.w3.org/TR/WCAG22
[7] https://davidmathlogic.com/colorblind
[8] https://seaborn.pydata.org/tutorial/color_palettes.html
[9] https://www.obdautodoctor.com/tutorials/how-to-read-and-reset-the-check-engine-light
[10] https://www.obdautodoctor.com/tutorials/obd-readiness-monitors-explained
[11] https://www.obdautodoctor.com/tutorials/using-obd2-mode-06-for-advanced-car-diagnostics
[12] https://www.obdautodoctor.com/tutorials/diagnostic-trouble-codes-explained
[13] https://www.obdautodoctor.com/tutorials/successful-car-diagnostics
[14] https://www.obdsoftware.net/software/obdfusion
[15] https://play.google.com/store/apps/details?id=com.ovz.carscanner
[16] https://play.google.com/store/apps/details?id=org.prowl.torque
[17] https://www.bluedriver.com
[18] https://www.fixd.com
[19] https://github.com/iUnreallx/ReDrive

# UI Motion & Media References — vetted 24 Sep 2026

Links Kiran shared; checked against this app's surfaces (overlay webview on the car Pi),
license terms, and the Pi's CPU budget. Verdict per source; adoption candidates have
concrete mapping to existing screens.

## Adopt-worthy

### transitions.dev — copy-paste CSS micro-interactions ✅ (free tier only)
License (checked 24 Sep): any transition, once accessed, is usable in unlimited
personal/commercial projects, may be modified and shipped — only redistributing the
collection as a competing kit is forbidden. Compatible with this repo's MIT app
(snippets land as our own CSS, credit comment kept). Pro tier is paid; do not scrape.

Hard rule for this app: **transform/opacity animations only**. Several of their
flashier effects (mask-position shimmer, SVG-displacement) repaint/CPU-filter every
frame — unacceptable in a webview that shares the Pi with OpenAuto (lesson already
learned from the echo-cancel CPU waste). Their own docs admit it.

Mapped to real surfaces (what exists today: scan sweep, exit fade, m3 snackbar):
| candidate | surface | today |
|---|---|---|
| status-line shimmer → swap ("Reading the ECU") | S3 scan in-flight | static label; sweep bar only |
| skeleton loader + reveal | report render, deep-scan rows | blank-then-populate |
| error shake (cubic-bezier) | DTC clear failure, invalid lane | snackbar only |
| spinner→check morph | DTC clear success | snackbar text only |
| number roll (digit reel) | PID values (RPM, speed) | instant text set — test on Pi first, staggered digits can cost |

Motion-pass status (24 Sep 2026, branch `motion-pass`): adopted 4/5.
| candidate | status | landed as |
|---|---|---|
| status-line shimmer + swap | adopted | `.scan-label.is-scanning` (translateX gradient pseudo) + `.swap-in` opacity cross-fade via `swapText()`; S1 label, deep variant "Reading every PID" |
| skeleton loader + reveal | adopted | `.skel` ×4 (opacity pulse) in `#reportPre` while loading + one-shot `.reveal-in` on fresh verdict/deep/report content via `revealOnce()` |
| error shake | clear flow live | `.shake-once` translateX keyframe on the failure panel (`#s0Hero` / `#verdict`, plus the S11 `#clearCard`) via `shakeOnce()`; snackbar kept. Clear failure/timeout shakes the confirm card with the server message; 409 contention is toast-only |
| spinner→check morph | clear flow live | `.scan-mark` pie spinner (rotate) while busy → check pop (scale/rotate/opacity) via `markScanDone()` on S1 and its twin `markClearDone()` on the S11 result card — same classes, no new keyframes |
| number roll (digit reel) | skipped | live values render as whole text nodes; a reel needs per-digit DOM + timers — over budget for a Pi webview this pass |

Only 2–3 of these per future polish card; verify each with `body.reduced-motion`
honouring (existing rule) and a CPU eyeball via `vcgencmd` while animating.

### animos.app — static→motion showcase export ✅ (for README/launch media only)
720p export free forever, no account, **everything runs client-side — media never
leaves the device** (FAQ, checked 24 Sep). Not an app dependency: use it once to
turn diag overlay screenshots/short captures into a looping MP4 for the GitHub
README (GitHub renders mp4 natively) and any launch post. Pro ($9/mo) only if we
want 4K; not needed for a README.

## No action

- **godly.design** — infinite-scroll website-inspiration gallery + an affiliate-ish
  tools directory (Firefly, Cursor, CleanShot…). No downloadable/licensable assets,
  nothing this stack lacks. Time-sink for our purpose.
- **deck.gallery** — curated presentation/brand decks (freemium, $12/mo Pro).
  Pitch-deck inspiration only; nothing for the app or repo.
- **backgrounds.supply** — one-time-purchase pack of decorative/AI background
  images. Wrong direction for this app on purpose: the overlay uses flat dark M3
  surfaces for glanceability in sunlight; large bitmap backgrounds cost decode
  memory on the Pi. AI-asset licensing is also murky; avoid.

## Not applicable here
- transitions.dev "agent skill / CLI delivery" is a Pro feature — we don't need it;
  manual paste of 2–3 snippets is the whole adoption.

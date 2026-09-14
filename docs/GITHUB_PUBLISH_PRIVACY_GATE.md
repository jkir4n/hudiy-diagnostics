# Publication privacy gate — executed 2026-09-14

**Status: scrubbed & ready — NOT published.** (Standing owner directive: prepare,
do not push.)

This file was the pre-publish checklist. The 2026-09-14 pass executed it; the
file now serves as the record plus the re-audit recipe for any future push.

## What was scrubbed (2026-09-14)
- **Vehicle identity** — the reference vehicle's real VIN, CAL-ID (0904) and
  CVN (0906) were replaced with synthetic placeholders, recomputed consistently
  across raw fixtures, decoded fixtures, docs, tests, README and CHANGELOG.
- **Network identity** — the tailnet address became the `car@<PI-IP>`
  placeholder (AGENTS.md, tools/README.md); `/home/<user>/...` paths became
  `~/...` everywhere.
- **Personal context** — owner name/handles and dev-machine references were
  genericised across docs and comments.
- This file itself carries no real identifiers and is safe to ship.

## Re-audit before ANY public push
    tools/privacy_audit.sh        # every check must report 0

Exact local-only patterns (real VIN/CAL-ID/CVN fragments, the tailnet address,
handles) live in `tools/privacy-patterns.local` — **gitignored; never commit,
never copy into the repository**. The audit checks them automatically when the
file is present.

## History — read before pushing
Scrubbing the working tree does not rewrite git history: commits up to and
including tag `pre-scrub-2026-09-14` contain the original values (and agent/CI
author identities). A public push must use fresh history:
- **Option A (recommended):** publish one clean commit —
  `git checkout --orphan public && git add -A && git commit -m "Initial public release"` —
  push `public` to the new public remote; keep this repo private.
- **Option B:** rewrite history with
  `git filter-repo --replace-text <patterns-file>` (patterns file built from the
  local list), verify with the audit, then push.
Never `git push --tags` from this repo while the `pre-scrub-2026-09-14` tag
exists.

## Still open (owner decisions at publish time)
- License: none in-repo yet — pick one before/at publish.
- Repo name + visibility.
- Whether the archived `tools/` capture scripts ship as-is (reference-only; see
  `tools/README.md`).

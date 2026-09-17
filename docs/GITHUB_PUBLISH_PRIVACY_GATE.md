# Publication privacy gate — executed 2026-09-14

**Status: scrubbed; PUBLISHED 2026-09-17 at https://github.com/jkir4n/hudiy-diagnostics (public, MIT).**
The pre-publish "prepare, do not push" directive was lifted by the owner on 17 Sep 2026.

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

The audit covers three surfaces: working-tree files (generic checks + exact
local-only patterns), commit identities (maintainer-only), and a full-history
sweep for local-pattern residuals.

Exact local-only patterns (real VIN/CAL-ID/CVN fragments, the tailnet address,
private handles) live in `tools/privacy-patterns.local` — **gitignored; never
commit, never copy into the repository**. The audit checks them automatically
when the file is present. (The maintainer's public GitHub handle is no longer
listed there: it is the sanctioned public identity — see Decisions.)

## History — purged 2026-09-14
All commits were rewritten **in place** on 2026-09-14: every original identifier was
replaced in every historical blob *and* commit message (one fixture typo-fix commit
collapsed to empty in the process and was auto-pruned; 47 commits remain). Verified
zero residuals across all refs; the working tree is byte-identical to before the
rewrite. The original pre-scrub history survives only as an **offline archive kept by
the maintainer** (fingerprint sha256 `6dec1228...`) — never upload, share, or copy it
into this repo.

**Second pass (17 Sep 2026, publish-day):** author/committer metadata was the one
field class the first pass left behind. All identities were normalized to the
maintainer identity `jkir4n <jkir4n@users.noreply.github.com>`; content untouched
(trees byte-identical before/after). The audit now checks identities so this class
cannot recur silently.

Consequence: **a plain `git push` of `master` is now safe.** No fresh-history
trickery, no tag restrictions. The old `pre-scrub-2026-09-14` tag has been retired.

## Decisions (made at publication, 17 Sep 2026)
- License: **MIT** (added at publish).
- Repo: **jkir4n/hudiy-diagnostics**, public.
- Authors: every commit carries the maintainer identity `jkir4n <jkir4n@users.noreply.github.com>` (owner decision, 17 Sep 2026).
- `tools/` capture scripts ship as-is (reference-only; see `tools/README.md`).
- Plain `master` push, no history tricks (as planned post-scrub).

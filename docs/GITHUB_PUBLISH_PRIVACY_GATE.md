# GitHub Publication Gate — READ BEFORE PUSHING PUBLIC

> Standing directive from the owner (10 Sep 2026): "Leave it for now. But make a note for when pushing the repo to GitHub."
> This file is the note. **Do not `git push` to any public remote until every item below is scrubbed.**

## What must be scrubbed before a public push

### 1. Machine-specific network identity (2 real spots + this doc)
- `AGENTS.md` line ~18: `car@<PI-IP>` (real Tailscale IP)
- `tools/README.md` line ~26: same IP
- This gate doc itself quotes the IP for reference — it is scrubbed/excluded the
  same way (a public copy of this file must not contain it either).

Replace with a placeholder like `car@<PI-IP>` or a documentation-only note.

### 2. Real vehicle identity (fixtures + docs + tests)
The fixtures are captured from the owner's actual car. Before publishing, replace with
synthetic ground-truth:

- **VIN `WVWZZZ1KZAW555555`** appears in:
  - `README.md` (project facts section)
  - `CHANGELOG.md`
  - `backend/README.md` (`/vin` endpoint example)
  - `docs/DECODED_FIXTURES.md`
  - `backend/tests/test_diag_core.py` (hardcoded assert `WVWZZZ1KZAW555555`)
  - `backend/tests/test_diag_server.py`
  - `fixtures/*.json` (decoded + raw captures embed it inside `0902` frames)
- **CALID `00Z000000Z  0000`** + **CVN `0xA5A5A5A5`** in:
  - `docs/DECODED_FIXTURES.md`, `docs/V1_SPEC.md`
  - `fixtures/decoded_final_fixtures.json`, `fixtures/capture_final_fixtures.jsonl`

Scrub recipe: use a synthetic VIN (e.g. `WVWZZZ1KZAW555555`), recompute the
`0902` multi-frame hex in the raw fixtures, and update the CALID/CVN to dummy
values consistently across raw + decoded fixtures, docs, and test asserts.
Then re-run `python3 -m unittest discover -s backend/tests` (must stay 86/86 —
the frontend slice added 20 endpoint/static-serving tests to the original 41,
and the control lane added 25 more; with Hudiy's real `Api_pb2.py` reachable
via `DIAG_HUDIY_API_PB2` the two real-API tests run instead of skipping)
and re-run the replay-mode server smoke test (`/app/diag.html`, `/app/diag.js`,
`/app/diag.css` + `/health`).

### 3. Optional, lower sensitivity
- `~/...` Pi paths and `<projects-folder>\Hudiy Diagnostics` / "the dev workstation" mentions
  in docs — genericize if you want zero topology hints.

## What is already clean (verified 10 Sep 2026 audit)
- All backend code: loopback-only defaults, everything env-overridable, no
  IPs/MACs/usernames in any `.py`
- Deploy files (`backend/deploy/`): user units, `%h` homes, fully generic
- No secrets/tokens/.env files tracked
- `backend/third_party/dtc-database/dtc_codes.db`: public Wal33D data (MIT), safe

## Re-audit command (run this before pushing, always)

```bash
cd <repo>
grep -rInE '\b100\.(10[0-9]|6[0-9]|8[0-9])\.[0-9]+\.[0-9]+\b' . --exclude-dir=.git
grep -rIn 'WVWZZZ1KZAW555555\|00Z000000Z\|A5A5A5A5' . --exclude-dir=.git
grep -rInE '([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}' . --exclude-dir=.git
grep -rInE '<scrubbed-patterns>' . --exclude-dir=.git
```

All four greps must return **zero hits** before the push.

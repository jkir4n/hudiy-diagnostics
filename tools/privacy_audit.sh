#!/usr/bin/env bash
# Privacy re-audit for publication readiness (docs/GITHUB_PUBLISH_PRIVACY_GATE.md).
# Every check must report 0. File checks: generic patterns, plus exact local-only
# patterns read from tools/privacy-patterns.local when present (gitignored, never
# commit). History checks: every commit identity must be the maintainer identity,
# and a full-history sweep must show no local-pattern residuals.
set -u
cd "$(dirname "$0")/.."

fail=0
EXCLUDES=(--exclude-dir=.git --exclude-dir=__pycache__ --exclude=privacy_audit.sh --exclude=privacy-patterns.local)

check() { # name pattern
  local name="$1" pat="$2" hits
  hits=$(grep -rInE "$pat" . "${EXCLUDES[@]}" 2>/dev/null | wc -l)
  printf '%-46s %s\n' "$name" "$hits"
  [ "$hits" -eq 0 ] || fail=1
}

echo "== generic checks =="
check "tailnet-style 100.x addresses" '100\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}'
check "MAC-style addresses" '([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}'
check "user-specific home paths" '/home/[a-z0-9_-]+/'
check "private-key blocks" 'BEGIN [A-Z ]*PRIVATE KEY'
check "long bearer/JWT tokens" 'eyJ[A-Za-z0-9_-]{30,}'

if [ -f tools/privacy-patterns.local ]; then
  echo "== local pattern checks (tools/privacy-patterns.local) =="
  while IFS= read -r pat; do
    case "$pat" in ''|'#'*) continue ;; esac
    check "local: ${pat:0:28}" "$pat"
  done < tools/privacy-patterns.local
else
  echo "note: tools/privacy-patterns.local not present - only generic checks ran"
fi

echo "== history checks =="
id_bad=$(git log --all --pretty=format:'%an <%ae>%n%cn <%ce>' 2>/dev/null | sort -u | grep -cvE '^jkir4n <jkir4n@users[.]noreply[.]github[.]com>$' || true)
printf '%-46s %s\n' "non-maintainer commit identities" "$id_bad"
[ "$id_bad" -eq 0 ] || fail=1
if [ -f tools/privacy-patterns.local ]; then
  pats=$(grep -vE '^#|^$' tools/privacy-patterns.local | awk '{print $1}' | paste -sd'|' -)
  sweep=$(git log --all -p 2>/dev/null | grep -aE "$pats" | wc -l || true)
  printf '%-46s %s\n' "history sweep residual lines" "$sweep"
  [ "$sweep" -eq 0 ] || fail=1
fi

echo
if [ "$fail" -eq 0 ]; then echo "privacy audit: PASS (all checks zero)"; else echo "privacy audit: FAIL - see hits above"; fi
exit "$fail"

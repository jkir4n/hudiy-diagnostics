#!/usr/bin/env bash
# Privacy re-audit for publication readiness (docs/GITHUB_PUBLISH_PRIVACY_GATE.md).
# Every check must report 0. Generic patterns only; exact local-only patterns are
# read from tools/privacy-patterns.local when present (gitignored, never commit).
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

echo
if [ "$fail" -eq 0 ]; then echo "privacy audit: PASS (all checks zero)"; else echo "privacy audit: FAIL - see hits above"; fi
exit "$fail"

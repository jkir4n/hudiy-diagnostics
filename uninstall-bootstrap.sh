#!/usr/bin/env bash
# Hudiy Diagnostics one-line uninstall bootstrap (POSIX bash, no root).
#
#   git clone https://github.com/jkir4n/hudiy-diagnostics.git && cd hudiy-diagnostics && bash uninstall-bootstrap.sh
#   - or, without cloning -
#   bash <(curl -fsSL https://raw.githubusercontent.com/jkir4n/hudiy-diagnostics/master/uninstall-bootstrap.sh)
#
# Wraps backend/deploy/install.sh --uninstall, which does the real work:
# stops + removes both user units, reverses the Hudiy menu/overlay merge,
# removes the copied tree and the env file, then reboots so the menu entry
# disappears. Extra flags (e.g. --no-reboot) are passed through.
set -euo pipefail

REMOTE="${DIAG_REPO_REMOTE:-https://github.com/jkir4n/hudiy-diagnostics.git}"   # overrideable: git URL to clone from

SELF="${BASH_SOURCE[0]:-}"
if [ -n "$SELF" ]; then SELF_DIR="$(dirname "$SELF")"; else SELF_DIR="."; fi

if [ ! -f "$SELF_DIR/backend/deploy/install.sh" ]; then
  # Running piped/curl'd, or from an odd CWD: clone to a temp dir.
  [ -n "$REMOTE" ] || { echo "uninstall-bootstrap: no repo found; set DIAG_REPO_REMOTE=<git url>" >&2; exit 1; }
  TMP="$(mktemp -d)"
  echo "==> cloning into $TMP"
  git clone --depth 1 "$REMOTE" "$TMP/repo"
  cd "$TMP/repo"
  SELF_DIR="$TMP/repo"
fi

bash "$SELF_DIR/backend/deploy/install.sh" --uninstall "$@"

cat <<'EOF'

Manual one-time notes (the script leaves these alone on purpose):
  1) your user is still in the 'input' group (harmless without the shim).
  2) config backups (*.bak-*) were left next to the Hudiy config files.
The uninstaller reboots the Pi at the end, so the removed menu entry is
gone on the fresh boot (Hudiy reads its menu/overlay config at start).
Pass --no-reboot to skip that (then restart Hudiy by hand).
EOF

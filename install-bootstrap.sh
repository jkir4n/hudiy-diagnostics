#!/usr/bin/env bash
# Hudiy Diagnostics one-line bootstrap (POSIX bash, no root).
#
#   git clone <repo> && cd Hudiy-Diagnostics && bash install-bootstrap.sh
#   - or, once published -
#   bash <(curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/master/install-bootstrap.sh)
#
# Wraps backend/deploy/install.sh, which does the real work. Extra flags
# (e.g. --no-reboot) are passed through.
set -euo pipefail

REMOTE="${DIAG_REPO_REMOTE:-}"   # optional: git URL to clone from

SELF="${BASH_SOURCE[0]:-}"
if [ -n "$SELF" ]; then SELF_DIR="$(dirname "$SELF")"; else SELF_DIR="."; fi

if [ ! -f "$SELF_DIR/backend/deploy/install.sh" ]; then
  # Running piped/curl'd, or from an odd CWD: clone to a temp dir.
  [ -n "$REMOTE" ] || { echo "install-bootstrap: no repo found; set DIAG_REPO_REMOTE=<git url>" >&2; exit 1; }
  TMP="$(mktemp -d)"
  echo "==> cloning into $TMP"
  git clone --depth 1 "$REMOTE" "$TMP/repo"
  cd "$TMP/repo"
  SELF_DIR="$TMP/repo"
fi

bash "$SELF_DIR/backend/deploy/install.sh" "$@"

cat <<'EOF'

Manual one-time extras (script could not do them):
  1) wheel/knob shim needs the input group:
       sudo usermod -aG input "$USER"    # log out+back in, or reboot
The installer reboots the Pi at the end, so every change is picked up
on the fresh boot (Hudiy reads its menu/overlay config at start).
Pass --no-reboot to skip that.
Also: after the first install set DIAG_MODE in
  ~/.config/hudiy-diagnostics/env   # standalone | bridge | replay
EOF

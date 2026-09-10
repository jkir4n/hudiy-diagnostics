#!/usr/bin/env bash
# Hudiy Diagnostics - idempotent installer for ANY Hudiy instance.
#
#   ./install.sh              install (or update) + start the diagnostics lane
#   ./install.sh --dry-run    print what would happen, change nothing
#   ./install.sh --uninstall  stop + remove the unit (keeps copied files)
#
# No root, no machine-specific values: everything comes from $HOME and env
# overrides. Safe to re-run after every `git pull`.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALL_DIR="${DIAG_INSTALL_DIR:-$HOME/.local/share/hudiy-diagnostics}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_NAME="hudiy-diagnostics.service"
ENV_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/hudiy-diagnostics"
PORT="${DIAG_HTTP_PORT:-44414}"
HOST="${DIAG_HTTP_HOST:-127.0.0.1}"
SERVICE="hudiy-diagnostics"
DRY_RUN=0
UNINSTALL=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,9p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '==> %s\n' "$*"; }
run() {
  if [ "$DRY_RUN" = "1" ]; then printf '    [dry-run] %s\n' "$*"; else "$@"; fi
}

need_systemctl_user() {
  if [ -z "${XDG_RUNTIME_DIR:-}" ] || [ ! -d "${XDG_RUNTIME_DIR:-/nonexistent}" ]; then
    say "no user session bus (XDG_RUNTIME_DIR unset)."
    echo "    Fix: loginctl enable-linger $USER   # then re-run this script" >&2
    exit 1
  fi
  command -v systemctl >/dev/null || { echo "systemctl not found" >&2; exit 1; }
}

case "$PORT" in
  44411|44412|44413) echo "port $PORT is taken by race-dash (charts/bridge/toggle); use 44414+" >&2; exit 2 ;;
esac
if [ "$UNINSTALL" = "0" ] && ! command -v python3 >/dev/null; then
  echo "python3 not found on PATH" >&2; exit 1
fi

if [ "$UNINSTALL" = "1" ]; then
  need_systemctl_user
  say "stopping and removing $UNIT_NAME"
  run systemctl --user disable --now "$SERVICE" || true
  run rm -f "$UNIT_DIR/$UNIT_NAME"
  run systemctl --user daemon-reload
  say "removed. Copied files left in $INSTALL_DIR (delete by hand if wanted)."
  exit 0
fi

say "installing from $REPO_DIR -> $INSTALL_DIR"
run mkdir -p "$INSTALL_DIR" "$UNIT_DIR" "$ENV_DIR"
# Replace (not merge) the copied trees so a pulled version never leaves stale
# modules behind - this is what makes re-running the installer an update.
run rm -rf "$INSTALL_DIR/backend" "$INSTALL_DIR/fixtures"
run cp -a "$REPO_DIR/backend" "$INSTALL_DIR/backend"
run cp -a "$REPO_DIR/fixtures" "$INSTALL_DIR/fixtures"
run rm -rf "$INSTALL_DIR/backend/__pycache__"
if [ "$DRY_RUN" = "0" ]; then
  find "$INSTALL_DIR/backend" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
fi

say "installing user unit -> $UNIT_DIR/$UNIT_NAME"
run cp -a "$REPO_DIR/backend/deploy/$UNIT_NAME" "$UNIT_DIR/$UNIT_NAME"

if [ ! -f "$ENV_DIR/env" ]; then
  say "writing default env file -> $ENV_DIR/env"
  if [ "$DRY_RUN" = "1" ]; then
    printf '    [dry-run] create %s\n' "$ENV_DIR/env"
  else
    cat > "$ENV_DIR/env" <<'ENVEOF'
# Hudiy Diagnostics per-instance settings (read by hudiy-diagnostics.service).
# Managed by hand: the installer only creates this file if it is missing.
#
# DIAG_MODE: standalone (talk to the ELM directly) | bridge (ride the race-dash
# process when it owns the OBD slot) | replay (fixtures, no car - demos/tests)
DIAG_MODE=standalone
# When charts/race-dash owns the OBD slot, point the bridge at it instead of
# opening the adapter yourself (see docs/ARCHITECTURE_NOTES.md, single client).
#DIAG_MODE=bridge
#DIAG_CHARTS_BRIDGE_URL=http://127.0.0.1:44412/diag/obd
#DIAG_HTTP_PORT=44414
#DIAG_HTTP_HOST=127.0.0.1
ENVEOF
  fi
fi

need_systemctl_user
say "reloading user systemd and starting $SERVICE"
run systemctl --user daemon-reload
run systemctl --user enable --now "$SERVICE"

say "health check: http://$HOST:$PORT/health"
if [ "$DRY_RUN" = "1" ]; then
  echo "    [dry-run] curl -fsS http://$HOST:$PORT/health"
  exit 0
fi
for _ in $(seq 1 20); do
  if curl -fsS --max-time 2 "http://$HOST:$PORT/health" >/dev/null 2>&1; then
    say "OK - diagnostics lane is up:"
    curl -sS "http://$HOST:$PORT/health"
    echo
    echo "    unit:    systemctl --user status $SERVICE"
    echo "    logs:    systemctl --user status $SERVICE   (no journald on Hudiy)"
    exit 0
  fi
  sleep 0.5
done

echo "!! $SERVICE did not answer on http://$HOST:$PORT/health after 10s" >&2
systemctl --user status "$SERVICE" --no-pager || true
exit 1

#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/lms-arb}"
SERVICE_NAME="${SERVICE_NAME:-bot-api}"
HEALTH_PATH="${HEALTH_PATH:-/api/health}"

log() {
  printf '[deploy] %s\n' "$1"
}

fail() {
  printf '[deploy] ERROR: %s\n' "$1" >&2
  exit 1
}

[ -d "$APP_DIR" ] || fail "App directory not found: $APP_DIR"
cd "$APP_DIR"

[ -d .git ] || fail "This script expects a git checkout in $APP_DIR"
[ -f requirements.txt ] || fail "requirements.txt not found in $APP_DIR"
[ -d .venv ] || fail "Python virtual environment missing: $APP_DIR/.venv"

if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a
  . ./.env
  set +a
fi

BOT_PORT="${BOT_PORT:-5003}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:${BOT_PORT}${HEALTH_PATH}}"

log "Updating git repository..."
git fetch --all --prune
git pull --ff-only

log "Installing/updating Python dependencies..."
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

log "Restarting service: $SERVICE_NAME"
systemctl daemon-reload
systemctl restart "$SERVICE_NAME"

log "Waiting for service health..."
for i in $(seq 1 25); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    log "Deployment successful. Health check passed: $HEALTH_URL"
    systemctl --no-pager --full status "$SERVICE_NAME" | sed -n '1,12p'
    exit 0
  fi
  sleep 2
done

log "Health check failed after restart: $HEALTH_URL"
log "Recent service logs:"
journalctl -u "$SERVICE_NAME" -n 80 --no-pager || true
exit 1

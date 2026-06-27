#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/lms-arb}"
WORKERS="${GUNICORN_WORKERS:-3}"
THREADS="${GUNICORN_THREADS:-4}"
TIMEOUT="${GUNICORN_TIMEOUT:-120}"

cd "$APP_DIR"

if [ ! -d ".venv" ]; then
  echo "Python virtual environment not found at $APP_DIR/.venv"
  echo "Create it first: python3 -m venv .venv"
  exit 1
fi

source .venv/bin/activate
export PYTHONUNBUFFERED=1

# Socket activation: systemd provides fd 0 from bot-api-gunicorn.socket
exec gunicorn \
  --workers "$WORKERS" \
  --worker-class gthread \
  --threads "$THREADS" \
  --timeout "$TIMEOUT" \
  --access-logfile - \
  --error-logfile - \
  --bind fd://0 \
  bot_api:app

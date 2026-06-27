#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/lms-arb}"
cd "$APP_DIR"

if [ ! -d ".venv" ]; then
  echo "Python virtual environment not found at $APP_DIR/.venv"
  echo "Create it first: python3 -m venv .venv"
  exit 1
fi

source .venv/bin/activate
export PYTHONUNBUFFERED=1

exec python bot_api.py

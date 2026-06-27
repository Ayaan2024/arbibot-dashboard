#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/lms-arb}"
APP_USER="${APP_USER:-lmsarb}"
APP_GROUP="${APP_GROUP:-lmsarb}"
WEB_GROUP="${WEB_GROUP:-www-data}"

log() {
  printf '[setup-user] %s\n' "$1"
}

if ! getent group "$APP_GROUP" >/dev/null; then
  log "Creating group: $APP_GROUP"
  groupadd --system "$APP_GROUP"
fi

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  log "Creating user: $APP_USER"
  useradd --system --gid "$APP_GROUP" --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

log "Ensuring app directory exists: $APP_DIR"
mkdir -p "$APP_DIR"

log "Setting ownership on app directory"
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"

log "Adding service user to web group ($WEB_GROUP) for socket/nginx interoperability"
usermod -a -G "$WEB_GROUP" "$APP_USER" || true

log "Done. Service user: $APP_USER, group: $APP_GROUP"

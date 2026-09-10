#!/bin/bash
# Staging watchdog / (re)start script for cPanel shared hosting.
# Mirrors start_server.sh but scoped to the staging copy only, so a staging
# restart can never kill the production gunicorn next to it.
# Safe to run from cron every minute alongside the production entry.
# Usage: /home/demos/proposal-generator-staging/start_server-staging.sh

set -e

export PATH="$HOME/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$SCRIPT_DIR/.env"
  set +a
elif [ -f "${STAGING_APP_DIR:-/home/landloom/proposal-generator-staging}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "${STAGING_APP_DIR:-/home/landloom/proposal-generator-staging}/.env"
  set +a
fi

APP_DIR="${STAGING_APP_DIR:-/home/demos/proposal-generator-staging}"
REPO_DIR="${STAGING_REPO_DIR:-/home/demos/workflow.git}"
WEB_ROOT="${STAGING_WEB_ROOT:-/home/demos/staging_html}"
GUNICORN="$APP_DIR/venv/bin/gunicorn"
DEPLOYMENT_MARKER="$APP_DIR/.deployed_commit"
WATCHDOG_LOG="$APP_DIR/watchdog.log"
HEALTH_PATH="/health"

# Staging prefers its own port range so it never steals production port 8000.
PORT="${STAGING_PORT:-${APP_PORT:-8001}}"
FALLBACK_PORTS="8001 8002 8003 8004 8005 8080 8081 9000 9001 9002 7860 7861"

# The staging .htaccess is the source of truth for the staging port.
HTACCESS_PORT=$(sed -n 's#^RewriteRule .*http://127\.0\.0\.1:\([0-9][0-9]*\)/.*#\1#p' "$WEB_ROOT/.htaccess" 2>/dev/null | head -n 1)
if [ -n "$HTACCESS_PORT" ]; then
  PORT="$HTACCESS_PORT"
fi

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$WATCHDOG_LOG"
}

write_deployment_marker() {
  local deployed_commit
  deployed_commit=$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true)
  if [ -z "$deployed_commit" ]; then
    return 0
  fi
  printf '{"commit":"%s","deployed_at":"%s","source":"github-staging"}\n' \
    "$deployed_commit" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$DEPLOYMENT_MARKER"
}

# Scoped process match: only this staging venv's gunicorn, never production's.
STAGING_GUNICORN_MATCH="$APP_DIR/venv/bin/gunicorn"

# Already healthy on the live staging port? (bypassed if --force is passed)
if [ "$1" != "--force" ] && curl -fsS -m 5 "http://127.0.0.1:${PORT}${HEALTH_PATH}" 2>/dev/null | grep -q '"deployed_commit"'; then
  log "OK: staging gunicorn already healthy on port $PORT"
  exit 0
fi

log "WARN: staging health check failed on port $PORT; restarting..."

# Stop only staging gunicorn processes, then wait for the port to free up.
pkill -TERM -f "$STAGING_GUNICORN_MATCH" 2>/dev/null || true
for i in $(seq 1 15); do
  (echo >/dev/tcp/127.0.0.1/$PORT) 2>/dev/null || break
  sleep 1
done
pkill -9 -f "$STAGING_GUNICORN_MATCH" 2>/dev/null || true

# Pick a free port, preferring the staging port.
SELECTED_PORT=""
for p in $PORT $FALLBACK_PORTS; do
  if ! (timeout 1 bash -c "echo >/dev/tcp/127.0.0.1/$p") 2>/dev/null; then
    SELECTED_PORT=$p
    break
  fi
done

if [ -z "$SELECTED_PORT" ]; then
  log "ERROR: no free port found for staging"
  exit 1
fi

log "Starting staging gunicorn on 127.0.0.1:$SELECTED_PORT"

mkdir -p "$WEB_ROOT"
cd "$APP_DIR"
setsid "$GUNICORN" -b "127.0.0.1:$SELECTED_PORT" app:app \
  --workers 2 \
  --threads 4 \
  --timeout 300 \
  --graceful-timeout 30 \
  --max-requests 200 \
  --max-requests-jitter 50 \
  --capture-output \
  --access-logfile "$APP_DIR/server.log" \
  --error-logfile "$APP_DIR/server.log" \
  </dev/null >>"$APP_DIR/boot.log" 2>&1 &
disown

sleep 3

# Expose staging via Apache immediately using the selected gunicorn port.
sed "s/127\\.0\\.0\\.1:[0-9]*/127.0.0.1:$SELECTED_PORT/g" "$APP_DIR/.htaccess_prod" > "$WEB_ROOT/.htaccess"
log "Staging .htaccess routed to 127.0.0.1:$SELECTED_PORT"

# Final health check with retry loop
HEALTH_OK=0
for i in $(seq 1 15); do
  if curl -fsS -m 5 "http://127.0.0.1:${SELECTED_PORT}${HEALTH_PATH}" >/dev/null 2>&1; then
    HEALTH_OK=1
    break
  fi
  sleep 1
done

if [ "$HEALTH_OK" -eq 1 ]; then
  write_deployment_marker
  log "OK: staging gunicorn running on port $SELECTED_PORT"
else
  log "ERROR: staging gunicorn failed health check on port $SELECTED_PORT"
  tail -n 30 "$APP_DIR/server.log" | tee -a "$WATCHDOG_LOG"
  exit 1
fi

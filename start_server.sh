#!/bin/bash
# Lightweight watchdog / (re)start script for cPanel shared hosting.
# Safe to run from cron every minute.
# Usage: /home/sagdemo/proposal-generator/start_server.sh

set -e

export PATH="$HOME/bin:$PATH"

APP_DIR="/home/sagdemo/proposal-generator"
WEB_ROOT="/home/sagdemo/public_html"
GUNICORN="$APP_DIR/venv/bin/gunicorn"
WATCHDOG_LOG="$APP_DIR/watchdog.log"
HEALTH_PATH="/health"

# Load optional APP_PORT from .env
if [ -f "$APP_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$APP_DIR/.env"
  set +a
fi

PORT="${APP_PORT:-8000}"
FALLBACK_PORTS="8001 8002 8003 8004 8005 8080 8081 9000 9001 9002 7860 7861"

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$WATCHDOG_LOG"
}

# Already healthy on the configured port? (bypassed if --force is passed)
if [ "$1" != "--force" ] && curl -fsS -m 5 "http://127.0.0.1:${PORT}${HEALTH_PATH}" >/dev/null 2>&1; then
  log "OK: gunicorn already healthy on port $PORT"
  exit 0
fi

log "WARN: health check failed on port $PORT; restarting..."

# Stop any old gunicorn, preferring the configured port
pkill -TERM -f "gunicorn.*:$PORT" 2>/dev/null || true
for i in $(seq 1 15); do
  (echo >/dev/tcp/127.0.0.1/$PORT) 2>/dev/null || break
  sleep 1
done
pkill -9 -f "gunicorn.*:$PORT" 2>/dev/null || true
pkill -9 -f gunicorn 2>/dev/null || true

# Pick a free port, preferring APP_PORT
SELECTED_PORT=""
for p in $PORT $FALLBACK_PORTS; do
  if ! (timeout 1 bash -c "echo >/dev/tcp/127.0.0.1/$p") 2>/dev/null; then
    SELECTED_PORT=$p
    break
  fi
done

if [ -z "$SELECTED_PORT" ]; then
  log "ERROR: no free port found"
  exit 1
fi

log "Starting gunicorn on 127.0.0.1:$SELECTED_PORT"

cd "$APP_DIR"
setsid "$GUNICORN" -b "127.0.0.1:$SELECTED_PORT" app:app \
  --workers 3 \
  --threads 2 \
  --timeout 300 \
  --graceful-timeout 30 \
  --max-requests 200 \
  --max-requests-jitter 50 \
  --access-logfile "$APP_DIR/server.log" \
  --error-logfile "$APP_DIR/server.log" \
  </dev/null >>"$APP_DIR/boot.log" 2>&1 &
disown

sleep 3

# Expose via Apache immediately using the selected Gunicorn port.
# This is unconditional so stale/default port numbers (e.g. 3000) cannot linger.
sed "s/127\\.0\\.0\\.1:[0-9]*/127.0.0.1:$SELECTED_PORT/g" "$APP_DIR/.htaccess_prod" > "$WEB_ROOT/.htaccess"
log ".htaccess routed to 127.0.0.1:$SELECTED_PORT"

# Final health check
if curl -fsS -m 10 "http://127.0.0.1:${SELECTED_PORT}${HEALTH_PATH}" >/dev/null 2>&1; then
  log "OK: gunicorn running on port $SELECTED_PORT"
else
  log "ERROR: gunicorn failed health check on port $SELECTED_PORT"
  tail -n 30 "$APP_DIR/server.log" | tee -a "$WATCHDOG_LOG"
  exit 1
fi

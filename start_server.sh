#!/bin/bash
# Lightweight watchdog / (re)start script for cPanel shared hosting.
# Safe to run from cron every minute.
# Usage: /home/landloom/proposal-generator/start_server.sh

set -e

export PATH="$HOME/bin:$PATH"

APP_DIR="/home/landloom/proposal-generator"
REPO_DIR="/home/landloom/workflow.git"
WEB_ROOT="/home/landloom/public_html"
# Production lives on the landloom.ai account (root DocumentRoot). If a path
# ever moves, override via PROD_APP_DIR / PROD_REPO_DIR / PROD_WEB_ROOT.
APP_DIR="${PROD_APP_DIR:-$APP_DIR}"
REPO_DIR="${PROD_REPO_DIR:-$REPO_DIR}"
WEB_ROOT="${PROD_WEB_ROOT:-$WEB_ROOT}"
GUNICORN="$APP_DIR/venv/bin/gunicorn"
DEPLOYMENT_MARKER="$APP_DIR/.deployed_commit"
WATCHDOG_LOG="$APP_DIR/watchdog.log"
HEALTH_PATH="/health"

# Load optional APP_PORT from .env literally: values keep $, #, !, backticks and
# spaces exactly as written. Sourcing the file with `.` would expand $VARS and
# $(cmd), which silently rewrites secrets (e.g. a password containing $7 loses
# it and every login after a restart fails with "Invalid email or password").
load_env_file() {
  local env_file="$1" line key value quoted
  [ -f "$env_file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in ''|'#'*) continue ;; esac
    case "$line" in export[[:space:]]*) line="${line#export}" ;; esac
    case "$line" in
      *=*) key="${line%%=*}"; value="${line#*=}" ;;
      *) continue ;;
    esac
    key="$(printf '%s' "$key" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    case "$key" in ''|*[!A-Za-z0-9_]* ) continue ;; esac
    quoted=0
    case "$value" in
      \'*\') value="${value#\'}"; value="${value%\'}"; quoted=1 ;;
      \"*\") value="${value#\"}"; value="${value%\"}"; quoted=1 ;;
    esac
    if [ "$quoted" -eq 0 ]; then
      case "$value" in *' #'*) value="${value%%' #'*}" ;; esac
      value="$(printf '%s' "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    fi
    printf -v "$key" '%s' "$value"
    export "$key"
  done < "$env_file"
}
if [ -f "$APP_DIR/.env" ]; then
  load_env_file "$APP_DIR/.env"
fi

PORT="${APP_PORT:-8000}"
FALLBACK_PORTS="8001 8002 8003 8004 8005 8080 8081 9000 9001 9002 7860 7861"

# On shared hosting the preferred ports are usually taken by other tenants, so the
# app ends up on a fallback port. The live .htaccess is the source of truth for the
# port Apache proxies to — health-check THAT port, otherwise the watchdog would
# kill a healthy app on every run and cause restart loops + downtime.
HTACCESS_PORT=$(sed -n 's#^RewriteRule .*http://127\.0\.0\.1:\([0-9][0-9]*\)/.*#\1#p' "$WEB_ROOT/.htaccess" 2>/dev/null | head -n 1)
if [ -n "$HTACCESS_PORT" ]; then
  PORT="$HTACCESS_PORT"
fi

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$WATCHDOG_LOG"
}

write_deployment_marker() {
  # A watchdog restart is not a deploy: the deploy script owns this marker.
  [ -f "$DEPLOYMENT_MARKER" ] && return 0
  local deployed_commit
  deployed_commit=$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true)
  if [ -z "$deployed_commit" ]; then
    return 0
  fi
  printf '{"commit":"%s","deployed_at":"%s","source":"github"}\n' \
    "$deployed_commit" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$DEPLOYMENT_MARKER"
}

# Already healthy on the live port? (bypassed if --force is passed)
# The "commit" marker proves the responder is OUR app, not a neighbor's app that
# happens to answer /health on the same port.
if [ "$1" != "--force" ] && curl -fsS -m 5 "http://127.0.0.1:${PORT}${HEALTH_PATH}" 2>/dev/null | grep -q '"deployed_commit"'; then
  log "OK: gunicorn already healthy on port $PORT"
  exit 0
fi

log "WARN: health check failed on port $PORT; restarting..."

# Scoped process match: only this app dir's venv gunicorn, never a neighbor's
# on shared hosting. The old processes keep serving until the replacement
# passes health — killing them first is what turned every slow minute into
# downtime plus a cold boot.
PROD_GUNICORN_MATCH="$APP_DIR/venv/bin/gunicorn"
OLD_PIDS="$(pgrep -f "$PROD_GUNICORN_MATCH" || true)"
if [ -r "$APP_DIR/.prod-gunicorn-$PORT.pid" ]; then
  read -r old_pid < "$APP_DIR/.prod-gunicorn-$PORT.pid" || old_pid=""
  if [[ "$old_pid" =~ ^[0-9]+$ ]] && [ "$old_pid" -gt 1 ] \
    && [ "$(readlink "/proc/$old_pid/cwd" 2>/dev/null)" = "$(cd "$APP_DIR" && pwd -P)" ]; then
    OLD_PIDS="$old_pid"
  fi
fi

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
  --pid "$APP_DIR/.prod-gunicorn-$SELECTED_PORT.pid" \
  --preload \
  --workers 3 \
  --threads 2 \
  --timeout 300 \
  --graceful-timeout 30 \
  --max-requests 200 \
  --max-requests-jitter 50 \
  --capture-output \
  --access-logfile "$APP_DIR/server.log" \
  --error-logfile "$APP_DIR/server.log" \
  </dev/null >>"$APP_DIR/boot.log" 2>&1 9>&- &
NEW_PID=$!
disown

sleep 3
log "Startup readiness checks beginning; pid=$NEW_PID port=$SELECTED_PORT boot_wait_seconds=3"

# The old proxy stays active until the new process passes health: traffic never
# moves to a cold worker, and a failed start leaves the old app untouched.
HEALTH_OK=0
for i in $(seq 1 15); do
  if ! kill -0 "$NEW_PID" 2>/dev/null; then
    log "ERROR: gunicorn exited before readiness probe attempt=$i pid=$NEW_PID port=$SELECTED_PORT"
    break
  fi
  probe_started_ms="$(date +%s%3N)"
  health_curl_exit=0
  health_status="$(curl --silent -m 5 -o /dev/null -w '%{http_code}' \
    "http://127.0.0.1:${SELECTED_PORT}${HEALTH_PATH}")" || {
      health_curl_exit=$?
      health_status="000"
    }
  probe_finished_ms="$(date +%s%3N)"
  probe_elapsed_ms=$((probe_finished_ms - probe_started_ms))
  log "readiness probe run_pid=$$ attempt=$i port=$SELECTED_PORT gunicorn_pid=$NEW_PID status=$health_status curl_exit=$health_curl_exit elapsed_ms=$probe_elapsed_ms"
  if [ "$health_status" = "200" ]; then
    HEALTH_OK=1
    break
  elif [ "$health_status" != "000" ]; then
    log "ERROR: health returned HTTP $health_status"
    break
  fi
  sleep 1
done

if [ "$HEALTH_OK" -eq 1 ]; then
  write_deployment_marker
  HTACCESS_TEMP="$(mktemp "$WEB_ROOT/.htaccess.XXXXXX")"
  sed "s/127\\.0\\.0\\.1:[0-9]*/127.0.0.1:$SELECTED_PORT/g" "$APP_DIR/.htaccess_prod" > "$HTACCESS_TEMP"
  chmod 644 "$HTACCESS_TEMP"
  mv "$HTACCESS_TEMP" "$WEB_ROOT/.htaccess"
  log ".htaccess routed to 127.0.0.1:$SELECTED_PORT"
  if [ -n "$OLD_PIDS" ]; then
    kill -TERM $OLD_PIDS 2>/dev/null || true
  fi
  log "OK: gunicorn running on port $SELECTED_PORT"
else
  log "ERROR: gunicorn failed health check on port $SELECTED_PORT"
  # Never leave a failed replacement bound: it would squat the port and trick
  # the next watchdog run into proxying traffic at a dead process.
  kill -TERM "$NEW_PID" 2>/dev/null || true
  tail -n 30 "$APP_DIR/server.log" | tee -a "$WATCHDOG_LOG"
  exit 1
fi

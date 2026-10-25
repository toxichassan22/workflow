#!/bin/bash
# Staging watchdog / (re)start script for cPanel shared hosting.
# Mirrors start_server.sh but scoped to the staging copy only, so a staging
# restart can never kill the production gunicorn next to it.
# Safe to run from cron every minute alongside the production entry.
# Usage: /home/landloom/proposal-generator-staging/start_server-staging.sh

set -e

export PATH="$HOME/bin:$PATH"

for lib_dir in \
  "$HOME/chromium-libs/usr/lib64" \
  "$HOME/chromium-libs/lib64" \
  "$HOME/chromium-libs" \
  "/home/landloom/chromium-libs/usr/lib64" \
  "/home/landloom/chromium-libs/lib64" \
  "/home/landloom/chromium-libs"; do
  if [ -d "$lib_dir" ]; then
    export LD_LIBRARY_PATH="$lib_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  fi
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Load a .env file literally: values keep $, #, !, backticks and spaces exactly
# as written. Sourcing the file with `.` would expand $VARS and $(cmd), which
# silently rewrites secrets (e.g. ADMIN_PASSWORD=K9#mP$7vL!2xQ@5wZ lost its $7
# and every login after a restart failed with "Invalid email or password").
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
if [ -f "$SCRIPT_DIR/.env" ]; then
  load_env_file "$SCRIPT_DIR/.env"
elif [ -f "${STAGING_APP_DIR:-/home/landloom/proposal-generator-staging}/.env" ]; then
  load_env_file "${STAGING_APP_DIR:-/home/landloom/proposal-generator-staging}/.env"
fi

APP_DIR="${STAGING_APP_DIR:-/home/landloom/proposal-generator-staging}"
REPO_DIR="${STAGING_REPO_DIR:-/home/landloom/workflow.git}"
WEB_ROOT="${STAGING_WEB_ROOT:-/home/landloom/lab.landloom.ai}"
GUNICORN="$APP_DIR/venv/bin/gunicorn"
DEPLOYMENT_MARKER="$APP_DIR/.deployed_commit"
WATCHDOG_LOG="$APP_DIR/watchdog.log"
HEALTH_PATH="/health"
NEW_PID=""
HTACCESS_TEMP=""
trap 'rc=$?; if [ "$rc" -ne 0 ] && [ -n "$NEW_PID" ]; then kill -TERM "$NEW_PID" 2>/dev/null || true; fi; if [ -n "$HTACCESS_TEMP" ]; then rm -f "$HTACCESS_TEMP"; fi' EXIT
if command -v flock >/dev/null 2>&1; then
  exec 8>"$APP_DIR/.staging-start.lock"
  if ! flock -n 8; then
    echo "ERROR: another staging server startup is already running"
    exit 1
  fi
fi

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

log_readiness_probe() {
  echo "$(date '+%Y-%m-%d %H:%M:%S.%3N') INFO: staging readiness probe $1" | tee -a "$WATCHDOG_LOG"
}

write_deployment_marker() {
  # A watchdog restart is not a deploy: the deploy script owns this marker.
  # Rewriting it from the clone's HEAD on every restart misreported which
  # code is actually live whenever HEAD and the synced tree diverged.
  [ -f "$DEPLOYMENT_MARKER" ] && return 0
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

# A browser whose owning worker died keeps its profile and its processes
# forever (measured: 278 chrome processes, the oldest 1.5 days old, held ~1 GB
# and starved the next scan). Only parentless Chromium is touched — a running
# job's browser always has its worker as parent.
for chrome_pattern in 'chrome-linux64/chrome' 'chrome_crashpad'; do
  pkill -P 1 -f "$chrome_pattern" 2>/dev/null || true
done

# Already healthy on the live staging port? (bypassed if --force is passed)
if [ "$1" != "--force" ] && curl -fsS -m 5 "http://127.0.0.1:${PORT}${HEALTH_PATH}" 2>/dev/null | grep -q '"deployed_commit"'; then
  log "OK: staging gunicorn already healthy on port $PORT"
  exit 0
fi

log "WARN: staging health check failed on port $PORT; restarting..."

# Keep the current staging processes alive until the replacement is healthy.
OLD_PIDS="$(pgrep -f "$STAGING_GUNICORN_MATCH" || true)"
if [ -r "$APP_DIR/.staging-gunicorn-$PORT.pid" ]; then
  read -r old_pid < "$APP_DIR/.staging-gunicorn-$PORT.pid" || old_pid=""
  if [[ "$old_pid" =~ ^[0-9]+$ ]] && [ "$old_pid" -gt 1 ] \
    && [ "$(readlink "/proc/$old_pid/cwd" 2>/dev/null)" = "$(cd "$APP_DIR" && pwd -P)" ]; then
    OLD_PIDS="$old_pid"
  fi
fi

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
# fd 8 and fd 9 protect startup and deployment; daemons must inherit neither.
# Closing them for gunicorn keeps both locks scoped to the current script run.
# Otherwise a healthy daemon could prevent every later deployment.
setsid "$GUNICORN" -b "127.0.0.1:$SELECTED_PORT" app:app \
  --pid "$APP_DIR/.staging-gunicorn-$SELECTED_PORT.pid" \
  --preload \
  --workers 2 \
  --threads 4 \
  --timeout 300 \
  --graceful-timeout 30 \
  --max-requests 200 \
  --max-requests-jitter 50 \
  --capture-output \
  --access-logfile "$APP_DIR/server.log" \
  --error-logfile "$APP_DIR/server.log" \
  </dev/null >>"$APP_DIR/boot.log" 2>&1 8>&- 9>&- &
NEW_PID=$!
disown

sleep 3
log "Staging startup readiness checks beginning; pid=$NEW_PID port=$SELECTED_PORT boot_wait_seconds=3"

# The old proxy stays active until the new staging process passes health.

# Wait for application readiness before the single traffic switch.
HEALTH_OK=0
for i in $(seq 1 15); do
  if ! kill -0 "$NEW_PID" 2>/dev/null; then
    log "ERROR: staging gunicorn exited before readiness probe attempt=$i pid=$NEW_PID port=$SELECTED_PORT"
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
  log_readiness_probe "run_pid=$$ attempt=$i port=$SELECTED_PORT gunicorn_pid=$NEW_PID status=$health_status curl_exit=$health_curl_exit elapsed_ms=$probe_elapsed_ms"
  if [ "$health_status" = "200" ]; then
    HEALTH_OK=1
    break
  elif [ "$health_status" != "000" ]; then
    log "ERROR: staging health returned HTTP $health_status"
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
  log "Staging .htaccess routed to 127.0.0.1:$SELECTED_PORT"
  if [ -n "$OLD_PIDS" ]; then
    kill -TERM $OLD_PIDS 2>/dev/null || true
  fi
  log "OK: staging gunicorn running on port $SELECTED_PORT"
else
  log "ERROR: staging gunicorn failed health check on port $SELECTED_PORT"
  tail -n 30 "$APP_DIR/server.log" | tee -a "$WATCHDOG_LOG"
  exit 1
fi

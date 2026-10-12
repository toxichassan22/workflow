#!/bin/bash
# Staging deployment script for cPanel shared hosting (lab copy next to production).
# Production deploy.sh stays manual-only: landloom.ai root is the production
# home but nothing is deployed there yet.
# This script never touches production paths: it syncs origin/lab into a
# separate APP_DIR and restarts a separate gunicorn + .htaccess pair.
#
# Server setup (one time, on the host):
#   STAGING_WEB_ROOT must point at the lab.landloom.ai subdomain DocumentRoot
#   created in cPanel (default below: /home/landloom/lab.landloom.ai).
#   Override it by exporting STAGING_WEB_ROOT on the server or in the staging
#   .env if cPanel created a different DocumentRoot.
# Optional overrides: STAGING_REPO_DIR, STAGING_APP_DIR, STAGING_BRANCH.

set -eo pipefail

export PATH="$HOME/bin:$PATH"
export GIT_LFS_SKIP_SMUDGE=1

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

REPO_DIR="${STAGING_REPO_DIR:-/home/landloom/workflow.git}"
APP_DIR="${STAGING_APP_DIR:-/home/landloom/proposal-generator-staging}"
WEB_ROOT="${STAGING_WEB_ROOT:-/home/landloom/lab.landloom.ai}"
BRANCH="${STAGING_BRANCH:-lab}"
PYTHON="$APP_DIR/venv/bin/python"
PIP="$APP_DIR/venv/bin/pip"
GUNICORN="$APP_DIR/venv/bin/gunicorn"
TARGET_COMMIT="${1:-}"
REQUEST_ID="${STAGING_DEPLOY_REQUEST_ID:-manual-$(date -u '+%Y%m%d%H%M%S')-$$}"

if [ -n "$TARGET_COMMIT" ] && [[ ! "$TARGET_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "ERROR: invalid target deployment commit"
  exit 1
fi
if [[ ! "$REQUEST_ID" =~ ^[A-Za-z0-9_-]{1,80}$ ]]; then
  echo "ERROR: invalid deployment request ID"
  exit 1
fi
mkdir -p "$APP_DIR/.deploy_runs"
STEP_LOG="$(mktemp "$APP_DIR/.deploy_runs/$REQUEST_ID.XXXXXX.log")"

# Record every run's outcome where /health can report it: a run that dies
# mid-way used to leave only a stale .deployed_commit, and the GitHub check
# timed out with no hint which step failed.
DEPLOY_STEP="start"
STATUS_FILE="$APP_DIR/.deploy_status"
write_deploy_status() {
  local helper="$APP_DIR/scripts/deploy_runtime.py"
  [ -f "$helper" ] || helper="$REPO_DIR/scripts/deploy_runtime.py"
  if [ -f "$helper" ]; then
    python3 "$helper" status --app-dir "$APP_DIR" --commit "${TARGET_COMMIT:-latest}" \
      --request-id "$REQUEST_ID" --status "$1" --step "$DEPLOY_STEP" \
      --exit-code "${2:-0}" --log-path "$STEP_LOG"
  else
    printf '{"commit":"%s","status":"%s","step":"%s","exit_code":%s,"finished_at":"%s"}\n' \
      "${TARGET_COMMIT:-latest}" "$1" "$DEPLOY_STEP" "${2:-0}" \
      "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$STATUS_FILE"
  fi
}
run_deploy_step() {
  DEPLOY_STEP="$1"
  shift
  write_deploy_status running
  "$@" 2>&1 | tee "$STEP_LOG"
}
trap 'rc=$?; if [ "$rc" -ne 0 ]; then write_deploy_status failed "$rc" || true; fi' EXIT

# Serialize deploys: two webhook spawns used to fight over one clone's git
# locks and kill each other mid-run — code synced, marker never written.
if command -v flock >/dev/null 2>&1; then
  DEPLOY_STEP="lock"
  exec 9>"${TMPDIR:-/tmp}/landloom-staging-deploy.lock"
  if ! flock -n 9; then
    echo "ERROR: another staging deployment is already running" | tee "$STEP_LOG"
    exit 1
  fi
else
  echo "ERROR: staging deployment requires flock" | tee "$STEP_LOG"
  exit 1
fi

DEPLOY_STEP="pull"
# From here this run holds the deploy lock: say so on /health, otherwise a
# slow-but-healthy deploy looked exactly like a dead one.
write_deploy_status running
echo "===== 1. Pull latest staging code (branch: $BRANCH) ====="
cd "$REPO_DIR"
if [ "$(git rev-parse --is-bare-repository 2>/dev/null)" = "true" ]; then
  echo "ERROR: $REPO_DIR is a bare clone — git reset --hard needs a worktree; re-clone normally."
  exit 1
fi
# GIT_TERMINAL_PROMPT=0: a missing/expired credential must fail fast here —
# an interactive prompt would hang forever while holding the deploy lock.
run_deploy_step pull env GIT_TERMINAL_PROMPT=0 git fetch origin "$BRANCH"
if [ -n "$TARGET_COMMIT" ]; then
  if ! git cat-file -e "${TARGET_COMMIT}^{commit}" 2>/dev/null; then
    echo "ERROR: target deployment commit is not available after fetch: $TARGET_COMMIT"
    exit 1
  fi
  run_deploy_step pull git reset --hard "$TARGET_COMMIT"
else
  run_deploy_step pull git reset --hard "origin/$BRANCH"
fi
GIT_TERMINAL_PROMPT=0 git lfs pull 2>/dev/null || true

DEPLOY_STEP="sync"
echo "===== 2. Sync to staging app directory ($APP_DIR) ====="
mkdir -p "$APP_DIR" "$WEB_ROOT"
run_deploy_step sync rsync -av \
  --exclude='.deployed_commit' \
  --exclude='.deploy_status' \
  --exclude='.deploy_runs' \
  --exclude='.deploy_backups' \
  --exclude='.deploy_inventory.json' \
  --exclude='app.db' \
  --exclude='data.db' \
  --exclude='.env' \
  --exclude='.git' \
  --exclude='venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='server.log' \
  --exclude='server_stderr.log' \
  --exclude='server_stdout.log' \
  --exclude='watchdog.log' \
  --exclude='boot.log' \
  --exclude='deploy.log' \
  --exclude='outputs' \
  --exclude='uploads' \
  "$REPO_DIR/" "$APP_DIR/"
run_deploy_step sync python3 "$APP_DIR/scripts/deploy_runtime.py" prepare \
  --repo-dir "$REPO_DIR" --app-dir "$APP_DIR"

echo "===== 3. Ensure scripts are executable ====="
chmod +x "$APP_DIR/start_server.sh" 2>/dev/null || true
chmod +x "$APP_DIR/start_server-staging.sh" 2>/dev/null || true
chmod +x "$APP_DIR/deploy-staging.sh" 2>/dev/null || true

echo "===== 4. Clean Python cache ====="
cd "$APP_DIR"
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -name '*.pyc' -delete 2>/dev/null || true

DEPLOY_STEP="deps"
echo "===== 5. Update dependencies ====="
if [ ! -d "$APP_DIR/venv" ]; then
  run_deploy_step deps python3 -m venv "$APP_DIR/venv"
fi
run_deploy_step deps "$PIP" install --upgrade pip setuptools wheel
run_deploy_step deps "$PIP" install -r "$APP_DIR/requirements.txt"
run_deploy_step deps "$PIP" install gunicorn

DEPLOY_STEP="migrate"
echo "===== 6. Run database migrations ====="
run_deploy_step migrate "$PYTHON" -c "import app; app.db.init_db()"

# The marker reports the commit this deploy was asked to ship — re-reading the
# clone's HEAD here could record whatever a concurrent operation left behind.
local_commit="${TARGET_COMMIT:-$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true)}"
DEPLOY_STEP="restart"
echo "===== 7. Start/restart staging application server ====="
# 9>&-: the lock fd is inheritable — anything the restart chain spawns (the
# daemon above all) must not carry it or the lock outlives this deploy.
run_deploy_step restart bash "$APP_DIR/start_server-staging.sh" --force 9>&-

if [ -n "$local_commit" ]; then
  printf '{"commit":"%s","deployed_at":"%s","source":"github-staging"}\n' \
    "$local_commit" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$APP_DIR/.deployed_commit"
fi
write_deploy_status deployed 0
trap - EXIT

# The deploy is done — marker written, server restarted, status recorded. The
# playwright install below is a best-effort extra that can take up to 2x15
# minutes; keeping the flock through it starved every queued webhook deploy
# into a lock-timeout failure. Release the lock before it.
exec 9>&-

DEPLOY_STEP="vision"
echo "===== 8. Headless browser for slide rendering (optional) ====="
(
  set +e
  install_log="$APP_DIR/playwright_install.log"
  : > "$install_log" 2>/dev/null || install_log=/dev/null
  install_timeout=""
  command -v timeout >/dev/null 2>&1 && install_timeout="timeout 900"
  for browser_target in chromium chromium-headless-shell; do
    echo "--- playwright install $browser_target ---" >> "$install_log" 2>/dev/null
    $install_timeout "$PYTHON" -m playwright install "$browser_target" >> "$install_log" 2>&1 \
      || echo "WARNING: playwright install $browser_target failed or timed out"
  done

  "$PYTHON" - "$APP_DIR/scripts" > "$APP_DIR/.vision_status.tmp" <<PY
import json
import sys
sys.path.insert(0, sys.argv[1])
detail = ''
try:
    with open("$install_log", encoding='utf-8', errors='replace') as fh:
        detail = fh.read()[-1200:]
except OSError as exc:
    detail = f'no install log: {exc}'
available, error = False, ''
try:
    import _bootstrap
    import generate_pdf_from_preview as gp
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, how = gp._launch_chromium(p)
        available = True
        error = f'chromium {browser.version} via {how}'
        browser.close()
except Exception as exc:
    err = ' '.join(f'{type(exc).__name__}: {exc}'.split())
    error = err if len(err) <= 600 else err[:150] + ' ... ' + err[-440:]
print(json.dumps({'available': available, 'error': error, 'installLog': detail}, ensure_ascii=False))
PY
  mv "$APP_DIR/.vision_status.tmp" "$APP_DIR/.vision_status" 2>/dev/null
  if grep -q '"available": true' "$APP_DIR/.vision_status" 2>/dev/null; then
    echo "Slide vision available: the AI editor sees a rendered snapshot of each slide."
  else
    echo "WARNING: no slide vision on this host; the AI editor will edit slide markup blind."
    cat "$APP_DIR/.vision_status" 2>/dev/null
  fi
) || true

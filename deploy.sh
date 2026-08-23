#!/bin/bash
# One-command deployment script for cPanel shared hosting.
# Run this from /home/demos/proposal-generator after pushing code to GitHub.

set -e

export PATH="$HOME/bin:$PATH"
export GIT_LFS_SKIP_SMUDGE=1

REPO_DIR="/home/demos/workflow.git"
APP_DIR="/home/demos/proposal-generator"
WEB_ROOT="/home/demos/public_html"
PYTHON="$APP_DIR/venv/bin/python"
PIP="$APP_DIR/venv/bin/pip"
GUNICORN="$APP_DIR/venv/bin/gunicorn"
TARGET_COMMIT="${1:-}"

if [ -n "$TARGET_COMMIT" ] && [[ ! "$TARGET_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "ERROR: invalid target deployment commit"
  exit 1
fi

echo "===== 1. Pull latest code ====="
cd "$REPO_DIR"
git fetch origin main
if [ -n "$TARGET_COMMIT" ]; then
  if ! git cat-file -e "${TARGET_COMMIT}^{commit}" 2>/dev/null; then
    echo "ERROR: target deployment commit is not available after fetch: $TARGET_COMMIT"
    exit 1
  fi
  git reset --hard "$TARGET_COMMIT"
else
  git reset --hard origin/main
fi
git lfs pull 2>/dev/null || true

echo "===== 2. Sync to app directory ====="
mkdir -p "$APP_DIR"
rsync -av \
  --exclude='.deployed_commit' \
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

echo "===== 3. Ensure scripts are executable ====="
chmod +x "$APP_DIR/start_server.sh"

echo "===== 4. Clean Python cache ====="
cd "$APP_DIR"
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -name '*.pyc' -delete 2>/dev/null || true

echo "===== 5. Update dependencies ====="
if [ ! -d "$APP_DIR/venv" ]; then
  python3 -m venv "$APP_DIR/venv"
fi
"$PIP" install --upgrade pip setuptools wheel || true
"$PIP" install -r "$APP_DIR/requirements.txt" || true
"$PIP" install gunicorn || true

echo "===== 6. Run database migrations ====="
"$PYTHON" -c "import app; app.db.init_db()"

# Pre-seed deployment marker from repo HEAD
local_commit=$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true)
if [ -n "$local_commit" ]; then
  printf '{"commit":"%s","deployed_at":"%s","source":"github"}\n' \
    "$local_commit" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$APP_DIR/.deployed_commit"
fi

echo "===== 7. Start/restart application server ====="
bash "$APP_DIR/start_server.sh" --force

# The browser comes last and can never fail the deploy. An earlier version of this ran before the
# migrations under `set -e`, and one unguarded write to /tmp aborted deploy.sh silently: the app was
# left on the previous commit and the only signal was the GitHub check failing six minutes later.
# `chromium.launch()` resolves to chrome-headless-shell, which is a separate download, so installing
# "chromium" alone left the host with no launchable browser and the AI editor working blind.
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

  # Recorded where the app can report it: the install log stays on the server, and a silent failure
  # here is exactly what hid the missing browser for so long.
  "$PYTHON" - > "$APP_DIR/.vision_status.tmp" <<PY
import json
detail = ''
try:
    with open("$install_log", encoding='utf-8', errors='replace') as fh:
        detail = fh.read()[-1200:]
except OSError as exc:
    detail = f'no install log: {exc}'
available, error = False, ''
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        available = True
        error = f'chromium {browser.version}'
        browser.close()
except Exception as exc:
    error = str(exc)[:600]
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

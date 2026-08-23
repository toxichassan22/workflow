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

# Ensure headless Chromium is available for Playwright PDF export and for the visual snapshot the
# AI slide editor looks at. Installing is not enough: on shared hosting the download succeeds and the
# launch then fails on missing system libraries, which used to leave the editor working blind with
# the reason buried in /tmp. So the launch is verified and the reason printed into deploy.log.
> /tmp/playwright_install.log
# chromium.launch() resolves to chrome-headless-shell, which is a separate download: installing
# "chromium" alone left the host with no launchable browser and the editor working blind.
for browser_target in chromium chromium-headless-shell; do
  echo "--- playwright install $browser_target ---" >> /tmp/playwright_install.log
  "$PYTHON" -m playwright install "$browser_target" >> /tmp/playwright_install.log 2>&1 \
    || echo "WARNING: playwright install $browser_target failed" | tee -a /tmp/playwright_install.log
done

# The result is written where the app can report it, because the install log lives on the server
# and a silent failure here is exactly what hid the missing browser.
"$PYTHON" - > "$APP_DIR/.vision_status" <<'PY' || true
import json
detail = ''
try:
    with open('/tmp/playwright_install.log', encoding='utf-8', errors='replace') as fh:
        detail = fh.read()[-1200:]
except OSError as exc:
    detail = f'no install log: {exc}'
available, error = False, ''
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        available, version = True, browser.version
        browser.close()
    error = f'chromium {version}'
except Exception as exc:
    error = str(exc)[:600]
print(json.dumps({'available': available, 'error': error, 'installLog': detail}, ensure_ascii=False))
PY
if grep -q '"available": true' "$APP_DIR/.vision_status" 2>/dev/null; then
  echo "Slide vision available: the AI editor sees a rendered snapshot of each slide."
else
  echo "WARNING: no slide vision on this host — the AI editor will edit slide markup blind."
  cat "$APP_DIR/.vision_status" 2>/dev/null || true
fi

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

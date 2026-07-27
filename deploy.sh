#!/bin/bash
# One-command deployment script for cPanel shared hosting.
# Run this from /home/sagdemo/proposal-generator after pushing code to GitHub.

set -e

REPO_DIR="/home/sagdemo/workflow.git"
APP_DIR="/home/sagdemo/proposal-generator"
WEB_ROOT="/home/sagdemo/public_html"
PYTHON="$APP_DIR/venv/bin/python"
PIP="$APP_DIR/venv/bin/pip"
GUNICORN="$APP_DIR/venv/bin/gunicorn"

echo "===== 1. Pull latest code ====="
cd "$REPO_DIR"
git pull
git lfs pull || true

echo "===== 2. Sync to app directory ====="
mkdir -p "$APP_DIR"
rsync -av \
  --exclude='app.db' \
  --exclude='data.db' \
  --exclude='.env' \
  --exclude='venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='server.log' \
  --exclude='server_stderr.log' \
  --exclude='server_stdout.log' \
  --exclude='watchdog.log' \
  --exclude='outputs' \
  --exclude='uploads' \
  "$REPO_DIR/" "$APP_DIR/"

echo "===== 3. Clean Python cache ====="
cd "$APP_DIR"
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -name '*.pyc' -delete 2>/dev/null || true

echo "===== 4. Update dependencies ====="
if [ ! -d "$APP_DIR/venv" ]; then
  python3 -m venv "$APP_DIR/venv"
fi
"$PIP" install --upgrade pip setuptools wheel
"$PIP" install -r "$APP_DIR/requirements.txt"
"$PIP" install gunicorn

# Ensure headless Chromium is available for Playwright PDF/PPTX export
if ! "$PYTHON" -m playwright install chromium >/tmp/playwright_install.log 2>&1; then
  echo "WARNING: Playwright Chromium install failed or skipped; check /tmp/playwright_install.log"
fi

echo "===== 5. Run database migrations ====="
"$PYTHON" -c "import app; app.db.init_db()"

echo "===== 6. Start/restart application server ====="
bash "$APP_DIR/start_server.sh"

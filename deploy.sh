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
  --exclude='outputs' \
  --exclude='uploads' \
  "$REPO_DIR/" "$APP_DIR/"

echo "===== 3. Update .htaccess ====="
cp "$APP_DIR/.htaccess_prod" "$WEB_ROOT/.htaccess"

echo "===== 4. Clean Python cache ====="
cd "$APP_DIR"
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -name '*.pyc' -delete 2>/dev/null || true

echo "===== 5. Update dependencies ====="
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

echo "===== 6. Run database migrations ====="
"$PYTHON" -c "import app; app.db.init_db()"

echo "===== 7. Find a free port ====="
PORT=""
for p in 8000 8001 8002 8003 8004 8005 8080 8081 9000 9001 9002 7860 7861; do
  if ! (timeout 1 bash -c "echo >/dev/tcp/127.0.0.1/$p") 2>/dev/null; then
    PORT=$p
    break
  fi
done

if [ -z "$PORT" ]; then
  echo "ERROR: No free port found"
  exit 1
fi

echo "Using port: $PORT"
sed -i "s/127.0.0.1:[0-9]*/127.0.0.1:$PORT/g" "$APP_DIR/.htaccess_prod"
cp "$APP_DIR/.htaccess_prod" "$WEB_ROOT/.htaccess"

echo "===== 8. Stop old gunicorn ====="
fuser -k 3000/tcp 2>/dev/null || true
pkill -9 -f gunicorn 2>/dev/null || true
killall -9 gunicorn 2>/dev/null || true
sleep 2

echo "===== 9. Start gunicorn ====="
cd "$APP_DIR"
"$GUNICORN" -b "127.0.0.1:$PORT" app:app --workers 2 --timeout 300 --daemon --access-logfile "$APP_DIR/server.log" --error-logfile "$APP_DIR/server.log"
sleep 3

echo "===== 10. Health check ====="
if curl -I "http://127.0.0.1:$PORT/health" 2>/dev/null | head -n 1 | grep -q "200"; then
  echo "SUCCESS: Server is running on port $PORT"
  curl -I "https://sagdemo.site/api/branding" 2>/dev/null | head -n 1
else
  echo "ERROR: Health check failed"
  tail -n 30 "$APP_DIR/server.log"
  exit 1
fi

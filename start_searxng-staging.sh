#!/bin/bash
# SearXNG metasearch watchdog / (re)start for the staging host.
# Keeps the local JSON endpoint the browse agents use (SEARXNG_URL,
# default http://127.0.0.1:8888) alive — same cron-every-minute pattern as
# start_server-staging.sh.
#
# One-time install:
#   git clone https://github.com/searxng/searxng.git ~/searxng-src
#   python3 -m venv ~/searxng-venv
#   ~/searxng-venv/bin/pip install -U pip setuptools wheel
#   ~/searxng-venv/bin/pip install -e ~/searxng-src
#   mkdir -p ~/searxng   # then place settings.yml there (json format on)
# Cron: * * * * * /home/landloom/proposal-generator-staging/start_searxng-staging.sh

set -e

export PATH="$HOME/bin:$PATH"

BASE="${SEARXNG_HOME:-$HOME/searxng}"
VENV="${SEARXNG_VENV:-$HOME/searxng-venv}"
SETTINGS="${SEARXNG_SETTINGS_PATH:-$BASE/settings.yml}"
ADDR="${SEARXNG_BIND_ADDRESS:-127.0.0.1:8888}"
PORT="${ADDR##*:}"
PIDFILE="$BASE/searxng-$PORT.pid"
LOG="$BASE/searxng.log"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    exit 0
fi
# Something healthy already answers the port — leave it alone.
if curl -fsS -m 3 "http://$ADDR/search?q=healthcheck&format=json" -o /dev/null 2>/dev/null; then
    exit 0
fi

if [ ! -x "$VENV/bin/searxng-run" ]; then
    echo "searxng-run missing — install SearXNG into $VENV first" >&2
    exit 1
fi

export SEARXNG_SETTINGS_PATH="$SETTINGS"
export SEARXNG_BIND_ADDRESS="$ADDR"
cd "$BASE"
nohup "$VENV/bin/searxng-run" >>"$LOG" 2>&1 &
echo $! > "$PIDFILE"
echo "searxng started pid $(cat "$PIDFILE") on $ADDR"

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
# Cron: * * * * * /home/landloom/proposal-generator-staging/start_searxng-staging.sh >/dev/null 2>&1

set -e

export PATH="$HOME/bin:$PATH"

BASE="${SEARXNG_HOME:-$HOME/searxng}"
VENV="${SEARXNG_VENV:-$HOME/searxng-venv}"
SETTINGS="${SEARXNG_SETTINGS_PATH:-$BASE/settings.yml}"
# searxng-run reads host and port separately — SEARXNG_BIND_ADDRESS is a bare
# host ("127.0.0.1"), never host:port (a "host:port" value reaches getaddrinfo
# as the hostname and the process dies with "Name or service not known").
HOST="${SEARXNG_BIND_ADDRESS:-127.0.0.1}"
PORT="${SEARXNG_PORT:-8888}"
PIDFILE="$BASE/searxng-$PORT.pid"
LOG="$BASE/searxng.log"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    exit 0
fi
# Something healthy already answers the port — leave it alone.
if curl -fsS -m 3 "http://$HOST:$PORT/search?q=healthcheck&format=json" -o /dev/null 2>/dev/null; then
    exit 0
fi

if [ ! -x "$VENV/bin/searxng-run" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') searxng-run missing — install SearXNG into $VENV first" >> "$LOG"
    if [ -t 1 ] || [ -n "${VERBOSE:-}" ]; then
        echo "searxng-run missing — install SearXNG into $VENV first" >&2
    fi
    exit 0
fi

export SEARXNG_SETTINGS_PATH="$SETTINGS"
export SEARXNG_BIND_ADDRESS="$HOST"
export SEARXNG_PORT="$PORT"
cd "$BASE"
nohup "$VENV/bin/searxng-run" >>"$LOG" 2>&1 &
echo $! > "$PIDFILE"
if [ -t 1 ] || [ -n "${VERBOSE:-}" ]; then
    echo "searxng started pid $(cat "$PIDFILE") on $HOST:$PORT"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') searxng started pid $(cat "$PIDFILE") on $HOST:$PORT" >> "$LOG"
fi

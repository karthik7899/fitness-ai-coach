#!/usr/bin/env bash
# Start the app: database if it is not already up, then the server.
# Serves the API and the built frontend together on one port.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

if [ -n "${PREFIX:-}" ] && [ -d "${PREFIX}/bin" ] && command -v pkg >/dev/null 2>&1; then
    PGDATA="$PREFIX/var/lib/postgresql"
    termux-wake-lock 2>/dev/null || true
else
    PGDATA="${PGDATA:-$ROOT/data/pgdata}"
fi

if ! pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
    echo "Starting PostgreSQL…"
    mkdir -p "$ROOT/data"
    # -k keeps the socket somewhere this user can write; see setup.sh.
    pg_ctl -D "$PGDATA" -o "-p 5432 -h 127.0.0.1 -k $PGDATA" \
        -l "$ROOT/data/postgres.log" start
    for _ in $(seq 1 15); do
        pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1 && break
        sleep 1
    done
fi

[ -d "$ROOT/web/dist" ] || echo "web/dist missing — the API will run, but there is no UI to open."

cd "$ROOT/api"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
echo "Open http://$HOST:$PORT"

if command -v uv >/dev/null 2>&1; then
    exec uv run uvicorn app.main:app --host "$HOST" --port "$PORT"
else
    exec ./.venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT"
fi

#!/usr/bin/env bash
# Start the app: database if it is not already up, then the server.
# Serves the API and the built frontend together on one port.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

if [ -n "${PREFIX:-}" ] && [ -d "${PREFIX}/bin" ] && command -v pkg >/dev/null 2>&1; then
    termux-wake-lock 2>/dev/null || true
fi
PGDATA="${PGDATA:-$ROOT/data/pgdata}"

# The server reads DATABASE_URL from the environment or .env; read it the same
# way so this script agrees with the app about which database it is starting.
DB_URL="${DATABASE_URL:-$(sed -n 's/^DATABASE_URL=//p' "$ROOT/.env" 2>/dev/null | tail -n 1)}"

case "$DB_URL" in
    sqlite*)
        # Nothing to start: SQLite is a file the server opens itself.
        ;;
    *)
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
        ;;
esac

[ -d "$ROOT/web/dist" ] || echo "web/dist missing — the API will run, but there is no UI to open."

cd "$ROOT/api"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
echo "Open http://$HOST:$PORT"

if command -v uv >/dev/null 2>&1; then
    exec uv run uvicorn app.main:app --host "$HOST" --port "$PORT"
fi

if [ ! -x ./.venv/bin/uvicorn ]; then
    # Saying "no such file" here would be true and useless: the real story is
    # that setup.sh did not finish.
    echo "The Python environment is missing or incomplete." >&2
    echo "Run ./scripts/setup.sh and check it finishes without an error." >&2
    exit 1
fi

exec ./.venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT"

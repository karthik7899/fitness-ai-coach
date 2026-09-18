#!/usr/bin/env bash
# One-shot install. Works on a desktop and inside Termux on Android.
#
# The two environments differ in three ways and are otherwise identical:
# where PostgreSQL keeps its data, whether psycopg can use a bundled libpq,
# and whether there is a `su` to run the database as another user.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

if [ -n "${PREFIX:-}" ] && [ -d "${PREFIX}/bin" ] && command -v pkg >/dev/null 2>&1; then
    TERMUX=1
    PGDATA="$PREFIX/var/lib/postgresql"
    # Termux is Bionic libc, so the manylinux psycopg-binary wheels do not apply.
    PSYCOPG_EXTRA="system"
else
    TERMUX=0
    PGDATA="${PGDATA:-$ROOT/data/pgdata}"
    PSYCOPG_EXTRA="binary"
fi

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

# --------------------------------------------------------------------------

if [ "$TERMUX" = 1 ]; then
    say "Installing packages"
    pkg install -y postgresql python nodejs-lts git

    say "Keeping the app awake"
    # Android kills background processes; without this the database dies as
    # soon as you switch apps.
    termux-wake-lock || echo "termux-wake-lock unavailable; install Termux:API"
fi

say "PostgreSQL"
if [ ! -d "$PGDATA" ]; then
    echo "Initialising cluster at $PGDATA"
    mkdir -p "$PGDATA"
    initdb -D "$PGDATA" -U aura --auth=trust
fi

if ! pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
    mkdir -p "$ROOT/data"
    # -k puts the unix socket in the data directory. The build default is
    # /var/run/postgresql, which an unprivileged user cannot write to.
    pg_ctl -D "$PGDATA" -o "-p 5432 -h 127.0.0.1 -k $PGDATA" \
        -l "$ROOT/data/postgres.log" start
    for _ in $(seq 1 15); do
        pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1 && break
        sleep 1
    done
fi
pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1 || {
    echo "PostgreSQL did not start; see $ROOT/data/postgres.log" >&2
    exit 1
}
createdb -h 127.0.0.1 -U aura aura 2>/dev/null && echo "Created database" || echo "Database exists"

say "Python dependencies"
cd "$ROOT/api"
if command -v uv >/dev/null 2>&1; then
    uv sync --extra "$PSYCOPG_EXTRA"
    PY="uv run python"
    ALEMBIC="uv run alembic"
else
    [ -d .venv ] || python -m venv .venv
    ./.venv/bin/pip install --quiet --upgrade pip
    ./.venv/bin/pip install --quiet -e ".[$PSYCOPG_EXTRA]"
    PY="./.venv/bin/python"
    ALEMBIC="./.venv/bin/alembic"
fi

say "Database schema"
$ALEMBIC upgrade head
$PY -m app.seed

say "Frontend"
cd "$ROOT/web"
if command -v npm >/dev/null 2>&1; then
    npm install --silent
    npm run build
else
    echo "npm not found. Build web/dist elsewhere and copy it here," >&2
    echo "or install Node and re-run this script." >&2
fi

say "Done"
echo "Start the app with:  ./scripts/start.sh"
echo "Then open:           http://127.0.0.1:8000"

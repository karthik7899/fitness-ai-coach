#!/usr/bin/env bash
# One-shot install. Works on a desktop and inside Termux on Android.
#
# The two environments differ mainly in which database they use: a phone gets
# SQLite, a desktop gets PostgreSQL. Everything above the database is identical.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

if [ -n "${PREFIX:-}" ] && [ -d "${PREFIX}/bin" ] && command -v pkg >/dev/null 2>&1; then
    TERMUX=1
    # SQLite on a phone. Android kills background processes, so a database
    # daemon is the single most fragile part of a Termux install — and for one
    # user on one device, PostgreSQL's concurrency buys nothing.
    DB="${DB:-sqlite}"
else
    TERMUX=0
    DB="${DB:-postgres}"
    PGDATA="${PGDATA:-$ROOT/data/pgdata}"
fi

if [ "$DB" = "sqlite" ]; then
    # No libpq, no driver to build.
    PSYCOPG_EXTRA=""
elif [ "$TERMUX" = 1 ]; then
    # Termux is Bionic libc, so the manylinux psycopg-binary wheels do not apply.
    PSYCOPG_EXTRA="system"
else
    PSYCOPG_EXTRA="binary"
fi

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

# A failed dependency install leaves a half-built virtualenv, and the next
# thing the user sees is start.sh reporting a missing uvicorn — which says
# nothing about what actually went wrong. Say it here instead.
pip_failed() {
    cat >&2 <<'MSG'

Installing the Python dependencies failed.

If it stopped on a Rust package — pydantic-core and cryptography are the ones
that bite — check that Rust is installed and that the target is named, then
try again:

    pkg install rust binutils
    export CARGO_BUILD_TARGET=aarch64-linux-android   # `uname -m` if not arm64
    export CARGO_BUILD_JOBS=1                         # if it ran out of memory
    rm -rf api/.venv
    ./scripts/setup.sh

If it was killed rather than failing with an error, that was the out-of-memory
killer: CARGO_BUILD_JOBS=1 and closing other apps is the fix.

MSG
    exit 1
}

# --------------------------------------------------------------------------

if [ "$TERMUX" = 1 ]; then
    say "Installing packages"
    PACKAGES="python nodejs-lts git"
    [ "$DB" = "sqlite" ] || PACKAGES="postgresql $PACKAGES"
    # shellcheck disable=SC2086
    pkg install -y $PACKAGES

    # Several dependencies are Rust extensions with no Android wheel —
    # cryptography (via google-genai -> google-auth) and pydantic-core (via
    # FastAPI) among them. pip therefore builds them, and maturin looks for a
    # toolchain: finding none it tries rustup, which has no Android target, and
    # gives up with "Target triple not supported by rustup".
    #
    # So: install Termux's Rust, which does target Android, and take its
    # prebuilt cryptography to skip the largest build.
    say "Build tools for the Rust-based packages"
    pkg install -y rust binutils || echo "Could not install Rust; the Python step will likely fail." >&2
    pkg install -y python-cryptography || echo "No prebuilt cryptography; it will be built from source." >&2

    say "Keeping the app awake"
    # Android kills background processes; without this the server dies as soon
    # as you switch apps.
    termux-wake-lock || echo "termux-wake-lock unavailable; install Termux:API"

    if [ ! -d "$HOME/storage" ]; then
        say "Storage access"
        # Termux is sandboxed and cannot see shared storage until this is
        # granted — which is where FitNotes and Gadgetbridge write their
        # backups, so without it there is nothing for the app to import.
        echo "Android will ask for permission. Allow it."
        termux-setup-storage || echo "Could not request storage access; run termux-setup-storage by hand."
        sleep 2
    fi
fi

if [ "$DB" = "sqlite" ]; then
    say "Database"
    mkdir -p "$ROOT/data"
    if ! grep -qs '^DATABASE_URL=' "$ROOT/.env" 2>/dev/null; then
        echo "DATABASE_URL=sqlite:///$ROOT/data/aura.db" >> "$ROOT/.env"
    fi
    echo "SQLite at $ROOT/data/aura.db — nothing to keep running."
else
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
fi

say "Python dependencies"
cd "$ROOT/api"
if command -v uv >/dev/null 2>&1; then
    if [ -n "$PSYCOPG_EXTRA" ]; then
        uv sync --extra "$PSYCOPG_EXTRA"
    else
        uv sync
    fi
    PY="uv run python"
    ALEMBIC="uv run alembic"
else
    if [ ! -d .venv ]; then
        # --system-site-packages on Termux so the virtualenv can see the
        # packages pkg installed, rather than trying to build them itself.
        if [ "$TERMUX" = 1 ]; then
            python -m venv --system-site-packages .venv
        else
            python -m venv .venv
        fi
    fi
    ./.venv/bin/pip install --quiet --upgrade pip

    if [ "$TERMUX" = 1 ]; then
        # maturin derives 'aarch64-unknown-linux-android' from Python's SOABI,
        # which is not a triple Termux's Rust knows; its own is
        # 'aarch64-linux-android'. Naming it explicitly is what stops the
        # rustup detour.
        case "$(uname -m)" in
            aarch64|arm64) export CARGO_BUILD_TARGET=aarch64-linux-android ;;
            armv7l|armv8l) export CARGO_BUILD_TARGET=armv7-linux-androideabi ;;
            x86_64) export CARGO_BUILD_TARGET=x86_64-linux-android ;;
        esac
        # Building pydantic-core with every core at once is what makes a phone
        # run out of memory partway through.
        export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-2}"
        echo "Building Rust extensions for ${CARGO_BUILD_TARGET:-this device}."
        echo "This is the slow part — ten minutes or more is normal. Leave it be."
    fi

    # Not quiet on a phone: this takes minutes, and silence looks like a hang.
    QUIET="--quiet"
    [ "$TERMUX" = 1 ] && QUIET=""
    # shellcheck disable=SC2086
    if [ -n "$PSYCOPG_EXTRA" ]; then
        ./.venv/bin/pip install $QUIET -e ".[$PSYCOPG_EXTRA]" || pip_failed
    else
        ./.venv/bin/pip install $QUIET -e . || pip_failed
    fi
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

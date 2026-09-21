"""Regenerate the expected rows in `fixtures/`.

Python is the reference implementation: these files record what its importers
produce, and the Kotlin suite then has to match them. Run this when an
importer's behaviour changes on purpose, and read the diff — a change here is a
change to what a backup file means.

    cd api && uv run python ../scripts/refresh_fixtures.py
    cd api && uv run python ../scripts/refresh_fixtures.py --check
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

# Gadgetbridge samples are bucketed into days by local time, so the timezone has
# to be pinned before anything reads one. Must precede the app imports.
os.environ["TZ"] = "UTC"
time.tzset()

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "api"
FIXTURES = REPO_ROOT / "fixtures"
SCHEMA = REPO_ROOT / "android/core/src/main/resources/aura/schema.sql"

sys.path.insert(0, str(API_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.adapters import fitnotes, gadgetbridge  # noqa: E402
from app.db import configure_sqlite  # noqa: E402


def build_source(sql_path: Path, target: Path) -> Path:
    """Materialise one of the *.source.sql files as a real database file."""
    connection = sqlite3.connect(target)
    connection.executescript(sql_path.read_text())
    connection.commit()
    connection.close()
    return target


def canonical_db(path: Path) -> Session:
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA.read_text())
    connection.commit()
    connection.close()
    engine = configure_sqlite(create_engine(f"sqlite:///{path}", future=True))
    return Session(engine)


def read_rows(session: Session, query_path: Path) -> list[str]:
    return [row[0] for row in session.execute(text(query_path.read_text())).all()]


def generate() -> dict[Path, str]:
    """Run every importer over its fixture and return the rows each produced."""
    produced: dict[Path, str] = {}

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)

        for name in ("fitnotes_metric", "fitnotes_imperial"):
            source = build_source(FIXTURES / f"{name}.source.sql", work / f"{name}.fitnotes")
            with canonical_db(work / f"{name}.canonical.db") as session:
                fitnotes.import_sets(session, fitnotes.parse_sqlite(source))
                lines = read_rows(session, FIXTURES / "rows_fitnotes.sql")
            produced[FIXTURES / f"{name}.expected.csv"] = "".join(f"{line}\n" for line in lines)

        source = build_source(FIXTURES / "gadgetbridge.source.sql", work / "gadgetbridge.db")
        with canonical_db(work / "gadgetbridge.canonical.db") as session:
            gadgetbridge.upsert_daily(session, gadgetbridge.extract_daily(source))
            session.commit()
            lines = read_rows(session, FIXTURES / "rows_gadgetbridge.sql")
        produced[FIXTURES / "gadgetbridge.expected.csv"] = "".join(f"{line}\n" for line in lines)

    return produced


def main() -> int:
    produced = generate()

    if "--check" in sys.argv:
        stale = [
            path
            for path, content in produced.items()
            if not path.exists() or path.read_text() != content
        ]
        if stale:
            for path in stale:
                print(f"stale: {path.relative_to(REPO_ROOT)}", file=sys.stderr)
            print("Run: uv run python ../scripts/refresh_fixtures.py", file=sys.stderr)
            return 1
        print(f"{len(produced)} fixture files are up to date.")
        return 0

    for path, content in produced.items():
        path.write_text(content)
        print(f"Wrote {path.relative_to(REPO_ROOT)} ({len(content.splitlines())} rows).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

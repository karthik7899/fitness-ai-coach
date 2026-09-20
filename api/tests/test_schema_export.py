"""The schema the Android app is built against.

The Kotlin app does not run Alembic; it applies a generated SQL file. These
tests are what keep that file honest, and what keep SQLite's untyped columns
from quietly storing a boolean as text.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from export_schema import TARGET, build_schema_sql  # noqa: E402


@pytest.fixture(scope="module")
def schema_sql() -> str:
    return build_schema_sql()


def test_exported_schema_is_current(schema_sql):
    """A stale asset would ship the phone a different database than the server."""
    assert TARGET.exists(), f"{TARGET} is missing. Run scripts/export_schema.py."
    assert TARGET.read_text() == schema_sql, (
        f"{TARGET.relative_to(REPO_ROOT)} is out of date with the migrations. "
        "Run: uv run python ../scripts/export_schema.py"
    )


def test_no_boolean_column_defaults_to_text(schema_sql):
    """SQLite has no boolean type, so a quoted default is stored as text.

    `DEFAULT 'true'` then reads as *false* everywhere, because SQLite coerces
    the text 'true' to 0 in a boolean context. `DEFAULT 'false'` only looks
    correct by the same accident. Both must be numeric literals.
    """
    offenders = re.findall(r"^\s*(\w+)\s+BOOLEAN[^,\n]*DEFAULT\s+'[^']*'", schema_sql, re.M)
    assert offenders == [], (
        "Boolean columns with a text default: "
        + ", ".join(offenders)
        + ". Use sa.true()/sa.false(), which render as 1/0 on SQLite."
    )


def test_boolean_defaults_behave_as_booleans(schema_sql, tmp_path):
    """Insert without the boolean columns and check the values that come back."""
    database = tmp_path / "schema.db"
    connection = sqlite3.connect(database)
    connection.executescript(schema_sql)

    connection.execute("INSERT INTO exercises (id, name) VALUES (1, 'Test Lift')")
    connection.execute("INSERT INTO workouts (id, performed_on) VALUES (1, '2026-01-01')")
    connection.execute(
        "INSERT INTO sets (id, workout_id, exercise_id, weight_kg, reps)"
        " VALUES (1, 1, 1, 100, 5)"
    )
    connection.execute("INSERT INTO exercise_muscles (exercise_id, muscle) VALUES (1, 'quads')")
    connection.execute(
        "INSERT INTO coach_notes (id, kind, content)"
        " VALUES (1, 'injury', 'Left shoulder, no overhead pressing')"
    )

    # The defaulted set is a working set, so the views must count it.
    assert connection.execute("SELECT COUNT(*) FROM sets WHERE NOT is_warmup").fetchone()[0] == 1
    assert connection.execute("SELECT volume_kg FROM v_daily_volume").fetchone()[0] == 500
    # The defaulted muscle row is primary, so attribution must find it.
    assert connection.execute("SELECT muscle FROM v_weekly_muscle_volume").fetchone()[0] == "quads"
    # This is the one that was actually wrong. coach_notes.is_active decides
    # which durable facts load into every conversation, so a text 'true' default
    # meant a recorded injury was invisible to the coach.
    assert connection.execute(
        "SELECT content FROM coach_notes WHERE is_active"
    ).fetchone() is not None
    assert connection.execute(
        "SELECT COUNT(*) FROM exercises WHERE NOT is_archived"
    ).fetchone()[0] == 1
    connection.close()

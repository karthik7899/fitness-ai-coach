"""Test harness.

Tests run against a real Postgres database built by the real migrations, so the
SQL views — where every number the coach quotes comes from — are exercised rather
than mocked. Each test gets a session inside a transaction that is rolled back,
so tests never see each other's rows.
"""

import os
from urllib.parse import urlsplit, urlunsplit

# Must precede any app import: app.config builds its settings singleton on import,
# and environment variables outrank the .env file.
DEFAULT_URL = "postgresql+psycopg://aura:aura@127.0.0.1:5432/aura"
TEST_DB = "aura_test"
SQLITE_PATH = "/tmp/aura_test.sqlite3"

# TEST_DIALECT selects which database the whole suite runs against. Both are
# supported by the app, so both are worth running: the SQL views are the coach's
# only source of numbers, and a dialect difference there would be silent.
DIALECT = os.environ.get("TEST_DIALECT", "postgresql")

if DIALECT == "sqlite":
    TEST_URL = f"sqlite:///{SQLITE_PATH}"
    ADMIN_URL = None
else:
    _parts = urlsplit(os.environ.get("DATABASE_URL", DEFAULT_URL))
    TEST_URL = urlunsplit(_parts._replace(path=f"/{TEST_DB}"))
    ADMIN_URL = urlunsplit(_parts._replace(path="/postgres"))

os.environ["DATABASE_URL"] = TEST_URL

import datetime as dt  # noqa: E402
import sqlite3  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import configure_sqlite  # noqa: E402
from app.models import Exercise, SetEntry, Workout  # noqa: E402

API_DIR = Path(__file__).resolve().parents[1]


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture(scope="session")
def engine():
    if DIALECT == "sqlite":
        Path(SQLITE_PATH).unlink(missing_ok=True)
    else:
        import psycopg

        with psycopg.connect(_psycopg_url(ADMIN_URL), autocommit=True) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
            conn.execute(f"CREATE DATABASE {TEST_DB}")

    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    command.upgrade(config, "head")

    engine = configure_sqlite(create_engine(TEST_URL, future=True))
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    """A session whose writes are always rolled back, even across inner commits."""
    connection = engine.connect()
    transaction = connection.begin()
    # Adapters commit internally; savepoints let the outer rollback still win.
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield db
    finally:
        db.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def exercises(session) -> dict[str, Exercise]:
    rows = {
        "squat": Exercise(
            name="Back Squat", category="Legs", primary_muscles=["quads", "glutes"]
        ),
        "bench": Exercise(
            name="Bench Press", category="Chest", primary_muscles=["chest", "triceps"]
        ),
        # No muscle mapping: exercises the category fallback in the weekly view.
        "sled": Exercise(name="Sled Push", category="Conditioning", primary_muscles=[]),
    }
    session.add_all(rows.values())
    session.flush()
    return rows


def add_workout(session: Session, day: dt.date, sets: list[tuple[Exercise, float, int, bool]]):
    """sets: (exercise, weight_kg, reps, is_warmup)"""
    workout = Workout(performed_on=day, source="manual")
    session.add(workout)
    session.flush()
    for position, (exercise, weight, reps, warmup) in enumerate(sets, start=1):
        session.add(
            SetEntry(
                workout_id=workout.id,
                exercise_id=exercise.id,
                position=position,
                weight_kg=weight,
                reps=reps,
                is_warmup=warmup,
            )
        )
    session.flush()
    return workout


def rows_of(session: Session, sql: str, **params) -> list[dict]:
    return [dict(r) for r in session.execute(text(sql), params).mappings()]


# --------------------------------------------------------------------------
# Fixture files
# --------------------------------------------------------------------------


def write_fitnotes_db(path: Path, entries: list[tuple[str, str, float, int, int]]) -> Path:
    """entries: (date, exercise, metric_weight, reps, unit)"""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE Category (_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE exercise (_id INTEGER PRIMARY KEY, name TEXT, category_id INTEGER);
        CREATE TABLE training_log (
            _id INTEGER PRIMARY KEY AUTOINCREMENT, exercise_id INTEGER, date TEXT,
            metric_weight REAL, reps INTEGER, distance REAL, metric_distance REAL,
            duration_seconds INTEGER, unit INTEGER, comment TEXT);
        """
    )
    conn.execute("INSERT INTO Category VALUES (1, 'Legs')")
    names: dict[str, int] = {}
    for _, name, *_rest in entries:
        if name not in names:
            names[name] = len(names) + 1
            conn.execute("INSERT INTO exercise VALUES (?,?,1)", (names[name], name))
    conn.executemany(
        "INSERT INTO training_log (exercise_id, date, metric_weight, reps, unit)"
        " VALUES (?,?,?,?,?)",
        [(names[name], day, weight, reps, unit) for day, name, weight, reps, unit in entries],
    )
    conn.commit()
    conn.close()
    return path


def write_gadgetbridge_db(path: Path, samples: list[tuple[int, int, int, int]]) -> Path:
    """samples: (epoch_seconds, steps, heart_rate, kind)"""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE MOYOUNG_ACTIVITY_SAMPLE (
            TIMESTAMP INTEGER NOT NULL, DEVICE_ID INTEGER NOT NULL, USER_ID INTEGER NOT NULL,
            RAW_INTENSITY INTEGER, STEPS INTEGER, RAW_KIND INTEGER, KIND INTEGER,
            HEART_RATE INTEGER, PRIMARY KEY (TIMESTAMP, DEVICE_ID, USER_ID))
        """
    )
    conn.executemany(
        "INSERT OR IGNORE INTO MOYOUNG_ACTIVITY_SAMPLE"
        " (TIMESTAMP, DEVICE_ID, USER_ID, STEPS, HEART_RATE, KIND) VALUES (?,1,1,?,?,?)",
        samples,
    )
    conn.commit()
    conn.close()
    return path

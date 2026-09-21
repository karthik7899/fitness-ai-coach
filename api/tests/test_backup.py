"""Backup and restore.

A backup that cannot be restored is worse than none, so these tests care less
about the happy path than about what happens when the file is wrong: a damaged
database, someone else's database, an empty upload. Each of those must be
refused with a reason, and must not touch the live data.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app import backup
from app.db import configure_sqlite

SCHEMA = (
    Path(__file__).resolve().parents[2] / "android/core/src/main/resources/aura/schema.sql"
)


@pytest.fixture
def live(tmp_path):
    """A real database file, built from the canonical schema.

    Not `Base.metadata.create_all()`: that builds the tables but none of the
    views, and a backup missing the views would restore a database that cannot
    answer a single question the coach asks.
    """
    path = tmp_path / "aura.db"
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA.read_text())
    connection.commit()
    connection.close()
    return configure_sqlite(create_engine(f"sqlite:///{path}", future=True)), path


def test_a_backup_reports_what_it_holds(live, tmp_path):
    live_engine, _ = live
    with live_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO exercises (id, name, category) VALUES (1, 'Back Squat', 'Legs')")
        )
        connection.execute(
            text(
                "INSERT INTO workouts (id, performed_on, source)"
                " VALUES (1, '2026-09-01', 'manual')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO sets (id, workout_id, exercise_id, position, weight_kg, reps)"
                " VALUES (1, 1, 1, 1, 100, 5)"
            )
        )

    destination = tmp_path / "backup.db"
    info = backup.create(live_engine, destination)
    assert info.workouts == 1
    assert info.sets == 1
    assert info.earliest == "2026-09-01"
    assert not info.is_empty


def test_the_backup_is_a_usable_database(live, tmp_path):
    live_engine, _ = live
    destination = tmp_path / "backup.db"
    backup.create(live_engine, destination)

    # Not just readable: the views have to have come across too, since that is
    # where every number the coach quotes comes from.
    with sqlite3.connect(destination) as connection:
        views = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'view'")
        }
    assert "v_training_load" in views


def test_someone_elses_database_is_refused(tmp_path):
    stranger = tmp_path / "notes.db"
    with sqlite3.connect(stranger) as connection:
        connection.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")

    with pytest.raises(backup.NotABackup, match="not an Aura backup"):
        backup.verify(stranger)


def test_a_file_that_is_not_a_database_is_refused(tmp_path):
    junk = tmp_path / "holiday.jpg"
    junk.write_bytes(b"\xff\xd8\xff\xe0 this is a photo, not a database")

    with pytest.raises(backup.NotABackup):
        backup.verify(junk)


def test_an_empty_file_is_refused(tmp_path):
    empty = tmp_path / "empty.db"
    empty.touch()
    with pytest.raises(backup.NotABackup, match="empty"):
        backup.verify(empty)


def test_a_truncated_backup_is_refused(live, tmp_path):
    live_engine, _ = live
    destination = tmp_path / "backup.db"
    backup.create(live_engine, destination)

    damaged = tmp_path / "damaged.db"
    content = destination.read_bytes()
    damaged.write_bytes(content[: len(content) // 3])

    with pytest.raises(backup.NotABackup):
        backup.verify(damaged)


def test_restore_keeps_the_database_it_replaced(live, tmp_path):
    live_engine, path = live
    with live_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO exercises (id, name) VALUES (1, 'Original Lift')")
        )

    incoming = tmp_path / "incoming.db"
    backup.create(live_engine, incoming)
    with sqlite3.connect(incoming) as connection:
        connection.execute("INSERT INTO exercises (id, name) VALUES (2, 'Restored Lift')")

    _, replaced = backup.restore(live_engine, incoming)

    assert replaced.exists(), "the replaced database must be recoverable"
    with sqlite3.connect(path) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM exercises")}
    assert names == {"Original Lift", "Restored Lift"}


def test_restore_refuses_a_bad_file_without_touching_the_live_database(live, tmp_path):
    live_engine, path = live
    with live_engine.begin() as connection:
        connection.execute(text("INSERT INTO exercises (id, name) VALUES (1, 'Still Here')"))

    junk = tmp_path / "junk.db"
    junk.write_bytes(b"not a database at all")

    with pytest.raises(backup.NotABackup):
        backup.restore(live_engine, junk)

    with sqlite3.connect(path) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM exercises")}
    assert names == {"Still Here"}, "a refused restore must leave the data alone"


def test_postgres_is_pointed_at_its_own_tools():
    postgres = create_engine("postgresql+psycopg://aura:aura@127.0.0.1:5432/aura")
    with pytest.raises(backup.NotABackup, match="pg_dump"):
        backup.database_path(postgres)


# --------------------------------------------------------------------------
# The HTTP surface
# --------------------------------------------------------------------------


@pytest.fixture
def client(session):
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app

    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_inspect_reports_a_backup_without_touching_anything(client, live, tmp_path):
    live_engine, _ = live
    candidate = tmp_path / "backup.db"
    backup.create(live_engine, candidate)

    response = client.post(
        "/api/backup/inspect", files={"file": ("backup.db", candidate.read_bytes())}
    )
    assert response.status_code == 200
    assert response.json()["is_empty"] is True


def test_inspect_explains_why_a_bad_file_is_rejected(client):
    response = client.post(
        "/api/backup/inspect", files={"file": ("holiday.jpg", b"\xff\xd8\xff\xe0 not a database")}
    )
    assert response.status_code == 400
    assert "SQLite" in response.json()["detail"]


def test_download_matches_the_database_the_app_is_using(client):
    """On PostgreSQL this must refuse clearly rather than produce half a backup."""
    from tests.conftest import DIALECT

    response = client.get("/api/backup")
    if DIALECT == "sqlite":
        assert response.status_code == 200
        assert response.content[:15] == b"SQLite format 3"
    else:
        assert response.status_code == 400
        assert "pg_dump" in response.json()["detail"]

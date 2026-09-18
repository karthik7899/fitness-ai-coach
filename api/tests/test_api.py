"""HTTP surface: the contract the web app is written against."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.db import get_session
from app.main import app
from tests.conftest import add_workout

TODAY = dt.date.today()


@pytest.fixture
def client(session):
    # Constructed without a context manager so the lifespan — and with it the
    # background scheduler — never starts during tests.
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_create_and_list_exercises(client):
    created = client.post(
        "/api/exercises",
        json={"name": "Zercher Squat", "category": "Legs", "primary_muscles": ["quads"]},
    )
    assert created.status_code == 201
    assert created.json()["name"] == "Zercher Squat"

    names = [e["name"] for e in client.get("/api/exercises").json()]
    assert "Zercher Squat" in names


def test_duplicate_exercise_is_rejected_case_insensitively(client):
    client.post("/api/exercises", json={"name": "Hack Squat"})
    clash = client.post("/api/exercises", json={"name": "hack squat"})
    assert clash.status_code == 409


def test_exercise_search_filters(client, exercises):
    found = client.get("/api/exercises", params={"search": "bench"}).json()
    assert [e["name"] for e in found] == ["Bench Press"]


def test_creating_a_workout_twice_returns_the_same_one(client):
    first = client.post("/api/workouts", json={"performed_on": TODAY.isoformat()})
    second = client.post("/api/workouts", json={"performed_on": TODAY.isoformat()})
    assert first.json()["id"] == second.json()["id"], "one manual workout per day"


def test_add_and_remove_sets(client, exercises):
    workout_id = client.post("/api/workouts", json={"performed_on": TODAY.isoformat()}).json()["id"]

    for weight in (60, 100):
        added = client.post(
            f"/api/workouts/{workout_id}/sets",
            json={"exercise_id": exercises["squat"].id, "weight_kg": weight, "reps": 5},
        )
        assert added.status_code == 201

    detail = client.get(f"/api/workouts/{workout_id}").json()
    assert [s["position"] for s in detail["sets"]] == [1, 2]
    assert [s["weight_kg"] for s in detail["sets"]] == [60.0, 100.0]

    set_id = detail["sets"][0]["id"]
    assert client.delete(f"/api/sets/{set_id}").status_code == 204
    assert len(client.get(f"/api/workouts/{workout_id}").json()["sets"]) == 1


def test_adding_a_set_to_a_missing_workout_is_a_404(client, exercises):
    response = client.post(
        "/api/workouts/999999/sets", json={"exercise_id": exercises["squat"].id, "reps": 5}
    )
    assert response.status_code == 404


def test_adding_a_set_with_an_unknown_exercise_is_a_404(client):
    workout_id = client.post("/api/workouts", json={"performed_on": TODAY.isoformat()}).json()["id"]
    response = client.post(f"/api/workouts/{workout_id}/sets", json={"exercise_id": 999999})
    assert response.status_code == 404


def test_rpe_outside_one_to_ten_is_rejected_by_the_database(client, exercises):
    workout_id = client.post("/api/workouts", json={"performed_on": TODAY.isoformat()}).json()["id"]
    with pytest.raises(IntegrityError, match="ck_sets_rpe_range"):
        client.post(
            f"/api/workouts/{workout_id}/sets",
            json={"exercise_id": exercises["squat"].id, "reps": 5, "rpe": 47},
        )


def test_summary_reflects_logged_sets(client, session, exercises):
    add_workout(session, TODAY, [(exercises["squat"], 100, 5, False)])
    summary = client.get("/api/metrics/summary").json()
    assert summary["recent_workouts"][0]["volume_kg"] == 500.0
    assert summary["load"]["date"] == TODAY.isoformat()


def test_exercise_progression_respects_the_date_range(client, session, exercises):
    add_workout(session, TODAY, [(exercises["squat"], 100, 5, False)])
    add_workout(
        session, TODAY - dt.timedelta(days=200), [(exercises["squat"], 80, 5, False)]
    )

    recent = client.get(
        "/api/metrics/exercise/Back Squat",
        params={"start": (TODAY - dt.timedelta(days=30)).isoformat(), "end": TODAY.isoformat()},
    ).json()
    assert len(recent) == 1

    wide = client.get(
        "/api/metrics/exercise/back squat",
        params={"start": (TODAY - dt.timedelta(days=365)).isoformat(), "end": TODAY.isoformat()},
    ).json()
    assert len(wide) == 2


def test_exercises_with_history_excludes_untrained_ones(client, session, exercises):
    add_workout(session, TODAY, [(exercises["squat"], 100, 5, False)])
    listed = [e["exercise"] for e in client.get("/api/metrics/exercises").json()]
    assert listed == ["Back Squat"]


def test_volume_endpoint_groups_by_muscle(client, session, exercises):
    add_workout(session, TODAY, [(exercises["squat"], 100, 5, False)])
    volume = client.get("/api/metrics/volume").json()
    assert {r["muscle"] for r in volume["by_muscle"]} == {"quads", "glutes"}


def test_sync_status_covers_every_scheduled_adapter(client):
    from app.scheduler import ADAPTERS

    status = client.get("/api/sync/status").json()
    assert set(status) == {a.source for a in ADAPTERS}


def test_import_now_also_reads_the_watched_folders(client, session, tmp_path, monkeypatch):
    """The endpoint behind the button must do what the scheduler does, not less."""
    from app import settings_store
    from app.config import Settings
    from tests.conftest import write_fitnotes_db

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(Settings, "inbox_path", property(lambda self: inbox))

    watched = tmp_path / "FitNotesBackup"
    watched.mkdir()
    write_fitnotes_db(
        watched / "FitNotes_Backup.fitnotes", [(TODAY.isoformat(), "Back Squat", 100.0, 5, 0)]
    )
    settings_store.put(session, settings_store.INGEST, {"watch_dirs": [str(watched)]})

    body = client.post("/api/sync/inbox").json()
    assert body["watching"] == [str(watched)]
    assert [f["written"] for f in body["files"]] == [1]


def test_syncing_an_unconnected_source_reports_an_error(client):
    response = client.post("/api/sync/strava")
    assert response.status_code == 400
    assert "not connected" in response.json()["detail"].lower()

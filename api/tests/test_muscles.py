"""Sets per muscle over the last seven days, and the HTTP routes that go with
the Log screen's new actions: correcting a set and asking what records it broke.
MusclesTest in WorkoutsTest.kt pins the same counting for the Android app.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import muscles
from tests.conftest import add_workout

TODAY = dt.date(2026, 3, 10)


def by_muscle(rows: list[dict]) -> dict[str, dict]:
    return {r["muscle"]: r for r in rows}


def test_sets_count_for_each_primary_muscle_within_seven_days(session, exercises):
    squat, bench, sled = exercises["squat"], exercises["bench"], exercises["sled"]
    add_workout(session, TODAY - dt.timedelta(days=7), [(squat, 100, 5, False)] * 5)  # too old
    add_workout(session, TODAY - dt.timedelta(days=6), [(squat, 100, 5, False)] * 4)
    add_workout(session, TODAY, [
        (squat, 60, 5, True),               # warmup: not counted
        *[(bench, 80, 8, False)] * 12,
        (sled, 50, 1, False),               # no muscles: its category stands in
    ])

    rows = muscles.last_seven_days(session, TODAY)
    got = by_muscle(rows)
    assert (got["quads"]["sets"], got["glutes"]["sets"]) == (4, 4)
    assert (got["chest"]["sets"], got["chest"]["status"]) == (12, "on_target")
    assert got["quads"]["status"] == "under"
    assert got["Conditioning"]["sets"] == 1
    # Every major muscle is listed, trained or not, in a fixed order first.
    assert [r["muscle"] for r in rows][: len(muscles.MAJOR)] == muscles.MAJOR
    assert got["calves"]["sets"] == 0
    assert got["upper_back"]["label"] == "Upper back"


def test_status_bands():
    assert [muscles.status(n) for n in (0, 9, 10, 20, 21)] == [
        "under", "under", "on_target", "on_target", "over",
    ]


@pytest.fixture
def client(session):
    from app.db import get_session
    from app.main import app

    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_a_set_can_be_corrected(client, session, exercises):
    workout = add_workout(session, TODAY, [(exercises["bench"], 80, 8, False)])
    set_id = client.get(f"/api/workouts/{workout.id}").json()["sets"][0]["id"]

    fixed = client.put(
        f"/api/sets/{set_id}", json={"weight_kg": 82.5, "reps": 7, "rpe": 9, "is_warmup": False}
    )
    assert fixed.status_code == 200
    assert (fixed.json()["weight_kg"], fixed.json()["reps"], fixed.json()["rpe"]) == (82.5, 7, 9)
    assert client.put(f"/api/sets/{set_id}", json={"rpe": 11}).status_code == 422
    assert client.put("/api/sets/999999", json={}).status_code == 404


def test_the_records_route_reports_what_a_set_broke(client, session, exercises):
    bench = exercises["bench"]
    add_workout(session, TODAY - dt.timedelta(days=3), [(bench, 80, 8, False)])
    workout = add_workout(session, TODAY, [(bench, 85, 8, False)])
    set_id = client.get(f"/api/workouts/{workout.id}").json()["sets"][0]["id"]

    body = client.get(f"/api/sets/{set_id}/records").json()
    assert body["exercise"] == "Bench Press"
    assert [r["kind"] for r in body["records"]] == ["weight", "e1rm"]
    assert client.get("/api/sets/999999/records").status_code == 404


def test_the_muscle_route(client):
    body = client.get("/api/metrics/muscle-sets").json()
    assert body["target"] == {"min": 10, "max": 20, "major": muscles.MAJOR}
    assert len(body["muscles"]) == len(muscles.MAJOR)

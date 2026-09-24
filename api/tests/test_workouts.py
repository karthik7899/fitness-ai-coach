"""Starter workouts: the templates, starting one, and progress through it.

The same behaviour is pinned for the Android app in WorkoutsTest.kt, which
reads the file export_workouts.py writes from these templates.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import workouts
from app.models import Exercise
from app.seed import CATALOGUE
from tests.conftest import add_workout

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from export_workouts import TARGET, build  # noqa: E402

TODAY = dt.date(2026, 3, 10)


def test_the_exported_workouts_are_current():
    assert TARGET.exists() and TARGET.read_text() == build(), (
        "Stale. Run `uv run python ../scripts/export_workouts.py`."
    )


def test_every_template_exercise_is_in_the_catalogue():
    known = {name for name, *_ in CATALOGUE}
    for template in workouts.TEMPLATES:
        for name, sets, reps in template["exercises"]:
            assert name in known, f"{template['id']}: {name} is not in the catalogue"
            assert sets > 0 and reps > 0


def test_template_ids_are_unique():
    ids = [t["id"] for t in workouts.TEMPLATES]
    assert len(ids) == len(set(ids))


def test_starting_creates_missing_exercises_with_their_muscles(session):
    workouts.start(session, "full-body-a", TODAY)

    row = session.scalar(select(Exercise).where(Exercise.name == "Barbell Row"))
    assert row.category == "Back"
    assert sorted(row.primary_muscles) == ["lats", "upper_back"]


def test_starting_leaves_an_existing_exercise_alone(session):
    # Differently cased, with its own muscles: it came from an import.
    session.add(Exercise(name="back squat", category="Squats", primary_muscles=["quads"]))
    session.commit()

    workouts.start(session, "full-body-a", TODAY)

    squats = session.scalars(
        select(Exercise).where(func.lower(Exercise.name) == "back squat")
    ).all()
    assert len(squats) == 1
    assert squats[0].category == "Squats" and squats[0].primary_muscles == ["quads"]


def test_an_unknown_template_starts_nothing(session):
    assert workouts.start(session, "no-such-thing", TODAY) is None
    assert workouts.plan(session, TODAY) is None


@pytest.fixture
def started(session, exercises):
    workouts.start(session, "full-body-a", TODAY)
    return session


def entry(plan: dict, name: str) -> dict:
    return next(e for e in plan["entries"] if e["exercise"] == name)


def test_progress_counts_todays_working_sets(started, exercises):
    squat, bench = exercises["squat"], exercises["bench"]
    add_workout(started, TODAY - dt.timedelta(days=2), [(squat, 95, 5, False)])
    add_workout(started, TODAY, [
        (squat, 60, 5, True),     # warmup: not progress
        (squat, 100, 5, False),
        (squat, 100, 5, False),
        (bench, 70, 5, False),
    ])

    plan = workouts.plan(started, TODAY)
    assert plan["template"]["id"] == "full-body-a"
    assert entry(plan, "Back Squat")["done"] == 2
    assert entry(plan, "Bench Press")["done"] == 1
    assert entry(plan, "Barbell Row")["done"] == 0


def test_last_weight_is_the_most_recent_working_set(started, exercises):
    squat = exercises["squat"]
    add_workout(started, TODAY - dt.timedelta(days=7), [(squat, 90, 5, False)])
    add_workout(started, TODAY - dt.timedelta(days=2), [
        (squat, 95, 5, False),
        (squat, 97.5, 5, False),
        (squat, 50, 10, True),    # a later warmup does not count
    ])

    plan = workouts.plan(started, TODAY)
    assert entry(plan, "Back Squat")["last_weight_kg"] == 97.5
    assert entry(plan, "Barbell Row")["last_weight_kg"] is None


def test_a_plan_lasts_only_the_day_it_was_started(started):
    assert workouts.plan(started, TODAY) is not None
    assert workouts.plan(started, TODAY + dt.timedelta(days=1)) is None


def test_finishing_clears_the_plan(started):
    workouts.finish(started)
    assert workouts.plan(started, TODAY) is None


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


@pytest.fixture
def client(session):
    from app.db import get_session
    from app.main import app

    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_api_lists_starts_and_finishes(client):
    listed = client.get("/api/templates").json()
    assert [t["id"] for t in listed][:2] == ["full-body-a", "full-body-b"]
    assert client.get("/api/templates/active").json() is None

    started = client.post("/api/templates/push/start")
    assert started.status_code == 200
    plan = started.json()
    assert plan["template"]["name"] == "Push"
    assert all(e["exercise_id"] is not None for e in plan["entries"])
    assert client.get("/api/templates/active").json()["template"]["id"] == "push"

    assert client.delete("/api/templates/active").status_code == 204
    assert client.get("/api/templates/active").json() is None


def test_the_api_refuses_an_unknown_template(client):
    assert client.post("/api/templates/nope/start").status_code == 404

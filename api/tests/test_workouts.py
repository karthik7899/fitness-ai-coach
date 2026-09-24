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
from app.models import Exercise, SetEntry, Workout
from app.seed import ALIASES, CATALOGUE
from tests.conftest import add_workout

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from export_workouts import TARGET, build  # noqa: E402

TODAY = dt.date(2026, 3, 10)


def test_the_exported_workouts_are_current():
    assert TARGET.exists() and TARGET.read_text() == build(), (
        "Stale. Run `uv run python ../scripts/export_workouts.py`."
    )


def test_there_is_one_workout_per_body_part():
    assert [t["name"] for t in workouts.TEMPLATES] == [
        "Chest", "Back", "Shoulders", "Legs", "Triceps", "Biceps",
    ]


def test_every_template_exercise_is_in_the_catalogue():
    known = {name for name, *_ in CATALOGUE}
    for template in workouts.TEMPLATES:
        for name, sets, reps_min, reps_max in template["exercises"]:
            assert name in known, f"{template['id']}: {name} is not in the catalogue"
            assert sets > 0 and 0 < reps_min < reps_max


def test_no_alias_belongs_to_two_exercises():
    owners: dict[str, str] = {}
    known = {n for n, *_ in CATALOGUE}
    assert set(ALIASES) <= known, f"aliases for unknown {set(ALIASES) - known}"
    for name in known:
        for alias in [name, *ALIASES.get(name, [])]:
            key = workouts.normalise(alias)
            assert owners.setdefault(key, name) == name, (
                f"{alias!r} means both {owners[key]} and {name}"
            )


def test_names_compare_without_case_spaces_or_punctuation():
    assert workouts.normalise("Pull-Up") == workouts.normalise("pull up") == "pullup"
    assert workouts.normalise("EZ-Bar Curl") == workouts.normalise("ez bar curl")


def test_starting_creates_missing_exercises_with_their_muscles(session):
    workouts.start(session, "back", TODAY)

    row = session.scalar(select(Exercise).where(Exercise.name == "Barbell Row"))
    assert row.category == "Back"
    assert sorted(row.primary_muscles) == ["lats", "upper_back"]


def test_starting_leaves_an_existing_exercise_alone(session):
    # Differently cased, with its own muscles: it came from an import.
    session.add(Exercise(name="back squat", category="Squats", primary_muscles=["quads"]))
    session.commit()

    workouts.start(session, "legs", TODAY)

    squats = session.scalars(
        select(Exercise).where(func.lower(Exercise.name) == "back squat")
    ).all()
    assert len(squats) == 1
    assert squats[0].category == "Squats" and squats[0].primary_muscles == ["quads"]


def test_an_alias_is_used_instead_of_creating_a_duplicate(session):
    imported = Exercise(name="Flat Barbell Bench Press", category="Chest")
    session.add(imported)
    session.flush()
    add_workout(session, TODAY - dt.timedelta(days=3), [(imported, 80, 8, False)])

    plan = workouts.start(session, "chest", TODAY)

    benches = session.scalars(
        select(Exercise.name).where(Exercise.name.ilike("%bench press"))
    ).all()
    assert "Bench Press" not in benches
    first = plan["entries"][0]
    assert first["planned"] == "Bench Press"
    assert first["exercise"] == "Flat Barbell Bench Press"
    assert first["exercise_id"] == imported.id
    assert first["last_weight_kg"] == 80


def test_where_several_names_exist_the_one_with_history_wins(session):
    # An earlier workout created "Bench Press"; the import brought the history.
    fresh = Exercise(name="Bench Press", category="Chest")
    imported = Exercise(name="Flat Barbell Bench Press", category="Chest")
    session.add_all([fresh, imported])
    session.flush()
    add_workout(session, TODAY - dt.timedelta(days=5), [(fresh, 60, 8, False)])
    add_workout(session, TODAY - dt.timedelta(days=3), [
        (imported, 80, 8, False), (imported, 80, 8, False),
    ])

    assert workouts.resolve(session, "Bench Press").id == imported.id


def test_with_no_history_the_templates_own_name_wins(session):
    session.add_all([
        Exercise(name="Barbell Bench Press", category="Chest"),
        Exercise(name="Bench Press", category="Chest"),
    ])
    session.commit()
    assert workouts.resolve(session, "Bench Press").name == "Bench Press"


def test_an_unknown_template_starts_nothing(session):
    assert workouts.start(session, "no-such-thing", TODAY) is None
    assert workouts.plan(session, TODAY) is None


@pytest.fixture
def started(session, exercises):
    workouts.start(session, "legs", TODAY)
    return session


def entry(plan: dict, name: str) -> dict:
    return next(e for e in plan["entries"] if e["planned"] == name)


def test_progress_counts_todays_working_sets(started, exercises):
    squat, bench = exercises["squat"], exercises["bench"]
    add_workout(started, TODAY - dt.timedelta(days=2), [(squat, 95, 5, False)])
    add_workout(started, TODAY, [
        (squat, 60, 5, True),     # warmup: not progress
        (squat, 100, 5, False),
        (squat, 100, 5, False),
        (bench, 70, 5, False),    # not in this plan
    ])

    plan = workouts.plan(started, TODAY)
    assert plan["template"]["id"] == "legs"
    assert entry(plan, "Back Squat")["done"] == 2
    assert entry(plan, "Leg Press")["done"] == 0


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
    assert entry(plan, "Leg Press")["last_weight_kg"] is None


def test_the_target_comes_from_the_last_session(started, exercises):
    squat = exercises["squat"]
    # Legs plans Back Squat 4 × 5–8. Last time: all four sets of 8 at 100.
    add_workout(started, TODAY - dt.timedelta(days=4), [(squat, 100, 8, False)] * 4)

    squat_row = entry(workouts.plan(started, TODAY), "Back Squat")
    assert (squat_row["advice"], squat_row["target_weight_kg"], squat_row["target_reps"]) == (
        "up", 105.0, 5,
    )
    assert squat_row["rest_s"] == 180
    assert (squat_row["reps_min"], squat_row["reps_max"]) == (5, 8)


def test_todays_sets_do_not_move_the_target(started, exercises):
    squat = exercises["squat"]
    add_workout(started, TODAY - dt.timedelta(days=4), [(squat, 100, 8, False)] * 4)
    add_workout(started, TODAY, [(squat, 105, 5, False)])
    assert entry(workouts.plan(started, TODAY), "Back Squat")["target_weight_kg"] == 105.0


def test_with_no_history_the_target_is_the_bottom_of_the_range(started):
    row = entry(workouts.plan(started, TODAY), "Leg Press")
    assert (row["advice"], row["target_weight_kg"], row["target_reps"]) == ("new", None, 8)


def test_a_plan_lasts_only_the_day_it_was_started(started):
    assert workouts.plan(started, TODAY) is not None
    assert workouts.plan(started, TODAY + dt.timedelta(days=1)) is None


def test_finishing_clears_the_plan(started):
    workouts.finish(started)
    assert workouts.plan(started, TODAY) is None


# --------------------------------------------------------------------------
# Merging duplicates
# --------------------------------------------------------------------------


def imported_workout(session, day, sets):
    """Like add_workout, but from an import rather than logged by hand."""
    workout = Workout(performed_on=day, source="fitnotes", external_id=str(day))
    session.add(workout)
    session.flush()
    for position, (exercise, weight, reps) in enumerate(sets, start=1):
        session.add(SetEntry(workout_id=workout.id, exercise_id=exercise.id,
                             position=position, weight_kg=weight, reps=reps, is_warmup=False))
    session.flush()


@pytest.fixture
def duplicated(session):
    # What an earlier workout could leave behind: "Bench Press", created with
    # the catalogue's muscles and used for two sets, beside the imported
    # "Flat Barbell Bench Press", which has one imported set and no muscles.
    fresh = Exercise(name="Bench Press", category="Chest", primary_muscles=["chest", "triceps"])
    imported = Exercise(name="Flat Barbell Bench Press", category=None)
    session.add_all([fresh, imported])
    session.flush()
    add_workout(session, TODAY, [(fresh, 80, 8, False), (fresh, 80, 8, False)])
    imported_workout(session, TODAY - dt.timedelta(days=3), [(imported, 77.5, 8)])
    session.commit()
    return fresh.id, imported.id


def test_duplicates_are_found_and_the_imported_one_is_kept(session, duplicated):
    fresh, imported = duplicated
    [merge] = workouts.duplicates(session)
    # Imported history wins even though the other has more sets.
    assert merge.keep.id == imported
    assert [c.id for c in merge.drop] == [fresh]


def test_merging_moves_the_sets_and_deletes_the_duplicate(session, duplicated):
    fresh, imported = duplicated
    merged = workouts.merge_duplicates(session)

    assert len(merged) == 1
    assert session.get(Exercise, fresh) is None
    kept = session.get(Exercise, imported)
    assert kept.name == "Flat Barbell Bench Press"
    assert session.scalar(
        select(func.count()).select_from(SetEntry).where(SetEntry.exercise_id == imported)
    ) == 3
    # It had no muscles or category of its own, so it takes the duplicate's.
    assert sorted(kept.primary_muscles) == ["chest", "triceps"]
    assert kept.category == "Chest"
    assert workouts.duplicates(session) == []


def test_the_kept_exercise_keeps_its_own_muscles(session):
    kept = Exercise(name="Barbell Squat", category="Legs", primary_muscles=["quads"])
    other = Exercise(name="Back Squat", category="Legs", primary_muscles=["quads", "glutes"])
    session.add_all([kept, other])
    session.flush()
    imported_workout(session, TODAY, [(kept, 100, 5)])
    session.commit()

    workouts.merge_duplicates(session)
    assert session.get(Exercise, kept.id).primary_muscles == ["quads"]


def test_names_that_only_look_alike_are_not_merged(session):
    session.add_all([Exercise(name="Bench Press"), Exercise(name="Incline Bench Press")])
    session.commit()
    assert workouts.duplicates(session) == []


def test_after_merging_the_plan_follows_the_kept_exercise(session, duplicated):
    _, imported = duplicated
    workouts.merge_duplicates(session)
    plan = workouts.start(session, "chest", TODAY)
    bench = plan["entries"][0]
    assert bench["exercise_id"] == imported
    assert bench["done"] == 2


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
    assert [t["id"] for t in listed] == ["chest", "back", "shoulders", "legs", "triceps", "biceps"]
    assert client.get("/api/templates/active").json() is None

    started = client.post("/api/templates/shoulders/start")
    assert started.status_code == 200
    plan = started.json()
    assert plan["template"]["name"] == "Shoulders"
    assert all(e["exercise_id"] is not None for e in plan["entries"])
    assert client.get("/api/templates/active").json()["template"]["id"] == "shoulders"

    assert client.delete("/api/templates/active").status_code == 204
    assert client.get("/api/templates/active").json() is None


def test_the_api_lists_and_merges_duplicates(client, duplicated):
    fresh, imported = duplicated
    listed = client.get("/api/exercises/duplicates").json()
    assert listed == [{
        "keep": {"id": imported, "name": "Flat Barbell Bench Press", "sets": 1},
        "drop": [{"id": fresh, "name": "Bench Press", "sets": 2}],
    }]
    assert client.post("/api/exercises/duplicates/merge").json()["merged"] == 1
    assert client.get("/api/exercises/duplicates").json() == []


def test_the_api_refuses_an_unknown_template(client):
    assert client.post("/api/templates/nope/start").status_code == 404

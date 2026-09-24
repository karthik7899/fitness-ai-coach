"""Starter workouts: a few plain, well-worn sessions to pick from on day one.

A template is a list of exercises with a target of sets and reps. Starting one
does not log anything; it makes sure its exercises exist, with the category
and muscles from the catalogue so the volume views can attribute them, and
marks it as today's plan. The Log screen then shows how far through it you
are and what weight you used last time.

The templates are generated into the Android app by
`scripts/export_workouts.py`, so both apps offer the same sessions.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import settings_store
from app.models import Exercise, SetEntry, Workout
from app.seed import CATALOGUE

# The settings key the active plan is kept under. The Android app uses the
# same one, so a restored backup carries it across.
ACTIVE = "workout"

# id, name, what it is for, [(exercise, sets, reps)]
TEMPLATES: list[dict] = [
    {
        "id": "full-body-a",
        "name": "Full body A",
        "about": "Squat, bench and row. Alternate with B, three days a week.",
        "exercises": [("Back Squat", 3, 5), ("Bench Press", 3, 5), ("Barbell Row", 3, 5)],
    },
    {
        "id": "full-body-b",
        "name": "Full body B",
        "about": "Squat, press and deadlift. Alternate with A.",
        "exercises": [("Back Squat", 3, 5), ("Overhead Press", 3, 5), ("Deadlift", 1, 5)],
    },
    {
        "id": "push",
        "name": "Push",
        "about": "Chest, shoulders and triceps.",
        "exercises": [
            ("Bench Press", 4, 8),
            ("Overhead Press", 3, 8),
            ("Incline Bench Press", 3, 10),
            ("Lateral Raise", 3, 12),
            ("Triceps Pushdown", 3, 12),
        ],
    },
    {
        "id": "pull",
        "name": "Pull",
        "about": "Back, rear delts and biceps.",
        "exercises": [
            ("Deadlift", 3, 5),
            ("Pull-Up", 3, 8),
            ("Barbell Row", 3, 8),
            ("Face Pull", 3, 15),
            ("Barbell Curl", 3, 12),
        ],
    },
    {
        "id": "legs",
        "name": "Legs",
        "about": "Quads, hamstrings, glutes and calves.",
        "exercises": [
            ("Back Squat", 4, 6),
            ("Romanian Deadlift", 3, 8),
            ("Leg Press", 3, 10),
            ("Walking Lunge", 3, 10),
            ("Calf Raise", 3, 15),
        ],
    },
    {
        "id": "no-equipment",
        "name": "No equipment",
        "about": "Bodyweight only, for home or travel.",
        "exercises": [
            ("Push-Up", 3, 12),
            ("Bodyweight Squat", 3, 15),
            ("Glute Bridge", 3, 15),
            ("Pike Push-Up", 3, 8),
            ("Back Extension", 3, 12),
        ],
    },
]

_CATALOGUE = {name.lower(): (name, category, modality, muscles)
              for name, category, modality, muscles in CATALOGUE}


def document() -> dict:
    """The templates, and the catalogue entries they use, as plain data."""
    used = {name for t in TEMPLATES for name, _, _ in t["exercises"]}
    return {
        "catalogue": [
            {"name": name, "category": category, "modality": modality, "muscles": muscles}
            for name, category, modality, muscles in CATALOGUE
            if name in used
        ],
        "templates": [
            {
                "id": t["id"],
                "name": t["name"],
                "about": t["about"],
                "exercises": [
                    {"exercise": name, "sets": sets, "reps": reps}
                    for name, sets, reps in t["exercises"]
                ],
            }
            for t in TEMPLATES
        ],
    }


def template(template_id: str) -> dict | None:
    return next((t for t in document()["templates"] if t["id"] == template_id), None)


def _find(session: Session, name: str) -> Exercise | None:
    return session.scalar(select(Exercise).where(func.lower(Exercise.name) == name.lower()))


def ensure_exercises(session: Session, chosen: dict) -> None:
    """Create any of the template's exercises that do not exist yet.

    An existing exercise is left exactly as it is, even if its muscles differ
    from the catalogue's: it may have come from an import, and history already
    hangs off it.
    """
    for entry in chosen["exercises"]:
        if _find(session, entry["exercise"]) is not None:
            continue
        name, category, modality, muscles = _CATALOGUE[entry["exercise"].lower()]
        session.add(
            Exercise(name=name, category=category, modality=modality, primary_muscles=muscles)
        )
    session.commit()


def start(session: Session, template_id: str, day: dt.date) -> dict | None:
    chosen = template(template_id)
    if chosen is None:
        return None
    ensure_exercises(session, chosen)
    settings_store.put(session, ACTIVE, {"template": template_id, "day": day.isoformat()})
    return plan(session, day)


def finish(session: Session) -> None:
    settings_store.delete(session, ACTIVE)


def plan(session: Session, day: dt.date) -> dict | None:
    """Today's plan, if one was started today, with progress through it.

    `done` counts working sets of the exercise logged on the day, from any
    workout — logging it by hand or through the coach counts too. `last_weight_kg`
    is the most recent working weight, including today's, so the next set
    starts where the last one left off.
    """
    active = settings_store.get(session, ACTIVE) or {}
    if active.get("day") != day.isoformat():
        return None
    chosen = template(active.get("template", ""))
    if chosen is None:
        return None

    entries = []
    for entry in chosen["exercises"]:
        exercise = _find(session, entry["exercise"])
        done, last = 0, None
        if exercise is not None:
            done = session.scalar(
                select(func.count())
                .select_from(SetEntry)
                .join(Workout, Workout.id == SetEntry.workout_id)
                .where(
                    SetEntry.exercise_id == exercise.id,
                    SetEntry.is_warmup.is_(False),
                    Workout.performed_on == day,
                )
            ) or 0
            last = session.scalar(
                select(SetEntry.weight_kg)
                .join(Workout, Workout.id == SetEntry.workout_id)
                .where(
                    SetEntry.exercise_id == exercise.id,
                    SetEntry.is_warmup.is_(False),
                    SetEntry.weight_kg.is_not(None),
                )
                .order_by(Workout.performed_on.desc(), SetEntry.id.desc())
                .limit(1)
            )
        entries.append(
            {
                "exercise": entry["exercise"],
                "exercise_id": exercise.id if exercise is not None else None,
                "sets": entry["sets"],
                "reps": entry["reps"],
                "done": done,
                "last_weight_kg": float(last) if last is not None else None,
            }
        )
    return {"template": chosen, "day": day.isoformat(), "entries": entries}

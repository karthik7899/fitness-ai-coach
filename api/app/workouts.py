"""Starter workouts: one plain session per body part, to pick from on day one.

A template is a list of exercises with a target of sets and reps. Starting one
does not log anything; it makes sure its exercises exist, with the category
and muscles from the catalogue so the volume views can attribute them, and
marks it as today's plan. The Log screen then shows how far through it you
are and what weight you used last time.

Exercises are matched by name and by alias (`app.seed.ALIASES`), so a
template's "Bench Press" is the "Flat Barbell Bench Press" an imported FitNotes
history already has, and its history carries on.

The templates are generated into the Android app by
`scripts/export_workouts.py`, so both apps offer the same sessions.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from sqlalchemy import and_, case, func, select, text
from sqlalchemy.orm import Session

from app import settings_store
from app.models import Exercise, SetEntry, Workout
from app.seed import ALIASES, CATALOGUE

# The settings key the active plan is kept under. The Android app uses the
# same one, so a restored backup carries it across.
ACTIVE = "workout"

# One session per body part. id, name, what it is for, [(exercise, sets, reps)]
TEMPLATES: list[dict] = [
    {
        "id": "chest",
        "name": "Chest",
        "about": "Flat and incline pressing, then fly and dips.",
        "exercises": [
            ("Bench Press", 4, 8),
            ("Incline Bench Press", 3, 10),
            ("Dumbbell Press", 3, 10),
            ("Chest Fly", 3, 12),
            ("Dip", 3, 10),
        ],
    },
    {
        "id": "back",
        "name": "Back",
        "about": "A hinge, a vertical pull and two rows.",
        "exercises": [
            ("Deadlift", 3, 5),
            ("Pull-Up", 3, 8),
            ("Barbell Row", 3, 8),
            ("Lat Pulldown", 3, 10),
            ("Seated Cable Row", 3, 12),
        ],
    },
    {
        "id": "shoulders",
        "name": "Shoulders",
        "about": "Pressing, then front, side and rear delts.",
        "exercises": [
            ("Overhead Press", 4, 8),
            ("Dumbbell Shoulder Press", 3, 10),
            ("Lateral Raise", 3, 12),
            ("Rear Delt Fly", 3, 15),
            ("Face Pull", 3, 15),
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
            ("Leg Curl", 3, 12),
            ("Calf Raise", 3, 15),
        ],
    },
    {
        "id": "triceps",
        "name": "Triceps",
        "about": "A heavy compound, then all three heads.",
        "exercises": [
            ("Close-Grip Bench Press", 3, 8),
            ("Dip", 3, 10),
            ("Skull Crusher", 3, 10),
            ("Triceps Pushdown", 3, 12),
            ("Overhead Triceps Extension", 3, 12),
        ],
    },
    {
        "id": "biceps",
        "name": "Biceps",
        "about": "Chin-ups, then curls in three grips.",
        "exercises": [
            ("Chin-Up", 3, 8),
            ("Barbell Curl", 3, 10),
            ("Dumbbell Curl", 3, 12),
            ("Hammer Curl", 3, 12),
            ("Preacher Curl", 3, 12),
        ],
    },
]

_CATALOGUE = {name.lower(): (name, category, modality, muscles)
              for name, category, modality, muscles in CATALOGUE}

_NOT_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def normalise(name: str) -> str:
    """The form names are compared in: "Pull-Up", "pull up" and "Pullup" agree.

    The Android app normalises the same way, and WorkoutsTest.kt pins it.
    """
    return _NOT_ALPHANUMERIC.sub("", name.lower())


def names_for(exercise: str) -> list[str]:
    """The template's name for an exercise, then its aliases, in preference order."""
    return [exercise, *ALIASES.get(exercise, [])]


def document() -> dict:
    """The templates and the whole catalogue, aliases included, as plain data.

    The whole catalogue rather than only what the templates use: finding
    duplicates needs every exercise's aliases.
    """
    return {
        "catalogue": [
            {
                "name": name,
                "category": category,
                "modality": modality,
                "muscles": muscles,
                "aliases": ALIASES.get(name, []),
            }
            for name, category, modality, muscles in CATALOGUE
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


@dataclass(frozen=True)
class Candidate:
    """An existing exercise, with what counts when choosing between names."""

    id: int
    name: str
    sets: int
    imported: int
    rank: int

    @property
    def key(self) -> tuple:
        # Imported history first, then the most working sets, then the
        # earlier name in the alias list, then the older row.
        return (self.imported > 0, self.sets, -self.rank, -self.id)


def _existing(session: Session) -> list[tuple[int, str, int, int]]:
    """Every exercise with its working sets, and how many of them were imported."""
    return [
        (row.id, row.name, row.sets, row.imported)
        for row in session.execute(
            select(
                Exercise.id,
                Exercise.name,
                func.count(SetEntry.id).label("sets"),
                func.count(case((Workout.source != "manual", SetEntry.id))).label("imported"),
            )
            .outerjoin(
                SetEntry,
                and_(SetEntry.exercise_id == Exercise.id, SetEntry.is_warmup.is_(False)),
            )
            .outerjoin(Workout, Workout.id == SetEntry.workout_id)
            .group_by(Exercise.id, Exercise.name)
        )
    ]


def _candidates(existing: list[tuple[int, str, int, int]], exercise: str) -> list[Candidate]:
    """The existing exercises that go by this catalogue exercise's names, best first."""
    rank: dict[str, int] = {}
    for i, name in enumerate(names_for(exercise)):
        rank.setdefault(normalise(name), i)
    found = [
        Candidate(id_, name, sets, imported, rank[normalise(name)])
        for id_, name, sets, imported in existing
        if normalise(name) in rank
    ]
    return sorted(found, key=lambda c: c.key, reverse=True)


def resolve(session: Session, exercise: str) -> Exercise | None:
    """The existing exercise a template's exercise means, if there is one.

    Any exercise whose name matches the template's name or one of its aliases
    counts. When several do, as when an earlier workout created "Bench Press"
    beside an imported "Flat Barbell Bench Press", the imported one wins, then
    the one with the most working sets, since that is where the history is.
    """
    found = _candidates(_existing(session), exercise)
    return session.get(Exercise, found[0].id) if found else None


@dataclass(frozen=True)
class Merge:
    keep: Candidate
    drop: list[Candidate]

    def as_dict(self) -> dict:
        def one(c: Candidate) -> dict:
            return {"id": c.id, "name": c.name, "sets": c.sets}

        return {"keep": one(self.keep), "drop": [one(c) for c in self.drop]}


def duplicates(session: Session) -> list[Merge]:
    """Catalogue exercises that exist under more than one of their names."""
    existing = _existing(session)
    merges, claimed = [], set()
    for name, *_ in CATALOGUE:
        found = [c for c in _candidates(existing, name) if c.id not in claimed]
        if len(found) > 1:
            merges.append(Merge(found[0], found[1:]))
            claimed.update(c.id for c in found)
    return merges


def merge_duplicates(session: Session) -> list[Merge]:
    """Fold each duplicate into the exercise `duplicates` chose to keep.

    Its sets move across and it is deleted. The kept exercise keeps its own
    name, category and muscles, taking the duplicate's only where it has none,
    so an import that brought no muscle mapping gains the catalogue's. One
    transaction: a failure part-way leaves everything as it was.
    """
    merges = duplicates(session)
    for merge in merges:
        keep = merge.keep.id
        for drop in (c.id for c in merge.drop):
            params = {"keep": keep, "drop": drop}
            session.execute(
                text("UPDATE sets SET exercise_id = :keep WHERE exercise_id = :drop"), params
            )
            session.execute(
                text(
                    """
                    INSERT INTO exercise_muscles (exercise_id, muscle, is_primary)
                    SELECT :keep, muscle, is_primary FROM exercise_muscles
                    WHERE exercise_id = :drop
                      AND NOT EXISTS (SELECT 1 FROM exercise_muscles WHERE exercise_id = :keep)
                    """
                ),
                params,
            )
            session.execute(
                text(
                    """
                    UPDATE exercises
                    SET category = (SELECT category FROM exercises WHERE id = :drop)
                    WHERE id = :keep AND category IS NULL
                    """
                ),
                params,
            )
            session.execute(text("DELETE FROM exercise_muscles WHERE exercise_id = :drop"), params)
            session.execute(text("DELETE FROM exercises WHERE id = :drop"), params)
    session.commit()
    session.expire_all()
    return merges


def ensure_exercises(session: Session, chosen: dict) -> None:
    """Create the template's exercises that exist under none of their names.

    An existing exercise is left exactly as it is, even if its muscles differ
    from the catalogue's: it may have come from an import, and history already
    hangs off it.
    """
    for entry in chosen["exercises"]:
        if resolve(session, entry["exercise"]) is not None:
            continue
        name, category, modality, muscles = _CATALOGUE[entry["exercise"].lower()]
        session.add(
            Exercise(name=name, category=category, modality=modality, primary_muscles=muscles)
        )
        session.flush()
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

    Each entry names the exercise as it exists in the database, which may be
    an alias of the template's name; `planned` keeps the template's. `done`
    counts working sets of it logged on the day, from any workout — logging
    it by hand or through the coach counts too. `last_weight_kg` is the most
    recent working weight, including today's, so the next set starts where
    the last one left off.
    """
    active = settings_store.get(session, ACTIVE) or {}
    if active.get("day") != day.isoformat():
        return None
    chosen = template(active.get("template", ""))
    if chosen is None:
        return None

    entries = []
    for entry in chosen["exercises"]:
        exercise = resolve(session, entry["exercise"])
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
                "exercise": exercise.name if exercise is not None else entry["exercise"],
                "planned": entry["exercise"],
                "exercise_id": exercise.id if exercise is not None else None,
                "sets": entry["sets"],
                "reps": entry["reps"],
                "done": done,
                "last_weight_kg": float(last) if last is not None else None,
            }
        )
    return {"template": chosen, "day": day.isoformat(), "entries": entries}

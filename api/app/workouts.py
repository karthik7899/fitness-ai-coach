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

from app import progression, settings_store
from app.models import Exercise, SetEntry, Workout
from app.seed import ALIASES, CATALOGUE

# The settings key the active plan is kept under. The Android app uses the
# same one, so a restored backup carries it across.
ACTIVE = "workout"

# One session per body part.
# id, name, what it is for, [(exercise, sets, reps_min, reps_max)]
TEMPLATES: list[dict] = [
    {
        "id": "chest",
        "name": "Chest",
        "about": "Flat and incline pressing, then fly and dips.",
        "exercises": [
            ("Bench Press", 4, 6, 10),
            ("Incline Bench Press", 3, 8, 12),
            ("Dumbbell Press", 3, 8, 12),
            ("Chest Fly", 3, 10, 15),
            ("Dip", 3, 8, 12),
        ],
    },
    {
        "id": "back",
        "name": "Back",
        "about": "A hinge, a vertical pull and two rows.",
        "exercises": [
            ("Deadlift", 3, 4, 6),
            ("Pull-Up", 3, 6, 10),
            ("Barbell Row", 3, 6, 10),
            ("Lat Pulldown", 3, 8, 12),
            ("Seated Cable Row", 3, 10, 15),
        ],
    },
    {
        "id": "shoulders",
        "name": "Shoulders",
        "about": "Pressing, then front, side and rear delts.",
        "exercises": [
            ("Overhead Press", 4, 6, 10),
            ("Dumbbell Shoulder Press", 3, 8, 12),
            ("Lateral Raise", 3, 12, 15),
            ("Rear Delt Fly", 3, 12, 15),
            ("Face Pull", 3, 12, 15),
        ],
    },
    {
        "id": "legs",
        "name": "Legs",
        "about": "Quads, hamstrings, glutes and calves.",
        "exercises": [
            ("Back Squat", 4, 5, 8),
            ("Romanian Deadlift", 3, 6, 10),
            ("Leg Press", 3, 8, 12),
            ("Leg Curl", 3, 10, 15),
            ("Calf Raise", 3, 10, 15),
        ],
    },
    {
        "id": "triceps",
        "name": "Triceps",
        "about": "A heavy compound, then all three heads.",
        "exercises": [
            ("Close-Grip Bench Press", 3, 6, 10),
            ("Dip", 3, 8, 12),
            ("Skull Crusher", 3, 8, 12),
            ("Triceps Pushdown", 3, 10, 15),
            ("Overhead Triceps Extension", 3, 10, 15),
        ],
    },
    {
        "id": "biceps",
        "name": "Biceps",
        "about": "Chin-ups, then curls in three grips.",
        "exercises": [
            ("Chin-Up", 3, 6, 10),
            ("Barbell Curl", 3, 8, 12),
            ("Dumbbell Curl", 3, 10, 15),
            ("Hammer Curl", 3, 10, 15),
            ("Preacher Curl", 3, 10, 15),
        ],
    },
]

_CATALOGUE = {name.lower(): (name, category, modality, muscles)
              for name, category, modality, muscles in CATALOGUE}

# How much to add when a range is beaten, and how long to rest between sets.
# Big lower-body lifts move in bigger steps and need longer; small muscles
# move in small steps and recover quicker. Everything else sits between.
HEAVY = {"Back Squat", "Front Squat", "Deadlift", "Romanian Deadlift", "Leg Press", "Hip Thrust"}
ISOLATION = {
    "Leg Curl", "Leg Extension", "Calf Raise", "Chest Fly", "Lateral Raise", "Rear Delt Fly",
    "Face Pull", "Barbell Curl", "Dumbbell Curl", "Hammer Curl", "Preacher Curl",
    "Triceps Pushdown", "Skull Crusher", "Overhead Triceps Extension", "Cable Crunch",
}


def loading(name: str) -> tuple[float, int]:
    """(weight step in kg, rest between sets in seconds) for a catalogue exercise."""
    if name in HEAVY:
        return 5.0, 180
    if name in ISOLATION:
        return 1.0, 75
    return 2.5, 120


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
                "increment_kg": loading(name)[0],
                "rest_s": loading(name)[1],
            }
            for name, category, modality, muscles in CATALOGUE
        ],
        "templates": [
            {
                "id": t["id"],
                "name": t["name"],
                "about": t["about"],
                "exercises": [
                    {"exercise": name, "sets": sets, "reps_min": lo, "reps_max": hi}
                    for name, sets, lo, hi in t["exercises"]
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


def _previous_session(
    session: Session, exercise_id: int, day: dt.date
) -> list[tuple[float | None, int | None, float | None]]:
    """(weight, reps, rpe) of each working set on the last day before `day`."""
    last_day = session.scalar(
        select(func.max(Workout.performed_on))
        .join(SetEntry, SetEntry.workout_id == Workout.id)
        .where(
            SetEntry.exercise_id == exercise_id,
            SetEntry.is_warmup.is_(False),
            Workout.performed_on < day,
        )
    )
    if last_day is None:
        return []
    rows = session.execute(
        select(SetEntry.weight_kg, SetEntry.reps, SetEntry.rpe)
        .join(Workout, Workout.id == SetEntry.workout_id)
        .where(
            SetEntry.exercise_id == exercise_id,
            SetEntry.is_warmup.is_(False),
            Workout.performed_on == last_day,
        )
        .order_by(Workout.id, SetEntry.position, SetEntry.id)
    ).all()
    return [
        (
            float(w) if w is not None else None,
            r,
            float(rpe) if rpe is not None else None,
        )
        for w, r, rpe in rows
    ]


def plan(session: Session, day: dt.date) -> dict | None:
    """Today's plan, if one was started today, with progress and targets.

    Each entry names the exercise as it exists in the database, which may be
    an alias of the template's name; `planned` keeps the template's. `done`
    counts working sets of it logged on the day, from any workout — logging
    it by hand or through the coach counts too. The target comes from
    `progression.suggest` over the last session before today, so it holds
    steady through today's sets. `last_weight_kg` is the most recent working
    weight, today's included.
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
        increment, rest = loading(entry["exercise"])
        done, last, previous = 0, None, []
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
            previous = _previous_session(session, exercise.id, day)
        target = progression.suggest(
            previous, entry["sets"], entry["reps_min"], entry["reps_max"], increment
        )
        entries.append(
            {
                "exercise": exercise.name if exercise is not None else entry["exercise"],
                "planned": entry["exercise"],
                "exercise_id": exercise.id if exercise is not None else None,
                "sets": entry["sets"],
                "reps_min": entry["reps_min"],
                "reps_max": entry["reps_max"],
                "done": done,
                "last_weight_kg": float(last) if last is not None else None,
                "advice": target.advice,
                "target_weight_kg": target.weight,
                "target_reps": target.reps,
                "rest_s": rest,
            }
        )
    return {"template": chosen, "day": day.isoformat(), "entries": entries}

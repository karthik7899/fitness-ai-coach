"""Working sets per muscle over the last seven days, against a weekly target.

Sets are attributed as v_weekly_muscle_volume attributes them: one set counts
for each of its exercise's primary muscles, falling back to the category when
an exercise has none. A rolling seven days rather than the calendar week, so a
Monday does not read as every muscle under target.

The target is the common landmark of about 10–20 hard sets a muscle a week.
It and the muscles always listed are exported with the starter workouts, so
the Android tile reads the same numbers; the query below is the same text in
both apps.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import text
from sqlalchemy.orm import Session

TARGET_MIN = 10
TARGET_MAX = 20

# Listed even at zero, since a muscle not trained at all is the thing to see.
MAJOR = [
    "chest", "lats", "upper_back", "front_delts", "side_delts", "rear_delts",
    "biceps", "triceps", "quads", "hamstrings", "glutes", "calves",
]

QUERY = """
    SELECT COALESCE(m.muscle, v.category, 'Uncategorised') AS muscle,
           COUNT(*) AS sets
    FROM v_sets_enriched v
    LEFT JOIN exercise_muscles m
           ON m.exercise_id = v.exercise_id AND m.is_primary
    WHERE NOT v.is_warmup AND v.performed_on BETWEEN :start AND :end
    GROUP BY COALESCE(m.muscle, v.category, 'Uncategorised')
"""


def status(sets: int) -> str:
    if sets < TARGET_MIN:
        return "under"
    if sets > TARGET_MAX:
        return "over"
    return "on_target"


def label(muscle: str) -> str:
    return muscle.replace("_", " ").capitalize()


def document() -> dict:
    return {"min": TARGET_MIN, "max": TARGET_MAX, "major": MAJOR}


def last_seven_days(session: Session, today: dt.date) -> list[dict]:
    """Each major muscle, and any other trained, with its sets and status.

    Major muscles come first in their fixed order, then the others by sets.
    """
    counted = {
        row.muscle: row.sets
        for row in session.execute(
            text(QUERY),
            {"start": (today - dt.timedelta(days=6)).isoformat(), "end": today.isoformat()},
        )
    }
    others = sorted((m for m in counted if m not in MAJOR), key=lambda m: (-counted[m], m))
    return [
        {"muscle": m, "label": label(m), "sets": counted.get(m, 0),
         "status": status(counted.get(m, 0))}
        for m in [*MAJOR, *others]
    ]

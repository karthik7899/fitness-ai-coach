"""The coach's tool surface.

Every number the coach quotes comes from one of these handlers, which read the
SQL views in `alembic/versions/0002_metrics_views.py`. The model is never asked
to aggregate or compute — only to interpret.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CoachNote, Exercise, SetEntry, Workout
from app.queries import rows as _rows

MAX_ROWS = 400


def _find_exercise(session: Session, name: str) -> Exercise | None:
    return session.scalar(select(Exercise).where(func.lower(Exercise.name) == name.strip().lower()))


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------


def get_daily_metrics(
    session: Session, start_date: str, end_date: str, metrics: list[str] | None = None
) -> dict:
    sql = """
        SELECT date, metric, value, unit, source
        FROM v_daily_metrics_preferred
        WHERE date BETWEEN :start AND :end
          AND (:all_metrics OR metric = ANY(:metrics))
        ORDER BY date DESC, metric
        LIMIT :limit
    """
    rows = _rows(
        session,
        sql,
        start=start_date,
        end=end_date,
        all_metrics=not metrics,
        metrics=metrics or [],
        limit=MAX_ROWS,
    )
    return {"rows": rows, "count": len(rows)}


def get_training_load(session: Session, start_date: str, end_date: str) -> dict:
    sql = """
        SELECT date, strength_tonnes, cardio_minutes, cardio_km,
               load_au, acute_7d, chronic_28d, acwr
        FROM v_training_load
        WHERE date BETWEEN :start AND :end
        ORDER BY date DESC
        LIMIT :limit
    """
    rows = _rows(session, sql, start=start_date, end=end_date, limit=MAX_ROWS)
    return {
        "rows": rows,
        "count": len(rows),
        "note": (
            "load_au = strength tonnes + cardio minutes / 10. ACWR is the 7-day mean "
            "over the 28-day mean; roughly 0.8-1.3 is a steady build, above ~1.5 is a "
            "sharp spike in load relative to recent history."
        ),
    }


def get_exercise_history(session: Session, exercise: str, limit: int = 30) -> dict:
    match = _find_exercise(session, exercise)
    if match is None:
        available = session.scalars(
            select(Exercise.name).where(Exercise.name.ilike(f"%{exercise.strip()}%")).limit(10)
        ).all()
        return {
            "error": f"No exercise named {exercise!r}.",
            "did_you_mean": list(available),
        }

    sql = """
        SELECT date, best_e1rm_kg, top_weight_kg, volume_kg, working_sets
        FROM v_exercise_e1rm_daily
        WHERE exercise_id = :exercise_id
        ORDER BY date DESC
        LIMIT :limit
    """
    rows = _rows(session, sql, exercise_id=match.id, limit=min(limit, MAX_ROWS))
    return {"exercise": match.name, "sessions": rows, "count": len(rows)}


def get_volume_summary(
    session: Session, start_date: str, end_date: str, group_by: str = "muscle"
) -> dict:
    if group_by == "muscle":
        sql = """
            SELECT muscle, SUM(volume_kg) AS volume_kg, SUM(working_sets) AS working_sets
            FROM v_weekly_muscle_volume
            WHERE week_start BETWEEN :start AND :end
            GROUP BY muscle ORDER BY volume_kg DESC
        """
    elif group_by == "week":
        sql = """
            SELECT week_start, SUM(volume_kg) AS volume_kg, SUM(working_sets) AS working_sets
            FROM v_weekly_muscle_volume
            WHERE week_start BETWEEN :start AND :end
            GROUP BY week_start ORDER BY week_start DESC
        """
    elif group_by == "exercise":
        sql = """
            SELECT exercise, SUM(volume_kg) AS volume_kg, SUM(working_sets) AS working_sets,
                   MAX(best_e1rm_kg) AS best_e1rm_kg
            FROM v_exercise_e1rm_daily
            WHERE date BETWEEN :start AND :end
            GROUP BY exercise ORDER BY volume_kg DESC
        """
    elif group_by == "day":
        sql = """
            SELECT date, volume_kg, working_sets, exercises
            FROM v_daily_volume
            WHERE date BETWEEN :start AND :end
            ORDER BY date DESC
        """
    else:
        return {"error": f"Unknown group_by {group_by!r}."}

    rows = _rows(session, sql, start=start_date, end=end_date)
    return {"group_by": group_by, "rows": rows[:MAX_ROWS], "count": len(rows)}


def get_recent_activities(
    session: Session,
    limit: int = 20,
    sport_type: str | None = None,
    since: str | None = None,
) -> dict:
    sql = """
        SELECT external_id, sport_type, name, started_at, distance_m, moving_time_s,
               elevation_gain_m, average_hr, max_hr, calories,
               CASE WHEN distance_m > 0 AND moving_time_s > 0
                    THEN ROUND(((moving_time_s / 60.0) / (distance_m / 1000.0))::numeric, 2)
               END AS pace_min_per_km
        FROM activities
        WHERE (:sport_type IS NULL OR sport_type = :sport_type)
          AND (:since IS NULL OR started_at >= :since::timestamptz)
        ORDER BY started_at DESC
        LIMIT :limit
    """
    rows = _rows(
        session, sql, sport_type=sport_type, since=since, limit=min(limit, MAX_ROWS)
    )
    return {"rows": rows, "count": len(rows)}


def get_workout(session: Session, performed_on: str) -> dict:
    sql = """
        SELECT exercise, category, reps, weight_kg, rpe, is_warmup, volume_kg, e1rm_kg
        FROM v_sets_enriched
        WHERE performed_on = :date
        ORDER BY exercise, id
    """
    rows = _rows(session, sql, date=performed_on)
    notes = session.scalar(
        select(Workout.notes).where(Workout.performed_on == dt.date.fromisoformat(performed_on))
    )
    return {"date": performed_on, "sets": rows, "count": len(rows), "notes": notes}


def list_exercises(session: Session, search: str | None = None) -> dict:
    stmt = select(Exercise.name, Exercise.category, Exercise.modality).where(
        Exercise.is_archived.is_(False)
    )
    if search:
        stmt = stmt.where(Exercise.name.ilike(f"%{search.strip()}%"))
    rows = session.execute(stmt.order_by(Exercise.name).limit(MAX_ROWS)).mappings().all()
    return {"exercises": [dict(r) for r in rows]}


def log_set(
    session: Session,
    exercise: str,
    reps: int | None = None,
    weight_kg: float | None = None,
    performed_on: str | None = None,
    rpe: float | None = None,
    is_warmup: bool = False,
) -> dict:
    day = dt.date.fromisoformat(performed_on) if performed_on else dt.date.today()

    match = _find_exercise(session, exercise)
    if match is None:
        match = Exercise(name=exercise.strip(), modality="weight_reps")
        session.add(match)
        session.flush()

    workout = session.scalar(
        select(Workout).where(Workout.performed_on == day, Workout.source == "manual")
    )
    if workout is None:
        workout = Workout(performed_on=day, source="manual")
        session.add(workout)
        session.flush()

    next_position = (
        session.scalar(
            select(func.coalesce(func.max(SetEntry.position), 0)).where(
                SetEntry.workout_id == workout.id
            )
        )
        or 0
    ) + 1

    entry = SetEntry(
        workout_id=workout.id,
        exercise_id=match.id,
        position=next_position,
        reps=reps,
        weight_kg=Decimal(str(weight_kg)) if weight_kg is not None else None,
        rpe=Decimal(str(rpe)) if rpe is not None else None,
        is_warmup=is_warmup,
    )
    session.add(entry)
    session.commit()

    return {
        "logged": True,
        "set_id": entry.id,
        "exercise": match.name,
        "date": day.isoformat(),
        "reps": reps,
        "weight_kg": weight_kg,
        "position": next_position,
    }


def remember(session: Session, kind: str, content: str) -> dict:
    note = CoachNote(kind=kind, content=content.strip())
    session.add(note)
    session.commit()
    return {"saved": True, "id": note.id, "kind": kind, "content": note.content}


# --------------------------------------------------------------------------
# Tool schemas
# --------------------------------------------------------------------------

_DATE = {"type": "string", "description": "ISO date, YYYY-MM-DD."}

TOOL_SPECS: list[dict] = [
    {
        "name": "get_daily_metrics",
        "description": (
            "Daily wellness telemetry from the watch: steps, sleep_minutes, resting_hr, "
            "hrv_ms, active_minutes, body_weight_kg. Use for questions about sleep, "
            "recovery, step load, or bodyweight trends."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": _DATE,
                "end_date": _DATE,
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "steps",
                            "sleep_minutes",
                            "resting_hr",
                            "hrv_ms",
                            "active_minutes",
                            "body_weight_kg",
                        ],
                    },
                    "description": "Omit to return every metric.",
                },
            },
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "get_training_load",
        "description": (
            "Daily training load with acute (7d) and chronic (28d) averages and their "
            "ratio (ACWR). Use for readiness, overreaching, tapering, and 'am I doing "
            "too much' questions."
        ),
        "parameters": {
            "type": "object",
            "properties": {"start_date": _DATE, "end_date": _DATE},
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "get_exercise_history",
        "description": (
            "Per-session history for one lift: best estimated 1RM, top weight, volume "
            "and working sets by date. Use for strength progression questions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "exercise": {"type": "string", "description": "Exercise name, e.g. 'Back Squat'."},
                "limit": {"type": "integer", "description": "Max sessions, newest first."},
            },
            "required": ["exercise"],
        },
    },
    {
        "name": "get_volume_summary",
        "description": (
            "Aggregated training volume and working sets over a range, grouped by muscle, "
            "exercise, week or day. Use for balance, weak-point and weekly-tonnage questions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": _DATE,
                "end_date": _DATE,
                "group_by": {"type": "string", "enum": ["muscle", "exercise", "week", "day"]},
            },
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "get_recent_activities",
        "description": (
            "Cardio activities from Strava with distance, moving time, heart rate and "
            "computed pace in min/km. Use for running, cycling and pacing questions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer"},
                "sport_type": {"type": "string", "description": "e.g. 'Run', 'Ride'."},
                "since": _DATE,
            },
        },
    },
    {
        "name": "get_workout",
        "description": "Every set performed on one date, with volume and estimated 1RM.",
        "parameters": {
            "type": "object",
            "properties": {"performed_on": _DATE},
            "required": ["performed_on"],
        },
    },
    {
        "name": "list_exercises",
        "description": (
            "The exercise catalogue, optionally filtered. Use to resolve a name before "
            "logging a set, or to check what the athlete actually trains."
        ),
        "parameters": {
            "type": "object",
            "properties": {"search": {"type": "string"}},
        },
    },
    {
        "name": "log_set",
        "description": (
            "Record one completed set. Creates the day's workout and the exercise if "
            "they do not exist. Weight is kilograms. Only call this when the athlete "
            "states they actually performed the set."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "exercise": {"type": "string"},
                "reps": {"type": "integer"},
                "weight_kg": {"type": "number"},
                "performed_on": {**_DATE, "description": "ISO date; defaults to today."},
                "rpe": {"type": "number", "description": "Rate of perceived exertion, 1-10."},
                "is_warmup": {"type": "boolean"},
            },
            "required": ["exercise"],
        },
    },
    {
        "name": "remember",
        "description": (
            "Save a durable fact about the athlete that should inform future coaching: "
            "an injury, a goal, a schedule constraint, a training block, or a preference. "
            "These are loaded into every future conversation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["injury", "goal", "preference", "block", "constraint"],
                },
                "content": {"type": "string"},
            },
            "required": ["kind", "content"],
        },
    },
]

HANDLERS = {
    "get_daily_metrics": get_daily_metrics,
    "get_training_load": get_training_load,
    "get_exercise_history": get_exercise_history,
    "get_volume_summary": get_volume_summary,
    "get_recent_activities": get_recent_activities,
    "get_workout": get_workout,
    "list_exercises": list_exercises,
    "log_set": log_set,
    "remember": remember,
}

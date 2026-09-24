from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import muscles
from app.db import get_session
from app.queries import rows as _rows

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _default_range(
    start: dt.date | None, end: dt.date | None, days: int
) -> tuple[dt.date, dt.date]:
    end = end or dt.date.today()
    start = start or end - dt.timedelta(days=days)
    return start, end


@router.get("/daily")
def daily_metrics(
    start: dt.date | None = None,
    end: dt.date | None = None,
    session: Session = Depends(get_session),
):
    start, end = _default_range(start, end, 30)
    return _rows(
        session,
        """
        SELECT date, metric, value, unit, source
        FROM v_daily_metrics_preferred
        WHERE date BETWEEN :start AND :end
        ORDER BY date DESC, metric
        """,
        start=start,
        end=end,
    )


@router.get("/load")
def training_load(
    start: dt.date | None = None,
    end: dt.date | None = None,
    session: Session = Depends(get_session),
):
    start, end = _default_range(start, end, 90)
    return _rows(
        session,
        """
        SELECT date, strength_tonnes, cardio_minutes, cardio_km, load_au,
               acute_7d, chronic_28d, acwr
        FROM v_training_load
        WHERE date BETWEEN :start AND :end
        ORDER BY date
        """,
        start=start,
        end=end,
    )


@router.get("/volume")
def volume(
    start: dt.date | None = None,
    end: dt.date | None = None,
    session: Session = Depends(get_session),
):
    start, end = _default_range(start, end, 90)
    return {
        "by_muscle": _rows(
            session,
            """
            SELECT muscle, SUM(volume_kg) AS volume_kg, SUM(working_sets) AS working_sets
            FROM v_weekly_muscle_volume
            WHERE week_start BETWEEN :start AND :end
            GROUP BY muscle ORDER BY volume_kg DESC
            """,
            start=start,
            end=end,
        ),
        "by_day": _rows(
            session,
            """
            SELECT date, volume_kg, working_sets, exercises
            FROM v_daily_volume
            WHERE date BETWEEN :start AND :end
            ORDER BY date
            """,
            start=start,
            end=end,
        ),
    }


@router.get("/exercises")
def exercises_with_history(session: Session = Depends(get_session)):
    """Exercises that actually have logged sets, heaviest-trained first."""
    return _rows(
        session,
        """
        SELECT exercise, SUM(volume_kg) AS volume_kg, COUNT(DISTINCT date) AS sessions
        FROM v_exercise_e1rm_daily
        GROUP BY exercise
        ORDER BY volume_kg DESC
        """,
    )


@router.get("/exercise/{name}")
def exercise_progression(
    name: str,
    start: dt.date | None = None,
    end: dt.date | None = None,
    session: Session = Depends(get_session),
):
    start, end = _default_range(start, end, 90)
    return _rows(
        session,
        """
        SELECT date, best_e1rm_kg, top_weight_kg, volume_kg, working_sets
        FROM v_exercise_e1rm_daily
        WHERE lower(exercise) = lower(:name)
          AND date BETWEEN :start AND :end
        ORDER BY date
        """,
        name=name,
        start=start,
        end=end,
    )


@router.get("/summary")
def summary(session: Session = Depends(get_session)):
    """Everything the dashboard header needs, in one round trip."""
    latest = _rows(
        session,
        """
        SELECT metric, value, unit, date
        FROM v_daily_metrics_preferred
        WHERE (metric, date) IN (
            SELECT metric, MAX(date) FROM v_daily_metrics_preferred GROUP BY metric
        )
        """,
    )
    load = _rows(
        session,
        """
        SELECT date, load_au, acute_7d, chronic_28d, acwr
        FROM v_training_load WHERE date = CURRENT_DATE
        """,
    )
    recent = _rows(
        session,
        """
        SELECT date, volume_kg, working_sets, exercises
        FROM v_daily_volume ORDER BY date DESC LIMIT 7
        """,
    )
    return {
        "latest_metrics": {r["metric"]: r for r in latest},
        "load": load[0] if load else None,
        "recent_workouts": recent,
    }


@router.get("/muscle-sets")
def muscle_sets(session: Session = Depends(get_session)):
    """Working sets per muscle over the last seven days, against the weekly target."""
    return {
        "target": muscles.document(),
        "muscles": muscles.last_seven_days(session, dt.date.today()),
    }

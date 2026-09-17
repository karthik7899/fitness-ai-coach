"""The SQL views are the coach's only source of numbers, so they carry the most risk."""

import datetime as dt
from decimal import Decimal

import pytest

from app.models import DailyMetric
from tests.conftest import add_workout, rows_of

TODAY = dt.date.today()


def test_epley_e1rm(session, exercises):
    add_workout(session, TODAY, [(exercises["squat"], 100, 5, False)])
    row = rows_of(session, "SELECT e1rm_kg FROM v_sets_enriched")[0]
    # Epley: 100 * (1 + 5/30)
    assert float(row["e1rm_kg"]) == pytest.approx(116.67, abs=0.01)


def test_single_rep_e1rm_is_the_weight(session, exercises):
    add_workout(session, TODAY, [(exercises["squat"], 140, 1, False)])
    row = rows_of(session, "SELECT e1rm_kg FROM v_sets_enriched")[0]
    assert float(row["e1rm_kg"]) == pytest.approx(144.67, abs=0.01)


@pytest.mark.parametrize("reps", [0, 13, 20, 40])
def test_e1rm_is_null_outside_the_reliable_rep_range(session, exercises, reps):
    """An unguarded 1RM formula produces nonsense at high reps; Brzycki goes negative."""
    add_workout(session, TODAY, [(exercises["squat"], 60, reps, False)])
    row = rows_of(session, "SELECT e1rm_kg FROM v_sets_enriched")[0]
    assert row["e1rm_kg"] is None


def test_zero_weight_bodyweight_set_has_no_e1rm(session, exercises):
    add_workout(session, TODAY, [(exercises["squat"], 0, 10, False)])
    assert rows_of(session, "SELECT e1rm_kg FROM v_sets_enriched")[0]["e1rm_kg"] is None


def test_warmups_are_excluded_from_daily_volume(session, exercises):
    add_workout(
        session,
        TODAY,
        [
            (exercises["squat"], 60, 10, True),  # warmup: 600kg that must not count
            (exercises["squat"], 100, 5, False),
            (exercises["squat"], 100, 5, False),
        ],
    )
    row = rows_of(session, "SELECT volume_kg, working_sets FROM v_daily_volume")[0]
    assert float(row["volume_kg"]) == 1000.0
    assert row["working_sets"] == 2


def test_warmups_are_excluded_from_weekly_muscle_volume(session, exercises):
    add_workout(session, TODAY, [(exercises["bench"], 40, 20, True)])
    assert rows_of(session, "SELECT * FROM v_weekly_muscle_volume") == []


def test_volume_is_attributed_to_every_primary_muscle(session, exercises):
    add_workout(session, TODAY, [(exercises["squat"], 100, 5, False)])
    rows = rows_of(
        session, "SELECT muscle, volume_kg FROM v_weekly_muscle_volume ORDER BY muscle"
    )
    assert [r["muscle"] for r in rows] == ["glutes", "quads"]
    # Each muscle is credited the whole set; they are not split.
    assert all(float(r["volume_kg"]) == 500.0 for r in rows)


def test_unmapped_exercise_falls_back_to_its_category(session, exercises):
    """Without the fallback a CROSS JOIN on an empty array drops the set entirely."""
    add_workout(session, TODAY, [(exercises["sled"], 80, 8, False)])
    rows = rows_of(session, "SELECT muscle, volume_kg FROM v_weekly_muscle_volume")
    assert [r["muscle"] for r in rows] == ["Conditioning"]
    assert float(rows[0]["volume_kg"]) == 640.0


def test_exercise_progression_reports_the_best_set_of_the_day(session, exercises):
    add_workout(
        session,
        TODAY,
        [
            (exercises["squat"], 90, 5, False),
            (exercises["squat"], 110, 3, False),
            (exercises["squat"], 100, 5, False),
        ],
    )
    row = rows_of(session, "SELECT best_e1rm_kg, top_weight_kg FROM v_exercise_e1rm_daily")[0]
    assert float(row["top_weight_kg"]) == 110.0
    assert float(row["best_e1rm_kg"]) == pytest.approx(121.0, abs=0.01)


def test_rest_days_count_as_zero_load(session, exercises):
    """The date spine matters: averaging only over days with rows inflates the ratio."""
    add_workout(session, TODAY - dt.timedelta(days=6), [(exercises["squat"], 100, 10, False)])
    rows = rows_of(
        session,
        "SELECT date, load_au FROM v_daily_load WHERE date >= :start ORDER BY date",
        start=TODAY - dt.timedelta(days=6),
    )
    assert len(rows) == 7, "every calendar day should be present, not just training days"
    assert float(rows[0]["load_au"]) == pytest.approx(1.0)
    assert all(float(r["load_au"]) == 0.0 for r in rows[1:])


def test_acwr_is_acute_over_chronic(session, exercises):
    for offset in range(0, 28, 2):
        add_workout(
            session, TODAY - dt.timedelta(days=offset), [(exercises["squat"], 100, 10, False)]
        )
    row = rows_of(
        session,
        "SELECT acute_7d, chronic_28d, acwr FROM v_training_load WHERE date = :d",
        d=TODAY,
    )[0]
    expected = float(row["acute_7d"]) / float(row["chronic_28d"])
    assert float(row["acwr"]) == pytest.approx(expected, abs=0.01)


def test_acwr_is_null_without_history(session):
    row = rows_of(session, "SELECT acwr FROM v_training_load WHERE date = :d", d=TODAY)[0]
    assert row["acwr"] is None


def test_daily_metrics_resolve_conflicts_by_source_precedence(session):
    """Two devices reporting steps for one day must not double count."""
    for source, value in (("health_connect", 9000), ("gadgetbridge", 8000), ("manual", 10000)):
        session.add(
            DailyMetric(
                date=TODAY, metric="steps", source=source, value=Decimal(value), unit="count"
            )
        )
    session.flush()

    rows = rows_of(
        session,
        "SELECT value, source FROM v_daily_metrics_preferred WHERE date = :d AND metric = 'steps'",
        d=TODAY,
    )
    assert len(rows) == 1
    assert rows[0]["source"] == "manual"
    assert float(rows[0]["value"]) == 10000.0


def test_cardio_contributes_to_load(session):
    session.execute(
        __import__("sqlalchemy").text(
            """
            INSERT INTO activities (source, external_id, sport_type, started_at,
                                    distance_m, moving_time_s)
            VALUES ('strava', 'a1', 'Run', :started, 10000, 3000)
            """
        ),
        {"started": dt.datetime.combine(TODAY, dt.time(9, 0))},
    )
    session.flush()
    row = rows_of(
        session,
        "SELECT cardio_minutes, cardio_km, load_au FROM v_daily_load WHERE date = :d",
        d=TODAY,
    )[0]
    assert float(row["cardio_minutes"]) == pytest.approx(50.0)
    assert float(row["cardio_km"]) == pytest.approx(10.0)
    # load_au = tonnes + minutes/10
    assert float(row["load_au"]) == pytest.approx(5.0)

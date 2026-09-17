"""Derived metrics views

These are the agent's only source of numbers: every aggregate the coach quotes is
computed here in SQL rather than by the model.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEWS = [
    # One row per set, joined to its workout and exercise, with volume and a
    # guarded Epley estimated 1RM. The guard matters: an unbounded 1RM formula
    # produces nonsense (or negatives, with Brzycki) at high rep counts.
    (
        "v_sets_enriched",
        """
        CREATE VIEW v_sets_enriched AS
        SELECT
            s.id,
            s.workout_id,
            w.performed_on,
            s.exercise_id,
            e.name        AS exercise,
            e.category,
            e.modality,
            e.primary_muscles,
            s.weight_kg,
            s.reps,
            s.rpe,
            s.distance_m,
            s.duration_s,
            s.is_warmup,
            COALESCE(s.weight_kg, 0) * COALESCE(s.reps, 0) AS volume_kg,
            CASE
                WHEN s.reps BETWEEN 1 AND 12 AND s.weight_kg > 0
                THEN ROUND(s.weight_kg * (1 + s.reps::numeric / 30), 2)
            END AS e1rm_kg
        FROM sets s
        JOIN workouts  w ON w.id = s.workout_id
        JOIN exercises e ON e.id = s.exercise_id
        """,
    ),
    (
        "v_daily_volume",
        """
        CREATE VIEW v_daily_volume AS
        SELECT
            performed_on AS date,
            SUM(volume_kg) AS volume_kg,
            COUNT(*) AS working_sets,
            COUNT(DISTINCT exercise_id) AS exercises
        FROM v_sets_enriched
        WHERE NOT is_warmup
        GROUP BY performed_on
        """,
    ),
    # Exercises with no muscle mapping fall back to their category, so a set is
    # never silently dropped from the weekly picture.
    (
        "v_weekly_muscle_volume",
        """
        CREATE VIEW v_weekly_muscle_volume AS
        SELECT
            date_trunc('week', v.performed_on)::date AS week_start,
            m.muscle,
            SUM(v.volume_kg) AS volume_kg,
            COUNT(*) AS working_sets
        FROM v_sets_enriched v
        CROSS JOIN LATERAL UNNEST(
            CASE
                WHEN COALESCE(cardinality(v.primary_muscles), 0) > 0 THEN v.primary_muscles
                ELSE ARRAY[COALESCE(v.category, 'Uncategorised')]
            END
        ) AS m(muscle)
        WHERE NOT v.is_warmup
        GROUP BY 1, 2
        """,
    ),
    (
        "v_exercise_e1rm_daily",
        """
        CREATE VIEW v_exercise_e1rm_daily AS
        SELECT
            exercise_id,
            exercise,
            performed_on AS date,
            MAX(e1rm_kg)   AS best_e1rm_kg,
            MAX(weight_kg) AS top_weight_kg,
            SUM(volume_kg) AS volume_kg,
            COUNT(*)       AS working_sets
        FROM v_sets_enriched
        WHERE NOT is_warmup
        GROUP BY 1, 2, 3
        """,
    ),
    # Two devices can both report steps for the same day. Resolve to one value
    # per (date, metric) by source precedence so readers never double count.
    (
        "v_daily_metrics_preferred",
        """
        CREATE VIEW v_daily_metrics_preferred AS
        SELECT DISTINCT ON (date, metric)
            date, metric, value, unit, source
        FROM daily_metrics
        ORDER BY date, metric,
            CASE source
                WHEN 'manual'         THEN 0
                WHEN 'health_connect' THEN 1
                WHEN 'strava'         THEN 2
                ELSE 9
            END
        """,
    ),
    # A continuous date spine matters for load: a rest day is a real zero, not a
    # missing row, and averaging over present rows only would inflate the ratio.
    (
        "v_daily_load",
        """
        CREATE VIEW v_daily_load AS
        WITH spine AS (
            SELECT generate_series(
                CURRENT_DATE - INTERVAL '365 days', CURRENT_DATE, INTERVAL '1 day'
            )::date AS date
        ),
        strength AS (
            SELECT performed_on AS date, SUM(volume_kg) / 1000.0 AS tonnes
            FROM v_sets_enriched
            WHERE NOT is_warmup
            GROUP BY 1
        ),
        cardio AS (
            SELECT
                (started_at AT TIME ZONE 'UTC')::date AS date,
                SUM(COALESCE(moving_time_s, 0)) / 60.0 AS minutes,
                SUM(COALESCE(distance_m, 0)) / 1000.0  AS km
            FROM activities
            GROUP BY 1
        )
        SELECT
            sp.date,
            COALESCE(st.tonnes, 0)  AS strength_tonnes,
            COALESCE(c.minutes, 0)  AS cardio_minutes,
            COALESCE(c.km, 0)       AS cardio_km,
            -- Arbitrary but consistent unit: 1 tonne lifted ~ 10 cardio minutes.
            -- ACWR only needs the scale to be stable over time, not physical.
            COALESCE(st.tonnes, 0) + COALESCE(c.minutes, 0) / 10.0 AS load_au
        FROM spine sp
        LEFT JOIN strength st ON st.date = sp.date
        LEFT JOIN cardio   c  ON c.date  = sp.date
        """,
    ),
    (
        "v_training_load",
        """
        CREATE VIEW v_training_load AS
        SELECT
            date,
            strength_tonnes,
            cardio_minutes,
            cardio_km,
            load_au,
            ROUND(AVG(load_au) OVER w7::numeric, 3)  AS acute_7d,
            ROUND(AVG(load_au) OVER w28::numeric, 3) AS chronic_28d,
            CASE
                WHEN AVG(load_au) OVER w28 > 0
                THEN ROUND((AVG(load_au) OVER w7 / AVG(load_au) OVER w28)::numeric, 3)
            END AS acwr
        FROM v_daily_load
        WINDOW
            w7  AS (ORDER BY date ROWS BETWEEN 6  PRECEDING AND CURRENT ROW),
            w28 AS (ORDER BY date ROWS BETWEEN 27 PRECEDING AND CURRENT ROW)
        """,
    ),
]


def upgrade() -> None:
    for _, ddl in VIEWS:
        op.execute(ddl)


def downgrade() -> None:
    for name, _ in reversed(VIEWS):
        op.execute(f"DROP VIEW IF EXISTS {name}")

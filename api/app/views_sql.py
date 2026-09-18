"""The derived metrics views, in SQL that runs on PostgreSQL and SQLite alike.

These are the coach's only source of numbers, so there is one definition rather
than a translation: a second copy would drift, and a drifting metric is worse
than a missing one.

Most of the original Postgres-isms were avoidable rather than essential:

- `DISTINCT ON` becomes `ROW_NUMBER`, which both dialects have.
- `generate_series` becomes a recursive CTE, likewise.
- `UNNEST` over an array column disappeared entirely when muscles moved into
  their own table, which is the better relational shape anyway.

What genuinely differs is only date arithmetic, isolated in DIALECTS below.
"""

from __future__ import annotations

DIALECTS: dict[str, dict[str, str]] = {
    "postgresql": {
        "week_start": "date_trunc('week', {d})::date",
        "date_of": "({ts} AT TIME ZONE 'UTC')::date",
        "spine_start": "CURRENT_DATE - 365",
        "spine_next": 'sp."date" + 1',
        "today": "CURRENT_DATE",
    },
    "sqlite": {
        # 'weekday 0' moves to the coming Sunday; six days back is that week's
        # Monday, matching date_trunc('week', ...).
        "week_start": "date({d}, 'weekday 0', '-6 days')",
        "date_of": "date({ts})",
        "spine_start": "date('now', '-365 days')",
        "spine_next": "date(sp.\"date\", '+1 day')",
        "today": "date('now')",
    },
}

VIEW_NAMES = [
    "v_sets_enriched",
    "v_daily_volume",
    "v_weekly_muscle_volume",
    "v_exercise_e1rm_daily",
    "v_daily_metrics_preferred",
    "v_daily_load",
    "v_training_load",
]


def _templates() -> dict[str, str]:
    return {
        # One row per set with volume and a guarded Epley estimated 1RM. The
        # guard matters: an unbounded formula produces nonsense at high reps,
        # and Brzycki actually goes negative past ~37.
        "v_sets_enriched": """
        CREATE VIEW v_sets_enriched AS
        SELECT
            s.id,
            s.workout_id,
            w.performed_on,
            s.exercise_id,
            e.name        AS exercise,
            e.category,
            e.modality,
            s.weight_kg,
            s.reps,
            s.rpe,
            s.distance_m,
            s.duration_s,
            s.is_warmup,
            COALESCE(s.weight_kg, 0) * COALESCE(s.reps, 0) AS volume_kg,
            CASE
                WHEN s.reps BETWEEN 1 AND 12 AND s.weight_kg > 0
                THEN ROUND(s.weight_kg * (1 + s.reps / 30.0), 2)
            END AS e1rm_kg
        FROM sets s
        JOIN workouts  w ON w.id = s.workout_id
        JOIN exercises e ON e.id = s.exercise_id
        """,
        "v_daily_volume": """
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
        # The LEFT JOIN is what keeps an unmapped exercise in the picture: with
        # an inner join its sets would silently vanish from the weekly totals.
        "v_weekly_muscle_volume": """
        CREATE VIEW v_weekly_muscle_volume AS
        SELECT
            {week_start_performed} AS week_start,
            COALESCE(m.muscle, v.category, 'Uncategorised') AS muscle,
            SUM(v.volume_kg) AS volume_kg,
            COUNT(*) AS working_sets
        FROM v_sets_enriched v
        LEFT JOIN exercise_muscles m
               ON m.exercise_id = v.exercise_id AND m.is_primary
        WHERE NOT v.is_warmup
        GROUP BY 1, 2
        """,
        "v_exercise_e1rm_daily": """
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
        GROUP BY exercise_id, exercise, performed_on
        """,
        # Two devices can both report steps for one day. Resolve to a single
        # value by source precedence so readers never double count.
        "v_daily_metrics_preferred": """
        CREATE VIEW v_daily_metrics_preferred AS
        SELECT date, metric, value, unit, source
        FROM (
            SELECT
                date, metric, value, unit, source,
                ROW_NUMBER() OVER (
                    PARTITION BY date, metric
                    ORDER BY CASE source
                        WHEN 'manual'         THEN 0
                        WHEN 'health_connect' THEN 1
                        WHEN 'gadgetbridge'   THEN 2
                        WHEN 'strava'         THEN 3
                        ELSE 9
                    END
                ) AS rank
            FROM daily_metrics
        ) ranked
        WHERE rank = 1
        """,
        # A continuous date spine matters: a rest day is a real zero, and
        # averaging only over days that have rows would inflate every ratio.
        "v_daily_load": """
        CREATE VIEW v_daily_load AS
        WITH RECURSIVE spine("date") AS (
            SELECT {spine_start}
            UNION ALL
            SELECT {spine_next} FROM spine sp WHERE sp."date" < {today}
        ),
        strength AS (
            SELECT performed_on AS "date", SUM(volume_kg) / 1000.0 AS tonnes
            FROM v_sets_enriched
            WHERE NOT is_warmup
            GROUP BY performed_on
        ),
        cardio AS (
            SELECT
                {date_of_started} AS "date",
                SUM(COALESCE(moving_time_s, 0)) / 60.0 AS minutes,
                SUM(COALESCE(distance_m, 0)) / 1000.0  AS km
            FROM activities
            GROUP BY 1
        )
        SELECT
            spine."date" AS date,
            COALESCE(st.tonnes, 0)  AS strength_tonnes,
            COALESCE(c.minutes, 0)  AS cardio_minutes,
            COALESCE(c.km, 0)       AS cardio_km,
            -- Arbitrary but consistent: 1 tonne lifted ~ 10 cardio minutes.
            -- ACWR needs the scale stable over time, not physically meaningful.
            COALESCE(st.tonnes, 0) + COALESCE(c.minutes, 0) / 10.0 AS load_au
        FROM spine
        LEFT JOIN strength st ON st."date" = spine."date"
        LEFT JOIN cardio   c  ON c."date"  = spine."date"
        """,
        "v_training_load": """
        CREATE VIEW v_training_load AS
        SELECT
            date,
            strength_tonnes,
            cardio_minutes,
            cardio_km,
            load_au,
            ROUND(AVG(load_au) OVER w7, 3)  AS acute_7d,
            ROUND(AVG(load_au) OVER w28, 3) AS chronic_28d,
            CASE
                WHEN AVG(load_au) OVER w28 > 0
                THEN ROUND(AVG(load_au) OVER w7 / AVG(load_au) OVER w28, 3)
            END AS acwr
        FROM v_daily_load
        WINDOW
            w7  AS (ORDER BY date ROWS BETWEEN 6  PRECEDING AND CURRENT ROW),
            w28 AS (ORDER BY date ROWS BETWEEN 27 PRECEDING AND CURRENT ROW)
        """,
    }


def view_ddl(dialect: str) -> list[tuple[str, str]]:
    """The CREATE VIEW statements for a dialect, in dependency order."""
    if dialect not in DIALECTS:
        raise ValueError(f"No metrics views defined for dialect {dialect!r}.")
    d = DIALECTS[dialect]
    substitutions = {
        "week_start_performed": d["week_start"].format(d="v.performed_on"),
        "date_of_started": d["date_of"].format(ts="started_at"),
        "spine_start": d["spine_start"],
        "spine_next": d["spine_next"],
        "today": d["today"],
    }
    templates = _templates()
    return [(name, templates[name].format(**substitutions)) for name in VIEW_NAMES]


def drop_ddl() -> list[str]:
    return [f"DROP VIEW IF EXISTS {name}" for name in reversed(VIEW_NAMES)]

"""Every coach tool, executed against a real database on both dialects.

The agent tests mock Gemini, so until now nothing ran these handlers against
SQL. That gap hid two PostgreSQL-only constructs that made the coach unable to
answer a question about sleep, steps or recent runs on SQLite — which is the
build that runs on a phone.

The point of this file is coverage of the boring kind: call every declared
tool, with and without its optional arguments, and require that it comes back.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import text

from app.agent.tools import HANDLERS, TOOL_SPECS
from app.models import DailyMetric
from tests.conftest import add_workout

TODAY = dt.date.today()
WEEK_AGO = TODAY - dt.timedelta(days=7)


@pytest.fixture
def populated(session, exercises):
    add_workout(session, TODAY, [(exercises["squat"], 100, 5, False)])
    session.add(
        DailyMetric(date=TODAY, metric="steps", source="gadgetbridge", value=8000, unit="count")
    )
    session.execute(
        text(
            """
            INSERT INTO activities (source, external_id, sport_type, name, started_at,
                                    distance_m, moving_time_s)
            VALUES ('strava', 'a1', 'Run', 'Morning run', :started, 10000, 3000)
            """
        ),
        {"started": dt.datetime.combine(TODAY, dt.time(9, 0))},
    )
    session.flush()
    return session


# Every tool, with arguments that exercise the optional paths too.
CALLS = {
    "get_daily_metrics": [
        {"start_date": str(WEEK_AGO), "end_date": str(TODAY)},
        {"start_date": str(WEEK_AGO), "end_date": str(TODAY), "metrics": ["steps"]},
        {
            "start_date": str(WEEK_AGO),
            "end_date": str(TODAY),
            "metrics": ["steps", "sleep_minutes"],
        },
    ],
    "get_training_load": [{"start_date": str(WEEK_AGO), "end_date": str(TODAY)}],
    "get_exercise_history": [{"exercise": "Back Squat"}, {"exercise": "No Such Lift"}],
    "get_volume_summary": [
        {"start_date": str(WEEK_AGO), "end_date": str(TODAY), "group_by": group}
        for group in ("muscle", "week", "exercise", "day", "nonsense")
    ],
    "get_recent_activities": [
        {},
        {"limit": 5},
        {"sport_type": "Run"},
        {"since": str(WEEK_AGO)},
        {"since": f"{WEEK_AGO}T00:00:00"},
    ],
    "get_workout": [{"performed_on": str(TODAY)}],
    "list_exercises": [{}, {"search": "squat"}],
    "log_set": [{"exercise": "Back Squat", "reps": 5, "weight_kg": 100.0}],
    "remember": [{"kind": "injury", "content": "Left shoulder, no overhead pressing"}],
}


def test_every_declared_tool_is_covered_here():
    """A new tool must not be able to ship without being run against SQL."""
    declared = {spec["name"] for spec in TOOL_SPECS}
    assert declared == set(CALLS), f"untested tools: {declared ^ set(CALLS)}"


@pytest.mark.parametrize(
    ("name", "kwargs"),
    [(name, kwargs) for name, calls in CALLS.items() for kwargs in calls],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_tool_runs_against_the_database(populated, name, kwargs):
    result = HANDLERS[name](populated, **kwargs)
    assert isinstance(result, dict)
    # A handler that reports an error must say why, rather than returning junk.
    if "error" in result:
        assert result["error"]


def test_daily_metrics_filter_actually_filters(populated):
    everything = HANDLERS["get_daily_metrics"](
        populated, start_date=str(WEEK_AGO), end_date=str(TODAY)
    )
    just_sleep = HANDLERS["get_daily_metrics"](
        populated, start_date=str(WEEK_AGO), end_date=str(TODAY), metrics=["sleep_minutes"]
    )
    assert everything["count"] == 1
    assert just_sleep["count"] == 0, "the metric filter is not being applied"


def test_recent_activities_reports_pace(populated):
    row = HANDLERS["get_recent_activities"](populated)["rows"][0]
    # 3000s over 10km is 5.00 min/km.
    assert float(row["pace_min_per_km"]) == pytest.approx(5.0, abs=0.01)


def test_recent_activities_since_excludes_older(populated):
    tomorrow = TODAY + dt.timedelta(days=1)
    assert HANDLERS["get_recent_activities"](populated, since=str(tomorrow))["count"] == 0

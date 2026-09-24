"""Personal records against their specification, fixtures/records.json, and
against the database. RecordsTest.kt runs the same cases on the Kotlin port.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app import records
from app.models import SetEntry
from tests.conftest import add_workout

CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "records.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_rule_matches_its_specification(case):
    got = records.beaten([tuple(s) for s in case["before"]], tuple(case["set"]))
    assert [[r.kind, r.value, r.previous] for r in got] == case["expect"]


DAY = dt.date(2026, 3, 10)


def test_a_logged_set_is_checked_against_everything_before_it(session, exercises):
    squat = exercises["squat"]
    add_workout(session, DAY - dt.timedelta(days=7), [(squat, 100, 5, False)])
    today = add_workout(session, DAY, [
        (squat, 140, 3, True),   # a heavy warmup is not a record, nor counted
        (squat, 102.5, 5, False),
        (squat, 102.5, 5, False),
    ])
    sets = session.scalars(
        select(SetEntry).where(SetEntry.workout_id == today.id).order_by(SetEntry.position)
    ).all()
    first, second = [s.id for s in sets if not s.is_warmup]
    warmup = next(s.id for s in sets if s.is_warmup)

    name, found = records.for_set(session, first)
    assert name == "Back Squat"
    assert [r.kind for r in found] == ["weight", "e1rm"]
    # The second matches the first, and the first is now what it has to beat.
    assert records.for_set(session, second)[1] == []
    assert records.for_set(session, warmup)[1] == []
    assert records.for_set(session, 999_999) is None

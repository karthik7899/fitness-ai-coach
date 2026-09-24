"""The progression rule against its specification, fixtures/progression.json.

ProgressionTest.kt runs the same cases against the Kotlin port, so the two
apps cannot suggest different weights from the same history.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.progression import suggest

CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "progression.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_rule_matches_its_specification(case):
    got = suggest(
        [tuple(s) for s in case["last"]],
        case["sets"],
        case["reps_min"],
        case["reps_max"],
        case["increment"],
    )
    assert {"advice": got.advice, "weight": got.weight, "reps": got.reps} == case["expect"]

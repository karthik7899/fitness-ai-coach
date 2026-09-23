"""The grounding check's intent, stated independently of the generated fixture.

fixtures/grounding.json is produced from this module, so a weakened rule could
be regenerated into a green build. These assertions are what stop that: each
states a property the check exists to have, in terms a regeneration cannot
quietly rewrite.
"""

from __future__ import annotations

import pytest

from app.agent.grounding import check


def flagged(answer: str, *sources: str) -> list[str]:
    return check(answer, list(sources)).unverified


def test_an_invented_figure_is_caught():
    assert flagged("You averaged 12,000 steps.", '{"steps": 9876}') == ["12,000"]


def test_arithmetic_the_model_did_is_caught():
    """The design is that the model never computes. A difference is a computation."""
    assert flagged("300 kg more than last week.", '{"a": 1500, "b": 1200}') == ["300"]


def test_an_unrelated_large_value_cannot_vouch_for_a_small_one():
    """Without a unit, 8 is only grounded by an 8 — not by 8000 divided down.

    This is the property that makes "verified" mean something. A check that
    rescales everything would pass this, and would be worse than no check.
    """
    assert flagged("You did 8 sets.", '{"working_sets": 6, "steps": 8000}') == ["8"]


def test_digits_inside_a_key_are_not_values():
    assert flagged("Just 1 session.", '{"best_e1rm_kg": 99.5}') == ["1"]


def test_small_round_numbers_are_taken_literally():
    assert flagged("You did 10 reps.", '{"reps": 12}') == ["10"]


@pytest.mark.parametrize(
    ("answer", "source"),
    [
        ("About 117 kg.", '{"e1rm": 116.67}'),
        ("Roughly 10,000 steps.", '{"steps": 9876}'),
        ("That is 10.9 tonnes.", '{"volume_kg": 10872}'),
        ("You slept 7h 30m.", '{"sleep_minutes": 450}'),
        ("40% above.", '{"ratio": 0.4}'),
    ],
)
def test_presentation_is_not_mistaken_for_invention(answer, source):
    assert flagged(answer, source) == []


def test_the_question_can_ground_its_own_numbers():
    assert flagged("Over the last 30 days, yes.", "How was the last 30 days?") == []


def test_an_answer_without_figures_has_nothing_to_flag():
    result = check("Rest today.", [])
    assert result.ok and result.verified == [] and result.unverified == []

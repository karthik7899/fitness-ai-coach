"""The eval scenarios, run with the model's side scripted.

This does not grade the model: the script says what the model does. It proves
each scenario holds together — that its expected figures really come out of
the tools on its seed data, that the harness passes the scripted answer, and
that the scorer agrees. The same scenarios run through the Kotlin coach in
EvalTest.kt, so a scenario that passes here and fails there is a difference
between the two apps. The live runner, scripts/run_evals.py, grades Gemini
against them.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.agent import evals

SCENARIOS = evals.load_all()


def test_there_are_scenarios():
    assert len(SCENARIOS) >= 10
    assert len({s.name for s in SCENARIOS}) == len(SCENARIOS), "scenario names must be unique"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
async def test_scripted_scenario_passes(session, scenario):
    evals.seed(session, scenario)
    transcript = await evals.run(session, scenario, evals.ScriptedClient(scenario.script))

    checks = evals.score(scenario, transcript)
    failed = [f"{c.label} ({c.detail})" if c.detail else c.label for c in checks if not c.passed]
    assert not failed, f"{scenario.name}: {failed}\nanswer: {transcript.answer}"
    # A scripted answer that needed correcting is a broken script, not a pass.
    assert not transcript.retried, f"{scenario.name}: the harness sent the answer back"


def test_every_scenario_expects_something():
    for scenario in SCENARIOS:
        assert evals.score(scenario, evals.Transcript()), f"{scenario.name} checks nothing"


# --------------------------------------------------------------------------
# The scorer, against transcripts that should fail
# --------------------------------------------------------------------------


def scenario(**expect) -> evals.Scenario:
    return evals.Scenario(
        name="t", about="", question="q", seed={}, expect=expect, script=[],
        today=dt.date(2026, 1, 1),
    )


def failed(checks: list[evals.Check]) -> list[str]:
    return [c.label for c in checks if not c.passed]


def test_a_missing_tool_call_fails():
    checks = evals.score(scenario(calls=["get_training_load"]),
                         evals.Transcript(tools=["get_daily_metrics"]))
    assert failed(checks) == ["called get_training_load"]


def test_any_one_of_the_alternatives_is_enough():
    checks = evals.score(scenario(calls=[["get_volume_summary", "get_exercise_history"]]),
                         evals.Transcript(tools=["get_exercise_history"]))
    assert not failed(checks)


def test_a_forbidden_call_fails():
    checks = evals.score(scenario(avoids=["log_set"]), evals.Transcript(tools=["log_set"]))
    assert failed(checks) == ["did not call log_set"]


def test_quoting_follows_the_grounding_rules():
    assert evals.quotes("Top set was 107.5 kg.", 107.5)
    assert evals.quotes("About 2,940 kg in total.", 2940)
    assert evals.quotes("That is 0.1075 t.", 107.5)
    assert not evals.quotes("Top set was 105 kg.", 107.5)
    # 7 is definitional; it cannot count as quoting a figure from the data.
    assert not evals.quotes("Over the last 7 days.", 7)


def test_an_ungrounded_answer_fails():
    transcript = evals.Transcript(grounding={"ok": False, "verified": [], "unverified": ["12"]})
    checks = evals.score(scenario(grounded=True), transcript)
    assert failed(checks) == ["every figure found in the data"]


def test_an_error_fails_even_a_scenario_that_checks_little():
    checks = evals.score(scenario(avoids=["log_set"]), evals.Transcript(error="boom"))
    assert "finished without an error" in failed(checks)


def test_side_effects_are_checked():
    transcript = evals.Transcript(sets_added=1, notes_added=["Wants to run a marathon."])
    checks = evals.score(scenario(sets_added=0, remembers="knee"), transcript)
    assert failed(checks) == ["logged 0 sets", "remembered a note mentioning 'knee'"]


def test_dates_resolve_relative_to_today():
    today = dt.date(2026, 3, 1)
    assert evals.resolve_dates(
        {"a": ["{today}", "{today-1}", "on {today+2}."]}, today
    ) == {"a": ["2026-03-01", "2026-02-28", "on 2026-03-03."]}

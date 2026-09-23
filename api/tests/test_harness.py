"""The harness around the Python coach, with the model scripted.

Before this, nothing ran stream_turn end to end — only its parts. Each test
here says exactly what the model does and asserts what the harness does about
it: the grounding verdict, the one corrective retry, and the trace. The same
behaviours are pinned for the Android coach in HarnessTest.kt.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from google.genai import types

from app.agent import coach
from app.agent.grounding import CORRECTION_PREFIX
from tests.conftest import add_workout

TODAY = dt.date.today()
DAILY = {"start_date": str(TODAY), "end_date": str(TODAY), "group_by": "day"}


def text(answer: str, tokens: int = 0) -> list[types.GenerateContentResponse]:
    body: dict = {"candidates": [{"content": {"role": "model", "parts": [{"text": answer}]}}]}
    if tokens:
        body["usage_metadata"] = {"total_token_count": tokens}
    return [types.GenerateContentResponse.model_validate(body)]


def call(name: str, args: dict, tokens: int = 0) -> list[types.GenerateContentResponse]:
    body: dict = {
        "candidates": [
            {"content": {"role": "model",
                         "parts": [{"function_call": {"name": name, "args": args}}]}}
        ]
    }
    if tokens:
        body["usage_metadata"] = {"total_token_count": tokens}
    return [types.GenerateContentResponse.model_validate(body)]


class ScriptedModel:
    """Replays a fixed list of responses and records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[list[types.Content]] = []

    async def generate_content_stream(self, model, contents, config):
        self.requests.append(list(contents))
        chunks = self.responses[min(len(self.requests), len(self.responses)) - 1]

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


@pytest.fixture
def lifted(session, exercises):
    add_workout(session, TODAY, [(exercises["squat"], 100, 5, False)])  # 500 kg
    return session


async def run(session, monkeypatch, script: ScriptedModel, question: str) -> list[dict]:
    monkeypatch.setattr(coach, "_client", lambda _s: SimpleNamespace(
        aio=SimpleNamespace(models=script)))
    conversation = coach.ensure_conversation(session, None)
    return [event async for event in coach.stream_turn(session, conversation, question)]


def only(events: list[dict], kind: str) -> dict:
    matching = [e for e in events if e["type"] == kind]
    assert len(matching) == 1, f"expected one {kind} event, got {len(matching)}"
    return matching[0]


async def test_a_grounded_answer_goes_straight_through(lifted, monkeypatch):
    script = ScriptedModel(call("get_volume_summary", DAILY), text("You lifted 500 kg today."))
    events = await run(lifted, monkeypatch, script, "What did I lift?")

    verdict = only(events, "grounding")
    assert verdict["ok"] and verdict["verified"] == ["500"] and not verdict["retried"]
    assert not [e for e in events if e["type"] == "retry"]
    assert len(script.requests) == 2


async def test_an_invented_figure_is_sent_back_once_and_corrected(lifted, monkeypatch):
    script = ScriptedModel(
        text("You lifted 12,000 kg."),
        call("get_volume_summary", DAILY),
        text("You lifted 500 kg today."),
    )
    events = await run(lifted, monkeypatch, script, "What did I lift?")

    assert only(events, "retry")["unverified"] == ["12,000"]
    verdict = only(events, "grounding")
    assert verdict["ok"] and verdict["retried"]

    correction = script.requests[1][-1].parts[0].text
    assert correction.startswith(CORRECTION_PREFIX) and "12,000" in correction


async def test_only_one_retry_and_a_failing_answer_is_flagged(lifted, monkeypatch):
    script = ScriptedModel(text("You lifted 12,000 kg."), text("It was 11,500 kg."))
    events = await run(lifted, monkeypatch, script, "What did I lift?")

    assert only(events, "grounding")["unverified"] == ["11,500"]
    assert len(script.requests) == 2, "a second retry was made"


async def test_the_correction_cannot_vouch_for_the_figure_it_quotes(lifted, monkeypatch):
    script = ScriptedModel(text("You averaged 12,000 steps."), text("You averaged 12,000 steps."))
    events = await run(lifted, monkeypatch, script, "How many steps?")
    assert only(events, "grounding")["unverified"] == ["12,000"]


async def test_the_questions_own_figures_are_grounded(lifted, monkeypatch):
    script = ScriptedModel(text("Over the last 30 days nothing was logged."))
    events = await run(lifted, monkeypatch, script, "How was the last 30 days?")
    assert only(events, "grounding")["ok"]


async def test_the_trace_records_each_step_in_order(lifted, monkeypatch):
    script = ScriptedModel(call("get_volume_summary", DAILY), text("You lifted 500 kg today."))
    trace = only(await run(lifted, monkeypatch, script, "What did I lift?"), "trace")

    assert [s["kind"] for s in trace["steps"]] == ["model", "tool", "model", "check"]
    tool = next(s for s in trace["steps"] if s["kind"] == "tool")
    assert tool["label"] == "get_volume_summary" and "group_by=day" in tool["detail"]
    assert all(s["millis"] >= 0 for s in trace["steps"])


async def test_a_retry_shows_in_the_trace(lifted, monkeypatch):
    script = ScriptedModel(text("You lifted 12,000 kg."), text("Nothing logged yet."))
    trace = only(await run(lifted, monkeypatch, script, "What did I lift?"), "trace")
    assert [s["kind"] for s in trace["steps"]] == ["model", "check", "retry", "model", "check"]


async def test_a_failing_tool_is_marked(lifted, monkeypatch):
    script = ScriptedModel(call("get_workout", {}), text("I could not read that day."))
    trace = only(await run(lifted, monkeypatch, script, "What did I do?"), "trace")
    assert next(s for s in trace["steps"] if s["kind"] == "tool")["failed"]


async def test_token_use_is_summed_across_model_calls(lifted, monkeypatch):
    script = ScriptedModel(
        call("get_volume_summary", DAILY, tokens=120), text("You lifted 500 kg.", tokens=80)
    )
    trace = only(await run(lifted, monkeypatch, script, "What did I lift?"), "trace")
    assert trace["usage"]["total"] == 200

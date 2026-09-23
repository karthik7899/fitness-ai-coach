"""Scenario evals for the coach: seed a database, ask a question, score the answer.

The scenarios live in evals/scenarios/ at the repository root and are shared
with the Android suite, which runs them through the Kotlin coach. Each one
names the data, the question, and what a good answer must do: which tools it
calls, which figures it quotes, what it says, and what it changes.

There are two ways to run a scenario:

- scripted, where the model's side of the conversation comes from the
  scenario itself. Nothing is being judged about the model then; what the run
  proves is that the scenario holds together — its expected figures really
  come out of the tools on its seed data, in both apps — and that the harness
  and the scorer agree with it. That is what CI runs.
- live, against Gemini, via scripts/run_evals.py. The same scorer grades the
  real model's answer, which is the point of the whole exercise.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from google.genai import types
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent import coach
from app.agent.grounding import check
from app.models import CoachNote, DailyMetric, Exercise, SetEntry, Workout

SCENARIOS = Path(__file__).resolve().parents[3] / "evals" / "scenarios"

# The same three exercises both test suites use, for scenarios that do not
# bring their own.
DEFAULT_EXERCISES = [
    {"name": "Back Squat", "category": "Legs", "muscles": ["quads", "glutes"]},
    {"name": "Bench Press", "category": "Chest", "muscles": ["chest", "triceps"]},
    {"name": "Sled Push", "category": "Conditioning", "muscles": []},
]

_RELATIVE_DATE = re.compile(r"\{today(?:([+-])([0-9]+))?\}")


def resolve_dates(value, today: dt.date):
    """Replace {today}, {today-7} and {today+1} in every string, recursively.

    Scenarios are written relative to the day they run, because the tools and
    the prompt both work from the real date: a scenario pinned to fixed dates
    would drift out of every "last month" window within weeks.
    """
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            sign, days = match.group(1), int(match.group(2) or 0)
            return (today + dt.timedelta(days=-days if sign == "-" else days)).isoformat()

        return _RELATIVE_DATE.sub(replace, value)
    if isinstance(value, list):
        return [resolve_dates(v, today) for v in value]
    if isinstance(value, dict):
        return {k: resolve_dates(v, today) for k, v in value.items()}
    return value


@dataclass
class Scenario:
    name: str
    about: str
    question: str
    seed: dict
    expect: dict
    script: list[dict]
    today: dt.date


def load(path: Path, today: dt.date | None = None) -> Scenario:
    today = today or dt.date.today()
    raw = resolve_dates(json.loads(path.read_text()), today)
    return Scenario(
        name=raw["name"],
        about=raw.get("about", ""),
        question=raw["question"],
        seed=raw.get("seed", {}),
        expect=raw.get("expect", {}),
        script=raw.get("script", []),
        today=today,
    )


def load_all(directory: Path = SCENARIOS, today: dt.date | None = None) -> list[Scenario]:
    return [load(path, today) for path in sorted(directory.glob("*.json"))]


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------


def seed(session: Session, scenario: Scenario) -> None:
    exercises: dict[str, Exercise] = {}
    for spec in scenario.seed.get("exercises", DEFAULT_EXERCISES):
        exercise = Exercise(
            name=spec["name"],
            category=spec.get("category"),
            primary_muscles=spec.get("muscles", []),
        )
        session.add(exercise)
        exercises[spec["name"]] = exercise
    session.flush()

    for spec in scenario.seed.get("workouts", []):
        workout = Workout(
            performed_on=scenario.today + dt.timedelta(days=spec["day"]), source="manual"
        )
        session.add(workout)
        session.flush()
        for position, entry in enumerate(spec["sets"], start=1):
            name, weight, reps, *rest = entry
            session.add(
                SetEntry(
                    workout_id=workout.id,
                    exercise_id=exercises[name].id,
                    position=position,
                    weight_kg=Decimal(str(weight)) if weight is not None else None,
                    reps=reps,
                    is_warmup=bool(rest and rest[0]),
                )
            )

    for spec in scenario.seed.get("daily_metrics", []):
        session.add(
            DailyMetric(
                date=scenario.today + dt.timedelta(days=spec["day"]),
                metric=spec["metric"],
                source=spec.get("source", "gadgetbridge"),
                value=Decimal(str(spec["value"])),
                unit=spec["unit"],
            )
        )

    for spec in scenario.seed.get("notes", []):
        session.add(CoachNote(kind=spec["kind"], content=spec["content"]))

    session.commit()


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------


@dataclass
class Transcript:
    """What happened when the scenario's question was asked."""

    answer: str = ""
    tools: list[str] = field(default_factory=list)
    grounding: dict = field(default_factory=dict)
    retried: bool = False
    sets_added: int = 0
    notes_added: list[str] = field(default_factory=list)
    tokens: int = 0
    millis: int = 0
    error: str | None = None


class ScriptedModel:
    """Plays the model's side of a scenario from its `script`.

    Each step is one model response: `{"text": ...}`, `{"call": name, "args":
    {...}}`, or `{"calls": [{"name": ..., "args": ...}, ...]}` for several
    calls in one response. Past the end of the script the last step repeats,
    which is what a real model stuck in a loop would look like.
    """

    def __init__(self, steps: list[dict]):
        self.steps = steps
        self.requests = 0

    def _response(self, step: dict) -> types.GenerateContentResponse:
        if "text" in step:
            parts = [{"text": step["text"]}]
        else:
            calls = step.get("calls") or [{"name": step["call"], "args": step.get("args", {})}]
            parts = [
                {"function_call": {"name": c["name"], "args": c.get("args", {})}} for c in calls
            ]
        return types.GenerateContentResponse.model_validate(
            {"candidates": [{"content": {"role": "model", "parts": parts}}]}
        )

    async def generate_content_stream(self, model, contents, config):
        step = self.steps[min(self.requests, len(self.steps) - 1)]
        self.requests += 1
        response = self._response(step)

        async def stream():
            yield response

        return stream()


class ScriptedClient:
    """Just enough of genai.Client for stream_turn: `client.aio.models`."""

    def __init__(self, steps: list[dict]):
        self.aio = type("Aio", (), {})()
        self.aio.models = ScriptedModel(steps)


def _set_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(SetEntry)) or 0


def _note_ids(session: Session) -> set[int]:
    return set(session.scalars(select(CoachNote.id)).all())


async def run(session: Session, scenario: Scenario, client=None) -> Transcript:
    """Ask the scenario's question on an already-seeded database.

    `client` is a genai.Client, or a ScriptedClient; None means whatever the
    app itself would use, which is the live model.
    """
    transcript = Transcript()
    sets_before, notes_before = _set_count(session), _note_ids(session)
    conversation = coach.ensure_conversation(session, None)

    try:
        async for event in coach.stream_turn(
            session, conversation, scenario.question, client=client
        ):
            kind = event["type"]
            if kind == "token":
                transcript.answer += event["text"]
            elif kind == "tool":
                transcript.tools.append(event["name"])
            elif kind == "retry":
                # The streamed draft is replaced; what is graded is what stays.
                transcript.answer = ""
                transcript.retried = True
            elif kind == "grounding":
                transcript.grounding = {
                    k: event[k] for k in ("ok", "verified", "unverified")
                }
            elif kind == "trace":
                transcript.tokens = event["usage"]["total"]
                transcript.millis = event["total_millis"]
            elif kind == "error":
                transcript.error = event["message"]
    except Exception as exc:  # a live run records the failure and moves on
        session.rollback()
        transcript.error = f"{type(exc).__name__}: {exc}"

    transcript.sets_added = _set_count(session) - sets_before
    added = _note_ids(session) - notes_before
    transcript.notes_added = [
        note.content for note in session.scalars(
            select(CoachNote).where(CoachNote.id.in_(added)).order_by(CoachNote.id)
        )
    ]
    return transcript


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


@dataclass
class Check:
    label: str
    passed: bool
    detail: str = ""


def quotes(answer: str, figure) -> bool:
    """Whether the answer states this figure, by the grounding check's rules.

    So "107.5 kg", "107.50" and "0.1075 t" all quote 107.5, the same way they
    would all be accepted as coming from a tool result that said 107.5. The
    figure is what an answer claimed only against it, over and above what the
    definitional constants already account for.
    """
    baseline = set(check(answer, []).verified)
    return bool(set(check(answer, [str(figure)]).verified) - baseline)


def _alternatives(entry) -> list[str]:
    return entry if isinstance(entry, list) else [entry]


def score(scenario: Scenario, transcript: Transcript) -> list[Check]:
    expect = scenario.expect
    checks: list[Check] = []

    if transcript.error:
        checks.append(Check("finished without an error", False, transcript.error))

    for entry in expect.get("calls", []):
        options = _alternatives(entry)
        called = [t for t in options if t in transcript.tools]
        checks.append(
            Check(f"called {' or '.join(options)}", bool(called),
                  "" if called else f"tools called: {', '.join(transcript.tools) or 'none'}")
        )

    for tool in expect.get("avoids", []):
        checks.append(Check(f"did not call {tool}", tool not in transcript.tools))

    for figure in expect.get("quotes", []):
        checks.append(Check(f"quoted {figure}", quotes(transcript.answer, figure)))

    if expect.get("grounded"):
        unverified = transcript.grounding.get("unverified", [])
        found = transcript.grounding.get("ok", False) and not transcript.error
        checks.append(
            Check("every figure found in the data", found,
                  f"not found: {', '.join(unverified)}" if unverified else "")
        )

    lowered = transcript.answer.lower()
    for entry in expect.get("says", []):
        options = _alternatives(entry)
        said = any(option.lower() in lowered for option in options)
        shown = " / ".join(repr(o) for o in options[:3]) + (" / …" if len(options) > 3 else "")
        checks.append(Check(f"says {shown}", said))

    if "sets_added" in expect:
        wanted = expect["sets_added"]
        checks.append(
            Check(f"logged {wanted} set{'s' if wanted != 1 else ''}",
                  transcript.sets_added == wanted, f"logged {transcript.sets_added}")
        )

    if "remembers" in expect:
        word = expect["remembers"].lower()
        kept = any(word in note.lower() for note in transcript.notes_added)
        checks.append(
            Check(f"remembered a note mentioning {expect['remembers']!r}", kept,
                  f"notes: {transcript.notes_added}" if transcript.notes_added else "no note")
        )

    return checks

"""The coaching agent loop, on the Gemini API.

Function calling is driven manually rather than through the SDK's automatic mode,
because each turn has to emit SSE events per tool call, persist every content part
to `chat_messages`, and hand each handler the request's SQLAlchemy session.

`tools.py` stays provider-neutral; the conversion to Gemini declarations lives here.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import time
from collections.abc import AsyncIterator

from google import genai
from google.genai import types
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import settings_store
from app.agent.grounding import CORRECTION_PREFIX, Grounding, check, correction, describe
from app.agent.tools import HANDLERS, TOOL_SPECS
from app.models import ChatMessage, CoachNote, Conversation

MAX_TURNS = 12

SYSTEM_INSTRUCTIONS = """\
You are the athlete's personal strength and conditioning coach. You have direct \
query access to their complete training database through your tools.

How you work:

- Never estimate, recall or compute a number yourself. Every figure you cite must \
come from a tool call in this conversation. If you have not queried it, you do not \
know it.
- Query before you answer. A question about progress, recovery or volume needs data, \
not a general-principles answer. Prefer several narrow queries over one broad one.
- When the data does not support a conclusion, say so plainly and name what is \
missing. Do not fill gaps with plausible-sounding training advice.
- Be concrete and brief. Give the reading, then the recommendation. Reference actual \
dates, loads and rep counts.
- Ground advice in evidence-based practice: progressive overload, managing acute \
versus chronic load, specificity, and adequate recovery. Interpret ACWR as a signal, \
not a verdict, and weigh it alongside sleep and resting heart rate.
- You are a coach, not a physician. Flag anything that reads like injury or illness \
and recommend proper medical attention rather than training through it.
- When the athlete tells you something durable about themselves — an injury, a goal, \
a constraint, a preference — call `remember` so it informs future sessions.
- Log sets only when the athlete says they performed them, never from a plan or an \
intention.
"""


def _client(session: Session) -> genai.Client:
    # A key entered in the UI wins over .env; with neither, the bare constructor
    # still picks up GEMINI_API_KEY or GOOGLE_API_KEY from the environment.
    key, _ = settings_store.gemini_api_key(session)
    return genai.Client(api_key=key) if key else genai.Client()


def declarations() -> list[types.FunctionDeclaration]:
    return [
        types.FunctionDeclaration(
            name=spec["name"],
            description=spec["description"],
            parameters_json_schema=spec["parameters"],
        )
        for spec in TOOL_SPECS
    ]


def build_system_instruction(
    instructions: str, today: dt.date, notes: list[tuple[str, str]]
) -> str:
    """The prompt the model sees: the instructions, today's date, remembered facts.

    Pure, so the Android coach can be held to produce exactly the same text —
    the shared fixture in fixtures/prompt_assembly.json is what enforces it.
    Today's date is not decoration: without it "this week" leaves the model
    guessing which dates to query.
    """
    context = [instructions, f"\nToday is {today.isoformat()}."]
    if notes:
        context.append("\nStanding facts about this athlete:")
        context.extend(f"- ({kind}) {content}" for kind, content in notes)
    else:
        context.append("\nNo standing facts recorded for this athlete yet.")
    return "\n".join(context)


def standing_facts(session: Session) -> list[tuple[str, str]]:
    # Ordered by kind then id, so the prompt is the same text on every call and
    # in both apps. Kind alone left ties in whatever order the database chose.
    notes = session.scalars(
        select(CoachNote)
        .where(CoachNote.is_active.is_(True))
        .order_by(CoachNote.kind, CoachNote.id)
    ).all()
    return [(n.kind, n.content) for n in notes]


def _system_instruction(session: Session) -> str:
    return build_system_instruction(
        SYSTEM_INSTRUCTIONS, dt.date.today(), standing_facts(session)
    )


def _load_history(session: Session, conversation_id: int) -> list[types.Content]:
    rows = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.id)
    ).all()
    return [
        types.Content(
            role=row.role,
            parts=[types.Part.model_validate(part) for part in row.content],
        )
        for row in rows
    ]


def _persist(session: Session, conversation_id: int, content: types.Content) -> None:
    session.add(
        ChatMessage(
            conversation_id=conversation_id,
            role=content.role or "user",
            content=[p.model_dump(mode="json", exclude_none=True) for p in content.parts or []],
        )
    )
    session.commit()


def merge_stream_parts(parts: list[types.Part]) -> list[types.Part]:
    """Collapse the streamed text fragments back into whole parts.

    Streaming splits a reply across many small text parts. Function calls and any
    part carrying a thought signature pass through untouched — Gemini needs those
    echoed back verbatim on the next turn or it loses its reasoning context.
    """
    merged: list[types.Part] = []
    for part in parts:
        plain_text = (
            part.text is not None
            and not part.thought
            and part.function_call is None
            and part.thought_signature is None
        )
        if plain_text and merged:
            previous = merged[-1]
            if (
                previous.text is not None
                and not previous.thought
                and previous.function_call is None
                and previous.thought_signature is None
            ):
                merged[-1] = types.Part(text=(previous.text or "") + part.text)
                continue
        merged.append(part)
    return merged


def ensure_conversation(session: Session, conversation_id: int | None) -> Conversation:
    if conversation_id is not None:
        found = session.get(Conversation, conversation_id)
        if found is not None:
            return found
    conversation = Conversation()
    session.add(conversation)
    session.commit()
    return conversation


async def _run_tool(session: Session, name: str, args: dict) -> dict:
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": f"No such tool {name!r}."}
    try:
        return await asyncio.to_thread(handler, session, **args)
    except Exception as exc:  # surfaced to the model so it can correct itself
        await asyncio.to_thread(session.rollback)
        return {"error": f"{type(exc).__name__}: {exc}"}


def sources_in(contents: list[types.Content]) -> list[str]:
    """What the model's figures may legitimately come from.

    Tool results and the athlete's own words, anywhere in the conversation. Not
    the model's earlier replies — they are not evidence — and not the
    harness's corrections, which quote the unverified figures back.
    """
    sources: list[str] = []
    for content in contents:
        if content.role != "user":
            continue
        for part in content.parts or []:
            if part.text is not None:
                if not part.text.startswith(CORRECTION_PREFIX):
                    sources.append(part.text)
            elif part.function_response is not None:
                response = part.function_response
                sources.append(
                    json.dumps({"name": response.name, "response": response.response}, default=str)
                )
    return sources


def _millis(since: float) -> int:
    return int((time.perf_counter() - since) * 1000)


def _step(kind: str, label: str, detail: str, since: float, failed: bool = False) -> dict:
    return {"kind": kind, "label": label, "detail": detail, "millis": _millis(since),
            "failed": failed}


def _summarise(args: dict) -> str:
    return ", ".join(
        f"{key}={value if isinstance(value, str) else json.dumps(value, default=str)}"
        for key, value in args.items()
    )


def _usage(metadata) -> dict:
    def count(name: str) -> int:
        return int(getattr(metadata, name, None) or 0) if metadata is not None else 0

    return {
        "prompt": count("prompt_token_count"),
        "output": count("candidates_token_count"),
        "total": count("total_token_count"),
    }


async def stream_turn(
    session: Session, conversation: Conversation, user_text: str
) -> AsyncIterator[dict]:
    """Run one user turn to completion, yielding SSE payloads as it goes.

    Wrapped in the harness: the final answer's figures are checked against
    what the tools returned, an answer that fails is sent back once, and a
    trace of every step is emitted at the end. Because tokens stream as they
    arrive, an answer that gets sent back has already been shown — so a
    `retry` event tells the page to replace it, rather than the correction
    happening out of sight.
    """
    client = _client(session)
    model, _ = settings_store.gemini_model(session)
    started = time.perf_counter()
    steps: list[dict] = []
    usage = {"prompt": 0, "output": 0, "total": 0}
    retried = False
    grounding = Grounding()

    contents = _load_history(session, conversation.id)
    user_turn = types.Content(role="user", parts=[types.Part(text=user_text)])
    contents.append(user_turn)
    _persist(session, conversation.id, user_turn)

    yield {"type": "start", "conversation_id": conversation.id}

    config = types.GenerateContentConfig(
        system_instruction=_system_instruction(session),
        tools=[types.Tool(function_declarations=declarations())],
        # Manual: the SDK would otherwise call the handlers itself, with no session.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    for _ in range(MAX_TURNS):
        streamed: list[types.Part] = []
        call_started = time.perf_counter()
        metadata = None

        stream = await client.aio.models.generate_content_stream(
            model=model, contents=contents, config=config
        )
        async for chunk in stream:
            # Usage arrives cumulatively; the last chunk that carries it wins.
            if getattr(chunk, "usage_metadata", None) is not None:
                metadata = chunk.usage_metadata
            if not chunk.candidates:
                continue
            candidate = chunk.candidates[0]
            for part in candidate.content.parts if candidate.content else []:
                if part.text and not part.thought:
                    yield {"type": "token", "text": part.text}
                streamed.append(part)

        spent = _usage(metadata)
        for key in usage:
            usage[key] += spent[key]
        spent_text = f"{spent['total']} tokens" if spent["total"] else ""
        steps.append(_step("model", model, spent_text, call_started))

        parts = merge_stream_parts(streamed)
        if not parts:
            yield {"type": "error", "message": "The model returned an empty response."}
            return

        model_turn = types.Content(role="model", parts=parts)
        contents.append(model_turn)
        _persist(session, conversation.id, model_turn)

        calls = [p.function_call for p in parts if p.function_call is not None]
        if not calls:
            text = "".join(p.text for p in parts if p.text and not p.thought)
            check_started = time.perf_counter()
            grounding = check(text, sources_in(contents))
            steps.append(
                _step("check", "grounding", describe(grounding), check_started,
                      failed=not grounding.ok)
            )
            # One chance to correct itself; more would let a model that cannot
            # find a figure burn the round budget looking for it.
            if not grounding.ok and not retried:
                retried = True
                steps.append({"kind": "retry", "label": "sent back",
                              "detail": ", ".join(grounding.unverified), "millis": 0,
                              "failed": False})
                yield {"type": "retry", "unverified": grounding.unverified}
                correction_turn = types.Content(
                    role="user", parts=[types.Part(text=correction(grounding))]
                )
                contents.append(correction_turn)
                _persist(session, conversation.id, correction_turn)
                continue
            break

        response_parts: list[types.Part] = []
        for call in calls:
            name = call.name or ""
            args = dict(call.args or {})
            yield {"type": "tool", "name": name, "input": args}
            tool_started = time.perf_counter()
            result = await _run_tool(session, name, args)
            steps.append(
                _step("tool", name, _summarise(args), tool_started, failed="error" in result)
            )
            response_parts.append(
                types.Part.from_function_response(name=name, response=result)
            )

        # Function responses go back on the user turn; Gemini roles are user/model only.
        tool_turn = types.Content(role="user", parts=response_parts)
        contents.append(tool_turn)
        _persist(session, conversation.id, tool_turn)
    else:
        yield {"type": "error", "message": f"Stopped after {MAX_TURNS} tool rounds."}
        return

    yield {"type": "grounding", **grounding.as_dict(), "retried": retried}
    yield {"type": "trace", "steps": steps, "usage": usage, "total_millis": _millis(started)}
    yield {"type": "done"}


if __name__ == "__main__":
    # `uv run python -m app.agent.coach` — which models this key can actually call.
    for model in _client().models.list():
        if "generateContent" in (model.supported_actions or []):
            print(f"{model.name}\t{model.display_name}")

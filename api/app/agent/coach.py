"""The coaching agent loop, on the Gemini API.

Function calling is driven manually rather than through the SDK's automatic mode,
because each turn has to emit SSE events per tool call, persist every content part
to `chat_messages`, and hand each handler the request's SQLAlchemy session.

`tools.py` stays provider-neutral; the conversion to Gemini declarations lives here.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import AsyncIterator

from google import genai
from google.genai import types
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.tools import HANDLERS, TOOL_SPECS
from app.config import settings
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


def _client() -> genai.Client:
    # An unset setting does not mean no credentials: the bare constructor picks up
    # GEMINI_API_KEY or GOOGLE_API_KEY from the environment.
    if settings.gemini_api_key:
        return genai.Client(api_key=settings.gemini_api_key)
    return genai.Client()


def declarations() -> list[types.FunctionDeclaration]:
    return [
        types.FunctionDeclaration(
            name=spec["name"],
            description=spec["description"],
            parameters_json_schema=spec["parameters"],
        )
        for spec in TOOL_SPECS
    ]


def _system_instruction(session: Session) -> str:
    notes = session.scalars(
        select(CoachNote).where(CoachNote.is_active.is_(True)).order_by(CoachNote.kind)
    ).all()

    context = [SYSTEM_INSTRUCTIONS, f"\nToday is {dt.date.today().isoformat()}."]
    if notes:
        context.append("\nStanding facts about this athlete:")
        context.extend(f"- ({n.kind}) {n.content}" for n in notes)
    else:
        context.append("\nNo standing facts recorded for this athlete yet.")
    return "\n".join(context)


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


async def stream_turn(
    session: Session, conversation: Conversation, user_text: str
) -> AsyncIterator[dict]:
    """Run one user turn to completion, yielding SSE payloads as it goes."""
    client = _client()

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

        stream = await client.aio.models.generate_content_stream(
            model=settings.gemini_model, contents=contents, config=config
        )
        async for chunk in stream:
            if not chunk.candidates:
                continue
            candidate = chunk.candidates[0]
            for part in candidate.content.parts if candidate.content else []:
                if part.text and not part.thought:
                    yield {"type": "token", "text": part.text}
                streamed.append(part)

        parts = merge_stream_parts(streamed)
        if not parts:
            yield {"type": "error", "message": "The model returned an empty response."}
            return

        model_turn = types.Content(role="model", parts=parts)
        contents.append(model_turn)
        _persist(session, conversation.id, model_turn)

        calls = [p.function_call for p in parts if p.function_call is not None]
        if not calls:
            break

        response_parts: list[types.Part] = []
        for call in calls:
            name = call.name or ""
            args = dict(call.args or {})
            yield {"type": "tool", "name": name, "input": args}
            result = await _run_tool(session, name, args)
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

    yield {"type": "done"}


if __name__ == "__main__":
    # `uv run python -m app.agent.coach` — which models this key can actually call.
    for model in _client().models.list():
        if "generateContent" in (model.supported_actions or []):
            print(f"{model.name}\t{model.display_name}")

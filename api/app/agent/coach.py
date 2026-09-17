"""The coaching agent loop.

This is a manual loop rather than the SDK tool runner because each turn has to do
three things the runner does not expose together: emit SSE events per tool call,
persist every content block to `chat_messages`, and hand each handler the request's
SQLAlchemy session.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from collections.abc import AsyncIterator

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.tools import HANDLERS, TOOL_SPECS
from app.config import settings
from app.models import ChatMessage, CoachNote, Conversation

MAX_TURNS = 12
MAX_TOKENS = 16000

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


def _client() -> anthropic.AsyncAnthropic:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set; the coach cannot run.")
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


def _system_blocks(session: Session) -> list[dict]:
    notes = session.scalars(
        select(CoachNote).where(CoachNote.is_active.is_(True)).order_by(CoachNote.kind)
    ).all()

    context = [f"Today is {dt.date.today().isoformat()}."]
    if notes:
        context.append("\nStanding facts about this athlete:")
        context.extend(f"- ({n.kind}) {n.content}" for n in notes)
    else:
        context.append("\nNo standing facts recorded for this athlete yet.")

    # The instructions are the stable cache prefix; date and notes change, so they
    # sit after the breakpoint.
    return [
        {
            "type": "text",
            "text": SYSTEM_INSTRUCTIONS,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": "\n".join(context)},
    ]


def _load_history(session: Session, conversation_id: int) -> list[dict]:
    rows = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.id)
    ).all()
    return [{"role": r.role, "content": r.content} for r in rows]


def _persist(session: Session, conversation_id: int, role: str, content) -> None:
    session.add(ChatMessage(conversation_id=conversation_id, role=role, content=content))
    session.commit()


def ensure_conversation(session: Session, conversation_id: int | None) -> Conversation:
    if conversation_id is not None:
        found = session.get(Conversation, conversation_id)
        if found is not None:
            return found
    conversation = Conversation()
    session.add(conversation)
    session.commit()
    return conversation


async def _run_tool(session: Session, name: str, args: dict) -> tuple[str, bool]:
    handler = HANDLERS.get(name)
    if handler is None:
        return f"Error: no such tool {name!r}.", True
    try:
        result = await asyncio.to_thread(handler, session, **args)
        return json.dumps(result, default=str), False
    except Exception as exc:  # surfaced to the model so it can correct itself
        await asyncio.to_thread(session.rollback)
        return f"Error running {name}: {exc}", True


async def stream_turn(
    session: Session, conversation: Conversation, user_text: str
) -> AsyncIterator[dict]:
    """Run one user turn to completion, yielding SSE payloads as it goes."""
    client = _client()

    messages = _load_history(session, conversation.id)
    messages.append({"role": "user", "content": user_text})
    _persist(session, conversation.id, "user", user_text)

    yield {"type": "start", "conversation_id": conversation.id}

    system = _system_blocks(session)

    for _ in range(MAX_TURNS):
        async with client.beta.messages.stream(
            model=settings.anthropic_model,
            max_tokens=MAX_TOKENS,
            system=system,
            thinking={"type": "adaptive"},
            tools=TOOL_SPECS,
            messages=messages,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield {"type": "token", "text": event.delta.text}
            final = await stream.get_final_message()

        content = [block.model_dump(mode="json") for block in final.content]
        messages.append({"role": "assistant", "content": content})
        _persist(session, conversation.id, "assistant", content)

        if final.stop_reason == "refusal":
            yield {"type": "error", "message": "The model declined to answer that."}
            return

        if final.stop_reason != "tool_use":
            break

        tool_results = []
        for block in final.content:
            if block.type != "tool_use":
                continue
            yield {"type": "tool", "name": block.name, "input": block.input}
            payload, is_error = await _run_tool(session, block.name, dict(block.input))
            result_block = {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": payload,
            }
            if is_error:
                result_block["is_error"] = True
            tool_results.append(result_block)

        messages.append({"role": "user", "content": tool_results})
        _persist(session, conversation.id, "user", tool_results)
    else:
        yield {"type": "error", "message": f"Stopped after {MAX_TURNS} tool rounds."}
        return

    yield {"type": "done"}

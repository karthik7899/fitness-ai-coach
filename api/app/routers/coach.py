from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.agent.coach import ensure_conversation, stream_turn
from app.db import SessionLocal, get_session
from app.models import ChatMessage, CoachNote, Conversation
from app.schemas import ChatIn, CoachNoteIn

router = APIRouter(prefix="/api/coach", tags=["coach"])


@router.post("/chat")
async def chat(payload: ChatIn) -> EventSourceResponse:
    async def events() -> AsyncIterator[dict]:
        # A dedicated session: the request-scoped dependency would be torn down
        # before the stream finishes.
        with SessionLocal() as session:
            conversation = ensure_conversation(session, payload.conversation_id)
            try:
                async for event in stream_turn(session, conversation, payload.message):
                    yield {"data": json.dumps(event)}
            except Exception as exc:
                yield {"data": json.dumps({"type": "error", "message": str(exc)})}

    return EventSourceResponse(events())


@router.get("/conversations")
def list_conversations(session: Session = Depends(get_session)):
    return session.scalars(
        select(Conversation).order_by(Conversation.created_at.desc()).limit(50)
    ).all()


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, session: Session = Depends(get_session)):
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, "No such conversation.")
    messages = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.id)
    ).all()
    return {
        "id": conversation.id,
        "title": conversation.title,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
    }


@router.get("/notes")
def list_notes(session: Session = Depends(get_session)):
    return session.scalars(
        select(CoachNote).where(CoachNote.is_active.is_(True)).order_by(CoachNote.kind)
    ).all()


@router.post("/notes", status_code=201)
def create_note(payload: CoachNoteIn, session: Session = Depends(get_session)):
    note = CoachNote(kind=payload.kind, content=payload.content)
    session.add(note)
    session.commit()
    return note


@router.delete("/notes/{note_id}", status_code=204)
def deactivate_note(note_id: int, session: Session = Depends(get_session)):
    note = session.get(CoachNote, note_id)
    if note is None:
        raise HTTPException(404, "No such note.")
    note.is_active = False
    session.commit()

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app import settings_store
from app.db import get_session

router = APIRouter(prefix="/api/settings", tags=["settings"])


class GeminiIn(BaseModel):
    api_key: str | None = None
    model: str | None = None

    @field_validator("api_key", "model")
    @classmethod
    def strip_blank(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None


def _readable(error: Exception) -> str:
    """Google's errors arrive as a wall of JSON; say the useful part."""
    text = str(error)
    if "API_KEY_INVALID" in text or "API key not valid" in text:
        return "That key was rejected by Google. Check it was copied in full."
    if "PERMISSION_DENIED" in text or "SERVICE_DISABLED" in text:
        return "The key is valid but lacks access to the Gemini API."
    if "RESOURCE_EXHAUSTED" in text or "429" in text:
        return "The key is valid but currently rate limited. Try again shortly."
    return text.split("\n")[0][:200]


async def _verify(api_key: str, model: str) -> tuple[bool, str | None]:
    """Confirm the key works before the user discovers it at chat time."""
    from google import genai

    def check() -> tuple[bool, str | None]:
        try:
            client = genai.Client(api_key=api_key)
            names = {
                m.name.split("/")[-1]
                for m in client.models.list()
                if "generateContent" in (m.supported_actions or [])
            }
        except Exception as exc:
            return False, _readable(exc)
        if names and model not in names:
            return False, f"The key works, but {model} is not available to it."
        return True, None

    return await asyncio.to_thread(check)


@router.get("")
def read(session: Session = Depends(get_session)):
    """The key itself is never returned — only whether one is set and its last digits."""
    return settings_store.describe(session)


@router.put("/gemini")
async def write(payload: GeminiIn, session: Session = Depends(get_session)):
    stored = settings_store.get(session, settings_store.GEMINI) or {}
    if payload.api_key:
        stored["api_key"] = payload.api_key
    if payload.model:
        stored["model"] = payload.model
    if not stored:
        raise HTTPException(400, "Provide an API key or a model.")

    settings_store.put(session, settings_store.GEMINI, stored)

    key, _ = settings_store.gemini_api_key(session)
    model, _ = settings_store.gemini_model(session)
    verified, error = (False, "No API key set.") if not key else await _verify(key, model)

    return {**settings_store.describe(session), "verified": verified, "error": error}


@router.delete("/gemini", status_code=204)
def clear(session: Session = Depends(get_session)):
    settings_store.delete(session, settings_store.GEMINI)

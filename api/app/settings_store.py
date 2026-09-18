"""Settings entered through the UI, layered over the ones from the environment.

A value stored here wins over the matching `.env` entry: the UI is the more
deliberate, more recent action, and `.env` is for headless setup. Which source
won is always reported back, so the precedence is never a surprise — a shadowed
credential that nobody can see is a genuinely nasty thing to debug.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting
from app.upsert import upsert

GEMINI = "gemini"
INGEST = "ingest"


def get(session: Session, key: str) -> dict | None:
    row = session.get(AppSetting, key)
    return row.value if row else None


def put(session: Session, key: str, value: dict) -> None:
    stmt = upsert(
        session, AppSetting, {"key": key, "value": value}, ["key"], set_={"value": value}
    )
    session.execute(stmt)
    session.commit()


def delete(session: Session, key: str) -> None:
    row = session.get(AppSetting, key)
    if row is not None:
        session.delete(row)
        session.commit()


def gemini_api_key(session: Session) -> tuple[str | None, str | None]:
    """Returns (key, source) where source is 'ui', 'env', or None."""
    stored = get(session, GEMINI) or {}
    if stored.get("api_key"):
        return stored["api_key"], "ui"
    if settings.gemini_api_key:
        return settings.gemini_api_key, "env"
    return None, None


def gemini_model(session: Session) -> tuple[str, str]:
    stored = get(session, GEMINI) or {}
    if stored.get("model"):
        return stored["model"], "ui"
    return settings.gemini_model, "env"


def watch_dirs(session: Session) -> tuple[list[Path], str]:
    """Folders to read in place. Set here, they replace the .env list entirely."""
    stored = get(session, INGEST) or {}
    if stored.get("watch_dirs") is not None:
        return [Path(p).expanduser() for p in stored["watch_dirs"]], "ui"
    return settings.watch_paths, "env"


def mask(secret: str) -> str:
    """Enough to recognise which key is set, not enough to use it."""
    return f"…{secret[-4:]}" if len(secret) > 4 else "…"


def describe(session: Session) -> dict[str, Any]:
    key, key_source = gemini_api_key(session)
    model, model_source = gemini_model(session)
    watched, watch_source = watch_dirs(session)
    return {
        "ingest": {
            "inbox_dir": str(settings.inbox_path),
            "watch_dirs": [
                {"path": str(p), "exists": p.is_dir()} for p in watched
            ],
            "watch_source": watch_source,
        },
        "gemini": {
            "configured": key is not None,
            "source": key_source,
            "hint": mask(key) if key else None,
            # Only a key stored here can be removed here. An env key would need
            # the .env edited, so don't offer a button that does nothing.
            "can_clear": key_source == "ui",
            "model": model,
            "model_source": model_source,
        }
    }

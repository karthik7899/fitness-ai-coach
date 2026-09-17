"""Background sync.

Runs only inside the FastAPI lifespan, so CLI commands and tests never trigger
network calls. A source that is not connected is skipped quietly rather than
recorded as a failed run — an unconfigured adapter is not an error.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.adapters import health_connect, inbox, strava
from app.config import settings
from app.db import SessionLocal

log = logging.getLogger(__name__)

@dataclass(frozen=True)
class Adapter:
    source: str
    is_connected: Callable[[Session], bool]
    sync: Callable[[Session], object]
    # None means the shared remote-sync interval; the inbox polls a local
    # directory, so it can run often enough that a dropped file lands quickly.
    every_minutes: int | None = None


ADAPTERS: list[Adapter] = [
    Adapter(inbox.SOURCE, inbox.is_connected, inbox.sync, every_minutes=2),
    Adapter(strava.SOURCE, strava.is_connected, strava.sync),
    Adapter(health_connect.SOURCE, health_connect.is_connected, health_connect.sync),
]


def run_adapter(source: str, is_connected: Callable, sync: Callable) -> None:
    with SessionLocal() as session:
        if not is_connected(session):
            log.info("%s is not connected; skipping scheduled sync.", source)
            return
        try:
            outcome = sync(session)
            log.info(
                "%s sync complete: read %s, wrote %s.", source, outcome.read, outcome.written
            )
        except Exception:
            # sync_run already recorded the failure; never let it kill the scheduler.
            log.exception("%s sync failed.", source)


def sync_all() -> None:
    for adapter in ADAPTERS:
        run_adapter(adapter.source, adapter.is_connected, adapter.sync)


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    for adapter in ADAPTERS:
        minutes = adapter.every_minutes or settings.sync_interval_minutes
        scheduler.add_job(
            run_adapter,
            trigger="interval",
            minutes=minutes,
            args=[adapter.source, adapter.is_connected, adapter.sync],
            id=f"sync_{adapter.source}",
            # Overlapping runs would double-fetch; a missed run just waits for the next.
            max_instances=1,
            coalesce=True,
            jitter=min(60, minutes * 30),
        )
    return scheduler

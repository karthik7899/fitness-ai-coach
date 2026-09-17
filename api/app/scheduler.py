"""Background sync.

Runs only inside the FastAPI lifespan, so CLI commands and tests never trigger
network calls. A source that is not connected is skipped quietly rather than
recorded as a failed run — an unconfigured adapter is not an error.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.adapters import health_connect, strava
from app.config import settings
from app.db import SessionLocal

log = logging.getLogger(__name__)

Adapter = tuple[str, Callable[[Session], bool], Callable[[Session], object]]

ADAPTERS: list[Adapter] = [
    (strava.SOURCE, strava.is_connected, strava.sync),
    (health_connect.SOURCE, health_connect.is_connected, health_connect.sync),
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
    for source, is_connected, sync in ADAPTERS:
        run_adapter(source, is_connected, sync)


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    for source, is_connected, sync in ADAPTERS:
        scheduler.add_job(
            run_adapter,
            trigger="interval",
            minutes=settings.sync_interval_minutes,
            args=[source, is_connected, sync],
            id=f"sync_{source}",
            # Overlapping runs would double-fetch; a missed run just waits for the next.
            max_instances=1,
            coalesce=True,
            jitter=60,
        )
    return scheduler

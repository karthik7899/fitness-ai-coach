"""Shared adapter machinery.

Every adapter follows the same path: fetch -> store_raw -> normalise -> upsert.
Storing the raw payload first means the canonical tables can always be rebuilt
without re-contacting an upstream API.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import OAuthToken, RawRecord, SyncRun


@dataclass
class SyncOutcome:
    read: int = 0
    written: int = 0


def content_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def store_raw(
    session: Session,
    source: str,
    kind: str,
    payload: dict,
    external_id: str | None = None,
) -> int | None:
    """Append a raw payload. Returns the new row id, or None if already stored."""
    stmt = (
        pg_insert(RawRecord)
        .values(
            source=source,
            kind=kind,
            external_id=external_id,
            payload=payload,
            content_hash=content_hash(payload),
        )
        .on_conflict_do_nothing(constraint="uq_raw_records_source_hash")
        .returning(RawRecord.id)
    )
    return session.execute(stmt).scalar_one_or_none()


def get_token(session: Session, service: str) -> dict | None:
    row = session.get(OAuthToken, service)
    return row.payload if row else None


def save_token(session: Session, service: str, payload: dict) -> None:
    stmt = (
        pg_insert(OAuthToken)
        .values(service=service, payload=payload)
        .on_conflict_do_update(
            index_elements=[OAuthToken.service],
            set_={"payload": payload, "updated_at": dt.datetime.now(dt.UTC)},
        )
    )
    session.execute(stmt)
    session.commit()


@contextmanager
def sync_run(session: Session, source: str) -> Iterator[SyncOutcome]:
    """Bookkeeping around one adapter run, recorded in `sync_runs` either way."""
    run = SyncRun(source=source, status="running")
    session.add(run)
    session.commit()

    outcome = SyncOutcome()
    try:
        yield outcome
    except Exception as exc:
        session.rollback()
        run = session.get(SyncRun, run.id)
        run.status = "failed"
        run.error = str(exc)[:2000]
        run.finished_at = dt.datetime.now(dt.UTC)
        session.commit()
        raise
    else:
        run.status = "ok"
        run.records_read = outcome.read
        run.records_written = outcome.written
        run.finished_at = dt.datetime.now(dt.UTC)
        session.commit()

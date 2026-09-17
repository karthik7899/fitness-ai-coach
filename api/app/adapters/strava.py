"""Strava cardio ingestion.

Pull adapter: OAuth2 authorisation code flow, then incremental activity fetch
keyed on the newest activity already stored.
"""

from __future__ import annotations

import time
from decimal import Decimal

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.adapters.base import SyncOutcome, get_token, save_token, store_raw, sync_run
from app.config import settings
from app.models import Activity

SOURCE = "strava"
AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
REDIRECT_URI = "http://localhost:8000/api/sync/strava/callback"


def authorize_url() -> str:
    return (
        f"{AUTH_URL}?client_id={settings.strava_client_id}"
        f"&redirect_uri={REDIRECT_URI}"
        "&response_type=code&approval_prompt=auto&scope=activity:read_all"
    )


def exchange_code(session: Session, code: str) -> dict:
    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": settings.strava_client_id,
            "client_secret": settings.strava_client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    save_token(session, SOURCE, payload)
    return payload


def _access_token(session: Session) -> str | None:
    token = get_token(session, SOURCE)
    if not token:
        return None

    # Refresh a little early so a long sync cannot expire mid-run.
    if token.get("expires_at", 0) - 300 > time.time():
        return token.get("access_token")

    refresh_token = token.get("refresh_token")
    if not refresh_token:
        return None

    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": settings.strava_client_id,
            "client_secret": settings.strava_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    response.raise_for_status()
    refreshed = {**token, **response.json()}
    save_token(session, SOURCE, refreshed)
    return refreshed.get("access_token")


def is_connected(session: Session) -> bool:
    return get_token(session, SOURCE) is not None


def _decimal(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _upsert_activity(session: Session, payload: dict, raw_id: int | None) -> None:
    values = {
        "source": SOURCE,
        "external_id": str(payload["id"]),
        "sport_type": payload.get("sport_type") or payload.get("type") or "Unknown",
        "name": payload.get("name"),
        "started_at": payload.get("start_date"),
        "timezone": payload.get("timezone"),
        "distance_m": _decimal(payload.get("distance")),
        "moving_time_s": payload.get("moving_time"),
        "elapsed_time_s": payload.get("elapsed_time"),
        "elevation_gain_m": _decimal(payload.get("total_elevation_gain")),
        "average_hr": _decimal(payload.get("average_heartrate")),
        "max_hr": _decimal(payload.get("max_heartrate")),
        "average_speed_ms": _decimal(payload.get("average_speed")),
        "calories": _decimal(payload.get("calories")),
        "raw_record_id": raw_id,
    }
    stmt = (
        pg_insert(Activity)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_activities_source_external",
            set_={k: v for k, v in values.items() if k not in ("source", "external_id")},
        )
    )
    session.execute(stmt)


def sync(session: Session) -> SyncOutcome:
    with sync_run(session, SOURCE) as outcome:
        token = _access_token(session)
        if not token:
            raise RuntimeError("Strava is not connected. Authorise it first.")

        latest = session.scalar(
            select(func.max(Activity.started_at)).where(Activity.source == SOURCE)
        )
        params: dict = {"per_page": 100}
        if latest:
            params["after"] = int(latest.timestamp())

        page = 1
        while True:
            response = httpx.get(
                ACTIVITIES_URL,
                headers={"Authorization": f"Bearer {token}"},
                params={**params, "page": page},
                timeout=60,
            )
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break

            for payload in batch:
                outcome.read += 1
                raw_id = store_raw(
                    session,
                    SOURCE,
                    "activity",
                    payload,
                    external_id=str(payload["id"]),
                )
                _upsert_activity(session, payload, raw_id)
                outcome.written += 1

            session.commit()
            if len(batch) < params["per_page"]:
                break
            page += 1

        return outcome

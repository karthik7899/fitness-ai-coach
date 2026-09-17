from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import health_connect, strava
from app.db import get_session
from app.models import SyncRun

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    latest = {}
    for source in (strava.SOURCE, health_connect.SOURCE):
        run = session.scalar(
            select(SyncRun)
            .where(SyncRun.source == source)
            .order_by(SyncRun.started_at.desc())
            .limit(1)
        )
        latest[source] = {
            "connected": (
                strava.is_connected(session)
                if source == strava.SOURCE
                else health_connect.is_connected(session)
            ),
            "last_run": None
            if run is None
            else {
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "status": run.status,
                "records_written": run.records_written,
                "error": run.error,
            },
        }
    return latest


@router.get("/strava/authorize")
def strava_authorize() -> RedirectResponse:
    return RedirectResponse(strava.authorize_url())


@router.get("/strava/callback")
def strava_callback(code: str, session: Session = Depends(get_session)):
    strava.exchange_code(session, code)
    return RedirectResponse("http://localhost:5173/?connected=strava")


@router.post("/strava")
def run_strava(session: Session = Depends(get_session)):
    try:
        outcome = strava.sync(session)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"read": outcome.read, "written": outcome.written}


@router.post("/health-connect")
def run_health_connect(session: Session = Depends(get_session)):
    try:
        outcome = health_connect.sync(session)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"read": outcome.read, "written": outcome.written}

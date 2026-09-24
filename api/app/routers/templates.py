"""Starter workouts: list them, start one, see progress through it, finish."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import workouts
from app.db import get_session

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("")
def list_templates():
    return workouts.document()["templates"]


@router.get("/active")
def active_plan(session: Session = Depends(get_session)):
    """Today's plan, or null when none was started today."""
    return workouts.plan(session, dt.date.today())


@router.post("/{template_id}/start")
def start(template_id: str, session: Session = Depends(get_session)):
    started = workouts.start(session, template_id, dt.date.today())
    if started is None:
        raise HTTPException(404, f"No workout named {template_id!r}.")
    return started


@router.delete("/active", status_code=204)
def finish(session: Session = Depends(get_session)):
    workouts.finish(session)

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import records, workouts
from app.db import get_session
from app.models import Exercise, SetEntry, Workout
from app.schemas import (
    ExerciseIn,
    ExerciseOut,
    SetIn,
    SetOut,
    SetUpdate,
    WorkoutIn,
    WorkoutOut,
)

router = APIRouter(prefix="/api", tags=["training"])


@router.get("/exercises", response_model=list[ExerciseOut])
def list_exercises(search: str | None = None, session: Session = Depends(get_session)):
    stmt = select(Exercise).where(Exercise.is_archived.is_(False))
    if search:
        stmt = stmt.where(Exercise.name.ilike(f"%{search}%"))
    return session.scalars(stmt.order_by(Exercise.name)).all()


@router.get("/exercises/duplicates")
def exercise_duplicates(session: Session = Depends(get_session)):
    """Exercises that exist under more than one of their names, and which is kept."""
    return [m.as_dict() for m in workouts.duplicates(session)]


@router.post("/exercises/duplicates/merge")
def merge_exercise_duplicates(session: Session = Depends(get_session)):
    merged = workouts.merge_duplicates(session)
    return {"merged": sum(len(m.drop) for m in merged), "merges": [m.as_dict() for m in merged]}


@router.post("/exercises", response_model=ExerciseOut, status_code=201)
def create_exercise(payload: ExerciseIn, session: Session = Depends(get_session)):
    existing = session.scalar(
        select(Exercise).where(func.lower(Exercise.name) == payload.name.strip().lower())
    )
    if existing:
        raise HTTPException(409, f"Exercise {payload.name!r} already exists.")
    exercise = Exercise(**payload.model_dump())
    exercise.name = exercise.name.strip()
    session.add(exercise)
    session.commit()
    return exercise


@router.get("/workouts", response_model=list[WorkoutOut])
def list_workouts(
    start: dt.date | None = None,
    end: dt.date | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
):
    stmt = select(Workout).options(selectinload(Workout.sets))
    if start:
        stmt = stmt.where(Workout.performed_on >= start)
    if end:
        stmt = stmt.where(Workout.performed_on <= end)
    stmt = stmt.order_by(Workout.performed_on.desc()).limit(limit)
    return session.scalars(stmt).all()


@router.post("/workouts", response_model=WorkoutOut, status_code=201)
def create_workout(payload: WorkoutIn, session: Session = Depends(get_session)):
    existing = session.scalar(
        select(Workout).where(
            Workout.performed_on == payload.performed_on, Workout.source == "manual"
        )
    )
    if existing:
        return existing
    workout = Workout(performed_on=payload.performed_on, notes=payload.notes, source="manual")
    session.add(workout)
    session.commit()
    return workout


@router.get("/workouts/{workout_id}", response_model=WorkoutOut)
def get_workout(workout_id: int, session: Session = Depends(get_session)):
    workout = session.get(Workout, workout_id)
    if workout is None:
        raise HTTPException(404, "No such workout.")
    return workout


@router.post("/workouts/{workout_id}/sets", response_model=SetOut, status_code=201)
def add_set(workout_id: int, payload: SetIn, session: Session = Depends(get_session)):
    if session.get(Workout, workout_id) is None:
        raise HTTPException(404, "No such workout.")
    if session.get(Exercise, payload.exercise_id) is None:
        raise HTTPException(404, "No such exercise.")

    position = (
        session.scalar(
            select(func.coalesce(func.max(SetEntry.position), 0)).where(
                SetEntry.workout_id == workout_id
            )
        )
        or 0
    ) + 1

    data = payload.model_dump()
    for decimal_field in ("weight_kg", "rpe", "distance_m"):
        if data[decimal_field] is not None:
            data[decimal_field] = Decimal(str(data[decimal_field]))

    entry = SetEntry(workout_id=workout_id, position=position, **data)
    session.add(entry)
    session.commit()
    return entry


@router.delete("/sets/{set_id}", status_code=204)
def delete_set(set_id: int, session: Session = Depends(get_session)):
    entry = session.get(SetEntry, set_id)
    if entry is None:
        raise HTTPException(404, "No such set.")
    session.delete(entry)
    session.commit()


@router.put("/sets/{set_id}", response_model=SetOut)
def update_set(set_id: int, payload: SetUpdate, session: Session = Depends(get_session)):
    """Correct a logged set. Its exercise, workout and place in it stay."""
    entry = session.get(SetEntry, set_id)
    if entry is None:
        raise HTTPException(404, "No such set.")
    entry.weight_kg = Decimal(str(payload.weight_kg)) if payload.weight_kg is not None else None
    entry.reps = payload.reps
    entry.rpe = Decimal(str(payload.rpe)) if payload.rpe is not None else None
    entry.is_warmup = payload.is_warmup
    session.commit()
    return entry


@router.get("/sets/{set_id}/records")
def set_records(set_id: int, session: Session = Depends(get_session)):
    """The personal records this set broke, for the alert after logging it."""
    found = records.for_set(session, set_id)
    if found is None:
        raise HTTPException(404, "No such set.")
    exercise, beaten = found
    return {"exercise": exercise, "records": [r.as_dict() for r in beaten]}

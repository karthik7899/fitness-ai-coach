from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class ExerciseIn(BaseModel):
    name: str
    category: str | None = None
    modality: str = "weight_reps"
    primary_muscles: list[str] = Field(default_factory=list)
    secondary_muscles: list[str] = Field(default_factory=list)


class ExerciseOut(ExerciseIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_archived: bool


class SetIn(BaseModel):
    exercise_id: int
    reps: int | None = None
    weight_kg: float | None = None
    rpe: float | None = None
    distance_m: float | None = None
    duration_s: int | None = None
    is_warmup: bool = False
    notes: str | None = None


class SetUpdate(BaseModel):
    """A correction to a logged set: the fields a typo can get wrong."""

    weight_kg: float | None = None
    reps: int | None = None
    rpe: float | None = Field(default=None, ge=1, le=10)
    is_warmup: bool = False


class SetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exercise_id: int
    position: int
    reps: int | None
    weight_kg: float | None
    rpe: float | None
    distance_m: float | None
    duration_s: int | None
    is_warmup: bool
    notes: str | None


class WorkoutIn(BaseModel):
    performed_on: dt.date
    notes: str | None = None


class WorkoutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    performed_on: dt.date
    notes: str | None
    source: str
    sets: list[SetOut] = Field(default_factory=list)


class ChatIn(BaseModel):
    message: str
    conversation_id: int | None = None


class CoachNoteIn(BaseModel):
    kind: str
    content: str

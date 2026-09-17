"""Canonical training data model.

Storage is always SI: kilograms, metres, seconds. Unit conversion happens at the
display edge only, so no row ever carries its own unit for weight or distance.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Sources that may write to the canonical tables.
SOURCE_MANUAL = "manual"
SOURCE_STRAVA = "strava"
SOURCE_HEALTH_CONNECT = "health_connect"
SOURCE_FITNOTES = "fitnotes_import"

# How an exercise is measured. Drives which set columns are meaningful.
MODALITIES = (
    "weight_reps",
    "bodyweight_reps",
    "weighted_bodyweight",
    "distance_time",
    "duration",
)

# Recognised daily metric names. Adding one is an insert, not a migration.
METRIC_STEPS = "steps"
METRIC_SLEEP_MINUTES = "sleep_minutes"
METRIC_RESTING_HR = "resting_hr"
METRIC_HRV_MS = "hrv_ms"
METRIC_ACTIVE_MINUTES = "active_minutes"
METRIC_BODY_WEIGHT_KG = "body_weight_kg"

METRIC_UNITS = {
    METRIC_STEPS: "count",
    METRIC_SLEEP_MINUTES: "min",
    METRIC_RESTING_HR: "bpm",
    METRIC_HRV_MS: "ms",
    METRIC_ACTIVE_MINUTES: "min",
    METRIC_BODY_WEIGHT_KG: "kg",
}


class Base(DeclarativeBase):
    pass


class RawRecord(Base):
    """Append-only landing zone. Every adapter writes here before normalising.

    Nothing deletes from this table; the canonical tables can always be rebuilt
    from it without re-contacting an upstream API.
    """

    __tablename__ = "raw_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("source", "content_hash", name="uq_raw_records_source_hash"),
        Index("ix_raw_records_source_external", "source", "external_id"),
    )


class AppSetting(Base):
    """Configuration entered through the UI, so the app is usable without a .env."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OAuthToken(Base):
    """Third-party OAuth credentials, one row per upstream service."""

    __tablename__ = "oauth_tokens"

    service: Mapped[str] = mapped_column(String(32), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    category: Mapped[str | None] = mapped_column(String(64))
    modality: Mapped[str] = mapped_column(String(32), default="weight_reps")
    primary_muscles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )
    secondary_muscles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    sets: Mapped[list[SetEntry]] = relationship(back_populates="exercise")

    __table_args__ = (
        CheckConstraint(
            "modality IN ('weight_reps','bodyweight_reps','weighted_bodyweight',"
            "'distance_time','duration')",
            name="ck_exercises_modality",
        ),
    )


class Workout(Base):
    """A strength session. Cardio lives in `activities`."""

    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    performed_on: Mapped[dt.date] = mapped_column(Date, index=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_MANUAL)
    external_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sets: Mapped[list[SetEntry]] = relationship(
        back_populates="workout",
        cascade="all, delete-orphan",
        order_by="SetEntry.position",
    )

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_workouts_source_external"),
    )


class SetEntry(Base):
    __tablename__ = "sets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workout_id: Mapped[int] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), index=True
    )
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    reps: Mapped[int | None] = mapped_column(Integer)
    rpe: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    distance_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    duration_s: Mapped[int | None] = mapped_column(Integer)

    is_warmup: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    workout: Mapped[Workout] = relationship(back_populates="sets")
    exercise: Mapped[Exercise] = relationship(back_populates="sets")

    __table_args__ = (
        CheckConstraint("reps IS NULL OR reps >= 0", name="ck_sets_reps_non_negative"),
        CheckConstraint("weight_kg IS NULL OR weight_kg >= 0", name="ck_sets_weight_non_negative"),
        CheckConstraint("rpe IS NULL OR (rpe >= 1 AND rpe <= 10)", name="ck_sets_rpe_range"),
    )


class Activity(Base):
    """A cardio activity from a tracked source (Strava today)."""

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(128))
    sport_type: Mapped[str] = mapped_column(String(48))
    name: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    timezone: Mapped[str | None] = mapped_column(String(64))

    distance_m: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    moving_time_s: Mapped[int | None] = mapped_column(Integer)
    elapsed_time_s: Mapped[int | None] = mapped_column(Integer)
    elevation_gain_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    average_hr: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    max_hr: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    average_speed_ms: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    calories: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))

    raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id"))

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_activities_source_external"),
    )


class DailyMetric(Base):
    """One value per (day, metric, source). Long-form so new metrics need no migration."""

    __tablename__ = "daily_metrics"

    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    metric: Mapped[str] = mapped_column(String(32), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit: Mapped[str] = mapped_column(String(16))
    recorded_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("ix_daily_metrics_metric_date", "metric", "date"),)


class CoachNote(Base):
    """Durable facts the coach should carry between conversations."""

    __tablename__ = "coach_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('injury','goal','preference','block','constraint')",
            name="ck_coach_notes_kind",
        ),
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )


class ChatMessage(Base):
    """A single turn. `content` holds the API content blocks verbatim, so tool_use
    and thinking blocks round-trip back to the model unchanged."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[list | dict] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class SyncRun(Base):
    """Per-adapter run history, so 'why is my step data stale?' is answerable."""

    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")
    records_read: Mapped[int] = mapped_column(Integer, default=0)
    records_written: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)

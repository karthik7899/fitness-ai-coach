"""Canonical training schema

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "raw_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "content_hash", name="uq_raw_records_source_hash"),
    )
    op.create_index("ix_raw_records_source_external", "raw_records", ["source", "external_id"])

    op.create_table(
        "oauth_tokens",
        sa.Column("service", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("service"),
    )

    op.create_table(
        "exercises",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("modality", sa.String(32), nullable=False, server_default="weight_reps"),
        sa.Column("primary_muscles", postgresql.ARRAY(sa.Text()), server_default="{}"),
        sa.Column("secondary_muscles", postgresql.ARRAY(sa.Text()), server_default="{}"),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.CheckConstraint(
            "modality IN ('weight_reps','bodyweight_reps','weighted_bodyweight',"
            "'distance_time','duration')",
            name="ck_exercises_modality",
        ),
    )
    # Case-insensitive uniqueness so "Back Squat" and "back squat" cannot diverge.
    op.execute("CREATE UNIQUE INDEX ix_exercises_name_lower ON exercises (lower(name))")

    op.create_table(
        "workouts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("performed_on", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_workouts_source_external"),
    )
    op.create_index("ix_workouts_performed_on", "workouts", ["performed_on"])

    op.create_table(
        "sets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workout_id", sa.Integer(), nullable=False),
        sa.Column("exercise_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weight_kg", sa.Numeric(7, 3), nullable=True),
        sa.Column("reps", sa.Integer(), nullable=True),
        sa.Column("rpe", sa.Numeric(3, 1), nullable=True),
        sa.Column("distance_m", sa.Numeric(10, 2), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column("is_warmup", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["workout_id"], ["workouts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.id"]),
        sa.CheckConstraint("reps IS NULL OR reps >= 0", name="ck_sets_reps_non_negative"),
        sa.CheckConstraint(
            "weight_kg IS NULL OR weight_kg >= 0", name="ck_sets_weight_non_negative"
        ),
        sa.CheckConstraint("rpe IS NULL OR (rpe >= 1 AND rpe <= 10)", name="ck_sets_rpe_range"),
    )
    op.create_index("ix_sets_workout_id", "sets", ["workout_id"])
    op.create_index("ix_sets_exercise_id", "sets", ["exercise_id"])

    op.create_table(
        "activities",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("sport_type", sa.String(48), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=True),
        sa.Column("distance_m", sa.Numeric(12, 2), nullable=True),
        sa.Column("moving_time_s", sa.Integer(), nullable=True),
        sa.Column("elapsed_time_s", sa.Integer(), nullable=True),
        sa.Column("elevation_gain_m", sa.Numeric(8, 2), nullable=True),
        sa.Column("average_hr", sa.Numeric(5, 1), nullable=True),
        sa.Column("max_hr", sa.Numeric(5, 1), nullable=True),
        sa.Column("average_speed_ms", sa.Numeric(8, 3), nullable=True),
        sa.Column("calories", sa.Numeric(8, 1), nullable=True),
        sa.Column("raw_record_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_records.id"]),
        sa.UniqueConstraint("source", "external_id", name="uq_activities_source_external"),
    )
    op.create_index("ix_activities_started_at", "activities", ["started_at"])

    op.create_table(
        "daily_metrics",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("value", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("date", "metric", "source"),
    )
    op.create_index("ix_daily_metrics_metric_date", "daily_metrics", ["metric", "date"])

    op.create_table(
        "coach_notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "kind IN ('injury','goal','preference','block','constraint')",
            name="ck_coach_notes_kind",
        ),
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("records_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_runs_source", "sync_runs", ["source"])


def downgrade() -> None:
    op.drop_table("sync_runs")
    op.drop_table("chat_messages")
    op.drop_table("conversations")
    op.drop_table("coach_notes")
    op.drop_table("daily_metrics")
    op.drop_table("activities")
    op.drop_table("sets")
    op.drop_table("workouts")
    op.drop_table("exercises")
    op.drop_table("oauth_tokens")
    op.drop_table("raw_records")

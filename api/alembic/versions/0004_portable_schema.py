"""Move muscles out of array columns and rebuild the views portably

A no-op on a database created after this change; the work here is for one made
before it, where `exercises` still has the Postgres ARRAY columns.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.views_sql import drop_ddl, view_ddl

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Views read the columns being dropped, so they have to go first.
    for statement in drop_ddl():
        op.execute(statement)

    tables = set(sa.inspect(bind).get_table_names())
    if "exercise_muscles" not in tables:
        op.create_table(
            "exercise_muscles",
            sa.Column("exercise_id", sa.Integer(), nullable=False),
            sa.Column("muscle", sa.String(48), nullable=False),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="1"),
            sa.PrimaryKeyConstraint("exercise_id", "muscle"),
            sa.ForeignKeyConstraint(["exercise_id"], ["exercises.id"], ondelete="CASCADE"),
        )

    existing = _columns(bind, "exercises")
    if "primary_muscles" in existing:
        # UNNEST is Postgres-only, but so are the array columns being drained.
        for column, is_primary in (("primary_muscles", True), ("secondary_muscles", False)):
            if column not in existing:
                continue
            op.execute(
                sa.text(
                    f"""
                    INSERT INTO exercise_muscles (exercise_id, muscle, is_primary)
                    SELECT e.id, m, :is_primary
                    FROM exercises e, UNNEST(e.{column}) AS m
                    WHERE m IS NOT NULL AND m <> ''
                    ON CONFLICT (exercise_id, muscle) DO NOTHING
                    """
                ).bindparams(is_primary=is_primary)
            )
            op.drop_column("exercises", column)

    for _, ddl in view_ddl(dialect):
        op.execute(ddl)


def downgrade() -> None:
    for statement in drop_ddl():
        op.execute(statement)
    op.drop_table("exercise_muscles")

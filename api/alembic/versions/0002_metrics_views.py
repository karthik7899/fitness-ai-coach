"""Derived metrics views

The SQL lives in app/views_sql.py so that this migration, the later one that
recreates the views, and anything porting them elsewhere all read one definition.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op
from app.views_sql import drop_ddl, view_ddl

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    for _, ddl in view_ddl(dialect):
        op.execute(ddl)


def downgrade() -> None:
    for statement in drop_ddl():
        op.execute(statement)

"""Dialect-appropriate upserts.

PostgreSQL and SQLite both implement `INSERT ... ON CONFLICT`, but through
separate SQLAlchemy constructs, and only Postgres can name a constraint —
SQLite needs the columns. Naming the columns works on both, so that is the
form used here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session


def _insert(session: Session, model: Any):
    dialect = session.get_bind().dialect.name
    return sqlite_insert(model) if dialect == "sqlite" else pg_insert(model)


def upsert(
    session: Session,
    model: Any,
    values: dict,
    index_elements: list[str],
    set_: dict | None = None,
):
    """INSERT, updating on conflict — or doing nothing when `set_` is omitted."""
    statement = _insert(session, model).values(**values)
    if set_ is None:
        return statement.on_conflict_do_nothing(index_elements=index_elements)
    return statement.on_conflict_do_update(index_elements=index_elements, set_=set_)

"""Raw-SQL helpers shared by the HTTP routes and the agent's tools.

Both read the same views, so they share the same row conversion.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    return value


def rows(session: Session, sql: str, **params: Any) -> list[dict]:
    result = session.execute(text(sql), params)
    return [{k: jsonable(v) for k, v in row.items()} for row in result.mappings()]

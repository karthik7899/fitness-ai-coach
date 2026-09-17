"""Gadgetbridge export ingestion — watch data with no vendor or Google involvement.

Gadgetbridge talks to Moyoung/CRRepa watches (the ones the Da Fit app ships with)
directly over Bluetooth, so the data never touches Moyoung's servers or Google's.
Its Data Export writes a SQLite database, which this module reads.

Gadgetbridge stores samples in per-device tables (`MI_BAND_ACTIVITY_SAMPLE`,
`MOYOUNG_ACTIVITY_SAMPLE`, ...) that share a column shape, and the set of tables
depends on which devices you have paired. Extraction is therefore
schema-discovering: `inspect_export` reports what a real export contains.

Sleep is deliberately conservative. Gadgetbridge stores a device-specific
RAW_KIND and normalises it only on read, so a kind value cannot be mapped to
sleep without knowing the device. Steps and heart rate are read directly; sleep
is only emitted when the export carries an explicitly typed sleep column.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import (
    METRIC_HRV_MS,
    METRIC_RESTING_HR,
    METRIC_SLEEP_MINUTES,
    METRIC_STEPS,
    DailyMetric,
)

SOURCE = "gadgetbridge"

SAMPLE_TABLE_SUFFIX = "ACTIVITY_SAMPLE"
TIMESTAMP_COLUMNS = ("TIMESTAMP",)
STEPS_COLUMNS = ("STEPS",)
HEART_RATE_COLUMNS = ("HEART_RATE",)
# Gadgetbridge's normalised kind values; only meaningful where a device writes them.
SLEEP_KIND_COLUMNS = ("KIND",)
SLEEP_KINDS = {2, 4, 16}  # light, deep, REM

METRIC_UNITS = {
    METRIC_STEPS: "count",
    METRIC_RESTING_HR: "bpm",
    METRIC_SLEEP_MINUTES: "min",
    METRIC_HRV_MS: "ms",
}


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def _pick(available: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {c.lower(): c for c in available}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def sample_tables(conn: sqlite3.Connection) -> list[str]:
    return [t for t in _tables(conn) if t.upper().endswith(SAMPLE_TABLE_SUFFIX)]


def looks_like_gadgetbridge(path: Path) -> bool:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            return bool(sample_tables(conn))
    except sqlite3.Error:
        return False


def inspect_export(path: Path) -> dict:
    """Report the export's structure, for checking the mapping against a real file."""
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        report: dict = {"sample_tables": {}, "all_tables": sorted(_tables(conn))}
        for table in sample_tables(conn):
            cols = _columns(conn, table)
            report["sample_tables"][table] = {
                "columns": cols,
                "rows": conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
                "timestamp_column": _pick(cols, TIMESTAMP_COLUMNS),
                "steps_column": _pick(cols, STEPS_COLUMNS),
                "heart_rate_column": _pick(cols, HEART_RATE_COLUMNS),
                "sleep_kind_column": _pick(cols, SLEEP_KIND_COLUMNS),
            }
    return report


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * fraction)))
    return ordered[index]


def extract_daily(path: Path) -> dict[tuple[dt.date, str], float]:
    """Reduce the export to {(date, metric): value}."""
    steps: dict[dt.date, int] = defaultdict(int)
    heart_rates: dict[dt.date, list[float]] = defaultdict(list)
    sleep_minutes: dict[dt.date, float] = defaultdict(float)

    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        for table in sample_tables(conn):
            cols = _columns(conn, table)
            ts_col = _pick(cols, TIMESTAMP_COLUMNS)
            if ts_col is None:
                continue
            steps_col = _pick(cols, STEPS_COLUMNS)
            hr_col = _pick(cols, HEART_RATE_COLUMNS)
            kind_col = _pick(cols, SLEEP_KIND_COLUMNS)

            selected = [f'"{ts_col}"']
            for col in (steps_col, hr_col, kind_col):
                selected.append(f'"{col}"' if col else "NULL")

            for ts, step_value, hr_value, kind in conn.execute(
                f'SELECT {", ".join(selected)} FROM "{table}"'
            ):
                if ts is None:
                    continue
                # Gadgetbridge timestamps are epoch seconds; bucket to local date.
                day = dt.datetime.fromtimestamp(ts).date()

                if step_value:
                    steps[day] += int(step_value)
                # 0 means "not measured"; anything under 25bpm is noise, not a reading.
                if hr_value and hr_value >= 25:
                    heart_rates[day].append(float(hr_value))
                if kind is not None and kind in SLEEP_KINDS:
                    # Samples are one minute apart.
                    sleep_minutes[day] += 1.0

    daily: dict[tuple[dt.date, str], float] = {}
    for day, value in steps.items():
        daily[(day, METRIC_STEPS)] = float(value)
    for day, values in heart_rates.items():
        # Resting HR proxy: the low end of the day's distribution, which is more
        # robust than the single minimum sample.
        daily[(day, METRIC_RESTING_HR)] = round(_percentile(values, 0.10), 1)
    for day, minutes in sleep_minutes.items():
        daily[(day, METRIC_SLEEP_MINUTES)] = round(minutes, 1)
    return daily


def upsert_daily(session: Session, daily: dict[tuple[dt.date, str], float]) -> int:
    written = 0
    for (day, metric), value in daily.items():
        stmt = (
            pg_insert(DailyMetric)
            .values(
                date=day,
                metric=metric,
                source=SOURCE,
                value=Decimal(str(value)),
                unit=METRIC_UNITS.get(metric, ""),
            )
            .on_conflict_do_update(
                index_elements=[DailyMetric.date, DailyMetric.metric, DailyMetric.source],
                set_={"value": Decimal(str(value))},
            )
        )
        session.execute(stmt)
        written += 1
    return written

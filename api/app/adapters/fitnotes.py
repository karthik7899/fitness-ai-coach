"""One-time FitNotes history import.

Reads either a FitNotes SQLite backup (`.fitnotes`) or its CSV export and lands
the history in the canonical tables under `source='fitnotes_import'`, separate
from anything logged in the app so an import can never clobber manual entries.

Re-running is safe: each imported day is keyed on its date and its sets are
replaced wholesale.

    uv run python -m app.adapters.fitnotes ~/Downloads/FitNotes_Backup.fitnotes
    uv run python -m app.adapters.fitnotes --inspect ~/Downloads/backup.fitnotes
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.adapters.base import SyncOutcome, store_raw, sync_run
from app.models import SOURCE_FITNOTES, Exercise, SetEntry, Workout
from app.upsert import upsert

LBS_TO_KG = Decimal("0.45359237")
MILES_TO_M = Decimal("1609.344")


@dataclass
class ParsedSet:
    performed_on: dt.date
    exercise: str
    category: str | None
    weight_kg: Decimal | None = None
    reps: int | None = None
    distance_m: Decimal | None = None
    duration_s: int | None = None
    notes: str | None = None


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _pick(available: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {c.lower(): c for c in available}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def inspect_backup(path: Path) -> dict:
    """Report the backup's structure, for checking the mapping below against a real file."""
    with sqlite3.connect(path) as conn:
        present = _tables(conn)
        report: dict = {"tables": sorted(present)}
        for table in ("training_log", "exercise", "Category", "category"):
            if table in present:
                report[table] = {
                    "columns": _columns(conn, table),
                    "rows": conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
                }
    return report


def parse_sqlite(path: Path) -> list[ParsedSet]:
    with sqlite3.connect(path) as conn:
        present = _tables(conn)
        if "training_log" not in present or "exercise" not in present:
            raise ValueError(
                "Not a FitNotes backup: expected training_log and exercise, "
                f"found {sorted(present)}"
            )

        log_cols = _columns(conn, "training_log")

        # FitNotes stores a metric_weight column alongside the user's display unit.
        # Prefer it and take it as kilograms; only convert when the file has just
        # an imperial column.
        metric_weight = _pick(log_cols, ("metric_weight",))
        plain_weight = _pick(log_cols, ("weight", "imperial_weight"))
        weight_col = metric_weight or plain_weight
        weight_is_metric = metric_weight is not None

        metric_distance = _pick(log_cols, ("metric_distance",))
        plain_distance = _pick(log_cols, ("distance",))
        distance_col = metric_distance or plain_distance
        distance_is_metric = metric_distance is not None

        unit_col = _pick(log_cols, ("unit",))
        duration_col = _pick(log_cols, ("duration_seconds",))
        comment_col = _pick(log_cols, ("comment", "notes"))
        reps_col = _pick(log_cols, ("reps",))

        category_table = _pick(sorted(present), ("Category", "category"))
        category_select = "c.name" if category_table else "NULL"
        category_join = (
            f'LEFT JOIN "{category_table}" c ON c._id = e.category_id' if category_table else ""
        )

        selected = ", ".join(
            [
                "t.date",
                "e.name",
                category_select,
                f't."{weight_col}"' if weight_col else "NULL",
                f't."{reps_col}"' if reps_col else "NULL",
                f't."{distance_col}"' if distance_col else "NULL",
                f't."{duration_col}"' if duration_col else "NULL",
                f't."{unit_col}"' if unit_col else "NULL",
                f't."{comment_col}"' if comment_col else "NULL",
            ]
        )

        rows = conn.execute(
            f"""
            SELECT {selected}
            FROM training_log t
            JOIN exercise e ON e._id = t.exercise_id
            {category_join}
            ORDER BY t.date
            """
        ).fetchall()

    parsed: list[ParsedSet] = []
    for date_s, exercise, category, weight, reps, distance, duration, unit, comment in rows:
        if not date_s or not exercise:
            continue
        try:
            performed_on = dt.date.fromisoformat(str(date_s)[:10])
        except ValueError:
            continue

        imperial = unit == 1

        weight_kg = None
        if weight is not None and float(weight) > 0:
            weight_kg = Decimal(str(weight))
            if not weight_is_metric and imperial:
                weight_kg *= LBS_TO_KG

        distance_m = None
        if distance is not None and float(distance) > 0:
            value = Decimal(str(distance))
            # metric_distance is kilometres; a plain imperial distance is miles.
            use_miles = imperial and not distance_is_metric
            distance_m = value * MILES_TO_M if use_miles else value * 1000

        parsed.append(
            ParsedSet(
                performed_on=performed_on,
                exercise=str(exercise).strip(),
                category=str(category).strip() if category else None,
                weight_kg=None if weight_kg is None else round(weight_kg, 3),
                reps=int(reps) if reps else None,
                distance_m=None if distance_m is None else round(distance_m, 2),
                duration_s=int(duration) if duration else None,
                notes=(comment or None),
            )
        )
    return parsed


def parse_csv(content: bytes) -> list[ParsedSet]:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig", errors="replace")))

    def number(row: dict, *names: str) -> Decimal | None:
        for name in names:
            raw = (row.get(name) or "").strip()
            if raw:
                try:
                    return Decimal(raw)
                except (ValueError, ArithmeticError):
                    return None
        return None

    parsed: list[ParsedSet] = []
    for row in reader:
        raw_date = (row.get("Date") or "").strip()
        exercise = (row.get("Exercise") or "").strip()
        if not raw_date or not exercise:
            continue
        try:
            performed_on = dt.date.fromisoformat(raw_date[:10])
        except ValueError:
            continue

        weight_kg = number(row, "Weight (kg)")
        if weight_kg is None:
            pounds = number(row, "Weight (lbs)")
            weight_kg = None if pounds is None else pounds * LBS_TO_KG

        distance = number(row, "Distance")
        distance_m = None
        if distance is not None:
            unit = (row.get("Distance Unit") or "").strip().lower()
            if unit in ("mile", "miles", "mi"):
                distance_m = distance * MILES_TO_M
            elif unit in ("m", "metres", "meters"):
                distance_m = distance
            else:
                distance_m = distance * 1000

        reps = number(row, "Reps")
        parsed.append(
            ParsedSet(
                performed_on=performed_on,
                exercise=exercise,
                category=(row.get("Category") or "").strip() or None,
                weight_kg=None if weight_kg is None else round(weight_kg, 3),
                reps=None if reps is None else int(reps),
                distance_m=None if distance_m is None else round(distance_m, 2),
                notes=(row.get("Comment") or "").strip() or None,
            )
        )
    return parsed


def _exercise_ids(session: Session, parsed: list[ParsedSet]) -> dict[str, int]:
    """Resolve every exercise name to an id, creating any that are new."""
    wanted = {p.exercise: p.category for p in parsed}
    existing = {
        name.lower(): id_
        for id_, name in session.execute(select(Exercise.id, Exercise.name)).all()
    }

    resolved: dict[str, int] = {}
    for name, category in wanted.items():
        found = existing.get(name.lower())
        if found is None:
            exercise = Exercise(name=name, category=category, modality="weight_reps")
            session.add(exercise)
            session.flush()
            found = exercise.id
            existing[name.lower()] = found
        resolved[name] = found
    return resolved


def import_sets(session: Session, parsed: list[ParsedSet]) -> SyncOutcome:
    with sync_run(session, SOURCE_FITNOTES) as outcome:
        outcome.read = len(parsed)
        if not parsed:
            return outcome

        days = sorted({p.performed_on for p in parsed})
        store_raw(
            session,
            SOURCE_FITNOTES,
            "import",
            {
                "sets": len(parsed),
                "days": len(days),
                "first": days[0].isoformat(),
                "last": days[-1].isoformat(),
            },
            external_id=f"{days[0].isoformat()}..{days[-1].isoformat()}",
        )

        ids = _exercise_ids(session, parsed)

        by_day: dict[dt.date, list[ParsedSet]] = {}
        for entry in parsed:
            by_day.setdefault(entry.performed_on, []).append(entry)

        for day, entries in by_day.items():
            workout_id = session.execute(
                upsert(
                    session,
                    Workout,
                    {
                        "performed_on": day,
                        "source": SOURCE_FITNOTES,
                        "external_id": day.isoformat(),
                    },
                    index_elements=["source", "external_id"],
                    set_={"performed_on": day},
                ).returning(Workout.id)
            ).scalar_one()

            # Replace the day wholesale so a re-import cannot duplicate sets.
            session.execute(delete(SetEntry).where(SetEntry.workout_id == workout_id))

            for position, entry in enumerate(entries, start=1):
                session.add(
                    SetEntry(
                        workout_id=workout_id,
                        exercise_id=ids[entry.exercise],
                        position=position,
                        weight_kg=entry.weight_kg,
                        reps=entry.reps,
                        distance_m=entry.distance_m,
                        duration_s=entry.duration_s,
                        notes=entry.notes,
                    )
                )
                outcome.written += 1

        session.commit()
        return outcome


def import_file(session: Session, filename: str, content: bytes) -> SyncOutcome:
    if filename.lower().endswith(".csv"):
        return import_sets(session, parse_csv(content))

    with tempfile.NamedTemporaryFile(suffix=".fitnotes", delete=False) as handle:
        handle.write(content)
        path = Path(handle.name)
    try:
        return import_sets(session, parse_sqlite(path))
    finally:
        path.unlink(missing_ok=True)


def _summarise(session: Session) -> str:
    total = session.scalar(
        select(func.count()).select_from(SetEntry).join(Workout).where(
            Workout.source == SOURCE_FITNOTES
        )
    )
    span = session.execute(
        select(func.min(Workout.performed_on), func.max(Workout.performed_on)).where(
            Workout.source == SOURCE_FITNOTES
        )
    ).one()
    return f"{total} sets imported, {span[0]} to {span[1]}"


if __name__ == "__main__":
    from app.db import SessionLocal

    args = [a for a in sys.argv[1:] if a != "--inspect"]
    if not args:
        print(__doc__)
        raise SystemExit(1)

    target = Path(args[0]).expanduser()
    if "--inspect" in sys.argv:
        import json

        print(json.dumps(inspect_backup(target), indent=2))
        raise SystemExit(0)

    with SessionLocal() as db:
        result = import_file(db, target.name, target.read_bytes())
        print(f"Read {result.read} sets, wrote {result.written}.")
        print(_summarise(db))

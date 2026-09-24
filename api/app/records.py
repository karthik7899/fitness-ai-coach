"""Personal records: whether a set just logged beat everything before it.

Three kinds, checked against every earlier working set of the exercise:

- **weight**: heavier than ever.
- **e1rm**: a better estimated one-rep max, by the same Epley formula as
  v_sets_enriched, so the number matches the Trends chart.
- **reps**: more reps than any set at this weight or heavier. Only where such a
  set exists: at a weight never lifted before, the weight record says it.

A first set is no record; there is nothing to beat. Warmups are neither
checked nor counted. Specified case by case in fixtures/records.json, which
the Kotlin port is held to as well.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Exercise, SetEntry, Workout


@dataclass(frozen=True)
class Record:
    kind: str  # "weight" | "e1rm" | "reps"
    value: float
    previous: float

    def as_dict(self) -> dict:
        return {"kind": self.kind, "value": self.value, "previous": self.previous}


def e1rm(weight: float | None, reps: int | None) -> float | None:
    if weight is None or weight <= 0 or reps is None or not 1 <= reps <= 12:
        return None
    return round(weight * (1 + reps / 30.0), 2)


def beaten(before: list[tuple[float | None, int | None]], new: tuple[float | None, int | None]):
    """The records `new` sets over `before`, in the order weight, e1rm, reps."""
    if not before or new[1] is None:
        return []
    weight, reps = new[0] or 0.0, new[1]
    found: list[Record] = []

    heaviest = max((w or 0.0) for w, _ in before)
    if weight > 0 and weight > heaviest:
        found.append(Record("weight", weight, heaviest))

    mine = e1rm(new[0], reps)
    estimates = [e for e in (e1rm(w, r) for w, r in before) if e is not None]
    if mine is not None and estimates and mine > max(estimates):
        found.append(Record("e1rm", mine, max(estimates)))

    at_or_above = [r or 0 for w, r in before if (w or 0.0) >= weight]
    if at_or_above and reps > max(at_or_above):
        found.append(Record("reps", reps, max(at_or_above)))
    return found


def for_set(session: Session, set_id: int) -> tuple[str, list[Record]] | None:
    """The exercise's name and the records this set broke, or None if no such set.

    "Earlier" is an earlier day, or the same day and logged first, so a record
    set earlier in the session is the one the next set has to beat.
    """
    row = session.execute(
        select(SetEntry, Workout.performed_on, Exercise.name)
        .join(Workout, Workout.id == SetEntry.workout_id)
        .join(Exercise, Exercise.id == SetEntry.exercise_id)
        .where(SetEntry.id == set_id)
    ).first()
    if row is None:
        return None
    entry, day, name = row
    if entry.is_warmup:
        return name, []

    before = session.execute(
        select(SetEntry.weight_kg, SetEntry.reps)
        .join(Workout, Workout.id == SetEntry.workout_id)
        .where(
            SetEntry.exercise_id == entry.exercise_id,
            SetEntry.is_warmup.is_(False),
            SetEntry.id != set_id,
            or_(
                Workout.performed_on < day,
                (Workout.performed_on == day) & (SetEntry.id < set_id),
            ),
        )
    ).all()

    def weight(value) -> float | None:
        return float(value) if value is not None else None

    return name, beaten(
        [(weight(w), r) for w, r in before], (weight(entry.weight_kg), entry.reps)
    )

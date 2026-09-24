"""What to lift next time: double progression over a rep range.

Given the working sets of the most recent earlier session, suggest today's
weight and reps for an exercise planned as `sets` × `reps_min`–`reps_max`:

- **up**: every planned set at the top weight reached the top of the range,
  and none was a grind (RPE 10). Add one increment, back to the bottom.
- **down**: even the best set at that weight fell short of the bottom of the
  range. Drop about ten percent, rounded down to a loadable weight.
- **repeat**: anything between. Same weight, one more rep on the weakest set.
- **new**: no history. The bottom of the range; the weight is the trainee's call.

Bodyweight sets progress in reps; at the top of the range the advice is "up"
with no weight, meaning add load. Pure, and specified case by case in
fixtures/progression.json, which the Kotlin port is held to as well.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

GRIND_RPE = 10.0
DROP = 0.9


@dataclass(frozen=True)
class Suggestion:
    advice: str  # "new" | "up" | "repeat" | "down"
    weight: float | None
    reps: int


def _round_down(value: float, step: float) -> float:
    # The epsilon keeps 90.00000000000001 / 2.5 from flooring to 35.
    return round(math.floor(value / step + 1e-9) * step, 3)


def suggest(
    last: list[tuple[float | None, int | None, float | None]],
    sets: int,
    reps_min: int,
    reps_max: int,
    increment: float,
) -> Suggestion:
    """`last` is (weight_kg, reps, rpe) per working set of the previous session."""
    done = [(w, r or 0, rpe) for w, r, rpe in last if r is not None]
    if not done:
        return Suggestion("new", None, reps_min)

    weights = [w for w, _, _ in done if w is not None]
    top = max(weights) if weights else None
    at_top = [(r, rpe) for w, r, rpe in done if w == top]
    lowest = min(r for r, _ in at_top)
    best = max(r for r, _ in at_top)
    grind = any(rpe is not None and rpe >= GRIND_RPE for _, rpe in at_top)

    if len(at_top) >= sets and lowest >= reps_max and not grind:
        if top is None:
            return Suggestion("up", None, reps_max)
        return Suggestion("up", round(top + increment, 3), reps_min)
    if best < reps_min and top is not None:
        return Suggestion("down", _round_down(top * DROP, increment), reps_min)
    return Suggestion("repeat", top, max(reps_min, min(lowest + 1, reps_max)))

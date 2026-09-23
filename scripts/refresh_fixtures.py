"""Regenerate the expected rows in `fixtures/`.

Python is the reference implementation: these files record what its importers
produce, and the Kotlin suite then has to match them. Run this when an
importer's behaviour changes on purpose, and read the diff — a change here is a
change to what a backup file means.

    cd api && uv run python ../scripts/refresh_fixtures.py
    cd api && uv run python ../scripts/refresh_fixtures.py --check
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

# Gadgetbridge samples are bucketed into days by local time, so the timezone has
# to be pinned before anything reads one. Must precede the app imports.
os.environ["TZ"] = "UTC"
time.tzset()

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "api"
FIXTURES = REPO_ROOT / "fixtures"
SCHEMA = REPO_ROOT / "android/core/src/main/resources/aura/schema.sql"

sys.path.insert(0, str(API_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.adapters import fitnotes, gadgetbridge  # noqa: E402
from app.db import configure_sqlite  # noqa: E402


def build_source(sql_path: Path, target: Path) -> Path:
    """Materialise one of the *.source.sql files as a real database file."""
    connection = sqlite3.connect(target)
    connection.executescript(sql_path.read_text())
    connection.commit()
    connection.close()
    return target


def canonical_db(path: Path) -> Session:
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA.read_text())
    connection.commit()
    connection.close()
    engine = configure_sqlite(create_engine(f"sqlite:///{path}", future=True))
    return Session(engine)


def read_rows(session: Session, query_path: Path) -> list[str]:
    return [row[0] for row in session.execute(text(query_path.read_text())).all()]


def generate() -> dict[Path, str]:
    """Run every importer over its fixture and return the rows each produced."""
    produced: dict[Path, str] = {}

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)

        for name in ("fitnotes_metric", "fitnotes_imperial"):
            source = build_source(FIXTURES / f"{name}.source.sql", work / f"{name}.fitnotes")
            with canonical_db(work / f"{name}.canonical.db") as session:
                fitnotes.import_sets(session, fitnotes.parse_sqlite(source))
                lines = read_rows(session, FIXTURES / "rows_fitnotes.sql")
            produced[FIXTURES / f"{name}.expected.csv"] = "".join(f"{line}\n" for line in lines)

        source = build_source(FIXTURES / "gadgetbridge.source.sql", work / "gadgetbridge.db")
        with canonical_db(work / "gadgetbridge.canonical.db") as session:
            gadgetbridge.upsert_daily(session, gadgetbridge.extract_daily(source))
            session.commit()
            lines = read_rows(session, FIXTURES / "rows_gadgetbridge.sql")
        produced[FIXTURES / "gadgetbridge.expected.csv"] = "".join(f"{line}\n" for line in lines)

    produced[FIXTURES / "prompt_assembly.json"] = prompt_assembly()
    produced[FIXTURES / "grounding.json"] = grounding_cases()
    return produced


# (name, answer, sources). The expected verdicts are computed by the Python
# reference and written out; the Kotlin coach is then held to them. Each case
# is here because it pins one rule — the name says which.
GROUNDING_CASES = [
    ("exact figure", "Your best squat was 116.67 kg.", ['{"best_e1rm_kg": 116.67}']),
    ("rounded to what is written", "About 117 kg, or 116.7.", ['{"best_e1rm_kg": 116.67}']),
    ("ratio rounded", "Your ACWR is 1.8.", ['{"acwr": 1.793}']),
    ("an invented figure", "You averaged 12,000 steps.", ['{"value": 9876}']),
    ("round thousands are approximate", "Roughly 10,000 steps a day.", ['{"value": 9876}']),
    ("small round numbers are exact", "You did 10 reps.", ['{"reps": 12}']),
    ("compact thousands", "That is 10.9K kg, or 11K.", ['{"volume_kg": 10872}']),
    ("tonnes from kilograms", "That is 10.9 tonnes.", ['{"volume_kg": 10872}']),
    ("kilograms from tonnes", "That was 500 kg.", ['{"strength_tonnes": 0.5}']),
    ("hours from minutes", "You slept 7.5 hours.", ['{"sleep_minutes": 450}']),
    ("hours and minutes as one", "You slept 7h 30m.", ['{"sleep_minutes": 450}']),
    ("kilometres from metres", "You ran 5 km.", ['{"distance_m": 5000}']),
    ("percentage of a ratio", "40% above your chronic load.", ['{"x": 0.4}']),
    ("percentage as a value", "A 40% share.", ['{"x": 40}']),
    ("a wrong percentage", "45% above.", ['{"x": 0.4}']),
    ("no unit means no rescaling", "You did 8 sets.", ['{"working_sets": 6, "steps": 8000}']),
    ("digits in a key are not values", "Just 1 session.", ['{"best_e1rm_kg": 99.5}']),
    ("dates are not claims", "On 2026-09-21 and 21 Sep you did 5 sets.", ['{"working_sets": 5}']),
    ("1RM is a name, not a figure", "Your e1RM rose to 120.", ['{"best": 120}']),
    ("the load windows are definitional", "Your 7-day and 28-day averages.", []),
    ("echoing the question", "Over the last 30 days you trained twice.", ["Last 30 days?"]),
    ("arithmetic is reported, by design", "300 kg more than last week.", ['{"a": 1500, "b": 1200}']),
    ("list markers are not figures", "1. Squat 4x5 at 100 kg", ['{"sets": 4, "reps": 5, "w": 100}']),
    ("nothing to check", "Rest today.", []),
    ("each figure once", "5 sets, then 5 more sets.", ['{"sets": 5}']),
]


def grounding_cases() -> str:
    """The grounding verdicts both coaches must reach on the same inputs."""
    import json

    from app.agent.grounding import check

    document = {
        "_comment": (
            "Generated by scripts/refresh_fixtures.py from the Python grounding "
            "check. The Kotlin coach must reach exactly these verdicts."
        ),
        "cases": [
            {
                "name": name,
                "answer": answer,
                "sources": sources,
                **{k: v for k, v in check(answer, sources).as_dict().items() if k != "ok"},
            }
            for name, answer, sources in GROUNDING_CASES
        ],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def prompt_assembly() -> str:
    """How the final prompt is put together, pinned for both coaches.

    The instructions are a stand-in: the real text is exported separately and
    checked on its own. What this pins is the assembly — where the date goes,
    how remembered facts are listed, what is said when there are none — which
    is the part the two implementations could each get subtly wrong.
    """
    import datetime as dt
    import json

    from app.agent.coach import build_system_instruction

    instructions = "INSTRUCTIONS\nSecond line.\n"
    cases = [
        (
            "with standing facts",
            [
                ("constraint", "Trains before work, 45 minutes at most"),
                ("goal", "Squat 140 kg by March"),
                ("injury", "Left shoulder — no overhead pressing"),
            ],
        ),
        ("no standing facts", []),
        ("a fact with quotes and accents", [("preference", 'Prefers "RPE" over %1RM; café after')]),
    ]
    document = {
        "_comment": (
            "Generated by scripts/refresh_fixtures.py. Both coaches must assemble "
            "exactly these prompts from these inputs."
        ),
        "cases": [
            {
                "name": name,
                "instructions": instructions,
                "today": "2026-09-23",
                "notes": [list(n) for n in notes],
                "expected": build_system_instruction(
                    instructions, dt.date(2026, 9, 23), notes
                ),
            }
            for name, notes in cases
        ],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    produced = generate()

    if "--check" in sys.argv:
        stale = [
            path
            for path, content in produced.items()
            if not path.exists() or path.read_text() != content
        ]
        if stale:
            for path in stale:
                print(f"stale: {path.relative_to(REPO_ROOT)}", file=sys.stderr)
            print("Run: uv run python ../scripts/refresh_fixtures.py", file=sys.stderr)
            return 1
        print(f"{len(produced)} fixture files are up to date.")
        return 0

    for path, content in produced.items():
        path.write_text(content)
        print(f"Wrote {path.relative_to(REPO_ROOT)} ({len(content.splitlines())} rows).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

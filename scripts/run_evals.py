"""Run the coach eval scenarios against the live model and write a scored report.

Each scenario gets a fresh SQLite database built from the shared schema,
seeded with its data. Its question is asked through the real coach loop, with
the harness, and the answer is graded by the same scorer CI uses on the
scripted runs. See evals/README.md.

    cd api && uv run python ../scripts/run_evals.py
    cd api && uv run python ../scripts/run_evals.py --only load-spike --repeat 3
    cd api && uv run python ../scripts/run_evals.py --scripted   # offline, no key

Needs GEMINI_API_KEY (or GOOGLE_API_KEY) in the environment. The report lands
in evals/results/ unless --out says otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "api"
SCHEMA = REPO_ROOT / "android/core/src/main/resources/aura/schema.sql"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", help="Gemini model to grade; defaults to the app's own.")
    parser.add_argument("--only", nargs="*", default=[], help="Scenario names to run.")
    parser.add_argument("--repeat", type=int, default=1,
                        help="Runs per scenario. Model output varies; one run is an anecdote.")
    parser.add_argument("--pause", type=float, default=0.0,
                        help="Seconds between runs, to stay under a free-tier rate limit.")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "evals" / "results")
    parser.add_argument("--scripted", action="store_true",
                        help="Play each scenario's own script instead of calling the model.")
    parser.add_argument("--min-pass", type=float, default=0.0,
                        help="Exit non-zero when fewer than this fraction of runs pass.")
    return parser.parse_args()


ARGS = parse_args()

# Settings are read once, on first import of the app, so these must come first.
sys.path.insert(0, str(API_DIR))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
if ARGS.model:
    os.environ["GEMINI_MODEL"] = ARGS.model

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.agent import evals  # noqa: E402
from app.db import configure_sqlite  # noqa: E402


def template(directory: Path) -> Path:
    """An empty canonical database, copied for each run rather than rebuilt."""
    path = directory / "template.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA.read_text())
    return path


async def run_one(blank: Path, directory: Path, scenario: evals.Scenario, index: int) -> dict:
    path = directory / f"{scenario.name}-{index}.sqlite3"
    shutil.copy(blank, path)
    engine = configure_sqlite(create_engine(f"sqlite:///{path}", future=True))
    try:
        with Session(engine) as session:
            evals.seed(session, scenario)
            client = evals.ScriptedClient(scenario.script) if ARGS.scripted else None
            transcript = await evals.run(session, scenario, client)
            checks = evals.score(scenario, transcript)
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)
    return {
        "scenario": scenario.name,
        "run": index + 1,
        "passed": all(c.passed for c in checks),
        "checks": [asdict(c) for c in checks],
        "transcript": asdict(transcript),
    }


def model_name() -> str:
    # Every run starts from a fresh database, so a model chosen in the app's
    # Settings page never applies here: it is the environment's, or the default.
    from app.config import settings

    return "scripted" if ARGS.scripted else settings.gemini_model


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def report(results: list[dict], scenarios: list[evals.Scenario], model: str,
           seconds: float) -> str:
    runs = len(results)
    passed = sum(r["passed"] for r in results)
    checks = [c for r in results for c in r["checks"]]
    retries = sum(r["transcript"]["retried"] for r in results)
    tokens = sum(r["transcript"]["tokens"] for r in results)

    lines = [
        f"# Coach evals: {model}",
        "",
        f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')} · {len(scenarios)} scenarios"
        f" × {ARGS.repeat} run{'s' if ARGS.repeat != 1 else ''}",
        "",
        f"**{passed}/{runs} runs passed** · {sum(c['passed'] for c in checks)}/{len(checks)}"
        f" checks · {retries} grounding retr{'y' if retries == 1 else 'ies'}"
        f" · {tokens:,} tokens · {seconds:.1f} s",
        "",
        "| scenario | passed | failed checks | tools called | retried | tokens | time |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for scenario in scenarios:
        mine = [r for r in results if r["scenario"] == scenario.name]
        failing = sorted({c["label"] for r in mine for c in r["checks"] if not c["passed"]})
        tools = sorted({t for r in mine for t in r["transcript"]["tools"]})
        lines.append(
            f"| {scenario.name} | {sum(r['passed'] for r in mine)}/{len(mine)} "
            f"| {_cell('; '.join(failing)) or '—'} | {', '.join(tools) or '—'} "
            f"| {sum(r['transcript']['retried'] for r in mine)} "
            f"| {sum(r['transcript']['tokens'] for r in mine):,} "
            f"| {sum(r['transcript']['millis'] for r in mine) / 1000:.1f} s |"
        )

    failures = [r for r in results if not r["passed"]]
    if failures:
        lines += ["", "## Failed runs"]
        for r in failures:
            scenario = next(s for s in scenarios if s.name == r["scenario"])
            transcript = r["transcript"]
            lines += ["", f"### {r['scenario']} (run {r['run']})", "", f"_{scenario.about}_", "",
                      f"**Question:** {scenario.question}", ""]
            lines += [f"- {'✓' if c['passed'] else '✗'} {c['label']}"
                      + (f" — {c['detail']}" if c["detail"] and not c["passed"] else "")
                      for c in r["checks"]]
            answer = transcript["answer"].strip() or "(no answer)"
            lines += ["", *[f"> {line}" for line in answer.splitlines()]]
    return "\n".join(lines) + "\n"


async def main() -> int:
    if not ARGS.scripted and not (
        os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    ):
        print("Set GEMINI_API_KEY to run against the live model, or pass --scripted.",
              file=sys.stderr)
        return 2

    scenarios = evals.load_all()
    if ARGS.only:
        unknown = set(ARGS.only) - {s.name for s in scenarios}
        if unknown:
            print(f"No such scenario: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        scenarios = [s for s in scenarios if s.name in ARGS.only]

    model = model_name()
    started = time.perf_counter()
    results: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        blank = template(directory)
        for index in range(ARGS.repeat):
            for scenario in scenarios:
                if results and ARGS.pause:
                    await asyncio.sleep(ARGS.pause)
                result = await run_one(blank, directory, scenario, index)
                results.append(result)
                mark = "pass" if result["passed"] else "FAIL"
                print(f"{mark}  {scenario.name} (run {index + 1})", flush=True)

    seconds = time.perf_counter() - started
    ARGS.out.mkdir(parents=True, exist_ok=True)
    text = report(results, scenarios, model, seconds)
    (ARGS.out / "report.md").write_text(text)
    (ARGS.out / "results.json").write_text(
        json.dumps({"model": model, "results": results}, indent=2, default=str) + "\n"
    )
    print(f"\n{text.splitlines()[4]}\nReport: {ARGS.out / 'report.md'}")

    if results and all(r["transcript"]["error"] for r in results):
        # Nothing was graded: a bad key or model name, not a bad coach.
        print(f"Every run failed with an error, first: {results[0]['transcript']['error']}",
              file=sys.stderr)
        return 2
    rate = sum(r["passed"] for r in results) / len(results) if results else 0.0
    return 1 if rate < ARGS.min_pass else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

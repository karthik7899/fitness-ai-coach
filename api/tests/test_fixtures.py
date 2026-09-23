"""The shared import fixtures.

Two implementations read the same backup files now. The schema cannot drift
because it is generated; import behaviour can, so it is pinned here instead.
This test fails when Python's importers stop producing the checked-in rows —
either a regression, or a deliberate change that needs the fixtures
regenerating and the diff reading.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from refresh_fixtures import FIXTURES, build_source, generate  # noqa: E402

from app.adapters.inbox import (  # noqa: E402
    KIND_FITNOTES_DB,
    KIND_GADGETBRIDGE,
    detect_kind,
)


@pytest.fixture(scope="module")
def produced() -> dict[Path, str]:
    return generate()


def test_fixtures_match_the_importers(produced):
    stale = [
        path.relative_to(REPO_ROOT)
        for path, content in produced.items()
        if not path.exists() or path.read_text() != content
    ]
    assert stale == [], (
        f"Import behaviour no longer matches {stale}. If that is deliberate, run "
        "`uv run python ../scripts/refresh_fixtures.py` and read the diff — the "
        "Kotlin importers are held to these same files."
    )


def test_the_fixtures_actually_cover_the_conversions(produced):
    """A fixture that exercised nothing would pass forever without meaning anything."""
    imperial = produced[REPO_ROOT / "fixtures/fitnotes_imperial.expected.csv"]
    # 225 lb -> kg, and miles -> metres.
    assert "102.058" in imperial, "the pounds-to-kilograms conversion is not covered"
    assert "4988.97" in imperial, "the miles-to-metres conversion is not covered"

    metric = produced[REPO_ROOT / "fixtures/fitnotes_metric.expected.csv"]
    # metric_weight wins over the imperial unit flag: 140 stays 140.
    assert ",140," in metric, "metric_weight precedence is not covered"

    watch = produced[REPO_ROOT / "fixtures/gadgetbridge.expected.csv"]
    assert "resting_hr,51" in watch, "the resting-HR percentile is not covered"
    assert "sleep_minutes,3" in watch, "typed sleep samples are not covered"


@pytest.mark.parametrize(
    ("fixture", "kind"),
    [
        ("fitnotes_metric", KIND_FITNOTES_DB),
        ("fitnotes_imperial", KIND_FITNOTES_DB),
        ("gadgetbridge", KIND_GADGETBRIDGE),
    ],
)
def test_both_apps_identify_a_file_the_same_way(tmp_path, fixture, kind):
    """Identification has to agree, not just importing.

    Both apps can watch the same folder. If one recognises a file the other
    ignores, the two databases drift apart with nothing reporting an error —
    the quietest possible failure.
    """
    built = build_source(FIXTURES / f"{fixture}.source.sql", tmp_path / f"{fixture}.db")
    assert detect_kind(built) == kind

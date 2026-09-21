"""The generated tool surface.

The Android app does not declare the coach's tools; it reads the file this
exports. A stale file would mean the phone's coach describing a tool to the
model differently from the desktop's, or offering one that no longer exists.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from export_tools import TARGET, build  # noqa: E402

from app.agent.tools import HANDLERS, TOOL_SPECS  # noqa: E402


def test_the_exported_tool_surface_is_current():
    assert TARGET.exists(), f"{TARGET} is missing. Run scripts/export_tools.py."
    assert TARGET.read_text() == build(), (
        f"{TARGET.relative_to(REPO_ROOT)} is out of date. Run "
        "`uv run python ../scripts/export_tools.py` — the Android coach reads this file."
    )


def test_every_declared_tool_has_a_handler():
    declared = {spec["name"] for spec in TOOL_SPECS}
    assert declared == set(HANDLERS), (
        f"declared and implemented disagree: {declared ^ set(HANDLERS)}"
    )


def test_every_tool_declares_a_usable_schema():
    """A tool the model cannot call correctly is worse than one that is missing."""
    for spec in json.loads(build())["tools"]:
        name = spec["name"]
        assert spec.get("description"), f"{name} has no description for the model to read"
        parameters = spec["parameters"]
        assert parameters["type"] == "object", name
        for required in parameters.get("required", []):
            assert required in parameters["properties"], (
                f"{name} requires '{required}' but never describes it"
            )

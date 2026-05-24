"""Unit tests for the SOS-08-G Surfer annotation-overlay scaffold.

@spec  SOS-08-G-CONCEPTS.md §5.2 (annotation overlay schema — six
       normative fields + two optional), §6 (viewer integration
       contract — (a)-(c) MUST conformance), §7 (INV-S-HDL-G-1..6),
       §15 (ratified 2026-05-23 — PCDN-G-001..007 resolved).
@spec  SOS-08-G-CONCEPTS.md §5.5 + PCDN-G-004 (viewer-extension
       distribution location — in-subrepo).

Wave-1 acceptance gates (per the orchestrator dispatch):
  - load_annotations parses a valid overlay file with the schema
    header and N records (test_load_annotations).
  - validate_schema_header rejects unknown schema names / versions
    (test_validate_schema_header_rejects_unknown).
  - render_to_stdout surfaces cycle + chart_state + transition_id in
    the human-readable preview (test_render_to_stdout).
  - to_surfer_commands emits Surfer-shape marker commands
    (test_to_surfer_commands_emits_markers).
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

# Bootstrap path so the sibling module is importable.
_VIEWERS_DIR = Path(__file__).resolve().parent.parent
if str(_VIEWERS_DIR) not in sys.path:
    sys.path.insert(0, str(_VIEWERS_DIR))

from surfer.sos_surfer_ext import (  # noqa: E402
    SCHEMA_NAME,
    SCHEMA_VERSION,
    load_annotations,
    render_to_stdout,
    to_surfer_commands,
    validate_schema_header,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "example_annotations.jsonl"
)


def test_load_annotations() -> None:
    """Valid overlay parses; surfer scaffold uses shared loader."""
    records = load_annotations(FIXTURE_PATH)
    assert len(records) == 6
    # Spot-check chart-vocabulary fields are present.
    assert records[0]["chart_state"] == "idle"
    assert records[-1]["chart_state"] == "halted"


def test_validate_schema_header_rejects_unknown() -> None:
    """Unknown schema or version raises ValueError."""
    with pytest.raises(ValueError):
        validate_schema_header({"schema": "not-sos", "version": SCHEMA_VERSION})
    with pytest.raises(ValueError):
        validate_schema_header({"schema": SCHEMA_NAME, "version": "0.0"})


def test_render_to_stdout() -> None:
    """Preview surfaces cycle + chart_state + transition_id."""
    records = load_annotations(FIXTURE_PATH)
    buf = io.StringIO()
    render_to_stdout(records, stream=buf)
    out = buf.getvalue()
    assert "surfer" in out  # banner identifies the surfer variant
    assert f"schema={SCHEMA_NAME}" in out
    assert "chart_state=idle" in out
    assert "chart_state=running" in out
    assert "transition_id=t_arming_to_running" in out
    assert "cycle=" in out
    assert "invariant_id=INV-S-CHART-3" in out


def test_to_surfer_commands_emits_markers() -> None:
    """Surfer command script contains add_marker commands per record."""
    records = load_annotations(FIXTURE_PATH)
    text = to_surfer_commands(records)
    assert f"schema={SCHEMA_NAME}" in text
    assert f"version={SCHEMA_VERSION}" in text
    # Surfer's canonical marker command.
    assert "add_marker" in text
    # One add_marker per record (6 records in the fixture).
    assert text.count("add_marker") >= 6
    # Invariant-fire highlight surfaces for the record carrying
    # invariant_id (record #5 / cycle 102).
    assert "mark_invariant" in text
    # The 'arming' chart-state surfaces in a marker label.
    assert "arming" in text
    assert text.endswith("\n")


def test_to_surfer_commands_no_cap() -> None:
    """Surfer emitter does NOT truncate (unlike GTKWave's 26-cap)."""
    records = [
        {
            "cycle": cycle,
            "signal": "dut.fsm_state",
            "chart_state": f"s{cycle}",
            "transition_id": None,
            "chart_path": "/c",
            "region": None,
        }
        for cycle in range(40)
    ]
    text = to_surfer_commands(records)
    # Count only emitted command lines (not the header comments which
    # mention "add_marker" in their narration). One command line per
    # record; 40 records in this fixture.
    command_lines = [
        ln for ln in text.splitlines() if ln.startswith("add_marker ")
    ]
    assert len(command_lines) == 40
    # No cap-note comment in the Surfer output.
    assert "suppressed" not in text

"""Unit tests for the SOS-08-G GTKWave annotation-overlay scaffold.

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
  - to_gtkwave_tcl emits GTKWave-shape marker commands (test_to_
    gtkwave_tcl_emits_markers).
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

# Bootstrap path so the sibling module is importable when pytest runs
# from any working directory. Mirrors the pattern in
# tools/sos-codegen/tests/test_transliterate_cocotb.py.
_VIEWERS_DIR = Path(__file__).resolve().parent.parent
if str(_VIEWERS_DIR) not in sys.path:
    sys.path.insert(0, str(_VIEWERS_DIR))

from gtkwave.sos_gtkwave_ext import (  # noqa: E402
    SCHEMA_NAME,
    SCHEMA_VERSION,
    load_annotations,
    render_to_stdout,
    to_gtkwave_tcl,
    validate_schema_header,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "example_annotations.jsonl"
)


# ---------------------------------------------------------------------------
# load_annotations
# ---------------------------------------------------------------------------


def test_load_annotations() -> None:
    """Valid overlay parses; schema header is accepted; records are returned."""
    records = load_annotations(FIXTURE_PATH)
    # Fixture carries 1 header + 6 records.
    assert len(records) == 6
    # Every record carries cycle + chart_state + chart_path (normative).
    for record in records:
        assert "cycle" in record
        assert "chart_state" in record
        assert "chart_path" in record
    # Spot-check the first transition.
    first = records[0]
    assert first["cycle"] == 0
    assert first["chart_state"] == "idle"


def test_load_annotations_rejects_missing_file(tmp_path: Path) -> None:
    """Absent overlay raises FileNotFoundError with a chart-vocabulary message."""
    missing = tmp_path / "does_not_exist.annotations.jsonl"
    with pytest.raises(FileNotFoundError):
        load_annotations(missing)


def test_load_annotations_rejects_empty_file(tmp_path: Path) -> None:
    """An empty file fails the INV-S-HDL-G-3 header requirement."""
    empty = tmp_path / "empty.annotations.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        load_annotations(empty)


# ---------------------------------------------------------------------------
# validate_schema_header
# ---------------------------------------------------------------------------


def test_validate_schema_header_accepts_simple_shape() -> None:
    """The §5.2 simple-shape header is accepted."""
    validate_schema_header({"schema": SCHEMA_NAME, "version": SCHEMA_VERSION})


def test_validate_schema_header_accepts_meta_envelope() -> None:
    """The §15 amendment ``_meta`` envelope header is accepted."""
    validate_schema_header(
        {
            "_meta": {
                "schema": SCHEMA_NAME,
                "version": SCHEMA_VERSION,
                "chart_path_max_depth": 8,
            }
        }
    )


def test_validate_schema_header_rejects_unknown() -> None:
    """Unknown schema or version raises ValueError per INV-S-HDL-G-3."""
    with pytest.raises(ValueError):
        validate_schema_header({"schema": "bogus-overlay", "version": "1.0"})
    with pytest.raises(ValueError):
        validate_schema_header({"schema": SCHEMA_NAME, "version": "9.9"})


# ---------------------------------------------------------------------------
# render_to_stdout
# ---------------------------------------------------------------------------


def test_render_to_stdout() -> None:
    """Preview surfaces cycle + chart_state + transition_id in human form."""
    records = load_annotations(FIXTURE_PATH)
    buf = io.StringIO()
    render_to_stdout(records, stream=buf)
    out = buf.getvalue()
    # Header lines present.
    assert "SOS-08-G annotation overlay" in out
    assert f"schema={SCHEMA_NAME}" in out
    assert f"version={SCHEMA_VERSION}" in out
    # Spot-check chart-state + transition + cycle appear.
    assert "chart_state=idle" in out
    assert "chart_state=arming" in out
    assert "transition_id=t_idle_to_arming" in out
    assert "cycle=" in out
    # Invariant + vector index surfaced when present.
    assert "invariant_id=INV-S-CHART-3" in out
    assert "vector_index=7" in out


# ---------------------------------------------------------------------------
# to_gtkwave_tcl
# ---------------------------------------------------------------------------


def test_to_gtkwave_tcl_emits_markers() -> None:
    """Tcl output contains GTKWave-shape marker commands."""
    records = load_annotations(FIXTURE_PATH)
    tcl = to_gtkwave_tcl(records)
    # Header comments cite the schema.
    assert f"schema={SCHEMA_NAME}" in tcl
    assert f"version={SCHEMA_VERSION}" in tcl
    # add_marker conventional command surfaces (greppable for wave-2
    # implementations that switch GTKWave command surfaces).
    assert "add_marker" in tcl
    # Set_Named_Marker / Set_Marker_Name GTKWave-canonical commands
    # both surface for the first record.
    assert "Set_Named_Marker" in tcl
    assert "Set_Marker_Name" in tcl
    # The 'arming' chart-state from cycle 12 is rendered as a marker
    # label, and its transition id rides along.
    assert "arming" in tcl
    assert "t_idle_to_arming" in tcl
    # Marker letters are assigned A..F (6 records, well under the 26-cap).
    assert " A " in tcl or "\tA\t" in tcl or " A\n" in tcl or 'A "' in tcl
    # Sanity: the script is non-empty + newline-terminated.
    assert tcl.endswith("\n")


def test_to_gtkwave_tcl_caps_named_markers_at_26() -> None:
    """When > 26 records, the named-marker section caps at A..Z but
    wave-3c (2026-05-24) carries the overflow into the comment-trace
    overlay track per SOS-08-G §6 (d). Verifies BOTH: the cap note
    surfaces for orientation AND all records remain accessible via the
    comment-trace track (no record loss)."""
    records = []
    for cycle in range(30):
        records.append(
            {
                "cycle": cycle,
                "signal": "dut.fsm_state",
                "chart_state": f"s{cycle}",
                "transition_id": None,
                "chart_path": "/c",
                "region": None,
            }
        )
    tcl = to_gtkwave_tcl(records)
    # Named-marker cap-note surfaces.
    assert "named-marker cap" in tcl
    # 4 record(s) overflow (30 - 26) — surfaced as wave-3c overflow
    # message naming the count.
    assert "4 record(s) beyond the named-marker cap" in tcl
    # Wave-3c: all records are carried in the comment-trace overlay
    # track even though only the first 26 get named markers.
    assert tcl.count('"s29"') >= 1
    assert "gtkwave::addCommentTracesFromList" in tcl
    assert "sos:/c" in tcl

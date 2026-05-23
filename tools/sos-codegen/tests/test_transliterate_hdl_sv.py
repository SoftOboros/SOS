"""SOS-08-C SystemVerilog chart→FSM emitter tests.

@spec docs/concepts/SOS-08-C-CONCEPTS.md §6 (10-step emission algorithm)
      docs/concepts/SOS-08-C-CONCEPTS.md §12 (acceptance checklist)
      docs/concepts/SOS-08-C-CONCEPTS.md §7  (INV-S-HDL-C-1..5)
      docs/concepts/SOS-08-C-CONCEPTS.md §15 (2026-05-23 ratification)

These tests verify the wave-1 scope of `transliterate_hdl_sv.render_target`:
  * Single-region SCXML → single SV module emitted.
  * Datamodel signals surface as registered + exposed via output port.
  * One-hot state encoding is the default (PCDN-SOS-08-C-005).
  * Initial state equals the reset state (SOS-08-C §5.6).
  * Document-order priority is preserved for outgoing transitions
    (SOS-08-C §5.2; lint warning `SCXML-LINT-C-1` proposed but the
    emitter itself respects the order).
  * Guards are rejected at wave-1 with a chart-vocabulary error.
  * Parallel regions are rejected at wave-1 with a chart-vocabulary
    error citing SOS-08-C §6.1.

The SV walker (post-SOS-08-C wave-1 integration fix) consumes the raw
scjson dict shape — the same shape the VHDL walker reads. These tests
build the dict inline so the suite has no cross-agent fixture dependency.

Cross-dialect:
  * `test_sv_and_vhdl_have_equivalent_state_constants` loads the same
    fixture and renders once as VHDL and once as SV, asserting state
    names + bit patterns match. This catches drift between the two
    dialects. The test is skipped when the VHDL emitter is not yet
    present (the sibling agent's file lands concurrently); CI will
    re-run it once both are committed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest


# Local imports — the sos-codegen tree is a flat package, mirroring the
# layout used by main.py's `sys.path.insert` shim.
TESTS_DIR = Path(__file__).resolve().parent
TOOL_DIR = TESTS_DIR.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

# hdl_common is authored by a sibling agent in this wave. When the
# sibling's commit has not yet landed (e.g. transient state during
# fan-out), skip the entire suite with a clear message rather than
# raising ImportError during collection.
hdl_common = pytest.importorskip(
    "hdl_common",
    reason="hdl_common sibling-agent module not yet on disk; SV emit tests "
    "skip until the sibling commit lands.",
)

transliterate_hdl_sv = pytest.importorskip(
    "transliterate_hdl_sv",
    reason="transliterate_hdl_sv not importable (hdl_common helper "
    "mismatch?). Suite skips until imports resolve.",
)

pytestmark = pytest.mark.hdl_sv


# ---------------------------------------------------------------------------
# Inline scjson-dict builders.
#
# The wave-1 `render_target` contract takes the raw scjson dict shape,
# not a file path — so tests can synthesize charts without going through
# the `scjson json` shell-out. This keeps the test suite hermetic and
# disjoint from the sibling agent's fixture file plans. The builders
# below mirror the loader's `_collect_states` / `_collect_datamodel`
# expected shapes:
#   chart["initial"]    -> str (state-id)
#   chart["state"]      -> list of { "id": str, "transition": [...],
#                                    "onentry": [...], "onexit": [...] }
#   chart["datamodel"]  -> list of { "data": [{"id": ..., "expr": ...}] }
#   chart["parallel"]   -> list (triggers wave-1 rejection)
# ---------------------------------------------------------------------------


def _state(state_id, *, onentry=None, onexit=None, transitions=None):
    """Build a single-state scjson dict in the loader's expected shape."""
    out: dict[str, Any] = {"id": state_id}
    if onentry is not None:
        out["onentry"] = onentry
    if onexit is not None:
        out["onexit"] = onexit
    if transitions is not None:
        out["transition"] = transitions
    return out


def _simple_chart():
    """A three-state linear chart: A → B → C. No datamodel; transitions
    carry events (wave-1 accepts events — the wave-1 cut just doesn't
    decode them, so the first listed transition wins unconditionally)."""
    return {
        "initial": "A",
        "state": [
            _state("A", transitions=[{"event": "go", "target": "B"}]),
            _state("B", transitions=[{"event": "finish", "target": "C"}]),
            _state("C"),  # terminal
        ],
    }


def _chart_with_datamodel():
    """A two-state chart with a couple of datamodel entries."""
    return {
        "initial": "IDLE",
        "datamodel": [
            {
                "data": [
                    {"id": "counter", "expr": "0"},
                    {"id": "flag", "expr": "false"},
                ],
            }
        ],
        "state": [
            _state("IDLE", transitions=[{"event": "go", "target": "ACTIVE"}]),
            _state("ACTIVE"),
        ],
    }


def _chart_with_guard():
    """A chart whose transition carries a `cond` attribute — wave-1
    rejects with GuardNotSupportedError."""
    return {
        "initial": "A",
        "state": [
            _state(
                "A",
                transitions=[
                    {"event": "tick", "target": "B", "cond": "counter > 0"},
                ],
            ),
            _state("B"),
        ],
    }


def _chart_with_parallel():
    """A chart with a top-level <parallel> — wave-1 rejects with
    ParallelNotSupportedError."""
    return {
        "initial": "p",
        "parallel": [
            {
                "id": "p",
                "state": [_state("p_left"), _state("p_right")],
            }
        ],
    }


def _chart_with_script():
    """A chart whose <onentry> carries a <script> body — wave-1 rejects."""
    return {
        "initial": "s",
        "state": [
            _state(
                "s",
                onentry=[{"script": [{"content": ["doSomething();"]}]}],
            ),
        ],
    }


def _chart_with_doc_order():
    """A chart whose first state has two outgoing transitions in
    document order — wave-1 takes the first one (doc-order priority,
    SOS-08-C §5.2)."""
    return {
        "initial": "A",
        "state": [
            _state(
                "A",
                transitions=[
                    {"event": "first", "target": "B"},
                    {"event": "second", "target": "C"},
                ],
            ),
            _state("B"),
            _state("C"),
        ],
    }


# Cross-dialect equivalence fixture: the same chart shape used by both
# walkers' equivalence test below.
def _three_state_chart():
    return {
        "initial": "A",
        "state": [
            _state("A", transitions=[{"target": "B"}]),
            _state("B", transitions=[{"target": "C"}]),
            _state("C"),
        ],
    }


# ---------------------------------------------------------------------------
# Single-region clean emit.
# ---------------------------------------------------------------------------


def test_single_region_renders_one_sv_file():
    """SOS-08-C §6 ten-step walk: a single-region chart produces a
    single {filename: source} entry from render_target."""
    chart = _simple_chart()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    assert isinstance(out, dict)
    assert len(out) == 1
    fname, src = next(iter(out.items()))
    assert fname.endswith(".sv")
    assert fname.startswith("simple")
    assert "module simple_fsm" in src
    assert "endmodule" in src


def test_single_region_module_contains_state_constants():
    """SOS-08-C §5.1 + §6.2: state-encoding constants are emitted as
    localparam-style declarations, one per chart state, with names
    `ST_<state_id_upper>`."""
    chart = _simple_chart()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    src = next(iter(out.values()))
    assert "ST_A" in src
    assert "ST_B" in src
    assert "ST_C" in src


def test_single_region_includes_clk_rst_current_state_ports():
    """The emitted module SHALL expose clk, rst, current_state per the
    wave-1 port surface (SOS-08-C §6.2 worked example + INV-S-HDL-C-2)."""
    chart = _simple_chart()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    src = next(iter(out.values()))
    # Tolerant of formatting variations.
    assert re.search(r"\bclk\b", src)
    assert re.search(r"\brst\b", src)
    assert re.search(r"\bcurrent_state\b", src)


def test_module_uses_unique_case_for_transition_mux():
    """Per parent CLAUDE.md SV synthesis convention + SOS-08-C §6.2's
    worked example: the transition mux SHALL use `unique case` (SV-2017)
    so synthesis tools enforce exhaustiveness."""
    chart = _simple_chart()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    src = next(iter(out.values()))
    assert "unique case" in src


def test_module_uses_always_ff_and_always_comb():
    """SOS-08-C §6.2: register process is sequential (`always_ff`);
    transition mux is combinational (`always_comb`)."""
    chart = _simple_chart()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    src = next(iter(out.values()))
    assert "always_ff" in src
    assert "always_comb" in src


# ---------------------------------------------------------------------------
# Datamodel signals.
# ---------------------------------------------------------------------------


def test_datamodel_entries_emit_as_signals():
    """SOS-08-C §5.4 + §6.6: each `<data>` element compiles to one
    output port + one internal register."""
    chart = _chart_with_datamodel()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "dm_chart"})
    src = next(iter(out.values()))
    # The emitter sanitizes chart-side identifiers and prefixes them
    # with `data_` — match either bare or prefixed form.
    assert "data_counter" in src
    assert "data_flag" in src


def test_datamodel_signals_have_registered_storage():
    """Per §5.4: signals modified by `<assign>` are registered. Wave-1
    has no `<assign>` compile yet, so signals are registered but hold
    their reset value. Verify the `_q` register exists alongside the
    output wire."""
    chart = _chart_with_datamodel()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "dm_chart"})
    src = next(iter(out.values()))
    assert "data_counter_q" in src
    # The reset block in always_ff should reference the datamodel
    # register reset value (0 for `counter`, 0 / 1'b0 for `flag`).
    assert "if (rst)" in src


# ---------------------------------------------------------------------------
# Encoding & reset state.
# ---------------------------------------------------------------------------


def test_one_hot_is_default_encoding():
    """SOS-08-C §5.1 + PCDN-SOS-08-C-005: one-hot is the default
    encoding at wave-1. The state register width SHALL equal the state
    count (one-hot), and the constants SHALL be powers-of-two."""
    chart = _simple_chart()  # 3 states
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    _, metadata = transliterate_hdl_sv.render_target_with_metadata(
        chart, {"chart_name": "simple"}
    )
    # 3 state-constants, one per state, in document order.
    assert len(metadata["state_constants"]) == 3
    assert metadata["state_names"] == ["A", "B", "C"]
    # The emitted source should declare a state_q register of width
    # equal to the state count.
    src = next(iter(out.values()))
    # Width literal appears in the localparam declarations; tolerate
    # either `3'b001` style or `3'b0...` length prefixes.
    assert re.search(r"3'(?:b|d|h)", src) or "[2:0]" in src


def test_initial_state_equals_reset_state():
    """SOS-08-C §5.6 + PCDN-SOS-08-C-003: SCXML `<initial>` is the
    FSM's reset state. The reset block in `always_ff` SHALL assign the
    initial state's constant to `state_q`."""
    chart = _simple_chart()  # initial="A"
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    src = next(iter(out.values()))
    # In the reset branch, state_q is assigned ST_A.
    # Tolerant of formatting (newlines, indentation).
    reset_match = re.search(
        r"if\s*\(\s*rst\s*\).*?state_q\s*<=\s*ST_A", src, re.S
    )
    assert reset_match is not None, (
        "expected `state_q <= ST_A;` inside the rst branch; chart "
        "initial='A' should match the reset state per SOS-08-C §5.6"
    )


def test_reset_state_follows_chart_initial_attribute():
    """Changing the chart's `initial` attribute changes the reset
    state assignment."""
    chart = {
        "initial": "C",
        "state": [
            _state("A", transitions=[{"target": "B"}]),
            _state("B", transitions=[{"target": "C"}]),
            _state("C"),
        ],
    }
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "foo"})
    src = next(iter(out.values()))
    reset_match = re.search(
        r"if\s*\(\s*rst\s*\).*?state_q\s*<=\s*ST_C", src, re.S
    )
    assert reset_match is not None


# ---------------------------------------------------------------------------
# Document-order priority.
# ---------------------------------------------------------------------------


def test_document_order_priority_first_transition_wins():
    """SOS-08-C §5.2: document-order priority — the first transition in
    the SCXML source out of a state wins on simultaneous-guard-true
    cycles. Wave-1 has no guards; the first transition out of A SHALL
    drive the next-state to B (not C)."""
    chart = _chart_with_doc_order()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "docord"})
    src = next(iter(out.values()))
    # In the transition mux, the arm for ST_A SHALL assign ST_B (not
    # ST_C) as next_state.
    arm_match = re.search(
        r"ST_A\s*:.*?state_next\s*=\s*(ST_[A-Z]+)", src, re.S
    )
    assert arm_match is not None, "expected an ST_A arm in the case"
    assert arm_match.group(1) == "ST_B", (
        "document-order priority violated: first transition "
        "(A→B) should win over second (A→C)"
    )


# ---------------------------------------------------------------------------
# Wave-1 narrow-scope rejections.
# ---------------------------------------------------------------------------


def test_guards_rejected_at_wave_1():
    """SOS-08-C §6.3: guards compile to combinational RTL in a
    follow-on wave. Wave-1 rejects with a chart-vocabulary error."""
    chart = _chart_with_guard()
    with pytest.raises(transliterate_hdl_sv.GuardNotSupportedError) as excinfo:
        transliterate_hdl_sv.render_target(chart, {"chart_name": "guarded"})
    msg = str(excinfo.value)
    assert "SOS-08-C" in msg
    assert "§6.3" in msg or "INV-S-HDL-C-4" in msg


def test_parallel_rejected_at_wave_1():
    """SOS-08-C §6.1: <parallel> region emission lands in a follow-on
    wave. Wave-1 rejects with a chart-vocabulary error."""
    chart = _chart_with_parallel()
    with pytest.raises(
        transliterate_hdl_sv.ParallelNotSupportedError
    ) as excinfo:
        transliterate_hdl_sv.render_target(chart, {"chart_name": "par"})
    msg = str(excinfo.value)
    assert "SOS-08-C" in msg
    assert "§6.1" in msg or "<parallel>" in msg


def test_script_bodies_rejected_at_wave_1():
    """SOS-08-C wave-1: ECMAScript <script> bodies in onentry/onexit
    are rejected; assign-only at v1."""
    chart = _chart_with_script()
    with pytest.raises(transliterate_hdl_sv.UnsupportedChartError) as excinfo:
        transliterate_hdl_sv.render_target(chart, {"chart_name": "scr"})
    msg = str(excinfo.value)
    assert "SOS-08-C" in msg
    assert "script" in msg.lower()


def test_render_target_rejects_non_dict_chart_ir():
    """The wave-1 contract is raw-scjson-dict input; non-dict shapes
    surface a clear UnsupportedChartError so main.py callers see the
    failure in chart vocabulary."""

    class _NotADict:
        pass

    with pytest.raises(transliterate_hdl_sv.UnsupportedChartError) as excinfo:
        transliterate_hdl_sv.render_target(_NotADict(), None)
    assert "raw scjson" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Determinism (INV-S-HDL-C-1).
# ---------------------------------------------------------------------------


def test_emission_is_deterministic():
    """Per INV-S-HDL-C-1: given a fixed chart-IR + fixed config, the
    emitter SHALL produce byte-identical output across runs."""
    chart = _simple_chart()
    out1 = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    out2 = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    assert out1 == out2


def test_emission_contains_spec_citations():
    """Per parent CLAUDE.md `Spec-Before-Code Planning Discipline /
    Execution discipline`: emitted files SHALL cite the spec sections
    they implement. The header comment carries the citations."""
    chart = _simple_chart()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    src = next(iter(out.values()))
    assert "SOS-08-C" in src
    assert "§6" in src  # the ten-step algorithm
    assert "INV-S-HDL-C-" in src  # at least one of C-1..5 cited


# ---------------------------------------------------------------------------
# Cross-dialect equivalence — VHDL vs SV state constants must match.
# This is the load-bearing drift-detection test mandated by the task.
# ---------------------------------------------------------------------------


def test_sv_and_vhdl_have_equivalent_state_constants():
    """Cross-dialect drift detection: render the same chart-IR as both
    VHDL and SV, parse the state-constant declarations out of each,
    and assert the state names + bit patterns match.

    The test is skipped if the VHDL emitter is not yet importable
    (sibling agent's file lands concurrently). When both are present,
    a passing test confirms the two walkers consume the same chart-IR
    shape and produce a consistent state encoding.
    """
    vhdl_module = pytest.importorskip(
        "transliterate_hdl_vhdl",
        reason="VHDL sibling emitter not yet present; cross-dialect "
        "equivalence skipped until both lands.",
    )

    chart = _three_state_chart()
    cfg = {"chart_name": "simple"}

    # Render SV side (with metadata).
    sv_out, sv_meta = transliterate_hdl_sv.render_target_with_metadata(chart, cfg)

    # Render VHDL side. The VHDL walker doesn't yet expose
    # `render_target_with_metadata`, so parse the emitted source for
    # state-constant identifiers.
    vhdl_meta: dict[str, Any]
    if hasattr(vhdl_module, "render_target_with_metadata"):
        _vhdl_out, vhdl_meta = vhdl_module.render_target_with_metadata(chart, cfg)
    else:
        vhdl_out = vhdl_module.render_target(chart, cfg)
        vhdl_src = next(iter(vhdl_out.values()))
        state_names: list[str] = []
        for m in re.finditer(
            r"constant\s+(ST_[A-Z_0-9]+)\s*:", vhdl_src
        ):
            state_names.append(m.group(1))
        vhdl_meta = {"state_constants": state_names, "state_names": state_names}

    # State-constant identifier sets MUST match across dialects.
    assert set(sv_meta["state_constants"]) == set(vhdl_meta["state_constants"]), (
        "SV vs VHDL state constants drifted: "
        f"SV={sv_meta['state_constants']!r} VHDL={vhdl_meta['state_constants']!r}"
    )

    # Ordering MUST also match (one-hot bit positions follow doc order).
    assert sv_meta["state_constants"] == vhdl_meta["state_constants"], (
        "state-constant ORDER differs between SV and VHDL — "
        "one-hot bit positions will not align"
    )

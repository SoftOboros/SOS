"""Wave-1 unit tests for `transliterate_hdl_vhdl.render_target`.

@spec  SOS-08-C-CONCEPTS.md §6 (emission algorithm), §15 (ratification)
@spec  PCDN-C-003 (reset state = SCXML <initial>)
@spec  PCDN-C-005 (chart annotation wins for encoding — wave-1 default = one-hot)
@spec  PCDN-C-006 (document-order priority in transition mux)
@spec  INV-S-HDL-A-1 (sync active-high reset)
@spec  INV-S-HDL-C-1..5 (deterministic emission, observability, etc.)

The wave-1 scaffold consumes the raw scjson dict shape — the same shape
`loader._collect_states` / `_collect_datamodel` walk. The sibling
agent's main.py dispatcher parses SCXML to scjson via `scjson json` and
passes the result to `render_target`; these tests build the same dict
shape inline so the test suite has no cross-agent fixture dependency.

Note: tests do NOT execute pytest themselves (per the orchestrator's
"static deliverable; do NOT run pytest" directive). They define
assertions for the wave-1 acceptance gate that the integration-pass
agent runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the sos-codegen package is importable when pytest is invoked
# from the repo root. Mirrors the bootstrap pattern in
# tests/test_verified_strip.py.
_TOOL_DIR = Path(__file__).resolve().parent.parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))

from transliterate_hdl_vhdl import (  # noqa: E402
    UnsupportedChartError,
    entity_name,
    one_hot_value,
    render_target,
    state_constant_name,
)


# ---------------------------------------------------------------------------
# Inline scjson-dict builders.
#
# The `render_target` wave-1 contract takes the raw scjson dict shape,
# not a file path — so tests can synthesize charts without going through
# the `scjson json` shell-out. This keeps the test suite hermetic and
# disjoint from the sibling agent's fixture file plans.
# ---------------------------------------------------------------------------


def _state(state_id, *, onentry=None, onexit=None, transitions=None):
    """Build a single-state scjson dict in the loader's expected shape."""
    out = {"id": state_id}
    if onentry is not None:
        out["onentry"] = onentry
    if onexit is not None:
        out["onexit"] = onexit
    if transitions is not None:
        out["transition"] = transitions
    return out


def _simple_chart():
    """A 3-state chart: idle → working → done. No datamodel."""
    return {
        "initial": "idle",
        "state": [
            _state(
                "idle",
                transitions=[{"event": "go", "target": "working"}],
            ),
            _state(
                "working",
                transitions=[{"event": "finish", "target": "done"}],
            ),
            _state("done"),
        ],
    }


def _chart_with_datamodel():
    """One state with one datamodel signal `counter` initial 0."""
    return {
        "initial": "running",
        "datamodel": [{"data": [{"id": "counter", "expr": "0"}]}],
        "state": [_state("running")],
    }


def _four_state_chart():
    """A 4-state chart for one-hot encoding verification."""
    return {
        "initial": "a",
        "state": [
            _state("a", transitions=[{"target": "b"}]),
            _state("b", transitions=[{"target": "c"}]),
            _state("c", transitions=[{"target": "d"}]),
            _state("d"),
        ],
    }


def _multi_transition_chart():
    """State `pick` with three outgoing transitions; per PCDN-C-006 the
    first listed transition wins at wave-1."""
    return {
        "initial": "pick",
        "state": [
            _state(
                "pick",
                transitions=[
                    {"event": "first", "target": "winner"},
                    {"event": "second", "target": "loser_a"},
                    {"event": "third", "target": "loser_b"},
                ],
            ),
            _state("winner"),
            _state("loser_a"),
            _state("loser_b"),
        ],
    }


def _chart_with_guarded_transition():
    """A chart whose transition carries a `cond` attribute — rejected at v1."""
    return {
        "initial": "guarded",
        "state": [
            _state(
                "guarded",
                transitions=[
                    {"event": "tick", "target": "next", "cond": "x > 0"},
                ],
            ),
            _state("next"),
        ],
    }


def _chart_with_parallel():
    """A chart with a top-level <parallel> — rejected at v1."""
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
    """A chart whose <onentry> carries a <script> body — rejected at v1."""
    return {
        "initial": "s",
        "state": [
            _state(
                "s",
                onentry=[{"script": [{"content": ["doSomething();"]}]}],
            ),
        ],
    }


# ---------------------------------------------------------------------------
# Wave-1 acceptance tests.
# ---------------------------------------------------------------------------


def test_single_region_simple_emits_clean():
    """SOS-08-C §6.2 acceptance: a 3-state single-region chart emits
    one `<chart>_fsm.vhd` file carrying the required VHDL artifacts
    (library imports, entity, architecture, register process,
    transition mux, current_state output)."""
    chart = _simple_chart()
    files = render_target(chart, {"chart_name": "simple"})
    assert "simple_fsm.vhd" in files
    body = files["simple_fsm.vhd"]
    assert "library ieee;" in body
    assert "use ieee.std_logic_1164.all;" in body
    assert "use ieee.numeric_std.all;" in body
    assert "entity simple_fsm is" in body
    assert "architecture rtl of simple_fsm is" in body
    assert "rising_edge(clk)" in body
    # The reset branch + sync active-high check (INV-S-HDL-A-1).
    assert "rst = '1'" in body
    # Per-state constants present.
    assert state_constant_name("idle") in body
    assert state_constant_name("working") in body
    assert state_constant_name("done") in body
    # current_state observability port (INV-S-HDL-C-2).
    assert "current_state" in body
    # state_q / state_next signals declared.
    assert "signal state_q" in body
    assert "signal state_next" in body


def test_datamodel_signals_emitted():
    """SOS-08-C §5.4 / §6.6: each <data> compiles to a registered signal
    whose reset value is the chart's initial expression. Wave-1 maps
    numeric literals through `to_signed(...)`."""
    chart = _chart_with_datamodel()
    files = render_target(chart, {"chart_name": "dm"})
    body = files["dm_fsm.vhd"]
    # The registered signal carries the `_q` suffix.
    assert "signal counter_q" in body
    # Reset value uses to_signed (numeric_std).
    assert "to_signed(0, counter_q'length)" in body
    # Exposed as an output port driving the datamodel observable.
    assert "data_counter" in body


def test_one_hot_encoding_default():
    """SOS-08-C §5.1 / PCDN-C-005: one-hot encoding by default at wave-1.
    For a 4-state chart the constants are 0001 / 0010 / 0100 / 1000."""
    chart = _four_state_chart()
    files = render_target(chart, {"chart_name": "four"})
    body = files["four_fsm.vhd"]
    # The state-constant literals (one-hot in document order).
    assert '"0001"' in body
    assert '"0010"' in body
    assert '"0100"' in body
    assert '"1000"' in body
    # And the helper returns the same encoding for spot-checking.
    assert one_hot_value(0, 4) == '"0001"'
    assert one_hot_value(3, 4) == '"1000"'


def test_initial_state_is_reset_state():
    """PCDN-C-003: the SCXML <initial> attribute drives the FSM reset
    value. For `initial="idle"` the reset assignment must use
    ST_IDLE."""
    chart = _simple_chart()
    files = render_target(chart, {"chart_name": "init"})
    body = files["init_fsm.vhd"]
    initial_const = state_constant_name("idle")
    # Reset assignment binds state_q <= ST_IDLE when rst='1'.
    assert f"state_q <= {initial_const}" in body


def test_document_order_priority_in_transition_mux():
    """PCDN-C-006: when multiple outgoing transitions share a source
    state, the wave-1 scaffold picks the first listed (document
    order) target. The remaining transitions emit as commented-elided
    lines so chart authors can see them in the output."""
    chart = _multi_transition_chart()
    files = render_target(chart, {"chart_name": "prio"})
    body = files["prio_fsm.vhd"]
    # The case-arm body for ST_PICK selects ST_WINNER, NOT ST_LOSER_*.
    winner = state_constant_name("winner")
    loser_a = state_constant_name("loser_a")
    loser_b = state_constant_name("loser_b")
    # The winner is the chosen state_next assignment.
    assert f"state_next <= {winner}" in body
    # The losers appear only as elided-priority comments — they MUST
    # NOT appear as a direct assignment.
    direct_loser_a = f"state_next <= {loser_a}"
    direct_loser_b = f"state_next <= {loser_b}"
    # Allow them in comment lines (`-- ... target=loser_a`) but reject
    # any direct case-arm assignment.
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        assert direct_loser_a not in stripped
        assert direct_loser_b not in stripped


def test_guards_rejected_at_v1_scaffold():
    """Per the orchestrator's wave-1 scope: charts carrying guarded
    transitions raise `UnsupportedChartError` with a clear message
    citing "SOS-08-C wave-1 scaffold does not emit guards yet"."""
    chart = _chart_with_guarded_transition()
    with pytest.raises(UnsupportedChartError) as exc_info:
        render_target(chart, {"chart_name": "g"})
    msg = str(exc_info.value)
    assert "SOS-08-C wave-1 scaffold does not emit guards yet" in msg


def test_parallel_regions_rejected_at_v1_scaffold():
    """Per the orchestrator's wave-1 scope: charts containing
    <parallel> raise `UnsupportedChartError` citing the deferred wave."""
    chart = _chart_with_parallel()
    with pytest.raises(UnsupportedChartError) as exc_info:
        render_target(chart, {"chart_name": "p"})
    msg = str(exc_info.value)
    assert "SOS-08-C wave-1 scaffold does not emit parallel regions yet" in msg


def test_script_bodies_rejected_at_v1_scaffold():
    """Wave-1 is assign-only — <script> bodies (ECMAScript) raise
    UnsupportedChartError, with wave-2 as the landing wave."""
    chart = _chart_with_script()
    with pytest.raises(UnsupportedChartError) as exc_info:
        render_target(chart, {"chart_name": "sc"})
    msg = str(exc_info.value)
    assert "SOS-08-C wave-1 scaffold does not emit ECMAScript" in msg


def test_render_target_rejects_non_dict_chart_ir():
    """The wave-1 contract takes the raw scjson dict; passing a
    `ChartAst` (the loader's normalised view) by mistake yields a
    clear error so the integration pass can repair the dispatcher."""
    with pytest.raises(UnsupportedChartError) as exc_info:
        render_target("not a dict", {"chart_name": "x"})
    msg = str(exc_info.value)
    assert "expects the raw scjson dict" in msg


def test_entity_name_normalises_chart_name():
    """The VHDL entity name is `<chart>_fsm`, lower-snake-case, with
    any non-identifier chars folded to `_`."""
    assert entity_name("simple") == "simple_fsm"
    assert entity_name("Mixed-Case Chart") == "mixed_case_chart_fsm"
    assert entity_name("1starts_numeric").startswith("x")


def test_default_initial_falls_back_to_first_state():
    """SCXML allows `initial` to be omitted; in that case the FSM's
    reset state is the first state in document order (SOS-08-C §5.6
    cites this as the SCXML default)."""
    chart = {
        "state": [
            _state("alpha"),
            _state("beta"),
        ],
    }
    files = render_target(chart, {"chart_name": "noinit"})
    body = files["noinit_fsm.vhd"]
    alpha = state_constant_name("alpha")
    # Reset binds state_q <= ST_ALPHA (the first state).
    assert f"state_q <= {alpha}" in body


def test_emits_header_comment_with_spec_citations():
    """Every emitted file MUST carry the spec-citation header per
    CLAUDE.md "Execution discipline" — the §15 amendment, PCDN ids,
    and INV ids."""
    files = render_target(_simple_chart(), {"chart_name": "hdr"})
    body = files["hdr_fsm.vhd"]
    assert "SOS-08-C-CONCEPTS.md" in body
    assert "INV-S-HDL" in body
    # At least one PCDN cited.
    assert "PCDN" in body or "C-001" in body or "C-006" in body


def test_empty_chart_raises_clear_error():
    """A chart with no states surfaces an UnsupportedChartError naming
    the wave-1 requirement, NOT a generic IndexError."""
    chart = {"state": []}
    with pytest.raises(UnsupportedChartError) as exc_info:
        render_target(chart, {"chart_name": "empty"})
    msg = str(exc_info.value)
    assert "at least one <state>" in msg

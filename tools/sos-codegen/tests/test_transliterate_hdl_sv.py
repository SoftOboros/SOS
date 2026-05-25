"""SOS-08-C SystemVerilog chart→FSM emitter tests (wave-2).

@spec docs/concepts/SOS-08-C-CONCEPTS.md §6 (10-step emission algorithm)
      docs/concepts/SOS-08-C-CONCEPTS.md §6.3 (guard compilation — wave-2)
      docs/concepts/SOS-08-C-CONCEPTS.md §6.7 (cross-domain wiring)
      docs/concepts/SOS-08-C-CONCEPTS.md §6.10 (chart-top wrapper)
      docs/concepts/SOS-08-C-CONCEPTS.md §12 (acceptance checklist)
      docs/concepts/SOS-08-C-CONCEPTS.md §7  (INV-S-HDL-C-1..5)
      docs/concepts/SOS-08-C-CONCEPTS.md §15 (2026-05-23 ratification)

These tests verify the wave-2 surface of
`transliterate_hdl_sv.render_target`:
  * Single-region SCXML → single SV module emitted.
  * Datamodel signals surface as registered + exposed via output port,
    with multi-bit widths honoured per §5.4 / SOS-04 i32 default.
  * One-hot state encoding is the default (PCDN-SOS-08-C-005).
  * Initial state equals the reset state (SOS-08-C §5.6).
  * Document-order priority is preserved for outgoing transitions.
  * Guards compile to `if (<expr>) / else if (<expr>) / else` chains
    inside each source-state arm (§6.3 / INV-S-HDL-C-4).
  * Over-budget guards raise `UnsupportedChartError` (or
    `GuardDepthExceeded`) per PCDN-C-004.
  * `<parallel>` regions emit N region modules + one chart-top wrapper.
  * Cross-domain signals get `sos_synchronizer` instances in the wrapper.
  * Wave-3 features (`<raise>`, `<script>`) still reject with wave-3
    citations.

Cross-dialect:
  * `test_sv_and_vhdl_have_equivalent_state_constants` loads the same
    fixture and renders once as VHDL and once as SV, asserting state
    names + bit patterns match.
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

# hdl_common is authored by a sibling agent in this wave.
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
    """A three-state linear chart: A → B → C. No datamodel."""
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


def _chart_with_typed_datamodel():
    """Wave-2: chart whose <data> carries `type="int"` (32-bit signed)."""
    return {
        "initial": "IDLE",
        "datamodel": [
            {
                "data": [
                    {"id": "counter", "expr": "0", "type": "int"},
                ],
            }
        ],
        "state": [
            _state("IDLE", transitions=[{"target": "ACTIVE"}]),
            _state("ACTIVE"),
        ],
    }


def _chart_with_guard():
    """Wave-2: chart whose transition carries a `cond` attribute — now
    ACCEPTED (was wave-1 reject)."""
    return {
        "initial": "A",
        "datamodel": [
            {"data": [{"id": "counter", "expr": "0", "type": "int"}]},
        ],
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


def _chart_with_multiple_guards():
    """Wave-2: three guarded transitions out of state A in document order.
    Final unguarded transition becomes the `else` arm."""
    return {
        "initial": "A",
        "datamodel": [
            {"data": [{"id": "counter", "expr": "0", "type": "int"}]},
        ],
        "state": [
            _state(
                "A",
                transitions=[
                    {"target": "B", "cond": "counter == 1"},
                    {"target": "C", "cond": "counter == 2"},
                    {"target": "D", "cond": "counter == 3"},
                    {"target": "A"},  # unguarded default → else arm
                ],
            ),
            _state("B"),
            _state("C"),
            _state("D"),
        ],
    }


def _chart_with_deep_guard():
    """Wave-2: chart whose guard has 9 boolean operators chained — over
    the default depth budget of 8 (PCDN-C-004)."""
    # 9 && operators (depth 9) — over the default budget.
    cond = "a && b && c && d && e && f && g && h && i && j"
    return {
        "initial": "A",
        "state": [
            _state("A", transitions=[{"target": "B", "cond": cond}]),
            _state("B"),
        ],
    }


def _chart_with_parallel():
    """Wave-2: chart with a top-level <parallel> — now ACCEPTED.

    Shape mirrors the canonical scjson tree (see
    ``fixtures/parallel_two_regions.scxml``): a single ``<parallel>``
    element whose ``state`` children are the per-region containers
    (``region_left``/``region_right``). Each region container owns its
    own leaf states + ``initial``. SOS-08-C §6.1 maps each ``<parallel>``
    child to one HDL region module.
    """
    return {
        "initial": "p",
        "parallel": [
            {
                "id": "p",
                "state": [
                    {
                        "id": "left",
                        "initial": "L1",
                        "state": [
                            _state("L1", transitions=[{"target": "L2"}]),
                            _state("L2"),
                        ],
                    },
                    {
                        "id": "right",
                        "initial": "R1",
                        "state": [
                            _state("R1", transitions=[{"target": "R2"}]),
                            _state("R2"),
                        ],
                    },
                ],
            },
        ],
    }


def _chart_with_cross_domain():
    """Wave-2: <parallel> with two regions on different clock domains
    that both touch the same datamodel signal — wrapper must instantiate
    a synchronizer."""
    return {
        "initial": "p",
        "datamodel": [
            {"data": [{"id": "shared", "expr": "0", "type": "int"}]},
        ],
        "parallel": [
            {
                "id": "fast",
                "clock": "fast",
                "initial": "F1",
                "state": [
                    _state(
                        "F1",
                        onentry=[
                            {"assign": [{"location": "shared", "expr": "1"}]}
                        ],
                        transitions=[{"target": "F2"}],
                    ),
                    _state("F2"),
                ],
            },
            {
                "id": "slow",
                "clock": "slow",
                "initial": "S1",
                "state": [
                    _state(
                        "S1",
                        transitions=[
                            {"target": "S2", "cond": "shared > 0"},
                        ],
                    ),
                    _state("S2"),
                ],
            },
        ],
    }


def _chart_with_script():
    """A chart whose <onentry> carries a <script> body — wave-3 still rejects."""
    return {
        "initial": "s",
        "state": [
            _state(
                "s",
                onentry=[{"script": [{"content": ["doSomething();"]}]}],
            ),
        ],
    }


def _chart_with_raise():
    """A chart whose transition carries a <raise> — wave-3 still rejects."""
    return {
        "initial": "A",
        "state": [
            _state(
                "A",
                transitions=[
                    {"target": "B", "raise_value": [{"event": "go"}]},
                ],
            ),
            _state("B"),
        ],
    }


def _chart_with_doc_order():
    """A chart whose first state has two outgoing unguarded transitions.
    Document-order priority — first wins."""
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


def _three_state_chart():
    """Cross-dialect equivalence fixture."""
    return {
        "initial": "A",
        "state": [
            _state("A", transitions=[{"target": "B"}]),
            _state("B", transitions=[{"target": "C"}]),
            _state("C"),
        ],
    }


# ---------------------------------------------------------------------------
# Single-region clean emit (wave-1 surface preserved).
# ---------------------------------------------------------------------------


def test_single_region_renders_one_sv_file():
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
    chart = _simple_chart()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    src = next(iter(out.values()))
    assert "ST_A" in src
    assert "ST_B" in src
    assert "ST_C" in src


def test_single_region_includes_clk_rst_current_state_ports():
    chart = _simple_chart()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    src = next(iter(out.values()))
    assert re.search(r"\bclk\b", src)
    assert re.search(r"\brst\b", src)
    assert re.search(r"\bcurrent_state\b", src)


def test_module_uses_unique_case_for_transition_mux():
    chart = _simple_chart()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    src = next(iter(out.values()))
    assert "unique case" in src


def test_module_uses_always_ff_and_always_comb():
    chart = _simple_chart()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    src = next(iter(out.values()))
    assert "always_ff" in src
    assert "always_comb" in src


# ---------------------------------------------------------------------------
# Datamodel signals.
# ---------------------------------------------------------------------------


def test_datamodel_entries_emit_as_signals():
    chart = _chart_with_datamodel()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "dm_chart"})
    src = next(iter(out.values()))
    assert "data_counter" in src
    assert "data_flag" in src


def test_datamodel_signals_have_registered_storage():
    chart = _chart_with_datamodel()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "dm_chart"})
    src = next(iter(out.values()))
    assert "data_counter_q" in src
    assert "if (rst)" in src


def test_port_width_follows_signal_width():
    """Wave-2: a chart `<data id="counter" type="int"/>` should emit a
    multi-bit port — `wire [31:0] data_counter` — not a scalar."""
    chart = _chart_with_typed_datamodel()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "dm"})
    src = next(iter(out.values()))
    # Match the output-port declaration with a 32-bit width.
    assert re.search(r"output\s+wire\s+\[31:0\]\s+data_counter", src), (
        "expected `output wire [31:0] data_counter` per SOS-08-C §5.4 "
        "(SOS-04 i32 default width)"
    )


# ---------------------------------------------------------------------------
# Encoding & reset state.
# ---------------------------------------------------------------------------


def test_one_hot_is_default_encoding():
    chart = _simple_chart()  # 3 states
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    _, metadata = transliterate_hdl_sv.render_target_with_metadata(
        chart, {"chart_name": "simple"}
    )
    assert len(metadata["state_constants"]) == 3
    assert metadata["state_names"] == ["A", "B", "C"]
    src = next(iter(out.values()))
    assert re.search(r"3'(?:b|d|h)", src) or "[2:0]" in src


def test_initial_state_equals_reset_state():
    chart = _simple_chart()  # initial="A"
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    src = next(iter(out.values()))
    reset_match = re.search(
        r"if\s*\(\s*rst\s*\).*?state_q\s*<=\s*ST_A", src, re.S
    )
    assert reset_match is not None, (
        "expected `state_q <= ST_A;` inside the rst branch; chart "
        "initial='A' should match the reset state per SOS-08-C §5.6"
    )


def test_reset_state_follows_chart_initial_attribute():
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
    chart = _chart_with_doc_order()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "docord"})
    src = next(iter(out.values()))
    # The ST_A arm assigns ST_B (the first unguarded transition).
    arm_match = re.search(
        r"ST_A\s*:\s*begin.*?state_next\s*=\s*(ST_[A-Z]+)", src, re.S
    )
    assert arm_match is not None, "expected an ST_A arm in the case"
    assert arm_match.group(1) == "ST_B", (
        "document-order priority violated: first transition "
        "(A→B) should win over second (A→C)"
    )


# ---------------------------------------------------------------------------
# Guard emission (wave-2).
# ---------------------------------------------------------------------------


def test_guarded_transition_emits_if_block():
    """Wave-2 §6.3 / INV-S-HDL-C-4: a chart transition with a `cond`
    becomes an `if (<expr>) state_next = ST_X;` inside the source-state
    arm — accepted, not rejected."""
    chart = _chart_with_guard()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "guarded"})
    assert len(out) == 1
    src = next(iter(out.values()))
    # Look for an `if (...)` line inside the ST_A arm that assigns ST_B.
    arm_match = re.search(
        r"ST_A\s*:\s*begin(?P<body>.*?)end", src, re.S
    )
    assert arm_match is not None
    body = arm_match.group("body")
    assert re.search(
        r"if\s*\(.*?\)\s*state_next\s*=\s*ST_B", body
    ), f"expected `if (<expr>) state_next = ST_B` inside ST_A; got {body!r}"


def test_multiple_guards_become_elseif_chain():
    """Wave-2 §6.3 + PCDN-C-006: three guarded transitions yield an
    `if / else if / else if / else` chain in document order."""
    chart = _chart_with_multiple_guards()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "multi"})
    src = next(iter(out.values()))
    arm_match = re.search(
        r"ST_A\s*:\s*begin(?P<body>.*?)end", src, re.S
    )
    assert arm_match is not None
    body = arm_match.group("body")
    # First guard → `if (...)` → ST_B.
    assert re.search(
        r"if\s*\(.*?\)\s*state_next\s*=\s*ST_B", body
    ), body
    # Second + third → `else if (...)` → ST_C / ST_D.
    assert re.search(
        r"else\s+if\s*\(.*?\)\s*state_next\s*=\s*ST_C", body
    ), body
    assert re.search(
        r"else\s+if\s*\(.*?\)\s*state_next\s*=\s*ST_D", body
    ), body
    # Trailing unguarded → final `else state_next = ST_A;`.
    assert re.search(r"else\s+state_next\s*=\s*ST_A", body), body


def test_guard_depth_over_budget_fails():
    """Wave-2 PCDN-C-004: a guard whose compiled depth exceeds the budget
    raises a chart-vocabulary error."""
    chart = _chart_with_deep_guard()
    with pytest.raises(transliterate_hdl_sv.UnsupportedChartError) as excinfo:
        transliterate_hdl_sv.render_target(
            chart,
            {"chart_name": "deep", "guard_depth_budget": 8},
        )
    msg = str(excinfo.value)
    assert "SOS-08-C" in msg
    # Either §6.3 or PCDN-C-004 must surface in the chart-vocabulary
    # message.
    assert "§6.3" in msg or "PCDN-C-004" in msg or "depth" in msg.lower()


# ---------------------------------------------------------------------------
# Parallel regions + chart-top wrapper (wave-2).
# ---------------------------------------------------------------------------


def test_parallel_regions_emit_separate_modules():
    """Wave-2 §6.1: `<parallel>` with N children emits N region modules
    plus one chart-top wrapper (N+1 files total)."""
    chart = _chart_with_parallel()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "par"})
    assert len(out) == 3, (
        f"expected 3 output files (2 regions + chart-top wrapper); got "
        f"{sorted(out.keys())!r}"
    )
    # Each region module is `par_region_<name>_fsm.sv`.
    names = sorted(out.keys())
    assert "par_region_left_fsm.sv" in names
    assert "par_region_right_fsm.sv" in names
    assert "par_top.sv" in names


def test_chart_top_wrapper_instantiates_regions():
    """Wave-2 §6.10: the wrapper instantiates each region FSM with the
    per-region module name + a sensible instance name."""
    chart = _chart_with_parallel()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "par"})
    wrapper = out["par_top.sv"]
    # Each region should be instantiated under `u_region_<name>`.
    assert re.search(
        r"par_region_left_fsm\s+u_region_left\s*\(", wrapper
    ), wrapper
    assert re.search(
        r"par_region_right_fsm\s+u_region_right\s*\(", wrapper
    ), wrapper


def test_cross_domain_signal_gets_synchronizer():
    """Wave-2 §6.7 + PCDN-C-002: when two regions on different clock
    domains share a datamodel signal, the chart-top wrapper SHALL
    instantiate an `sos_synchronizer` for that signal."""
    chart = _chart_with_cross_domain()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "cdc"})
    wrapper = out["cdc_top.sv"]
    # The synchronizer instance has parameterised stages + width.
    assert "sos_synchronizer" in wrapper, wrapper
    # Per-domain clk/rst ports surface in the wrapper.
    assert re.search(r"\bclk_fast\b", wrapper), wrapper
    assert re.search(r"\bclk_slow\b", wrapper), wrapper
    # PCDN-C-002 citation in the synchronizer block.
    assert "PCDN-C-002" in wrapper or "MTBF" in wrapper


# ---------------------------------------------------------------------------
# Wave-3 narrow-scope rejections (script + raise still rejected).
# ---------------------------------------------------------------------------


def test_script_bodies_rejected_at_wave_2():
    """Wave-2 still rejects <script> bodies; message cites wave-3."""
    chart = _chart_with_script()
    with pytest.raises(transliterate_hdl_sv.UnsupportedChartError) as excinfo:
        transliterate_hdl_sv.render_target(chart, {"chart_name": "scr"})
    msg = str(excinfo.value)
    assert "SOS-08-C" in msg
    assert "script" in msg.lower()
    assert "wave-3" in msg


def test_raise_accepted_at_wave_3():
    """SOS-08-C wave-3 events (2026-05-23 §15 / §6.5): <raise>
    accepted. The emitted FSM module exposes per-event egress ports
    (`event_<name>_send_valid`) and drives them combinationally for
    one cycle when a matching transition fires. Chart-top wrapper
    sos_message_channel instantiation lands in wave-3-b."""
    chart = _chart_with_raise()
    files = transliterate_hdl_sv.render_target(chart, {"chart_name": "r"})
    src = files["r_fsm.sv"]
    # Per-event egress port emitted.
    assert "event_go_send_valid" in src
    # Combinational drive present (chart event `go` raised when A
    # transitions to B; the only transition out of A is unguarded so
    # the drive predicate is just the state-match).
    assert "assign event_go_send_valid" in src


def test_render_target_rejects_non_dict_chart_ir():
    class _NotADict:
        pass

    with pytest.raises(transliterate_hdl_sv.UnsupportedChartError) as excinfo:
        transliterate_hdl_sv.render_target(_NotADict(), None)
    assert "raw scjson" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Determinism (INV-S-HDL-C-1).
# ---------------------------------------------------------------------------


def test_emission_is_deterministic():
    chart = _simple_chart()
    out1 = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    out2 = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    assert out1 == out2


def test_emission_contains_spec_citations():
    chart = _simple_chart()
    out = transliterate_hdl_sv.render_target(chart, {"chart_name": "simple"})
    src = next(iter(out.values()))
    assert "SOS-08-C" in src
    assert "§6" in src
    assert "INV-S-HDL-C-" in src


# ---------------------------------------------------------------------------
# Cross-dialect equivalence.
# ---------------------------------------------------------------------------


def test_sv_and_vhdl_have_equivalent_state_constants():
    """Cross-dialect drift detection: render the same chart-IR as both
    VHDL and SV, parse the state-constant declarations out of each,
    and assert the state names + bit patterns match."""
    vhdl_module = pytest.importorskip(
        "transliterate_hdl_vhdl",
        reason="VHDL sibling emitter not yet present; cross-dialect "
        "equivalence skipped until both lands.",
    )

    chart = _three_state_chart()
    cfg = {"chart_name": "simple"}

    sv_out, sv_meta = transliterate_hdl_sv.render_target_with_metadata(chart, cfg)

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

    assert set(sv_meta["state_constants"]) == set(vhdl_meta["state_constants"]), (
        "SV vs VHDL state constants drifted: "
        f"SV={sv_meta['state_constants']!r} VHDL={vhdl_meta['state_constants']!r}"
    )

    assert sv_meta["state_constants"] == vhdl_meta["state_constants"], (
        "state-constant ORDER differs between SV and VHDL — "
        "one-hot bit positions will not align"
    )


# ---------------------------------------------------------------------------
# SOS-08-C wave-3 events: event egress emission (§6.5).
# ---------------------------------------------------------------------------


def _chart_with_raise_and_guard():
    """A chart where two raises share a state, gated by a guard."""
    return {
        "initial": "idle",
        "datamodel": [{"data": [{"id": "ready", "expr": "0"}]}],
        "state": [
            {
                "id": "idle",
                "transition": [
                    {"event": "go", "cond": "ready == 1", "target": "active",
                     "raise_value": [{"event": "ack"}]},
                    {"target": "wait_state",
                     "raise_value": [{"event": "ack"}, {"event": "trace"}]},
                ],
            },
            {"id": "active"},
            {"id": "wait_state"},
        ],
    }


class TestWave3Events:
    """SOS-08-C wave-3 events: per-region `<raise>` egress emission."""

    def test_simple_raise_emits_egress_port(self):
        files = transliterate_hdl_sv.render_target(
            _chart_with_raise(), {"chart_name": "r"}
        )
        src = files["r_fsm.sv"]
        assert "output wire event_go_send_valid" in src

    def test_simple_raise_emits_drive(self):
        files = transliterate_hdl_sv.render_target(
            _chart_with_raise(), {"chart_name": "r"}
        )
        src = files["r_fsm.sv"]
        # The unguarded raise from state A produces a simple state-
        # match predicate.
        assert "assign event_go_send_valid = (state_q == ST_A)" in src

    def test_multiple_raises_aggregated(self):
        files = transliterate_hdl_sv.render_target(
            _chart_with_raise_and_guard(), {"chart_name": "m"}
        )
        src = files["m_fsm.sv"]
        # Both event names get their own egress ports (sorted alpha).
        assert "event_ack_send_valid" in src
        assert "event_trace_send_valid" in src

    def test_guard_lowered_into_drive(self):
        files = transliterate_hdl_sv.render_target(
            _chart_with_raise_and_guard(), {"chart_name": "m"}
        )
        src = files["m_fsm.sv"]
        # `ack` fires from the guarded transition (ready==1) OR from
        # the unguarded fallback (when ready != 1). The drive expression
        # includes both terms.
        ack_line = [l for l in src.splitlines() if "event_ack_send_valid" in l and "assign" in l]
        assert ack_line, f"missing event_ack_send_valid drive"
        # The guarded term references the data signal.
        assert "data_ready_q" in ack_line[0]

    def test_safe_event_identifier_sanitises_dots(self):
        """SCXML event names with dots (sem.give) → underscore form."""
        chart_ir = {
            "initial": "a",
            "state": [
                {"id": "a", "transition": [
                    {"target": "b", "raise_value": [{"event": "sem.give"}]},
                ]},
                {"id": "b"},
            ],
        }
        files = transliterate_hdl_sv.render_target(
            chart_ir, {"chart_name": "sem"}
        )
        src = files["sem_fsm.sv"]
        # `sem.give` → `sem_give` for the port name; original preserved
        # in trailing comment.
        assert "event_sem_give_send_valid" in src
        assert "`sem.give`" in src

    def test_single_region_chart_without_raise_no_egress(self):
        """Wave-3 MUST NOT emit egress (send) ports for charts without
        `<raise>`. Wave-3-d-3 added consume-event ingress ports
        (_recv_*) for transitions with `event="..."` attributes —
        those ARE present on `_simple_chart` because it has
        `event="go"` / `event="finish"` transitions, but `_send_*`
        ports require `<raise>` which `_simple_chart` doesn't carry.
        """
        files_a = transliterate_hdl_sv.render_target(
            _simple_chart(), {"chart_name": "x"}
        )
        src = files_a["x_fsm.sv"]
        # No raise side ports.
        assert "send_valid" not in src
        assert "send_ready" not in src


class TestWave3cChartTopChannels:
    """SOS-08-C wave-3-c (2026-05-24 §15): chart-top wrapper
    instantiates one `sos_message_channel` per chart-wide unique
    event name. Per-region egress pulses become internal wires that
    OR-aggregate into the channel's `s_axis_tvalid` input.

    Wave-3-b's per-region `event_<region>_<name>_send_valid`
    boundary ports are SUPERSEDED by wave-3-c's channel-mediated
    `event_<name>_recv_valid` + `event_<name>_recv_ready` pair (one
    per chart-wide unique event name).
    """

    def _parallel_with_raise(self):
        return {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "left", "initial": "L1", "state": [
                        _state("L1", transitions=[
                            {"target": "L2", "raise_value": [{"event": "ack"}]},
                        ]),
                        _state("L2"),
                    ]},
                    {"id": "right", "initial": "R1", "state": [
                        _state("R1", transitions=[
                            {"target": "R2", "raise_value": [{"event": "done"}]},
                        ]),
                        _state("R2"),
                    ]},
                ],
            }],
        }

    def _top(self):
        files = transliterate_hdl_sv.render_target(
            self._parallel_with_raise(), {"chart_name": "k"}
        )
        candidates = [k for k in files if k.endswith("_top.sv") or k == "k_top.sv"]
        assert candidates, f"chart-top wrapper file not in {sorted(files)}"
        return files[candidates[0]]

    def test_chart_top_exposes_recv_valid_per_unique_event(self):
        top = self._top()
        assert "event_ack_recv_valid" in top
        assert "event_done_recv_valid" in top
        # Wave-3-b per-region passthrough port names MUST NOT appear at
        # the wave-3-c boundary (replaced by channel-mediated form).
        assert "event_left_ack_send_valid" not in top
        assert "event_right_done_send_valid" not in top

    def test_chart_top_exposes_recv_ready_per_unique_event(self):
        top = self._top()
        assert "input wire event_ack_recv_ready" in top
        assert "input wire event_done_recv_ready" in top

    def test_chart_top_instantiates_message_channel_per_event(self):
        top = self._top()
        assert "u_chan_ack" in top
        assert "u_chan_done" in top
        assert "sos_message_channel #(" in top

    def test_chart_top_aggregates_per_region_pulses(self):
        top = self._top()
        # Per-region pulse internal wires.
        assert "w_ev_left_ack_pulse" in top
        assert "w_ev_right_done_pulse" in top
        # Region instances wire to the internal pulse, not the
        # superseded per-region boundary port.
        assert ".event_ack_send_valid(w_ev_left_ack_pulse)" in top
        assert ".event_done_send_valid(w_ev_right_done_pulse)" in top
        # Channel's s_axis_tvalid driven by the aggregated wire.
        assert ".s_axis_tvalid(ev_ack_send_valid)" in top
        assert ".s_axis_tvalid(ev_done_send_valid)" in top

    def test_chart_top_omits_channels_when_no_raise(self):
        chart = {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "left", "initial": "L1", "state": [
                        _state("L1", transitions=[{"target": "L2"}]),
                        _state("L2"),
                    ]},
                    {"id": "right", "initial": "R1", "state": [
                        _state("R1", transitions=[{"target": "R2"}]),
                        _state("R2"),
                    ]},
                ],
            }],
        }
        files = transliterate_hdl_sv.render_target(
            chart, {"chart_name": "x"}
        )
        top = files.get("x_top.sv", "")
        assert "event_" not in top
        assert "sos_message_channel" not in top

    def test_multi_producer_event_or_aggregates(self):
        """Two regions raising the SAME event → ONE channel instance,
        s_axis_tvalid is the OR of both producers' pulses."""
        chart = {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "left", "initial": "L1", "state": [
                        _state("L1", transitions=[
                            {"target": "L2", "raise_value": [{"event": "shared"}]},
                        ]),
                        _state("L2"),
                    ]},
                    {"id": "right", "initial": "R1", "state": [
                        _state("R1", transitions=[
                            {"target": "R2", "raise_value": [{"event": "shared"}]},
                        ]),
                        _state("R2"),
                    ]},
                ],
            }],
        }
        files = transliterate_hdl_sv.render_target(
            chart, {"chart_name": "m"}
        )
        top = files["m_top.sv"]
        # ONE channel instance (chart-wide unique event count = 1).
        assert top.count("u_chan_shared (") == 1
        # OR-aggregation of both producers' pulse signals.
        assert ("wire ev_shared_send_valid = "
                "w_ev_left_shared_pulse | w_ev_right_shared_pulse"
                in top)


class TestWave3dProducerBackpressure:
    """SOS-08-C wave-3-d (2026-05-24 §15): producer backpressure on
    `<raise>` egress.

    Each region with `<raise>` transitions gets an `event_<name>_send_ready`
    input port. Transitions are gated on send_ready — state holds in the
    source when the channel is full (cooperative priority-claim per
    INV-S-HDL-4). At the chart-top wrapper, the channel's `s_axis_tready`
    output is routed back to every producer region via a per-event
    `ev_<name>_send_ready` wire.
    """

    def test_region_module_emits_send_ready_input_port(self):
        files = transliterate_hdl_sv.render_target(
            _chart_with_raise(), {"chart_name": "r"}
        )
        src = files["r_fsm.sv"]
        # Wave-3-d pairs each `_send_valid` (output) with a matching
        # `_send_ready` (input) per chart-wide unique raise-event name.
        assert "output wire event_go_send_valid" in src
        assert "input  wire event_go_send_ready" in src

    def test_unguarded_raise_transition_gated_on_send_ready(self):
        """Unguarded raise transitions stall in source when send_ready=0.
        The case-arm wraps the state-advance in `if (send_ready) ... else
        state_next = state_q;` so priority-claim survives backpressure."""
        files = transliterate_hdl_sv.render_target(
            _chart_with_raise(), {"chart_name": "r"}
        )
        src = files["r_fsm.sv"]
        # ST_A's unguarded raise from A→B is wrapped with send_ready.
        assert "if (event_go_send_ready) state_next = ST_B;" in src
        # Stall path holds in source.
        assert "else state_next = ST_A;" in src

    def test_guarded_raise_transition_wrapped_with_send_ready(self):
        """Guarded raise transitions keep their outer guard + inner
        send_ready wrap. Lower-priority transitions MUST NOT take over
        when a high-priority raise is stalled by backpressure."""
        files = transliterate_hdl_sv.render_target(
            _chart_with_raise_and_guard(), {"chart_name": "m"}
        )
        src = files["m_fsm.sv"]
        # Outer guard is `data_ready_q == 1`; inner wrap on ack.
        assert "if (event_ack_send_ready)" in src
        # The unguarded raise-and-trace transition raises BOTH ack and
        # trace — wrap requires AND of both readies.
        assert (
            "if (event_ack_send_ready && event_trace_send_ready)" in src
        )

    def test_non_raising_transition_not_wrapped(self):
        """Transitions WITHOUT `<raise>` retain the wave-1/2 emission
        shape for the egress side — no send_ready wrap. Wave-3-d-3
        does add ingress `_recv_*` ports for `event="..."` transitions,
        but those don't affect the egress side."""
        files = transliterate_hdl_sv.render_target(
            _simple_chart(), {"chart_name": "x"}
        )
        src = files["x_fsm.sv"]
        # No raise-side ports on a chart without `<raise>`.
        assert "send_ready" not in src
        assert "send_valid" not in src

    def _parallel_with_raise(self):
        return {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "left", "initial": "L1", "state": [
                        _state("L1", transitions=[
                            {"target": "L2", "raise_value": [{"event": "ack"}]},
                        ]),
                        _state("L2"),
                    ]},
                    {"id": "right", "initial": "R1", "state": [
                        _state("R1", transitions=[
                            {"target": "R2", "raise_value": [{"event": "done"}]},
                        ]),
                        _state("R2"),
                    ]},
                ],
            }],
        }

    def _top(self):
        files = transliterate_hdl_sv.render_target(
            self._parallel_with_raise(), {"chart_name": "k"}
        )
        return files["k_top.sv"]

    def test_chart_top_declares_per_event_send_ready_wire(self):
        top = self._top()
        assert "wire ev_ack_send_ready;" in top
        assert "wire ev_done_send_ready;" in top

    def test_chart_top_wires_channel_s_axis_tready_to_send_ready(self):
        """Channel's s_axis_tready connects to the per-event send_ready
        wire (NOT left unconnected as in wave-3-c)."""
        top = self._top()
        assert ".s_axis_tready(ev_ack_send_ready)" in top
        assert ".s_axis_tready(ev_done_send_ready)" in top
        # Wave-3-c's `.s_axis_tready(),` (unconnected) MUST NOT appear.
        assert ".s_axis_tready()," not in top

    def test_chart_top_fans_send_ready_to_producer_regions(self):
        """Each producer region instance gets the per-event send_ready
        wire connected to its `event_<name>_send_ready` input port."""
        top = self._top()
        assert ".event_ack_send_ready(ev_ack_send_ready)" in top
        assert ".event_done_send_ready(ev_done_send_ready)" in top

    def test_multi_producer_backpressure_broadcasts(self):
        """Two regions raising the SAME event share ONE channel; the
        channel's s_axis_tready broadcasts to BOTH producers' send_ready
        inputs. INV-S-HDL-4 cooperative-only makes the broadcast correct
        (at most one producer pulses per cycle)."""
        chart = {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "left", "initial": "L1", "state": [
                        _state("L1", transitions=[
                            {"target": "L2", "raise_value": [{"event": "shared"}]},
                        ]),
                        _state("L2"),
                    ]},
                    {"id": "right", "initial": "R1", "state": [
                        _state("R1", transitions=[
                            {"target": "R2", "raise_value": [{"event": "shared"}]},
                        ]),
                        _state("R2"),
                    ]},
                ],
            }],
        }
        files = transliterate_hdl_sv.render_target(
            chart, {"chart_name": "m"}
        )
        top = files["m_top.sv"]
        # ONE send_ready wire shared by BOTH producers.
        assert top.count("wire ev_shared_send_ready;") == 1
        # Both producers wire to the same shared signal.
        # Broadcast under INV-S-HDL-4.
        ready_drives = [
            l for l in top.splitlines()
            if ".event_shared_send_ready(ev_shared_send_ready)" in l
        ]
        assert len(ready_drives) == 2, (
            "expected 2 send_ready fanouts (one per producer region)"
        )


class TestWave3d3EventIngressRefactor:
    """SOS-08-C wave-3-d-3 (2026-05-24 §15): event ingress refactor.

    Transitions with `event="..."` are now gated on `_recv_valid` (until
    this wave, the event attribute was captured but unused at emit
    time — transitions fired combinationally on state + cond alone).
    Per consumed event, the region FSM emits a (_recv_valid input,
    _recv_ready output) port pair. The chart-top wrapper fans channel
    `m_axis_tvalid` to every consuming region + OR-aggregates the
    consumers' _recv_ready outputs into channel `m_axis_tready`.
    """

    def test_region_emits_recv_valid_input_port(self):
        chart = {
            "initial": "A",
            "state": [
                _state("A", transitions=[{"event": "go", "target": "B"}]),
                _state("B"),
            ],
        }
        files = transliterate_hdl_sv.render_target(chart, {"chart_name": "r"})
        src = files["r_fsm.sv"]
        assert "input  wire event_go_recv_valid" in src
        assert "output wire event_go_recv_ready" in src

    def test_event_transition_gated_on_recv_valid(self):
        """A transition with `event="go"` (no cond) is gated on
        `event_go_recv_valid` in the case-arm — NOT emitted as an
        unguarded `state_next = target;`."""
        chart = {
            "initial": "A",
            "state": [
                _state("A", transitions=[{"event": "go", "target": "B"}]),
                _state("B"),
            ],
        }
        files = transliterate_hdl_sv.render_target(chart, {"chart_name": "r"})
        src = files["r_fsm.sv"]
        assert "if (event_go_recv_valid) state_next = ST_B;" in src

    def test_event_and_cond_combined_in_predicate(self):
        """A transition with both `event` and `cond` AND-combines them
        in the predicate."""
        chart = {
            "initial": "idle",
            "datamodel": [{"data": [{"id": "ready", "expr": "0"}]}],
            "state": [
                {
                    "id": "idle",
                    "transition": [
                        {"event": "tick", "cond": "ready == 1",
                         "target": "active"},
                    ],
                },
                {"id": "active"},
            ],
        }
        files = transliterate_hdl_sv.render_target(chart, {"chart_name": "c"})
        src = files["c_fsm.sv"]
        # Combined predicate: event_recv_valid && cond.
        assert (
            "if (event_tick_recv_valid && ((data_ready_q == 1)))" in src
        )

    def test_recv_ready_drive_asserts_in_source_state(self):
        """`event_<name>_recv_ready` asserts when this region is in a
        state with a non-elided transition consuming the event. recv_ready
        does NOT include the event's own _recv_valid term (would create
        a combinational dependency through the channel)."""
        chart = {
            "initial": "A",
            "state": [
                _state("A", transitions=[{"event": "go", "target": "B"}]),
                _state("B"),
            ],
        }
        files = transliterate_hdl_sv.render_target(chart, {"chart_name": "r"})
        src = files["r_fsm.sv"]
        assert "assign event_go_recv_ready = (state_q == ST_A);" in src

    def test_doc_order_priority_with_events(self):
        """Multiple transitions with different events from same source
        form an if/elsif chain — first event arriving wins (PCDN-C-006
        doc-order priority preserved)."""
        chart = {
            "initial": "pick",
            "state": [
                _state("pick", transitions=[
                    {"event": "first", "target": "to_first"},
                    {"event": "second", "target": "to_second"},
                ]),
                _state("to_first"),
                _state("to_second"),
            ],
        }
        files = transliterate_hdl_sv.render_target(chart, {"chart_name": "x"})
        src = files["x_fsm.sv"]
        # First transition emits in if/elsif chain — first matching
        # event-valid wins per PCDN-C-006.
        assert "if (event_first_recv_valid) state_next = ST_TO_FIRST;" in src
        # Second transition is in elsif — only fires when first event
        # NOT valid this cycle.
        assert (
            "else if (event_second_recv_valid) state_next = ST_TO_SECOND;"
            in src
        )

    def test_chart_top_fans_recv_valid_to_consumers(self):
        """Chart-top wrapper: channel `m_axis_tvalid` connects to an
        internal `ev_<name>_recv_valid_w` wire which is driven OUT to
        the boundary AND fanned to every consuming region's
        `event_<name>_recv_valid` input."""
        chart = {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "left", "initial": "L1", "state": [
                        _state("L1", transitions=[
                            {"target": "L2", "raise_value": [{"event": "tick"}]},
                        ]),
                        _state("L2"),
                    ]},
                    {"id": "right", "initial": "R1", "state": [
                        _state("R1", transitions=[
                            {"event": "tick", "target": "R2"},
                        ]),
                        _state("R2"),
                    ]},
                ],
            }],
        }
        files = transliterate_hdl_sv.render_target(chart, {"chart_name": "k"})
        top = files["k_top.sv"]
        # Per-event recv_valid fanout wire declared.
        assert "wire ev_tick_recv_valid_w;" in top
        # Channel drives the fanout wire.
        assert ".m_axis_tvalid(ev_tick_recv_valid_w)" in top
        # Boundary observer port driven by the fanout wire.
        assert "assign event_tick_recv_valid = ev_tick_recv_valid_w;" in top
        # Consumer region wired to the fanout.
        assert (
            ".event_tick_recv_valid(ev_tick_recv_valid_w)" in top
        )

    def test_chart_top_aggregates_recv_ready(self):
        """`m_axis_tready` is OR of boundary _recv_ready input AND
        every consumer region's _recv_ready output."""
        chart = {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "left", "initial": "L1", "state": [
                        _state("L1", transitions=[
                            {"target": "L2", "raise_value": [{"event": "tick"}]},
                        ]),
                        _state("L2"),
                    ]},
                    {"id": "right", "initial": "R1", "state": [
                        _state("R1", transitions=[
                            {"event": "tick", "target": "R2"},
                        ]),
                        _state("R2"),
                    ]},
                ],
            }],
        }
        files = transliterate_hdl_sv.render_target(chart, {"chart_name": "k"})
        top = files["k_top.sv"]
        # Per-consumer ready wire.
        assert "wire w_ev_right_tick_ready;" in top
        # OR-aggregation: boundary | each consumer.
        assert (
            "wire ev_tick_recv_ready_w = event_tick_recv_ready | "
            "w_ev_right_tick_ready;" in top
        )
        # Channel drives from aggregated ready.
        assert ".m_axis_tready(ev_tick_recv_ready_w)" in top

    def test_event_attribute_no_longer_ignored(self):
        """Regression guard for the §6.4 fix: prior to wave-3-d-3,
        transitions with `event="..."` had the event attribute IGNORED
        at emit time — they fired combinationally on state + cond
        alone. Wave-3-d-3 correctly gates them on `_recv_valid`."""
        # `_simple_chart` has `event="go"` and `event="finish"` — pre
        # wave-3-d-3, the state advances were emitted directly:
        #   ST_A: state_next = ST_B;
        # Post wave-3-d-3:
        #   ST_A: if (event_go_recv_valid) state_next = ST_B; ...
        files = transliterate_hdl_sv.render_target(
            _simple_chart(), {"chart_name": "x"}
        )
        src = files["x_fsm.sv"]
        # The bare unconditional advance MUST NOT appear inside the
        # ST_A case-arm — it must be gated on recv_valid.
        # We look for the bare assign WITHOUT the wrapping if/else.
        assert "if (event_go_recv_valid) state_next = ST_B;" in src
        assert "if (event_finish_recv_valid) state_next = ST_C;" in src


class TestWave3d2AsyncChannelVariant:
    """SOS-08-C wave-3-d-2 (2026-05-24 §15): walker selects between
    `sos_message_channel` (single-clock) and `sos_message_channel_async`
    (CDC) based on producer/consumer clock-domain alignment.

    Per SOS-08-B §15 2026-05-24 amendment, the channel family has TWO
    sibling primitives. Selection contract:
      - producer + consumer same clock → sos_message_channel.
      - producer + consumer different clocks → sos_message_channel_async
        with wr_clk = producer domain, rd_clk = consumer domain.
      - multi-domain producers OR consumers per event → walker raises.
    """

    def _cdc_chart(self):
        """Two parallel regions on different clock domains; one raises
        `tick`, the other consumes it."""
        return {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "fast", "clock": "fast", "initial": "F1",
                     "state": [
                         _state("F1", transitions=[
                             {"target": "F2",
                              "raise_value": [{"event": "tick"}]},
                         ]),
                         _state("F2"),
                     ]},
                    {"id": "slow", "clock": "slow", "initial": "S1",
                     "state": [
                         _state("S1", transitions=[
                             {"event": "tick", "target": "S2"},
                         ]),
                         _state("S2"),
                     ]},
                ],
            }],
        }

    def test_cdc_chart_selects_async_variant(self):
        files = transliterate_hdl_sv.render_target(
            self._cdc_chart(), {"chart_name": "cdc"}
        )
        top = files["cdc_top.sv"]
        # Async variant primitive instantiated for the cross-domain
        # event.
        assert "sos_message_channel_async #(" in top
        # SYNC_STAGES parameter present.
        assert ".SYNC_STAGES(2)" in top
        # The sync variant MUST NOT be instantiated for this chart.
        assert "sos_message_channel #(" not in top

    def test_async_variant_uses_wr_clk_from_producer(self):
        files = transliterate_hdl_sv.render_target(
            self._cdc_chart(), {"chart_name": "cdc"}
        )
        top = files["cdc_top.sv"]
        # Producer is region `fast` → wr_clk = clk_fast.
        assert ".wr_clk(clk_fast)" in top
        assert ".wr_rst(rst_fast)" in top
        # Consumer is region `slow` → rd_clk = clk_slow.
        assert ".rd_clk(clk_slow)" in top
        assert ".rd_rst(rst_slow)" in top

    def test_async_variant_exposes_per_domain_observability(self):
        """Async variant has wr_full/wr_count + rd_empty/rd_count
        (split across the two domains)."""
        files = transliterate_hdl_sv.render_target(
            self._cdc_chart(), {"chart_name": "cdc"}
        )
        top = files["cdc_top.sv"]
        assert ".wr_full()" in top
        assert ".wr_count()" in top
        assert ".rd_empty()" in top
        assert ".rd_count()" in top
        # Single-clock unified observability ports MUST NOT appear.
        # (At least, not in a way that's confusable with the async
        # variant.)
        assert ".full()" not in top  # async has wr_full instead
        assert ".empty()" not in top  # async has rd_empty instead

    def test_single_clock_chart_still_uses_sync_variant(self):
        """Regression: charts with all regions on one clock domain
        continue to use the wave-3-c sync variant."""
        chart = {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "left", "initial": "L1", "state": [
                        _state("L1", transitions=[
                            {"target": "L2", "raise_value": [{"event": "tick"}]},
                        ]),
                        _state("L2"),
                    ]},
                    {"id": "right", "initial": "R1", "state": [
                        _state("R1", transitions=[
                            {"event": "tick", "target": "R2"},
                        ]),
                        _state("R2"),
                    ]},
                ],
            }],
        }
        files = transliterate_hdl_sv.render_target(chart, {"chart_name": "x"})
        top = files["x_top.sv"]
        # Sync variant — no SYNC_STAGES generic, single clk/rst.
        assert "sos_message_channel #(" in top
        assert "sos_message_channel_async #(" not in top
        # Single clk/rst on the channel instance.
        assert ".clk(clk_main)" in top
        # Async-only ports MUST NOT appear on the sync channel.
        assert ".wr_clk(" not in top
        assert ".rd_clk(" not in top

    def test_multi_producer_domains_raises(self):
        """Wave-3-d-2 does not support multiple producer clock domains
        per chart event — walker raises ValueError."""
        chart = {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "fast", "clock": "fast", "initial": "F1",
                     "state": [
                         _state("F1", transitions=[
                             {"target": "F2",
                              "raise_value": [{"event": "shared"}]},
                         ]),
                         _state("F2"),
                     ]},
                    {"id": "slow", "clock": "slow", "initial": "S1",
                     "state": [
                         _state("S1", transitions=[
                             {"target": "S2",
                              "raise_value": [{"event": "shared"}]},
                         ]),
                         _state("S2"),
                     ]},
                ],
            }],
        }
        import pytest
        with pytest.raises(ValueError, match="multiple clock domains"):
            transliterate_hdl_sv.render_target(
                chart, {"chart_name": "x"}
            )


class TestWave3ePayloadRouting:
    """SOS-08-C wave-3-e (2026-05-24 §15): payload data routing.

    Chart `<raise>` elements with `<param name="x" expr="..."/>`
    children produce payload data ports:
      - Region FSM: `event_<name>_send_data[7:0]` output (producer)
        + `event_<name>_recv_data[7:0]` input (consumer).
      - Chart-top: per-event data wires; channel's `s_axis_tpayload`
        and `m_axis_tpayload` wired through; boundary observer port
        `event_<name>_recv_data[7:0]` exposes payload externally.
    PAYLOAD_WIDTH = 8 at v1 (matches channel hardcoded baseline).

    Events without `<param>` retain the wave-3-{a..d} valid/ready-
    only emission (no data ports).
    """

    def _chart_with_payload(self):
        return {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "left", "initial": "L1",
                     "datamodel": [
                         {"data": [{"id": "counter", "expr": "5"}]},
                     ],
                     "state": [
                         _state("L1", transitions=[
                             {"target": "L2", "raise_value": [
                                 {"event": "tick", "param": [
                                     {"name": "value", "expr": "counter"},
                                 ]},
                             ]},
                         ]),
                         _state("L2"),
                     ]},
                    {"id": "right", "initial": "R1", "state": [
                        _state("R1", transitions=[
                            {"event": "tick", "target": "R2"},
                        ]),
                        _state("R2"),
                    ]},
                ],
            }],
        }

    def test_payload_event_emits_send_data_on_producer(self):
        files = transliterate_hdl_sv.render_target(
            self._chart_with_payload(), {"chart_name": "pl"}
        )
        producer = files["pl_region_left_fsm.sv"]
        assert "output wire [7:0] event_tick_send_data" in producer

    def test_payload_event_emits_recv_data_on_consumer(self):
        files = transliterate_hdl_sv.render_target(
            self._chart_with_payload(), {"chart_name": "pl"}
        )
        consumer = files["pl_region_right_fsm.sv"]
        assert "input  wire [7:0] event_tick_recv_data" in consumer

    def test_send_data_driven_from_param_expr(self):
        """When the raising transition fires, `_send_data` carries
        the compiled param expr (datamodel signal rewritten to
        registered form `data_<x>_q`). Else zero."""
        files = transliterate_hdl_sv.render_target(
            self._chart_with_payload(), {"chart_name": "pl"}
        )
        producer = files["pl_region_left_fsm.sv"]
        # The fire predicate gates the data drive; data_counter_q
        # comes from the param expr "counter" rewritten to its
        # registered form.
        assert (
            "((state_q == ST_L1) ? 8'(data_counter_q) : 8'd0)"
            in producer
        )

    def test_chart_top_exposes_recv_data_boundary_port(self):
        files = transliterate_hdl_sv.render_target(
            self._chart_with_payload(), {"chart_name": "pl"}
        )
        top = files["pl_top.sv"]
        assert "output wire [7:0] event_tick_recv_data" in top

    def test_chart_top_wires_channel_tpayload(self):
        """Channel's `s_axis_tpayload` connects to producer-data
        aggregate; `m_axis_tpayload` connects to recv_data fanout."""
        files = transliterate_hdl_sv.render_target(
            self._chart_with_payload(), {"chart_name": "pl"}
        )
        top = files["pl_top.sv"]
        assert ".s_axis_tpayload(ev_tick_send_data)" in top
        assert ".m_axis_tpayload(ev_tick_recv_data_w)" in top
        # Data wire declarations.
        assert "wire [7:0] w_ev_left_tick_data;" in top
        assert "wire [7:0] ev_tick_recv_data_w;" in top
        # Producer-side aggregation (single producer here).
        assert (
            "wire [7:0] ev_tick_send_data = w_ev_left_tick_data;" in top
        )
        # Boundary observer driven by fanout wire.
        assert (
            "assign event_tick_recv_data = ev_tick_recv_data_w;" in top
        )

    def test_chart_top_region_instance_wires_data_ports(self):
        files = transliterate_hdl_sv.render_target(
            self._chart_with_payload(), {"chart_name": "pl"}
        )
        top = files["pl_top.sv"]
        # Producer region wires its _send_data to the per-region wire.
        assert (
            ".event_tick_send_data(w_ev_left_tick_data)" in top
        )
        # Consumer region wires its _recv_data to the chart-wide
        # fanout wire.
        assert (
            ".event_tick_recv_data(ev_tick_recv_data_w)" in top
        )

    def test_non_payload_event_keeps_minimal_ports(self):
        """Events raised WITHOUT `<param>` MUST NOT get data ports —
        the wave-3-{a..d} valid/ready-only shape is preserved."""
        chart = {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "left", "initial": "L1", "state": [
                        _state("L1", transitions=[
                            {"target": "L2", "raise_value": [
                                {"event": "tick"},  # NO <param>
                            ]},
                        ]),
                        _state("L2"),
                    ]},
                    {"id": "right", "initial": "R1", "state": [
                        _state("R1", transitions=[
                            {"event": "tick", "target": "R2"},
                        ]),
                        _state("R2"),
                    ]},
                ],
            }],
        }
        files = transliterate_hdl_sv.render_target(
            chart, {"chart_name": "np"}
        )
        producer = files["np_region_left_fsm.sv"]
        consumer = files["np_region_right_fsm.sv"]
        top = files["np_top.sv"]
        # No data ports anywhere.
        assert "send_data" not in producer
        assert "recv_data" not in consumer
        assert "send_data" not in top
        assert "recv_data" not in top


# ---------------------------------------------------------------------------
# SOS-08-C wave-3-f (2026-05-24 §15) — datamodel binding on consume side.
# ---------------------------------------------------------------------------


class TestWave3fEventPayloadCapture:
    """Wave-3-f lowers `<onentry><assign location="X"
    expr="event.<EV>.value"/></onentry>` into a registered assignment
    gated by `state_q != ST_S && state_next == ST_S &&
    event_<EV>_recv_valid`. Tests verify the SV emit shape +
    backwards-compat with charts that don't use the form."""

    def _chart_with_capture(self):
        return {
            "datamodel": [{"data": [
                {"id": "last_value", "expr": "0", "type": "i32"},
            ]}],
            "state": [
                {"id": "idle", "transition": [{"event": "tick", "target": "observed"}]},
                {
                    "id": "observed",
                    "onentry": [{"assign": [
                        {"location": "last_value", "expr": "event.tick.value"},
                    ]}],
                    "transition": [{"target": "idle"}],
                },
            ],
            "initial": "idle",
        }

    def _files(self) -> dict:
        return transliterate_hdl_sv.render_target(
            self._chart_with_capture(), {"chart_name": "cap"}
        )

    def test_register_process_emits_capture_branch(self):
        sv = self._files()["cap_fsm.sv"]
        assert (
            "state_q != ST_OBSERVED && state_next == ST_OBSERVED && "
            "event_tick_recv_valid"
        ) in sv

    def test_capture_branch_assigns_recv_data(self):
        sv = self._files()["cap_fsm.sv"]
        assert "data_last_value_q <= event_tick_recv_data" in sv

    def test_capture_default_holds_value(self):
        """Outside the capture entry-edge the datamodel register holds
        its previous value (the else branch of the if/else chain)."""
        sv = self._files()["cap_fsm.sv"]
        assert "data_last_value_q <= data_last_value_q" in sv

    def test_capture_does_not_break_state_register(self):
        sv = self._files()["cap_fsm.sv"]
        assert "state_q <= state_next" in sv
        assert "state_q <= ST_IDLE" in sv

    def test_capture_target_is_consume_event_check(self):
        """If the chart writes `event.<EV>.value` but the region does
        NOT consume event EV, the walker MUST raise a chart-vocabulary
        error rather than silently emit dead code."""
        chart = self._chart_with_capture()
        chart["state"][1]["onentry"][0]["assign"][0]["expr"] = (
            "event.nonsense.value"
        )
        with pytest.raises(
            transliterate_hdl_sv.UnsupportedChartError,
            match="NOT a consume event",
        ):
            transliterate_hdl_sv.render_target(chart, {"chart_name": "cap"})

    def test_multiple_captures_into_same_signal_form_chain(self):
        """Two `<onentry>` captures into the SAME datamodel signal
        from DIFFERENT states form an if/else if chain (document
        order). Each branch routes its own event's `_recv_data`."""
        chart = {
            "datamodel": [{"data": [{"id": "buf", "expr": "0", "type": "i32"}]}],
            "state": [
                {"id": "s0", "transition": [
                    {"event": "a", "target": "s_a"},
                    {"event": "b", "target": "s_b"},
                ]},
                {
                    "id": "s_a",
                    "onentry": [{"assign": [
                        {"location": "buf", "expr": "event.a.value"},
                    ]}],
                    "transition": [{"target": "s0"}],
                },
                {
                    "id": "s_b",
                    "onentry": [{"assign": [
                        {"location": "buf", "expr": "event.b.value"},
                    ]}],
                    "transition": [{"target": "s0"}],
                },
            ],
            "initial": "s0",
        }
        sv = transliterate_hdl_sv.render_target(chart, {"chart_name": "m"})["m_fsm.sv"]
        assert "event_a_recv_valid" in sv
        assert "event_b_recv_valid" in sv
        assert "data_buf_q <= event_a_recv_data" in sv
        assert "data_buf_q <= event_b_recv_data" in sv
        # If/else if chain present.
        assert "end else if" in sv

    def test_capture_only_emitted_for_event_value_form(self):
        """An `<assign>` with a numeric-literal expr (not
        `event.<EV>.value`) is silently ignored by wave-3-f — the
        register-process body does NOT emit a capture branch for it
        (preserves wave-1/wave-2 semantics for non-event assigns)."""
        chart = {
            "datamodel": [{"data": [{"id": "x", "expr": "0", "type": "i32"}]}],
            "state": [
                {"id": "a",
                 "onentry": [{"assign": [{"location": "x", "expr": "42"}]}],
                 "transition": [{"target": "b"}]},
                {"id": "b"},
            ],
            "initial": "a",
        }
        sv = transliterate_hdl_sv.render_target(
            chart, {"chart_name": "n"}
        )["n_fsm.sv"]
        # No event-recv reference on data_x_q.
        assert "data_x_q <= event_" not in sv
        # data_x_q still holds (wave-1/wave-2 shape).
        assert "data_x_q <= data_x_q" in sv

    def test_no_captures_preserves_wave1_register_process_shape(self):
        """A chart with NO event-payload captures emits the wave-1/-2
        register-process shape (no wave-3-f if/else if chain)."""
        chart = {
            "datamodel": [{"data": [{"id": "x", "expr": "0", "type": "i32"}]}],
            "state": [
                {"id": "a", "transition": [{"target": "b"}]},
                {"id": "b"},
            ],
            "initial": "a",
        }
        sv = transliterate_hdl_sv.render_target(
            chart, {"chart_name": "p"}
        )["p_fsm.sv"]
        assert "data_x_q <= event_" not in sv
        assert "data_x_q <= data_x_q" in sv

    def test_emitted_sv_default_nettype_guards_present(self):
        """Wave-3-f emit MUST preserve the `default_nettype` guards
        (wave-1 shape) so the module compiles cleanly under strict
        Verilator settings."""
        sv = self._files()["cap_fsm.sv"]
        assert "`default_nettype none" in sv
        assert "`default_nettype wire" in sv


# ---------------------------------------------------------------------------
# Wave-3-f-future-A (2026-05-24 §15) — `<onexit>` captures.
# Wave-3-f-future-B remains carry-forward (multi-`<param>` events); the
# walker rejects the syntactic form with an actionable error here so
# chart authors get a citation rather than silently-mismatched ports.
# ---------------------------------------------------------------------------


class TestWave3fFutureOnexitCapture:
    """Wave-3-f-future-A: lowering `<onexit><assign expr="event.<EV>.value"/>`
    fires on the exit-edge from the carrying state (gating inverted
    from the entry shape)."""

    def _chart_with_onexit_capture(self):
        return {
            "datamodel": [{"data": [
                {"id": "last_seen", "expr": "0", "type": "i32"},
            ]}],
            "state": [
                {"id": "idle", "transition": [
                    {"event": "tick", "target": "observed"},
                ]},
                {
                    "id": "observed",
                    "onexit": [{"assign": [
                        {"location": "last_seen", "expr": "event.tick.value"},
                    ]}],
                    "transition": [
                        {"event": "tick", "target": "idle"},
                    ],
                },
            ],
            "initial": "idle",
        }

    def _files(self):
        return transliterate_hdl_sv.render_target(
            self._chart_with_onexit_capture(), {"chart_name": "ex"}
        )

    def test_exit_edge_gating_emitted(self):
        """Exit-edge gating uses ``state_q == ST_OBSERVED && state_next !=
        ST_OBSERVED``, the mirror of the entry shape."""
        sv = self._files()["ex_fsm.sv"]
        assert (
            "state_q == ST_OBSERVED && state_next != ST_OBSERVED && "
            "event_tick_recv_valid"
        ) in sv

    def test_exit_capture_assigns_recv_data(self):
        sv = self._files()["ex_fsm.sv"]
        assert "data_last_seen_q <= event_tick_recv_data" in sv

    def test_exit_capture_default_holds_value(self):
        """Outside the exit-edge the datamodel register holds previous
        value (the else branch)."""
        sv = self._files()["ex_fsm.sv"]
        assert "data_last_seen_q <= data_last_seen_q" in sv

    def test_entry_gating_not_emitted_for_exit_capture(self):
        """An `<onexit>` capture MUST NOT also produce the entry-edge
        gating expression — the edge tag selects exactly one shape."""
        sv = self._files()["ex_fsm.sv"]
        # The entry-edge condition for `observed` would be
        # `state_q != ST_OBSERVED && state_next == ST_OBSERVED`; verify
        # it does NOT appear for the `data_last_seen_q` write.
        assert (
            "state_q != ST_OBSERVED && state_next == ST_OBSERVED && "
            "event_tick_recv_valid"
        ) not in sv

    def test_onexit_and_onentry_can_coexist_in_chain(self):
        """A chart that captures the same datamodel on entry AND exit
        from different states produces an if/elsif chain with both
        gating shapes."""
        chart = {
            "datamodel": [{"data": [
                {"id": "buf", "expr": "0", "type": "i32"},
            ]}],
            "state": [
                {"id": "s0", "transition": [
                    {"event": "a", "target": "s1"},
                ]},
                {
                    "id": "s1",
                    "onentry": [{"assign": [
                        {"location": "buf", "expr": "event.a.value"},
                    ]}],
                    "onexit": [{"assign": [
                        {"location": "buf", "expr": "event.a.value"},
                    ]}],
                    "transition": [
                        {"event": "a", "target": "s0"},
                    ],
                },
            ],
            "initial": "s0",
        }
        sv = transliterate_hdl_sv.render_target(
            chart, {"chart_name": "mix"}
        )["mix_fsm.sv"]
        # Entry-edge for s1.
        assert "state_q != ST_S1 && state_next == ST_S1" in sv
        # Exit-edge for s1.
        assert "state_q == ST_S1 && state_next != ST_S1" in sv
        # Two captures in the same chain → if + end-else-if structure.
        assert "end else if" in sv


class TestWave3fFutureBMultiParamRejection:
    """Wave-3-f-future-B (multi-`<param>` events) remains carry-forward.
    The walker MUST recognise the syntactic form `event.<EV>.<custom>`
    when `<custom> != "value"` and reject with a chart-vocabulary error
    citing the wave-3-f-future-B boundary — silent fall-through to
    wave-1/2 no-op would obscure the chart-author's intent."""

    def _chart_with_custom_param(self, suffix: str = "payload"):
        return {
            "datamodel": [{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
            ]}],
            "state": [
                {"id": "idle", "transition": [
                    {"event": "tick", "target": "observed"},
                ]},
                {
                    "id": "observed",
                    "onentry": [{"assign": [
                        {"location": "x", "expr": f"event.tick.{suffix}"},
                    ]}],
                    "transition": [{"target": "idle"}],
                },
            ],
            "initial": "idle",
        }

    def test_custom_suffix_raises(self):
        with pytest.raises(
            transliterate_hdl_sv.UnsupportedChartError,
            match=r"wave-3-f-future-B",
        ):
            transliterate_hdl_sv.render_target(
                self._chart_with_custom_param("payload"),
                {"chart_name": "x"},
            )

    def test_custom_suffix_error_names_offending_suffix(self):
        with pytest.raises(
            transliterate_hdl_sv.UnsupportedChartError,
            match=r"event\.tick\.payload",
        ):
            transliterate_hdl_sv.render_target(
                self._chart_with_custom_param("payload"),
                {"chart_name": "x"},
            )

    def test_custom_suffix_error_suggests_rename(self):
        """Error message includes guidance on the workaround (rename
        the `<param>` to `value` for the wave-3-e single-bus path)."""
        try:
            transliterate_hdl_sv.render_target(
                self._chart_with_custom_param("payload"),
                {"chart_name": "x"},
            )
        except transliterate_hdl_sv.UnsupportedChartError as exc:
            assert "rename" in str(exc).lower() or "value" in str(exc)
        else:
            pytest.fail("expected UnsupportedChartError")

    def test_value_suffix_still_accepted(self):
        """Backwards-compat: `event.<EV>.value` (wave-3-f baseline)
        keeps working unchanged — the regex extension MUST NOT regress
        the canonical single-`<param>` shape."""
        chart = self._chart_with_custom_param("value")
        # The exit-without-event-trigger transition in `observed` is
        # untriggered (target back to idle). Add a tick trigger so the
        # consume-event validation passes.
        chart["state"][1]["transition"] = [
            {"event": "tick", "target": "idle"},
        ]
        files = transliterate_hdl_sv.render_target(
            chart, {"chart_name": "v"}
        )
        sv = files["v_fsm.sv"]
        # Standard wave-3-f emit shape present.
        assert (
            "state_q != ST_OBSERVED && state_next == ST_OBSERVED && "
            "event_tick_recv_valid"
        ) in sv


# ---------------------------------------------------------------------------
# SOS-08-C wave-3-f-future-assign (2026-05-24 §15) — general
# ECMAScript-subset `<assign>` lowering: integer literals, datamodel
# idents, binary +/-.  These exercise the recursive-descent parser
# wired up in `_assign_expr.py` + `_collect_region_general_assigns` +
# the per-signal if/else chain extension in `_emit_register_process`.
# ---------------------------------------------------------------------------


class TestWave3fFutureAssignLowering:
    """Lowering for `<assign expr="<numeric-literal>"/>`,
    `<assign expr="<ident>"/>`, `<assign expr="<lhs> + <rhs>"/>`,
    `<assign expr="<lhs> - <rhs>"/>`, and the existing
    `event.<EV>.value` form (regression-guarded)."""

    @staticmethod
    def _chart_with_assign(expr_text, *, edge="onentry", datamodel=None):
        """Build a minimal chart that lowers a single ``<assign>``
        carried by `<onentry>` (default) or `<onexit>` on a state
        named ``hit``.  Datamodel can be overridden to add extra
        signals; the default has a single i32 `x` with reset 0."""
        if datamodel is None:
            datamodel = [{"data": [{"id": "x", "expr": "0", "type": "i32"}]}]
        hit_state = {
            "id": "hit",
            "transition": [{"target": "rest"}],
        }
        hit_state[edge] = [{"assign": [
            {"location": "x", "expr": expr_text},
        ]}]
        return {
            "datamodel": datamodel,
            "state": [
                {"id": "start", "transition": [{"target": "hit"}]},
                hit_state,
                {"id": "rest"},
            ],
            "initial": "start",
        }

    def _render(self, chart):
        return transliterate_hdl_sv.render_target(
            chart, {"chart_name": "a"}
        )["a_fsm.sv"]

    # --- Supported forms -------------------------------------------------

    def test_numeric_literal_assign_emits_constant_write(self):
        sv = self._render(self._chart_with_assign("42"))
        # Entry-edge gating into ST_HIT, RHS is the bare literal.
        assert "state_q != ST_HIT && state_next == ST_HIT" in sv
        assert "data_x_q <= 42;" in sv

    def test_hex_literal_assign_emits_constant_write(self):
        sv = self._render(self._chart_with_assign("0x2A"))
        # Hex literal lowered to its decimal value (42).
        assert "data_x_q <= 42;" in sv
        assert "state_q != ST_HIT && state_next == ST_HIT" in sv

    def test_unary_minus_literal_emits_signed_negative(self):
        sv = self._render(self._chart_with_assign("-7"))
        # Unary minus on a literal lowers to a bare negative integer
        # (SV signed-literal context — the register is `signed [31:0]`).
        assert "data_x_q <= -7;" in sv

    def test_datamodel_ident_assign_emits_register_copy(self):
        chart = self._chart_with_assign(
            "src",
            datamodel=[{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
                {"id": "src", "expr": "5", "type": "i32"},
            ]}],
        )
        sv = self._render(chart)
        assert "data_x_q <= data_src_q;" in sv

    def test_binary_plus_literal_and_ident_emits_add(self):
        chart = self._chart_with_assign(
            "x + 1",
            datamodel=[{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
            ]}],
        )
        sv = self._render(chart)
        assert "data_x_q <= data_x_q + 1;" in sv

    def test_binary_minus_two_idents_emits_sub(self):
        chart = self._chart_with_assign(
            "a - b",
            datamodel=[{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
                {"id": "a", "expr": "0", "type": "i32"},
                {"id": "b", "expr": "0", "type": "i32"},
            ]}],
        )
        sv = self._render(chart)
        assert "data_x_q <= data_a_q - data_b_q;" in sv

    # --- Edge gating ------------------------------------------------------

    def test_onentry_assign_gates_on_entry_edge(self):
        sv = self._render(self._chart_with_assign("99", edge="onentry"))
        # Entry-edge gating: state_q != ST_S && state_next == ST_S.
        assert "state_q != ST_HIT && state_next == ST_HIT" in sv
        # Exit-edge gating MUST NOT also fire for the same write.
        assert "state_q == ST_HIT && state_next != ST_HIT" not in sv

    def test_onexit_assign_gates_on_exit_edge(self):
        sv = self._render(self._chart_with_assign("99", edge="onexit"))
        assert "state_q == ST_HIT && state_next != ST_HIT" in sv
        # Entry-edge gating MUST NOT be emitted for the same write.
        # (`state_q != ST_HIT && state_next == ST_HIT` would be the
        # entry shape.)
        # The combinational mux still uses `state_q != ST_HIT` etc.
        # in unrelated arms, so we check the FULL `data_x_q` write
        # context — assert the entry shape doesn't appear immediately
        # above the data_x_q assign.
        entry_with_assign = (
            "state_q != ST_HIT && state_next == ST_HIT) begin\n"
            "                data_x_q"
        )
        assert entry_with_assign not in sv

    # --- Regression guards (wave-3-f-future-A still works) ---------------

    def test_event_value_path_still_works_byte_identical(self):
        """The `event.<EV>.value` form (handled upstream by the regex
        pre-pass) must continue to emit its standard
        `_recv_data`-bearing gating shape — NOT the new
        `_render_sv` lowering path."""
        chart = {
            "datamodel": [{"data": [
                {"id": "y", "expr": "0", "type": "i32"},
            ]}],
            "state": [
                {"id": "idle", "transition": [
                    {"event": "tick", "target": "seen"},
                ]},
                {"id": "seen",
                 "onentry": [{"assign": [
                     {"location": "y", "expr": "event.tick.value"},
                 ]}],
                 "transition": [{"event": "tick", "target": "idle"}]},
            ],
            "initial": "idle",
        }
        sv = transliterate_hdl_sv.render_target(
            chart, {"chart_name": "ev"}
        )["ev_fsm.sv"]
        # Event-payload gating shape — the `_recv_valid` term.
        assert (
            "state_q != ST_SEEN && state_next == ST_SEEN && "
            "event_tick_recv_valid"
        ) in sv
        # Lowered to `event_<EV>_recv_data`, NOT the parser path.
        assert "data_y_q <= event_tick_recv_data;" in sv

    def test_event_dot_value_emit_unchanged_for_charts_without_new_form(self):
        """A chart that has NO `<assign>` writes (the most common
        wave-1/wave-2 shape) must still emit the byte-identical
        wave-1 register-process body."""
        chart = {
            "datamodel": [{"data": [{"id": "x", "expr": "0", "type": "i32"}]}],
            "state": [
                {"id": "a", "transition": [{"target": "b"}]},
                {"id": "b"},
            ],
            "initial": "a",
        }
        sv = transliterate_hdl_sv.render_target(
            chart, {"chart_name": "n"}
        )["n_fsm.sv"]
        # Hold-shape from wave-1: `data_x_q <= data_x_q;` with NO if/else.
        assert "data_x_q <= data_x_q" in sv
        # No spurious state-edge gating introduced.
        assert "state_q != ST_" not in sv

    # --- Chart-vocab rejections ------------------------------------------

    def test_unknown_datamodel_ident_raises_chart_vocab_error(self):
        chart = self._chart_with_assign("unknown_thing")
        with pytest.raises(
            transliterate_hdl_sv.UnsupportedChartError,
            match=r"wave-3-f-future-assign.*unknown.*'unknown_thing'",
        ):
            transliterate_hdl_sv.render_target(chart, {"chart_name": "a"})

    def test_unsupported_operator_star_raises(self):
        chart = self._chart_with_assign(
            "x * 2",
            datamodel=[{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
            ]}],
        )
        with pytest.raises(
            transliterate_hdl_sv.UnsupportedChartError,
            match=r"wave-3-f-future-assign.*unsupported operator '\*'",
        ):
            transliterate_hdl_sv.render_target(chart, {"chart_name": "a"})

    def test_function_call_raises(self):
        chart = self._chart_with_assign("f(x)")
        with pytest.raises(
            transliterate_hdl_sv.UnsupportedChartError,
            match=r"wave-3-f-future-assign.*function call 'f\(\.\.\.\)'",
        ):
            transliterate_hdl_sv.render_target(chart, {"chart_name": "a"})

    def test_conditional_expr_raises(self):
        chart = self._chart_with_assign(
            "x == 1 ? a : b",
            datamodel=[{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
                {"id": "a", "expr": "0", "type": "i32"},
                {"id": "b", "expr": "0", "type": "i32"},
            ]}],
        )
        with pytest.raises(
            transliterate_hdl_sv.UnsupportedChartError,
            match=r"wave-3-f-future-assign",
        ):
            transliterate_hdl_sv.render_target(chart, {"chart_name": "a"})

    def test_string_literal_raises(self):
        chart = self._chart_with_assign('"hello"')
        with pytest.raises(
            transliterate_hdl_sv.UnsupportedChartError,
            match=r"wave-3-f-future-assign.*string literal",
        ):
            transliterate_hdl_sv.render_target(chart, {"chart_name": "a"})

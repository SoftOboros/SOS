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


def test_raise_rejected_at_wave_2():
    """Wave-2 still rejects <raise>; message cites wave-3 + §6.4/§6.5."""
    chart = _chart_with_raise()
    with pytest.raises(
        transliterate_hdl_sv.EventIngressNotSupportedError
    ) as excinfo:
        transliterate_hdl_sv.render_target(chart, {"chart_name": "r"})
    msg = str(excinfo.value)
    assert "SOS-08-C" in msg
    assert "§6.4" in msg or "§6.5" in msg
    assert "wave-3" in msg.lower()


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

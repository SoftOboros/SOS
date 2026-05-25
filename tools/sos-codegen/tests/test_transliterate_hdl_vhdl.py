"""Unit tests for `render_target` (wave-1 + wave-2).

@spec  SOS-08-C-CONCEPTS.md §6 (emission algorithm), §15 (ratification)
@spec  PCDN-C-001 (clock-domain default inherit-from-parent)
@spec  PCDN-C-002 (verified-strip retain synchronizers — wave-2 wraps)
@spec  PCDN-C-003 (reset state = SCXML <initial>)
@spec  PCDN-C-004 (guard depth budget = 8 chained operators)
@spec  PCDN-C-005 (chart annotation wins for encoding — wave-1 default = one-hot)
@spec  PCDN-C-006 (document-order priority in transition mux)
@spec  INV-S-HDL-A-1 (sync active-high reset)
@spec  INV-S-HDL-C-1..5 (deterministic emission, observability, etc.)

The wave-1/wave-2 scaffold consumes the raw scjson dict shape — the same
shape `loader._collect_states` / `_collect_datamodel` walk.  The sibling
agent's main.py dispatcher parses SCXML to scjson via `scjson json` and
passes the result to `render_target`; these tests build the same dict
shape inline so the test suite has no cross-agent fixture dependency.

Note: tests do NOT execute pytest themselves (per the orchestrator's
"static deliverable; do NOT run pytest" directive).  They define
assertions for the wave-1/2 acceptance gates that the integration-pass
agent runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the sos-codegen package is importable when pytest is invoked
# from the repo root.  Mirrors the bootstrap pattern in
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
    """A 3-state chart: idle → working → done.  No datamodel."""
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
        "datamodel": [{"data": [{"id": "counter", "expr": "0", "type": "int"}]}],
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
    first listed transition wins at wave-1 (unguarded path)."""
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
    """A chart whose transition carries a `cond` attribute — supported at v2."""
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


def _chart_with_multiple_guards():
    """State `dispatch` with three guarded transitions on one state.
    Per PCDN-C-006 they must compose into an if/elsif/elsif chain in
    document order."""
    return {
        "initial": "dispatch",
        "datamodel": [
            {"data": [
                {"id": "mode", "expr": "0", "type": "int"},
                {"id": "ready", "expr": "0", "type": "bool"},
            ]}
        ],
        "state": [
            _state(
                "dispatch",
                transitions=[
                    {"target": "fast", "cond": "mode == 1"},
                    {"target": "slow", "cond": "mode == 2"},
                    {"target": "idle", "cond": "ready != 0"},
                ],
            ),
            _state("fast"),
            _state("slow"),
            _state("idle"),
        ],
    }


def _chart_with_deep_guard():
    """A guard whose depth exceeds the 8-operator budget per
    PCDN-C-004 — should raise UnsupportedChartError."""
    # 9 chained operators (8 `&&` + a relational): exceeds budget=8.
    deep = "a == 1 && b == 2 && c == 3 && d == 4 && e == 5 && f == 6 && g == 7 && h == 8 && i == 9"
    return {
        "initial": "deep",
        "state": [
            _state(
                "deep",
                transitions=[{"target": "ok", "cond": deep}],
            ),
            _state("ok"),
        ],
    }


def _chart_with_parallel():
    """A chart with a top-level <parallel> carrying two orthogonal
    regions.  Supported at v2: emits one module per region plus a
    chart-top wrapper."""
    return {
        "initial": "p",
        "parallel": [
            {
                "id": "p",
                "state": [
                    {
                        "id": "left",
                        "initial": "l_idle",
                        "state": [
                            _state(
                                "l_idle",
                                transitions=[{"target": "l_active"}],
                            ),
                            _state("l_active"),
                        ],
                    },
                    {
                        "id": "right",
                        "initial": "r_idle",
                        "state": [
                            _state(
                                "r_idle",
                                transitions=[{"target": "r_active"}],
                            ),
                            _state("r_active"),
                        ],
                    },
                ],
            }
        ],
    }


def _chart_with_cross_domain():
    """A chart with two parallel regions in different clock domains;
    region A writes shared datamodel `flag`, region B reads it via a
    guard.  Should produce a cross-domain synchronizer in the wrapper."""
    return {
        "initial": "p",
        "datamodel": [
            {"data": [{"id": "flag", "expr": "0", "type": "int"}]}
        ],
        "parallel": [
            {
                "id": "p",
                "state": [
                    {
                        "id": "writer",
                        "clock": "fast",
                        "initial": "w_idle",
                        "state": [
                            _state(
                                "w_idle",
                                onentry=[{"assign": [{"location": "flag", "expr": "1"}]}],
                                transitions=[{"target": "w_done"}],
                            ),
                            _state("w_done"),
                        ],
                    },
                    {
                        "id": "reader",
                        "clock": "slow",
                        "initial": "r_idle",
                        "state": [
                            _state(
                                "r_idle",
                                transitions=[
                                    {"target": "r_seen", "cond": "flag != 0"},
                                ],
                            ),
                            _state("r_seen"),
                        ],
                    },
                ],
            }
        ],
    }


def _chart_with_wide_datamodel():
    """A chart whose datamodel signal is multi-bit (int = 32-bit).
    Port should emit as std_logic_vector(31 downto 0)."""
    return {
        "initial": "counting",
        "datamodel": [{"data": [{"id": "counter", "expr": "0", "type": "int"}]}],
        "state": [_state("counting")],
    }


def _chart_with_script():
    """A chart whose <onentry> carries a <script> body — rejected at v2,
    lands in v3."""
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
# Wave-1 acceptance tests (carried forward unchanged).
# ---------------------------------------------------------------------------


def test_single_region_simple_emits_clean():
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
    assert "rst = '1'" in body
    assert state_constant_name("idle") in body
    assert state_constant_name("working") in body
    assert state_constant_name("done") in body
    assert "current_state" in body
    assert "signal state_q" in body
    assert "signal state_next" in body


def test_datamodel_signals_emitted():
    chart = _chart_with_datamodel()
    files = render_target(chart, {"chart_name": "dm"})
    body = files["dm_fsm.vhd"]
    assert "signal counter_q" in body
    assert "to_signed(0, counter_q'length)" in body
    assert "data_counter" in body


def test_one_hot_encoding_default():
    chart = _four_state_chart()
    files = render_target(chart, {"chart_name": "four"})
    body = files["four_fsm.vhd"]
    assert '"0001"' in body
    assert '"0010"' in body
    assert '"0100"' in body
    assert '"1000"' in body
    assert one_hot_value(0, 4) == '"0001"'
    assert one_hot_value(3, 4) == '"1000"'


def test_initial_state_is_reset_state():
    chart = _simple_chart()
    files = render_target(chart, {"chart_name": "init"})
    body = files["init_fsm.vhd"]
    initial_const = state_constant_name("idle")
    assert f"state_q <= {initial_const}" in body


def test_document_order_priority_in_transition_mux():
    """PCDN-C-006 doc-order priority semantics under wave-3-d-3.

    Pre-wave-3-d-3, transitions with `event="..."` no `cond` were
    treated as unguarded, so the doc-order-first transition was the
    sole emission and the rest were elided as dead. Wave-3-d-3
    correctly treats `event="..."` as a predicate term — all three
    transitions emit into an if/elsif chain, and the first matching
    event-valid wins. Doc-order priority is preserved by the elsif
    structure (event_first arrives → winner; only when event_first is
    NOT valid does event_second get a chance → loser_a; etc.).
    """
    chart = _multi_transition_chart()
    files = render_target(chart, {"chart_name": "prio"})
    body = files["prio_fsm.vhd"]
    winner = state_constant_name("winner")
    loser_a = state_constant_name("loser_a")
    loser_b = state_constant_name("loser_b")
    # All three targets reachable under their own event-valid.
    assert f"state_next <= {winner}" in body
    assert f"state_next <= {loser_a}" in body
    assert f"state_next <= {loser_b}" in body
    # Priority order in the chain: winner first, then loser_a, then
    # loser_b. The line indices establish doc-order priority — first
    # match wins.
    lines = body.splitlines()
    winner_line = next(
        i for i, l in enumerate(lines) if f"state_next <= {winner}" in l
    )
    loser_a_line = next(
        i for i, l in enumerate(lines) if f"state_next <= {loser_a}" in l
    )
    loser_b_line = next(
        i for i, l in enumerate(lines) if f"state_next <= {loser_b}" in l
    )
    assert winner_line < loser_a_line < loser_b_line, (
        f"doc-order priority broken: winner@{winner_line} "
        f"loser_a@{loser_a_line} loser_b@{loser_b_line}"
    )


def test_script_bodies_rejected_at_v2_scaffold():
    """Wave-2 is still assign-only — <script> bodies (ECMAScript) raise
    UnsupportedChartError, with wave-3 as the landing wave."""
    chart = _chart_with_script()
    with pytest.raises(UnsupportedChartError) as exc_info:
        render_target(chart, {"chart_name": "sc"})
    msg = str(exc_info.value)
    assert "SOS-08-C wave-2 emitter does not lower ECMAScript" in msg
    assert "wave-3" in msg


def test_render_target_rejects_non_dict_chart_ir():
    with pytest.raises(UnsupportedChartError) as exc_info:
        render_target("not a dict", {"chart_name": "x"})
    msg = str(exc_info.value)
    assert "expects the raw scjson dict" in msg


def test_entity_name_normalises_chart_name():
    assert entity_name("simple") == "simple_fsm"
    assert entity_name("Mixed-Case Chart") == "mixed_case_chart_fsm"
    assert entity_name("1starts_numeric").startswith("x")


def test_default_initial_falls_back_to_first_state():
    chart = {
        "state": [
            _state("alpha"),
            _state("beta"),
        ],
    }
    files = render_target(chart, {"chart_name": "noinit"})
    body = files["noinit_fsm.vhd"]
    alpha = state_constant_name("alpha")
    assert f"state_q <= {alpha}" in body


def test_emits_header_comment_with_spec_citations():
    files = render_target(_simple_chart(), {"chart_name": "hdr"})
    body = files["hdr_fsm.vhd"]
    assert "SOS-08-C-CONCEPTS.md" in body
    assert "INV-S-HDL" in body
    assert "PCDN" in body or "C-001" in body or "C-006" in body


def test_empty_chart_raises_clear_error():
    chart = {"state": []}
    with pytest.raises(UnsupportedChartError) as exc_info:
        render_target(chart, {"chart_name": "empty"})
    msg = str(exc_info.value)
    assert "at least one <state>" in msg


# ---------------------------------------------------------------------------
# Wave-2 acceptance tests.
# ---------------------------------------------------------------------------


def test_guards_rejected_at_v1_scaffold():
    """RETRACTED at wave-2: guards are now SUPPORTED.  The test name is
    kept for backward identification but the assertion flips: the
    render now succeeds and emits an if/then case-arm body."""
    chart = _chart_with_guarded_transition()
    files = render_target(chart, {"chart_name": "g"})
    assert "g_fsm.vhd" in files
    body = files["g_fsm.vhd"]
    # The guard-aware arm body is an if/then assignment, not a plain
    # state_next assignment.
    assert "if " in body
    assert "then" in body
    assert state_constant_name("next") in body


def test_parallel_regions_rejected_at_v1_scaffold():
    """RETRACTED at wave-2: <parallel> is now SUPPORTED — each region
    becomes its own module + a chart-top wrapper instantiates them."""
    chart = _chart_with_parallel()
    files = render_target(chart, {"chart_name": "par"})
    # Expect one file per region + the wrapper.
    assert "par_top.vhd" in files
    assert "par_region_left_fsm.vhd" in files
    assert "par_region_right_fsm.vhd" in files


def test_guarded_transition_emits_if_block():
    """Wave-2 new acceptance: a chart with one guarded transition
    compiles to a VHDL if/then case-arm body (PCDN-C-006 chain head)."""
    chart = _chart_with_guarded_transition()
    files = render_target(chart, {"chart_name": "guarded"})
    body = files["guarded_fsm.vhd"]
    # Arm body contains an `if <expr> then state_next <= ST_NEXT;` form.
    assert "if " in body
    # The compiled guard should reference the registered `_q` form of
    # the datamodel signal (heuristic — wave-2 fallback path); the
    # canonical hdl_common.emit_guard_expr may render differently.
    next_const = state_constant_name("next")
    # The target state must be the next-state assignment inside the
    # if-block — search for the literal assignment line.
    assert any(
        f"state_next <= {next_const}" in line for line in body.splitlines()
    )


def test_multiple_guards_become_elsif_chain():
    """Wave-2: 3 guarded transitions on one state compose into an
    if/elsif/elsif chain in document order per PCDN-C-006.  No
    unguarded fallback ⇒ the chain closes with `else state_next <=
    state_q;`."""
    chart = _chart_with_multiple_guards()
    files = render_target(chart, {"chart_name": "multi"})
    body = files["multi_fsm.vhd"]
    # Look at lines inside the dispatch case-arm.  At minimum: one `if`
    # and at least one `elsif`.
    text = body
    assert "if " in text
    assert "elsif " in text
    # All three guard targets present.
    for tgt in ("fast", "slow", "idle"):
        assert state_constant_name(tgt) in text
    # End-of-chain closing `else` falling back to state_q.
    assert "else" in text


def test_guard_depth_over_budget_fails():
    """Wave-2: a guard expression whose depth exceeds the configured
    budget surfaces as `UnsupportedChartError` citing PCDN-C-004 and
    the offending state."""
    chart = _chart_with_deep_guard()
    with pytest.raises(UnsupportedChartError) as exc_info:
        render_target(
            chart,
            {"chart_name": "deep", "guard_depth_budget": 8},
        )
    msg = str(exc_info.value)
    assert "PCDN-C-004" in msg
    assert "depth" in msg
    assert "budget" in msg
    # The source state is named.
    assert "deep" in msg


def test_parallel_regions_emit_separate_modules():
    """Wave-2: a chart with <parallel> containing 2 regions emits 3
    output files — one per region + the chart-top wrapper."""
    chart = _chart_with_parallel()
    files = render_target(chart, {"chart_name": "par"})
    assert len(files) == 3
    assert "par_top.vhd" in files
    assert "par_region_left_fsm.vhd" in files
    assert "par_region_right_fsm.vhd" in files
    # Each region module is a complete VHDL file.
    for region_name in ("left", "right"):
        body = files[f"par_region_{region_name}_fsm.vhd"]
        assert "library ieee;" in body
        assert f"entity par_region_{region_name}_fsm is" in body
        assert "architecture rtl of" in body


def test_chart_top_wrapper_instantiates_regions():
    """Wave-2: the chart-top wrapper carries `u_region_<name> : entity
    work.<chart>_region_<name>` instantiation lines for each region."""
    chart = _chart_with_parallel()
    files = render_target(chart, {"chart_name": "par"})
    wrapper = files["par_top.vhd"]
    # The wrapper is a VHDL entity + architecture.
    assert "entity par_top is" in wrapper
    assert "architecture rtl of par_top" in wrapper
    # Each region is instantiated via `entity work.<chart>_region_<name>_fsm`
    # (PCDN-SOS-08-C-wave2-region-naming, 2026-05-23 walkthrough Q1).
    assert "entity work.par_region_left_fsm" in wrapper
    assert "entity work.par_region_right_fsm" in wrapper


def test_cross_domain_signal_gets_synchronizer():
    """Wave-2 + PCDN-C-002: a chart whose two regions live in distinct
    clock domains and share a datamodel signal triggers emission of a
    `sos_synchronizer` instantiation in the chart-top wrapper.
    Synchronizers are retained regardless of verified-strip."""
    chart = _chart_with_cross_domain()
    files = render_target(chart, {"chart_name": "cdc"})
    assert "cdc_top.vhd" in files
    wrapper = files["cdc_top.vhd"]
    # Two distinct clock-domain ports.
    assert "clk_fast" in wrapper
    assert "clk_slow" in wrapper
    assert "rst_fast" in wrapper
    assert "rst_slow" in wrapper
    # sos_synchronizer instantiation (canonical helper OR inline fallback).
    assert "sos_synchronizer" in wrapper
    # PCDN-C-002 comment cite present.
    assert "PCDN-C-002" in wrapper


def test_port_width_follows_signal_width():
    """Wave-2: a datamodel `<data id="counter" type="int">` emits its
    port as `std_logic_vector(31 downto 0)` (32-bit per SOS-08-C §5.4
    default)."""
    chart = _chart_with_wide_datamodel()
    files = render_target(chart, {"chart_name": "wide"})
    body = files["wide_fsm.vhd"]
    # The data_counter port's width annotation reflects the 32-bit
    # underlying signal.
    assert "data_counter" in body
    assert "std_logic_vector(31 downto 0)" in body


def test_wave2_rejection_messages_cite_wave3():
    """Wave-2 rejections for still-unsupported features cite wave-3 as
    the landing wave (not wave-2 like the wave-1 prompt did)."""
    chart = _chart_with_script()
    with pytest.raises(UnsupportedChartError) as exc_info:
        render_target(chart, {"chart_name": "sc"})
    msg = str(exc_info.value)
    assert "wave-3" in msg


# ---------------------------------------------------------------------------
# SOS-08-C wave-3 events: event egress emission (§6.5) — VHDL side.
# ---------------------------------------------------------------------------


def _chart_with_raise_vhdl():
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


class TestVhdlWave3Events:
    """SOS-08-C wave-3 events: VHDL emit accepts <raise> + emits per-event
    `event_<name>_send_valid : out std_logic` egress ports + concurrent
    `when … else '0'` drives."""

    def test_raise_accepted_at_wave_3(self):
        files = render_target(
            _chart_with_raise_vhdl(), {"chart_name": "r"}
        )
        # Single-region chart → one .vhd file.
        assert len(files) == 1
        src = list(files.values())[0]
        assert "event_go_send_valid" in src

    def test_egress_port_declared_as_std_logic_out(self):
        files = render_target(
            _chart_with_raise_vhdl(), {"chart_name": "r"}
        )
        src = list(files.values())[0]
        # Port declaration form: `event_go_send_valid : out std_logic`.
        assert "event_go_send_valid : out std_logic" in src

    def test_egress_drive_is_concurrent_when_else(self):
        files = render_target(
            _chart_with_raise_vhdl(), {"chart_name": "r"}
        )
        src = list(files.values())[0]
        # Drive uses VHDL conditional concurrent signal assignment.
        assert "event_go_send_valid <= '1' when" in src
        assert "else '0';" in src

    def test_event_name_sanitisation(self):
        chart = {
            "initial": "A",
            "state": [
                _state("A", transitions=[
                    {"target": "B", "raise_value": [{"event": "sem.give"}]},
                ]),
                _state("B"),
            ],
        }
        files = render_target(
            chart, {"chart_name": "k"}
        )
        src = list(files.values())[0]
        # `sem.give` → `sem_give` for the VHDL identifier; the original
        # name is preserved in the trailing comment.
        assert "event_sem_give_send_valid" in src
        assert "`sem.give`" in src

    def test_chart_without_raise_unchanged(self):
        """Regression guard: charts without <raise> emit the same shape
        as wave-2."""
        chart = {
            "initial": "A",
            "state": [
                _state("A", transitions=[{"target": "B"}]),
                _state("B"),
            ],
        }
        files = render_target(
            chart, {"chart_name": "p"}
        )
        src = list(files.values())[0]
        assert "event_" not in src
        assert "send_valid" not in src


# ---------------------------------------------------------------------------
# SOS-08-C wave-3-f (2026-05-24 §15) — datamodel binding on consume
# side. VHDL mirror of the SV walker's wave-3-f.
# ---------------------------------------------------------------------------


class TestWave3fEventPayloadCaptureVhdl:
    """Wave-3-f VHDL mirror: `<onentry><assign location="X"
    expr="event.<EV>.value"/></onentry>` lowers to an if/elsif chain
    in the register process. Tests verify the VHDL emit shape +
    cross-walker parity with the SV walker."""

    def _chart_with_capture(self):
        return {
            "datamodel": [{"data": [
                {"id": "last_value", "expr": "0", "type": "i32"},
            ]}],
            "state": [
                {"id": "idle",
                 "transition": [{"event": "tick", "target": "observed"}]},
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

    def _vhd(self) -> str:
        files = render_target(
            self._chart_with_capture(), {"chart_name": "cap"}
        )
        return files["cap_fsm.vhd"]

    def test_register_process_emits_capture_branch_vhdl(self):
        vhd = self._vhd()
        # VHDL syntax: `state_q /= X and state_next = X and event_<EV>_recv_valid = '1'`.
        assert (
            "state_q /= ST_OBSERVED and "
            "state_next = ST_OBSERVED and "
            "event_tick_recv_valid = '1'"
        ) in vhd

    def test_capture_branch_assigns_recv_data_via_signed_cast(self):
        """VHDL emit converts `std_logic_vector` _recv_data to `signed`
        before assigning to the datamodel register (which is declared
        as `signed`)."""
        vhd = self._vhd()
        assert "last_value_q <= signed(event_tick_recv_data)" in vhd

    def test_capture_default_holds_value(self):
        vhd = self._vhd()
        assert "last_value_q <= last_value_q" in vhd

    def test_capture_target_is_consume_event_check(self):
        """SOS-08-C wave-3-f-future-xreg (2026-05-24 §15): rebadged
        from "NOT a consume event" to "not raised anywhere in the
        chart" — the cross-region rule replaces the per-region
        consume-event check with a chart-wide raiser check."""
        chart = self._chart_with_capture()
        chart["state"][1]["onentry"][0]["assign"][0]["expr"] = (
            "event.nonsense.value"
        )
        with pytest.raises(
            UnsupportedChartError,
            match="not raised anywhere in the chart",
        ):
            render_target(chart, {"chart_name": "cap"})

    def test_multiple_captures_form_elsif_chain(self):
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
        vhd = render_target(chart, {"chart_name": "m"})["m_fsm.vhd"]
        assert "event_a_recv_valid = '1'" in vhd
        assert "event_b_recv_valid = '1'" in vhd
        assert "buf_q <= signed(event_a_recv_data)" in vhd
        assert "buf_q <= signed(event_b_recv_data)" in vhd
        assert "elsif" in vhd

    def test_no_captures_preserves_wave1_shape(self):
        """Charts without event-payload captures emit the wave-1
        register-process shape (no if/elsif chain in the update branch)."""
        chart = {
            "datamodel": [{"data": [{"id": "x", "expr": "0", "type": "i32"}]}],
            "state": [
                {"id": "a", "transition": [{"target": "b"}]},
                {"id": "b"},
            ],
            "initial": "a",
        }
        vhd = render_target(chart, {"chart_name": "p"})["p_fsm.vhd"]
        # No event-recv reference; no entry-edge if/elsif.
        assert "event_" not in vhd
        # x_q reset present.
        assert "x_q <= to_signed(0, x_q'length);" in vhd


# ---------------------------------------------------------------------------
# Wave-3-f-future-A (2026-05-24 §15) — VHDL `<onexit>` capture mirror.
# ---------------------------------------------------------------------------


class TestWave3fFutureOnexitCaptureVhdl:
    """VHDL mirror of `TestWave3fFutureOnexitCapture` (SV side)."""

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

    def _vhd(self):
        files = render_target(
            self._chart_with_onexit_capture(), {"chart_name": "ex"}
        )
        return files["ex_fsm.vhd"]

    def test_exit_edge_gating_emitted_vhdl(self):
        vhd = self._vhd()
        # VHDL syntax: `state_q = X and state_next /= X and recv_valid='1'`.
        assert (
            "state_q = ST_OBSERVED and "
            "state_next /= ST_OBSERVED and "
            "event_tick_recv_valid = '1'"
        ) in vhd

    def test_exit_capture_assigns_recv_data_with_signed_cast(self):
        vhd = self._vhd()
        assert "last_seen_q <= signed(event_tick_recv_data)" in vhd

    def test_exit_capture_holds_value_in_else(self):
        vhd = self._vhd()
        assert "last_seen_q <= last_seen_q" in vhd

    def test_entry_shape_not_emitted_for_exit_capture(self):
        vhd = self._vhd()
        assert (
            "state_q /= ST_OBSERVED and "
            "state_next = ST_OBSERVED and "
            "event_tick_recv_valid = '1'"
        ) not in vhd


class TestWave3fFutureBMultiParamRejectionVhdl_legacy_now_routed:
    """VHDL mirror: PCDN-SOS-08-C-007 (2026-05-25 §15) resolves
    wave-3-f-future-B's blanket "reject any non-`value` suffix".  The
    walker now routes ``event.<EV>.<param>`` to per-param sub-buses
    ``event_<EV>_recv_data_<param>`` when ``<param>`` is declared on
    the corresponding ``<raise>``/``<send>``; undeclared suffixes
    still reject with an actionable chart-vocab error."""

    def _chart_with_undeclared_custom_param(self, suffix: str = "payload"):
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

    def _chart_with_custom_param_and_declaration(
        self, suffix: str = "payload"
    ):
        return {
            "datamodel": [{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
                {"id": "src", "expr": "0", "type": "i32"},
            ]}],
            "state": [
                {"id": "idle", "transition": [
                    {"target": "send", "raise_value": [
                        {"event": "tick", "param": [
                            {"name": suffix, "expr": "src"},
                        ]},
                    ]},
                ]},
                {"id": "send", "transition": [
                    {"event": "tick", "target": "observed"},
                ]},
                {
                    "id": "observed",
                    "onentry": [{"assign": [
                        {"location": "x", "expr": f"event.tick.{suffix}"},
                    ]}],
                    "transition": [
                        {"event": "tick", "target": "idle"},
                    ],
                },
            ],
            "initial": "idle",
        }

    def test_undeclared_custom_suffix_still_rejects_vhdl(self):
        with pytest.raises(
            UnsupportedChartError,
            match=r"PCDN-SOS-08-C-007",
        ):
            render_target(
                self._chart_with_undeclared_custom_param("payload"),
                {"chart_name": "x"},
            )

    def test_undeclared_custom_suffix_error_names_offending_suffix_vhdl(self):
        with pytest.raises(
            UnsupportedChartError,
            match=r"event\.tick\.payload",
        ):
            render_target(
                self._chart_with_undeclared_custom_param("payload"),
                {"chart_name": "x"},
            )

    def test_declared_custom_suffix_routes_to_per_param_sub_bus_vhdl(self):
        files = render_target(
            self._chart_with_custom_param_and_declaration("payload"),
            {"chart_name": "rt"},
        )
        vhd = files["rt_fsm.vhd"]
        assert "event_tick_recv_data_payload" in vhd
        assert "x_q <= signed(event_tick_recv_data_payload)" in vhd

    def test_value_suffix_still_accepted_vhdl(self):
        chart = self._chart_with_undeclared_custom_param("value")
        chart["state"][1]["transition"] = [
            {"event": "tick", "target": "idle"},
        ]
        files = render_target(chart, {"chart_name": "v"})
        vhd = files["v_fsm.vhd"]
        assert (
            "state_q /= ST_OBSERVED and "
            "state_next = ST_OBSERVED and "
            "event_tick_recv_valid = '1'"
        ) in vhd
        # Legacy alias is the source (no per-param sub-bus port).
        assert "event_tick_recv_data_value" not in vhd


# ---------------------------------------------------------------------------
# SOS-08-C wave-3-f-future-assign (2026-05-24 §15) — general
# ECMAScript-subset `<assign>` lowering (VHDL mirror of the SV
# walker's `TestWave3fFutureAssignLowering`).
# ---------------------------------------------------------------------------


class TestWave3fFutureAssignLoweringVhdl:
    """Lowering for VHDL counterparts of the SV-side numeric-literal /
    datamodel-ident / binary +/- forms.  Integer literals are wrapped
    in ``to_signed(N, <width>)``; idents emit as ``<name>_q`` (VHDL
    walker drops the `data_` prefix from the register name)."""

    @staticmethod
    def _chart_with_assign(expr_text, *, edge="onentry", datamodel=None):
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
        return render_target(chart, {"chart_name": "a"})["a_fsm.vhd"]

    # --- Supported forms -------------------------------------------------

    def test_numeric_literal_assign_emits_constant_write(self):
        vhd = self._render(self._chart_with_assign("42"))
        # Entry-edge gating into ST_HIT.
        assert "state_q /= ST_HIT and state_next = ST_HIT" in vhd
        # Integer literal wrapped in to_signed(N, width).
        assert "x_q <= to_signed(42, 32);" in vhd

    def test_hex_literal_assign_emits_constant_write(self):
        vhd = self._render(self._chart_with_assign("0x2A"))
        # Hex literal lowered to its decimal value (42) inside to_signed.
        assert "x_q <= to_signed(42, 32);" in vhd

    def test_unary_minus_literal_emits_signed_negative(self):
        vhd = self._render(self._chart_with_assign("-7"))
        # Unary minus on a literal → negative integer inside to_signed.
        assert "x_q <= to_signed(-7, 32);" in vhd

    def test_datamodel_ident_assign_emits_register_copy(self):
        chart = self._chart_with_assign(
            "src",
            datamodel=[{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
                {"id": "src", "expr": "5", "type": "i32"},
            ]}],
        )
        vhd = self._render(chart)
        # VHDL ident copy: `<reg>_q <= <other>_q;` (no `data_` prefix).
        assert "x_q <= src_q;" in vhd

    def test_binary_plus_literal_and_ident_emits_add(self):
        chart = self._chart_with_assign(
            "x + 1",
            datamodel=[{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
            ]}],
        )
        vhd = self._render(chart)
        # Ident on left, to_signed-wrapped literal on right.
        assert "x_q <= x_q + to_signed(1, 32);" in vhd

    def test_binary_minus_two_idents_emits_sub(self):
        chart = self._chart_with_assign(
            "a - b",
            datamodel=[{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
                {"id": "a", "expr": "0", "type": "i32"},
                {"id": "b", "expr": "0", "type": "i32"},
            ]}],
        )
        vhd = self._render(chart)
        assert "x_q <= a_q - b_q;" in vhd

    # --- Edge gating ------------------------------------------------------

    def test_onentry_assign_gates_on_entry_edge(self):
        vhd = self._render(self._chart_with_assign("99", edge="onentry"))
        assert "state_q /= ST_HIT and state_next = ST_HIT" in vhd

    def test_onexit_assign_gates_on_exit_edge(self):
        vhd = self._render(self._chart_with_assign("99", edge="onexit"))
        assert "state_q = ST_HIT and state_next /= ST_HIT" in vhd
        # Entry shape MUST NOT appear in the immediate context of the
        # x_q write.
        entry_with_assign = (
            "state_q /= ST_HIT and state_next = ST_HIT then\n"
            "                    x_q"
        )
        assert entry_with_assign not in vhd

    # --- Regression guards -----------------------------------------------

    def test_event_value_path_still_works_byte_identical(self):
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
        vhd = render_target(chart, {"chart_name": "ev"})["ev_fsm.vhd"]
        # Wave-3-f event-payload gating shape preserved.
        assert (
            "state_q /= ST_SEEN and "
            "state_next = ST_SEEN and "
            "event_tick_recv_valid = '1'"
        ) in vhd
        # Lowered via the wave-3-f signed-cast path, NOT the parser.
        assert "y_q <= signed(event_tick_recv_data)" in vhd

    def test_event_dot_value_emit_unchanged_for_charts_without_new_form(self):
        chart = {
            "datamodel": [{"data": [{"id": "x", "expr": "0", "type": "i32"}]}],
            "state": [
                {"id": "a", "transition": [{"target": "b"}]},
                {"id": "b"},
            ],
            "initial": "a",
        }
        vhd = render_target(chart, {"chart_name": "n"})["n_fsm.vhd"]
        # No new state-edge gating; x_q only present in the wave-1
        # reset (to_signed(0, ...)).
        assert "x_q <= to_signed(0, x_q'length);" in vhd
        assert "state_q /= ST_" not in vhd

    # --- Chart-vocab rejections ------------------------------------------

    def test_unknown_datamodel_ident_raises_chart_vocab_error(self):
        chart = self._chart_with_assign("unknown_thing")
        with pytest.raises(
            UnsupportedChartError,
            match=r"wave-3-f-future-assign.*unknown.*'unknown_thing'",
        ):
            render_target(chart, {"chart_name": "a"})

    def test_unsupported_operator_star_raises(self):
        chart = self._chart_with_assign(
            "x * 2",
            datamodel=[{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
            ]}],
        )
        with pytest.raises(
            UnsupportedChartError,
            match=r"wave-3-f-future-assign.*unsupported operator '\*'",
        ):
            render_target(chart, {"chart_name": "a"})

    def test_function_call_raises(self):
        chart = self._chart_with_assign("f(x)")
        with pytest.raises(
            UnsupportedChartError,
            match=r"wave-3-f-future-assign.*function call 'f\(\.\.\.\)'",
        ):
            render_target(chart, {"chart_name": "a"})

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
            UnsupportedChartError,
            match=r"wave-3-f-future-assign",
        ):
            render_target(chart, {"chart_name": "a"})

    def test_string_literal_raises(self):
        chart = self._chart_with_assign('"hello"')
        with pytest.raises(
            UnsupportedChartError,
            match=r"wave-3-f-future-assign.*string literal",
        ):
            render_target(chart, {"chart_name": "a"})


# ---------------------------------------------------------------------------
# SOS-08-C wave-3-f-future-xreg (2026-05-24 §15) — VHDL mirror of the SV
# walker's cross-region event-value capture tests.  Test list MUST match
# the SV class one-for-one per the §15 wave-3-f-future-xreg conformance
# matrix (cross-walker parity).
# ---------------------------------------------------------------------------


class TestWave3fFutureCrossRegionEventCaptureVhdl:
    """VHDL mirror of the SV ``TestWave3fFutureCrossRegionEventCapture``
    class — every test asserts the VHDL emit shape (signed casts,
    VHDL ``or`` operator, ``report ... severity warning`` instead of
    SV ``$warning``)."""

    @staticmethod
    def _chart_cross_region(
        *,
        capture_edge: str = "onentry",
        capture_state: str = "R2",
        capture_location: str = "last",
        raised_event: str = "tick",
        capture_event: str | None = None,
    ):
        capture_event = capture_event or raised_event
        capture_state_obj: dict = {"id": capture_state}
        capture_state_obj[capture_edge] = [{"assign": [
            {"location": capture_location,
             "expr": f"event.{capture_event}.value"},
        ]}]
        if capture_state == "R1":
            r1 = capture_state_obj
            r1["transition"] = [{"target": "R2"}]
            r2 = {"id": "R2"}
        else:
            r1 = _state("R1", transitions=[{"target": "R2"}])
            r2 = capture_state_obj
            r2["transition"] = [{"target": "R1"}]
        return {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "left", "initial": "L1", "state": [
                        _state("L1", transitions=[
                            {"target": "L2", "raise_value": [
                                {"event": raised_event, "param": [
                                    {"name": "value", "expr": "1"},
                                ]},
                            ]},
                        ]),
                        _state("L2"),
                    ]},
                    {"id": "right", "initial": "R1",
                     "datamodel": [
                         {"data": [{"id": capture_location, "expr": "0",
                                    "type": "i32"}]},
                     ],
                     "state": [r1, r2]},
                ],
            }],
        }

    @staticmethod
    def _chart_intra_only():
        return {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "left", "initial": "L1",
                     "datamodel": [
                         {"data": [{"id": "lcap", "expr": "0",
                                    "type": "i32"}]},
                     ],
                     "state": [
                         _state("L1", transitions=[
                             {"target": "L2", "raise_value": [
                                 {"event": "lev", "param": [
                                     {"name": "value", "expr": "1"},
                                 ]},
                             ]},
                         ]),
                         {"id": "L2",
                          "onentry": [{"assign": [
                              {"location": "lcap",
                               "expr": "event.lev.value"},
                          ]}],
                          "transition": [
                              {"event": "lev", "target": "L1"},
                          ]},
                     ]},
                    {"id": "right", "initial": "R1",
                     "datamodel": [
                         {"data": [{"id": "rcap", "expr": "0",
                                    "type": "i32"}]},
                     ],
                     "state": [
                         _state("R1", transitions=[
                             {"target": "R2", "raise_value": [
                                 {"event": "rev", "param": [
                                     {"name": "value", "expr": "2"},
                                 ]},
                             ]},
                         ]),
                         {"id": "R2",
                          "onentry": [{"assign": [
                              {"location": "rcap",
                               "expr": "event.rev.value"},
                          ]}],
                          "transition": [
                              {"event": "rev", "target": "R1"},
                          ]},
                     ]},
                ],
            }],
        }

    @staticmethod
    def _chart_multi_raiser():
        """Three-region chart: ``a`` and ``b`` both raise ``shared``;
        ``c`` captures via a cross-region <onentry>."""
        return {
            "initial": "p",
            "parallel": [{"id": "p", "state": [
                {"id": "a", "initial": "A1", "state": [
                    _state("A1", transitions=[
                        {"target": "A2", "raise_value": [
                            {"event": "shared", "param": [
                                {"name": "value", "expr": "10"},
                            ]},
                        ]},
                    ]),
                    _state("A2"),
                ]},
                {"id": "b", "initial": "B1", "state": [
                    _state("B1", transitions=[
                        {"target": "B2", "raise_value": [
                            {"event": "shared", "param": [
                                {"name": "value", "expr": "20"},
                            ]},
                        ]},
                    ]),
                    _state("B2"),
                ]},
                {"id": "c", "initial": "C1",
                 "datamodel": [
                     {"data": [{"id": "buf", "expr": "0",
                                "type": "i32"}]},
                 ],
                 "state": [
                     _state("C1", transitions=[{"target": "C2"}]),
                     {"id": "C2",
                      "onentry": [{"assign": [
                          {"location": "buf",
                           "expr": "event.shared.value"},
                      ]}],
                      "transition": [{"target": "C1"}]},
                 ]},
            ]}],
        }

    # ----- Byte-identity regression guard -----

    def test_byte_identity_when_chart_has_only_intra_region_captures(self):
        files = render_target(
            self._chart_intra_only(), {"chart_name": "intra"}
        )
        top = files["intra_top.vhd"]
        assert "chart_event_" not in top
        assert "wave-3-f-future-xreg" not in top
        # Intra-region capture still emitted in consumer region.
        left_fsm = files["intra_region_left_fsm.vhd"]
        assert "lcap_q <= signed(event_lev_recv_data)" in left_fsm

    # ----- Cross-region capture wires from chart-top bus -----

    def test_cross_region_capture_wires_from_chart_top_bus(self):
        files = render_target(
            self._chart_cross_region(), {"chart_name": "x"}
        )
        right_fsm = files["x_region_right_fsm.vhd"]
        # Region B has the recv_valid/recv_data input ports.
        assert "event_tick_recv_valid : in std_logic" in right_fsm
        assert (
            "event_tick_recv_data : in std_logic_vector(7 downto 0)"
            in right_fsm
        )
        # Capture branch with signed-cast.
        assert (
            "state_q /= ST_R2 and state_next = ST_R2 and "
            "event_tick_recv_valid = '1'"
        ) in right_fsm
        assert "last_q <= signed(event_tick_recv_data)" in right_fsm
        # Chart-top broadcast bus signals declared.
        top = files["x_top.vhd"]
        assert "chart_event_tick_raise_valid" in top
        assert "chart_event_tick_raise_data" in top

    # ----- Bus signal naming -----

    def test_chart_top_bus_signal_naming(self):
        files = render_target(
            self._chart_cross_region(), {"chart_name": "n"}
        )
        top = files["n_top.vhd"]
        # VHDL signal declaration.
        assert (
            "signal chart_event_tick_raise_valid : std_logic;"
            in top
        )
        assert (
            "signal chart_event_tick_raise_data : "
            "std_logic_vector(7 downto 0);"
            in top
        )
        # Concurrent assignment aliasing.
        assert (
            "chart_event_tick_raise_valid <= ev_tick_send_valid"
            in top
        )
        assert (
            "chart_event_tick_raise_data <= ev_tick_send_data"
            in top
        )

    # ----- Multi-raiser OR aggregation -----

    def test_multi_raiser_or_aggregation(self):
        files = render_target(
            self._chart_multi_raiser(), {"chart_name": "agg"}
        )
        top = files["agg_top.vhd"]
        # Existing aggregated valid uses VHDL `or` operator.
        assert (
            "ev_shared_send_valid <= "
            "w_ev_a_shared_pulse or w_ev_b_shared_pulse"
            in top
        )
        assert (
            "chart_event_shared_raise_valid <= ev_shared_send_valid"
            in top
        )

    # ----- Multi-raiser priority mux (lower-doc-order wins) -----

    def test_multi_raiser_priority_mux_lower_region_wins(self):
        files = render_target(
            self._chart_multi_raiser(), {"chart_name": "pri"}
        )
        top = files["pri_top.vhd"]
        # `raisers: a, b` comment documents the priority order.
        assert "raisers: a, b" in top
        assert "priority to first" in top

    # ----- Same-cycle conflict report -----

    def test_same_cycle_conflict_emits_runtime_warning(self):
        files = render_target(
            self._chart_multi_raiser(), {"chart_name": "warn"}
        )
        top = files["warn_top.vhd"]
        # VHDL `report ... severity warning` instead of SV $warning.
        assert "severity warning" in top
        assert (
            "same-cycle multi-raiser conflict on chart event `shared`"
            in top
        )
        # Surrounded by synthesis pragma so synthesisers ignore it.
        assert "pragma synthesis_off" in top
        assert "pragma synthesis_on" in top

    # ----- Chart-vocab error: unraised event -----

    def test_unraised_event_capture_raises_chart_vocab_error(self):
        chart = {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "left", "initial": "L1", "state": [
                        _state("L1", transitions=[{"target": "L2"}]),
                        _state("L2"),
                    ]},
                    {"id": "right", "initial": "R1",
                     "datamodel": [
                         {"data": [{"id": "buf", "expr": "0",
                                    "type": "i32"}]},
                     ],
                     "state": [
                         _state("R1", transitions=[{"target": "R2"}]),
                         {"id": "R2",
                          "onentry": [{"assign": [
                              {"location": "buf",
                               "expr": "event.ghost.value"},
                          ]}],
                          "transition": [{"target": "R1"}]},
                     ]},
                ],
            }],
        }
        with pytest.raises(
            UnsupportedChartError,
            match=(
                r"SOS-08-C wave-3-f-future-xreg.*"
                r"'ghost'.*not raised anywhere in the chart"
            ),
        ):
            render_target(chart, {"chart_name": "u"})

    # ----- Entry edge -----

    def test_onentry_cross_region_capture_on_entry_edge_only(self):
        files = render_target(
            self._chart_cross_region(
                capture_edge="onentry", capture_state="R2",
                capture_location="last",
            ),
            {"chart_name": "enen"},
        )
        right_fsm = files["enen_region_right_fsm.vhd"]
        assert (
            "state_q /= ST_R2 and state_next = ST_R2 and "
            "event_tick_recv_valid = '1'"
        ) in right_fsm
        # No exit-edge form.
        assert (
            "state_q = ST_R2 and state_next /= ST_R2 and "
            "event_tick_recv_valid = '1'"
        ) not in right_fsm

    # ----- Exit edge -----

    def test_onexit_cross_region_capture_on_exit_edge_only(self):
        files = render_target(
            self._chart_cross_region(
                capture_edge="onexit", capture_state="R1",
                capture_location="last",
            ),
            {"chart_name": "exit"},
        )
        right_fsm = files["exit_region_right_fsm.vhd"]
        assert (
            "state_q = ST_R1 and state_next /= ST_R1 and "
            "event_tick_recv_valid = '1'"
        ) in right_fsm

    # ----- Intra-region capture coexists with xreg -----

    def test_intra_region_capture_continues_to_work_for_same_event_in_chart_with_xreg(
        self,
    ):
        chart = {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {"id": "left", "initial": "L1",
                     "datamodel": [
                         {"data": [{"id": "lcap", "expr": "0",
                                    "type": "i32"}]},
                     ],
                     "state": [
                         _state("L1", transitions=[
                             {"target": "L2", "raise_value": [
                                 {"event": "tick", "param": [
                                     {"name": "value", "expr": "7"},
                                 ]},
                             ]},
                         ]),
                         {"id": "L2",
                          "onentry": [{"assign": [
                              {"location": "lcap",
                               "expr": "event.tick.value"},
                          ]}],
                          "transition": [
                              {"event": "tick", "target": "L1"},
                          ]},
                     ]},
                    {"id": "right", "initial": "R1",
                     "datamodel": [
                         {"data": [{"id": "rcap", "expr": "0",
                                    "type": "i32"}]},
                     ],
                     "state": [
                         _state("R1", transitions=[{"target": "R2"}]),
                         {"id": "R2",
                          "onentry": [{"assign": [
                              {"location": "rcap",
                               "expr": "event.tick.value"},
                          ]}],
                          "transition": [{"target": "R1"}]},
                     ]},
                ],
            }],
        }
        files = render_target(chart, {"chart_name": "mix"})
        left_fsm = files["mix_region_left_fsm.vhd"]
        right_fsm = files["mix_region_right_fsm.vhd"]
        # Intra-region (left) shape.
        assert (
            "state_q /= ST_L2 and state_next = ST_L2 and "
            "event_tick_recv_valid = '1'"
        ) in left_fsm
        assert "lcap_q <= signed(event_tick_recv_data)" in left_fsm
        # Cross-region (right) shape.
        assert (
            "state_q /= ST_R2 and state_next = ST_R2 and "
            "event_tick_recv_valid = '1'"
        ) in right_fsm
        assert "rcap_q <= signed(event_tick_recv_data)" in right_fsm
        # Chart-top broadcast bus present.
        top = files["mix_top.vhd"]
        assert "chart_event_tick_raise_valid" in top

    # ----- Chart-event raiser map -----

    def test_chart_event_raiser_map_built_correctly(self):
        from _chart_events import build_chart_event_raiser_map
        import transliterate_hdl_vhdl

        chart = (
            TestWave3fFutureCrossRegionEventCaptureVhdl
            ._chart_multi_raiser()
        )
        parsed = transliterate_hdl_vhdl._normalise_chart(chart, "rmap")
        raiser_map = build_chart_event_raiser_map(parsed.regions)
        assert "shared" in raiser_map
        assert raiser_map["shared"] == ["a", "b"]
        assert "ghost" not in raiser_map


# ---------------------------------------------------------------------------
# PCDN-SOS-08-C-007 (2026-05-25 §15) — per-`<param>` sub-buses (VHDL).
# Mirror of the SV walker's `TestPCDN007PerParamSubBuses`.  Same fixture
# layout; assertions adapted for VHDL emit (entity port decls, signal
# declarations, signed() casts, port-map associations).
# ---------------------------------------------------------------------------


class TestPCDN007PerParamSubBusesVhdl:
    """PCDN-SOS-08-C-007 (2026-05-25 §15) — VHDL mirror of the SV
    walker's per-`<param>` sub-bus emit + suffix routing + chart-vocab
    rejection assertions."""

    @staticmethod
    def _chart_no_params():
        return {
            "datamodel": [{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
            ]}],
            "state": [
                {"id": "idle", "transition": [
                    {"target": "fire", "raise_value": [
                        {"event": "tick"},
                    ]},
                ]},
                {"id": "fire", "transition": [
                    {"event": "tick", "target": "idle"},
                ]},
            ],
            "initial": "idle",
        }

    @staticmethod
    def _chart_value_only_param():
        return {
            "datamodel": [{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
                {"id": "src", "expr": "7", "type": "i32"},
            ]}],
            "state": [
                {"id": "idle", "transition": [
                    {"target": "fire", "raise_value": [
                        {"event": "tick", "param": [
                            {"name": "value", "expr": "src"},
                        ]},
                    ]},
                ]},
                {"id": "fire",
                 "onentry": [{"assign": [
                     {"location": "x", "expr": "event.tick.value"},
                 ]}],
                 "transition": [
                     {"event": "tick", "target": "idle"},
                 ]},
            ],
            "initial": "idle",
        }

    @staticmethod
    def _chart_two_named_params():
        return {
            "datamodel": [{"data": [
                {"id": "hi_q", "expr": "0", "type": "i32"},
                {"id": "lo_q", "expr": "0", "type": "i32"},
                {"id": "src_hi", "expr": "1", "type": "i32"},
                {"id": "src_lo", "expr": "2", "type": "i32"},
            ]}],
            "state": [
                {"id": "idle", "transition": [
                    {"target": "fire", "raise_value": [
                        {"event": "tick", "param": [
                            {"name": "hi", "expr": "src_hi"},
                            {"name": "lo", "expr": "src_lo"},
                        ]},
                    ]},
                ]},
                {"id": "fire",
                 "onentry": [{"assign": [
                     {"location": "hi_q", "expr": "event.tick.hi"},
                     {"location": "lo_q", "expr": "event.tick.lo"},
                 ]}],
                 "transition": [
                     {"event": "tick", "target": "idle"},
                 ]},
            ],
            "initial": "idle",
        }

    @staticmethod
    def _chart_first_declared_param_only(p_name: str = "payload"):
        return {
            "datamodel": [{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
                {"id": "src", "expr": "11", "type": "i32"},
            ]}],
            "state": [
                {"id": "idle", "transition": [
                    {"target": "fire", "raise_value": [
                        {"event": "tick", "param": [
                            {"name": p_name, "expr": "src"},
                        ]},
                    ]},
                ]},
                {"id": "fire",
                 "onentry": [{"assign": [
                     {"location": "x", "expr": f"event.tick.{p_name}"},
                 ]}],
                 "transition": [
                     {"event": "tick", "target": "idle"},
                 ]},
            ],
            "initial": "idle",
        }

    # ---------- Regression guards ---------------------------------------

    def test_byte_identity_for_chart_without_param_children_vhdl(self):
        """No `<param>` children → no payload-bearing event → no
        recv_data port emitted at the entity boundary."""
        vhd = render_target(
            self._chart_no_params(), {"chart_name": "nop"}
        )["nop_fsm.vhd"]
        assert "event_tick_recv_data_" not in vhd
        assert "event_tick_recv_data" not in vhd

    def test_byte_identity_for_chart_with_only_value_param_vhdl(self):
        """A SOLE `<param name="value">` keeps the wave-3-e single-bus
        emit — the legacy alias is the sole bus; no per-param sub-bus."""
        vhd = render_target(
            self._chart_value_only_param(), {"chart_name": "vop"}
        )["vop_fsm.vhd"]
        assert "event_tick_recv_data" in vhd
        assert "event_tick_recv_data_value" not in vhd
        assert "x_q <= signed(event_tick_recv_data)" in vhd

    # ---------- Per-`<param>` sub-bus emit ------------------------------

    def test_two_param_event_emits_both_sub_buses_vhdl(self):
        vhd = render_target(
            self._chart_two_named_params(), {"chart_name": "tp"}
        )["tp_fsm.vhd"]
        # Both per-param sub-bus port decls present.
        assert "event_tick_recv_data_hi" in vhd
        assert "event_tick_recv_data_lo" in vhd
        # Legacy alias port preserved (byte-identity guard).
        assert "event_tick_recv_data " in vhd or "event_tick_recv_data:" in vhd

    def test_legacy_alias_wired_to_value_when_value_param_present_vhdl(self):
        vhd = render_target(
            self._chart_value_only_param(), {"chart_name": "v1"}
        )["v1_fsm.vhd"]
        assert "x_q <= signed(event_tick_recv_data)" in vhd

    def test_legacy_alias_wired_to_first_declared_when_no_value_param_vhdl(self):
        vhd = render_target(
            self._chart_first_declared_param_only("payload"),
            {"chart_name": "fd"},
        )["fd_fsm.vhd"]
        assert "event_tick_recv_data_payload" in vhd
        assert "x_q <= signed(event_tick_recv_data_payload)" in vhd

    # ---------- Suffix routing ------------------------------------------

    def test_assign_event_value_routes_to_legacy_alias_vhdl(self):
        vhd = render_target(
            self._chart_value_only_param(), {"chart_name": "val"}
        )["val_fsm.vhd"]
        assert "x_q <= signed(event_tick_recv_data)" in vhd

    def test_assign_event_custom_param_routes_to_sub_bus_vhdl(self):
        vhd = render_target(
            self._chart_two_named_params(), {"chart_name": "cp"}
        )["cp_fsm.vhd"]
        # Chart-side datamodel id `hi_q` becomes register `hi_q_q`
        # (VHDL walker keeps the `_q` register suffix).
        assert "hi_q_q <= signed(event_tick_recv_data_hi)" in vhd
        assert "lo_q_q <= signed(event_tick_recv_data_lo)" in vhd

    # ---------- Chart-vocab errors --------------------------------------

    def test_assign_undeclared_param_raises_chart_vocab_error_vhdl(self):
        chart = {
            "datamodel": [{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
                {"id": "src", "expr": "1", "type": "i32"},
            ]}],
            "state": [
                {"id": "idle", "transition": [
                    {"target": "fire", "raise_value": [
                        {"event": "tick", "param": [
                            {"name": "actual", "expr": "src"},
                        ]},
                    ]},
                ]},
                {"id": "fire",
                 "onentry": [{"assign": [
                     {"location": "x", "expr": "event.tick.bogus"},
                 ]}],
                 "transition": [
                     {"event": "tick", "target": "idle"},
                 ]},
            ],
            "initial": "idle",
        }
        with pytest.raises(
            UnsupportedChartError,
            match=r"PCDN-SOS-08-C-007.*undeclared.*'bogus'",
        ):
            render_target(chart, {"chart_name": "x"})

    def test_param_name_value_collision_raises_chart_vocab_error_vhdl(self):
        chart = {
            "datamodel": [{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
            ]}],
            "state": [
                {"id": "idle", "transition": [
                    {"target": "fire", "raise_value": [
                        {"event": "tick", "param": [
                            {"name": "value", "expr": "1"},
                            {"name": "extra", "expr": "2"},
                        ]},
                    ]},
                ]},
                {"id": "fire", "transition": [
                    {"event": "tick", "target": "idle"},
                ]},
            ],
            "initial": "idle",
        }
        with pytest.raises(
            UnsupportedChartError,
            match=r"collides with the legacy",
        ):
            render_target(chart, {"chart_name": "x"})

    # ---------- Edge gating mirrors -------------------------------------

    def test_onentry_capture_via_per_param_bus_vhdl(self):
        vhd = render_target(
            self._chart_first_declared_param_only("payload"),
            {"chart_name": "oe"},
        )["oe_fsm.vhd"]
        assert (
            "state_q /= ST_FIRE and state_next = ST_FIRE and "
            "event_tick_recv_valid = '1'"
        ) in vhd
        assert "x_q <= signed(event_tick_recv_data_payload)" in vhd

    def test_onexit_capture_via_per_param_bus_vhdl(self):
        chart = {
            "datamodel": [{"data": [
                {"id": "x", "expr": "0", "type": "i32"},
                {"id": "src", "expr": "33", "type": "i32"},
            ]}],
            "state": [
                {"id": "idle", "transition": [
                    {"target": "fire", "raise_value": [
                        {"event": "tick", "param": [
                            {"name": "payload", "expr": "src"},
                        ]},
                    ]},
                ]},
                {"id": "fire",
                 "onexit": [{"assign": [
                     {"location": "x", "expr": "event.tick.payload"},
                 ]}],
                 "transition": [
                     {"event": "tick", "target": "idle"},
                 ]},
            ],
            "initial": "idle",
        }
        vhd = render_target(chart, {"chart_name": "ox"})["ox_fsm.vhd"]
        assert (
            "state_q = ST_FIRE and state_next /= ST_FIRE and "
            "event_tick_recv_valid = '1'"
        ) in vhd
        assert "x_q <= signed(event_tick_recv_data_payload)" in vhd

    # ---------- Cross-`<raise>` param-name union ------------------------

    def test_multi_raise_same_event_unions_param_names_vhdl(self):
        chart = {
            "datamodel": [{"data": [
                {"id": "x_hi", "expr": "0", "type": "i32"},
                {"id": "x_lo", "expr": "0", "type": "i32"},
                {"id": "src_hi", "expr": "1", "type": "i32"},
                {"id": "src_lo", "expr": "2", "type": "i32"},
            ]}],
            "state": [
                {"id": "idle", "transition": [
                    {"target": "send_hi", "raise_value": [
                        {"event": "tick", "param": [
                            {"name": "hi", "expr": "src_hi"},
                        ]},
                    ]},
                ]},
                {"id": "send_hi", "transition": [
                    {"target": "send_lo", "raise_value": [
                        {"event": "tick", "param": [
                            {"name": "lo", "expr": "src_lo"},
                        ]},
                    ]},
                ]},
                {"id": "send_lo",
                 "onentry": [{"assign": [
                     {"location": "x_hi", "expr": "event.tick.hi"},
                     {"location": "x_lo", "expr": "event.tick.lo"},
                 ]}],
                 "transition": [
                     {"event": "tick", "target": "idle"},
                 ]},
            ],
            "initial": "idle",
        }
        vhd = render_target(chart, {"chart_name": "u"})["u_fsm.vhd"]
        assert "event_tick_recv_data_hi" in vhd
        assert "event_tick_recv_data_lo" in vhd
        assert "x_hi_q <= signed(event_tick_recv_data_hi)" in vhd
        assert "x_lo_q <= signed(event_tick_recv_data_lo)" in vhd

    # ---------- Chart-top wrapper integration ---------------------------

    def test_chart_top_emits_per_param_sub_bus_signals_vhdl(self):
        chart = {
            "parallel": [{"id": "par", "state": [
                {"id": "P", "datamodel": [], "state": [
                    {"id": "p0", "transition": [
                        {"target": "p1", "raise_value": [
                            {"event": "tick", "param": [
                                {"name": "payload", "expr": "0"},
                            ]},
                        ]},
                    ]},
                    {"id": "p1", "transition": [{"target": "p0"}]},
                ]},
                {"id": "Q", "datamodel": [{"data": [
                    {"id": "y", "expr": "0", "type": "i32"},
                ]}], "state": [
                    {"id": "q0", "transition": [
                        {"event": "tick", "target": "q1"},
                    ]},
                    {"id": "q1",
                     "onentry": [{"assign": [
                         {"location": "y", "expr": "event.tick.payload"},
                     ]}],
                     "transition": [
                         {"event": "tick", "target": "q0"},
                     ]},
                ]},
            ]}],
        }
        files = render_target(chart, {"chart_name": "ct"})
        top = files["ct_top.vhd"]
        # Sub-bus signal declared + driven from the existing aggregate.
        assert "ev_tick_recv_data_payload_w" in top
        # Region instance port-map carries the sub-bus association.
        assert (
            "event_tick_recv_data_payload => "
            "ev_tick_recv_data_payload_w"
        ) in top


# ---------------------------------------------------------------------------
# PCDN-SOS-08-C-008 (2026-05-25 §15) — shared-datamodel HDL wiring (VHDL).
# VHDL mirror of the SV walker's `TestPCDN008SharedSignalWiring` class.
# Same chart-vocab, same v1 same-clock-domain rejection, same one-driver
# SVA invariant preservation by construction.
# ---------------------------------------------------------------------------


class TestPCDN008SharedSignalWiringVhdl:
    """PCDN-SOS-08-C-008 (2026-05-25 §15) — VHDL chart-top shared-signal
    declarations + owner-region driving process + concurrent alias.
    Mirror of the SV walker's `TestPCDN008SharedSignalWiring`.
    """

    @staticmethod
    def _parallel_chart_no_shared():
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
                                {"id": "L1", "transition": [
                                    {"target": "L2"},
                                ]},
                                {"id": "L2"},
                            ],
                        },
                        {
                            "id": "right",
                            "initial": "R1",
                            "state": [
                                {"id": "R1", "transition": [
                                    {"target": "R2"},
                                ]},
                                {"id": "R2"},
                            ],
                        },
                    ],
                },
            ],
        }

    @staticmethod
    def _chart_with_shared_signal(
        *,
        width: str = "8",
        writer_expr: str = "42",
        with_reader: bool = False,
        cross_domain: bool = False,
    ):
        chart = {
            "datamodel": [{"data": [
                {"id": "counter", "expr": "0", "type": "i8"},
            ]}],
            "initial": "p",
            "parallel": [
                {
                    "id": "p",
                    "state": [
                        {
                            "id": "owner",
                            "initial": "O1",
                            "state": [
                                {
                                    "id": "O1",
                                    "onentry": [{"assign": [
                                        {
                                            "location": "my_shared",
                                            "expr": writer_expr,
                                        },
                                    ]}],
                                    "transition": [{"target": "O2"}],
                                },
                                {"id": "O2"},
                            ],
                        },
                        {
                            "id": "reader",
                            "initial": "R1",
                            "state": [
                                {"id": "R1", "transition": [
                                    {"target": "R2"},
                                ]},
                                {"id": "R2"},
                            ],
                        },
                    ],
                },
            ],
            "sos:shared_signal": [
                {
                    "name": "my_shared",
                    "width": width,
                    "owner_region": "owner",
                },
            ],
        }
        if with_reader:
            chart["parallel"][0]["state"][1]["state"][0][
                "sos:shared_signal_ref"
            ] = [{"name": "my_shared"}]
        if cross_domain:
            chart["parallel"][0]["state"][0]["clock"] = "fast"
            chart["parallel"][0]["state"][1]["clock"] = "slow"
        return chart

    # ---------- Regression guard --------------------------------------

    def test_byte_identity_for_chart_without_shared_signal(self):
        files = render_target(
            self._parallel_chart_no_shared(), {"chart_name": "ns"}
        )
        top = files["ns_top.vhd"]
        assert "PCDN-SOS-08-C-008" not in top
        assert "shared_" not in top

    # ---------- Declaration + concurrent alias ----------------------

    def test_shared_signal_declared_at_chart_top(self):
        files = render_target(
            self._chart_with_shared_signal(), {"chart_name": "sh"}
        )
        top = files["sh_top.vhd"]
        assert (
            "signal shared_my_shared : "
            "std_logic_vector(7 downto 0);"
        ) in top
        assert (
            "signal shared_my_shared_q : "
            "std_logic_vector(7 downto 0);"
        ) in top

    def test_continuous_assign_from_q_to_combinational(self):
        files = render_target(
            self._chart_with_shared_signal(), {"chart_name": "sh"}
        )
        top = files["sh_top.vhd"]
        assert "shared_my_shared <= shared_my_shared_q;" in top

    # ---------- Owner-driver process ---------------------------------

    def test_owner_region_drives_shared_signal_q(self):
        files = render_target(
            self._chart_with_shared_signal(), {"chart_name": "sh"}
        )
        top = files["sh_top.vhd"]
        # The owner is on `clk_main`; the process is rising-edge-clocked
        # with a reset arm and writes `shared_<name>_q`.
        assert "process(clk_main) is" in top
        assert "if rising_edge(clk_main) then" in top
        assert "if rst_main = '1' then" in top
        assert "shared_my_shared_q <=" in top

    def test_reader_region_reads_shared_signal(self):
        files = render_target(
            self._chart_with_shared_signal(with_reader=True),
            {"chart_name": "sh"},
        )
        top = files["sh_top.vhd"]
        # Reader-validation pass survives; the chart-top wire is
        # visible to the reader region.
        assert "shared_my_shared" in top
        assert (
            "signal shared_my_shared : "
            "std_logic_vector(7 downto 0);"
        ) in top

    # ---------- Cross-clock-domain rejection -------------------------

    def test_cross_clock_domain_owner_reader_raises(self):
        """v1 same-clock-domain only: cross-domain readers raise."""
        chart = self._chart_with_shared_signal(
            with_reader=True, cross_domain=True
        )
        with pytest.raises(
            UnsupportedChartError,
            match=r"SOS-08-C wave-future-shared-xclk:",
        ):
            render_target(chart, {"chart_name": "sh"})

    # ---------- `<sos:shared_signal_ref>` element recognition --------

    def test_shared_signal_ref_in_assign_location_recognised(self):
        """A `<sos:shared_signal_ref>` element in the reader's subtree
        is recognised; same-domain configurations pass through cleanly.
        """
        chart = self._chart_with_shared_signal(with_reader=True)
        files = render_target(chart, {"chart_name": "sh"})
        top = files["sh_top.vhd"]
        assert "shared_my_shared" in top

    # ---------- Width propagation ------------------------------------

    def test_width_propagates_to_signal_declaration(self):
        files = render_target(
            self._chart_with_shared_signal(width="16"),
            {"chart_name": "sh"},
        )
        top = files["sh_top.vhd"]
        assert (
            "signal shared_my_shared : "
            "std_logic_vector(15 downto 0);"
        ) in top
        assert (
            "signal shared_my_shared_q : "
            "std_logic_vector(15 downto 0);"
        ) in top

    # ---------- Multiple shared signals ------------------------------

    def test_multiple_shared_signals_emit_independently(self):
        chart = self._chart_with_shared_signal()
        chart["sos:shared_signal"] = [
            {"name": "a", "width": "8", "owner_region": "owner"},
            {"name": "b", "width": "4", "owner_region": "owner"},
        ]
        chart["parallel"][0]["state"][0]["state"][0]["onentry"] = [
            {"assign": [
                {"location": "a", "expr": "1"},
                {"location": "b", "expr": "2"},
            ]},
        ]
        files = render_target(chart, {"chart_name": "sh"})
        top = files["sh_top.vhd"]
        assert (
            "signal shared_a : std_logic_vector(7 downto 0);"
        ) in top
        assert (
            "signal shared_b : std_logic_vector(3 downto 0);"
        ) in top
        assert "shared_a <= shared_a_q;" in top
        assert "shared_b <= shared_b_q;" in top

    # ---------- ECMA-subset lowering ---------------------------------

    def test_owner_region_assign_uses_ecma_subset_lowering(self):
        """The owner-region's assign RHS lowers via the wave-3-f-future-
        assign ECMA subset.  VHDL chart-top has no datamodel ports, so
        ident-bearing RHS expressions defer to a literal-zero fallback
        with a comment (see module-level note in
        `transliterate_hdl_vhdl.py`); literal/binop-literal RHS lowers
        normally.
        """
        # Literal RHS.
        files = render_target(
            self._chart_with_shared_signal(writer_expr="7"),
            {"chart_name": "lit"},
        )
        top = files["lit_top.vhd"]
        assert (
            "shared_my_shared_q <= "
            "std_logic_vector(to_signed(7, 8));"
        ) in top

        # Datamodel-ident RHS — deferred to literal-zero fallback with
        # an explanatory comment.
        files = render_target(
            self._chart_with_shared_signal(writer_expr="counter"),
            {"chart_name": "id"},
        )
        top = files["id_top.vhd"]
        assert "deferred" in top
        assert (
            "shared_my_shared_q <= "
            "std_logic_vector(to_signed(0, 8));"
        ) in top

        # Binop-on-literals RHS lowers normally.
        files = render_target(
            self._chart_with_shared_signal(writer_expr="3 + 4"),
            {"chart_name": "bn"},
        )
        top = files["bn_top.vhd"]
        # The binop is rendered with signed casts around each operand.
        assert "shared_my_shared_q <=" in top

        # Boolean literal (`true`) lowers to integer 1 via the parser.
        files = render_target(
            self._chart_with_shared_signal(
                width="1", writer_expr="true"
            ),
            {"chart_name": "bool"},
        )
        top = files["bool_top.vhd"]
        assert "shared_my_shared_q <=" in top

    # ---------- D walker invariant preservation ----------------------

    def test_d_walker_one_driver_invariant_preserved_by_construction(self):
        """Exactly ONE driver of ``shared_<name>_q`` (the owner-region
        driving process).  SOS-08-D's `_emit_shared_signal_invariants`
        SVA assertion is structurally satisfied.
        """
        files = render_target(
            self._chart_with_shared_signal(), {"chart_name": "inv"}
        )
        top = files["inv_top.vhd"]
        # Exactly one banner comment for the shared signal → exactly
        # one driver process.
        assert top.count(
            "-- <sos:shared_signal name=\"my_shared\""
        ) == 1
        # The concurrent alias reads (does not drive) the _q register.
        assert "shared_my_shared <= shared_my_shared_q;" in top

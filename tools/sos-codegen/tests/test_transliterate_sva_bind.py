"""SOS-08-D SVA bind file emitter tests (wave-1).

@spec docs/concepts/SOS-08-D-CONCEPTS.md §6.3 (per-DUT SVA bind file shape)
      docs/concepts/SOS-08-D-CONCEPTS.md §15  (ratified 2026-05-23; PCDN-D-004)
      docs/concepts/SOS-08-D-CONCEPTS.md §7   (INV-S-HDL-D-3..5)
      docs/concepts/SOS-08-C-CONCEPTS.md §5.1 (one-hot encoding mirrored)
      docs/concepts/SOS-08-C-CONCEPTS.md §6   (chart→FSM emission this binds to)
      docs/concepts/SOS-07-CONCEPTS.md  §6    (INV-SOS-A..H — cited)
      docs/concepts/SOS-08-CONCEPTS.md  §7    (INV-S-HDL-1..5 — cited;
                                              INV-S-HDL-5 chart-vocabulary
                                              failure messages = load-bearing
                                              for $fatal format checks)

These tests verify the wave-1 surface of
``transliterate_sva_bind.render_target``:
  * Two files emitted per single-region chart (assertion module + bind
    directive), both rooted under ``tests/<chart>/`` per PCDN-D-004.
  * One-hot invariant assertion present.
  * Reset-initial assertion present.
  * Per-chart-transition property emitted.
  * Guard expressions lower into the antecedent.
  * Bind directive uses module-type bind shape.
  * Every assertion has an ``else $fatal(1, "SOS-08-D INV-D-..."``
    clause (INV-S-HDL-5).
  * Parallel charts reject at wave-1.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest


TESTS_DIR = Path(__file__).resolve().parent
TOOL_DIR = TESTS_DIR.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))


transliterate_sva_bind = pytest.importorskip(
    "transliterate_sva_bind",
    reason="transliterate_sva_bind not importable — wave-1 SVA-bind suite "
    "skips until the module lands.",
)


# ---------------------------------------------------------------------------
# Inline scjson-dict builders. Same shape as the SOS-08-C SV walker tests
# (single-region charts; no parallel) plus a parallel reject fixture.
# ---------------------------------------------------------------------------


def _state(state_id, *, transitions=None, onentry=None, onexit=None):
    out: dict[str, Any] = {"id": state_id}
    if transitions is not None:
        out["transition"] = transitions
    if onentry is not None:
        out["onentry"] = onentry
    if onexit is not None:
        out["onexit"] = onexit
    return out


def _simple_chart():
    """Three-state linear chart: A → B → C. No guards, no datamodel."""
    return {
        "initial": "A",
        "state": [
            _state("A", transitions=[{"event": "go", "target": "B"}]),
            _state("B", transitions=[{"event": "finish", "target": "C"}]),
            _state("C"),
        ],
    }


def _chart_with_guarded_transition():
    return {
        "initial": "A",
        "datamodel": [
            {"data": [{"id": "a", "expr": "0", "type": "int"}]},
        ],
        "state": [
            _state(
                "A",
                transitions=[
                    {"target": "B", "cond": "a == 1"},
                ],
            ),
            _state("B"),
        ],
    }


def _chart_with_three_transitions():
    return {
        "initial": "A",
        "state": [
            _state("A", transitions=[{"target": "B"}]),
            _state("B", transitions=[{"target": "C"}]),
            _state("C", transitions=[{"target": "A"}]),
        ],
    }


def _parallel_chart():
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


# ---------------------------------------------------------------------------
# File shape / placement.
# ---------------------------------------------------------------------------


def test_render_emits_two_files():
    """PCDN-D-004 / SOS-08-D §6.1: emit one assertion module + one bind
    directive per single-region chart, both rooted under tests/<chart>/."""
    chart = _simple_chart()
    out = transliterate_sva_bind.render_target(chart, {"chart_name": "simple"})
    assert isinstance(out, dict)
    assert len(out) == 2
    fnames = set(out.keys())
    assert "tests/simple/simple_fsm_sva.sv" in fnames
    assert "tests/simple/simple_fsm_bind.sv" in fnames


def test_per_dut_test_directory_prefix():
    """All emitted files live under ``tests/<chart>/`` per PCDN-D-004."""
    chart = _simple_chart()
    out = transliterate_sva_bind.render_target(chart, {"chart_name": "MyChart"})
    for fname in out:
        assert fname.startswith("tests/mychart/"), fname


# ---------------------------------------------------------------------------
# Assertion module shape.
# ---------------------------------------------------------------------------


def _sva_source(chart, *, chart_name="simple"):
    out = transliterate_sva_bind.render_target(chart, {"chart_name": chart_name})
    sva_path = f"tests/{chart_name.lower()}/{chart_name.lower()}_fsm_sva.sv"
    assert sva_path in out, f"missing assertion module file at {sva_path}"
    return out[sva_path]


def _bind_source(chart, *, chart_name="simple"):
    out = transliterate_sva_bind.render_target(chart, {"chart_name": chart_name})
    bind_path = f"tests/{chart_name.lower()}/{chart_name.lower()}_fsm_bind.sv"
    assert bind_path in out, f"missing bind directive at {bind_path}"
    return out[bind_path]


def test_assertion_module_declares_state_constants():
    """SOS-08-C §5.1 one-hot encoding mirrored on the SVA side so the
    chart-FSM module's ST_* constants and the assertion module's match
    by construction (INV-S-HDL-C-1 / INV-S-HDL-D-3)."""
    src = _sva_source(_simple_chart())
    assert "ST_A" in src
    assert "ST_B" in src
    assert "ST_C" in src
    # One-hot literal of width 3 should appear (e.g. 3'b001).
    assert re.search(r"3'b[01]{3}", src), src


def test_assertion_module_has_clk_rst_current_state_ports():
    """PCDN-SOS-08-D-wave1-sva-port-name (2026-05-23): the SVA module's
    state-vector input port is named ``current_state`` (matching the
    DUT's external output port), NOT ``state_q`` (the DUT-internal
    register name). Module-type bind wires external→external."""
    src = _sva_source(_simple_chart())
    assert "module simple_fsm_sva" in src
    assert re.search(r"input\s+wire\s+clk\b", src)
    assert re.search(r"input\s+wire\s+rst\b", src)
    assert re.search(r"input\s+wire\s+\[2:0\]\s+current_state\b", src)


def test_sva_module_input_port_is_current_state_not_state_q():
    """Regression guard for PCDN-SOS-08-D-wave1-sva-port-name (2026-05-23).

    The SVA assertion module's state-vector input port MUST be named
    ``current_state`` (the DUT's external output port name), NOT
    ``state_q`` (the DUT-internal register name). Module-type bind
    connects external ports to external ports, so a mismatched port
    name on the SVA side would refuse to elaborate."""
    src = _sva_source(_simple_chart())

    # Positive: current_state appears as the input port declaration.
    assert re.search(
        r"input\s+wire\s+\[\d+:\d+\]\s+current_state\b", src
    ), f"SVA module must declare `current_state` as input port:\n{src}"

    # Negative: no `state_q` input-port declaration should appear in
    # the emitted SV. (Docstring/comment mentions of `state_q` live in
    # the .py source, not the .sv emit.)
    assert not re.search(
        r"input\s+wire\s+\[?\d*:?\d*\]?\s*state_q\b", src
    ), f"SVA module must NOT declare `state_q` input port:\n{src}"


def test_one_hot_assertion_present():
    """INV-D-1: assertion checks ``$countones(current_state) <= 1`` on
    every posedge clk (one-hot encoding invariant)."""
    src = _sva_source(_simple_chart())
    assert "$countones(current_state) <= 1" in src
    assert "a_one_hot" in src
    assert "SOS-08-D INV-D-1" in src


def test_reset_initial_assertion_present():
    """INV-D-2: ``rst |=> current_state == ST_<initial>``. Chart
    initial='A' → assertion targets ST_A."""
    src = _sva_source(_simple_chart())
    assert "a_reset_initial" in src
    # Look for the |=> form with the initial state constant.
    assert re.search(
        r"rst\s*\|=>\s*\(current_state\s*==\s*ST_A\)", src
    ), src
    assert "SOS-08-D INV-D-2" in src


def test_per_transition_assertion_per_chart_transition():
    """Chart with three transitions (A→B, B→C, C→A) → three a_trans_*
    properties."""
    src = _sva_source(_chart_with_three_transitions(), chart_name="ring")
    trans_ids = re.findall(r"a_trans_\w+:\s*assert\s+property", src)
    assert len(trans_ids) == 3, f"expected 3 transition properties, got {len(trans_ids)}: {trans_ids}"


def test_guarded_transition_includes_cond():
    """A chart with ``cond="a == 1"`` → the assertion antecedent
    contains the guard with the registered-signal name (``data_a_q``)."""
    src = _sva_source(_chart_with_guarded_transition(), chart_name="g")
    # Compiled antecedent: (current_state == ST_A) && (data_a_q == 1)
    # The exact spacing / parens depend on hdl_common.emit_guard_expr;
    # accept any whitespace and parens around the comparison.
    assert "data_a_q" in src, src
    assert re.search(
        r"\(current_state\s*==\s*ST_A\)\s*&&\s*\(.*data_a_q.*==.*1.*\)",
        src,
    ), src


def test_guarded_transition_signal_routed_as_input_port():
    """A datamodel signal referenced by a guard surfaces as an
    ``input wire [W-1:0] data_<id>_q`` port on the assertion module
    so the antecedent compiles."""
    src = _sva_source(_chart_with_guarded_transition(), chart_name="g")
    assert re.search(
        r"input\s+wire\s+\[31:0\]\s+data_a_q\b",
        src,
    ), src


# ---------------------------------------------------------------------------
# Failure-message format (INV-S-HDL-5 + INV-S-HDL-D-5).
# ---------------------------------------------------------------------------


def test_chart_vocabulary_failure_messages():
    """INV-S-HDL-5 / INV-S-HDL-D-5: every assert has an
    ``else $fatal(1, "SOS-08-D INV-D-..."`` clause; messages cite the
    chart name + invariant id so failures surface in chart vocabulary."""
    src = _sva_source(_chart_with_three_transitions(), chart_name="ring")

    # Count `assert property` blocks; each must have a matching $fatal.
    asserts = re.findall(r"assert\s+property\s*\(", src)
    fatals = re.findall(r"\$fatal\s*\(\s*1\s*,", src)
    assert len(asserts) == len(fatals), (
        f"every assert needs an else $fatal; got {len(asserts)} asserts "
        f"and {len(fatals)} fatals"
    )

    # Every $fatal message body cites SOS-08-D + an INV-D-N id.
    for m in re.finditer(
        r'\$fatal\s*\(\s*1\s*,\s*\n?\s*"([^"]+)"', src
    ):
        msg = m.group(1)
        assert "SOS-08-D" in msg, (
            f"$fatal message {msg!r} does not cite SOS-08-D"
        )
        assert re.search(r"INV-D-\d+", msg), (
            f"$fatal message {msg!r} does not cite INV-D-N"
        )
        # Chart name surfaces in the failure (chart vocabulary).
        assert "ring" in msg, (
            f"$fatal message {msg!r} does not surface the chart name"
        )


# ---------------------------------------------------------------------------
# Bind directive shape.
# ---------------------------------------------------------------------------


def test_bind_directive_module_type():
    """SOS-08-D §6.3 + PCDN-A-bind-form: module-type bind directive
    attaches the assertion module to every elaborated DUT instance."""
    src = _bind_source(_simple_chart())
    # bind <dut_module> <sva_module> <inst> ( ... );
    assert re.search(
        r"bind\s+simple_fsm\s+simple_fsm_sva\s+u_\w+\s*\(",
        src,
    ), src


def test_bind_directive_wires_dut_current_state_to_sva_current_state():
    """PCDN-SOS-08-D-wave1-sva-port-name (2026-05-23): the assertion
    module's ``current_state`` input is driven from the chart-FSM
    module's ``current_state`` output (SOS-08-C §6.2). Module-type
    bind connects external→external; the SVA-side port name matches
    the DUT-side output port name verbatim."""
    src = _bind_source(_simple_chart())
    assert re.search(
        r"\.current_state\s*\(\s*current_state\s*\)",
        src,
    ), src
    # Regression guard: bind directive must NOT use the legacy
    # `.state_q(current_state)` form (the DUT-internal name).
    assert not re.search(r"\.state_q\s*\(", src), (
        f"bind directive must not reference the DUT-internal "
        f"`state_q` name:\n{src}"
    )


def test_bind_directive_routes_clk_rst():
    src = _bind_source(_simple_chart())
    assert re.search(r"\.clk\s*\(\s*clk\s*\)", src)
    assert re.search(r"\.rst\s*\(\s*rst\s*\)", src)


def test_bind_directive_wires_guard_signal():
    """When a chart transition has a guard referencing a datamodel
    signal, the bind directive wires the DUT's ``data_<id>`` output
    into the assertion module's ``data_<id>_q`` input."""
    src = _bind_source(_chart_with_guarded_transition(), chart_name="g")
    assert re.search(
        r"\.data_a_q\s*\(\s*data_a\s*\)",
        src,
    ), src


# ---------------------------------------------------------------------------
# Citations / wave-1 scope rejection.
# ---------------------------------------------------------------------------


def test_module_cites_sos_08_d_spec():
    src = _sva_source(_simple_chart())
    assert "SOS-08-D" in src
    assert "§6.3" in src or "6.3" in src


def test_parallel_charts_accepted_at_wave_2b():
    """Wave-2b (2026-05-23 §15): parallel charts now emit per-region
    SVA + per-region bind files; the wave-1 rejection is lifted."""
    chart = _parallel_chart()
    files = transliterate_sva_bind.render_target(chart, {"chart_name": "p"})
    # Two regions in the fixture → 4 files (2 per region).
    assert len(files) == 4, (
        f"Wave-2b parallel-chart emit expected 4 files for the 2-region "
        f"fixture; got {sorted(files)}"
    )
    # Per-region file names follow `<chart>_region_<region>_fsm_*.sv`.
    expected = {
        "tests/p/p_region_left_fsm_sva.sv",
        "tests/p/p_region_left_fsm_bind.sv",
        "tests/p/p_region_right_fsm_sva.sv",
        "tests/p/p_region_right_fsm_bind.sv",
    }
    assert set(files) == expected


class TestParallelChartEmit:
    """SOS-08-D wave-2b parallel-chart emission contract (§15
    2026-05-23 entry)."""

    def _files(self):
        return transliterate_sva_bind.render_target(
            _parallel_chart(), {"chart_name": "p"}
        )

    def test_per_region_sva_module_name(self):
        sva = self._files()["tests/p/p_region_left_fsm_sva.sv"]
        # SVA module name follows `<chart>_region_<region>_fsm_sva`.
        assert "module p_region_left_fsm_sva" in sva

    def test_per_region_bind_targets_chart_top_wrapper(self):
        """The bind directive MUST target the chart-top wrapper module
        `<chart>_fsm` (per SOS-08-C §6.10), NOT the per-region FSM
        module."""
        bind = self._files()["tests/p/p_region_left_fsm_bind.sv"]
        # `bind <chart-top> <sva-module> <inst> (...);` — chart-top is
        # `p_fsm` per SOS-08-C wave-2 chart-top wrapper naming.
        assert "bind p_fsm p_region_left_fsm_sva" in bind

    def test_per_region_bind_wires_current_state_per_region(self):
        """The bind directive's `.current_state(...)` connection MUST
        wire the chart-top wrapper's `current_state_<region>` output
        port to the SVA module's region-local `current_state` input."""
        bind = self._files()["tests/p/p_region_left_fsm_bind.sv"]
        assert ".current_state (current_state_left)" in bind

    def test_other_region_bind_wires_other_observable(self):
        """Each region binds to its own `current_state_<region>` port."""
        bind = self._files()["tests/p/p_region_right_fsm_bind.sv"]
        assert ".current_state (current_state_right)" in bind

    def test_per_region_bind_uses_single_clock_domain(self):
        """Wave-2b assumes single-clock-domain parallel charts; the
        bind wires `.clk(clk), .rst(rst)`. Multi-clock parallel charts
        are wave-3."""
        bind = self._files()["tests/p/p_region_left_fsm_bind.sv"]
        assert ".clk           (clk)" in bind
        assert ".rst           (rst)" in bind

    def test_per_region_sva_module_has_one_hot_assertion(self):
        """Each region's SVA module retains INV-D-1 (one-hot encoding
        assertion) — the per-region observability claim is independent
        of every other region's."""
        sva = self._files()["tests/p/p_region_left_fsm_sva.sv"]
        assert "INV-D-1" in sva

    def test_per_region_sva_module_has_reset_initial_assertion(self):
        sva = self._files()["tests/p/p_region_left_fsm_sva.sv"]
        assert "INV-D-2" in sva

    def test_per_region_sva_module_has_transition_assertions(self):
        # The fixture region "left" has one transition L1→L2.
        sva = self._files()["tests/p/p_region_left_fsm_sva.sv"]
        assert "INV-D-3" in sva

    def test_per_region_bind_cites_wave_2b(self):
        """The per-region bind file's header SHOULD cite wave-2b so a
        reader of the bind file knows which contract emitted it."""
        bind = self._files()["tests/p/p_region_left_fsm_bind.sv"]
        assert "wave-2b" in bind

    def test_single_region_chart_unchanged(self):
        """Wave-2b MUST NOT change single-region emit behavior."""
        files = transliterate_sva_bind.render_target(
            _simple_chart(), {"chart_name": "demo"}
        )
        # Single-region path emits exactly 2 files at the original
        # paths.
        assert len(files) == 2
        assert "tests/demo/demo_fsm_sva.sv" in files
        assert "tests/demo/demo_fsm_bind.sv" in files


def test_chart_ir_must_be_dict():
    with pytest.raises(transliterate_sva_bind.UnsupportedChartError):
        transliterate_sva_bind.render_target(None, {"chart_name": "x"})


# ---------------------------------------------------------------------------
# SOS-08-D wave-4 (2026-05-24 §15) — multi-clock-domain bind wiring +
# cross-region invariant SVA properties.
# ---------------------------------------------------------------------------


def _multi_clock_parallel_chart():
    """Parallel chart with two regions on distinct clock domains."""
    return {
        "initial": "p",
        "parallel": [
            {
                "id": "p",
                "state": [
                    {
                        "id": "fast",
                        "clock": "fast",
                        "initial": "F1",
                        "state": [
                            _state("F1", transitions=[{"target": "F2"}]),
                            _state("F2"),
                        ],
                    },
                    {
                        "id": "slow",
                        "clock": "slow",
                        "initial": "S1",
                        "state": [
                            _state("S1", transitions=[{"target": "S2"}]),
                            _state("S2"),
                        ],
                    },
                ],
            },
        ],
    }


def _chart_with_cross_invariants():
    """Parallel chart carrying two cross-region invariants."""
    chart = _parallel_chart()
    chart["sos:cross_invariant"] = [
        {
            "id": "INV-S-CHART-1",
            "antecedent": "region.left == L2",
            "consequent": "region.right == R2",
            "within": 8,
        },
        {
            "id": "INV-S-CHART-2",
            "antecedent": "region.right == R2",
            "consequent": "region.left == L2",
            "within": 1,
        },
    ]
    return chart


class TestWave4MultiClockBindWiring:
    """Wave-4 lifts the wave-2b single-clock-domain assumption.
    Regions carrying a `clock` attribute now wire their bind to the
    chart-top wrapper's `clk_<dom>` / `rst_<dom>` ports per SOS-08-C
    wave-3's clock-distribution contract."""

    def _files(self) -> dict:
        return transliterate_sva_bind.render_target(
            _multi_clock_parallel_chart(), {"chart_name": "p"}
        )

    def test_fast_region_bind_uses_fast_clock_ports(self):
        bind = self._files()["tests/p/p_region_fast_fsm_bind.sv"]
        # Per-domain clock/reset wiring.
        assert ".clk           (clk_fast)" in bind
        assert ".rst           (rst_fast)" in bind
        # No fallback to the wave-2b shared clk/rst.
        assert ".clk           (clk)" not in bind
        assert ".rst           (rst)" not in bind

    def test_slow_region_bind_uses_slow_clock_ports(self):
        bind = self._files()["tests/p/p_region_slow_fsm_bind.sv"]
        assert ".clk           (clk_slow)" in bind
        assert ".rst           (rst_slow)" in bind

    def test_bind_header_cites_wave4_multi_clock(self):
        """Each per-region bind file's header SHOULD cite the wave-4
        multi-clock-domain wiring so a reader knows why the ports
        differ from wave-2b."""
        bind = self._files()["tests/p/p_region_fast_fsm_bind.sv"]
        assert "Wave-4 multi-clock" in bind
        assert "clk_fast" in bind
        assert "rst_fast" in bind

    def test_single_clock_region_unchanged(self):
        """Regions without a `clock` attribute keep the wave-2b
        single-clock shape (`.clk(clk)` / `.rst(rst)`)."""
        files = transliterate_sva_bind.render_target(
            _parallel_chart(), {"chart_name": "p"}
        )
        bind = files["tests/p/p_region_left_fsm_bind.sv"]
        assert ".clk           (clk)" in bind
        assert ".rst           (rst)" in bind
        # No per-domain ports leaking in.
        assert "clk_" not in bind.replace("clk_port_name", "")

    def test_mixed_clock_chart(self):
        """A chart with one region on a clock domain + one region
        without an annotation: the annotated region gets per-domain
        wiring; the bare region keeps wave-2b shape."""
        chart = {
            "initial": "p",
            "parallel": [
                {
                    "id": "p",
                    "state": [
                        {
                            "id": "fast",
                            "clock": "fast",
                            "initial": "F1",
                            "state": [
                                _state("F1", transitions=[{"target": "F2"}]),
                                _state("F2"),
                            ],
                        },
                        {
                            "id": "ref",
                            "initial": "X1",
                            "state": [
                                _state("X1"),
                            ],
                        },
                    ],
                }
            ],
        }
        files = transliterate_sva_bind.render_target(
            chart, {"chart_name": "mix"}
        )
        fast_bind = files["tests/mix/mix_region_fast_fsm_bind.sv"]
        ref_bind = files["tests/mix/mix_region_ref_fsm_bind.sv"]
        assert ".clk           (clk_fast)" in fast_bind
        assert ".clk           (clk)" in ref_bind


class TestWave4CrossRegionInvariants:
    """Wave-4 §15 ratifies the `<sos:cross_invariant>` declaration form
    + emits `<chart>_top_sva.sv` + `<chart>_top_bind.sv` carrying chart-
    top SVA properties referencing per-region observables."""

    def _files(self) -> dict:
        return transliterate_sva_bind.render_target(
            _chart_with_cross_invariants(), {"chart_name": "p"}
        )

    def test_top_sva_file_emitted(self):
        assert "tests/p/p_top_sva.sv" in self._files()

    def test_top_bind_file_emitted(self):
        assert "tests/p/p_top_bind.sv" in self._files()

    def test_chart_without_cross_invariants_omits_top_files(self):
        """Wave-2b parallel chart with no `<sos:cross_invariant>` MUST
        NOT emit the top-sva / top-bind files."""
        files = transliterate_sva_bind.render_target(
            _parallel_chart(), {"chart_name": "p"}
        )
        assert "tests/p/p_top_sva.sv" not in files
        assert "tests/p/p_top_bind.sv" not in files

    def test_top_sva_declares_per_region_state_ports(self):
        sva = self._files()["tests/p/p_top_sva.sv"]
        assert "input wire [N_STATES_LEFT-1:0] current_state_left" in sva
        assert "input wire [N_STATES_RIGHT-1:0] current_state_right" in sva

    def test_top_sva_module_name_convention(self):
        sva = self._files()["tests/p/p_top_sva.sv"]
        assert "module p_top_sva" in sva

    def test_top_sva_emits_one_property_per_invariant(self):
        sva = self._files()["tests/p/p_top_sva.sv"]
        assert "property p_inv_s_chart_1" in sva
        assert "property p_inv_s_chart_2" in sva

    def test_top_sva_assert_per_invariant(self):
        sva = self._files()["tests/p/p_top_sva.sv"]
        assert "INV_S_CHART_1: assert property" in sva
        assert "INV_S_CHART_2: assert property" in sva

    def test_top_sva_within_window_lowers_to_temporal_range(self):
        """`within="8"` lowers to `##[1:8]` SVA temporal range."""
        sva = self._files()["tests/p/p_top_sva.sv"]
        assert "##[1:8]" in sva
        # The second invariant has within=1.
        assert "##[1:1]" in sva

    def test_top_sva_failure_message_chart_vocabulary(self):
        """INV-S-HDL-D-5: failure messages render in chart vocabulary
        — name chart, invariant id, regions, states."""
        sva = self._files()["tests/p/p_top_sva.sv"]
        assert "chart `p`" in sva
        assert "INV-S-CHART-1" in sva
        assert "region `left`" in sva
        assert "state `L2`" in sva
        assert "region `right`" in sva
        assert "state `R2`" in sva

    def test_top_sva_uses_disable_iff_reset(self):
        sva = self._files()["tests/p/p_top_sva.sv"]
        assert "disable iff (rst)" in sva

    def test_top_bind_targets_chart_top_wrapper(self):
        bind = self._files()["tests/p/p_top_bind.sv"]
        assert "bind p_fsm p_top_sva" in bind

    def test_top_bind_wires_per_region_observables(self):
        bind = self._files()["tests/p/p_top_bind.sv"]
        assert ".current_state_left (current_state_left)" in bind
        assert ".current_state_right (current_state_right)" in bind

    def test_top_bind_uses_reference_clock(self):
        """Cross-region SVA samples on the chart-top reference clock
        even for multi-clock charts (per INV-S-HDL-3 — region
        observables are synced before the chart-top exposes them)."""
        bind = self._files()["tests/p/p_top_bind.sv"]
        assert ".clk           (clk)" in bind
        assert ".rst           (rst)" in bind

    def test_top_bind_default_nettype_guard(self):
        bind = self._files()["tests/p/p_top_bind.sv"]
        assert "`default_nettype none" in bind
        assert "`default_nettype wire" in bind

    def test_within_attribute_defaults_to_1(self):
        """When `within` is absent the walker defaults to 1 cycle."""
        chart = _parallel_chart()
        chart["sos:cross_invariant"] = [
            {
                "id": "INV-S-CHART-X",
                "antecedent": "region.left == L1",
                "consequent": "region.right == R1",
                # No `within` key.
            },
        ]
        files = transliterate_sva_bind.render_target(chart, {"chart_name": "p"})
        sva = files["tests/p/p_top_sva.sv"]
        assert "##[1:1]" in sva

    def test_cross_invariant_count_in_two_region_emit(self):
        """Two regions + two invariants → 2 region-sva + 2 region-bind
        + 1 top-sva + 1 top-bind = 6 files."""
        files = self._files()
        assert len(files) == 6


class TestWave4CrossInvariantValidation:
    """Wave-4 rejects malformed `<sos:cross_invariant>` declarations
    early with chart-vocabulary errors per INV-S-HDL-D-5."""

    def _chart_with_one_invariant(self, **kw):
        chart = _parallel_chart()
        inv = {
            "id": "INV-S-CHART-X",
            "antecedent": "region.left == L1",
            "consequent": "region.right == R1",
        }
        inv.update(kw)
        chart["sos:cross_invariant"] = [inv]
        return chart

    def test_rejects_missing_id(self):
        chart = self._chart_with_one_invariant(id="")
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match="non-empty `id`",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_rejects_malformed_antecedent(self):
        chart = self._chart_with_one_invariant(antecedent="left.L1")
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match="must match",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_rejects_malformed_consequent(self):
        chart = self._chart_with_one_invariant(consequent="bogus")
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match="must match",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_rejects_within_too_large(self):
        chart = self._chart_with_one_invariant(within=99999)
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match="exceeds the v1 cap",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_rejects_non_integer_within(self):
        chart = self._chart_with_one_invariant(within="forever")
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match="positive integer",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_normalises_within_zero_to_one(self):
        """`within=0` is normalised up to 1 (single-cycle reaction is
        the minimum meaningful temporal window)."""
        chart = self._chart_with_one_invariant(within=0)
        files = transliterate_sva_bind.render_target(chart, {"chart_name": "p"})
        sva = files["tests/p/p_top_sva.sv"]
        assert "##[1:1]" in sva


class TestWave4SingleRegionUnchanged:
    """Wave-4 MUST NOT change single-region emit behavior."""

    def test_single_region_emit_unchanged(self):
        files = transliterate_sva_bind.render_target(
            _simple_chart(), {"chart_name": "demo"}
        )
        # Same 2 files as wave-1/wave-2b.
        assert len(files) == 2
        assert "tests/demo/demo_fsm_sva.sv" in files
        assert "tests/demo/demo_fsm_bind.sv" in files
        # Cross-invariants attached at top level have no effect on a
        # single-region chart — they only fire when the chart has
        # regions (the cross_invariant collector still parses them
        # to surface errors, but the parallel-chart path is what
        # actually emits the chart-top SVA).
        chart = _simple_chart()
        chart["sos:cross_invariant"] = [{
            "id": "INV-S-CHART-Z",
            "antecedent": "region.left == L1",
            "consequent": "region.right == R1",
        }]
        files = transliterate_sva_bind.render_target(
            chart, {"chart_name": "demo"}
        )
        # Single-region charts ignore cross-invariants (no regions to
        # reference); the top-sva / top-bind files are NOT emitted.
        assert "tests/demo/demo_top_sva.sv" not in files
        assert "tests/demo/demo_top_bind.sv" not in files

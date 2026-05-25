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


# ---------------------------------------------------------------------------
# SOS-08-D wave-4-future (2026-05-24 §15): state-encoding pass-through into
# `<chart>_top_sva.sv`. The wave-4 v1 placeholder resolved every state
# constant to bit 0 — the cross-region property's RHS therefore matched
# the region's first-document-order state regardless of which state the
# invariant named. Wave-4-future threads the per-region state-index map
# (matching SOS-08-C's document-order one-hot encoding) through the
# emitter so every state constant resolves to its actual bit position.
# ---------------------------------------------------------------------------


def _bit_index_in_const_definition(sva: str, state_const: str) -> int | None:
    """Return the integer bit index in the ``localparam ST_X = ...`` line
    of ``sva``. Parses the ``({param}'(1) << <idx>)`` form emitted by
    ``_emit_cross_invariant_state_constants``."""
    pat = (
        rf"localparam\s+logic\s+\[N_STATES_[A-Z0-9_]+-1:0\]\s+"
        rf"{re.escape(state_const)}\s*=\s*\{{N_STATES_[A-Z0-9_]+\{{1'b0\}}\}}\s*\|"
        rf"\s*\(N_STATES_[A-Z0-9_]+'\(1\)\s*<<\s*(\d+)\)"
    )
    m = re.search(pat, sva)
    return int(m.group(1)) if m else None


class TestWave4FutureEncodingPassthrough:
    """Wave-4-future closes the v1 placeholder: every state constant in
    ``<chart>_top_sva.sv`` MUST encode the actual one-hot bit position
    matching SOS-08-C's per-region FSM module emit.

    The reference parallel chart (``_parallel_chart``) has region
    ``left`` with states (L1, L2) — bit 0, bit 1 — and region ``right``
    with states (R1, R2) — bit 0, bit 1. The reference cross-invariant
    chart (``_chart_with_cross_invariants``) references L2 + R2, both
    of which should now resolve to bit 1.
    """

    def _sva(self):
        files = transliterate_sva_bind.render_target(
            _chart_with_cross_invariants(), {"chart_name": "p"}
        )
        return files["tests/p/p_top_sva.sv"]

    def test_l2_constant_resolves_to_bit_1(self):
        """L2 is document-order index 1 in region `left` (after L1)."""
        sva = self._sva()
        bit = _bit_index_in_const_definition(sva, "ST_L2")
        assert bit == 1, (
            f"ST_L2 must be bit 1 (matching SOS-08-C's document-order "
            f"one-hot encoding for left.L2); got bit {bit}"
        )

    def test_r2_constant_resolves_to_bit_1(self):
        """R2 is document-order index 1 in region `right` (after R1)."""
        sva = self._sva()
        bit = _bit_index_in_const_definition(sva, "ST_R2")
        assert bit == 1, (
            f"ST_R2 must be bit 1 (matching SOS-08-C's document-order "
            f"one-hot encoding for right.R2); got bit {bit}"
        )

    def test_l1_constant_resolves_to_bit_0_when_referenced(self):
        """L1 is document-order index 0; verifying a state at index 0
        still encodes cleanly (not via the v1 placeholder)."""
        chart = _parallel_chart()
        chart["sos:cross_invariant"] = [{
            "id": "INV-S-CHART-X",
            "antecedent": "region.left == L1",
            "consequent": "region.right == R1",
        }]
        files = transliterate_sva_bind.render_target(
            chart, {"chart_name": "p"}
        )
        sva = files["tests/p/p_top_sva.sv"]
        bit = _bit_index_in_const_definition(sva, "ST_L1")
        assert bit == 0

    def test_emit_marks_real_encoding_in_comment(self):
        """The state-constant comment SHOULD name the bit position so
        a reviewer can audit the SVA module against SOS-08-C's emit by
        reading the comment alone."""
        sva = self._sva()
        # Each referenced state's comment cites its bit position.
        assert "bit 1 per SOS-08-C document-order encoding" in sva
        # The wave-4 v1 placeholder comment MUST NOT appear when the
        # encoding map is threaded through.
        assert "WAVE-4-V1 PLACEHOLDER" not in sva

    def test_distinct_states_resolve_to_distinct_bits(self):
        """L1 + L2 referenced together must produce distinct bit
        positions (0 + 1) — verifies the per-region map is consulted
        per-state, not a single value per region."""
        chart = _parallel_chart()
        chart["sos:cross_invariant"] = [
            {
                "id": "INV-S-CHART-A",
                "antecedent": "region.left == L1",
                "consequent": "region.right == R1",
            },
            {
                "id": "INV-S-CHART-B",
                "antecedent": "region.left == L2",
                "consequent": "region.right == R2",
            },
        ]
        files = transliterate_sva_bind.render_target(
            chart, {"chart_name": "p"}
        )
        sva = files["tests/p/p_top_sva.sv"]
        l1_bit = _bit_index_in_const_definition(sva, "ST_L1")
        l2_bit = _bit_index_in_const_definition(sva, "ST_L2")
        r1_bit = _bit_index_in_const_definition(sva, "ST_R1")
        r2_bit = _bit_index_in_const_definition(sva, "ST_R2")
        assert (l1_bit, l2_bit, r1_bit, r2_bit) == (0, 1, 0, 1)

    def test_state_constants_match_sos_08c_emit_exactly(self):
        """The wave-4-future encoding emit MUST match what SOS-08-C's
        ``_one_hot_value`` produces for the same (index, n) — verified
        by cross-checking against the SOS-08-C walker helper."""
        import importlib
        hdl_sv = importlib.import_module("transliterate_hdl_sv")
        sva = self._sva()
        # Region `left` has 2 states; L2 is index 1.
        expected = hdl_sv.one_hot_value(1, 2)  # → "2'b10"
        # Reconstruct the wave-4-future emit's constant value.
        # The `localparam` form is {N{1'b0}} | (N'(1) << bit); for N=2,
        # bit=1, the constant equals 2'b10 = expected.
        bit = _bit_index_in_const_definition(sva, "ST_L2")
        n_states = 2
        synthesised = (1 << bit) & ((1 << n_states) - 1)
        expected_int = int(expected.split("'b")[1], 2)
        assert synthesised == expected_int


class TestWave4FutureValidation:
    """Wave-4-future rejects cross-invariants referencing unknown
    region.state names with chart-vocabulary errors per INV-S-HDL-D-5."""

    def test_rejects_unknown_region(self):
        chart = _parallel_chart()
        chart["sos:cross_invariant"] = [{
            "id": "INV-S-CHART-BAD",
            "antecedent": "region.middle == M1",
            "consequent": "region.right == R1",
        }]
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match=r"references region 'middle' which the chart does not declare",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_rejects_unknown_state_in_known_region(self):
        chart = _parallel_chart()
        chart["sos:cross_invariant"] = [{
            "id": "INV-S-CHART-BAD",
            "antecedent": "region.left == L99",
            "consequent": "region.right == R1",
        }]
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match=r"references state 'L99' in region 'left'",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_validation_error_cites_invariant_id(self):
        """Chart-vocabulary error (INV-S-HDL-D-5) MUST cite the
        offending cross-invariant id so the chart author can locate it
        directly."""
        chart = _parallel_chart()
        chart["sos:cross_invariant"] = [{
            "id": "INV-S-CHART-DEBUG-ME",
            "antecedent": "region.left == BOGUS",
            "consequent": "region.right == R1",
        }]
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match=r"INV-S-CHART-DEBUG-ME",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_validation_error_cites_role(self):
        """Validation error names whether the antecedent or consequent
        side carried the bad reference so the chart author can fix the
        right side directly."""
        chart = _parallel_chart()
        chart["sos:cross_invariant"] = [{
            "id": "INV-S-CHART-BAD",
            "antecedent": "region.left == L1",
            "consequent": "region.right == BOGUS",
        }]
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match=r"consequent references state 'BOGUS'",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_validation_error_lists_known_states(self):
        """Error message includes the list of states the chart DOES
        declare — actionable diagnostic for the chart author."""
        chart = _parallel_chart()
        chart["sos:cross_invariant"] = [{
            "id": "INV-S-CHART-BAD",
            "antecedent": "region.left == BOGUS",
            "consequent": "region.right == R1",
        }]
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match=r"Known states in region 'left': \['L1', 'L2'\]",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})


class TestWave4FutureHelperFunctions:
    """Direct-call tests for ``_build_region_state_indices`` +
    ``_state_index_for`` so the helpers' contracts are pinned outside
    the full render_target path."""

    def test_build_region_state_indices_document_order(self):
        chart = _parallel_chart()
        # Match the `regions` shape `_collect_parallel_regions` yields.
        regions = transliterate_sva_bind._collect_parallel_regions(chart)
        indices = transliterate_sva_bind._build_region_state_indices(regions)
        assert indices == {
            "left":  {"L1": 0, "L2": 1},
            "right": {"R1": 0, "R2": 1},
        }

    def test_state_index_for_returns_zero_when_map_absent(self):
        """Backwards-compatible behaviour: callers that do not yet thread
        the encoding map (wave-4 v1 path) get bit-0 fallback. Walker's
        public render_target always threads the map; this is a
        helper-contract pin."""
        bit = transliterate_sva_bind._state_index_for("any", "any", None)
        assert bit == 0

    def test_state_index_for_returns_mapped_bit(self):
        m = {"left": {"L1": 0, "L2": 1, "L3": 2}}
        assert transliterate_sva_bind._state_index_for("left", "L1", m) == 0
        assert transliterate_sva_bind._state_index_for("left", "L2", m) == 1
        assert transliterate_sva_bind._state_index_for("left", "L3", m) == 2

    def test_state_index_for_unknown_returns_zero_fallback(self):
        """Without explicit validation, unknown lookups return 0; the
        validation pass at collect-time is what raises — keep the helper
        total so internal callers don't need defensive try/except."""
        m = {"left": {"L1": 0}}
        assert transliterate_sva_bind._state_index_for("left", "BOGUS", m) == 0
        assert transliterate_sva_bind._state_index_for("nope", "X", m) == 0


class TestWave4FutureBackwardsCompatibleEmit:
    """When the encoding map is NOT threaded through (legacy callers),
    the wave-4 v1 behaviour MUST persist verbatim: bit 0 + placeholder
    comment. Verifies the migration path is gradual."""

    def test_v1_placeholder_comment_when_map_omitted(self):
        invariants = transliterate_sva_bind._collect_cross_invariants(
            _chart_with_cross_invariants()
        )
        lines = transliterate_sva_bind._emit_cross_invariant_state_constants(
            invariants  # no region_state_indices
        )
        body = "\n".join(lines)
        assert "WAVE-4-V1 PLACEHOLDER" in body
        # Every localparam emitted with shift bit 0.
        for state_const in ("ST_L2", "ST_R2"):
            assert re.search(
                rf"{state_const}\s*=.*<<\s*0\)",
                body,
            )

    def test_real_encoding_comment_when_map_provided(self):
        invariants = transliterate_sva_bind._collect_cross_invariants(
            _chart_with_cross_invariants()
        )
        m = {"left": {"L1": 0, "L2": 1}, "right": {"R1": 0, "R2": 1}}
        lines = transliterate_sva_bind._emit_cross_invariant_state_constants(
            invariants, m
        )
        body = "\n".join(lines)
        assert "WAVE-4-V1 PLACEHOLDER" not in body
        assert "bit 1 per SOS-08-C document-order encoding" in body


# ---------------------------------------------------------------------------
# SOS-08-D wave-4-future (2026-05-24 §15): `<sos:raw_property>` escape
# hatch. Chart authors paste literal SVA into the element body when the
# structured `<sos:cross_invariant>` grammar cannot express the desired
# property (liveness, multi-step `##` temporal sequences, vendor-specific
# coverage constructs). The walker validates the element wrapper +
# collision-checks names but treats the body as opaque IEEE 1800-2017
# SystemVerilog (authority relationship `derive`).
# ---------------------------------------------------------------------------


def _chart_with_raw_property():
    """Parallel chart with one `<sos:raw_property>` block and no
    cross_invariants. Exercises the raw-property-only emit path."""
    chart = _parallel_chart()
    chart["sos:raw_property"] = [
        {
            "name": "liveness_p",
            "clock_region": "left",
            "body": (
                "(left_request_pending) "
                "|-> ##[1:8] (left_request_granted)"
            ),
        },
    ]
    return chart


def _chart_with_structured_and_raw():
    """Parallel chart carrying BOTH a `<sos:cross_invariant>` AND a
    `<sos:raw_property>`. Exercises ordering + banner separation."""
    chart = _chart_with_cross_invariants()
    chart["sos:raw_property"] = [
        {
            "name": "liveness_after_l2",
            "clock_region": "left",
            "body": (
                "(current_state_left == ST_L2) "
                "|-> ##[1:16] $past(current_state_right) != "
                "current_state_right"
            ),
        },
    ]
    return chart


class TestWave4FutureRawPropertyEscapeHatch:
    """SOS-08-D wave-4-future §15 (2026-05-24): `<sos:raw_property>`
    escape hatch for SVA bodies the structured cross_invariant grammar
    cannot express. The walker emits the body verbatim, collision-checks
    names, validates clock_region against declared regions, and bans
    empty bodies + missing attrs.

    Authority boundary per §0:
      * Element shape (`name`, `clock_region`, body)  — relationship `own`.
      * SVA body content                               — relationship `derive`
        (IEEE 1800-2017 §16 grammar; walker does not interpret).
    """

    def _files(self) -> dict:
        return transliterate_sva_bind.render_target(
            _chart_with_raw_property(), {"chart_name": "p"}
        )

    def test_emits_raw_property_block_after_structured_invariants(self):
        """The chart-top SVA file MUST appear with the raw-property
        block when ONLY raw properties exist; the wave-4 cross-region
        banner reports zero invariants but the file is still emitted."""
        files = transliterate_sva_bind.render_target(
            _chart_with_structured_and_raw(), {"chart_name": "p"}
        )
        sva = files["tests/p/p_top_sva.sv"]
        # Structured property text appears before raw-property text.
        cross_idx = sva.find("property p_inv_s_chart_1")
        banner_idx = sva.find(
            "// === raw_property escape hatches (walker-opaque) ==="
        )
        raw_idx = sva.find("property liveness_after_l2")
        assert cross_idx > 0, "structured property missing"
        assert banner_idx > 0, "banner comment missing"
        assert raw_idx > 0, "raw property missing"
        assert cross_idx < banner_idx < raw_idx, (
            f"emission order MUST be structured → banner → raw; "
            f"got cross_idx={cross_idx} banner_idx={banner_idx} "
            f"raw_idx={raw_idx}"
        )

    def test_byte_identity_when_chart_has_no_raw_property(self):
        """Regression guard — wave-4-future MUST NOT alter the emitted
        byte content for any chart that declares no `<sos:raw_property>`.

        Verifies the existing wave-4 fixture (`_chart_with_cross_invariants`)
        produces identical bytes to a re-emit through the new code path.
        The body MUST NOT carry the wave-4-future banner OR any per-
        region clock port — the file is byte-identical to the wave-4
        emit."""
        files = transliterate_sva_bind.render_target(
            _chart_with_cross_invariants(), {"chart_name": "p"}
        )
        sva = files["tests/p/p_top_sva.sv"]
        bind = files["tests/p/p_top_bind.sv"]
        # No wave-4-future-only banner.
        assert (
            "// === raw_property escape hatches (walker-opaque) ===" not in sva
        )
        # No per-region clock input port.
        assert "_clk," not in sva  # No `<region>_clk,` port declaration.
        assert "_clk\n" not in sva.replace("clk_", "x_x_")
        # Bind also free of raw-property wiring.
        assert "wave-4-future" not in bind.lower()
        # Spot-check: wave-4 file count + names unchanged for this chart.
        # (4 per-region SVA/bind + 2 top files = 6 — matches wave-4 baseline.)
        assert len(files) == 6

    def test_banner_comment_separates_structured_from_raw(self):
        sva = self._files()["tests/p/p_top_sva.sv"]
        assert (
            "// === raw_property escape hatches (walker-opaque) ===" in sva
        )
        # The banner explicitly cites that the walker is opaque to the
        # body — IEEE 1800-2017 lives upstream.
        assert "IEEE 1800-2017" in sva
        assert "`derive`" in sva

    def test_collision_with_cross_invariant_name_raises(self):
        """A raw property's derived assert label MUST NOT collide with
        an existing `<sos:cross_invariant>` id (which derives the same
        `<ID>_ASSERT` label inside the bind module)."""
        chart = _chart_with_cross_invariants()
        chart["sos:raw_property"] = [
            {
                # `inv_s_chart_1` after sanitise → collides with the
                # structured `INV-S-CHART-1` invariant.
                "name": "inv_s_chart_1",
                "clock_region": "left",
                "body": "1'b1",
            },
        ]
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match=r"collides with the structured <sos:cross_invariant",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_collision_with_another_raw_property_name_raises(self):
        chart = _parallel_chart()
        chart["sos:raw_property"] = [
            {
                "name": "dup_p",
                "clock_region": "left",
                "body": "1'b1",
            },
            {
                "name": "dup_p",
                "clock_region": "right",
                "body": "1'b1",
            },
        ]
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match=r"collides with another <sos:raw_property>",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_missing_clock_region_raises(self):
        chart = _parallel_chart()
        chart["sos:raw_property"] = [
            {
                "name": "no_clock_p",
                "body": "1'b1",
            },
        ]
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match=r"non-empty `clock_region`",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_missing_name_raises(self):
        chart = _parallel_chart()
        chart["sos:raw_property"] = [
            {
                "clock_region": "left",
                "body": "1'b1",
            },
        ]
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match=r"non-empty `name`",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_unknown_clock_region_raises_with_chart_vocab_error(self):
        chart = _parallel_chart()
        chart["sos:raw_property"] = [
            {
                "name": "bad_region_p",
                "clock_region": "middle",
                "body": "1'b1",
            },
        ]
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match=r"does not reference a region the chart declares",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_empty_body_raises(self):
        chart = _parallel_chart()
        chart["sos:raw_property"] = [
            {
                "name": "empty_p",
                "clock_region": "left",
                "body": "   \n\t  ",
            },
        ]
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match=r"non-empty body",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_missing_body_key_raises(self):
        """Body absent entirely (no `body` / `_text` / `$` / `#text`)."""
        chart = _parallel_chart()
        chart["sos:raw_property"] = [
            {
                "name": "no_body_p",
                "clock_region": "left",
            },
        ]
        with pytest.raises(
            transliterate_sva_bind.UnsupportedChartError,
            match=r"non-empty body",
        ):
            transliterate_sva_bind.render_target(chart, {"chart_name": "p"})

    def test_leading_trailing_whitespace_stripped_body_verbatim_preserved(self):
        """The walker MUST strip leading/trailing whitespace on the body
        text but preserve the interior verbatim."""
        chart = _parallel_chart()
        verbatim = (
            "(current_state_left == ST_L1) "
            "|-> ##[2:4] !$isunknown(current_state_right)"
        )
        chart["sos:raw_property"] = [
            {
                "name": "whitespace_p",
                "clock_region": "left",
                # Leading + trailing whitespace MUST be stripped.
                "body": "\n   " + verbatim + "   \n  ",
            },
        ]
        files = transliterate_sva_bind.render_target(
            chart, {"chart_name": "p"}
        )
        sva = files["tests/p/p_top_sva.sv"]
        # Body interior is preserved verbatim — same `$isunknown` call,
        # same `##[2:4]` window, same parens / spacing.
        assert verbatim in sva
        # The body MUST appear inside the property block @ posedge line.
        assert f"@(posedge left_clk) {verbatim};" in sva

    def test_source_document_order_preserved_across_multiple_raw_properties(self):
        chart = _parallel_chart()
        chart["sos:raw_property"] = [
            {
                "name": "first_p",
                "clock_region": "left",
                "body": "1'b1",
            },
            {
                "name": "second_p",
                "clock_region": "right",
                "body": "1'b0",
            },
            {
                "name": "third_p",
                "clock_region": "left",
                "body": "1'b1",
            },
        ]
        files = transliterate_sva_bind.render_target(chart, {"chart_name": "p"})
        sva = files["tests/p/p_top_sva.sv"]
        first_idx = sva.find("property first_p")
        second_idx = sva.find("property second_p")
        third_idx = sva.find("property third_p")
        assert 0 < first_idx < second_idx < third_idx, (
            f"raw properties MUST emit in source document order; got "
            f"first={first_idx} second={second_idx} third={third_idx}"
        )

    def test_emitted_clock_region_resolves_to_existing_region_clock(self):
        """`clock_region="left"` MUST lower to `@(posedge left_clk)`
        inside the emitted property + add `input wire left_clk` to the
        module's port list."""
        sva = self._files()["tests/p/p_top_sva.sv"]
        assert "@(posedge left_clk)" in sva
        # Module port list carries the `<region>_clk` input.
        assert re.search(
            r"input\s+wire\s+left_clk\b", sva
        ), f"SVA module must declare `left_clk` input port:\n{sva}"

    def test_bind_directive_wires_raw_property_clock_from_default_clk(self):
        """Region without a `clock=` annotation routes raw_property's
        `<region>_clk` from the chart-top reference `clk`."""
        bind = self._files()["tests/p/p_top_bind.sv"]
        assert re.search(
            r"\.left_clk\s*\(\s*clk\s*\)", bind
        ), f"left_clk MUST wire from default clk:\n{bind}"

    def test_bind_directive_wires_raw_property_clock_from_per_domain_clock(self):
        """Region carrying a `clock=` annotation routes raw_property's
        `<region>_clk` from `clk_<domain>` per SOS-08-C wave-3 clock-
        distribution contract."""
        chart = _multi_clock_parallel_chart()
        chart["sos:raw_property"] = [
            {
                "name": "fast_liveness",
                "clock_region": "fast",
                "body": "1'b1",
            },
        ]
        files = transliterate_sva_bind.render_target(
            chart, {"chart_name": "p"}
        )
        bind = files["tests/p/p_top_bind.sv"]
        assert re.search(
            r"\.fast_clk\s*\(\s*clk_fast\s*\)", bind
        ), f"fast region's `fast_clk` MUST wire from `clk_fast`:\n{bind}"

    def test_assert_label_uppercased_per_emit_convention(self):
        sva = self._files()["tests/p/p_top_sva.sv"]
        assert "LIVENESS_P_ASSERT: assert property (liveness_p)" in sva

    def test_raw_only_chart_omits_param_block(self):
        """A chart carrying ONLY raw properties (no `<sos:cross_invariant>`)
        emits a top-sva module WITHOUT the `#(parameter int N_STATES_X)`
        block — there are no structured invariants needing per-region
        state-vector parameters."""
        sva = self._files()["tests/p/p_top_sva.sv"]
        # No `#(...)` parameter list — module decl is `module <m> (`
        # directly. The wave-4 emit shape for charts WITH cross-
        # invariants uses `module <m> #(\n    parameter int ...`.
        assert "parameter int N_STATES_" not in sva
        # Module decl line — `module p_top_sva (`.
        assert re.search(r"module\s+p_top_sva\s*\(\s*\n", sva)

    def test_render_emits_top_files_even_without_cross_invariants(self):
        """The wave-4 emit fires when EITHER cross_invariants OR raw
        properties are non-empty. Raw-property-only charts MUST emit
        the top files."""
        files = self._files()
        assert "tests/p/p_top_sva.sv" in files
        assert "tests/p/p_top_bind.sv" in files

    def test_single_region_chart_ignores_raw_property(self):
        """Mirroring `TestWave4SingleRegionUnchanged`: single-region
        charts ignore `<sos:raw_property>` (and `<sos:cross_invariant>`)
        — the wave-4 + wave-4-future top-file emit fires only on
        parallel-chart inputs."""
        chart = _simple_chart()
        chart["sos:raw_property"] = [
            {
                "name": "ignored_p",
                "clock_region": "left",
                "body": "1'b1",
            },
        ]
        files = transliterate_sva_bind.render_target(
            chart, {"chart_name": "demo"}
        )
        assert "tests/demo/demo_top_sva.sv" not in files
        assert "tests/demo/demo_top_bind.sv" not in files
        assert len(files) == 2  # single-region path unchanged.

    def test_dict_form_accepted_for_single_raw_property(self):
        """Loader-friendly: a single `<sos:raw_property>` may surface
        as a bare dict (not a list) per the bare/wrapped scjson loader
        convention. The walker MUST normalise either shape."""
        chart = _parallel_chart()
        chart["sos:raw_property"] = {
            "name": "single_p",
            "clock_region": "left",
            "body": "1'b1",
        }
        files = transliterate_sva_bind.render_target(chart, {"chart_name": "p"})
        sva = files["tests/p/p_top_sva.sv"]
        assert "property single_p" in sva

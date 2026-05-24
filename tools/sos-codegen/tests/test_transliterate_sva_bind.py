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


def test_assertion_module_has_clk_rst_state_q_ports():
    src = _sva_source(_simple_chart())
    assert "module simple_fsm_sva" in src
    assert re.search(r"input\s+wire\s+clk\b", src)
    assert re.search(r"input\s+wire\s+rst\b", src)
    assert re.search(r"input\s+wire\s+\[2:0\]\s+state_q\b", src)


def test_one_hot_assertion_present():
    """INV-D-1: assertion checks ``$countones(state_q) <= 1`` on every
    posedge clk (one-hot encoding invariant)."""
    src = _sva_source(_simple_chart())
    assert "$countones(state_q) <= 1" in src
    assert "a_one_hot" in src
    assert "SOS-08-D INV-D-1" in src


def test_reset_initial_assertion_present():
    """INV-D-2: ``rst |=> state_q == ST_<initial>``. Chart initial='A'
    → assertion targets ST_A."""
    src = _sva_source(_simple_chart())
    assert "a_reset_initial" in src
    # Look for the |=> form with the initial state constant.
    assert re.search(r"rst\s*\|=>\s*\(state_q\s*==\s*ST_A\)", src), src
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
    # Compiled antecedent: (state_q == ST_A) && (data_a_q == 1)
    # The exact spacing / parens depend on hdl_common.emit_guard_expr;
    # accept any whitespace and parens around the comparison.
    assert "data_a_q" in src, src
    assert re.search(
        r"\(state_q\s*==\s*ST_A\)\s*&&\s*\(.*data_a_q.*==.*1.*\)",
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


def test_bind_directive_wires_dut_current_state_to_sva_state_q():
    """The assertion module's ``state_q`` input is driven from the
    chart-FSM module's ``current_state`` output (SOS-08-C §6.2)."""
    src = _bind_source(_simple_chart())
    assert re.search(
        r"\.state_q\s*\(\s*current_state\s*\)",
        src,
    ), src


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


def test_parallel_charts_rejected_at_v1():
    """Wave-1 scaffold; parallel chart bind files land in wave-2."""
    chart = _parallel_chart()
    with pytest.raises(transliterate_sva_bind.UnsupportedChartError) as excinfo:
        transliterate_sva_bind.render_target(chart, {"chart_name": "p"})
    msg = str(excinfo.value)
    assert "wave-1" in msg.lower() or "wave-2" in msg.lower()


def test_chart_ir_must_be_dict():
    with pytest.raises(transliterate_sva_bind.UnsupportedChartError):
        transliterate_sva_bind.render_target(None, {"chart_name": "x"})

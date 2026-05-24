"""Unit tests for `transliterate_cocotb.render_target` (SOS-08-D wave-1).

@spec  SOS-08-D-CONCEPTS.md §5 (frozen decisions), §6 (per-artifact
       contracts), §15 (ratified 2026-05-23 — PCDN-D-001..007 resolved)
@spec  SOS-08-C-CONCEPTS.md §5.1 (one-hot encoding default; cross-
       dialect determinism — `_STATE_ENCODING` mirrors the synthesised
       state register's bit pattern)
@spec  SOS-03-CONCEPTS.md §7.1 (vector format reference)
@spec  PCDN-D-001 (Verilator default), PCDN-D-002 (JUnit XML emission),
       PCDN-D-003 (per-vector test isolation), PCDN-D-004 (full SVA
       bind default), PCDN-D-005 (Python 3.10+), PCDN-D-006 (one
       test_<dut>.py + shared helpers), PCDN-D-007 (Makefile + pytest.ini)
@spec  INV-S-HDL-D-1..6 (cross-artifact invariants)

The wave-1 scaffold consumes the raw scjson dict shape — the same
shape SOS-08-C walkers (`transliterate_hdl_vhdl`, `transliterate_hdl_sv`)
consume. The tests build the same dict shape inline so the suite has
no cross-agent fixture dependency.

Tests do NOT execute pytest themselves (per the orchestrator's "static
deliverable; do NOT run pytest" directive). They define assertions for
the wave-1 acceptance gates that the integration-pass agent runs.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

# Bootstrap path so the sibling module is importable when pytest runs
# from the repo root. Mirrors the pattern in
# tests/test_transliterate_hdl_vhdl.py.
_TOOL_DIR = Path(__file__).resolve().parent.parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))

from transliterate_cocotb import (  # noqa: E402
    UnsupportedChartError,
    dut_module_name,
    one_hot_encoding,
    render_target,
    slugify_vector_id,
    state_constant_name,
)


# ---------------------------------------------------------------------------
# Inline scjson-dict builders — mirror the SOS-08-C VHDL/SV test fixtures.
# ---------------------------------------------------------------------------


def _state(state_id, *, transitions=None):
    out = {"id": state_id}
    if transitions is not None:
        out["transition"] = transitions
    return out


def _simple_chart():
    """A 3-state chart: idle → working → done. No datamodel."""
    return {
        "initial": "idle",
        "state": [
            _state("idle", transitions=[{"event": "go", "target": "working"}]),
            _state("working", transitions=[{"event": "finish", "target": "done"}]),
            _state("done"),
        ],
    }


def _four_state_chart():
    """4-state chart for one-hot encoding verification."""
    return {
        "initial": "a",
        "state": [
            _state("a", transitions=[{"target": "b"}]),
            _state("b", transitions=[{"target": "c"}]),
            _state("c", transitions=[{"target": "d"}]),
            _state("d"),
        ],
    }


def _chart_with_parallel():
    """Wave-1 reject path — parallel charts land in wave-2."""
    return {
        "initial": "p",
        "parallel": [
            {
                "id": "p",
                "state": [
                    {
                        "id": "left",
                        "initial": "l_idle",
                        "state": [_state("l_idle"), _state("l_active")],
                    },
                    {
                        "id": "right",
                        "initial": "r_idle",
                        "state": [_state("r_idle"), _state("r_active")],
                    },
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Test 1 — Per-artifact directory layout (PCDN-D-006, PCDN-D-007, §6.1).
# ---------------------------------------------------------------------------


def test_render_emits_expected_files():
    """Single-region chart → 5 emitter artifacts + 1 scaffold vector.

    Per SOS-08-D §6.1 emit directory layout + PCDN-D-006 / §5.6
    (one test_<dut>.py + shared helpers) + PCDN-D-007 (Makefile +
    pytest.ini both emitted):

      tests/<chart>/
        test_<chart>_fsm.py
        _cocotb_helpers.py
        Makefile
        pytest.ini
        README.md
        vectors/<vector_id>.json   # scaffold so wave-1 dir is runnable
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})

    # The five normative emitter artifacts.
    assert "test_demo_fsm.py" in files
    assert "_cocotb_helpers.py" in files
    assert "Makefile" in files
    assert "pytest.ini" in files
    assert "README.md" in files

    # Plus one scaffold vector under vectors/ — the wave-1 default is
    # `000-reset` per the emitter's `_DEFAULT_SCAFFOLD_VECTOR` constant.
    assert "vectors/000-reset.json" in files
    assert len(files) == 6


def test_makefile_and_pytest_ini_both_emitted():
    """PCDN-SOS-08-D-007: emit BOTH a Makefile AND a pytest.ini.

    Two paths produce equivalent JUnit XML; users opt into either.
    The cost of doubling the emit by a fixed handful of lines is
    negligible vs. user-base fragmentation if only one path ships.
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    assert "Makefile" in files
    assert "pytest.ini" in files

    # Verilator default per PCDN-D-001 / §5.1 — `SIM ?= verilator` in
    # the Makefile.
    assert "SIM ?= verilator" in files["Makefile"]

    # Pytest.ini wires to the same test module.
    assert "test_demo_fsm.py" in files["pytest.ini"]


# ---------------------------------------------------------------------------
# Test 2 — One @cocotb.test per vector (PCDN-D-003, §5.5, INV-S-HDL-D-6).
# ---------------------------------------------------------------------------


def test_cocotb_test_has_one_test_per_vector():
    """Chart with N vector fixtures → N @cocotb.test() decorators in emit.

    Per PCDN-SOS-08-D-003 / §5.5 / INV-S-HDL-D-6 — per-vector test
    isolation is the default (unambiguous JUnit-XML attribution per
    INV-S-HDL-D-6; --group-by-region opt-in lands in wave-2).
    """
    vector_ids = ["000-reset", "0001-boundary", "0002-stress"]
    files = render_target(
        _simple_chart(),
        {"chart_name": "demo", "vector_ids": vector_ids},
    )
    test_module = files["test_demo_fsm.py"]

    # One @cocotb.test() decorator per vector. We count via AST so the
    # docstring's textual mention of `@cocotb.test()` doesn't inflate
    # the result.
    tree = ast.parse(test_module)
    decorated = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            for dec in node.decorator_list:
                # @cocotb.test()  → ast.Call on an ast.Attribute.
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    if dec.func.attr == "test":
                        decorated += 1
    assert decorated == len(vector_ids)

    # Test function names mirror the vector ids (slugified for Python
    # identifier safety).
    assert "test_vector_v000_reset" in test_module
    assert "test_vector_v0001_boundary" in test_module
    assert "test_vector_v0002_stress" in test_module

    # Each test loads its own vector file at runtime per INV-S-HDL-D-3
    # (vector-IR read-only at emitter boundary; never embedded).
    for vid in vector_ids:
        assert f'load_vector(_VECTORS_DIR / "{vid}.json")' in test_module

    # And the emitter writes one scaffold vector per bound id.
    for vid in vector_ids:
        assert f"vectors/{vid}.json" in files


# ---------------------------------------------------------------------------
# Test 3 — State encoding matches SOS-08-C one-hot (INV-S-HDL-C-1).
# ---------------------------------------------------------------------------


def test_state_encoding_matches_one_hot():
    """Emitted state map mirrors SOS-08-C's one-hot encoding.

    Per SOS-08-C §5.1 / PCDN-002 / INV-S-HDL-C-1 (deterministic
    emission extended to the test harness): state 0 (document order
    first) → bit 0 → integer 1; state k → integer 1 << k. The
    integer values match the synthesised state register exactly so
    `dut.current_state.value` equality holds without re-decoding.
    """
    files = render_target(_four_state_chart(), {"chart_name": "fourstates"})
    helpers = files["_cocotb_helpers.py"]

    # The embedded encoding map declares each state with its one-hot
    # binary literal. State 0 → 0b0001, state 1 → 0b0010, etc.
    assert "'a': 0b0001" in helpers
    assert "'b': 0b0010" in helpers
    assert "'c': 0b0100" in helpers
    assert "'d': 0b1000" in helpers

    # Public re-export mirrors the embedded values for cross-dialect
    # determinism checks.
    enc = one_hot_encoding(["a", "b", "c", "d"])
    assert enc == {"a": 1, "b": 2, "c": 4, "d": 8}


def test_state_constant_name_mirrors_sos_08_c_convention():
    """`ST_<UPPER>` convention mirrors both VHDL + SV walkers so the
    cocotb test can grep / reference the same state constant names.
    """
    assert state_constant_name("idle") == "ST_IDLE"
    assert state_constant_name("active") == "ST_ACTIVE"
    assert state_constant_name("foo-bar") == "ST_FOO_BAR"


def test_dut_module_name_uses_chart_fsm_convention():
    """DUT default is `<chart>_fsm` per SOS-08-C single-region
    convention; override via `config.dut_module` for vendor-shim
    variants per SOS-08-A §5.3."""
    assert dut_module_name("demo") == "demo_fsm"
    assert dut_module_name("RTOS-Kernel") == "rtos_kernel_fsm"


# ---------------------------------------------------------------------------
# Test 4 — Chart-vocabulary failure message (§6.6, INV-S-HDL-D-5).
# ---------------------------------------------------------------------------


def test_chart_vocabulary_failure_message():
    """The helper's failure string includes chart name + vector id +
    transition_id + expected chart-state ID per SOS-08-D §6.6.

    Per INV-S-HDL-D-5: every cocotb assertion failure MUST render
    with chart-vocabulary metadata. A failure that surfaces only RTL
    signal traces is a verification-emission bug, not a passing test.
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    helpers = files["_cocotb_helpers.py"]

    # AST-parse the helper module + extract the format_failure body
    # (the helper is dependency-free against cocotb so we can exec it).
    namespace: dict = {}
    exec(compile(helpers, "_cocotb_helpers.py", "exec"), namespace)

    format_failure = namespace["format_failure"]
    assert_state = namespace["assert_state"]

    # Caller passes a vector dict + a step dict; the returned string
    # carries chart name, vector id, step index, transition id,
    # expected state.
    vector = {"id": "000-reset", "name": "reset-baseline"}
    step = {"index": 3, "transition_id": "T42", "expected_state": "idle"}
    msg = format_failure(vector, step)
    assert "chart=demo" in msg
    assert "vector=000-reset" in msg
    assert "step=3" in msg
    assert "transition_id=T42" in msg
    assert "expected_state=idle" in msg

    # When no step is supplied, the helper still renders chart + vector
    # (used at boot-baseline + terminal-state assertions).
    msg_no_step = format_failure(vector)
    assert "chart=demo" in msg_no_step
    assert "vector=000-reset" in msg_no_step

    # And the assert_state helper raises AssertionError with the
    # chart-vocabulary message when its expected != observed.
    class _FakeSignal:
        value = 0b010  # state "working" in the simple chart

    class _FakeDut:
        current_state = _FakeSignal()

    # The simple chart's encoding: idle=0b001, working=0b010, done=0b100.
    # Asking for "idle" against current_state=0b010 must fail in chart
    # vocabulary.
    with pytest.raises(AssertionError) as exc_info:
        assert_state(_FakeDut(), "idle", format_failure(vector, step))
    err = str(exc_info.value)
    assert "chart-state mismatch" in err
    # Chart-vocabulary state id MUST appear (NOT the raw RTL bit
    # pattern alone — INV-S-HDL-D-5).
    assert "'idle'" in err
    # Chart-vocabulary context still flows through.
    assert "vector=000-reset" in err
    assert "transition_id=T42" in err
    # SOS-08-D §6.6 citation in failure message.
    assert "SOS-08-D §6.6" in err
    # And the observed RTL value is reported alongside as diagnostic
    # context (not as the failure surface).
    assert "0b" in err


def test_assert_state_passes_on_match():
    """Sanity gate: assert_state does NOT raise when the chart-state
    encoding matches the observed one-hot value."""
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    namespace: dict = {}
    exec(compile(files["_cocotb_helpers.py"], "_cocotb_helpers.py", "exec"), namespace)
    assert_state = namespace["assert_state"]

    class _FakeSignal:
        value = 0b001  # idle in the simple chart

    class _FakeDut:
        current_state = _FakeSignal()

    # Should not raise.
    assert_state(_FakeDut(), "idle", "chart=demo vector=000-reset")


# ---------------------------------------------------------------------------
# Test 5 — Parallel charts rejected at wave-1 (wave-2 lands them).
# ---------------------------------------------------------------------------


def test_parallel_charts_rejected_at_v1():
    """A parallel chart must surface UnsupportedChartError with a
    clear chart-vocabulary message naming the wave that lands the
    feature (per INV-S-HDL-D-5 / INV-S-HDL-5).
    """
    with pytest.raises(UnsupportedChartError) as exc_info:
        render_target(_chart_with_parallel(), {"chart_name": "parallels"})
    msg = str(exc_info.value)
    assert "wave-1" in msg
    # The rejection MUST cite the landing wave so chart authors know
    # when to expect support.
    assert "wave-2" in msg
    # And cite the spec doc per the chart-vocabulary doctrine.
    assert "SOS-08-D" in msg


def test_non_dict_chart_ir_rejected():
    """Per INV-S-HDL-D-3 the emitter's input boundary is a dict;
    anything else surfaces as UnsupportedChartError, not a generic
    TypeError. This keeps the CLI's chart-vocabulary failure surface
    consistent."""
    with pytest.raises(UnsupportedChartError):
        render_target(["not", "a", "dict"], {"chart_name": "demo"})  # type: ignore[arg-type]


def test_empty_state_list_rejected():
    """A chart with no <state> children is rejected with a
    chart-vocabulary message naming the wave-1 contract."""
    with pytest.raises(UnsupportedChartError):
        render_target({"initial": "x", "state": []}, {"chart_name": "empty"})


# ---------------------------------------------------------------------------
# Test 6 — Python 3.10+ minimum pinned in README (PCDN-D-005, §5.3).
# ---------------------------------------------------------------------------


def test_python_3_10_pinned_in_readme():
    """The emitted README MUST state Python 3.10+ minimum per
    PCDN-SOS-08-D-005 / §5.3. Matches parent-repo pinning; future-
    proofs against cocotb 2.x adoption.
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    readme = files["README.md"]
    assert "Python 3.10" in readme
    # PCDN citation present so the version policy is traceable to a
    # ratified decision.
    assert "PCDN" in readme and "D-005" in readme


def test_readme_documents_simulator_selection():
    """Per PCDN-D-001 / §5.1: README documents simulator selection.

    Verilator is the primary default; Icarus + GHDL are secondary
    acceptance targets. INV-S-HDL-D-2 requires open-source-simulator
    coverage at v1.
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    readme = files["README.md"]
    assert "Verilator" in readme
    assert "Icarus" in readme
    assert "GHDL" in readme
    # Both invocation paths documented (PCDN-D-007).
    assert "make sim" in readme
    assert "pytest" in readme


# ---------------------------------------------------------------------------
# Test 7 — Emitted Python parses cleanly.
# ---------------------------------------------------------------------------


def test_emitted_test_module_parses():
    """Sanity gate: every emitted Python file MUST parse as Python.

    Per INV-S-HDL-C-1 the emit is deterministic; syntactic validity
    is the load-bearing prerequisite for the cocotb runtime to even
    consider executing the test.
    """
    files = render_target(_four_state_chart(), {"chart_name": "fourstates"})
    ast.parse(files["test_fourstates_fsm.py"])
    ast.parse(files["_cocotb_helpers.py"])


def test_emitted_scaffold_vector_is_valid_json():
    """The scaffold vector emitted alongside the test files MUST be
    parseable JSON so the wave-1 test runs end-to-end on a freshly-
    emitted directory.
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    payload = json.loads(files["vectors/000-reset.json"])
    # Scaffold carries minimal SOS-03 fields.
    assert payload["id"] == "000-reset"
    assert payload["expected_terminal_state"] == "initial" or \
           payload["expected_terminal_state"] == "idle"
    # Scaffold has no steps — it only verifies the reset baseline.
    assert payload["steps"] == []


def test_deterministic_emission():
    """Per INV-S-HDL-C-1 / INV-S-HDL-D-3 (extended): the same chart
    + config produces byte-identical output across calls. The emit
    has no time-, hostname-, or path-dependent content."""
    chart = _simple_chart()
    config = {"chart_name": "demo", "vector_ids": ["v1", "v2"]}
    files_a = render_target(chart, config)
    files_b = render_target(chart, config)
    assert files_a == files_b


# ---------------------------------------------------------------------------
# Test 8 — Vector id slugification (Python identifier safety).
# ---------------------------------------------------------------------------


def test_slugify_vector_id_handles_sos_03_shapes():
    """The slug helper produces Python-identifier-safe names from
    SOS-03 §6.3 vector id shapes.
    """
    # Plain digits-with-hyphen (the wave-1 default scaffold shape).
    assert slugify_vector_id("000-reset") == "v000_reset"
    # Full SOS-03 slug with multiple hyphens.
    assert slugify_vector_id("0007-two-tasks-same-prio") == "v0007_two_tasks_same_prio"
    # Mixed-case + non-identifier characters.
    assert slugify_vector_id("Higher Prio Preempts on sem.give") == \
           "higher_prio_preempts_on_sem_give"
    # Empty / unnamed.
    assert slugify_vector_id("") == "unnamed"


# ---------------------------------------------------------------------------
# Test 9 — Reset + clock setup (§6.2, INV-S-HDL-A-1).
# ---------------------------------------------------------------------------


def test_reset_and_clock_match_spec_defaults():
    """Per SOS-08-D §6.2 / INV-S-HDL-A-1: 10 ns clock period (100 MHz)
    and 5-cycle synchronous active-high reset are the defaults. The
    emitted test module embeds these as module-level constants so a
    bench operator can grep + adjust without re-running the codegen.
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    test_module = files["test_demo_fsm.py"]
    assert "_CLOCK_PERIOD_NS = 10" in test_module
    assert "_RESET_CYCLES = 5" in test_module
    # Clock is started via cocotb.start_soon(Clock(...)).
    assert "cocotb.start_soon(Clock(dut.clk" in test_module
    # Reset is asserted before being deasserted — SOS-08-A INV-S-HDL-A-1.
    assert "dut.rst.value = 1" in test_module
    assert "dut.rst.value = 0" in test_module


def test_clock_period_and_reset_cycles_overridable():
    """Bench operators with non-100MHz DUTs MAY override clock period
    + reset cycles via the config object. The wave-1 emitter honors
    both."""
    files = render_target(
        _simple_chart(),
        {"chart_name": "demo", "clock_period_ns": 20, "reset_cycles": 10},
    )
    test_module = files["test_demo_fsm.py"]
    assert "_CLOCK_PERIOD_NS = 20" in test_module
    assert "_RESET_CYCLES = 10" in test_module


# ---------------------------------------------------------------------------
# Test 10 — Spec citations present in emitted artifacts.
# ---------------------------------------------------------------------------


def test_emitted_artifacts_cite_sos_08_d():
    """Per the chart-vocabulary doctrine + spec-before-code lineage:
    every emitted artifact MUST cite SOS-08-D so a reviewer can trace
    the emission back to its phase doc without leaving the file.
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    for fname, body in files.items():
        if fname.startswith("vectors/"):
            # Vector files are author-replaceable; they don't need
            # spec citations.
            continue
        assert "SOS-08-D" in body, f"{fname} missing SOS-08-D citation"

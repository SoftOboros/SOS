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
    """Single-region chart → 7 emitter artifacts + 1 scaffold vector.

    Per SOS-08-D §6.1 emit directory layout + PCDN-D-006 / §5.6 (one
    test_<dut>.py + shared helpers) + PCDN-D-007 (Makefile +
    pytest.ini both emitted) + PCDN-D-002 (post_results.py JUnit
    post-processor — wave-2a) + SOS-08-G §15 wave-2b
    (post_annotations.py SVA fire merge) + PCDN-SOS-08-D-wave1-file-
    layout (2026-05-23 — every key prefixed with ``tests/<chart>/``):

      tests/<chart>/test_<chart>_fsm.py
      tests/<chart>/_cocotb_helpers.py
      tests/<chart>/Makefile
      tests/<chart>/pytest.ini
      tests/<chart>/README.md
      tests/<chart>/post_results.py            # wave-2a per §6.7
      tests/<chart>/post_annotations.py        # wave-2b SVA fire merge
      tests/<chart>/vectors/<vector_id>.json   # scaffold so dir runnable
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})

    # The seven normative emitter artifacts under tests/<chart>/.
    assert "tests/demo/test_demo_fsm.py" in files
    assert "tests/demo/_cocotb_helpers.py" in files
    assert "tests/demo/Makefile" in files
    assert "tests/demo/pytest.ini" in files
    assert "tests/demo/README.md" in files
    assert "tests/demo/post_results.py" in files
    assert "tests/demo/post_annotations.py" in files

    # Plus one scaffold vector under tests/<chart>/vectors/.
    assert "tests/demo/vectors/000-reset.json" in files
    assert len(files) == 8


def test_makefile_and_pytest_ini_both_emitted():
    """PCDN-SOS-08-D-007: emit BOTH a Makefile AND a pytest.ini.

    Two paths produce equivalent JUnit XML; users opt into either.
    The cost of doubling the emit by a fixed handful of lines is
    negligible vs. user-base fragmentation if only one path ships.
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    assert "tests/demo/Makefile" in files
    assert "tests/demo/pytest.ini" in files

    # Verilator default per PCDN-D-001 / §5.1 — `SIM ?= verilator` in
    # the Makefile.
    assert "SIM ?= verilator" in files["tests/demo/Makefile"]

    # Pytest.ini wires to the same test module.
    assert "test_demo_fsm.py" in files["tests/demo/pytest.ini"]


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
    test_module = files["tests/demo/test_demo_fsm.py"]

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

    # And the emitter writes one scaffold vector per bound id under
    # tests/<chart>/vectors/ per PCDN-SOS-08-D-wave1-file-layout.
    for vid in vector_ids:
        assert f"tests/demo/vectors/{vid}.json" in files


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
    helpers = files["tests/fourstates/_cocotb_helpers.py"]

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
    helpers = files["tests/demo/_cocotb_helpers.py"]

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
    exec(compile(files["tests/demo/_cocotb_helpers.py"], "_cocotb_helpers.py", "exec"), namespace)
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


def test_parallel_charts_accepted_at_wave_2c():
    """SOS-08-D wave-2c (2026-05-23 §15): parallel charts now produce
    a parallel-aware test scaffold. The wave-1 UnsupportedChartError
    rejection is lifted; the emitted test reads per-region observables
    via the chart-top wrapper.
    """
    files = render_target(_chart_with_parallel(), {"chart_name": "parallels"})

    # Standard emit set still present (six normative files + scaffold).
    assert "tests/parallels/test_parallels_fsm.py" in files
    assert "tests/parallels/_cocotb_helpers.py" in files

    # Per SOS-08-C §6.10 the chart-top wrapper exposes one
    # `current_state_<region>` output per region; the wave-2c test
    # body MUST read both `current_state_left` and `current_state_right`.
    test_src = files["tests/parallels/test_parallels_fsm.py"]
    assert "current_state_left" in test_src
    assert "current_state_right" in test_src

    # The emitted helpers module carries the per-region encoding maps.
    helpers_src = files["tests/parallels/_cocotb_helpers.py"]
    assert "_REGION_STATE_ENCODINGS" in helpers_src
    assert "_REGION_INITIAL_STATES" in helpers_src
    assert "assert_region_state" in helpers_src

    # `_HAS_PARALLEL = True` flag is set for parallel charts so
    # downstream tools (e.g. SOS-08-G annotation overlay readers)
    # can detect the parallel-chart provenance.
    assert "_HAS_PARALLEL: bool = True" in helpers_src


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
    readme = files["tests/demo/README.md"]
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
    readme = files["tests/demo/README.md"]
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
    ast.parse(files["tests/fourstates/test_fourstates_fsm.py"])
    ast.parse(files["tests/fourstates/_cocotb_helpers.py"])


def test_emitted_scaffold_vector_is_valid_json():
    """The scaffold vector emitted alongside the test files MUST be
    parseable JSON so the wave-1 test runs end-to-end on a freshly-
    emitted directory.
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    payload = json.loads(files["tests/demo/vectors/000-reset.json"])
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
    test_module = files["tests/demo/test_demo_fsm.py"]
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
    test_module = files["tests/demo/test_demo_fsm.py"]
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
        if "/vectors/" in fname or fname.startswith("vectors/"):
            # Vector files are author-replaceable; they don't need
            # spec citations.
            continue
        assert "SOS-08-D" in body, f"{fname} missing SOS-08-D citation"


# ---------------------------------------------------------------------------
# Test 11 — SOS-08-G AnnotationWriter (waveform annotation emission).
#
# @spec  SOS-08-G-CONCEPTS.md §5.2 (overlay schema), §5.6 (one file
#        per test run per PCDN-G-003), §5.7 (per-event default
#        granularity per PCDN-G-005), §15 (ratified 2026-05-23).
# @spec  PCDN-SOS-08-G-001 — first-line schema header
# @spec  PCDN-SOS-08-G-005 — per-event default; SOS_ANNOTATION_DENSITY
#        env var opts into cycle granularity.
# @spec  PCDN-SOS-08-G-006 — line-buffered flush.
# @spec  INV-S-HDL-G-2 — chart-vocabulary mandatory in overlay.
# @spec  INV-S-HDL-G-3 — schema-version header required.
# @spec  INV-S-HDL-G-5 — writer instrumented INSIDE @cocotb.test().
# ---------------------------------------------------------------------------


def _exec_helpers(files):
    """Exec the emitted `_cocotb_helpers.py` into a fresh namespace
    and return it. The module is dependency-free against cocotb so
    this works without a simulator runtime."""
    helpers = files["tests/demo/_cocotb_helpers.py"]
    namespace: dict = {}
    exec(compile(helpers, "_cocotb_helpers.py", "exec"), namespace)
    return namespace, helpers


def test_annotation_writer_emits_schema_header(tmp_path):
    """SOS-08-G §5.2 + PCDN-G-001 + INV-S-HDL-G-3: the emitted
    ``AnnotationWriter`` class carries the schema-version header
    matching the spec, and writes it as the first JSONL record on
    construction.

    The header MUST carry:
      - "schema": "sos-08-g/annotations"  (per §5.2 + PCDN-G-wave1-001)
      - "version": "1.0"
      - "chart_path_max_depth": 8 (mirrors SOS-12 depth-cap per
        PCDN-G-002)
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    ns, helpers_src = _exec_helpers(files)

    # The class exists in the emitted module.
    assert "AnnotationWriter" in ns, \
        "AnnotationWriter class missing from _cocotb_helpers.py emit"
    AnnotationWriter = ns["AnnotationWriter"]

    # Class-level _SCHEMA_HEADER matches the spec exactly.
    assert AnnotationWriter._SCHEMA_HEADER == {
        "_meta": {
            "schema": "sos-08-g/annotations",
            "version": "1.0",
            "chart_path_max_depth": 8,
        }
    }

    # Header source text appears in the emitted module (so a
    # source-level reviewer can grep for PCDN-G-001 / spec compliance).
    assert '"schema"' in helpers_src
    assert '"sos-08-g/annotations"' in helpers_src
    assert '"version"' in helpers_src
    assert '"1.0"' in helpers_src
    assert '"chart_path_max_depth"' in helpers_src

    # When instantiated, the writer's FIRST JSONL line MUST be the
    # schema header (INV-S-HDL-G-3 — files without the header are
    # non-conformant).
    writer = AnnotationWriter("smoke", output_dir=tmp_path)
    writer.close()
    first_line = (tmp_path / "smoke.annotations.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()[0]
    assert json.loads(first_line) == {
        "_meta": {
            "schema": "sos-08-g/annotations",
            "version": "1.0",
            "chart_path_max_depth": 8,
        }
    }


def test_test_body_uses_annotation_writer():
    """Per INV-S-HDL-G-5: the annotation writer MUST be instrumented
    INSIDE each @cocotb.test() body (not a post-process step). The
    emitted test module:
      - Imports ``AnnotationWriter`` from the helpers.
      - Instantiates an ``AnnotationWriter`` at test start.
      - Calls ``record_transition`` (per PCDN-G-005 event default).
      - Calls ``close()`` in a finally so the file is well-formed on
        both success and failure (PCDN-G-003 one-file-per-run).
    """
    files = render_target(
        _simple_chart(),
        {"chart_name": "demo", "vector_ids": ["000-reset", "0001-step"]},
    )
    test_module = files["tests/demo/test_demo_fsm.py"]

    # Import surfaces AnnotationWriter.
    assert "AnnotationWriter" in test_module, \
        "test module does not import AnnotationWriter"

    # Each @cocotb.test() body instantiates an AnnotationWriter and
    # calls record_transition + close. Count instantiations via AST.
    tree = ast.parse(test_module)
    instantiations = 0
    record_calls = 0
    close_calls = 0
    finally_blocks = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith(
            "test_vector_"
        ):
            # Walk the test body looking for AnnotationWriter(...) calls.
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                    if sub.func.id == "AnnotationWriter":
                        instantiations += 1
                if isinstance(sub, ast.Call) and isinstance(
                    sub.func, ast.Attribute
                ):
                    if sub.func.attr == "record_transition":
                        record_calls += 1
                    if sub.func.attr == "close":
                        close_calls += 1
                if isinstance(sub, ast.Try) and sub.finalbody:
                    finally_blocks += 1
    # 2 vectors → 2 @cocotb.test() bodies → 2 writer instantiations.
    assert instantiations == 2, (
        f"expected one AnnotationWriter() per test body, got {instantiations}"
    )
    # Each test body emits at least one record_transition (reset
    # baseline) — typically two (baseline + terminal). We just require
    # one-per-vector at minimum.
    assert record_calls >= 2, (
        f"expected record_transition calls in each test body, got {record_calls}"
    )
    # Each test body MUST close() the writer in finally (PCDN-G-003).
    assert close_calls >= 2, (
        f"expected writer.close() in each test body, got {close_calls}"
    )
    # And the close() lives in a `finally` (so failure paths still
    # flush the annotation file to disk).
    assert finally_blocks >= 2, (
        f"expected try/finally per test body, got {finally_blocks}"
    )


def test_annotation_density_env_var_respected(tmp_path, monkeypatch):
    """Per PCDN-SOS-08-G-005: per-event is the v1 default; per-cycle
    is the opt-in via ``SOS_ANNOTATION_DENSITY=cycle``. The helper
    module MUST reference the env var name so a future migration to
    a flag-driven configuration has a single grep target.
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    ns, helpers_src = _exec_helpers(files)

    # Env-var name appears literally in the emitted source.
    assert "SOS_ANNOTATION_DENSITY" in helpers_src

    AnnotationWriter = ns["AnnotationWriter"]

    # Default density (env var unset) is "event" per PCDN-G-005.
    monkeypatch.delenv("SOS_ANNOTATION_DENSITY", raising=False)
    w = AnnotationWriter("default_density", output_dir=tmp_path)
    try:
        assert w.density == "event"
    finally:
        w.close()

    # Setting the env var to "cycle" flips the writer's mode.
    monkeypatch.setenv("SOS_ANNOTATION_DENSITY", "cycle")
    w_cycle = AnnotationWriter("cycle_density", output_dir=tmp_path)
    try:
        assert w_cycle.density == "cycle"
    finally:
        w_cycle.close()

    # Unknown values fall back to "event" (defensive — opt-ins must
    # be explicit; typos do not silently change behaviour).
    monkeypatch.setenv("SOS_ANNOTATION_DENSITY", "garbage")
    w_unknown = AnnotationWriter("unknown_density", output_dir=tmp_path)
    try:
        assert w_unknown.density == "event"
    finally:
        w_unknown.close()


def test_annotation_record_carries_chart_vocabulary(tmp_path):
    """Per INV-S-HDL-G-2: every annotation record MUST carry the
    chart-vocabulary fields (`chart_state`, `transition_id`,
    `chart_path`). A record that surfaces only `cycle` + `signal`
    regresses to RTL-signal-level review.
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    ns, _ = _exec_helpers(files)
    AnnotationWriter = ns["AnnotationWriter"]

    w = AnnotationWriter("vocab", output_dir=tmp_path)
    w.record_transition(
        cycle=42,
        chart_state="working",
        transition_id="T_GO",
        chart_path=["working"],
        signal="dut.current_state",
    )
    w.close()

    lines = (tmp_path / "vocab.annotations.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    # Line 0 is the schema header (verified by the dedicated test);
    # line 1 is the transition record.
    record = json.loads(lines[1])
    # Six normative fields per §5.2 / INV-S-HDL-G-2.
    for field in ("cycle", "signal", "chart_state", "transition_id",
                  "chart_path", "region"):
        assert field in record, f"normative field {field!r} missing"
    assert record["cycle"] == 42
    assert record["chart_state"] == "working"
    assert record["transition_id"] == "T_GO"
    assert record["chart_path"] == ["working"]
    assert record["signal"] == "dut.current_state"


def test_annotation_writer_line_buffered(tmp_path):
    """Per PCDN-SOS-08-G-006: the writer's file handle is line-
    buffered (`buffering=1`) so every newline-terminated record
    reaches disk without per-record fsync overhead.

    We probe this by writing a record and then reading the file from
    a separate handle BEFORE closing the writer — line-buffered mode
    guarantees the line is visible.
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    ns, _ = _exec_helpers(files)
    AnnotationWriter = ns["AnnotationWriter"]

    w = AnnotationWriter("buffered", output_dir=tmp_path)
    w.record_transition(
        cycle=1,
        chart_state="idle",
        transition_id=None,
        chart_path=["idle"],
        signal="dut.current_state",
    )
    # Probe BEFORE close — line-buffered mode flushed the newline
    # already, so the file on disk MUST carry both the header line
    # and the transition record.
    on_disk = (tmp_path / "buffered.annotations.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(on_disk) >= 2, (
        "line-buffered flush should make both header + record visible "
        "before close()"
    )
    w.close()


def test_readme_documents_annotation_overlay():
    """Per SOS-08-G §6 (viewer integration): the emitted README MUST
    document the `.annotations.jsonl` overlay + how viewers consume
    it, citing the relevant PCDN identifiers.
    """
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    readme = files["tests/demo/README.md"]

    # SOS-08-G citation per chart-vocabulary doctrine.
    assert "SOS-08-G" in readme

    # Three-file output contract documented.
    assert ".fst" in readme
    assert ".vcd" in readme
    assert ".annotations.jsonl" in readme

    # Key PCDNs cited.
    assert "PCDN-SOS-08-G-001" in readme  # schema header
    assert "PCDN-SOS-08-G-004" in readme  # viewer location
    assert "PCDN-SOS-08-G-005" in readme  # density default
    assert "PCDN-SOS-08-G-006" in readme  # line-buffered

    # Viewer integration named (GTKWave + Surfer per §6).
    assert "GTKWave" in readme
    assert "Surfer" in readme


def test_helpers_module_parses_with_annotation_writer():
    """Sanity gate: the extended `_cocotb_helpers.py` MUST still parse
    cleanly as Python. The AnnotationWriter class is added inline; if
    the emit ever generates malformed f-string interpolation the AST
    parser will catch it before a downstream test does."""
    files = render_target(_simple_chart(), {"chart_name": "demo"})
    ast.parse(files["tests/demo/_cocotb_helpers.py"])
    # And the emitted test module continues to parse (the wired-in
    # AnnotationWriter usage must not regress the test body's syntax).
    ast.parse(files["tests/demo/test_demo_fsm.py"])


# ---------------------------------------------------------------------------
# SOS-08-D wave-2a: post_results.py JUnit XML post-processor (§6.7 +
# PCDN-D-002 — wave-1 deferred, wave-2a landed).
# ---------------------------------------------------------------------------


class TestPostResultsEmit:
    """post_results.py is emitted per chart and parses + runs against a
    synthetic build/ directory."""

    def _post_results(self) -> str:
        files = render_target(_simple_chart(), {"chart_name": "demo"})
        return files["tests/demo/post_results.py"]

    def test_emitted(self):
        files = render_target(_simple_chart(), {"chart_name": "demo"})
        assert "tests/demo/post_results.py" in files

    def test_parses_as_python(self):
        ast.parse(self._post_results())

    def test_cites_chart_name(self):
        src = self._post_results()
        assert "CHART_NAME = 'demo'" in src or 'CHART_NAME = "demo"' in src

    def test_cites_spec_sections(self):
        src = self._post_results()
        for token in ("SOS-08-D", "§6.7", "PCDN-D-002"):
            assert token in src, (
                f"post_results.py must cite spec reference {token!r}"
            )

    def test_cites_invariants(self):
        src = self._post_results()
        assert "INV-S-HDL-D-3" in src
        assert "INV-S-HDL-D-5" in src

    def test_uses_standard_library_only(self):
        """Per §5.3 + the wave-2a §15 entry the post-processor depends
        only on the Python standard library so it runs in CI without
        installing the cocotb/pytest stack twice."""
        src = self._post_results()
        # No imports of cocotb / pytest / external packages.
        for forbidden in ("import cocotb", "import pytest", "from cocotb",
                          "from pytest"):
            assert forbidden not in src, (
                f"post_results.py must be stdlib-only; saw {forbidden!r}"
            )

    def test_self_filters_by_chart_name(self):
        """§6.7 (3): post-processor MUST filter SOS-FAIL lines by
        chart name so a shared build/ across charts does not cross-
        contaminate."""
        src = self._post_results()
        assert 'gd.get("chart") != CHART_NAME' in src

    def test_non_mutating_with_respect_to_results_xml(self):
        """INV-S-HDL-D-3: the script reads build/results.xml but
        writes its output to a separate build/junit.xml path."""
        src = self._post_results()
        # Reads results.xml, writes junit.xml — never opens results.xml
        # for writing.
        assert 'results.xml' in src
        assert 'junit.xml' in src
        assert 'tree.write(junit_xml' in src
        # No .write_text on results.xml.
        import re
        assert not re.search(r"results_xml\s*\.\s*write_text", src)


class TestPostResultsEndToEnd:
    """Drive the emitted post_results.py against synthetic inputs and
    verify the JUnit XML output shape."""

    def _run_script(self, sim_log_text: str,
                    results_xml_text: str | None = None) -> tuple[int, str, str]:
        import subprocess
        import tempfile
        files = render_target(_simple_chart(), {"chart_name": "demo"})
        src = files["tests/demo/post_results.py"]
        with tempfile.TemporaryDirectory() as td:
            from pathlib import Path
            td_p = Path(td)
            (td_p / "post_results.py").write_text(src)
            build = td_p / "build"
            build.mkdir()
            if results_xml_text is None:
                results_xml_text = (
                    '<?xml version="1.0"?>\n'
                    '<testsuites>\n'
                    '  <testsuite name="demo">\n'
                    '    <testcase name="test_vector_a">\n'
                    '      <failure type="AssertionError">'
                    'cocotb assertion failed</failure>\n'
                    '    </testcase>\n'
                    '  </testsuite>\n'
                    '</testsuites>\n'
                )
            (build / "results.xml").write_text(results_xml_text)
            (build / "sim.log").write_text(sim_log_text)
            res = subprocess.run(
                ["python3", str(td_p / "post_results.py"), str(build)],
                capture_output=True, text=True,
            )
            junit = (build / "junit.xml").read_text() if (build / "junit.xml").exists() else ""
            return res.returncode, res.stdout + junit, res.stderr

    def test_emits_junit_xml_with_sos_fail_merged(self):
        rc, combined, err = self._run_script(
            "SOS-FAIL chart=demo region=main transition=T7 "
            "state=idle invariant=I1 @ 142ns\n"
        )
        assert rc == 0, f"post_results.py failed: stderr={err}"
        assert "transition=T7" in combined
        assert "state=idle" in combined
        assert "invariant=I1" in combined
        assert "[SOS-08-D §6.6 chart-vocabulary]" in combined

    def test_self_filters_by_chart_name_runtime(self):
        """SOS-FAIL line for a sibling chart name MUST be ignored."""
        rc, combined, err = self._run_script(
            "SOS-FAIL chart=other_chart region=main transition=T1 "
            "state=foo invariant=I2 @ 100ns\n"
            "SOS-FAIL chart=demo region=main transition=T7 "
            "state=idle invariant=I1 @ 142ns\n"
        )
        assert rc == 0
        # Only the demo-chart line is merged; the other_chart line
        # MUST NOT appear in the junit output.
        assert "other_chart" not in combined
        assert "invariant=I1" in combined
        # And the script reports merging exactly 1 line.
        assert "merged 1 SOS-FAIL line" in combined

    def test_returns_nonzero_when_results_xml_missing(self):
        """If cocotb did not produce results.xml the post-processor
        MUST surface the failure rather than silently writing an
        empty junit.xml."""
        import subprocess
        import tempfile
        files = render_target(_simple_chart(), {"chart_name": "demo"})
        src = files["tests/demo/post_results.py"]
        with tempfile.TemporaryDirectory() as td:
            from pathlib import Path
            td_p = Path(td)
            (td_p / "post_results.py").write_text(src)
            build = td_p / "build"
            build.mkdir()
            res = subprocess.run(
                ["python3", str(td_p / "post_results.py"), str(build)],
                capture_output=True, text=True,
            )
            assert res.returncode == 2
            assert "results.xml" in res.stderr

    def test_handles_no_failures(self):
        """A clean cocotb run (no <failure> elements) yields a clean
        junit.xml — no script error, no merge attempt."""
        rc, combined, err = self._run_script(
            "",  # no SOS-FAIL lines
            results_xml_text=(
                '<?xml version="1.0"?>\n'
                '<testsuites>\n'
                '  <testsuite name="demo">\n'
                '    <testcase name="test_vector_a"/>\n'
                '  </testsuite>\n'
                '</testsuites>\n'
            ),
        )
        assert rc == 0
        assert "merged 0 SOS-FAIL line" in combined

    def test_handles_more_sos_fail_lines_than_failures(self):
        """When sim.log has more SOS-FAIL lines than results.xml has
        <failure> elements, the extras MUST land in the last failure's
        text rather than being silently dropped."""
        rc, combined, err = self._run_script(
            "SOS-FAIL chart=demo region=main transition=T1 "
            "state=A invariant=I1 @ 10ns\n"
            "SOS-FAIL chart=demo region=main transition=T2 "
            "state=B invariant=I2 @ 20ns\n"
            "SOS-FAIL chart=demo region=main transition=T3 "
            "state=C invariant=I3 @ 30ns\n",
            results_xml_text=(
                '<?xml version="1.0"?>\n'
                '<testsuites>\n'
                '  <testsuite name="demo">\n'
                '    <testcase name="test_vector_a">\n'
                '      <failure type="AssertionError">first failure</failure>\n'
                '    </testcase>\n'
                '  </testsuite>\n'
                '</testsuites>\n'
            ),
        )
        assert rc == 0
        # All three SOS-FAIL lines must appear in the single failure
        # block (one in-order match + two trailing appended).
        for inv in ("I1", "I2", "I3"):
            assert f"invariant={inv}" in combined


# ---------------------------------------------------------------------------
# SOS-08-D wave-2c: cocotb parallel-chart support (§15 2026-05-23 entry).
# ---------------------------------------------------------------------------


class TestParallelChartEmit:
    """Parallel-chart cocotb emission contract per SOS-08-D §15 wave-2c."""

    def _files(self) -> dict:
        return render_target(_chart_with_parallel(),
                             {"chart_name": "parallels"})

    def test_emits_same_artifact_set_as_single_region(self):
        files = self._files()
        # Same six normative files + scaffold vector.
        for fname in (
            "tests/parallels/test_parallels_fsm.py",
            "tests/parallels/_cocotb_helpers.py",
            "tests/parallels/Makefile",
            "tests/parallels/pytest.ini",
            "tests/parallels/README.md",
            "tests/parallels/post_results.py",
            "tests/parallels/vectors/000-reset.json",
        ):
            assert fname in files, f"parallel emit missing {fname}"

    def test_helpers_carry_region_encodings_for_each_region(self):
        helpers = self._files()["tests/parallels/_cocotb_helpers.py"]
        # Both regions from the fixture: left + right.
        assert "'left'" in helpers
        assert "'right'" in helpers

    def test_helpers_carry_region_initial_states(self):
        helpers = self._files()["tests/parallels/_cocotb_helpers.py"]
        # Fixture: left initial = l_idle, right initial = r_idle.
        assert "'l_idle'" in helpers
        assert "'r_idle'" in helpers

    def test_assert_region_state_helper_present(self):
        helpers = self._files()["tests/parallels/_cocotb_helpers.py"]
        assert "def assert_region_state(" in helpers

    def test_helpers_module_parses(self):
        helpers = self._files()["tests/parallels/_cocotb_helpers.py"]
        ast.parse(helpers)

    def test_test_module_parses(self):
        test = self._files()["tests/parallels/test_parallels_fsm.py"]
        ast.parse(test)

    def test_test_imports_assert_region_state(self):
        test = self._files()["tests/parallels/test_parallels_fsm.py"]
        # Wave-2c parallel emit imports assert_region_state alongside
        # assert_state (latter retained for single-region paths through
        # the same helpers module).
        assert "assert_region_state" in test

    def test_test_body_asserts_per_region_initial_state(self):
        test = self._files()["tests/parallels/test_parallels_fsm.py"]
        # Each region's initial-state assertion via assert_region_state.
        assert "'left'" in test and "'l_idle'" in test
        assert "'right'" in test and "'r_idle'" in test

    def test_test_body_records_per_region_annotation(self):
        """SOS-08-G §5.2: every annotation record carries `region`;
        wave-2c sets region=<region> per record so the review surface
        attributes each post-reset state-entry to its region."""
        test = self._files()["tests/parallels/test_parallels_fsm.py"]
        assert "region='left'" in test or 'region="left"' in test
        assert "region='right'" in test or 'region="right"' in test

    def test_dut_module_name_is_chart_top_wrapper(self):
        """The DUT in the parallel-chart test is the chart-top
        wrapper `<chart>_fsm` (per SOS-08-C §6.10), NOT a per-region
        FSM module."""
        test = self._files()["tests/parallels/test_parallels_fsm.py"]
        assert "parallels_fsm" in test

    def test_single_region_chart_unchanged(self):
        """Wave-2c MUST NOT change single-region emit behavior — the
        wave-1 code path runs unchanged."""
        files = render_target(_simple_chart(), {"chart_name": "demo"})
        helpers = files["tests/demo/_cocotb_helpers.py"]
        # _HAS_PARALLEL is False for single-region.
        assert "_HAS_PARALLEL: bool = False" in helpers
        # Existing test path still emits.
        test = files["tests/demo/test_demo_fsm.py"]
        assert "test_vector_" in test
        # Single-region test reads `dut.current_state`, not
        # `dut.current_state_<region>`.
        assert "current_state" in test


class TestWave3PerRegionStepDrivenVectors:
    """SOS-08-D wave-3 (2026-05-24 §15): per-region step-driven
    vectors. Extends the parallel-chart test body to walk
    `vector["steps"]` where each step carries `expected_states:
    {region: state}`. The walker iterates steps, optionally drives
    `inputs`, advances by `cycles_advance` clocks, asserts each
    named region's state via `assert_region_state`, and records a
    SOS-08-G annotation per region. Closes with per-region terminal
    assertions via `expected_terminal_states` (dict).

    Backwards-compatible with wave-2c minimal vectors (no `steps`
    → reset + initial-state-only test, identical to wave-2c).
    """

    def _files(self) -> dict:
        return render_target(_chart_with_parallel(),
                             {"chart_name": "parallels"})

    def test_step_walker_loop_emitted(self):
        """Parallel test body iterates `vector["steps"]` via enumerate."""
        test = self._files()["tests/parallels/test_parallels_fsm.py"]
        assert "for step_index, step in enumerate(vector.get(\"steps\", [])" in test

    def test_step_walker_handles_inputs(self):
        """Each step optionally drives `inputs` as a flat
        {port: value} map (mirror of the single-region wave-1
        emission)."""
        test = self._files()["tests/parallels/test_parallels_fsm.py"]
        assert "(step.get(\"inputs\") or {})" in test
        assert "getattr(dut, port_name).value = port_value" in test

    def test_step_walker_handles_cycles_advance(self):
        """`cycles_advance` (default 1) lets vector authors wait
        multiple clocks between events — e.g. CDC settling."""
        test = self._files()["tests/parallels/test_parallels_fsm.py"]
        assert "cycles_to_advance = int(step.get(\"cycles_advance\", 1)" in test
        assert "for _ in range(cycles_to_advance):" in test

    def test_step_walker_asserts_per_region_expected_states(self):
        """Each step's `expected_states: {region: state}` produces
        one `assert_region_state` call per (region, state) entry."""
        test = self._files()["tests/parallels/test_parallels_fsm.py"]
        assert "expected_states = step.get(\"expected_states\") or {}" in test
        assert "for region_name, expected_state in expected_states.items():" in test
        # The assertion uses the wave-2c helper with per-step
        # context.
        assert "assert_region_state(\n                    dut, region_name, expected_state," in test

    def test_step_walker_records_annotation_per_region(self):
        """SOS-08-G integration: each per-region assertion produces
        a `writer.record_transition` annotation with region= named."""
        test = self._files()["tests/parallels/test_parallels_fsm.py"]
        assert "writer.record_transition(" in test
        assert "region=region_name" in test
        assert "vector_index=step_index" in test

    def test_terminal_states_dict_used(self):
        """`vector["expected_terminal_states"]` (dict) lets per-
        region terminals differ; falls back to each region's
        initial state when absent."""
        test = self._files()["tests/parallels/test_parallels_fsm.py"]
        assert (
            "terminal_states = vector.get(\"expected_terminal_states\") or {}"
            in test
        )
        # Per-region initial-state fallback map declared.
        assert "_region_initial = {" in test

    def test_per_region_terminal_assertion_loop(self):
        """After step walking, walker emits per-region
        `assert_region_state` for each region's terminal state."""
        test = self._files()["tests/parallels/test_parallels_fsm.py"]
        assert (
            "for region_name, init_state in _region_initial.items():"
            in test
        )
        assert (
            "terminal = terminal_states.get(region_name, init_state)"
            in test
        )

    def test_walker_remains_backward_compatible(self):
        """The wave-2c minimal-vector (reset + initial-state only)
        path MUST still work — `vector.get("steps", [])` returns []
        when absent, so the step loop is a no-op; terminal-state
        loop falls back to initial states. Verify the test body
        still parses cleanly and the wave-2c initial-state-per-
        region assertion block survives."""
        test = self._files()["tests/parallels/test_parallels_fsm.py"]
        ast.parse(test)
        # Wave-2c initial-state-per-region assertions still emitted.
        assert "assert_region_state(\n            dut, 'left', 'l_idle'" in test
        assert "assert_region_state(\n            dut, 'right', 'r_idle'" in test

    def test_format_failure_passes_step_context(self):
        """Per-step assertion failures MUST surface the step's
        chart-vocabulary context per INV-S-HDL-D-5."""
        test = self._files()["tests/parallels/test_parallels_fsm.py"]
        assert "format_failure(vector, step)" in test


# ---------------------------------------------------------------------------
# SOS-08-G wave-2a: nested chart_path walking (§15 2026-05-23 entry).
# ---------------------------------------------------------------------------


class TestNestedChartPathWalking:
    """SOS-08-G wave-2: chart_path field on annotation records is the
    walker-computed root-to-leaf path per §5.2 + PCDN-G-002 (max
    depth 8)."""

    def _nested_chart(self) -> dict:
        return {
            "initial": "outer",
            "state": [
                {
                    "id": "outer",
                    "state": [
                        {
                            "id": "inner",
                            "state": [
                                {"id": "leaf"},
                            ],
                        },
                    ],
                },
            ],
        }

    def test_chart_paths_emitted_in_helpers(self):
        files = render_target(self._nested_chart(), {"chart_name": "demo"})
        helpers = files["tests/demo/_cocotb_helpers.py"]
        assert "_CHART_PATHS: dict[str, list[str]] =" in helpers

    def test_root_state_path(self):
        files = render_target(self._nested_chart(), {"chart_name": "demo"})
        helpers = files["tests/demo/_cocotb_helpers.py"]
        # outer is at depth 1 below the chart root.
        assert "'outer': ['demo', 'outer']" in helpers

    def test_nested_state_path(self):
        files = render_target(self._nested_chart(), {"chart_name": "demo"})
        helpers = files["tests/demo/_cocotb_helpers.py"]
        # inner is rooted: chart -> outer -> inner.
        assert "'inner': ['demo', 'outer', 'inner']" in helpers

    def test_deeply_nested_state_path(self):
        files = render_target(self._nested_chart(), {"chart_name": "demo"})
        helpers = files["tests/demo/_cocotb_helpers.py"]
        # leaf is at depth 3: chart -> outer -> inner -> leaf.
        assert "'leaf': ['demo', 'outer', 'inner', 'leaf']" in helpers

    def test_test_body_uses_chart_paths_lookup(self):
        files = render_target(self._nested_chart(), {"chart_name": "demo"})
        test_body = files["tests/demo/test_demo_fsm.py"]
        # Test body uses _CHART_PATHS.get(...) lookup pattern rather
        # than the wave-1 single-segment `[state_id]` form.
        assert "_CHART_PATHS.get(" in test_body

    def test_path_truncated_at_max_depth(self):
        """PCDN-G-002 max depth = 8. Charts deeper than 8 truncate to
        the first 8 segments at emit time."""
        # Build a 10-deep chain.
        chart_ir = {"state": []}
        node = chart_ir
        for i in range(10):
            sid = f"s{i}"
            child = {"id": sid, "state": []}
            node["state"].append(child)
            node = child
        files = render_target(chart_ir, {"chart_name": "deep"})
        helpers = files["tests/deep/_cocotb_helpers.py"]
        # s9 is at chart depth 10; the emitted path is capped at 8.
        # Find the s9 entry and parse its list-literal length.
        import re as _re
        m = _re.search(r"'s9':\s*\[([^\]]+)\]", helpers)
        assert m, "s9 entry missing from emitted _CHART_PATHS"
        segs = [s.strip().strip("'") for s in m.group(1).split(",")]
        assert len(segs) == 8, (
            f"chart_path for s9 must be capped at 8 segments per "
            f"PCDN-G-002; got {len(segs)}: {segs}"
        )

    def test_parallel_chart_paths_include_region(self):
        """For parallel charts the path threads through the
        ``<parallel>`` wrapper id AND the region identifier (the
        parallel-child ``<state>``) per SOS-12 — both are hierarchy
        nodes in the SCXML AST so both appear in the path."""
        chart_ir = {
            "initial": "p",
            "parallel": [{
                "id": "p",
                "state": [
                    {
                        "id": "left",
                        "state": [{"id": "l_idle"}],
                    },
                ],
            }],
        }
        files = render_target(chart_ir, {"chart_name": "k"})
        helpers = files["tests/k/_cocotb_helpers.py"]
        # l_idle's path: chart root -> <parallel> id -> region -> leaf.
        assert "'l_idle': ['k', 'p', 'left', 'l_idle']" in helpers


# ---------------------------------------------------------------------------
# SOS-08-G wave-2b: post_annotations.py SVA invariant_id merge.
# ---------------------------------------------------------------------------


class TestPostAnnotationsEmit:
    """post_annotations.py is emitted per chart and merges SVA fires."""

    def _post_ann(self) -> str:
        files = render_target(_simple_chart(), {"chart_name": "demo"})
        return files["tests/demo/post_annotations.py"]

    def test_emitted(self):
        files = render_target(_simple_chart(), {"chart_name": "demo"})
        assert "tests/demo/post_annotations.py" in files

    def test_parses_as_python(self):
        ast.parse(self._post_ann())

    def test_cites_chart_name(self):
        src = self._post_ann()
        assert "CHART_NAME = 'demo'" in src or 'CHART_NAME = "demo"' in src

    def test_cites_spec_sections(self):
        src = self._post_ann()
        for token in ("SOS-08-G", "INV-S-HDL-G-2", "INV-S-HDL-G-3"):
            assert token in src, (
                f"post_annotations.py must cite {token!r}"
            )

    def test_stdlib_only(self):
        src = self._post_ann()
        for forbidden in ("import cocotb", "import pytest"):
            assert forbidden not in src


class TestPostAnnotationsEndToEnd:
    """Drive the emitted post_annotations.py against synthetic inputs."""

    def _run(self, sim_log_text: str, overlay_lines: list[str]) -> tuple[int, str, str, str]:
        import subprocess
        import tempfile
        files = render_target(_simple_chart(), {"chart_name": "demo"})
        src = files["tests/demo/post_annotations.py"]
        with tempfile.TemporaryDirectory() as td:
            from pathlib import Path
            td_p = Path(td)
            (td_p / "post_annotations.py").write_text(src)
            build = td_p / "build"
            build.mkdir()
            overlay = build / "test_x.annotations.jsonl"
            overlay.write_text("\n".join(overlay_lines) + "\n")
            (build / "sim.log").write_text(sim_log_text)
            res = subprocess.run(
                ["python3", str(td_p / "post_annotations.py"), str(build)],
                capture_output=True, text=True,
            )
            return res.returncode, res.stdout, res.stderr, overlay.read_text()

    def test_appends_sva_fire_with_invariant_id(self):
        header = (
            '{"_meta": {"schema": "sos-08-g/annotations", '
            '"version": "1.0", "chart_path_max_depth": 8}}'
        )
        rc, out, err, overlay = self._run(
            "SOS-FAIL chart=demo region=main transition=T7 "
            "state=idle invariant=I1 @ 142ns\n",
            [header],
        )
        assert rc == 0, f"post_annotations.py failed: {err}"
        # Header preserved at line 0 (INV-S-HDL-G-3).
        lines = overlay.strip().split("\n")
        assert "sos-08-g/annotations" in lines[0]
        # Appended record carries invariant_id.
        appended = lines[1]
        assert '"invariant_id": "I1"' in appended
        assert '"transition_id": "T7"' in appended

    def test_self_filters_by_chart_name(self):
        """Other-chart SOS-FAIL lines MUST NOT be appended."""
        header = (
            '{"_meta": {"schema": "sos-08-g/annotations", '
            '"version": "1.0", "chart_path_max_depth": 8}}'
        )
        rc, out, err, overlay = self._run(
            "SOS-FAIL chart=other region=foo transition=T1 "
            "state=q invariant=Ix @ 1ns\n"
            "SOS-FAIL chart=demo region=main transition=T7 "
            "state=idle invariant=I1 @ 142ns\n",
            [header],
        )
        assert rc == 0
        # Only the demo-chart fire merged.
        assert overlay.count("invariant_id") == 1
        assert "Ix" not in overlay

    def test_no_fires_no_changes(self):
        header = (
            '{"_meta": {"schema": "sos-08-g/annotations", '
            '"version": "1.0", "chart_path_max_depth": 8}}'
        )
        rc, out, err, overlay = self._run("", [header])
        assert rc == 0
        # Just the header line; no appended records.
        assert overlay.strip() == header

    def test_header_preserved_at_line_zero(self):
        """INV-S-HDL-G-3: schema-version header MUST remain at line 0
        after merge."""
        header = (
            '{"_meta": {"schema": "sos-08-g/annotations", '
            '"version": "1.0", "chart_path_max_depth": 8}}'
        )
        existing = (
            '{"cycle": 0, "signal": "dut.x", "chart_state": "idle", '
            '"transition_id": null, "chart_path": ["demo", "idle"], '
            '"region": null}'
        )
        rc, out, err, overlay = self._run(
            "SOS-FAIL chart=demo region=main transition=T7 "
            "state=idle invariant=I1 @ 142ns\n",
            [header, existing],
        )
        assert rc == 0
        lines = overlay.strip().split("\n")
        # Header at line 0; pre-existing record at line 1; merged
        # fire at line 2.
        import json as _json
        assert "_meta" in _json.loads(lines[0])
        assert len(lines) == 3


# ---------------------------------------------------------------------------
# SOS-08-G wave-3a: per-cycle density actual implementation (§15
# 2026-05-24).
# ---------------------------------------------------------------------------


class TestWave3aPerCycleDensity:
    """SOS-08-G wave-3a: PCDN-G-005 cycle-density opt-in is now wired
    by construction.

    Wave-1 + wave-2 read `SOS_ANNOTATION_DENSITY` and exposed
    `record_cycle` on `AnnotationWriter`, but the emitted
    `@cocotb.test()` body did NOT spawn a per-`RisingEdge(dut.clk)`
    callback. Wave-3a lands the callback wiring:

    - The test module imports `_STATE_ENCODING`, `_REGION_STATE_ENCODINGS`,
      `_CHART_NAME`, `_CHART_PATHS` from `_cocotb_helpers`.
    - A `_per_cycle_record(dut, writer, region_name=None)` coroutine is
      emitted at module level (right after `_apply_reset`).
    - Single-region: `cocotb.start_soon(_per_cycle_record(dut, writer))`
      when `writer.density == "cycle"`.
    - Parallel: one `cocotb.start_soon(_per_cycle_record(dut, writer,
      region_name=...))` per region (iterating `_REGION_STATE_ENCODINGS`).

    Invariants upheld: INV-S-HDL-G-5 (co-located with test body, not a
    post-process step); INV-S-HDL-G-2 (per-cycle records carry the same
    chart-vocabulary fields as per-event records); PCDN-G-005 (per-event
    remains the default; cycle is opt-in).
    """

    def _single_files(self) -> dict:
        return render_target(_simple_chart(), {"chart_name": "demo"})

    def _parallel_files(self) -> dict:
        return render_target(_chart_with_parallel(),
                             {"chart_name": "parallels"})

    # --- module-level emission --- #

    def test_per_cycle_record_coroutine_emitted(self):
        """The `_per_cycle_record` coroutine MUST be emitted at module
        level in the test module so both single-region and parallel
        test functions can spawn it."""
        test = self._single_files()["tests/demo/test_demo_fsm.py"]
        assert "async def _per_cycle_record(dut, writer, region_name=None):" in test

    def test_per_cycle_record_imports_encoding_maps(self):
        """The test module imports the encoding maps + chart-path
        helpers from `_cocotb_helpers` so the per-cycle recorder can
        decode the one-hot RTL value back to chart vocabulary."""
        test = self._single_files()["tests/demo/test_demo_fsm.py"]
        assert "from _cocotb_helpers import (" in test
        assert "_STATE_ENCODING" in test
        assert "_REGION_STATE_ENCODINGS" in test
        assert "_CHART_NAME" in test
        assert "_CHART_PATHS" in test

    def test_per_cycle_record_decodes_one_hot_via_inverted_map(self):
        """The recorder inverts the encoding map to decode the RTL
        one-hot value back to chart-state id at runtime."""
        test = self._single_files()["tests/demo/test_demo_fsm.py"]
        assert (
            "decode = {value: state_id for state_id, value in encoding.items()}"
            in test
        )

    def test_per_cycle_record_unknown_value_surfaces_literal(self):
        """Decode failures MUST NOT silently drop records — the
        recorder emits a literal `<unknown:0bNN>` chart_state so the
        review surface sees the decode failure."""
        test = self._single_files()["tests/demo/test_demo_fsm.py"]
        assert "decode.get(observed, f\"<unknown:0b{observed:b}>\")" in test

    def test_per_cycle_record_calls_writer_record_cycle(self):
        """The recorder invokes `writer.record_cycle` (NOT
        `record_transition`) — per-cycle stream is for cycle-density
        opt-in only."""
        test = self._single_files()["tests/demo/test_demo_fsm.py"]
        assert "writer.record_cycle(" in test

    def test_per_cycle_record_loops_on_rising_edge(self):
        """Inside the coroutine the recording loop awaits
        `RisingEdge(dut.clk)` per simulator tick."""
        test = self._single_files()["tests/demo/test_demo_fsm.py"]
        assert "while True:" in test
        assert "await RisingEdge(dut.clk)" in test

    # --- single-region spawn site --- #

    def test_single_region_spawns_recorder_when_cycle_density(self):
        """Single-region test body spawns the per-cycle recorder
        coroutine via `cocotb.start_soon` gated by
        `writer.density == "cycle"`."""
        test = self._single_files()["tests/demo/test_demo_fsm.py"]
        assert "if writer.density == \"cycle\":" in test
        assert "cocotb.start_soon(_per_cycle_record(dut, writer))" in test

    def test_single_region_does_not_spawn_per_region_recorders(self):
        """Single-region test body MUST NOT spawn per-region
        recorders (no regions to iterate)."""
        test = self._single_files()["tests/demo/test_demo_fsm.py"]
        # The single-region spawn site uses the no-region call shape.
        assert "_per_cycle_record(dut, writer)" in test
        # And does not iterate the region encoding map.
        assert "for _region_name in _REGION_STATE_ENCODINGS:" not in test

    # --- parallel-chart spawn site --- #

    def test_parallel_spawns_one_recorder_per_region(self):
        """Parallel test body iterates `_REGION_STATE_ENCODINGS` and
        spawns one recorder per region, tagging each with its region
        name so the resulting annotations are filterable per-region."""
        test = self._parallel_files()["tests/parallels/test_parallels_fsm.py"]
        assert "if writer.density == \"cycle\":" in test
        assert "for _region_name in _REGION_STATE_ENCODINGS:" in test
        assert (
            "cocotb.start_soon(\n"
            "                _per_cycle_record(dut, writer, region_name=_region_name)"
            in test
        )

    # --- backwards compatibility (per-event default) --- #

    def test_per_event_default_unchanged(self):
        """PCDN-G-005 freezes per-event as the default. The default
        path — no `SOS_ANNOTATION_DENSITY=cycle` env var — MUST still
        emit the wave-1 `record_transition` calls without the
        per-cycle recorder running. The gate is runtime; the emitted
        test body MUST still contain the per-event `record_transition`
        call sites unchanged."""
        test = self._single_files()["tests/demo/test_demo_fsm.py"]
        assert "writer.record_transition(" in test

    def test_emitted_test_module_parses(self):
        """The emitted test module — with the per-cycle recorder
        wired in — MUST still parse as valid Python 3.10+ syntax."""
        test = self._single_files()["tests/demo/test_demo_fsm.py"]
        ast.parse(test)

    def test_emitted_parallel_test_module_parses(self):
        """The emitted parallel test module — with per-region
        recorders wired in — MUST still parse as valid Python 3.10+
        syntax."""
        test = self._parallel_files()["tests/parallels/test_parallels_fsm.py"]
        ast.parse(test)

    # --- writer/helper integration (no walker change required) --- #

    def test_writer_density_env_var_unchanged(self):
        """The wave-1 env-var read on `AnnotationWriter` MUST remain
        — wave-3a only adds the consumer side, not the gate."""
        helpers = self._single_files()["tests/demo/_cocotb_helpers.py"]
        assert "_DENSITY_ENV_VAR = \"SOS_ANNOTATION_DENSITY\"" in helpers
        assert "os.environ.get(self._DENSITY_ENV_VAR, \"event\")" in helpers

    def test_helpers_still_expose_record_cycle(self):
        """The wave-1 `record_cycle` method on `AnnotationWriter`
        MUST remain — wave-3a wires the caller, not the writer."""
        helpers = self._single_files()["tests/demo/_cocotb_helpers.py"]
        assert "def record_cycle(" in helpers

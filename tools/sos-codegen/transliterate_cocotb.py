"""SCXML chart → cocotb testbench emitter (SOS-08-D PRIMARY vector path).

Wave-1 scaffold per SOS-08-D-CONCEPTS.md §6 (per-artifact contracts) and
§15 (ratified 2026-05-23 — PCDN-D-001..007 resolved). The emitter walks
the raw scjson chart-IR (the same shape SOS-08-C's L2 walkers consume)
and produces a per-DUT cocotb test directory:

    tests/<chart_name>/
        test_<chart_name>_fsm.py    # one @cocotb.test per vector
        _cocotb_helpers.py          # shared load_vector / assert_state / format_failure
        Makefile                    # cocotb-classic Makefile invocation
        pytest.ini                  # cocotb-test invocation
        README.md                   # Python 3.10+ minimum + simulator selection

Wave-1 scope (intentionally narrow — PCDN-D-003 / §5.5):
  - One @cocotb.test() async function per vector (`vector_ids` from
    config; defaults to a single scaffold vector "000-reset").
  - 100 MHz clock (10 ns period; matches `sos_fifo_sync` test pattern).
  - 5-cycle synchronous active-high reset assertion at test start
    (mirrors INV-S-HDL-A-1).
  - Vector files are loaded at TEST runtime from `<test_dir>/vectors/`.
  - State-encoding map embedded in the helper as a chart-derived
    `_STATE_ENCODING` dict mirroring SOS-08-C one-hot encoding
    (PCDN-002 / SOS-08-C §5.1).
  - Parallel charts REJECTED at wave-1 (UnsupportedChartError) — they
    land in wave-2 alongside the multi-region cocotb harness shape.

@spec  SOS-08-D-CONCEPTS.md §5 (frozen decisions: Verilator default
       per PCDN-D-001; one @cocotb.test per vector per PCDN-D-003 /
       §5.5; full SVA bind default per PCDN-D-004 / §5.4; per-DUT bind
       file placement per PCDN-D-006 / §5.6; Python 3.10+ per
       PCDN-D-005 / §5.3)
@spec  SOS-08-D-CONCEPTS.md §6 (per-artifact contracts):
         §6.1 emit directory layout
         §6.2 per-vector cocotb test function shape
         §6.5 pass/fail contract (vector trace + SVA + completion)
         §6.6 chart-vocabulary failure-message rendering
         §6.7 JUnit XML CI integration (post-processor stub deferred to
              wave-2; wave-1 emits cocotb's native results.xml only)
@spec  SOS-08-D-CONCEPTS.md §15 (ratified 2026-05-23 — PCDN-D-001..007
       resolved with recommendations accepted)
@spec  SOS-08-C-CONCEPTS.md §6 (chart→FSM emission this emitter tests),
       §5.1 (one-hot encoding default; chart-state ID → bit pattern)
@spec  SOS-03-CONCEPTS.md §7.1 (vector format reference — JSONL traces
       with `expected_trace` field; one event per JSONL line per
       PCDN-009)
@spec  SOS-07-CONCEPTS.md INV-SOS-A..H (cross-phase invariants;
       INV-SOS-A chart-as-source — emitter never mutates the chart IR;
       INV-SOS-H chart-vocabulary failure surfacing)
@spec  SOS-08-CONCEPTS.md INV-S-HDL-1..5 (cross-sub-phase invariants;
       INV-S-HDL-5 chart-vocabulary traceability)
@spec  SOS-08-D-CONCEPTS.md INV-S-HDL-D-1..6 (cross-artifact invariants):
         D-1 dual artifact, one IR (SVA bind co-emission deferred to
             wave-2 sibling; this module emits the cocotb half)
         D-2 open-source-simulator coverage at v1 (Verilator default;
             Makefile carries SIM ?= verilator)
         D-3 vector-IR is read-only at the emitter boundary (this
             module never mutates the chart_ir dict passed in)
         D-4 same SVA artifact feeds cocotb and formal flow (wave-2)
         D-5 chart-vocabulary failure messages (assert_state +
             format_failure helpers per §6.6)
         D-6 per-vector test isolation by default (one @cocotb.test
             per vector_id per §5.5)
@spec  PCDN-D-001 — Verilator default (`SIM ?= verilator`)
@spec  PCDN-D-002 — JUnit XML emission (post-processor stub deferred
       to wave-2; native results.xml emitted at wave-1)
@spec  PCDN-D-003 — per-vector test isolation default
@spec  PCDN-D-004 — full SVA bind default (wave-2 co-emission)
@spec  PCDN-D-005 — Python 3.10+ minimum
@spec  PCDN-D-006 — one `test_<dut>.py` per DUT + shared helpers
@spec  PCDN-D-007 — emit both Makefile and pytest.ini

# Integration contract

The codegen tool's CLI dispatcher (`main.py`) is intended to extend
with `--target cocotb` (sibling-agent's work):

    from transliterate_cocotb import render_target
    files = render_target(chart_ir, config)
    for fname, body in files.items():
        (out_dir / "tests" / chart_name / fname).write_text(body)

`chart_ir` is the raw scjson dict — the shape `loader.load_chart` reads
from disk before normalising into `ChartAst`, identical to the input
SOS-08-C walkers consume. `config` is a dict or an object exposing:
  - `chart_name`: str (defaults to "chart").
  - `vector_ids`: optional list[str]; one @cocotb.test per id. Empty
    list / absent → wave-1 scaffold emits a single ``000-reset`` test.
  - `dut_module`: optional str overriding the inferred DUT name
    (defaults to `<chart_name>_fsm` matching SOS-08-C single-region
    convention).
  - `clock_period_ns`: optional int (default 10 — 100 MHz).
  - `reset_cycles`: optional int (default 5).

Wave-1 is a static deliverable; no live cocotb run is performed. The
emitted Python is syntactically self-contained — it imports cocotb at
test-runtime only, and `_cocotb_helpers.py` is import-clean against
the standard library alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Error surface.
# ---------------------------------------------------------------------------


class UnsupportedChartError(Exception):
    """Chart construct outside the wave-1 cocotb scaffold scope.

    Per INV-S-HDL-5 / INV-S-HDL-D-5, every chart-author-facing
    rejection cites the chart construct + the wave/phase doc that owns
    the rule. wave-1 rejects parallel charts (they land in wave-2
    alongside the per-region harness shape).
    """


# ---------------------------------------------------------------------------
# Chart-IR walking — minimal, read-only per INV-S-HDL-D-3.
#
# We re-walk the same raw scjson dict SOS-08-C's walkers consume. The
# walker extracts ONLY what the wave-1 cocotb scaffold needs:
#   1. The list of state IDs in document order (for one-hot encoding).
#   2. The chart's initial state (for the reset-state assertion).
#   3. A presence flag for top-level <parallel> (the wave-1 reject path).
#
# We deliberately do NOT mutate or normalise the IR. INV-SOS-A and
# INV-S-HDL-D-3 forbid silent mutation at the emitter boundary.
# ---------------------------------------------------------------------------


@dataclass
class CocotbChart:
    """Minimal chart view this emitter consumes.

    The shape mirrors what SOS-08-C's single-region walker produces at
    its observation boundary but carries only the fields wave-1 needs.
    """

    name: str
    state_ids: list[str]
    initial_state: str
    has_parallel: bool = False
    # Vector ids the emitter was asked to bind tests against.
    vector_ids: list[str] = field(default_factory=list)


def _walk_states_in_order(node: dict[str, Any]) -> Iterable[tuple[str, dict]]:
    """Depth-first walk yielding (state_id, state_dict) in document
    order. Mirrors `transliterate_hdl_vhdl._walk_region_states` minus
    the parallel-region carve-out — wave-1 rejects parallel charts so
    this walk is single-region by construction.

    Per INV-S-HDL-C-1 (deterministic emission) the document-order walk
    is the canonical traversal SOS-08-C's encoding map already uses;
    we mirror it so the embedded `_STATE_ENCODING` dict matches the
    DUT's state-constant bit pattern exactly.
    """
    for st in node.get("state", []) or []:
        sid = st.get("id")
        if sid:
            yield sid, st
        # Descend into nested states (single-region chart may carry
        # nested compound states; we treat each as a leaf for one-hot
        # encoding purposes — same convention as SOS-08-C wave-1).
        yield from _walk_states_in_order(st)


def _detect_parallel(chart: dict[str, Any]) -> bool:
    """Return True iff the chart has any top-level <parallel> child
    OR any nested <parallel>. Wave-1 rejects both; wave-2 will lift
    the restriction once the per-region cocotb harness shape lands.
    """
    if chart.get("parallel"):
        return True
    for st in chart.get("state", []) or []:
        if st.get("parallel"):
            return True
        if _detect_parallel(st):
            return True
    return False


def _resolve_initial_state(chart: dict[str, Any], state_ids: list[str]) -> str:
    """Return the chart's `<initial>` state, defaulting to the first
    state in document order per SCXML semantics + SOS-08-C §5.6 /
    PCDN-C-003 (reset = <initial>)."""
    initial = chart.get("initial")
    if isinstance(initial, list):
        initial = initial[0] if initial else None
    if isinstance(initial, str) and initial:
        return initial
    if not state_ids:
        raise UnsupportedChartError(
            "SOS-08-D wave-1 cocotb emitter requires at least one <state> "
            "in the chart; none found. (Parallel charts land in wave-2 "
            "alongside the per-region cocotb harness — SOS-08-D §15.)"
        )
    return state_ids[0]


def _normalise_chart(
    chart_ir: dict[str, Any],
    chart_name: str,
    vector_ids: list[str],
) -> CocotbChart:
    """Re-walk the raw scjson dict into the minimal view this emitter
    consumes. Rejects parallel charts up front per the wave-1 scope.
    """
    if not isinstance(chart_ir, dict):
        raise UnsupportedChartError(
            "SOS-08-D wave-1 render_target expects the raw scjson dict, "
            f"not {type(chart_ir).__name__}. The main.py dispatcher "
            "passes the parsed scjson AST."
        )

    if _detect_parallel(chart_ir):
        raise UnsupportedChartError(
            "SOS-08-D wave-1 cocotb scaffold rejects parallel charts; "
            "parallel charts land in wave-2 alongside the per-region "
            "cocotb harness shape (SOS-08-D §15 / SOS-08-D §6.1)."
        )

    state_ids = [sid for sid, _st in _walk_states_in_order(chart_ir)]
    if not state_ids:
        raise UnsupportedChartError(
            "SOS-08-D wave-1 cocotb emitter requires at least one <state> "
            f"in chart '{chart_name}'; none found."
        )

    initial = _resolve_initial_state(chart_ir, state_ids)
    return CocotbChart(
        name=chart_name,
        state_ids=state_ids,
        initial_state=initial,
        has_parallel=False,
        vector_ids=list(vector_ids),
    )


# ---------------------------------------------------------------------------
# Identifier conventions — cross-dialect parity with SOS-08-C walkers.
# ---------------------------------------------------------------------------


def _safe_ident(raw: str) -> str:
    """Mirror SOS-08-C's `_safe_ident` so the cocotb test's references
    to the DUT module name + state constants match the VHDL/SV emit
    byte-for-byte (INV-S-HDL-C-1)."""
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in (raw or ""))
    if safe and safe[0].isdigit():
        safe = "x" + safe
    return safe.lower()


def _dut_module_name(chart_name: str) -> str:
    """SOS-08-C single-region convention: `<chart>_fsm`. Wave-1 cocotb
    binds to this DUT name by default; callers MAY override via
    `config.dut_module` for vendor-shim variants (SOS-08-A §5.3)."""
    return f"{_safe_ident(chart_name)}_fsm"


def _state_constant_name(state_id: str) -> str:
    """Mirror SOS-08-C's per-dialect `ST_<UPPER>` convention so the
    embedded `_STATE_ENCODING` dict's keys can serve as both the chart
    state-id (per INV-S-HDL-D-5 chart-vocabulary failure message) AND
    the synthesizable RTL state constant name."""
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in (state_id or ""))
    return f"ST_{safe.upper()}"


def _slugify_vector_id(vector_id: str) -> str:
    """SOS-03 §6.3-style slug, narrowed for Python identifier usage.

    The cocotb test function name is `test_vector_<slug>` so JUnit XML
    attribution (per §6.7 / INV-S-HDL-D-6) names the failing vector
    unambiguously. We accept either a raw vector id (`000-reset`) or a
    full SOS-03 slug (`0007-two-tasks-yield`) and produce a Python-
    identifier-safe form.
    """
    if not vector_id:
        return "unnamed"
    # Lowercase, replace non-[a-z0-9_] with underscore (Python idents
    # don't permit hyphens; SOS-03 slugs use hyphens — translate).
    lowered = vector_id.lower()
    out = re.sub(r"[^a-z0-9_]+", "_", lowered)
    out = re.sub(r"_+", "_", out).strip("_")
    if not out:
        return "unnamed"
    if out[0].isdigit():
        out = "v" + out
    return out


# ---------------------------------------------------------------------------
# State encoding — mirror SOS-08-C §5.1 one-hot.
# ---------------------------------------------------------------------------


def _one_hot_encoding(state_ids: list[str]) -> dict[str, int]:
    """Return ``{state_id: one_hot_int_value}`` mirroring SOS-08-C
    `hdl_common.emit_fsm_state_encoding(ONE_HOT)`.

    State 0 (document-order first) maps to bit 0 → integer 1; state 1
    to integer 2; state k to integer ``1 << k``. The bit ordering
    matches `_one_hot_value` in both VHDL + SV walkers so the cocotb
    test's `dut.current_state.value` integer compare lines up with
    the synthesised state register exactly (INV-S-HDL-C-1 cross-
    dialect determinism extended to the test harness).
    """
    return {sid: (1 << i) for i, sid in enumerate(state_ids)}


# ---------------------------------------------------------------------------
# Emit — per-artifact bodies.
# ---------------------------------------------------------------------------


# Header preamble line that goes at the top of every emitted Python /
# Makefile / pytest.ini / README file. Tooling that scans for codegen
# provenance grep's this string.
_GEN_HEADER = (
    "Generated by tools/sos-codegen/transliterate_cocotb.py (SOS-08-D wave-1 scaffold)."
)


def _emit_helpers_py(
    chart: CocotbChart,
    encoding: dict[str, int],
) -> str:
    """Emit ``_cocotb_helpers.py`` — load_vector, assert_state,
    format_failure, plus the chart-derived `_STATE_ENCODING` map.

    Per PCDN-D-006 / §5.6 shared helpers live alongside the cocotb
    test module; they are NOT a separate package. Wave-1 keeps the
    helper module dependency-free (json + pathlib from the stdlib
    only) so it can be imported even before cocotb is installed.
    """
    # Build the encoding map as a stable, sorted-by-bit-position dict
    # literal so the emit is deterministic per INV-S-HDL-C-1 / INV-
    # S-HDL-D-3.
    encoding_lines: list[str] = []
    for sid, value in sorted(encoding.items(), key=lambda kv: kv[1]):
        # state id → one-hot int. The string-quoted state id is the
        # chart-side state name; the integer is the synthesised RTL
        # value (matches SOS-08-C `_one_hot_value`'s bit-position
        # convention so `dut.current_state.value` equality holds).
        encoding_lines.append(f"    {sid!r}: 0b{value:0{len(encoding)}b},  # {_state_constant_name(sid)}")
    encoding_block = "\n".join(encoding_lines) if encoding_lines else "    # (no chart states found)"

    body = f'''"""Shared cocotb helpers for chart `{chart.name}`.

{_GEN_HEADER}

Per SOS-08-D §6.6 (chart-vocabulary failure-message rendering) and
INV-S-HDL-D-5 (chart-vocabulary failure messages). The helpers below
are intentionally dependency-free against the cocotb runtime so they
can be imported and unit-tested without a simulator present; the
chart-state encoding map mirrors SOS-08-C's one-hot encoding so
`dut.current_state.value` compares byte-identically against the
synthesised state register (INV-S-HDL-C-1).

Per PCDN-SOS-08-D-005 / §5.3, this module assumes Python 3.10+.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# Chart-derived state encoding (one-hot per SOS-08-C §5.1 / PCDN-002).
# State 0 (document-order first) → bit 0; state k → bit k. The integer
# values match the synthesised state register exactly so the cocotb
# assertion can compare ints without re-decoding the one-hot literal.
_STATE_ENCODING: dict[str, int] = {{
{encoding_block}
}}

# Chart-side identifiers — embedded so chart-vocabulary failure
# messages can render the chart name + initial state per INV-S-HDL-D-5.
_CHART_NAME: str = {chart.name!r}
_INITIAL_STATE: str = {chart.initial_state!r}


def load_vector(path: Path | str) -> dict[str, Any]:
    """Load a SOS-03 vector trace from disk.

    Wave-1 accepts both JSON (a single top-level vector object) and
    JSONL (one vector event per line, the SOS-03 PCDN-009 canonical
    form) — when the path's suffix is `.jsonl` each line is parsed
    as an event and bundled into a ``{{"events": [...]}}`` envelope.

    Per INV-S-HDL-D-3 (vector-IR read-only at the emitter boundary)
    this helper never mutates the file; it returns the parsed dict
    as-is for the test body to walk.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".jsonl":
        events = [json.loads(line) for line in text.splitlines() if line.strip()]
        return {{"id": p.stem, "events": events}}
    return json.loads(text)


def assert_state(dut: Any, expected_state_id: str, failure_ctx: str) -> None:
    """Chart-vocabulary state assertion helper.

    Maps the chart-side state id to its one-hot RTL value via the
    embedded `_STATE_ENCODING` dict; asserts ``dut.current_state``
    matches; on mismatch raises ``AssertionError`` carrying the
    chart-vocabulary failure message per SOS-08-D §6.6 / INV-S-HDL-D-5.

    The failure message names:
      - the chart-side state id (NOT the raw RTL bit pattern alone)
      - the observed RTL one-hot pattern in binary
      - the failure context the caller constructed via
        `format_failure(vector, step)`.

    A failure that surfaces only the raw RTL signal trace is a
    verification-emission bug per INV-S-HDL-D-5, not a passing test.
    """
    if expected_state_id not in _STATE_ENCODING:
        raise AssertionError(
            f"chart-state mismatch in test {{failure_ctx}}: expected state "
            f"{{expected_state_id!r}} is not a known state of chart "
            f"{{_CHART_NAME!r}}. Known states: {{sorted(_STATE_ENCODING)!r}}. "
            f"Chart-vocabulary failure per INV-SOS-H + SOS-08-D §6.6."
        )
    expected = _STATE_ENCODING[expected_state_id]
    try:
        observed = int(dut.current_state.value)
    except Exception as exc:  # pragma: no cover - simulator-side surface
        raise AssertionError(
            f"chart-state read failure in test {{failure_ctx}}: could not "
            f"convert dut.current_state.value to int ({{exc}}). "
            f"Expected state {{expected_state_id!r}} (one-hot=0b{{expected:b}}). "
            f"Chart-vocabulary failure per INV-SOS-H + SOS-08-D §6.6."
        ) from exc
    if observed != expected:
        raise AssertionError(
            f"chart-state mismatch in test {{failure_ctx}}: "
            f"expected state {{expected_state_id!r}} (one-hot=0b{{expected:b}}), "
            f"observed one-hot=0b{{observed:b}}. "
            f"Chart-vocabulary failure per INV-SOS-H + SOS-08-D §6.6."
        )


def format_failure(vector: dict[str, Any], step: dict[str, Any] | None = None) -> str:
    """Render the SOS-08-D §6.6 chart-vocabulary failure-context string.

    The string carries:
      - chart name (constant — embedded at emit time)
      - vector id (from `vector["id"]` or `vector["name"]`)
      - step index + transition id when a step is supplied
      - expected state when present on the step

    Per INV-S-HDL-D-5: every cocotb assertion failure MUST render
    with chart-vocabulary metadata. The caller passes the result of
    this helper as `assert_state`'s `failure_ctx`.
    """
    vector_id = vector.get("id") or vector.get("name") or "<unnamed-vector>"
    if step is None:
        return f"chart={{_CHART_NAME}} vector={{vector_id}}"
    step_index = step.get("index", step.get("after_input_idx", "?"))
    transition_id = step.get("transition_id", step.get("event", "-"))
    expected_state = step.get("expected_state", "-")
    return (
        f"chart={{_CHART_NAME}} vector={{vector_id}} "
        f"step={{step_index}} transition_id={{transition_id}} "
        f"expected_state={{expected_state}}"
    )
'''
    return body


def _emit_test_py(chart: CocotbChart, config: "_CocotbConfig") -> str:
    """Emit ``test_<chart_name>_fsm.py`` — the cocotb driver.

    Per PCDN-D-003 / §5.5: one @cocotb.test() per vector. The function
    body loads the vector at test runtime, drives the clock + reset,
    walks the vector steps (if any) asserting state per step, then
    asserts the terminal state.
    """
    dut_module = config.dut_module or _dut_module_name(chart.name)
    test_funcs: list[str] = []
    for vec in chart.vector_ids:
        slug = _slugify_vector_id(vec)
        func = _emit_one_test_function(
            vector_id=vec,
            slug=slug,
            clock_period_ns=config.clock_period_ns,
            reset_cycles=config.reset_cycles,
            initial_state=chart.initial_state,
        )
        test_funcs.append(func)

    funcs_block = "\n\n".join(test_funcs)

    body = f'''"""Cocotb testbench for chart `{chart.name}` (DUT: `{dut_module}`).

{_GEN_HEADER}

One @cocotb.test() function per vector per PCDN-SOS-08-D-003 / §5.5
(per-vector test isolation default; --group-by-region opt-in lands
in wave-2). Each test:

  1. Loads the vector from ``vectors/<vector_id>.json`` at runtime
     (the vector authoring is a separate concern per SOS-03 §6.2 /
     INV-S-HDL-D-3 — the emitter never embeds vector contents).
  2. Starts a {config.clock_period_ns} ns clock on ``dut.clk``
     (100 MHz default; matches the ``sos_fifo_sync`` testbench pattern
     and SOS-08-A acceptance gates).
  3. Asserts ``dut.rst`` for {config.reset_cycles} cycles synchronously
     (SOS-08-A INV-S-HDL-A-1 uniform sync active-high reset).
  4. Walks ``vector["steps"]`` (if present) asserting `expected_state`
     against ``dut.current_state`` after each step.
  5. Asserts the terminal state per ``vector["expected_terminal_state"]``
     (defaults to the chart's initial state when absent — SOS-03 minimal
     vector shape).

Failure messages render in chart vocabulary per SOS-08-D §6.6 /
INV-S-HDL-D-5 (chart-vocabulary failure messages — a failure that
surfaces only RTL signal traces is a verification-emission bug).
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

from _cocotb_helpers import assert_state, format_failure, load_vector


_VECTORS_DIR = Path(__file__).parent / "vectors"
_CLOCK_PERIOD_NS = {config.clock_period_ns}
_RESET_CYCLES = {config.reset_cycles}


async def _apply_reset(dut) -> None:
    """SOS-08-A INV-S-HDL-A-1: synchronous active-high reset, asserted
    for {config.reset_cycles} clock cycles, then deasserted."""
    dut.rst.value = 1
    for _ in range(_RESET_CYCLES):
        await RisingEdge(dut.clk)
    dut.rst.value = 0


{funcs_block}
'''
    return body


def _emit_one_test_function(
    vector_id: str,
    slug: str,
    clock_period_ns: int,
    reset_cycles: int,
    initial_state: str,
) -> str:
    """Emit one ``@cocotb.test()`` async function for a single vector.

    Per §6.2 / §6.5: the function loads the vector, walks its `steps`
    if present, then asserts the terminal state. The vector file is
    expected at ``vectors/<vector_id>.json`` at TEST runtime — the
    emitter does NOT embed the vector contents (INV-S-HDL-D-3).
    """
    return f'''@cocotb.test()
async def test_vector_{slug}(dut):
    """SOS-08-D wave-1 — vector {vector_id!r}."""
    vector = load_vector(_VECTORS_DIR / "{vector_id}.json")
    cocotb.start_soon(Clock(dut.clk, _CLOCK_PERIOD_NS, units="ns").start())
    await _apply_reset(dut)

    # After reset deassertion, the DUT MUST be in the chart's <initial>
    # state per SOS-08-C §5.6 / PCDN-C-003. We assert that BEFORE walking
    # the vector's steps so a wedged-at-reset DUT surfaces here, not
    # downstream where the chart-vocabulary attribution is murkier.
    await RisingEdge(dut.clk)
    assert_state(dut, {initial_state!r}, format_failure(vector))

    # Walk vector steps if present (SOS-03 §7.1 extended for HDL targets;
    # each step may carry `inputs` to drive, `expected_state` to assert,
    # and a `transition_id` for chart-vocabulary failure attribution).
    for step in vector.get("steps", []) or []:
        # Drive input stimuli — wave-1 supports a flat `{{port: value}}`
        # map on each step. Vector authors who name a port absent on
        # the DUT will get a cocotb signal-resolution AttributeError;
        # that surfaces as an ERROR per §6.5 (test-infrastructure
        # failure), distinct from a chart-vocabulary FAIL.
        for port_name, port_value in (step.get("inputs") or {{}}).items():
            getattr(dut, port_name).value = port_value
        await RisingEdge(dut.clk)
        expected_state = step.get("expected_state")
        if expected_state is not None:
            assert_state(dut, expected_state, format_failure(vector, step))

    # Final assertion: chart ended in the expected terminal state.
    # Defaults to the chart's initial state for minimal vectors that
    # only verify the reset-baseline (SOS-03 minimal vector shape).
    terminal = vector.get("expected_terminal_state", {initial_state!r})
    assert_state(dut, terminal, format_failure(vector))
'''


def _emit_makefile(chart: CocotbChart, dut_module: str) -> str:
    """Emit ``Makefile`` — cocotb-classic invocation (PCDN-D-001 +
    PCDN-D-007). `SIM ?= verilator` per PCDN-D-001 resolution.

    The Makefile assumes the chart's RTL has been emitted by the
    SOS-08-C walkers into a sibling directory; the user composes
    `VERILOG_SOURCES` with the canonical SOS-08-A / SOS-08-B / SOS-08-C
    layout. The wave-1 Makefile keeps the source list generic with a
    `RTL_DIR` knob so the same Makefile works regardless of where the
    RTL lives in the host repo.
    """
    chart_id = _safe_ident(chart.name)
    return f"""# {_GEN_HEADER}
#
# Cocotb-classic Makefile per SOS-08-D §6.4 (simulator-invocation
# conventions) + PCDN-SOS-08-D-001 (Verilator default) + PCDN-D-007
# (Makefile + pytest.ini both emitted).
#
# Per SOS-08-D §5.1 / INV-S-HDL-D-2, Verilator is the primary target;
# Icarus + GHDL remain acceptance targets at v1.
#
#   make sim SIM=verilator   # default
#   make sim SIM=icarus
#   make sim SIM=ghdl        # VHDL-pure DUTs only
#
# Cites: SOS-08-D-CONCEPTS.md §6.4, §15 (ratified 2026-05-23).

SIM ?= verilator
TOPLEVEL_LANG ?= verilog
TOPLEVEL ?= {dut_module}
MODULE ?= test_{chart_id}_fsm

# RTL_DIR points at the host-repo location holding the chart's emitted
# RTL. Override on the command line: `make sim RTL_DIR=../../../rtl`.
RTL_DIR ?= ../../../rtl

VERILOG_SOURCES += $(RTL_DIR)/{chart_id}/{dut_module}.sv

# Verilator wave dump + trace for debugging; harmless on Icarus.
ifeq ($(SIM),verilator)
    EXTRA_ARGS += --trace --trace-structs
endif

include $(shell cocotb-config --makefiles)/Makefile.sim
"""


def _emit_pytest_ini(chart: CocotbChart) -> str:
    """Emit ``pytest.ini`` — cocotb-test invocation (PCDN-D-007).

    The pytest runner consumes the same module + DUT names the Makefile
    does; the two paths produce equivalent JUnit XML (PCDN-D-002).
    """
    chart_id = _safe_ident(chart.name)
    return f"""# {_GEN_HEADER}
#
# Pytest runner config per SOS-08-D §6.4 (alternative `pytest` runner
# via `cocotb-test`) + PCDN-SOS-08-D-007 (Makefile + pytest.ini both
# emitted). Identical test attribution + simulator selection as the
# Makefile path; different orchestrator.
#
# Cites: SOS-08-D-CONCEPTS.md §6.4, §15 (ratified 2026-05-23).

[pytest]
testpaths = .
python_files = test_{chart_id}_fsm.py
addopts = -ra --tb=short
"""


def _emit_readme(chart: CocotbChart, dut_module: str, config: "_CocotbConfig") -> str:
    """Emit ``README.md`` — chart-side traceability metadata per §6.1.

    Per PCDN-D-005 / §5.3 the minimum Python version (3.10+) is
    documented here; per §6.2 the chart-side traceability metadata
    (chart file, region, invariants) names the chart this test
    directory was generated from.
    """
    chart_id = _safe_ident(chart.name)
    vector_lines: list[str] = []
    for vid in chart.vector_ids:
        slug = _slugify_vector_id(vid)
        vector_lines.append(f"- `{vid}.json` → `test_vector_{slug}`")
    vector_block = "\n".join(vector_lines) if vector_lines else "- _(no vectors bound at emit time)_"

    return f"""# Cocotb testbench — chart `{chart.name}`

{_GEN_HEADER}

Per SOS-08-D-CONCEPTS.md §6.1 (emit directory layout), §6.2
(per-vector cocotb test function shape), §5.3 (Python 3.10+ minimum
per PCDN-D-005), and §15 (ratified 2026-05-23 — PCDN-D-001..007
resolved).

## DUT

- **Module**: `{dut_module}` (SOS-08-C single-region convention —
  `<chart>_fsm`; override via `config.dut_module` for vendor-shim
  variants per SOS-08-A §5.3).
- **Chart**: `{chart.name}`
- **Initial state**: `{chart.initial_state}` (SCXML `<initial>` per
  PCDN-C-003 / SOS-08-C §5.6).
- **States** ({len(chart.state_ids)}): {", ".join(f"`{s}`" for s in chart.state_ids)}

## Requirements

- **Python 3.10+** (PCDN-SOS-08-D-005 / §5.3; matches parent-repo
  pinning and future-proofs against cocotb 2.x adoption).
- `cocotb ~= 1.9` (cocotb-classic at v1 per SOS-08 PCDN-004).
- `cocotb-test` (for the `pytest` runner path per PCDN-D-007).
- At least one of: Verilator (primary per PCDN-D-001 / §5.1), Icarus
  Verilog (secondary), GHDL (VHDL-pure DUTs only).

## Running

```bash
# Cocotb-classic Makefile path (canonical):
make sim                   # SIM=verilator (PCDN-D-001 default)
make sim SIM=icarus
make sim SIM=ghdl          # VHDL-pure DUTs only

# Pytest runner path (PCDN-D-007 alternative):
pytest
```

Both paths produce equivalent JUnit XML per PCDN-D-002. CI consumes
`build/results.xml` (cocotb's native xunit shape at wave-1; the
SOS-08-D §6.7 `post_results.py` JUnit XML post-processor lands in
wave-2 alongside the SVA bind file co-emission).

## Vectors

Bound at emit time:

{vector_block}

Vector files live under `vectors/` and are loaded at test runtime
per INV-S-HDL-D-3 (vector-IR is read-only at the emitter boundary;
the emitter never embeds vector contents). The SOS-03 §7.1 schema is
the vector format; HDL-target fields (`steps`, `expected_state`,
`expected_terminal_state`, `transition_id`) extend the schema per
SOS-08-D §10 reconciliation (the SOS-03 §15 amendment co-lands with
SOS-08-D implementation).

## Failure surfacing

Every assertion failure renders in chart vocabulary per SOS-08-D §6.6
and INV-S-HDL-D-5. Failures name:

- The chart name + vector id.
- The step index + transition id (when a step is supplied).
- The expected chart-state ID (NOT the raw RTL bit pattern alone).
- The observed one-hot RTL value in binary (for diagnostic context).

A failure that surfaces only RTL signal traces is a verification-
emission bug per INV-S-HDL-D-5, not a passing test.

## Configuration constants

- Clock period: **{config.clock_period_ns} ns** ({1000 // config.clock_period_ns if config.clock_period_ns else 0} MHz).
- Reset cycles: **{config.reset_cycles}** (synchronously high at test
  start; SOS-08-A INV-S-HDL-A-1).
"""


# ---------------------------------------------------------------------------
# Config shim — accept either a dict or an object exposing the same fields.
# ---------------------------------------------------------------------------


@dataclass
class _CocotbConfig:
    chart_name: str = "chart"
    vector_ids: list[str] = field(default_factory=list)
    dut_module: Optional[str] = None
    clock_period_ns: int = 10
    reset_cycles: int = 5


def _coerce_config(config: Any) -> _CocotbConfig:
    """Normalise the user-supplied config into the internal shape.

    Accepts:
      - ``None`` (use defaults).
      - ``dict`` (legacy CLI-supplied shape).
      - Any object exposing the named attributes (e.g. ``HdlEmitConfig``
        extended with cocotb-specific fields by the sibling agent).
    """
    if config is None:
        return _CocotbConfig()
    if isinstance(config, dict):
        return _CocotbConfig(
            chart_name=str(config.get("chart_name") or "chart"),
            vector_ids=list(config.get("vector_ids") or []),
            dut_module=config.get("dut_module"),
            clock_period_ns=int(config.get("clock_period_ns") or 10),
            reset_cycles=int(config.get("reset_cycles") or 5),
        )
    return _CocotbConfig(
        chart_name=str(getattr(config, "chart_name", None) or "chart"),
        vector_ids=list(getattr(config, "vector_ids", None) or []),
        dut_module=getattr(config, "dut_module", None),
        clock_period_ns=int(getattr(config, "clock_period_ns", None) or 10),
        reset_cycles=int(getattr(config, "reset_cycles", None) or 5),
    )


# ---------------------------------------------------------------------------
# Scaffold vector — emitted alongside the test files so the wave-1
# directory is self-contained on disk. The author replaces this with a
# real SOS-03 vector at suite-population time.
# ---------------------------------------------------------------------------


def _emit_scaffold_vector(chart: CocotbChart, vector_id: str) -> str:
    """Emit a minimal `vectors/<vector_id>.json` fixture so the wave-1
    test runs end-to-end on a freshly-emitted directory.

    The scaffold vector exercises the reset baseline only: no steps,
    terminal state = initial state. SOS-03 §7.1 minimal-vector shape.
    Vector authors replace this with real chart-derived expected
    traces per SOS-03 §6.6.
    """
    import json as _json
    payload = {
        "id": vector_id,
        "name": vector_id,
        "description": (
            "SOS-08-D wave-1 scaffold reset-baseline vector. "
            "Asserts that after the SOS-08-A INV-S-HDL-A-1 synchronous "
            "active-high reset the DUT lands in the chart's <initial> "
            f"state ({chart.initial_state!r}). Replace with a real "
            "SOS-03 §7.1 vector at suite-population time."
        ),
        "steps": [],
        "expected_terminal_state": chart.initial_state,
    }
    return _json.dumps(payload, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------


# Default scaffold vector id used when the caller supplies no vectors.
_DEFAULT_SCAFFOLD_VECTOR = "000-reset"


def render_target(chart_ir: dict, config: Any = None) -> dict[str, str]:
    """Emit cocotb test files for the chart.

    Returns a ``{filename: source}`` dict containing:
      - ``test_<chart_name>_fsm.py``  the cocotb driver (one
        @cocotb.test per vector per PCDN-D-003 / §5.5).
      - ``_cocotb_helpers.py``        shared helpers (load_vector,
        assert_state, format_failure) per PCDN-D-006 / §5.6.
      - ``Makefile``                  cocotb-classic invocation
        (PCDN-D-001 default `SIM ?= verilator`; PCDN-D-007).
      - ``pytest.ini``                cocotb-test invocation
        (PCDN-D-007).
      - ``README.md``                 chart-side traceability +
        Python 3.10+ minimum (PCDN-D-005 / §5.3) + simulator-selection
        notes (PCDN-D-001 / §5.1).
      - ``vectors/<vector_id>.json``  one minimal scaffold vector per
        bound vector id, so the wave-1 directory is end-to-end
        runnable on emit.

    Per INV-S-HDL-D-3 (vector-IR read-only at the emitter boundary)
    this function NEVER mutates the input ``chart_ir`` dict. Per INV-
    S-HDL-C-1 (deterministic emission, extended to the test harness)
    the same input produces byte-identical output.

    Args:
      chart_ir: Raw scjson dict — the same shape SOS-08-C walkers
        consume. The function rejects non-dict input + parallel
        charts (wave-1 scope per SOS-08-D §15).
      config: Optional dict or object exposing ``chart_name``,
        ``vector_ids``, ``dut_module``, ``clock_period_ns``,
        ``reset_cycles``. Missing fields fall back to defaults.

    Raises:
      UnsupportedChartError: Parallel charts (wave-2 scope); empty
        state list; non-dict ``chart_ir``.
    """
    cfg = _coerce_config(config)

    # If the caller supplied no vector ids, emit the wave-1 scaffold
    # vector. This makes the emitted directory end-to-end runnable
    # against the SOS-08-A INV-S-HDL-A-1 reset-baseline contract
    # before the vector authoring pipeline lands.
    if not cfg.vector_ids:
        cfg.vector_ids = [_DEFAULT_SCAFFOLD_VECTOR]

    chart = _normalise_chart(chart_ir, cfg.chart_name, cfg.vector_ids)
    encoding = _one_hot_encoding(chart.state_ids)
    dut_module = cfg.dut_module or _dut_module_name(chart.name)

    out: dict[str, str] = {}
    out[f"test_{_safe_ident(chart.name)}_fsm.py"] = _emit_test_py(chart, cfg)
    out["_cocotb_helpers.py"] = _emit_helpers_py(chart, encoding)
    out["Makefile"] = _emit_makefile(chart, dut_module)
    out["pytest.ini"] = _emit_pytest_ini(chart)
    out["README.md"] = _emit_readme(chart, dut_module, cfg)

    # Scaffold vector files (one per bound vector id) so the emitted
    # directory is end-to-end runnable. Authors replace these with
    # real SOS-03 §7.1 vectors at suite-population time.
    for vid in chart.vector_ids:
        out[f"vectors/{vid}.json"] = _emit_scaffold_vector(chart, vid)

    return out


# ---------------------------------------------------------------------------
# Test-helper re-exports (mirror the SOS-08-C walkers' surface so the
# test module can grep / assert on the same identifier shapes).
# ---------------------------------------------------------------------------


def dut_module_name(chart_name: str) -> str:
    """Return the DUT module name this emitter binds against by
    default. Mirrors SOS-08-C single-region convention `<chart>_fsm`."""
    return _dut_module_name(chart_name)


def state_constant_name(state_id: str) -> str:
    """Mirror SOS-08-C's `_state_constant_name` so cross-dialect
    tests can grep the same identifier shape."""
    return _state_constant_name(state_id)


def one_hot_encoding(state_ids: list[str]) -> dict[str, int]:
    """Mirror SOS-08-C `hdl_common.emit_fsm_state_encoding(ONE_HOT)`."""
    return _one_hot_encoding(state_ids)


def slugify_vector_id(vector_id: str) -> str:
    """Public re-export for testing the Python-identifier-safe slug."""
    return _slugify_vector_id(vector_id)

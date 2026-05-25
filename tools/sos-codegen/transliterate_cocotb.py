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

# SOS-08-G wave-1 extension (waveform annotation emission)

@spec  SOS-08-G-CONCEPTS.md §5 (frozen decisions — three-file output
       contract `.fst` + `.vcd` + `<test>.annotations.jsonl` per
       EOQ-011-ROADMAP; overlay schema v1.0 per §5.2 + PCDN-G-001),
       §5.6 (one annotation file per test run per PCDN-G-003),
       §5.7 (per-event default annotation granularity per PCDN-G-005;
       cycle-density opt-in via SOS_ANNOTATION_DENSITY=cycle env var),
       §6 (viewer integration contract — GTKWave / Surfer extensions
       consume the annotation overlay), §15 (ratified 2026-05-23).
@spec  PCDN-SOS-08-G-001 — schema-version detection via first-line
       header record `{"_meta": {"schema": "sos-08-g/annotations",
       "version": "1.0", "chart_path_max_depth": 8}}`.
@spec  PCDN-SOS-08-G-003 — one `.annotations.jsonl` per test run.
@spec  PCDN-SOS-08-G-004 — viewer extensions live in-subrepo at
       `tools/sos-codegen/viewers/{gtkwave,surfer}/` (sibling-agent
       deliverable; this module emits the overlay they consume).
@spec  PCDN-SOS-08-G-005 — per-event default granularity; cycle-density
       opt-in honored via SOS_ANNOTATION_DENSITY environment variable.
@spec  PCDN-SOS-08-G-006 — line-buffered flush (Python `open(...,
       buffering=1)`); per-record flush available via simulator-side
       opt-in (the helper exposes the file handle in line-buffered mode
       so each `\n` triggers a flush — sufficient for review-side mid-
       run inspection without per-record fsync overhead).
@spec  INV-S-HDL-G-2 — chart-vocabulary mandatory in overlay; every
       annotation record carries `chart_state` + `transition_id` so
       review-surface readers can name what the hardware did at chart
       vocabulary level (NOT raw RTL signal toggles alone).
@spec  INV-S-HDL-G-3 — schema-version header required as first line.
@spec  INV-S-HDL-G-5 — generation co-location: the annotation writer
       is instrumented INSIDE the cocotb test (this emitter wires it
       into every @cocotb.test() body), NOT a separate post-process.

# Integration contract

The codegen tool's CLI dispatcher (`main.py`) is intended to extend
with `--target cocotb` (sibling-agent's work). Per PCDN-SOS-08-D-
wave1-file-layout (ratified 2026-05-23) every returned key is
already prefixed with ``tests/<chart>/``, so the dispatcher writes
each file at ``out_dir / fname`` without re-prefixing:

    from transliterate_cocotb import render_target
    files = render_target(chart_ir, config)
    for fname, body in files.items():
        (out_dir / fname).parent.mkdir(parents=True, exist_ok=True)
        (out_dir / fname).write_text(body)

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
class CocotbRegion:
    """One chart region — SOS-08-D wave-2c parallel-chart shape.

    Per SOS-08-C §6.10 chart-top wrapper emission: each region of a
    parallel chart contributes one ``<chart>_region_<name>_fsm``
    sub-module instantiated by the chart-top wrapper, with the wrapper
    exposing a ``current_state_<name>`` output port per region. The
    cocotb test reads that per-region port through the chart-top wrapper
    DUT to verify per-region state.
    """

    name: str
    state_ids: list[str]
    initial_state: str


@dataclass
class CocotbChart:
    """Minimal chart view this emitter consumes.

    Single-region charts (wave-1) populate ``state_ids`` + ``initial_state``
    and leave ``regions`` empty. Parallel charts (wave-2c, 2026-05-23)
    additionally populate ``regions`` with per-region state lists +
    initial states; the emitted test branches on ``has_parallel`` to
    read ``current_state_<region>`` per region.

    State-encoding parity: for parallel charts ``state_ids`` is the
    union of all regions' state ids in document order so the chart-
    wide ``_STATE_ENCODING`` map remains a single-source-of-truth
    even when individual regions only reference their own slice.
    """

    name: str
    state_ids: list[str]
    initial_state: str
    has_parallel: bool = False
    # Vector ids the emitter was asked to bind tests against.
    vector_ids: list[str] = field(default_factory=list)
    # SOS-08-D wave-2c: per-region info for parallel charts; empty
    # tuple for single-region (wave-1 path unchanged).
    regions: list[CocotbRegion] = field(default_factory=list)
    # SOS-08-G wave-2: per-state chart_path lists (per §5.2 +
    # PCDN-G-002 — max depth 8). Wave-1 emitted single-segment
    # chart_path=[state_id]; wave-2 walks the SCXML hierarchy at
    # emit time so each state's path is rooted at the chart name
    # and threads through every parent state / parallel region.
    chart_paths: dict[str, list[str]] = field(default_factory=dict)


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


_CHART_PATH_MAX_DEPTH = 8
"""SOS-08-G PCDN-G-002 (resolved 2026-05-23) + PCDN-G-wave1-001 hybrid
header: chart_path is capped at 8 segments by reference from SOS-12.
The walker truncates anything deeper at emit time so the overlay's
`_meta.chart_path_max_depth` field remains the load-bearing depth
declaration."""


def _build_chart_paths(
    chart_ir: dict[str, Any], chart_name: str
) -> dict[str, list[str]]:
    """Build a ``{state_id: chart_path_list}`` map for the chart.

    SOS-08-G wave-2 (2026-05-23 §15): the annotation overlay's
    ``chart_path`` field per record (per §5.2 + INV-S-HDL-G-2) carries
    the chart-hierarchy path from the chart root to the named state.
    Wave-1 emitted ``chart_path=[state_id]`` (single-segment); wave-2
    walks the SCXML hierarchy at emit time to populate
    ``chart_path=[chart_name, parent_id, ..., state_id]`` per SOS-12
    recursive-dispatch vocabulary (separator `/` is render-side
    concern; the overlay stores the list form).

    Per PCDN-G-002 (resolved 2026-05-23) the max depth is 8 (mirrored
    from SOS-12). Paths deeper than the cap are truncated to the first
    8 segments at emit time; the truncation preserves the leaf state
    so chart-vocabulary attribution remains intact.

    Parallel charts: the path threads through each region's `<state>`
    container, so a state inside a region carries
    ``[chart_name, region_name, ..., state_id]``.

    Args:
        chart_ir: raw scjson dict.
        chart_name: chart identifier — first segment of every path.

    Returns:
        Mapping of every state-id reachable from chart_ir to its
        chart_path list. Capped at ``_CHART_PATH_MAX_DEPTH`` segments.
    """
    out: dict[str, list[str]] = {}

    def _walk(node: dict[str, Any], path: list[str]) -> None:
        # Recurse into <state> children.
        for st in node.get("state", []) or []:
            sid = st.get("id")
            if isinstance(sid, str) and sid:
                segment_path = (path + [sid])[:_CHART_PATH_MAX_DEPTH]
                out[sid] = segment_path
                _walk(st, segment_path)
            else:
                _walk(st, path)
        # Recurse into <parallel> wrappers — each <parallel> can name
        # sub-regions but the regions themselves are <state> children
        # of the parallel node.
        for par in node.get("parallel", []) or []:
            par_id = par.get("id")
            par_path = path
            if isinstance(par_id, str) and par_id:
                par_path = (path + [par_id])[:_CHART_PATH_MAX_DEPTH]
                out[par_id] = par_path
            _walk(par, par_path)

    _walk(chart_ir, [chart_name])
    return out


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
        # SOS-08-D wave-2c (2026-05-23 §15): parallel charts accepted.
        # Per-region observable read pattern lands here; SOS-08-C §6.10
        # chart-top wrapper exposes one `current_state_<region>` output
        # port per region.
        return _normalise_parallel_chart(chart_ir, chart_name, vector_ids)

    state_ids = [sid for sid, _st in _walk_states_in_order(chart_ir)]
    if not state_ids:
        raise UnsupportedChartError(
            "SOS-08-D cocotb emitter requires at least one <state> "
            f"in chart '{chart_name}'; none found."
        )

    initial = _resolve_initial_state(chart_ir, state_ids)
    return CocotbChart(
        name=chart_name,
        state_ids=state_ids,
        initial_state=initial,
        has_parallel=False,
        vector_ids=list(vector_ids),
        chart_paths=_build_chart_paths(chart_ir, chart_name),
    )


def _normalise_parallel_chart(
    chart_ir: dict[str, Any],
    chart_name: str,
    vector_ids: list[str],
) -> CocotbChart:
    """Build a parallel-chart ``CocotbChart`` per SOS-08-D wave-2c.

    For each ``<parallel>`` child ``<state>`` (each region):
      * Walk its state subtree in document order.
      * Resolve the region's initial state from ``<state initial="...">``
        (or first state in document order if missing).
      * Build a ``CocotbRegion`` carrying the region's name + state ids
        + initial state.

    The aggregate ``CocotbChart.state_ids`` is the union of all regions'
    state ids in document order (region-major). The aggregate
    ``initial_state`` is set to the first region's initial state — a
    placeholder for cross-region compatibility with the wave-1 code
    path; the parallel-chart test body branches to per-region
    assertions rather than reading the aggregate value.
    """
    regions: list[CocotbRegion] = []
    aggregate_state_ids: list[str] = []
    for par in chart_ir.get("parallel") or []:
        for region_state in par.get("state") or []:
            rname = region_state.get("id")
            if not isinstance(rname, str) or not rname:
                # Skip nameless region nodes — chart authors must name
                # every region (matches SOS-08-C wave-2 expectation).
                continue
            r_state_ids = [
                sid for sid, _st in _walk_states_in_order(region_state)
            ]
            if not r_state_ids:
                raise UnsupportedChartError(
                    f"SOS-08-D cocotb emitter: parallel chart "
                    f"'{chart_name}' region '{rname}' has no <state> "
                    f"children; every region must contribute at least "
                    f"one state."
                )
            r_initial = _resolve_initial_state(region_state, r_state_ids)
            regions.append(
                CocotbRegion(
                    name=rname,
                    state_ids=r_state_ids,
                    initial_state=r_initial,
                )
            )
            aggregate_state_ids.extend(r_state_ids)

    if not regions:
        raise UnsupportedChartError(
            f"SOS-08-D cocotb emitter: parallel chart '{chart_name}' "
            f"yielded zero regions; the top-level <parallel> must "
            f"contain at least one named <state> region."
        )

    return CocotbChart(
        name=chart_name,
        state_ids=aggregate_state_ids,
        initial_state=regions[0].initial_state,
        has_parallel=True,
        vector_ids=list(vector_ids),
        regions=regions,
        chart_paths=_build_chart_paths(chart_ir, chart_name),
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

    # SOS-08-D wave-2c: per-region state-encoding maps for parallel
    # charts. Each region has its own one-hot encoding (state 0 → bit 0
    # within the region's slice). The chart-top wrapper exposes one
    # `current_state_<region>` output per region; the test reads each
    # port and asserts against the region's encoding.
    region_encodings_block: str
    region_initials_block: str
    # SOS-08-G wave-2: per-state chart_path map (§5.2 + PCDN-G-002).
    # Walks the SCXML hierarchy at emit time so each annotation
    # record's `chart_path` carries the full root-to-leaf path
    # rather than the wave-1 single-segment `[state_id]` shape.
    chart_paths_lines: list[str] = []
    for sid in chart.state_ids:
        path = chart.chart_paths.get(sid, [chart.name, sid])
        chart_paths_lines.append(f"    {sid!r}: {path!r},")
    chart_paths_block = (
        "\n".join(chart_paths_lines)
        if chart_paths_lines
        else "    # (no states)"
    )

    if chart.has_parallel and chart.regions:
        region_enc_lines: list[str] = []
        region_init_lines: list[str] = []
        for r in chart.regions:
            r_enc = _one_hot_encoding(r.state_ids)
            r_inner: list[str] = []
            for sid, val in sorted(r_enc.items(), key=lambda kv: kv[1]):
                r_inner.append(
                    f"        {sid!r}: 0b{val:0{len(r_enc)}b},"
                )
            r_inner_block = "\n".join(r_inner) if r_inner else ""
            region_enc_lines.append(
                f"    {r.name!r}: {{\n{r_inner_block}\n    }},"
            )
            region_init_lines.append(
                f"    {r.name!r}: {r.initial_state!r},"
            )
        region_encodings_block = "\n".join(region_enc_lines)
        region_initials_block = "\n".join(region_init_lines)
    else:
        region_encodings_block = "    # (single-region chart; no per-region encodings)"
        region_initials_block = "    # (single-region chart; no per-region initials)"

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

SOS-08-G wave-1 extension (waveform annotation emission) lives at
the bottom of this module: ``AnnotationWriter`` writes the
``<test>.annotations.jsonl`` review-artifact overlay per SOS-08-G
§5.2 (overlay schema), §5.6 (one file per test run — PCDN-G-003),
§5.7 (per-event default granularity — PCDN-G-005), §5 (line-buffered
flush — PCDN-G-006). The schema-version header is emitted as the
first JSONL line per PCDN-G-001 / INV-S-HDL-G-3.
"""

from __future__ import annotations

import json
import os
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
_HAS_PARALLEL: bool = {chart.has_parallel!r}

# SOS-08-G wave-2: per-state chart_path map (§5.2 + PCDN-G-002 cap).
# Walks the SCXML hierarchy at emit time so each annotation record
# carries the full path from chart root to leaf state per SOS-12
# recursive-dispatch vocabulary. The test body looks up the path
# at runtime via ``_CHART_PATHS.get(state_id, [_CHART_NAME, state_id])``
# so a state added post-emit still gets a sensible default path.
_CHART_PATHS: dict[str, list[str]] = {{
{chart_paths_block}
}}

# SOS-08-D wave-2c: per-region state encodings + initial states for
# parallel charts. The chart-top wrapper exposes one `current_state_
# <region>` output port per region (per SOS-08-C §6.10); the test
# reads each port through `dut.current_state_<region>` and asserts
# against the region's encoding via `assert_region_state`. For
# single-region charts these maps are empty + unused.
_REGION_STATE_ENCODINGS: dict[str, dict[str, int]] = {{
{region_encodings_block}
}}

_REGION_INITIAL_STATES: dict[str, str] = {{
{region_initials_block}
}}


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


def assert_region_state(
    dut: Any,
    region_name: str,
    expected_state_id: str,
    failure_ctx: str,
) -> None:
    """Per-region chart-vocabulary state assertion (SOS-08-D wave-2c).

    For parallel charts the chart-top wrapper exposes one
    ``current_state_<region>`` output port per region per SOS-08-C
    §6.10. This helper:

      1. Looks up the per-region one-hot encoding in
         ``_REGION_STATE_ENCODINGS[region_name]``.
      2. Reads ``dut.current_state_<region>`` via getattr.
      3. Asserts equality with chart-vocabulary failure message.

    Mirrors :func:`assert_state` for the single-region case; differs
    only by routing through the region-specific encoding + observable
    port.

    Raises ``AssertionError`` (with chart vocabulary per INV-S-HDL-D-5)
    when the region name is unknown, the state id is not a member of
    the region's encoding, the observable cannot be read, or the
    observed value mismatches the expected.
    """
    if region_name not in _REGION_STATE_ENCODINGS:
        raise AssertionError(
            f"chart-state mismatch in test {{failure_ctx}}: region "
            f"{{region_name!r}} is not a known region of chart "
            f"{{_CHART_NAME!r}}. Known regions: "
            f"{{sorted(_REGION_STATE_ENCODINGS)!r}}. "
            f"Chart-vocabulary failure per INV-SOS-H + SOS-08-D §6.6."
        )
    region_encoding = _REGION_STATE_ENCODINGS[region_name]
    if expected_state_id not in region_encoding:
        raise AssertionError(
            f"chart-state mismatch in test {{failure_ctx}}: state "
            f"{{expected_state_id!r}} is not a known state of region "
            f"{{region_name!r}} (chart {{_CHART_NAME!r}}). Known "
            f"states: {{sorted(region_encoding)!r}}. Chart-vocabulary "
            f"failure per INV-SOS-H + SOS-08-D §6.6."
        )
    expected = region_encoding[expected_state_id]
    port_name = f"current_state_{{region_name}}"
    try:
        observed = int(getattr(dut, port_name).value)
    except Exception as exc:  # pragma: no cover - simulator-side surface
        raise AssertionError(
            f"chart-state read failure in test {{failure_ctx}}: could "
            f"not read dut.{{port_name}}.value ({{exc}}). Expected "
            f"state {{expected_state_id!r}} (one-hot=0b{{expected:b}}) "
            f"in region {{region_name!r}}. Chart-vocabulary failure "
            f"per INV-SOS-H + SOS-08-D §6.6."
        ) from exc
    if observed != expected:
        raise AssertionError(
            f"chart-state mismatch in test {{failure_ctx}}: region "
            f"{{region_name!r}} expected state "
            f"{{expected_state_id!r}} (one-hot=0b{{expected:b}}), "
            f"observed one-hot=0b{{observed:b}} on "
            f"dut.{{port_name}}. Chart-vocabulary failure per "
            f"INV-SOS-H + SOS-08-D §6.6."
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


# ---------------------------------------------------------------------------
# SOS-08-G annotation-overlay writer (waveform review-artifact emission).
#
# Per SOS-08-G §5 frozen decisions:
#   - PCDN-G-001: first-line schema-version header (single-file shape;
#     viewer extensions read the first line cheaply).
#   - PCDN-G-002: chart_path max depth = 8, mirrored by reference into
#     the schema header.
#   - PCDN-G-003: one `.annotations.jsonl` per test run.
#   - PCDN-G-005: per-event default; `SOS_ANNOTATION_DENSITY=cycle`
#     env var opts into per-cycle granularity for high-bandwidth debug.
#   - PCDN-G-006: line-buffered flush (`open(..., buffering=1)`); every
#     newline-terminated record is flushed without per-record fsync.
#   - INV-S-HDL-G-2: chart-vocabulary mandatory — every record carries
#     `chart_state` + `transition_id` (vector-to-chart traceability at
#     the review-surface layer; INV-SOS-H).
#   - INV-S-HDL-G-3: schema-version header required as first line.
#   - INV-S-HDL-G-5: generation co-located with the cocotb test (this
#     class is instantiated inside the @cocotb.test() body, NOT in a
#     separate post-process step).
# ---------------------------------------------------------------------------


class AnnotationWriter:
    """SOS-08-G chart-vocabulary annotation writer.

    Writes one JSONL record per chart-state transition observed
    during the cocotb test run. First record is the schema header
    (PCDN-SOS-08-G-001 / INV-S-HDL-G-3). Subsequent records are
    per-event annotations (PCDN-SOS-08-G-005 default; cycle-density
    opt-in via env var ``SOS_ANNOTATION_DENSITY=cycle``).

    Per PCDN-SOS-08-G-003 the file is one-per-test-run; per
    PCDN-SOS-08-G-006 the file handle is line-buffered so each
    record reaches disk on the trailing newline without per-record
    fsync overhead.

    Per INV-S-HDL-G-5 the writer is instantiated INSIDE the
    @cocotb.test() body — it is instrumentation co-located with the
    testbench, not a post-process step.
    """

    _SCHEMA_HEADER_BASE = {{
        "_meta": {{
            "schema": "sos-08-g/annotations",
            "version": "1.0",
            "chart_path_max_depth": 8,
        }}
    }}

    _DENSITY_ENV_VAR = "SOS_ANNOTATION_DENSITY"
    _WAVEFORM_PREFIX_ENV_VAR = "SOS_WAVEFORM_PREFIX"
    # Cocotb-classic sets MODULE to the test module name at simulator
    # launch; reading it as the waveform-prefix fallback gives by-
    # construction prefix coordination (PCDN-G-wave1-003 / wave-3b).
    _MODULE_ENV_VAR = "MODULE"
    # Cocotb-classic sets SIM_BUILD to the simulator's working dir
    # (default `sim_build/`); the annotation file lands there so the
    # waveform (`<MODULE>.fst|.vcd`) and the annotations
    # (`<test>.annotations.jsonl`) are co-located by construction
    # (SOS-08-G §6 (a) co-locate semantics).
    _SIM_BUILD_ENV_VAR = "SIM_BUILD"

    def __init__(
        self,
        test_name: str,
        output_dir: Path | str | None = None,
        waveform_prefix: str | None = None,
        vector_source: str | None = None,
    ) -> None:
        # SOS-08-G wave-3b / PCDN-G-wave1-003: output_dir defaults to
        # the cocotb-classic `SIM_BUILD` directory so annotations land
        # next to the simulator's waveform dumps. Explicit
        # `output_dir=...` still wins (test-side overrides for unit
        # tests, etc.). Fallback to current dir when neither is set
        # (e.g., the test runs outside the cocotb-classic Makefile
        # path).
        if output_dir is None:
            output_dir = os.environ.get(self._SIM_BUILD_ENV_VAR, ".")
        self.output_dir = Path(output_dir)
        self.path = self.output_dir / f"{{test_name}}.annotations.jsonl"
        # PCDN-G-005: per-event default; `cycle` opts into per-cycle.
        density = os.environ.get(self._DENSITY_ENV_VAR, "event")
        self.density: str = density if density in ("event", "cycle") else "event"
        # SOS-08-G wave-3b / PCDN-G-wave1-003: by-construction
        # filename-prefix coordination. The waveform prefix is the
        # discovery key viewer extensions use to locate
        # `<prefix>.fst|.vcd` in the same directory as the annotation
        # overlay (SOS-08-G §6 (a) co-locate semantics, amended
        # 2026-05-24). Explicit constructor arg wins; otherwise
        # consult the SOS-specific env var, then fall back to
        # cocotb-classic's `MODULE` (which the Makefile uses as the
        # waveform filename prefix in the wave-3b Makefile fragment).
        if waveform_prefix is None:
            waveform_prefix = (
                os.environ.get(self._WAVEFORM_PREFIX_ENV_VAR)
                or os.environ.get(self._MODULE_ENV_VAR)
            )
        self.waveform_prefix: str | None = waveform_prefix
        # SOS-08-G wave-3c-future §15 (2026-05-24): vector-citation
        # drill-down (§6 (f)). When present, ``vector_source`` is the
        # path to the SOS-03 vector JSON file the test loaded; the
        # viewer's drill-down click maps each annotation record's
        # ``vector_index`` to a step within this file. One source per
        # overlay because a conforming SOS-08-D test runs exactly one
        # vector per ``@cocotb.test()``.
        self.vector_source: str | None = vector_source
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # PCDN-G-006: line-buffered (flush at every newline).
        self._fh = open(self.path, "w", buffering=1, encoding="utf-8")
        # PCDN-G-001 / INV-S-HDL-G-3: schema-version header is the
        # first JSONL record. Viewer extensions parse this line to
        # detect schema version compatibility before reading the rest.
        # SOS-08-G wave-3b §15 (2026-05-24): the `_meta` envelope
        # gains an optional `waveform_prefix` field at v1.0; when
        # present, conforming viewer extensions locate the waveform
        # via `<output_dir>/<waveform_prefix>.fst|.vcd` instead of
        # the wave-1 same-prefix-as-overlay convention.
        # SOS-08-G wave-3c-future §15 (2026-05-24): the envelope
        # gains an optional `vector_source` field; viewer extensions
        # use it to resolve drill-down click-throughs to the chart's
        # vector definition (§6 (f) — data layer landed; GUI
        # invocation per-viewer per its link-back API).
        header = {{"_meta": dict(self._SCHEMA_HEADER_BASE["_meta"])}}
        if self.waveform_prefix is not None:
            header["_meta"]["waveform_prefix"] = self.waveform_prefix
        if self.vector_source is not None:
            header["_meta"]["vector_source"] = self.vector_source
        self._fh.write(json.dumps(header) + "\\n")

    def record_transition(
        self,
        cycle: int,
        chart_state: str,
        transition_id: str | None,
        chart_path: list[str] | None = None,
        signal: str | None = None,
        region: str | None = None,
        invariant_id: str | None = None,
        vector_index: int | None = None,
    ) -> None:
        """Emit one annotation record per SOS-08-G §5.2 / PCDN-G-005.

        Six normative fields per §5.2 (INV-S-HDL-G-2): ``cycle``,
        ``signal``, ``chart_state``, ``transition_id``, ``chart_path``,
        ``region``. Two optional: ``invariant_id``, ``vector_index``.

        Per INV-S-HDL-G-2 every record carries the chart-vocabulary
        triplet so review-surface readers (GTKWave / Surfer extensions
        per §6) can render badges at the chart level. A record that
        surfaces only ``cycle`` + ``signal`` regresses to RTL-signal-
        level review and is non-conformant.
        """
        record: dict[str, Any] = {{
            "cycle": cycle,
            "signal": signal or "",
            "chart_state": chart_state,
            "transition_id": transition_id,
            "chart_path": chart_path or [],
            "region": region or "",
        }}
        if invariant_id is not None:
            record["invariant_id"] = invariant_id
        if vector_index is not None:
            record["vector_index"] = vector_index
        self._fh.write(json.dumps(record) + "\\n")

    def record_cycle(
        self,
        cycle: int,
        chart_state: str,
        chart_path: list[str] | None = None,
        signal: str | None = None,
        region: str | None = None,
    ) -> None:
        """Per-cycle annotation (PCDN-G-005 ``cycle`` density opt-in).

        Emits one record per simulator clock cycle naming the
        currently-active chart state. Callers gate via
        ``self.density == "cycle"``; the writer always honors the
        call when invoked (the gate is a caller-side cost-knob, not
        a hard filter — high-bandwidth debug sessions may always
        want the per-cycle stream).
        """
        record = {{
            "cycle": cycle,
            "signal": signal or "",
            "chart_state": chart_state,
            "transition_id": None,
            "chart_path": chart_path or [],
            "region": region or "",
        }}
        self._fh.write(json.dumps(record) + "\\n")

    def close(self) -> None:
        """Close the underlying file handle.

        Called at @cocotb.test() teardown (success or failure) so the
        annotation file is well-formed on disk even if the test body
        raised. Idempotent — repeated calls are safe.
        """
        if self._fh is not None and not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> "AnnotationWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
'''
    return body


def _emit_test_py(chart: CocotbChart, config: "_CocotbConfig") -> str:
    """Emit ``test_<chart_name>_fsm.py`` — the cocotb driver.

    Per PCDN-D-003 / §5.5: one @cocotb.test() per vector. The function
    body loads the vector at test runtime, drives the clock + reset,
    walks the vector steps (if any) asserting state per step, then
    asserts the terminal state.

    SOS-08-D wave-2c: parallel charts emit a parallel-aware test body
    that reads ``current_state_<region>`` per region (SOS-08-C §6.10
    chart-top wrapper convention) and asserts per-region initial-state
    entry after reset. Per-region step-driven vectors land in wave-3
    alongside SOS-03 schema extension for per-region ``expected_states``.
    """
    dut_module = config.dut_module or _dut_module_name(chart.name)
    test_funcs: list[str] = []
    for vec in chart.vector_ids:
        slug = _slugify_vector_id(vec)
        if chart.has_parallel:
            func = _emit_parallel_test_function(
                chart=chart,
                vector_id=vec,
                slug=slug,
                clock_period_ns=config.clock_period_ns,
                reset_cycles=config.reset_cycles,
            )
        else:
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

from _cocotb_helpers import (
    AnnotationWriter,
    _CHART_NAME,
    _CHART_PATHS,
    _REGION_STATE_ENCODINGS,
    _STATE_ENCODING,
    assert_region_state,
    assert_state,
    format_failure,
    load_vector,
)


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


async def _per_cycle_record(dut, writer, region_name=None):
    """SOS-08-G wave-3a — per-cycle annotation recorder coroutine.

    PCDN-G-005 (cycle-density opt-in) is wave-3a-complete: the
    `@cocotb.test()` body spawns this coroutine via
    ``cocotb.start_soon`` when ``writer.density == "cycle"``. Per
    simulator clock edge the coroutine reads the chart-state
    observable port, decodes the one-hot RTL value back to the chart
    state id via the embedded encoding map, and emits one
    ``writer.record_cycle()`` record naming the currently-active
    chart state. Sub-region recorders pass ``region_name`` so each
    record's ``region`` field is populated and the resulting
    annotations are filterable per-region at the review surface
    (SOS-08-G §6 (d) chart-path navigation).

    The decoder maps unknown one-hot values to a literal
    ``<unknown:0bNN>`` chart-state string so decode failures surface
    in the overlay without dropping records — a record-loss failure
    mode is invisible at review time, while a literal unknown is
    legible and actionable.

    Per INV-S-HDL-G-5 this coroutine is co-located with the
    `@cocotb.test()` body (the call site spawns it inside the test
    function); it is NOT a post-process step.
    """
    if region_name is not None:
        encoding = _REGION_STATE_ENCODINGS.get(region_name, {{}})
        port_name = f"current_state_{{region_name}}"
    else:
        encoding = _STATE_ENCODING
        port_name = "current_state"
    decode = {{value: state_id for state_id, value in encoding.items()}}
    cycle = 0
    while True:
        await RisingEdge(dut.clk)
        cycle += 1
        try:
            observed = int(getattr(dut, port_name).value)
        except Exception:
            continue
        chart_state = decode.get(observed, f"<unknown:0b{{observed:b}}>")
        path = _CHART_PATHS.get(chart_state, [_CHART_NAME, chart_state])
        writer.record_cycle(
            cycle=cycle,
            chart_state=chart_state,
            chart_path=path,
            signal=f"dut.{{port_name}}",
            region=region_name or "",
        )


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
    """SOS-08-D wave-1 — vector {vector_id!r}.

    SOS-08-G wave-1: an ``AnnotationWriter`` is instantiated at test
    start and a per-step transition record is emitted on every step
    whose ``expected_state`` is non-null. The writer's underlying
    file (``<test>.annotations.jsonl``) is co-emitted alongside the
    simulator's ``.fst`` + ``.vcd`` waveforms per SOS-08-G §5.1
    three-file output contract / EOQ-011-ROADMAP. Per
    INV-S-HDL-G-5 the writer is instrumented INSIDE the test
    function (NOT a post-process step).
    """
    vector = load_vector(_VECTORS_DIR / "{vector_id}.json")
    cocotb.start_soon(Clock(dut.clk, _CLOCK_PERIOD_NS, units="ns").start())

    # SOS-08-G §5.6 (PCDN-G-003): one annotation file per test run.
    # Created at test start; closed in the `finally` so the file is
    # well-formed even when the test body raises.
    # SOS-08-G wave-3c-future §15 (2026-05-24): vector_source threads
    # the SOS-03 vector JSON path into the overlay's _meta envelope so
    # viewer extensions can resolve §6 (f) drill-down clicks.
    writer = AnnotationWriter(
        test_name="test_vector_{slug}",
        vector_source=str(_VECTORS_DIR / "{vector_id}.json"),
    )
    # SOS-08-G wave-3a / PCDN-G-005: per-cycle density opt-in. When
    # the writer's density resolved to "cycle" (env var
    # `SOS_ANNOTATION_DENSITY=cycle`) spawn the per-cycle recorder
    # coroutine so every simulator tick emits one annotation record
    # naming the currently-active chart state. The recorder is killed
    # implicitly at test teardown (cocotb cancels pending tasks); the
    # writer's line-buffered file handle ensures every record reaches
    # disk on its trailing newline per PCDN-G-006.
    if writer.density == "cycle":
        cocotb.start_soon(_per_cycle_record(dut, writer))
    cycle = 0
    try:
        await _apply_reset(dut)
        cycle += _RESET_CYCLES

        # After reset deassertion, the DUT MUST be in the chart's
        # <initial> state per SOS-08-C §5.6 / PCDN-C-003. We assert that
        # BEFORE walking the vector's steps so a wedged-at-reset DUT
        # surfaces here, not downstream where the chart-vocabulary
        # attribution is murkier.
        await RisingEdge(dut.clk)
        cycle += 1
        assert_state(dut, {initial_state!r}, format_failure(vector))
        # SOS-08-G §5.2: emit a chart-state-entry record for the
        # reset-baseline initial-state entry. `transition_id=None` per
        # §5.2 (initial-state entry is a state-enter that did not
        # transit).
        writer.record_transition(
            cycle=cycle,
            chart_state={initial_state!r},
            transition_id=None,
            # SOS-08-G wave-2 (§5.2 + PCDN-G-002): chart_path is the
            # walker-computed root-to-leaf path; defaults to a
            # single-segment list with the chart name + state id
            # when the state was added post-emit (unlikely in
            # practice; defensive).
            chart_path=_CHART_PATHS.get(
                {initial_state!r}, [_CHART_NAME, {initial_state!r}]
            ),
            signal="dut.current_state",
        )

        # Walk vector steps if present (SOS-03 §7.1 extended for HDL
        # targets; each step may carry `inputs` to drive, `expected_state`
        # to assert, and a `transition_id` for chart-vocabulary failure
        # attribution).
        for step_index, step in enumerate(vector.get("steps", []) or []):
            # Drive input stimuli — wave-1 supports a flat
            # `{{port: value}}` map on each step. Vector authors who name
            # a port absent on the DUT will get a cocotb signal-
            # resolution AttributeError; that surfaces as an ERROR per
            # §6.5 (test-infrastructure failure), distinct from a
            # chart-vocabulary FAIL.
            for port_name, port_value in (step.get("inputs") or {{}}).items():
                getattr(dut, port_name).value = port_value
            await RisingEdge(dut.clk)
            cycle += 1
            expected_state = step.get("expected_state")
            if expected_state is not None:
                assert_state(dut, expected_state, format_failure(vector, step))
                # SOS-08-G §5.2 / INV-S-HDL-G-2: emit a chart-vocabulary
                # transition record per step. The record names the
                # destination chart state + the transition id so the
                # review surface can render the badge at chart level.
                writer.record_transition(
                    cycle=cycle,
                    chart_state=expected_state,
                    transition_id=step.get("transition_id"),
                    chart_path=_CHART_PATHS.get(
                        expected_state, [_CHART_NAME, expected_state]
                    ),
                    signal="dut.current_state",
                    vector_index=step_index,
                )

        # Final assertion: chart ended in the expected terminal state.
        # Defaults to the chart's initial state for minimal vectors that
        # only verify the reset-baseline (SOS-03 minimal vector shape).
        terminal = vector.get("expected_terminal_state", {initial_state!r})
        assert_state(dut, terminal, format_failure(vector))
        writer.record_transition(
            cycle=cycle,
            chart_state=terminal,
            transition_id=None,
            chart_path=_CHART_PATHS.get(
                terminal, [_CHART_NAME, terminal]
            ),
            signal="dut.current_state",
        )
    finally:
        # SOS-08-G §5.6 (PCDN-G-003): one file per test run; close on
        # both success and failure so the annotation file is well-formed
        # on disk regardless of the test outcome.
        writer.close()
'''


def _emit_parallel_test_function(
    chart: CocotbChart,
    vector_id: str,
    slug: str,
    clock_period_ns: int,
    reset_cycles: int,
) -> str:
    """Emit one ``@cocotb.test()`` async function for a parallel chart.

    Per SOS-08-D §15 wave-2c (2026-05-23) + SOS-08-C §6.10 chart-top
    wrapper convention, extended by wave-3 (2026-05-24) with per-
    region step-driven vector walking. The emitted test:

      1. Loads the vector.
      2. Starts the clock + applies reset.
      3. For each region, asserts ``dut.current_state_<region>``
         equals the region's initial-state one-hot value (via the
         emitted ``assert_region_state`` helper).
      4. Records a per-region chart-state entry into the SOS-08-G
         annotation overlay so the review surface sees each region's
         post-reset state.
      5. SOS-08-D wave-3: walks ``vector["steps"]`` (if present)
         with per-step ``inputs`` (port→value driver) + per-step
         ``expected_states`` ({{region: state}} per the SOS-03 §15
         2026-05-24 schema extension). Each step optionally advances
         the clock via ``cycles_advance`` (default 1) and asserts
         every region's expected state, recording an annotation per
         region.
      6. Asserts per-region terminal states via
         ``vector["expected_terminal_states"]`` (dict, mirror of the
         single-region ``expected_terminal_state``; defaults to each
         region's initial state when absent).
    """
    # Build the per-region assertion + annotation block for the
    # initial-state entry post-reset.
    region_blocks: list[str] = []
    for r in chart.regions:
        per_region_path = chart.chart_paths.get(
            r.initial_state, [chart.name, r.name, r.initial_state]
        )
        region_blocks.append(
            f"        assert_region_state(\n"
            f"            dut, {r.name!r}, {r.initial_state!r},\n"
            f"            format_failure(vector),\n"
            f"        )\n"
            f"        writer.record_transition(\n"
            f"            cycle=cycle,\n"
            f"            chart_state={r.initial_state!r},\n"
            f"            transition_id=None,\n"
            f"            chart_path={per_region_path!r},\n"
            f"            signal=\"dut.current_state_{r.name}\",\n"
            f"            region={r.name!r},\n"
            f"        )"
        )
    region_block = "\n".join(region_blocks) if region_blocks else "        pass"

    # Wave-3 terminal-state assertion block: per-region fallback to
    # each region's initial state when ``expected_terminal_states``
    # lacks the region.
    region_initial_map = "{" + ", ".join(
        f"{r.name!r}: {r.initial_state!r}" for r in chart.regions
    ) + "}"

    return f'''@cocotb.test()
async def test_vector_{slug}(dut):
    """SOS-08-D wave-3 — parallel-chart vector {vector_id!r}.

    Wave-2c laid the scaffold (reset + initial-state-per-region);
    wave-3 (SOS-08-D §15 2026-05-24) lands the step-driven walker.
    SOS-03 §15 2026-05-24 extends the vector schema with per-region
    targeted assertions:

        "steps": [
            {{
                "inputs":         {{"port": value, ...}},   // optional
                "cycles_advance": <int>,                    // default 1
                "expected_states": {{"region": "state", ...}},
                "transition_id":  <int>                     // optional
            }},
            ...
        ],
        "expected_terminal_states": {{"region": "state", ...}}  // optional

    Each step asserts every named region's state and records a
    SOS-08-G annotation per region per INV-S-HDL-G-2. The walker is
    BACKWARDS-COMPATIBLE with wave-2c vectors (no ``steps`` key →
    reset + initial-state-only test, identical to wave-2c emission).
    """
    vector = load_vector(_VECTORS_DIR / "{vector_id}.json")
    cocotb.start_soon(Clock(dut.clk, _CLOCK_PERIOD_NS, units="ns").start())

    # SOS-08-G wave-3c-future §15 (2026-05-24): vector_source threads
    # the SOS-03 vector JSON path into the overlay's _meta envelope so
    # viewer extensions can resolve §6 (f) drill-down clicks (parallel
    # path; mirrors the single-region path above).
    writer = AnnotationWriter(
        test_name="test_vector_{slug}",
        vector_source=str(_VECTORS_DIR / "{vector_id}.json"),
    )
    # SOS-08-G wave-3a / PCDN-G-005: per-cycle density opt-in for
    # parallel charts. One recorder per region so each region's
    # annotation stream is tagged with its own region name and
    # filterable at the review-surface layer (SOS-08-G §6 (d)).
    # Recorders read `dut.current_state_<region>` per SOS-08-C §6.10
    # and decode via the per-region encoding map embedded in
    # `_REGION_STATE_ENCODINGS`.
    if writer.density == "cycle":
        for _region_name in _REGION_STATE_ENCODINGS:
            cocotb.start_soon(
                _per_cycle_record(dut, writer, region_name=_region_name)
            )
    cycle = 0
    # Per-region map: initial state → fallback when
    # `expected_terminal_states` lacks a region entry.
    _region_initial = {region_initial_map}
    try:
        await _apply_reset(dut)
        cycle += _RESET_CYCLES
        await RisingEdge(dut.clk)
        cycle += 1

        # SOS-08-D wave-2c: assert each region's initial state via
        # the per-region observable port. Per SOS-08-C §6.10 each
        # region's `current_state_<region>` is the chart-top wrapper's
        # observable output for that region.
{region_block}

        # SOS-08-D wave-3 (2026-05-24): walk `vector["steps"]` if
        # present. Each step may carry `inputs`, `cycles_advance`,
        # `expected_states: {{region: state}}`, and `transition_id`.
        # Backwards-compatible with wave-2c minimal vectors that omit
        # `steps` entirely (loop body is skipped).
        for step_index, step in enumerate(vector.get("steps", []) or []):
            # Drive input stimuli — flat `{{port: value}}` map per
            # SOS-03 §15 2026-05-24 extension.
            for port_name, port_value in (step.get("inputs") or {{}}).items():
                getattr(dut, port_name).value = port_value
            # `cycles_advance` defaults to 1 — one clock edge per
            # step. Vector authors MAY request multi-cycle advance
            # for vectors that exercise the period between events
            # (e.g. waiting for a CDC channel to settle).
            cycles_to_advance = int(step.get("cycles_advance", 1) or 1)
            for _ in range(cycles_to_advance):
                await RisingEdge(dut.clk)
                cycle += 1
            # Per-region expected state assertions. Each region named
            # in `expected_states` is verified against its own
            # `dut.current_state_<region>` port. Regions not named in
            # the step's map are NOT asserted (the step is per-region
            # targeted by design — vector author opts which regions
            # to check at each event).
            expected_states = step.get("expected_states") or {{}}
            for region_name, expected_state in expected_states.items():
                assert_region_state(
                    dut, region_name, expected_state,
                    format_failure(vector, step),
                )
                writer.record_transition(
                    cycle=cycle,
                    chart_state=expected_state,
                    transition_id=step.get("transition_id"),
                    chart_path=_CHART_PATHS.get(
                        expected_state, [_CHART_NAME, expected_state]
                    ),
                    signal=f"dut.current_state_{{region_name}}",
                    region=region_name,
                    vector_index=step_index,
                )

        # SOS-08-D wave-3: per-region terminal-state assertion.
        # Defaults to each region's initial state when the vector
        # lacks `expected_terminal_states` or lacks an entry for a
        # given region (minimal-vector reset-baseline shape).
        terminal_states = vector.get("expected_terminal_states") or {{}}
        for region_name, init_state in _region_initial.items():
            terminal = terminal_states.get(region_name, init_state)
            assert_region_state(
                dut, region_name, terminal,
                format_failure(vector),
            )
            writer.record_transition(
                cycle=cycle,
                chart_state=terminal,
                transition_id=None,
                chart_path=_CHART_PATHS.get(
                    terminal, [_CHART_NAME, terminal]
                ),
                signal=f"dut.current_state_{{region_name}}",
                region=region_name,
            )
    finally:
        writer.close()
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

# SOS-08-G wave-3b / PCDN-G-wave1-003: filename-prefix coordination
# BY CONSTRUCTION. The waveform and the annotation overlays share the
# same prefix-discovery source — `MODULE` — derived from the chart
# name at emit time. The Makefile passes `MODULE` through to the
# simulator's dump filename; cocotb-classic auto-exports `MODULE`
# into the test runner's environment, where `AnnotationWriter` reads
# it (falling back to `SOS_WAVEFORM_PREFIX`) and records
# `_meta.waveform_prefix = "<MODULE>"` in every overlay's first
# JSONL record. Viewer extensions read `_meta.waveform_prefix` to
# locate `<MODULE>.fst|.vcd` in the same directory (SOS-08-G §6 (a)
# co-locate, amended 2026-05-24).
SOS_WAVEFORM_PREFIX ?= $(MODULE)
export SOS_WAVEFORM_PREFIX

# Verilator wave dump + trace for debugging; harmless on Icarus.
# Wave-3b: the dump-file path is derived from `SOS_WAVEFORM_PREFIX`
# so the waveform shares a discoverable prefix with the annotation
# overlays in the same `SIM_BUILD` directory.
ifeq ($(SIM),verilator)
    EXTRA_ARGS += --trace --trace-structs
    PLUSARGS += +SOS_WAVEFORM_PREFIX=$(SOS_WAVEFORM_PREFIX)
endif

# Icarus uses an SV-side `initial $dumpfile(...)` driver. The emitted
# `dump_waveform.sv` file reads the `+SOS_WAVEFORM_PREFIX=<...>`
# plusarg at simulator launch and opens `<prefix>.fst`. When SIM is
# Icarus, append the dump driver to the SV sources.
ifeq ($(SIM),icarus)
    VERILOG_SOURCES += dump_waveform.sv
    PLUSARGS += +SOS_WAVEFORM_PREFIX=$(SOS_WAVEFORM_PREFIX)
endif

# GHDL writes VCD via `--vcd=<path>` flag passed to the run step.
ifeq ($(SIM),ghdl)
    SIM_ARGS += --vcd=$(SOS_WAVEFORM_PREFIX).vcd
endif

include $(shell cocotb-config --makefiles)/Makefile.sim
"""


def _emit_dump_waveform_sv(chart: CocotbChart, dut_module: str) -> str:
    """Emit ``dump_waveform.sv`` — SystemVerilog dump-file driver
    (SOS-08-G wave-3b / PCDN-G-wave1-003).

    Icarus does not honour a `--trace-file` CLI knob the way Verilator
    does; the dump filename is set via SV `$dumpfile(...)` at simulator
    launch. The wave-3b filename-prefix coordination contract requires
    the dump filename to derive from `MODULE` (the Makefile's chart-
    derived test-module identifier), so the SV driver reads the
    `+SOS_WAVEFORM_PREFIX=<prefix>` plusarg the Makefile passes via
    `PLUSARGS` and opens `<prefix>.fst`.

    The Verilator path does NOT use this file — Verilator's
    `--trace --trace-structs` writes to its own default path
    (`dump.fst` / `dump.vcd`) which the Makefile redirects via
    `--trace-file` (wave-3b future) or via the cocotb-classic wrapper's
    standard build-dir layout (wave-3b v1).

    Per INV-S-HDL-G-1 (three-file output coupling): the SV driver
    binds the simulator's dump path to the same `<prefix>` the
    annotation overlays record in their `_meta.waveform_prefix`
    field, so viewer extensions can locate `<prefix>.fst|.vcd` in
    the overlay's directory by construction.
    """
    chart_id = _safe_ident(chart.name)
    return f"""// {_GEN_HEADER}
//
// SystemVerilog dump-file driver for Icarus per SOS-08-G wave-3b
// (PCDN-G-wave1-003 — filename-prefix coordination by construction).
//
// The driver reads `+SOS_WAVEFORM_PREFIX=<prefix>` from the
// simulator's plusargs and opens `<prefix>.fst` for `$dumpvars`.
// The Makefile passes `+SOS_WAVEFORM_PREFIX=$(MODULE)` so the dump
// filename derives from the chart-derived MODULE identifier the
// `AnnotationWriter` records in `_meta.waveform_prefix`. Viewers
// thereby locate the waveform via the overlay's `_meta` field
// (SOS-08-G §6 (a) co-locate semantics, amended 2026-05-24).
//
// Cites: SOS-08-G §5.2 (overlay schema; `_meta.waveform_prefix`),
//        SOS-08-G §6 (a) (viewer co-locate by `_meta.waveform_prefix`),
//        INV-S-HDL-G-1 (three-file output coupling).
//
// Wave-3b v1: Icarus only. Verilator dump-file binding is handled
// inside the Makefile (`EXTRA_ARGS += --trace --trace-structs`); GHDL
// uses `--vcd=$(SOS_WAVEFORM_PREFIX).vcd`. Wave-3c may emit a
// Verilator-specific harness shim if the v1 default path proves
// insufficient.

`timescale 1ns / 1ps

module dump_waveform_{chart_id};
    initial begin : sos_dump
        string prefix;
        string filename;
        // Default if the Makefile did not pass +SOS_WAVEFORM_PREFIX.
        // Mirrors the AnnotationWriter env-var fallback chain so the
        // by-construction discovery stays consistent.
        prefix = "{dut_module}";
        $value$plusargs("SOS_WAVEFORM_PREFIX=%s", prefix);
        filename = {{prefix, ".fst"}};
        $dumpfile(filename);
        $dumpvars(0, {dut_module});
        $display("[SOS-08-G] dump file: %0s", filename);
    end
endmodule
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

## Waveform annotation overlay (SOS-08-G)

Every `@cocotb.test()` in this directory emits a three-file review
artifact per SOS-08-G-CONCEPTS.md §5.1 (three-file output contract,
EOQ-011-ROADMAP) and §15 (ratified 2026-05-23):

| File | Producer | Purpose |
|------|----------|---------|
| `<test>.fst` | simulator (`--trace`) | Fastsignaltrace waveform; GTKWave + Surfer native. |
| `<test>.vcd` | simulator (`--trace`) | VCD waveform; universal compatibility. |
| `<test>.annotations.jsonl` | this testbench (`AnnotationWriter`) | JSON-Lines chart-vocabulary overlay. |

The annotation file's first line is the schema-version header per
**PCDN-SOS-08-G-001** / INV-S-HDL-G-3:

```json
{{"_meta": {{"schema": "sos-08-g/annotations", "version": "1.0", "chart_path_max_depth": 8}}}}
```

Subsequent lines are per-event annotation records per
**PCDN-SOS-08-G-005** (per-event default; `cycle`-density opt-in
honored via `SOS_ANNOTATION_DENSITY=cycle` env var). Each record
carries the six normative fields per SOS-08-G §5.2 / INV-S-HDL-G-2:
`cycle`, `signal`, `chart_state`, `transition_id`, `chart_path`,
`region`. Two optional fields: `invariant_id`, `vector_index`.

The file handle is line-buffered per **PCDN-SOS-08-G-006**
(`open(..., buffering=1)`); each newline-terminated record reaches
disk without per-record fsync, sufficient for mid-run review.

### Filename-prefix coordination (wave-3b)

Per **PCDN-G-wave1-003** (closed wave-3b 2026-05-24) the waveform
and the annotation overlays share a discovery prefix BY CONSTRUCTION:

- The Makefile sets `SOS_WAVEFORM_PREFIX = $(MODULE)` (default
  `test_{{chart}}_fsm`) and `export`s it so `AnnotationWriter` reads
  it at test runtime.
- The Makefile passes `--trace --trace-structs` to Verilator (whose
  default dump file lives in `$(SIM_BUILD)`); for Icarus, the emitted
  `dump_waveform.sv` reads the same `+SOS_WAVEFORM_PREFIX=<...>`
  plusarg and calls `$dumpfile("<prefix>.fst")`; for GHDL, the
  Makefile passes `--vcd=$(SOS_WAVEFORM_PREFIX).vcd`.
- `AnnotationWriter.__init__` reads `SOS_WAVEFORM_PREFIX` (falling
  back to `MODULE`) and records it in `_meta.waveform_prefix` of
  every overlay's first JSONL record.
- Viewer extensions read `_meta.waveform_prefix` to locate
  `<output_dir>/<waveform_prefix>.fst|.vcd` in the SAME directory
  as the annotation overlay (SOS-08-G §6 (a), amended 2026-05-24).
- `AnnotationWriter` writes overlays to `$(SIM_BUILD)` by default
  (the cocotb-classic build directory), so the waveform + annotations
  + viewer all resolve relative to one canonical directory.

The wave-1 same-prefix-as-overlay convention is preserved as the
fallback for readers that encounter overlays missing the wave-3b
`_meta.waveform_prefix` field.

### Viewer integration

Per SOS-08-G §6 (viewer integration) + **PCDN-SOS-08-G-004**, GTKWave
and Surfer viewer extensions live in-subrepo at
`tools/sos-codegen/viewers/{{gtkwave,surfer}}/` (sibling-agent
deliverables landing alongside this emitter). They read the
`.annotations.jsonl` overlay and render chart-state badges as a track
on the waveform timeline next to the raw signal traces.

Commercial viewers (Riviera, Questa, VCS DVE, Xcelium SimVision) do
NOT receive native plugins from SOS; the customer wraps the
annotation overlay via the vendor's TCL/Python user-script extension
API. The overlay format is documented at SOS-08-G §5.2 so customers
can author their own hookup.

### Storage discipline

Per SOS-08-G §5.8 + INV-S-HDL-G-4, `.fst` / `.vcd` /
`.annotations.jsonl` files are **build outputs** and MUST NOT appear
in the chart's tracked git history. Add to `.gitignore`:

```
*.fst
*.vcd
*.annotations.jsonl
```
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
# post_results.py — JUnit XML post-processor (SOS-08-D wave-2a per §6.7).
#
# Per PCDN-SOS-08-D-002 (resolved 2026-05-23, §15) the cocotb runner
# writes a native `build/results.xml` in cocotb's xunit-like shape; the
# emitted `post_results.py` rewrites it to pure JUnit XML at
# `build/junit.xml` and merges chart-vocabulary `SOS-FAIL` lines from
# `build/sim.log` into each `<failure>` element's text content.
#
# CI systems (GitHub Actions, GitLab CI, Jenkins, Buildkite, CircleCI)
# consume `build/junit.xml` with zero per-system adapters. The
# post-processor is per-chart so it self-filters the SOS-FAIL stream
# by `chart=<this_chart>` for safety.
# ---------------------------------------------------------------------------


def _emit_post_results_py(chart: CocotbChart) -> str:
    """Emit ``post_results.py`` — the §6.7 JUnit XML post-processor.

    Per SOS-08-D §6.7 + PCDN-SOS-08-D-002 (resolved 2026-05-23, §15
    wave-1 walkthrough). Wave-1 deferred this artifact (per the
    `Impl wave-1 PCDN amendments` §15 entry); wave-2a lands it.

    The emitted script:
      1. Reads `build/results.xml` (cocotb-classic native xunit-ish).
      2. Scrapes `SOS-FAIL chart=<chart> ...` lines from
         `build/sim.log` (simulator stdout per §6.6).
      3. Filters to chart-matching lines (the emitter knows the chart
         name; the post-processor cites it verbatim).
      4. Merges each matching SOS-FAIL line into the corresponding
         `<failure>` element of `build/results.xml` (matched by test
         appearance order, since cocotb's xunit shape preserves
         per-test ordering).
      5. Writes the rewritten tree as pure JUnit XML at
         `build/junit.xml`.

    The script is standalone Python 3.10+ (matches the SOS-08-D §5.3
    runtime contract per PCDN-D-005) and depends only on the standard
    library (`xml.etree.ElementTree`, `pathlib`, `re`, `sys`). No
    cocotb / pytest runtime dependency at post-processing time — the
    cocotb run produces the inputs, the script reads them.

    Invariants upheld at emit time:
      * INV-SOS-H + INV-S-HDL-5 + INV-S-HDL-D-5: every failure
        rendered in chart vocabulary; the script lifts the SOS-FAIL
        lines into the JUnit `<failure>` element so CI consumers see
        chart-state + transition-id + invariant-id alongside the raw
        cocotb assertion text.
      * INV-S-HDL-D-3: the script does NOT mutate the cocotb
        `results.xml` input file in place — it reads, transforms in
        memory, writes to a separate `junit.xml` path. The cocotb
        artifact remains the audit trail of what the runner produced.
    """
    chart_name = chart.name
    chart_name_repr = repr(chart_name)
    return f'''# {_GEN_HEADER}
#
# SOS-08-D wave-2a JUnit XML post-processor for chart `{chart_name}`.
#
# Reads cocotb's native build/results.xml + scrapes SOS-FAIL lines
# from build/sim.log; produces pure JUnit XML at build/junit.xml.
# CI consumes build/junit.xml.
#
# Per SOS-08-D §6.7 + PCDN-D-002 (resolved 2026-05-23, §15) +
# wave-2a landing entry under §15.
#
# Usage:
#     python3 post_results.py [BUILD_DIR]
# (BUILD_DIR defaults to "./build".)
#
# Invariants:
#   * INV-S-HDL-D-3 — non-mutating with respect to cocotb's
#     results.xml; the script reads it but writes its output to a
#     separate junit.xml path.
#   * INV-S-HDL-D-5 + INV-S-HDL-5 + INV-SOS-H — failure messages
#     render in chart vocabulary; SOS-FAIL lines from sim.log are
#     merged into each <failure> element's text content.
#

from __future__ import annotations

import re
import sys
from pathlib import Path
import xml.etree.ElementTree as ET


CHART_NAME = {chart_name_repr}
"""Chart name the post-processor self-filters SOS-FAIL lines by per
SOS-08-D §6.7. The chart name is emitted by the cocotb walker so the
post-processor never matches SOS-FAIL lines from a sibling chart whose
simulator output happens to share a build/ directory."""


# Per SOS-08-D §6.6: SOS-FAIL line shape from the SVA `\\`SOS_FAIL`
# macro is:
#     SOS-FAIL chart=<chart> region=<region> transition=<txid>
#              state=<state> invariant=<invid> @ <time>
_SOS_FAIL_RE = re.compile(
    r"^.*SOS-FAIL\\s+chart=(?P<chart>\\S+)\\s+region=(?P<region>\\S+)\\s+"
    r"transition=(?P<transition>\\S+)\\s+state=(?P<state>\\S+)\\s+"
    r"invariant=(?P<invariant>\\S+)(?:\\s+@\\s+(?P<time>\\S+))?\\s*$",
)


def _scrape_sos_fail_lines(sim_log: Path) -> list[dict[str, str]]:
    """Return list of dicts of all SOS-FAIL lines matching this chart.

    Per §6.7 (3): self-filter by chart name so a shared build/
    directory across charts cannot cross-contaminate.
    """
    if not sim_log.is_file():
        return []
    hits: list[dict[str, str]] = []
    for line in sim_log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _SOS_FAIL_RE.match(line)
        if not m:
            continue
        gd = m.groupdict()
        if gd.get("chart") != CHART_NAME:
            continue
        hits.append(gd)
    return hits


def _format_chart_vocab(fail: dict[str, str]) -> str:
    """Single-line chart-vocabulary failure summary per INV-S-HDL-D-5."""
    pieces = [
        f"chart={{fail.get('chart')}}",
        f"region={{fail.get('region')}}",
        f"transition={{fail.get('transition')}}",
        f"state={{fail.get('state')}}",
        f"invariant={{fail.get('invariant')}}",
    ]
    if fail.get("time"):
        pieces.append(f"@ {{fail['time']}}")
    return " ".join(pieces)


def _merge_into_failures(tree: ET.ElementTree,
                        sos_fails: list[dict[str, str]]) -> None:
    """Append chart-vocabulary text to each `<failure>` element.

    Per §6.7 (3): match by test appearance order — cocotb's xunit
    output preserves per-test ordering, so the Nth `<failure>` in the
    XML corresponds to the Nth SOS-FAIL line in `sim.log` (when both
    are non-zero). Charts with more SOS-FAIL lines than `<failure>`
    elements append the remainder to the LAST failure block; charts
    with fewer leave trailing failures un-augmented (the cocotb-side
    assertion text remains).
    """
    root = tree.getroot()
    # Walk all <failure> children of <testcase> elements in document
    # order. JUnit XML places failures as direct children of testcase.
    failures = []
    for testsuite in root.iter("testsuite"):
        for testcase in testsuite.iter("testcase"):
            for failure in testcase.iter("failure"):
                failures.append(failure)
    if not failures:
        return
    n = min(len(failures), len(sos_fails))
    for i in range(n):
        existing = failures[i].text or ""
        augmented = (
            f"{{existing.rstrip()}}\\n\\n[SOS-08-D §6.6 chart-vocabulary] "
            f"{{_format_chart_vocab(sos_fails[i])}}"
        )
        failures[i].text = augmented
    # Append any trailing SOS-FAIL lines to the last failure element.
    if len(sos_fails) > len(failures):
        last = failures[-1]
        extras = sos_fails[len(failures):]
        extra_text = "\\n".join(
            f"[SOS-08-D §6.6 chart-vocabulary] {{_format_chart_vocab(x)}}"
            for x in extras
        )
        last.text = (last.text or "") + "\\n" + extra_text


def main(argv: list[str]) -> int:
    build_dir = Path(argv[1]) if len(argv) > 1 else Path("build")
    results_xml = build_dir / "results.xml"
    sim_log     = build_dir / "sim.log"
    junit_xml   = build_dir / "junit.xml"

    if not results_xml.is_file():
        sys.stderr.write(
            f"post_results: {{results_xml!s}} not found — did the cocotb "
            f"run produce its xunit output?\\n"
        )
        return 2

    try:
        tree = ET.parse(results_xml)
    except ET.ParseError as exc:
        sys.stderr.write(
            f"post_results: cocotb {{results_xml!s}} did not parse as XML "
            f"({{exc}}); leaving build/ untouched.\\n"
        )
        return 3

    sos_fails = _scrape_sos_fail_lines(sim_log)
    _merge_into_failures(tree, sos_fails)

    # Write to junit.xml — the chart's CI-consumable artifact path.
    # INV-S-HDL-D-3: results.xml is the cocotb run's audit trail, not
    # modified by this script.
    tree.write(junit_xml, encoding="utf-8", xml_declaration=True)

    sys.stdout.write(
        f"post_results: wrote {{junit_xml!s}} "
        f"(merged {{len(sos_fails)}} SOS-FAIL line(s) "
        f"for chart `{{CHART_NAME}}`).\\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''


# ---------------------------------------------------------------------------
# post_annotations.py — SVA invariant_id merge into annotation overlays.
# SOS-08-G wave-2b per §15 (2026-05-23) + wave-1 §15's "SVA bind-file
# annotation integration" wave-2 candidate.
#
# Reads cocotb's build/sim.log + the per-test build/<test>.annotations.
# jsonl overlays; merges chart-vocabulary `SOS-FAIL` lines into the
# matching overlay as invariant-fire annotation records (per §5.2 +
# INV-S-HDL-G-2 — the `invariant_id` field on annotation records is
# populated when an SVA assertion fires during the test run).
# ---------------------------------------------------------------------------


def _emit_post_annotations_py(chart: CocotbChart) -> str:
    """Emit ``post_annotations.py`` — the SOS-08-G wave-2b SVA fire
    merge post-processor.

    Per SOS-08-G §15 wave-2 candidate "SVA bind-file annotation
    integration" (resolved in this commit): the script reads the
    cocotb run's `build/sim.log` for `SOS-FAIL chart=<chart>
    region=<region> transition=<txid> state=<state> invariant=<invid>
    @ <time>` lines (per SOS-08-D §6.6 emit format) and appends one
    invariant-fire annotation record per matching line to the
    test's `.annotations.jsonl` overlay.

    The script is per-chart and self-filters by `chart=<this_chart>`
    so a shared `build/` across charts cannot cross-contaminate
    (same self-filter pattern wave-2a established for
    `post_results.py`). Standalone Python 3.10+, standard-library
    only.

    Annotation record shape per §5.2:
        {
            "cycle":         <int>,    # simulator time → cycle count
            "signal":        "dut.<chart_top>",
            "chart_state":   <state from SOS-FAIL>,
            "transition_id": <txid from SOS-FAIL>,
            "chart_path":    <from _CHART_PATHS lookup if available
                              else [chart_name, state]>,
            "region":        <region from SOS-FAIL>,
            "invariant_id":  <invid from SOS-FAIL>,
        }

    The script appends to each `<test>.annotations.jsonl` it finds
    in the build directory; INV-S-HDL-G-3 (schema header at line 0)
    is preserved because we append AFTER the existing records, never
    rewriting the header.

    Invariants upheld:
      * INV-S-HDL-G-2 (chart-vocabulary mandatory): every appended
        record carries chart_state, transition_id, chart_path,
        region, plus the invariant_id from the SVA fire.
      * INV-S-HDL-G-3 (schema-version header at line 0): preserved
        — we append, never rewrite the header.
      * INV-S-HDL-G-4 (build-output discipline): appended records
        live inside the per-test annotation file, which is itself
        a build output (gitignored per §5.8).
    """
    chart_name = chart.name
    chart_name_repr = repr(chart_name)
    return f'''# {_GEN_HEADER}
#
# SOS-08-G wave-2b SVA invariant_id merge for chart `{chart_name}`.
#
# Reads build/sim.log for SOS-FAIL lines (per SOS-08-D §6.6) and
# appends one invariant-fire annotation record to each test's
# build/<test>.annotations.jsonl overlay (per SOS-08-G §5.2 +
# INV-S-HDL-G-2).
#
# Per SOS-08-G §15 wave-2 candidate "SVA bind-file annotation
# integration" — wave-1 deferred this; wave-2b lands it as a
# post-test merge step that runs alongside post_results.py.
#
# Usage:
#     python3 post_annotations.py [BUILD_DIR]
# (BUILD_DIR defaults to "./build".)
#
# Invariants:
#   * INV-S-HDL-G-2 -- every appended record carries chart-vocab
#     metadata (chart_state, transition_id, chart_path, region,
#     invariant_id).
#   * INV-S-HDL-G-3 -- schema-version header at line 0 preserved
#     (we append, never rewrite).
#

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


CHART_NAME = {chart_name_repr}


# Per SOS-08-D §6.6: SOS-FAIL line emitted by the SVA `\\`SOS_FAIL`
# macro:
#     SOS-FAIL chart=<chart> region=<region> transition=<txid>
#              state=<state> invariant=<invid> @ <time>
_SOS_FAIL_RE = re.compile(
    r"^.*SOS-FAIL\\s+chart=(?P<chart>\\S+)\\s+region=(?P<region>\\S+)\\s+"
    r"transition=(?P<transition>\\S+)\\s+state=(?P<state>\\S+)\\s+"
    r"invariant=(?P<invariant>\\S+)(?:\\s+@\\s+(?P<time>\\S+))?\\s*$",
)


def _scrape_sva_fires(sim_log: Path) -> list[dict[str, str]]:
    """Return chart-matching SOS-FAIL lines as dicts. Self-filter
    by CHART_NAME so a shared build/ across charts cannot cross-
    contaminate (same pattern as wave-2a post_results.py)."""
    if not sim_log.is_file():
        return []
    hits: list[dict[str, str]] = []
    for line in sim_log.read_text(encoding="utf-8",
                                  errors="replace").splitlines():
        m = _SOS_FAIL_RE.match(line)
        if not m:
            continue
        gd = m.groupdict()
        if gd.get("chart") != CHART_NAME:
            continue
        hits.append(gd)
    return hits


def _time_to_cycle(time_str: str | None) -> int:
    """Wave-2b stub conversion: extract leading integer from the
    SOS-FAIL `@ <time>` field (e.g. ``"142ns"`` → 142). The unit
    suffix is dropped; full simulator-time → cycle conversion needs
    knowledge of the clock period and is wave-3 scope.
    """
    if not time_str:
        return 0
    m = re.match(r"(-?\\d+)", time_str)
    return int(m.group(1)) if m else 0


def _build_record(fire: dict[str, str]) -> dict:
    """Build an annotation record from one SOS-FAIL fire."""
    chart_path = [CHART_NAME, fire["state"]]
    return {{
        "cycle": _time_to_cycle(fire.get("time")),
        "signal": f"dut.{{fire['region']}}",
        "chart_state": fire["state"],
        "transition_id": fire["transition"],
        "chart_path": chart_path,
        "region": fire["region"],
        "invariant_id": fire["invariant"],
    }}


def _append_to_overlay(overlay: Path, records: list[dict]) -> None:
    """Append records to the overlay file. Per INV-S-HDL-G-3 we
    preserve the line-0 schema header by appending, not rewriting.
    """
    with overlay.open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\\n")


def main(argv: list[str]) -> int:
    build_dir = Path(argv[1]) if len(argv) > 1 else Path("build")
    sim_log = build_dir / "sim.log"

    fires = _scrape_sva_fires(sim_log)
    if not fires:
        sys.stdout.write(
            f"post_annotations: no SOS-FAIL lines for chart "
            f"`{{CHART_NAME}}` in {{sim_log!s}}; no records appended.\\n"
        )
        return 0

    # Find all <test>.annotations.jsonl files in the build dir; append
    # the chart's fires to every overlay so a reviewer scrubbing any
    # test's waveform sees the chart-wide invariant fires.
    overlays = sorted(build_dir.glob("*.annotations.jsonl"))
    if not overlays:
        sys.stderr.write(
            f"post_annotations: found {{len(fires)}} SOS-FAIL line(s) "
            f"for chart `{{CHART_NAME}}` but no <test>.annotations."
            f"jsonl overlay files in {{build_dir!s}}; nothing to "
            f"merge into.\\n"
        )
        return 3

    records = [_build_record(f) for f in fires]
    for overlay in overlays:
        _append_to_overlay(overlay, records)

    sys.stdout.write(
        f"post_annotations: appended {{len(records)}} SVA-fire "
        f"record(s) for chart `{{CHART_NAME}}` to "
        f"{{len(overlays)}} overlay file(s).\\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''


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

    Returns a ``{filename: source}`` dict whose keys are all prefixed
    with ``tests/<chart>/`` (mirroring the SVA walker's convention per
    PCDN-SOS-08-D-wave1-file-layout, ratified 2026-05-23):

      - ``tests/<chart>/test_<chart>_fsm.py``  the cocotb driver
        (one @cocotb.test per vector per PCDN-D-003 / §5.5).
      - ``tests/<chart>/_cocotb_helpers.py``   shared helpers
        (load_vector, assert_state, format_failure) per
        PCDN-D-006 / §5.6.
      - ``tests/<chart>/Makefile``             cocotb-classic invocation
        (PCDN-D-001 default `SIM ?= verilator`; PCDN-D-007).
      - ``tests/<chart>/pytest.ini``           cocotb-test invocation
        (PCDN-D-007).
      - ``tests/<chart>/README.md``            chart-side traceability +
        Python 3.10+ minimum (PCDN-D-005 / §5.3) + simulator-selection
        notes (PCDN-D-001 / §5.1).
      - ``tests/<chart>/vectors/<vector_id>.json``  one minimal
        scaffold vector per bound vector id, so the wave-1 directory
        is end-to-end runnable on emit.

    The ``tests/<chart>/`` prefix unifies the cocotb emit shape with
    the SVA walker (which already emits
    ``tests/<chart>/<chart>_fsm_sva.sv`` + ``..._bind.sv``) so both
    the cocotb test directory and its co-located SVA bind pair land
    in the same per-DUT subtree. See PCDN-SOS-08-D-wave1-file-layout
    (2026-05-23 wave-1 PCDN walkthrough resolution).

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

    # Per PCDN-SOS-08-D-wave1-file-layout (ratified 2026-05-23): every
    # emitted artifact lands under ``tests/<chart>/`` so the cocotb
    # test directory co-locates with the SVA walker's bind pair (which
    # already emits ``tests/<chart>/<chart>_fsm_sva.sv``). The
    # ``<chart>`` slug uses ``_safe_ident`` for cross-dialect parity
    # with the SVA walker's ``_sanitize_sv_identifier(...).lower()``.
    chart_slug = _safe_ident(chart.name)
    prefix = f"tests/{chart_slug}/"

    out: dict[str, str] = {}
    out[f"{prefix}test_{chart_slug}_fsm.py"] = _emit_test_py(chart, cfg)
    out[f"{prefix}_cocotb_helpers.py"] = _emit_helpers_py(chart, encoding)
    out[f"{prefix}Makefile"] = _emit_makefile(chart, dut_module)
    # SOS-08-G wave-3b: SV dump-file driver for Icarus (Verilator path
    # uses --trace-file from the Makefile). Filename-prefix
    # coordination by construction per PCDN-G-wave1-003.
    out[f"{prefix}dump_waveform.sv"] = _emit_dump_waveform_sv(chart, dut_module)
    out[f"{prefix}pytest.ini"] = _emit_pytest_ini(chart)
    out[f"{prefix}README.md"] = _emit_readme(chart, dut_module, cfg)
    # SOS-08-D wave-2a: per-chart JUnit XML post-processor per §6.7
    # + PCDN-D-002 (wave-1 deferred, wave-2a lands).
    out[f"{prefix}post_results.py"] = _emit_post_results_py(chart)
    # SOS-08-G wave-2b: per-chart SVA fire merge — appends invariant
    # _id-bearing annotation records into each test's overlay file.
    out[f"{prefix}post_annotations.py"] = _emit_post_annotations_py(chart)

    # Scaffold vector files (one per bound vector id) so the emitted
    # directory is end-to-end runnable. Authors replace these with
    # real SOS-03 §7.1 vectors at suite-population time.
    for vid in chart.vector_ids:
        out[f"{prefix}vectors/{vid}.json"] = _emit_scaffold_vector(chart, vid)

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

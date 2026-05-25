r"""SCXML chart → SystemVerilog testbench emitter (SOS-08-E).

Wave-1 scaffold per ``SOS-08-E-CONCEPTS.md`` §6 (emission contract) and
§15 (2026-05-23 ratification). Emits a class-based, self-checking,
constrained-random-free, UVM-free SV testbench per chart region. Wave-1
covers single-region charts; the per-region split for parallel charts is
wave-2 work.

@spec  SOS-08-E-CONCEPTS.md §5.1 (class-based, self-checking, no
       constrained-random, no UVM)
@spec  SOS-08-E-CONCEPTS.md §5.2 (SVA bind file mirror — byte-identical
       to SOS-08-D's emit; this module imports SOS-08-D's
       ``transliterate_sva_bind.render_target`` and re-keys the
       resulting filenames under the SV testbench directory)
@spec  SOS-08-E-CONCEPTS.md §5.3 (target simulator set — Questa,
       Riviera, VCS, Xcelium, Verilator)
@spec  SOS-08-E-CONCEPTS.md §5.4 (JSONL trace consumption via
       ``$fopen`` / ``$fgets``; JSON invariants delivered as bound SVA
       properties so the SV testbench does not parse them directly)
@spec  SOS-08-E-CONCEPTS.md §5.5 (chart-vocabulary failure messages)
@spec  SOS-08-E-CONCEPTS.md §6.1 (stimulus driver class contract)
@spec  SOS-08-E-CONCEPTS.md §6.2 (response checker class contract)
@spec  SOS-08-E-CONCEPTS.md §6.3 (top-level testbench module contract)
@spec  SOS-08-E-CONCEPTS.md §6.4 (build wrapper contract)
@spec  SOS-08-E-CONCEPTS.md §7 INV-S-HDL-E-1 (no constrained-random)
@spec  SOS-08-E-CONCEPTS.md §7 INV-S-HDL-E-2 (no UVM imports)
@spec  SOS-08-E-CONCEPTS.md §7 INV-S-HDL-E-3 (SVA only via bind files;
       no inline `assert property` in driver/checker/testbench)
@spec  SOS-08-E-CONCEPTS.md §7 INV-S-HDL-E-4 (chart-vocabulary failure
       messages)
@spec  SOS-08-E-CONCEPTS.md §7 INV-S-HDL-E-5 (per-simulator build
       wrapper — wave-1 ships Verilator Makefile + Questa/Riviera .do
       reference; VCS/Xcelium wrappers wave-2)
@spec  SOS-08-E-CONCEPTS.md §7 INV-S-HDL-E-6 (Verilator-subset
       compliance declared not assumed — emitted SV uses classes +
       virtual interfaces + file I/O which Verilator supports; SVA
       properties live in the bind file SOS-08-D owns)
@spec  SOS-07-CONCEPTS.md INV-SOS-A..H (cross-phase invariants — cited)
@spec  SOS-08-CONCEPTS.md INV-S-HDL-1..5 (cross-sub-phase invariants —
       cited; INV-S-HDL-5 = chart-vocabulary failure messages,
       load-bearing for `[FAIL]` prefix here)

# Wave-1 scope

* Single-region chart → eight files (all under ``tb/sv/<chart>/``):
    - ``tb/sv/<chart>/tb_<chart>.sv`` — top-level testbench module.
    - ``tb/sv/<chart>/sos_driver_<chart>.sv`` — stimulus driver class.
    - ``tb/sv/<chart>/sos_checker_<chart>.sv`` — response checker class.
    - ``tb/sv/<chart>/dut_if_<chart>.sv`` — virtual interface.
    - ``tb/sv/<chart>/<chart>_fsm_sva.sv`` — SVA assertion module
      (byte-identical to SOS-08-D emit; re-keyed under the SV testbench
      directory).
    - ``tb/sv/<chart>/<chart>_fsm_bind.sv`` — SVA bind directive
      (byte-identical to SOS-08-D emit).
    - ``tb/sv/<chart>/run_verilator.mk`` — Verilator build wrapper
      (the open-source-runnable wrapper; full CI verification target).
    - ``tb/sv/<chart>/run.do`` — Questa/Riviera build wrapper (the
      commercial-reference wrapper; smoke-tested but not full CI).

* Parallel charts are REJECTED at wave-1 with ``UnsupportedChartError``;
  per-region testbench split is wave-2 alongside the per-region SVA
  bind already deferred at SOS-08-D wave-1.

* VCS ``Makefile.sv``, Xcelium ``run_xrun.sh``, and the layered
  driver/checker hierarchy variant (PCDN-SOS-08-E-001 layered opt-in)
  are wave-2 scope; wave-1 ships the flat shape per the resolved
  recommendation.

# Integration contract

The codegen tool's CLI dispatcher invokes::

    from transliterate_hdl_sv_tb import render_target
    files = render_target(chart_ir, config)

``chart_ir`` is the raw scjson dict (``ChartAst.raw_scjson`` from the
loader). Output is a ``dict[filename, source]`` mapping output filename
(relative path, embedding the ``tb/sv/<chart>/`` prefix) to emitted file
source. The dispatcher writes each entry under the project's emit root.

# Invariant audit at emit time

Emitted text is post-pass scanned for INV-S-HDL-E-1..3 forbidden
constructs (``randomize``, ``constraint`` block opener, ``rand`` /
``randc`` property keyword, ``import uvm_pkg``, ``\`uvm_``, inline
``assert property`` in non-bind files). Any hit raises
``InvariantAuditError`` — the walker's contract is that emitted output
is conforming by construction, and the audit is belt-and-suspenders.

# Failure-message format (INV-S-HDL-E-4 + §5.5)

The response checker emits failures in chart vocabulary::

    [FAIL] vector V<n>: chart `<chart>` region `<region>` produced
           expected `<expected>` at cycle <cycle>; observed `<observed>`.

The format mirrors SOS-08-D's cocotb checker; INV-SOS-H + INV-S-HDL-5
+ INV-S-HDL-E-4 are upheld by the chart-vocabulary `[FAIL]` prefix and
the named chart region.
"""

from __future__ import annotations

import re
from typing import Any

# Reuse the SVA bind walker — same artifact, byte-identical per §5.2.
from transliterate_sva_bind import (  # noqa: E402
    UnsupportedChartError,
    render_target as _render_sva_bind,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvariantAuditError(RuntimeError):
    """Emitted text violated INV-S-HDL-E-1..3 at the post-emit audit pass.

    The walker's contract is that emitted output is conforming by
    construction; this exception signals an internal bug, not a chart-
    author error.
    """


# ---------------------------------------------------------------------------
# Identifier sanitization (mirrors transliterate_sva_bind)
# ---------------------------------------------------------------------------


_SV_RESERVED: frozenset[str] = frozenset({
    "alias", "always", "always_comb", "always_ff", "always_latch", "and",
    "assert", "assign", "assume", "automatic", "before", "begin", "bind",
    "bins", "binsof", "bit", "break", "buf", "bufif0", "bufif1", "byte",
    "case", "casex", "casez", "cell", "chandle", "class", "clocking", "cmos",
    "config", "const", "constraint", "context", "continue", "cover",
    "covergroup", "coverpoint", "cross", "deassign", "default", "defparam",
    "design", "disable", "dist", "do", "edge", "else", "end", "endcase",
    "endclass", "endclocking", "endconfig", "endfunction", "endgenerate",
    "endgroup", "endinterface", "endmodule", "endpackage", "endprimitive",
    "endprogram", "endproperty", "endspecify", "endsequence", "endtable",
    "endtask", "enum", "event", "expect", "export", "extends", "extern",
    "final", "first_match", "for", "force", "foreach", "forever", "fork",
    "forkjoin", "function", "generate", "genvar", "highz0", "highz1", "if",
    "iff", "ifnone", "ignore_bins", "illegal_bins", "import", "incdir",
    "include", "initial", "inout", "input", "inside", "instance", "int",
    "integer", "interface", "intersect", "join", "join_any", "join_none",
    "large", "liblist", "library", "local", "localparam", "logic", "longint",
    "macromodule", "matches", "medium", "modport", "module", "nand",
    "negedge", "new", "nmos", "nor", "noshowcancelled", "not", "notif0",
    "notif1", "null", "or", "output", "package", "packed", "parameter",
    "pmos", "posedge", "primitive", "priority", "program", "property",
    "protected", "pull0", "pull1", "pulldown", "pullup",
    "pulsestyle_ondetect", "pulsestyle_onevent", "pure", "rand", "randc",
    "randcase", "randsequence", "rcmos", "real", "realtime", "ref", "reg",
    "release", "repeat", "return", "rnmos", "rpmos", "rtran", "rtranif0",
    "rtranif1", "scalared", "sequence", "shortint", "shortreal",
    "showcancelled", "signed", "small", "solve", "specify", "specparam",
    "static", "string", "strong0", "strong1", "struct", "super", "supply0",
    "supply1", "table", "tagged", "task", "this", "throughout", "time",
    "timeprecision", "timeunit", "tran", "tranif0", "tranif1", "tri", "tri0",
    "tri1", "triand", "trior", "trireg", "type", "typedef", "union",
    "unique", "unsigned", "use", "uwire", "var", "vectored", "virtual",
    "void", "wait", "wait_order", "wand", "weak0", "weak1", "while",
    "wildcard", "wire", "with", "within", "wor", "xnor", "xor",
})


def _sanitize_sv_identifier(name: str) -> str:
    """Lower-case, swap non-alphanumerics to underscore, and ward off
    SV reserved words by suffix.

    Mirrors ``transliterate_sva_bind._sanitize_sv_identifier`` so the SV
    testbench module names and the SVA bind module names collide on the
    same canonical form when they reference each other.
    """
    out = re.sub(r"[^A-Za-z0-9_]", "_", name.strip()).strip("_").lower()
    if not out:
        return "chart"
    if out[0].isdigit():
        out = f"_{out}"
    if out in _SV_RESERVED:
        out = f"{out}_id"
    return out


def _normalise_chart_name(chart_name: str | None) -> str:
    base = chart_name or "chart"
    return _sanitize_sv_identifier(base)


# ---------------------------------------------------------------------------
# Chart introspection (single-region wave-1)
# ---------------------------------------------------------------------------


def _chart_has_parallel(chart_ir: dict[str, Any]) -> bool:
    """Detect a top-level ``<parallel>`` region.

    Wave-1 rejected; wave-3 (2026-05-24 §15) lifts the rejection via
    ``_collect_regions`` + the parallel-aware emit path.
    """
    parallels = chart_ir.get("parallel") or []
    if parallels:
        return True
    for st in chart_ir.get("state") or []:
        if (st.get("parallel") or []):
            return True
    return False


def _collect_regions(
    chart_ir: dict[str, Any],
) -> list[tuple[str, str | None, list[str]]]:
    """Return ``[(region_name, initial_state, [state_ids]), ...]`` for a
    parallel chart; empty list for single-region.

    Per SOS-08-C §6.1 + the SOS-08-D wave-2c parallel-chart emit shape:
    a parallel chart has a top-level ``<parallel>`` element whose
    ``<state>`` children are the regions. Each region carries its own
    ``initial`` attribute + state list; the region's subtree shape is
    the same as a single-region chart's.

    Mirrors ``transliterate_sva_bind._collect_parallel_regions`` but
    extracts the per-region initial-state + state list at the same
    time (the SV testbench walker needs both for the per-region
    checker emit).
    """
    out: list[tuple[str, str | None, list[str]]] = []
    parallels = chart_ir.get("parallel") or []
    for par in parallels:
        for region_state in par.get("state") or []:
            rid = region_state.get("id")
            if not isinstance(rid, str) or not rid:
                continue
            initial = region_state.get("initial")
            if not isinstance(initial, str) or not initial:
                initial = None
            state_ids: list[str] = []
            for st in region_state.get("state") or []:
                sid = st.get("id")
                if isinstance(sid, str) and sid:
                    state_ids.append(sid)
            # Region initial defaults to first state when not declared.
            if initial is None and state_ids:
                initial = state_ids[0]
            out.append((rid, initial, state_ids))
    return out


def _collect_state_ids(chart_ir: dict[str, Any]) -> list[str]:
    """Walk ``<state>`` nodes in document order; return their IDs."""
    ids: list[str] = []
    for st in chart_ir.get("state") or []:
        sid = st.get("id")
        if isinstance(sid, str) and sid:
            ids.append(sid)
        # Recurse — nested states should appear after their parent in
        # document order for predictable encoding.
        for child in st.get("state") or []:
            csid = child.get("id")
            if isinstance(csid, str) and csid:
                ids.append(csid)
    return ids


def _collect_initial_state(chart_ir: dict[str, Any]) -> str | None:
    """The chart's ``initial`` attribute; falls back to the first state."""
    init = chart_ir.get("initial")
    if isinstance(init, str) and init:
        return init
    states = _collect_state_ids(chart_ir)
    return states[0] if states else None


def _classify_param_type(param: dict[str, Any]) -> str:
    """Wave-3-future-remaining (2026-05-24 §15): infer ``int`` vs
    ``string`` for a nested ``<param>``.

    SCXML ``<param>`` declares ``expr=`` (datamodel expression) — there
    is no native type attribute. The walker uses two coarse heuristics:

      * If ``expr`` is a bare integer literal (``\\d+`` with optional
        leading sign) the param is integer-typed.
      * If ``expr`` is a single-quoted or double-quoted bare string
        literal the param is string-typed.

    Everything else falls back to integer (the dominant case for the
    SOS-03 vector schema's payload integers — counts, sample indices,
    etc.). A chart author who needs string-typed nested fields can
    write ``expr="'foo'"`` or ``expr=\"\"\"bar\"\"\"`` to land in the
    string branch.
    """
    expr = param.get("expr")
    if not isinstance(expr, str):
        return "int"
    stripped = expr.strip()
    if (stripped.startswith("'") and stripped.endswith("'") and len(stripped) >= 2):
        return "string"
    if (stripped.startswith('"') and stripped.endswith('"') and len(stripped) >= 2):
        return "string"
    return "int"


_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_path_segments(p_name: str) -> list[str]:
    """Wave-3-future-remaining-path (2026-05-24 §15): validate the dot-
    separated path ``p_name`` and return its segment list.

    Build-time chart-vocab gate for ``<param name="..."/>`` declarations
    with one or more dots. Per §15 (2026-05-24 wave-3-future-path):

      * Every segment MUST match ``[A-Za-z_][A-Za-z0-9_]*`` (SV
        identifier rules).
      * Empty segments (``"a..b"``, ``".a"``, ``"a."``) raise
        ``UnsupportedChartError``.
      * Non-identifier characters in a segment (``"a-b"``, ``"a/b"``,
        digits-first) raise ``UnsupportedChartError``.

    The runtime ``$warning`` (in the emitted SV) handles malformed
    JSONL-side input data; this build-time gate handles malformed chart
    source so the failure surfaces during codegen.
    """
    segments = p_name.split(".")
    for seg in segments:
        if seg == "":
            raise UnsupportedChartError(
                "SOS-08-E wave-3-future-path: <param "
                f'name="{p_name}"/> contains an empty path segment; '
                "use dot-separated identifiers only."
            )
        if not _PATH_SEGMENT_RE.match(seg):
            raise UnsupportedChartError(
                "SOS-08-E wave-3-future-path: <param "
                f'name="{p_name}"/> segment "{seg}" violates SV '
                "identifier rules ``[A-Za-z_][A-Za-z0-9_]*``; use "
                "dot-separated identifiers only."
            )
    return segments


def _collect_nested_params(
    chart_ir: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """Wave-3-future-remaining (2026-05-24 §15): collect every
    one-level-deep nested ``<param>`` declaration in the chart.

    Walks all transitions (single-region + parallel-region) and every
    ``<raise>`` child's ``<param>`` list. A param's ``name`` attribute
    of shape ``"outer.inner"`` (exactly one dot) triggers the nested-
    payload emit path in the checker class (see ``_emit_checker_class``).

    Returns the list of unique ``(outer, inner, value_type)`` triples
    in document order; duplicates (same outer.inner appearing under
    multiple events) are collapsed — the checker emits one parse call
    per unique nested field, not one per raising event.

    Wave-3-future-path (2026-05-24 §15): ``<param>`` names with two or
    more dots (``"a.b.c"``, ``"a.b.c.d"``, ...) are collected by
    ``_collect_path_params`` instead. The build-time chart-vocab gate
    (empty segments, non-identifier chars) runs in
    ``_validate_path_segments`` and is invoked from both collectors.
    """
    seen: dict[tuple[str, str], str] = {}
    out: list[tuple[str, str, str]] = []

    def _visit_transitions(container: dict[str, Any]) -> None:
        for tr in container.get("transition", []) or []:
            for r in tr.get("raise_value", []) or []:
                for p in r.get("param", []) or []:
                    p_name = p.get("name")
                    if not isinstance(p_name, str):
                        continue
                    if p_name.count(".") != 1:
                        # Depth-0 (top-level) and depth-≥2 (path) are
                        # not nested-payload triggers — depth-0 goes
                        # through the wave-3-future top-level parsers;
                        # depth-≥2 goes through ``_collect_path_params``
                        # and the ``sos_jsonl_parse_path_*`` emit.
                        continue
                    segments = _validate_path_segments(p_name)
                    outer, inner = segments
                    vtype = _classify_param_type(p)
                    key = (outer, inner)
                    if key in seen:
                        continue
                    seen[key] = vtype
                    out.append((outer, inner, vtype))

    def _visit_state(state: dict[str, Any]) -> None:
        _visit_transitions(state)
        for child in state.get("state") or []:
            _visit_state(child)
        for par in state.get("parallel") or []:
            for region in par.get("state") or []:
                _visit_state(region)

    _visit_transitions(chart_ir)
    for st in chart_ir.get("state") or []:
        _visit_state(st)
    for par in chart_ir.get("parallel") or []:
        for region in par.get("state") or []:
            _visit_state(region)

    return out


def _collect_path_params(
    chart_ir: dict[str, Any],
) -> list[tuple[tuple[str, ...], str]]:
    """Wave-3-future-remaining-path (2026-05-24 §15): collect every
    deeper-than-one-level nested ``<param>`` declaration in the chart.

    Sibling of ``_collect_nested_params``. A param's ``name`` attribute
    of shape ``"a.b.c"`` (two or more dots) triggers the path-parser
    emit path in the checker class — a chain of object descents lowering
    to ``sos_jsonl_parse_path_int`` / ``sos_jsonl_parse_path_string``.

    Returns the list of unique ``(segments_tuple, value_type)`` pairs in
    document order; duplicates are collapsed.

    Build-time chart-vocab errors (empty segments, non-identifier
    characters, leading/trailing dots) raise ``UnsupportedChartError``
    via ``_validate_path_segments``.
    """
    seen: dict[tuple[str, ...], str] = {}
    out: list[tuple[tuple[str, ...], str]] = []

    def _visit_transitions(container: dict[str, Any]) -> None:
        for tr in container.get("transition", []) or []:
            for r in tr.get("raise_value", []) or []:
                for p in r.get("param", []) or []:
                    p_name = p.get("name")
                    if not isinstance(p_name, str):
                        continue
                    if p_name.count(".") < 2:
                        # Depth-0 (top-level) and depth-1 (nested) are
                        # handled elsewhere.
                        continue
                    segments = tuple(_validate_path_segments(p_name))
                    vtype = _classify_param_type(p)
                    if segments in seen:
                        continue
                    seen[segments] = vtype
                    out.append((segments, vtype))

    def _visit_state(state: dict[str, Any]) -> None:
        _visit_transitions(state)
        for child in state.get("state") or []:
            _visit_state(child)
        for par in state.get("parallel") or []:
            for region in par.get("state") or []:
                _visit_state(region)

    _visit_transitions(chart_ir)
    for st in chart_ir.get("state") or []:
        _visit_state(st)
    for par in chart_ir.get("parallel") or []:
        for region in par.get("state") or []:
            _visit_state(region)

    return out


# ---------------------------------------------------------------------------
# Module + class name conventions
# ---------------------------------------------------------------------------


def tb_module_name(chart_name: str) -> str:
    """``tb_<chart>`` — top-level testbench module name."""
    return f"tb_{_normalise_chart_name(chart_name)}"


def driver_class_name(chart_name: str) -> str:
    """``sos_driver_<chart>`` — stimulus driver class name."""
    return f"sos_driver_{_normalise_chart_name(chart_name)}"


def checker_class_name(chart_name: str) -> str:
    """``sos_checker_<chart>`` — response checker class name."""
    return f"sos_checker_{_normalise_chart_name(chart_name)}"


def virtual_if_name(chart_name: str) -> str:
    """``dut_if_<chart>`` — virtual interface name."""
    return f"dut_if_{_normalise_chart_name(chart_name)}"


def dut_module_name(chart_name: str) -> str:
    """``<chart>_fsm`` — DUT module name (chart-emitted FSM).

    Mirrors ``transliterate_sva_bind.dut_module_name`` so the testbench
    instantiates the same DUT module the SVA bind file binds to.
    """
    return f"{_normalise_chart_name(chart_name)}_fsm"


# ---------------------------------------------------------------------------
# Per-file emitters
# ---------------------------------------------------------------------------


_HEADER_PREFIX = """// SPDX-License-Identifier: MIT
// SOS-08-E wave-1 emitted artifact — DO NOT EDIT BY HAND.
//
// Generated by ``tools/sos-codegen/transliterate_hdl_sv_tb.py``.
//
// Spec references:
//   * SOS-08-E-CONCEPTS.md §5..§7 (emission contract + invariants)
//   * SOS-08-D-CONCEPTS.md  (SVA bind file artifact — byte-identical
//                             mirror per SOS-08-E §5.2)
//   * SOS-07-CONCEPTS.md   §6 INV-SOS-A..H (cross-phase invariants)
//   * SOS-08-CONCEPTS.md   §7 INV-S-HDL-1..5 (cross-sub-phase
//                            invariants; INV-S-HDL-5 = chart-vocabulary
//                            failure messages — load-bearing here)
//
// Invariants upheld by this artifact:
//   * INV-S-HDL-E-1: no `randomize` / `constraint` / `rand` / `randc`.
//   * INV-S-HDL-E-2: no UVM imports or macros.
//   * INV-S-HDL-E-3: no inline `assert property` (all SVA via bind).
//   * INV-S-HDL-E-4: failure messages in chart vocabulary.
//
"""


def _emit_virtual_interface(chart_name: str) -> str:
    """``dut_if_<chart>.sv`` — virtual interface for driver/checker.

    Wave-1: ports are ``clk``, ``rst``, ``current_state`` (DUT state
    output observable to the checker), plus a single ``event_in``
    placeholder input wide enough to carry the chart's stimulus events.
    Per PCDN-SOS-08-E-001 (flat shape) the interface is intentionally
    minimal; wave-2 widens it once the chart-event-port shape ratifies
    in SOS-08-C wave-3 events.
    """
    iface = virtual_if_name(chart_name)
    return _HEADER_PREFIX + f"""//
// Virtual interface for the {chart_name} chart testbench.
//
// The driver class drives ``clk_en``, ``rst``, and ``event_in``; the
// checker class observes ``current_state`` (the DUT's chart-FSM state
// output). All routing goes through this interface so driver/checker
// classes do not couple to the DUT module directly.

`ifndef DUT_IF_{chart_name.upper().replace('-', '_')}_SV
`define DUT_IF_{chart_name.upper().replace('-', '_')}_SV

interface {iface} #(
    parameter int N_STATES = 1,
    parameter int EVENT_W  = 8
) (
    input  logic clk
);

    // Drives (set by driver).
    logic                rst;
    logic                clk_en;
    logic [EVENT_W-1:0]  event_in;

    // Observables (read by checker).
    logic [N_STATES-1:0] current_state;

    // Driver modport — drives stimulus.
    modport driver_mp (
        output rst,
        output clk_en,
        output event_in,
        input  current_state,
        input  clk
    );

    // Checker modport — observes responses only.
    modport checker_mp (
        input  rst,
        input  clk_en,
        input  event_in,
        input  current_state,
        input  clk
    );

endinterface

`endif // DUT_IF_{chart_name.upper().replace('-', '_')}_SV
"""


def _emit_driver_class_base(chart_name: str) -> str:
    """``sos_<chart>_driver_base.svh`` — stimulus driver BASE class.

    Wave-3-future (2026-05-24 §15): the layered class hierarchy split
    factors the wave-3 monolithic driver into a base class that owns
    the run-skeleton (file open, reset, per-line replay loop, settle)
    and declares per-step virtual hooks; the generated wave-3 body
    moves into ``_default`` as overrides of those hooks.

    Hooks (all ``virtual``):

    - ``virtual task drive_pre(int step_idx);`` — pre-step hook;
      default no-op.
    - ``virtual task drive_step(int step_idx, sos_jsonl_record_t rec);``
      — the per-step drive itself; default no-op (the wave-3 default
      lives in ``sos_driver_<chart>``).
    - ``virtual task drive_post(int step_idx);`` — post-step hook;
      default no-op.

    Per task spec (§15 2026-05-24 layered-class-hierarchy): users who
    want to override one method extend ``_base`` themselves; the
    walker keeps emitting ``_default`` byte-identical to wave-3
    chart-vocab.
    """
    cls_base = f"sos_{_normalise_chart_name(chart_name)}_driver_base"
    iface = virtual_if_name(chart_name)
    return _HEADER_PREFIX + f"""//
// Stimulus driver BASE class for chart `{chart_name}`.
//
// Wave-3-future (2026-05-24 §15) layered class hierarchy: owns the
// run-skeleton (file open, reset, per-line replay, settle) and
// declares virtual per-step hooks. The wave-3-default driver
// (``sos_driver_{chart_name}``) extends this class and overrides
// ``drive_step`` with the generated body. User-side overrides extend
// this class and override one or more hooks without re-implementing
// the run-skeleton.
//
// Per SOS-08-E §6.1 + INV-S-HDL-E-1 the driver is constrained-random-
// free; all stimulus comes from the trace file. Per INV-S-HDL-E-3
// the driver does NOT inline any ``assert property``.

`ifndef SOS_{_normalise_chart_name(chart_name).upper()}_DRIVER_BASE_SVH
`define SOS_{_normalise_chart_name(chart_name).upper()}_DRIVER_BASE_SVH

`include "sos_jsonl_parser_pkg.svh"

// Per-step record carried into ``drive_step``. Holds the minimal
// JSONL event-poke shape decoded by the base run-skeleton.
typedef struct {{
    int    event_code;
    int    cycles_wait;
    string line;
}} sos_jsonl_record_t;

virtual class {cls_base};

    virtual {iface}.driver_mp vif;
    string                    trace_path;
    int                       vector_idx;

    function new(virtual {iface}.driver_mp vif, string trace_path);
        this.vif        = vif;
        this.trace_path = trace_path;
        this.vector_idx = 0;
    endfunction

    // ------------------------------------------------------------
    // Virtual per-step hooks. Defaults are no-ops; override in a
    // subclass to inject custom drive logic, logging, or wait
    // shaping. The wave-3-default ``sos_driver_{chart_name}``
    // overrides ``drive_step`` with the generated drive body.
    // ------------------------------------------------------------

    virtual task drive_pre(int step_idx);
        // Default no-op — override to instrument pre-step state.
    endtask

    virtual task drive_step(int step_idx, sos_jsonl_record_t rec);
        // Default no-op — the wave-3-default driver overrides this
        // hook to drive ``vif.event_in`` and emit the chart-vocab
        // [DRIVE] log.
    endtask

    virtual task drive_post(int step_idx);
        // Default no-op — override to instrument post-step state.
    endtask

    // ------------------------------------------------------------
    // Run-skeleton — owned by the base class. Opens the trace file,
    // walks each line, decodes the minimal JSONL shape, fires
    // ``drive_pre`` / ``drive_step`` / ``drive_post`` per step.
    // ------------------------------------------------------------
    task run();
        int    fh;
        string line;
        int    rc;
        int    parsed;
        sos_jsonl_record_t rec;

        fh = $fopen(trace_path, "r");
        if (fh == 0) begin
            $display("[FATAL] sos_driver: cannot open trace `%s`",
                     trace_path);
            $finish(2);
        end

        // Pre-test reset assertion (chart-FSM convention).
        vif.rst     = 1'b1;
        vif.clk_en  = 1'b0;
        vif.event_in = '0;
        repeat (4) @(posedge vif.clk);
        vif.rst    = 1'b0;
        vif.clk_en = 1'b1;
        @(posedge vif.clk);

        while (!$feof(fh)) begin
            rc = $fgets(line, fh);
            if (rc == 0) break;
            // SOS-08-E §5.4: JSONL trace; one event per line.
            rec.event_code  = 0;
            rec.cycles_wait = 1;
            rec.line        = line;
            parsed = sos_jsonl_parse_int(line, "event", rec.event_code);
            parsed = sos_jsonl_parse_int(line, "cycles", rec.cycles_wait);
            if (rec.cycles_wait <= 0) rec.cycles_wait = 1;

            drive_pre(vector_idx);
            drive_step(vector_idx, rec);
            drive_post(vector_idx);
        end

        $fclose(fh);

        // Settle period — wave-1 fixed at 8 cycles.
        repeat (8) @(posedge vif.clk);
    endtask

endclass

`endif // SOS_{_normalise_chart_name(chart_name).upper()}_DRIVER_BASE_SVH
"""


def _emit_driver_class(chart_name: str) -> str:
    """``sos_driver_<chart>.sv`` — stimulus driver DEFAULT class.

    Wave-3-future (2026-05-24 §15) layered class hierarchy: this class
    extends ``sos_<chart>_driver_base`` (in the ``_base.svh`` companion
    file) and overrides ``drive_step`` with the wave-3 generated drive
    body. Users who want a different drive shape extend ``_base``
    themselves; the walker keeps this default byte-identical to wave-3
    chart-vocab for the ``[DRIVE]`` log line.

    Consumes the JSONL trace file via ``$fopen`` + ``$fgets`` (in the
    base ``run()``), decodes each line's event-poke map, drives
    ``vif.event_in``, and waits the prescribed number of clock cycles
    between events. Per §6.1 the driver SHALL NOT inspect DUT outputs.
    """
    cls = driver_class_name(chart_name)
    cls_base = f"sos_{_normalise_chart_name(chart_name)}_driver_base"
    base_svh = f"sos_{_normalise_chart_name(chart_name)}_driver_base.svh"
    return _HEADER_PREFIX + f"""//
// Stimulus driver DEFAULT class for the {chart_name} chart testbench.
//
// Wave-3-future (2026-05-24 §15) layered class hierarchy: extends
// ``{cls_base}`` (declared in ``{base_svh}``) and overrides
// ``drive_step`` with the wave-3 generated drive body. The base
// class owns the run-skeleton (file open, reset, per-line replay,
// settle). Users SHOULD extend the base class to customise the drive
// behaviour rather than copy-pasting this class.
//
// Per SOS-08-E §6.1 + INV-S-HDL-E-1 the driver is constrained-random-
// free — all stimulus comes from the trace file. Per INV-S-HDL-E-3
// the driver does NOT inline any ``assert property``; property
// checking lives exclusively in the bound SVA module.
//
// Wave-3-future (2026-05-24 §15): JSONL parsing is sourced from the
// shared ``sos_jsonl_parser_pkg.svh`` header (single-source for both
// the driver and the checker); the legacy inline ``parse_int_field``
// is gone in favour of ``sos_jsonl_parse_int``.

`include "{base_svh}"

class {cls} extends {cls_base};

    function new(virtual {virtual_if_name(chart_name)}.driver_mp vif, string trace_path);
        super.new(vif, trace_path);
    endfunction

    // Wave-3-default ``drive_step`` body — the per-event drive shape
    // emitted by the wave-3 monolithic walker. Drives ``vif.event_in``
    // for one cycle, then waits ``cycles_wait - 1`` extra cycles.
    virtual task drive_step(int step_idx, sos_jsonl_record_t rec);
        vif.event_in = rec.event_code[7:0];
        @(posedge vif.clk);
        vif.event_in = '0;
        repeat (rec.cycles_wait - 1) @(posedge vif.clk);

        vector_idx = vector_idx + 1;
        $display("[DRIVE] V%0d: event=%0d cycles=%0d  // chart=`{chart_name}`",
                 vector_idx, rec.event_code, rec.cycles_wait);
    endtask

endclass
"""


def _emit_jsonl_parser_pkg(chart_name: str) -> str:
    """``sos_jsonl_parser_pkg.svh`` — shared SV header-only package.

    SOS-08-E wave-3-future (2026-05-24 §15): factors the wave-1
    integer-field extractor out of the driver + checker source files
    into a shared SystemVerilog header, and adds a string-field
    extractor so SOS-03 vector traces with string-valued state names
    (per the SOS-03 §15 2026-05-24 schema extension) can be consumed
    directly by the checker without an external Python preflight.

    The package is header-only (``\\`include``-able) rather than a
    SV package import to keep wave-1 build flows unchanged — adding a
    `package` keyword would force every Makefile to compile the
    package before the consumers, which is unnecessary tooling churn
    for a two-function helper.

    Functions:

      * ``sos_jsonl_parse_int(line, key, value) → int`` — extracts a
        bare-integer JSON field. Returns 1 on hit, 0 on miss.
        Identical contract to the wave-1 ``parse_int_field`` it
        supersedes (the wave-3-future emit aliases the legacy name
        inside the consumer classes for source-level continuity).
      * ``sos_jsonl_parse_string(line, key, value, max_len) → int`` —
        extracts a quoted-string JSON field, populating ``value``
        (output string) up to ``max_len`` characters. Returns 1 on
        hit, 0 on miss. Strips no escapes — SOS-03 chart-state names
        are bare identifiers with no special characters per §5.4 of
        the SOS-03 vector schema spec.

    Wave-3-future-remaining-path (2026-05-24 §15): adds two new
    functions for arbitrary-depth dot-path descent, alongside the
    existing one-level-deep ``_nested_*`` functions (kept byte-identical
    for regression-guard purposes):

      * ``sos_jsonl_parse_path_int(line, path_dot_separated, value)`` —
        splits ``path_dot_separated`` on ``.``, descends through nested
        objects level by level, extracts the leaf integer. 1 on hit, 0
        on absence at any level / malformed scalar mid-path / empty
        segment (with a one-line ``$warning`` for empty segments since
        the build-time chart-vocab gate should have caught those).
      * ``sos_jsonl_parse_path_string(line, path_dot_separated, value)``
        — same shape, string leaf, 1024-character cap preserved.

    Per INV-S-HDL-E-1 all four functions are constrained-random-free.
    Per INV-S-HDL-E-2 no UVM symbols are referenced.
    Per INV-S-HDL-E-3 no SVA properties are declared.
    """
    base = _normalise_chart_name(chart_name)
    guard = f"SOS_JSONL_PARSER_PKG_{base.upper()}_SVH"
    return _HEADER_PREFIX + f"""//
// Shared JSON-Lines field extractors for the {chart_name} SV testbench.
//
// Per SOS-08-E §15 wave-3-future (2026-05-24): factor the wave-1
// integer-field extractor into a shared header; add string-field
// extraction for SOS-03 vector traces that carry symbolic state
// names (per SOS-03 §15 2026-05-24 schema extension).
//
// `\\`include`d by ``sos_driver_{chart_name}.sv`` and
// ``sos_checker_{chart_name}.sv`` to keep parse logic single-source.

`ifndef {guard}
`define {guard}

// ---------------------------------------------------------------------------
// sos_jsonl_parse_int — wave-1 integer-field extractor, lifted into
// the shared header. Returns 1 on hit, 0 on miss; populates ``value``
// (inout) with the parsed signed integer.
// ---------------------------------------------------------------------------
function automatic int sos_jsonl_parse_int(
    input  string line,
    input  string key,
    inout  int    value
);
    int   klen;
    int   slen;
    int   i;
    int   j;
    int   sign;
    byte  ch;
    int   hit;
    int   acc;
    slen = line.len();
    klen = key.len();
    hit  = 0;
    for (i = 0; i + klen + 2 <= slen; i++) begin
        if (line.getc(i) == "\\"") begin
            hit = 1;
            for (j = 0; j < klen; j++) begin
                if (line.getc(i + 1 + j) != key.getc(j)) begin
                    hit = 0;
                    break;
                end
            end
            if (hit && line.getc(i + 1 + klen) == "\\"") begin
                j = i + 2 + klen;
                while (j < slen &&
                      (line.getc(j) == " " || line.getc(j) == ":" ||
                       line.getc(j) == 9)) j++;
                sign = 1;
                if (j < slen && line.getc(j) == "-") begin
                    sign = -1;
                    j++;
                end
                acc = 0;
                while (j < slen &&
                      line.getc(j) >= "0" && line.getc(j) <= "9") begin
                    ch = line.getc(j);
                    acc = acc * 10 + (ch - 8'h30);
                    j++;
                end
                value = sign * acc;
                return 1;
            end
            hit = 0;
        end
    end
    return 0;
endfunction

// ---------------------------------------------------------------------------
// sos_jsonl_parse_string — quoted-string field extractor. Populates
// ``value`` with the contents of the matched `"<key>": "<string>"`
// pair. Returns 1 on hit, 0 on miss. No escape processing — SOS-03
// chart-state names are bare identifiers per the vector-schema spec.
// ---------------------------------------------------------------------------
function automatic int sos_jsonl_parse_string(
    input  string line,
    input  string key,
    inout  string value
);
    int   klen;
    int   slen;
    int   i;
    int   j;
    int   k;
    int   hit;
    byte  ch;
    slen = line.len();
    klen = key.len();
    hit  = 0;
    for (i = 0; i + klen + 2 <= slen; i++) begin
        if (line.getc(i) == "\\"") begin
            hit = 1;
            for (j = 0; j < klen; j++) begin
                if (line.getc(i + 1 + j) != key.getc(j)) begin
                    hit = 0;
                    break;
                end
            end
            if (hit && line.getc(i + 1 + klen) == "\\"") begin
                j = i + 2 + klen;
                // Skip whitespace + colon.
                while (j < slen &&
                      (line.getc(j) == " " || line.getc(j) == ":" ||
                       line.getc(j) == 9)) j++;
                // Expect opening quote.
                if (j >= slen || line.getc(j) != "\\"") begin
                    return 0;
                end
                j++; // skip opening quote
                value = "";
                k = 0;
                while (j < slen && line.getc(j) != "\\"") begin
                    ch = line.getc(j);
                    value = {{value, string'(ch)}};
                    j++;
                    k++;
                    // Cap to keep the inner loop bounded against
                    // malformed lines (no closing quote). 1024 chars
                    // is multiples of any realistic chart-state name.
                    if (k >= 1024) break;
                end
                return 1;
            end
            hit = 0;
        end
    end
    return 0;
endfunction

// ---------------------------------------------------------------------------
// sos_jsonl_parse_nested_int — one-level-deep nested-object integer
// field extractor. Locates the outer-key followed by an opening
// brace, then the inner-key followed by a bare integer. Returns 1
// on hit, 0 on miss / malformed.
//
// SOS-08-E wave-3-future-remaining (2026-05-24 §15): enables checker
// emit to consume SOS-03 vector traces that carry structured payloads
// such as ``payload`` objects with named integer fields. Defensive on
// malformed outer scalars — ``"outer":42`` (no opening brace) returns
// 0 without raising.
// ---------------------------------------------------------------------------
function automatic int sos_jsonl_parse_nested_int(
    input  string line,
    input  string outer_key,
    input  string inner_key,
    output int    value
);
    int   slen;
    int   olen;
    int   ilen;
    int   i;
    int   j;
    int   k;
    int   depth;
    int   obj_end;
    int   sign;
    int   acc;
    int   match_outer;
    int   match_inner;
    byte  ch;
    slen = line.len();
    olen = outer_key.len();
    ilen = inner_key.len();
    // Scan for ``"<outer_key>"``.
    for (i = 0; i + olen + 2 <= slen; i++) begin
        if (line.getc(i) != "\\"") continue;
        match_outer = 1;
        for (j = 0; j < olen; j++) begin
            if (line.getc(i + 1 + j) != outer_key.getc(j)) begin
                match_outer = 0;
                break;
            end
        end
        if (!match_outer) continue;
        if (line.getc(i + 1 + olen) != "\\"") continue;
        // Skip whitespace + colon between key and value.
        j = i + 2 + olen;
        while (j < slen &&
              (line.getc(j) == " " || line.getc(j) == ":" ||
               line.getc(j) == 9)) j++;
        // Defensive: outer value MUST be an object (open brace). A
        // scalar like ``"outer":42`` is not a parse error — return 0.
        if (j >= slen || line.getc(j) != "{{") return 0;
        // Locate matching closing brace (depth-tracked; one-level deep
        // — nested objects increment depth but we still scan within).
        depth = 1;
        obj_end = j + 1;
        while (obj_end < slen && depth > 0) begin
            ch = line.getc(obj_end);
            if (ch == "{{") depth = depth + 1;
            else if (ch == "}}") depth = depth - 1;
            obj_end = obj_end + 1;
        end
        // ``obj_end`` now points one past the matching ``}}``.
        // Scan ``[j+1, obj_end-1)`` for ``"<inner_key>"`` then a bare
        // integer (with optional sign).
        for (k = j + 1; k + ilen + 2 < obj_end; k++) begin
            if (line.getc(k) != "\\"") continue;
            match_inner = 1;
            for (j = 0; j < ilen; j++) begin
                if (line.getc(k + 1 + j) != inner_key.getc(j)) begin
                    match_inner = 0;
                    break;
                end
            end
            if (!match_inner) continue;
            if (line.getc(k + 1 + ilen) != "\\"") continue;
            j = k + 2 + ilen;
            while (j < obj_end &&
                  (line.getc(j) == " " || line.getc(j) == ":" ||
                   line.getc(j) == 9)) j++;
            sign = 1;
            if (j < obj_end && line.getc(j) == "-") begin
                sign = -1;
                j++;
            end
            acc = 0;
            // Require at least one digit; bail out on scalar miss.
            if (j >= obj_end || line.getc(j) < "0" ||
                line.getc(j) > "9") return 0;
            while (j < obj_end &&
                  line.getc(j) >= "0" && line.getc(j) <= "9") begin
                ch = line.getc(j);
                acc = acc * 10 + (ch - 8'h30);
                j++;
            end
            value = sign * acc;
            return 1;
        end
        // Inner key not present inside the outer object — defensive
        // miss (do NOT keep scanning the outer line for a stray
        // re-occurrence of outer_key elsewhere).
        return 0;
    end
    return 0;
endfunction

// ---------------------------------------------------------------------------
// sos_jsonl_parse_nested_string — one-level-deep nested-object string
// field extractor. Locates the outer-key followed by an opening
// brace, then the inner-key followed by a quoted string. Returns 1
// on hit, 0 on miss / malformed.
//
// Preserves the wave-3-future top-level extractor behaviour at the
// 1024-character cap, including support for ``\\"`` escaped quotes
// inside the string value (the escape is preserved verbatim — SOS-03
// chart-state names are bare identifiers but downstream consumers may
// carry richer payloads).
// ---------------------------------------------------------------------------
function automatic int sos_jsonl_parse_nested_string(
    input  string line,
    input  string outer_key,
    input  string inner_key,
    output string value
);
    int   slen;
    int   olen;
    int   ilen;
    int   i;
    int   j;
    int   k;
    int   m;
    int   depth;
    int   obj_end;
    int   cap;
    int   match_outer;
    int   match_inner;
    byte  ch;
    byte  prev_ch;
    slen = line.len();
    olen = outer_key.len();
    ilen = inner_key.len();
    for (i = 0; i + olen + 2 <= slen; i++) begin
        if (line.getc(i) != "\\"") continue;
        match_outer = 1;
        for (j = 0; j < olen; j++) begin
            if (line.getc(i + 1 + j) != outer_key.getc(j)) begin
                match_outer = 0;
                break;
            end
        end
        if (!match_outer) continue;
        if (line.getc(i + 1 + olen) != "\\"") continue;
        j = i + 2 + olen;
        while (j < slen &&
              (line.getc(j) == " " || line.getc(j) == ":" ||
               line.getc(j) == 9)) j++;
        if (j >= slen || line.getc(j) != "{{") return 0;
        depth = 1;
        obj_end = j + 1;
        while (obj_end < slen && depth > 0) begin
            ch = line.getc(obj_end);
            if (ch == "{{") depth = depth + 1;
            else if (ch == "}}") depth = depth - 1;
            obj_end = obj_end + 1;
        end
        for (k = j + 1; k + ilen + 2 < obj_end; k++) begin
            if (line.getc(k) != "\\"") continue;
            match_inner = 1;
            for (j = 0; j < ilen; j++) begin
                if (line.getc(k + 1 + j) != inner_key.getc(j)) begin
                    match_inner = 0;
                    break;
                end
            end
            if (!match_inner) continue;
            if (line.getc(k + 1 + ilen) != "\\"") continue;
            j = k + 2 + ilen;
            while (j < obj_end &&
                  (line.getc(j) == " " || line.getc(j) == ":" ||
                   line.getc(j) == 9)) j++;
            // Expect opening quote for the value.
            if (j >= obj_end || line.getc(j) != "\\"") return 0;
            j++; // skip opening quote
            value = "";
            cap = 0;
            prev_ch = 0;
            // Escape-aware scan: a backslash before a quote consumes
            // the quote as a literal. Mirrors the wave-3-future
            // top-level extractor's 1024-character cap so a malformed
            // line cannot pin the inner loop.
            while (j < obj_end) begin
                ch = line.getc(j);
                if (ch == "\\"" && prev_ch != "\\\\") begin
                    return 1;
                end
                value = {{value, string'(ch)}};
                prev_ch = ch;
                j++;
                cap++;
                if (cap >= 1024) return 1;
            end
            // Hit obj_end before closing quote — malformed, but
            // defensive: return what we have rather than spinning.
            return 1;
        end
        return 0;
    end
    return 0;
endfunction

// ---------------------------------------------------------------------------
// sos_jsonl_parse_path_int — arbitrary-depth nested-object integer
// field extractor. ``path_dot_separated`` is split on ``.``; the parser
// descends through each named object level, then extracts the leaf
// integer at the innermost key. Returns 1 on hit, 0 on miss / malformed
// at any descent level.
//
// SOS-08-E wave-3-future-remaining-path (2026-05-24 §15): lifts the
// one-level-deep cap from the ``_nested_*`` extractors. Defensive at
// every level — a malformed scalar mid-path returns 0 (not a parse
// error). An empty segment (``"a..b"``) emits a one-line ``$warning``
// at runtime so the chart author sees the malformed JSONL input;
// build-time chart-vocab malformation is gated by the walker.
//
// Algorithm sketch: walk ``path_dot_separated`` segment-by-segment.
// For each segment, locate ``"<segment>":`` inside the current
// substring window (initially the full ``line``; subsequently bounded
// by the previously located object's brace pair). On the final
// segment, expect a bare integer; on intermediate segments, expect
// ``{{`` and update the window to the contents of that object.
// ---------------------------------------------------------------------------
function automatic int sos_jsonl_parse_path_int(
    input  string line,
    input  string path_dot_separated,
    output int    value
);
    int   slen;
    int   plen;
    int   i;
    int   j;
    int   k;
    int   depth;
    int   win_lo;
    int   win_hi;
    int   seg_lo;
    int   seg_hi;
    int   total_segments;
    int   seg_idx;
    int   match_seg;
    int   sign;
    int   acc;
    int   seg_len;
    int   is_last;
    int   warned_empty;
    byte  ch;
    slen = line.len();
    plen = path_dot_separated.len();
    // Count segments + sanity-check for empty segments. Empty segments
    // at runtime indicate a malformed chart-vocab string (the build-
    // time gate normally rejects these); emit a one-line $warning so
    // the chart author sees it and return 0.
    total_segments = 0;
    warned_empty = 0;
    seg_lo = 0;
    for (i = 0; i <= plen; i++) begin
        if (i == plen || path_dot_separated.getc(i) == ".") begin
            if (i == seg_lo) begin
                if (!warned_empty) begin
                    $warning("sos_jsonl_parse_path_int: empty path segment in \\"%s\\"; returning 0.", path_dot_separated);
                    warned_empty = 1;
                end
                return 0;
            end
            total_segments = total_segments + 1;
            seg_lo = i + 1;
        end
    end
    if (total_segments == 0) return 0;
    // Descend: for each segment, locate the key inside [win_lo, win_hi)
    // and either narrow the window to the contained object (non-final)
    // or extract the leaf integer (final).
    win_lo = 0;
    win_hi = slen;
    seg_lo = 0;
    for (seg_idx = 0; seg_idx < total_segments; seg_idx = seg_idx + 1) begin
        // Find the end of this segment in path_dot_separated.
        seg_hi = seg_lo;
        while (seg_hi < plen && path_dot_separated.getc(seg_hi) != ".") begin
            seg_hi = seg_hi + 1;
        end
        seg_len = seg_hi - seg_lo;
        is_last = (seg_idx == total_segments - 1);
        // Scan [win_lo, win_hi) for ``"<segment>"``.
        match_seg = 0;
        for (i = win_lo; i + seg_len + 2 <= win_hi; i = i + 1) begin
            if (line.getc(i) != "\\"") continue;
            match_seg = 1;
            for (j = 0; j < seg_len; j = j + 1) begin
                if (line.getc(i + 1 + j) != path_dot_separated.getc(seg_lo + j)) begin
                    match_seg = 0;
                    break;
                end
            end
            if (!match_seg) continue;
            if (line.getc(i + 1 + seg_len) != "\\"") begin
                match_seg = 0;
                continue;
            end
            // Found ``"<segment>"``. Skip whitespace + colon.
            j = i + 2 + seg_len;
            while (j < win_hi &&
                  (line.getc(j) == " " || line.getc(j) == ":" ||
                   line.getc(j) == 9)) j = j + 1;
            if (is_last) begin
                // Leaf: expect bare integer (with optional sign).
                sign = 1;
                if (j < win_hi && line.getc(j) == "-") begin
                    sign = -1;
                    j = j + 1;
                end
                // Defensive: require at least one digit.
                if (j >= win_hi || line.getc(j) < "0" || line.getc(j) > "9") begin
                    return 0;
                end
                acc = 0;
                while (j < win_hi &&
                      line.getc(j) >= "0" && line.getc(j) <= "9") begin
                    ch = line.getc(j);
                    acc = acc * 10 + (ch - 8'h30);
                    j = j + 1;
                end
                value = sign * acc;
                return 1;
            end else begin
                // Intermediate: expect ``{{`` and narrow the window to
                // the matching close-brace range.
                if (j >= win_hi || line.getc(j) != "{{") return 0;
                depth = 1;
                k = j + 1;
                while (k < win_hi && depth > 0) begin
                    ch = line.getc(k);
                    if (ch == "{{") depth = depth + 1;
                    else if (ch == "}}") depth = depth - 1;
                    k = k + 1;
                end
                // k is now one past the matching ``}}`` (or win_hi if
                // unterminated). Narrow window to (j+1, k-1).
                win_lo = j + 1;
                win_hi = (k > 0) ? (k - 1) : k;
                seg_lo = seg_hi + 1;
                break;
            end
        end
        if (!match_seg) return 0;
    end
    return 0;
endfunction

// ---------------------------------------------------------------------------
// sos_jsonl_parse_path_string — arbitrary-depth nested-object string
// field extractor. Same shape as ``sos_jsonl_parse_path_int`` but the
// leaf is a quoted string. 1024-character cap preserved (mirrors the
// wave-3-future top-level + ``_nested_string`` extractors). Escape-
// aware: a backslash before a quote consumes the quote as a literal.
// ---------------------------------------------------------------------------
function automatic int sos_jsonl_parse_path_string(
    input  string line,
    input  string path_dot_separated,
    output string value
);
    int   slen;
    int   plen;
    int   i;
    int   j;
    int   k;
    int   depth;
    int   win_lo;
    int   win_hi;
    int   seg_lo;
    int   seg_hi;
    int   total_segments;
    int   seg_idx;
    int   match_seg;
    int   seg_len;
    int   is_last;
    int   cap;
    int   warned_empty;
    byte  ch;
    byte  prev_ch;
    slen = line.len();
    plen = path_dot_separated.len();
    total_segments = 0;
    warned_empty = 0;
    seg_lo = 0;
    for (i = 0; i <= plen; i = i + 1) begin
        if (i == plen || path_dot_separated.getc(i) == ".") begin
            if (i == seg_lo) begin
                if (!warned_empty) begin
                    $warning("sos_jsonl_parse_path_string: empty path segment in \\"%s\\"; returning 0.", path_dot_separated);
                    warned_empty = 1;
                end
                return 0;
            end
            total_segments = total_segments + 1;
            seg_lo = i + 1;
        end
    end
    if (total_segments == 0) return 0;
    win_lo = 0;
    win_hi = slen;
    seg_lo = 0;
    for (seg_idx = 0; seg_idx < total_segments; seg_idx = seg_idx + 1) begin
        seg_hi = seg_lo;
        while (seg_hi < plen && path_dot_separated.getc(seg_hi) != ".") begin
            seg_hi = seg_hi + 1;
        end
        seg_len = seg_hi - seg_lo;
        is_last = (seg_idx == total_segments - 1);
        match_seg = 0;
        for (i = win_lo; i + seg_len + 2 <= win_hi; i = i + 1) begin
            if (line.getc(i) != "\\"") continue;
            match_seg = 1;
            for (j = 0; j < seg_len; j = j + 1) begin
                if (line.getc(i + 1 + j) != path_dot_separated.getc(seg_lo + j)) begin
                    match_seg = 0;
                    break;
                end
            end
            if (!match_seg) continue;
            if (line.getc(i + 1 + seg_len) != "\\"") begin
                match_seg = 0;
                continue;
            end
            j = i + 2 + seg_len;
            while (j < win_hi &&
                  (line.getc(j) == " " || line.getc(j) == ":" ||
                   line.getc(j) == 9)) j = j + 1;
            if (is_last) begin
                // Leaf: expect opening quote.
                if (j >= win_hi || line.getc(j) != "\\"") return 0;
                j = j + 1;
                value = "";
                cap = 0;
                prev_ch = 0;
                while (j < win_hi) begin
                    ch = line.getc(j);
                    if (ch == "\\"" && prev_ch != "\\\\") begin
                        return 1;
                    end
                    value = {{value, string'(ch)}};
                    prev_ch = ch;
                    j = j + 1;
                    cap = cap + 1;
                    if (cap >= 1024) return 1;
                end
                // Hit window end before closing quote — defensive
                // return-what-we-have to avoid spinning.
                return 1;
            end else begin
                if (j >= win_hi || line.getc(j) != "{{") return 0;
                depth = 1;
                k = j + 1;
                while (k < win_hi && depth > 0) begin
                    ch = line.getc(k);
                    if (ch == "{{") depth = depth + 1;
                    else if (ch == "}}") depth = depth - 1;
                    k = k + 1;
                end
                win_lo = j + 1;
                win_hi = (k > 0) ? (k - 1) : k;
                seg_lo = seg_hi + 1;
                break;
            end
        end
        if (!match_seg) return 0;
    end
    return 0;
endfunction

`endif // {guard}
"""


def _emit_state_symbols(chart_name: str, state_ids: list[str]) -> str:
    """``sos_<chart>_state_symbols.svh`` — per-chart state symbol table.

    SOS-08-E wave-3-future (2026-05-24 §15): emits a single SV
    function ``sos_<chart>_state_id_of(string name) → int`` mapping
    chart-state names to their one-hot encoding bit position (matching
    SOS-08-C ``_emit_state_constants`` document-order convention).
    Returns -1 for unknown names so the checker can render a chart-
    vocabulary failure message naming the offending state.

    Index 0..N-1 corresponds to the bit position in the one-hot
    encoding; the checker constructs the one-hot value via
    ``1 << sos_<chart>_state_id_of(name)`` and compares against
    ``current_state``.
    """
    base = _normalise_chart_name(chart_name)
    guard = f"SOS_STATE_SYMBOLS_{base.upper()}_SVH"
    fn_name = f"sos_{base}_state_id_of"
    lines: list[str] = []
    lines.append(_HEADER_PREFIX.rstrip())
    lines.append(
        f"\n//\n// Per-chart state symbol table for `{chart_name}` — \n"
        f"// maps chart-state names to their one-hot bit position.\n"
        f"//\n// Per SOS-08-E §15 wave-3-future: the checker uses this\n"
        f"// to consume SOS-03 vector traces with string-valued\n"
        f"// `expected_state_str` fields (per SOS-03 §15 2026-05-24\n"
        f"// schema extension), rendering chart-vocabulary failure\n"
        f"// messages naming the offending state by chart name per\n"
        f"// INV-S-HDL-E-4 + INV-SOS-H.\n//\n"
    )
    lines.append(f"`ifndef {guard}")
    lines.append(f"`define {guard}")
    lines.append("")
    lines.append("// Returns the one-hot bit position for `name`, or -1 if")
    lines.append("// the name is not a known chart-state.")
    lines.append(f"function automatic int {fn_name}(input string name);")
    if state_ids:
        for idx, sid in enumerate(state_ids):
            # SystemVerilog string comparison uses ==.
            lines.append(f'    if (name == "{sid}") return {idx};')
    lines.append("    return -1;")
    lines.append("endfunction")
    lines.append("")
    lines.append(f"`endif // {guard}")
    return "\n".join(lines) + "\n"


def _render_nested_param_blocks(
    nested_params: list[tuple[str, str, str]],
    decl_indent: str,
    parse_indent: str,
    path_params: list[tuple[tuple[str, ...], str]] | None = None,
) -> tuple[str, str]:
    """Wave-3-future-remaining (2026-05-24 §15): emit the SV declaration
    + parse blocks for one-level-deep nested ``<param>`` fields.

    Returns ``(decls, parse_block)`` — both empty strings when
    ``nested_params`` and ``path_params`` are both empty, so callers'
    f-strings can interpolate them unconditionally without disturbing
    the wave-3-future byte-identical baseline.

    ``decl_indent`` is the column prefix for the local-variable
    declarations at the top of ``run()`` (typically 8 spaces).
    ``parse_indent`` is the column prefix for the parse calls inside
    the per-step loop (typically 12 spaces).

    Wave-3-future-remaining-path (2026-05-24 §15): ``path_params``
    (depth-≥2 declarations) MAY be passed. When non-empty, additional
    decls + ``sos_jsonl_parse_path_*`` calls are emitted after the
    depth-1 blocks. Charts using only depth-0 or depth-1 params get
    byte-identical emit to the prior wave-3-future-remaining baseline.
    """
    path_params = path_params or []
    if not nested_params and not path_params:
        return "", ""
    decl_lines: list[str] = []
    parse_lines: list[str] = []
    if nested_params:
        decl_lines.append("")
        decl_lines.append(
            f"{decl_indent}// Wave-3-future-remaining: nested-payload locals."
        )
        parse_lines.append("")
        parse_lines.append(
            f"{parse_indent}// Wave-3-future-remaining: nested-payload extraction"
        )
        parse_lines.append(
            f"{parse_indent}// (one level deep) per chart-declared <param "
            "name=\"outer.inner\"/>."
        )
        for outer, inner, vtype in nested_params:
            var = _sanitize_sv_identifier(f"{outer}_{inner}")
            parsed_var = f"parsed_nested_{var}"
            if vtype == "string":
                decl_lines.append(
                    f"{decl_indent}string nested_{var};"
                )
                decl_lines.append(
                    f"{decl_indent}int    {parsed_var};"
                )
                parse_lines.append(
                    f'{parse_indent}nested_{var} = "";'
                )
                parse_lines.append(
                    f"{parse_indent}{parsed_var} = sos_jsonl_parse_nested_string("
                )
                parse_lines.append(
                    f'{parse_indent}    line, "{outer}", "{inner}", nested_{var}'
                )
                parse_lines.append(f"{parse_indent});")
            else:
                decl_lines.append(
                    f"{decl_indent}int    nested_{var};"
                )
                decl_lines.append(
                    f"{decl_indent}int    {parsed_var};"
                )
                parse_lines.append(
                    f"{parse_indent}nested_{var} = 0;"
                )
                parse_lines.append(
                    f"{parse_indent}{parsed_var} = sos_jsonl_parse_nested_int("
                )
                parse_lines.append(
                    f'{parse_indent}    line, "{outer}", "{inner}", nested_{var}'
                )
                parse_lines.append(f"{parse_indent});")
    if path_params:
        decl_lines.append("")
        decl_lines.append(
            f"{decl_indent}// Wave-3-future-remaining-path: deep-nested-"
            "payload locals."
        )
        parse_lines.append("")
        parse_lines.append(
            f"{parse_indent}// Wave-3-future-remaining-path: arbitrary-"
            "depth nested-payload"
        )
        parse_lines.append(
            f"{parse_indent}// extraction per chart-declared <param "
            "name=\"a.b.c\"/>."
        )
        for segments, vtype in path_params:
            var = _sanitize_sv_identifier("_".join(segments))
            parsed_var = f"parsed_path_{var}"
            path_literal = ".".join(segments)
            if vtype == "string":
                decl_lines.append(
                    f"{decl_indent}string path_{var};"
                )
                decl_lines.append(
                    f"{decl_indent}int    {parsed_var};"
                )
                parse_lines.append(
                    f'{parse_indent}path_{var} = "";'
                )
                parse_lines.append(
                    f"{parse_indent}{parsed_var} = sos_jsonl_parse_path_string("
                )
                parse_lines.append(
                    f'{parse_indent}    line, "{path_literal}", path_{var}'
                )
                parse_lines.append(f"{parse_indent});")
            else:
                decl_lines.append(
                    f"{decl_indent}int    path_{var};"
                )
                decl_lines.append(
                    f"{decl_indent}int    {parsed_var};"
                )
                parse_lines.append(
                    f"{parse_indent}path_{var} = 0;"
                )
                parse_lines.append(
                    f"{parse_indent}{parsed_var} = sos_jsonl_parse_path_int("
                )
                parse_lines.append(
                    f'{parse_indent}    line, "{path_literal}", path_{var}'
                )
                parse_lines.append(f"{parse_indent});")
    return "\n".join(decl_lines), "\n".join(parse_lines)


def _emit_checker_class_base(
    chart_name: str,
    nested_params: list[tuple[str, str, str]] | None = None,
    path_params: list[tuple[tuple[str, ...], str]] | None = None,
) -> str:
    """``sos_<chart>_checker_base.svh`` — response checker BASE class.

    Wave-3-future (2026-05-24 §15) layered class hierarchy: factors
    the wave-3 monolithic checker into a base class that owns the
    structural skeleton + per-step virtual hooks. The wave-3-default
    checker (``sos_checker_<chart>``) extends this class and overrides
    the hooks with the generated body.

    Virtual hooks declared here:

    - ``virtual function bit pre_step(int step_idx);`` — returns 1 by
      default; returning 0 SHALL skip the per-step parse/compare.
    - ``virtual function void on_state_transition(int prev_state, int
      next_state, int trigger_event);`` — default no-op.
    - ``virtual function void on_invariant_fail(int invariant_id,
      string message);`` — default emits ``$error(message)``. The
      chart-vocab message construction lives in the base ``run()``;
      override hooks SHOULD call ``super.on_invariant_fail(...)``
      after any custom logging.
    - ``virtual function void post_step(int step_idx);`` — default
      no-op.

    The chart-vocab failure-message format strings live in this base
    class's ``run()`` so the byte-identity regression guard
    (``test_chart_vocab_message_byte_identical_to_wave3_baseline``)
    holds across the wave-3 → layered refactor.
    """
    base = _normalise_chart_name(chart_name)
    cls_base = f"sos_{base}_checker_base"
    iface = virtual_if_name(chart_name)
    symbol_fn = f"sos_{base}_state_id_of"
    nested_decls, nested_parse = _render_nested_param_blocks(
        nested_params or [],
        decl_indent="        ",
        parse_indent="            ",
        path_params=path_params or [],
    )
    return _HEADER_PREFIX + f"""//
// Response checker BASE class for the {chart_name} chart testbench.
//
// Wave-3-future (2026-05-24 §15) layered class hierarchy: owns the
// per-line replay loop, parse/resolve logic, and chart-vocabulary
// failure-message construction. Declares four virtual hooks
// (``pre_step`` / ``on_state_transition`` / ``on_invariant_fail`` /
// ``post_step``); the wave-3-default checker (``{checker_class_name(chart_name)}``)
// extends this class and overrides them. User-side overrides extend
// this class and override one or more hooks without re-implementing
// the run-skeleton.
//
// Per SOS-08-E §5.5 + INV-S-HDL-E-4 every failure renders in chart
// vocabulary with the failing vector index, chart region, and
// observed-vs-expected values. Per INV-S-HDL-E-3 the checker does
// NOT inline any ``assert property``.

`ifndef SOS_{base.upper()}_CHECKER_BASE_SVH
`define SOS_{base.upper()}_CHECKER_BASE_SVH

`include "sos_jsonl_parser_pkg.svh"
`include "sos_{base}_state_symbols.svh"

virtual class {cls_base};

    virtual {iface}.checker_mp vif;
    string                     trace_path;
    int                        fail_count;
    int                        vector_idx;

    function new(virtual {iface}.checker_mp vif, string trace_path);
        this.vif        = vif;
        this.trace_path = trace_path;
        this.fail_count = 0;
        this.vector_idx = 0;
    endfunction

    // ------------------------------------------------------------
    // Virtual per-step hooks. Defaults are no-ops (or, for
    // ``on_invariant_fail``, emit ``$error`` with the constructed
    // chart-vocab message). Override in a subclass to inject custom
    // pre/post instrumentation, transition logging, or alternative
    // failure routing.
    // ------------------------------------------------------------

    virtual function bit pre_step(int step_idx);
        // Default: proceed with this step. Override to skip a step
        // (return 0) or to instrument pre-parse state.
        return 1'b1;
    endfunction

    virtual function void on_state_transition(
        int prev_state,
        int next_state,
        int trigger_event
    );
        // Default no-op — override to log state transitions.
    endfunction

    virtual function void on_invariant_fail(
        int    invariant_id,
        string message
    );
        // Default: emit the chart-vocabulary failure message via
        // ``$error`` (the chart-vocab content is the same as today's
        // wave-3 ``$display`` text; severity escalates per the
        // layered-hierarchy default).
        $error("%s", message);
    endfunction

    virtual function void post_step(int step_idx);
        // Default no-op — override to instrument post-compare state.
    endfunction

    // ------------------------------------------------------------
    // Run-skeleton — owned by the base class. Per SOS-08-E §6.2:
    //   1. Open trace file.
    //   2. For each line: pre_step -> parse + state-resolution ->
    //      on_state_transition -> wait cycles -> compare ->
    //      on_invariant_fail (on mismatch) -> post_step.
    //
    // The chart-vocabulary failure-message format strings are
    // constructed inline below so the byte-identity regression
    // guard holds (``test_chart_vocab_message_byte_identical_to_
    // wave3_baseline``).
    // ------------------------------------------------------------
    task run();
        int    fh;
        string line;
        int    rc;
        int    expected_state;
        string expected_state_str;
        int    expected_state_resolved;
        int    cycles_wait;
        int    parsed_int;
        int    parsed_str;
        int    bit_idx;
        bit    do_step;
        string fail_msg;{nested_decls}

        fh = $fopen(trace_path, "r");
        if (fh == 0) begin
            $display("[FATAL] {cls_base}: cannot open trace `%s`",
                     trace_path);
            $finish(2);
        end

        // Wait for reset deassertion (driver handles reset; checker
        // starts comparing once clk_en is high).
        @(posedge vif.clk_en);
        @(posedge vif.clk);

        while (!$feof(fh)) begin
            rc = $fgets(line, fh);
            if (rc == 0) break;

            do_step = pre_step(vector_idx);
            if (!do_step) continue;

            expected_state          = -1;
            expected_state_str      = "";
            expected_state_resolved = -1;
            cycles_wait             = 1;
            parsed_int = sos_jsonl_parse_int(
                line, "expected_state", expected_state
            );
            parsed_str = sos_jsonl_parse_string(
                line, "expected_state_str", expected_state_str
            );
            parsed_int = sos_jsonl_parse_int(line, "cycles", cycles_wait);
            if (cycles_wait <= 0) cycles_wait = 1;{nested_parse}

            // Wave-3-future: string field takes precedence when present.
            // Resolution path: symbol table -> bit position -> one-hot
            // value compared against current_state.
            if (parsed_str) begin
                bit_idx = {symbol_fn}(expected_state_str);
                if (bit_idx < 0) begin
                    fail_count = fail_count + 1;
                    // INV-S-HDL-E-4 chart-vocab message — byte-
                    // identical to wave-3 monolithic emit.
                    fail_msg = $sformatf(
                        "[FAIL] vector V%0d: chart `{chart_name}` trace named expected_state_str=\\"%s\\" which is not a known chart-state of `{chart_name}`. INV-S-HDL-E-4 vocabulary violation.",
                        vector_idx + 1, expected_state_str
                    );
                    on_invariant_fail(1, fail_msg);
                end else begin
                    expected_state_resolved = 1 << bit_idx;
                end
            end else if (parsed_int) begin
                expected_state_resolved = expected_state;
            end

            // Wait the prescribed cycles before sampling.
            repeat (cycles_wait) @(posedge vif.clk);

            vector_idx = vector_idx + 1;
            on_state_transition(-1, expected_state_resolved, -1);

            if (expected_state_resolved >= 0) begin
                if (vif.current_state != expected_state_resolved[vif.current_state'left:0]) begin
                    fail_count = fail_count + 1;
                    // INV-S-HDL-E-4: chart-vocabulary failure message.
                    // When the trace named the state by string (the
                    // wave-3-future shape), surface that string in the
                    // failure message verbatim.
                    if (parsed_str) begin
                        fail_msg = $sformatf(
                            "[FAIL] vector V%0d: chart `{chart_name}` expected state=\\"%s\\" (one-hot=0b%0b) at cycle %0t; observed current_state=0b%0b.",
                            vector_idx, expected_state_str,
                            expected_state_resolved, $time,
                            vif.current_state
                        );
                    end else begin
                        fail_msg = $sformatf(
                            "[FAIL] vector V%0d: chart `{chart_name}` produced expected_state=%0d at cycle %0t; observed current_state=%0b.",
                            vector_idx, expected_state, $time,
                            vif.current_state
                        );
                    end
                    on_invariant_fail(2, fail_msg);
                end
            end

            post_step(vector_idx);
        end

        $fclose(fh);
    endtask

    function int get_fail_count();
        return fail_count;
    endfunction

endclass

`endif // SOS_{base.upper()}_CHECKER_BASE_SVH
"""


def _emit_checker_class(
    chart_name: str,
    nested_params: list[tuple[str, str, str]] | None = None,
    path_params: list[tuple[tuple[str, ...], str]] | None = None,
) -> str:
    """``sos_checker_<chart>.sv`` — response checker DEFAULT class.

    Wave-3-future (2026-05-24 §15) layered class hierarchy: this
    class extends ``sos_<chart>_checker_base`` (in the ``_base.svh``
    companion file) and overrides the per-step hooks with the
    wave-3-default bodies. Users who want a different checker shape
    extend ``_base`` themselves; the walker keeps this default
    byte-identical to wave-3 chart-vocab.

    The ``run()`` skeleton lives in ``_base.svh``. ``nested_params``
    and ``path_params`` are forwarded to the base emitter (they carry
    the wave-3-future-remaining nested-payload + wave-3-future-
    remaining-path deep-nested-payload locals and parse calls). When
    both lists are empty the base emit is byte-identical to the
    wave-3-future baseline.
    """
    cls = checker_class_name(chart_name)
    base = _normalise_chart_name(chart_name)
    cls_base = f"sos_{base}_checker_base"
    base_svh = f"sos_{base}_checker_base.svh"
    iface = virtual_if_name(chart_name)
    del nested_params
    del path_params
    return _HEADER_PREFIX + f"""//
// Response checker DEFAULT class for the {chart_name} chart testbench.
//
// Wave-3-future (2026-05-24 §15) layered class hierarchy: extends
// ``{cls_base}`` (declared in ``{base_svh}``) and overrides the
// per-step hooks with the wave-3 default bodies. The base class
// owns the run-skeleton, parse/resolve logic, and chart-vocabulary
// failure-message construction.
//
// User-side overrides SHOULD extend the base class rather than
// copy-paste this class — the walker keeps emitting ``_default``
// byte-identical to wave-3 chart-vocab for the [FAIL] log lines.
//
// Per SOS-08-E §5.5 + INV-S-HDL-E-4 every failure renders in chart
// vocabulary. Per INV-S-HDL-E-3 the checker does NOT inline any
// ``assert property``; property checking is in the SOS-08-D-emitted
// SVA bind file.

`include "{base_svh}"

class {cls} extends {cls_base};

    function new(virtual {iface}.checker_mp vif, string trace_path);
        super.new(vif, trace_path);
    endfunction

    // Wave-3-default ``pre_step`` — proceed with every step (no
    // filtering by default). Subclasses MAY override to skip steps.
    virtual function bit pre_step(int step_idx);
        return super.pre_step(step_idx);
    endfunction

    // Wave-3-default ``on_state_transition`` — no logging. Subclasses
    // MAY override to instrument transitions.
    virtual function void on_state_transition(
        int prev_state,
        int next_state,
        int trigger_event
    );
        super.on_state_transition(prev_state, next_state, trigger_event);
    endfunction

    // Wave-3-default ``on_invariant_fail`` — delegate to the base,
    // which emits ``$error(message)`` with the chart-vocabulary
    // message constructed in the base ``run()``. User overrides
    // SHOULD perform any custom logging FIRST, then call
    // ``super.on_invariant_fail(invariant_id, message)`` to preserve
    // the chart-vocab failure emission.
    virtual function void on_invariant_fail(
        int    invariant_id,
        string message
    );
        super.on_invariant_fail(invariant_id, message);
    endfunction

    // Wave-3-default ``post_step`` — no-op. Subclasses MAY override
    // to instrument post-compare state.
    virtual function void post_step(int step_idx);
        super.post_step(step_idx);
    endfunction

endclass
"""


def _emit_top_module(chart_name: str, n_states: int) -> str:
    """``tb_<chart>.sv`` — top-level testbench module.

    Instantiates the DUT (``<chart>_fsm``), the virtual interface, the
    driver, the checker, drives clock, forks driver + checker, and
    emits the final [PASS]/[FAIL] summary line per §6.3.
    """
    top = tb_module_name(chart_name)
    dut = dut_module_name(chart_name)
    drv = driver_class_name(chart_name)
    chk = checker_class_name(chart_name)
    iface = virtual_if_name(chart_name)
    base = _normalise_chart_name(chart_name)
    return _HEADER_PREFIX + f"""//
// Top-level testbench module for the {chart_name} chart.
//
// Per SOS-08-E §6.3:
//   1. Instantiates the DUT (``{dut}``).
//   2. Instantiates the virtual interface (``{iface}``).
//   3. Drives clock and reset (reset is driver-owned per the modport).
//   4. Instantiates driver + checker classes.
//   5. Fork-join runs them concurrently.
//   6. On driver completion + settle: emits ``[PASS]`` or ``[FAIL]``
//      and calls ``$finish``.
//
// The SVA bind file (``{base}_fsm_bind.sv``) is `include-d so its
// ``bind`` directive attaches the assertion module to the DUT instance.

`timescale 1ns/1ps

`include "dut_if_{base}.sv"
`include "sos_driver_{base}.sv"
`include "sos_checker_{base}.sv"

module {top};

    localparam int N_STATES   = {max(n_states, 1)};
    localparam int CLK_PERIOD = 10;  // 100 MHz wave-1 default.

    logic clk;
    initial clk = 1'b0;
    always #(CLK_PERIOD/2) clk = ~clk;

    {iface} #(.N_STATES(N_STATES), .EVENT_W(8)) vif (.clk(clk));

    // Reset comes from the driver modport; here we just expose the
    // chart-FSM observables for the checker.
    logic                rst_q;
    logic                clk_en_q;
    logic [7:0]          event_in_q;
    logic [N_STATES-1:0] current_state_q;

    always_comb begin
        rst_q      = vif.rst;
        clk_en_q   = vif.clk_en;
        event_in_q = vif.event_in;
        vif.current_state = current_state_q;
    end

    {dut} #(.N_STATES(N_STATES)) dut_i (
        .clk           (clk),
        .rst           (rst_q),
        .clk_en        (clk_en_q),
        .event_in      (event_in_q),
        .current_state (current_state_q)
    );

    {drv} driver;
    {chk} checker;

    initial begin
        string trace_path;
        trace_path = "vectors/{base}.jsonl";

        // SOS-08-E §5.4 + §6.1: driver consumes the JSONL trace.
        driver  = new(vif.driver_mp,  trace_path);
        checker = new(vif.checker_mp, trace_path);

        fork
            driver.run();
            checker.run();
        join

        // Summary — chart-vocabulary per INV-S-HDL-E-4.
        if (checker.get_fail_count() == 0) begin
            $display("[PASS] chart `{chart_name}` testbench: all vectors green.");
            $finish(0);
        end else begin
            $display("[FAIL count=%0d] chart `{chart_name}` testbench.",
                     checker.get_fail_count());
            $finish(1);
        end
    end

endmodule
"""


def _emit_verilator_makefile(chart_name: str) -> str:
    """``run_verilator.mk`` — Verilator build wrapper.

    Per §6.4 + INV-S-HDL-E-5 + PCDN-SOS-08-E-005. Wave-1 ships this
    wrapper as the open-source-runnable verification target; the
    commercial wrappers (Questa, VCS, Xcelium, Riviera) are wave-2
    enrichment scope.
    """
    base = _normalise_chart_name(chart_name)
    top = tb_module_name(chart_name)
    return f"""# SPDX-License-Identifier: MIT
# SOS-08-E wave-1 emitted artifact — DO NOT EDIT BY HAND.
#
# Verilator build wrapper for the {chart_name} chart testbench.
#
# Per SOS-08-E §5.3 + §6.4 + INV-S-HDL-E-5 + INV-S-HDL-E-6:
#   * Verilator is the open-source-runnable target.
#   * --assert enables the SVA subset Verilator supports.
#   * Unsupported SVA constructs (eventually, broad ##[a:b]) emit a
#     deferred-failure stub per INV-S-HDL-E-6; commercial simulators
#     run the full property set.

TOP := {top}

# Source files in dependency order: vif -> classes -> top + bind.
SOURCES := \\
    dut_if_{base}.sv \\
    sos_driver_{base}.sv \\
    sos_checker_{base}.sv \\
    {base}_fsm_sva.sv \\
    {base}_fsm_bind.sv \\
    tb_{base}.sv

# DUT module — chart-emitted FSM. The chart-FSM module is generated by
# the SOS-08-C walker (transliterate_hdl_sv.py) and lands at the
# project's chart-FSM emit path; this Makefile assumes the file is
# made available alongside the testbench at run time.
DUT_SOURCE ?= {base}_fsm.sv

VERILATOR ?= verilator
VFLAGS    := --binary --assert --timing -Wall -Wno-fatal \\
             --top-module $(TOP)

.PHONY: all run clean

all: run

run:
\t$(VERILATOR) $(VFLAGS) $(DUT_SOURCE) $(SOURCES)
\t./obj_dir/V$(TOP)

clean:
\trm -rf obj_dir
"""


def _emit_questa_do(chart_name: str) -> str:
    """``run.do`` — Questa-specific build wrapper.

    Per PCDN-SOS-08-E-005 (resolved 2026-05-23) separate wrappers per
    simulator. Wave-2 split this from the shared Questa/Riviera form
    (wave-1) — Riviera now has its own ``run_riviera.tcl`` wrapper
    with Riviera-specific `asim` / `arun` idioms.
    """
    base = _normalise_chart_name(chart_name)
    top = tb_module_name(chart_name)
    return f"""# SOS-08-E wave-2 emitted artifact — DO NOT EDIT BY HAND.
#
# Questa build wrapper for the {chart_name} chart testbench.
#
# Per SOS-08-E §5.3 + §6.4 + PCDN-SOS-08-E-005 separate wrappers per
# simulator (wave-2 split this from the shared Questa/Riviera form).

# Usage:
#   vsim -c -do run.do                 # batch mode
#   vsim    -do "run.do; run -all"     # GUI mode

vlib work
vmap work work

vlog -sv \\
    dut_if_{base}.sv \\
    sos_driver_{base}.sv \\
    sos_checker_{base}.sv \\
    {base}_fsm_sva.sv \\
    {base}_fsm_bind.sv \\
    tb_{base}.sv \\
    {base}_fsm.sv

vsim -c -voptargs="+acc" -assertdebug work.{top}
run -all
quit -code 0
"""


def _emit_vcs_makefile(chart_name: str) -> str:
    """``Makefile.sv`` — Synopsys VCS build wrapper.

    Per PCDN-SOS-08-E-005 separate wrappers per simulator. VCS uses
    `vcs` (compile) + `./simv` (run) with `+define`-style command-line
    flags rather than do-file conventions. The `-sverilog -assert
    enable_diag` flag-set is the canonical SVA-aware VCS invocation.
    """
    base = _normalise_chart_name(chart_name)
    top = tb_module_name(chart_name)
    return f"""# SOS-08-E wave-2 emitted artifact — DO NOT EDIT BY HAND.
#
# Synopsys VCS build wrapper for the {chart_name} chart testbench.
#
# Per SOS-08-E §5.3 + §6.4 + PCDN-SOS-08-E-005 separate wrappers per
# simulator.
#
# Usage:
#   make -f Makefile.sv          # compile + run
#   make -f Makefile.sv compile  # compile only
#   make -f Makefile.sv clean

TOP := {top}

SOURCES := \\
    dut_if_{base}.sv \\
    sos_driver_{base}.sv \\
    sos_checker_{base}.sv \\
    {base}_fsm_sva.sv \\
    {base}_fsm_bind.sv \\
    tb_{base}.sv \\
    {base}_fsm.sv

VCS       ?= vcs
VCS_FLAGS := -sverilog \\
             -assert enable_diag \\
             -timescale=1ns/1ps \\
             -full64 \\
             -debug_access+all \\
             -kdb \\
             -top $(TOP)

.PHONY: all compile run clean

all: run

compile: simv

simv: $(SOURCES)
\t$(VCS) $(VCS_FLAGS) $(SOURCES) -o simv

run: simv
\t./simv -ucli -do "run; quit"

clean:
\trm -rf simv simv.daidir csrc ucli.key DVEfiles inter.vpd
"""


def _emit_xcelium_argfile(chart_name: str) -> str:
    """``run_xrun.sh`` — Cadence Xcelium build wrapper.

    Per PCDN-SOS-08-E-005 separate wrappers per simulator. Xcelium's
    `xrun` accepts SystemVerilog sources directly on the command line
    along with `-sv -assert` flags; the wrapper is a shell script that
    invokes `xrun` with a deterministic flag order.
    """
    base = _normalise_chart_name(chart_name)
    top = tb_module_name(chart_name)
    return f"""#!/usr/bin/env bash
# SOS-08-E wave-2 emitted artifact — DO NOT EDIT BY HAND.
#
# Cadence Xcelium build wrapper for the {chart_name} chart testbench.
#
# Per SOS-08-E §5.3 + §6.4 + PCDN-SOS-08-E-005 separate wrappers per
# simulator.
#
# Usage:
#   ./run_xrun.sh                # compile + run with default flags
#   ./run_xrun.sh -gui           # open SimVision after elaboration
#
# Honors XRUN env var override for custom Xcelium installs.

set -euo pipefail

XRUN=${{XRUN:-xrun}}
TOP={top}

SOURCES=(
    dut_if_{base}.sv
    sos_driver_{base}.sv
    sos_checker_{base}.sv
    {base}_fsm_sva.sv
    {base}_fsm_bind.sv
    tb_{base}.sv
    {base}_fsm.sv
)

# Common Xcelium SVA-aware flag set.
XRUN_FLAGS=(
    -sv
    -access +rwc
    -assert
    -assertinitvar
    -timescale 1ns/1ps
    -top "$TOP"
)

if [[ "${{1:-}}" == "-gui" ]]; then
    XRUN_FLAGS+=(-gui)
    shift
fi

"$XRUN" "${{XRUN_FLAGS[@]}}" "${{SOURCES[@]}}" "$@"
"""


def _emit_riviera_tcl(chart_name: str) -> str:
    """``run_riviera.tcl`` — Aldec Riviera-PRO build wrapper.

    Per PCDN-SOS-08-E-005 separate wrappers per simulator. Riviera's
    Tcl uses `alog` (compile) + `asim` (elaborate + run) rather than
    Questa's `vlog`/`vsim`. The flag set diverges enough from Questa's
    that wave-2 splits them into separate wrapper files (wave-1's
    shared `.do` covered both at LCD-level only).
    """
    base = _normalise_chart_name(chart_name)
    top = tb_module_name(chart_name)
    return f"""# SOS-08-E wave-2 emitted artifact — DO NOT EDIT BY HAND.
#
# Aldec Riviera-PRO build wrapper for the {chart_name} chart testbench.
#
# Per SOS-08-E §5.3 + §6.4 + PCDN-SOS-08-E-005 separate wrappers per
# simulator (wave-2 split this from the shared Questa/Riviera `.do`).
#
# Usage:
#   vsim -c -do run_riviera.tcl         # batch mode (Riviera-PRO ships vsim as a wrapper)
#   alib + amap + alog + asim invocation below for the full Riviera flow

alib work
amap work work

alog -sv2k17 \\
    dut_if_{base}.sv \\
    sos_driver_{base}.sv \\
    sos_checker_{base}.sv \\
    {base}_fsm_sva.sv \\
    {base}_fsm_bind.sv \\
    tb_{base}.sv \\
    {base}_fsm.sv

asim -t 1ps +access+rw +sv_seed=1 work.{top}
run -all
exit
"""


# ---------------------------------------------------------------------------
# Invariant audit
# ---------------------------------------------------------------------------


_INV_E1_PATTERNS: tuple[tuple[str, str], ...] = (
    # INV-S-HDL-E-1: no constrained-random.
    (r"\brandomize\s*\(", "randomize() call"),
    (r"\bconstraint\s+\w+\s*\{", "constraint block"),
    (r"^\s*rand\s+\w", "`rand` property declaration"),
    (r"^\s*randc\s+\w", "`randc` property declaration"),
)

_INV_E2_PATTERNS: tuple[tuple[str, str], ...] = (
    # INV-S-HDL-E-2: no UVM imports / macros.
    (r"\bimport\s+uvm_pkg\s*::", "import uvm_pkg"),
    (r"`uvm_\w+", "`uvm_* macro"),
)

_INV_E3_PATTERNS: tuple[tuple[str, str], ...] = (
    # INV-S-HDL-E-3: no inline `assert property` in non-bind files.
    (r"\bassert\s+property\b", "inline assert property"),
)


# ---------------------------------------------------------------------------
# Parallel-chart emit (wave-3, 2026-05-24 §15)
# ---------------------------------------------------------------------------


def _emit_virtual_interface_parallel(
    chart_name: str,
    regions: list[tuple[str, str | None, list[str]]],
) -> str:
    """``dut_if_<chart>.sv`` — virtual interface for a PARALLEL chart.

    Per SOS-08-C §6.10 chart-top wrapper convention, parallel charts
    expose one ``current_state_<region>`` output port per region; the
    SV testbench's virtual interface mirrors that surface so the
    checker can read each region's state independently. Per
    INV-S-HDL-E-3 the interface carries observables only (no
    assertion-driven signals).

    Wave-3 (2026-05-24) lifts the wave-1 single-region restriction.
    Mirrors the SOS-08-D wave-2c parallel-chart cocotb walker's
    per-region observable shape so both verification paths read the
    SAME chart-top wrapper ports.
    """
    iface = virtual_if_name(chart_name)
    guard = f"DUT_IF_{chart_name.upper().replace('-', '_')}_SV"
    region_names = [r[0] for r in regions]

    region_port_decls = "\n".join(
        f"    logic [N_STATES_{_sanitize_sv_identifier(rn).upper()}-1:0] "
        f"current_state_{_sanitize_sv_identifier(rn)};"
        for rn in region_names
    )
    driver_mp_observable_inputs = "\n".join(
        f"        input  current_state_{_sanitize_sv_identifier(rn)},"
        for rn in region_names
    )
    checker_mp_observable_inputs = "\n".join(
        f"        input  current_state_{_sanitize_sv_identifier(rn)},"
        for rn in region_names
    )
    n_states_params = ",\n".join(
        f"    parameter int N_STATES_{_sanitize_sv_identifier(rn).upper()} = 1"
        for rn in region_names
    )

    return _HEADER_PREFIX + f"""//
// Virtual interface for the {chart_name} chart (parallel-chart wave-3).
//
// The driver drives ``clk_en``, ``rst``, and ``event_in``; the checker
// observes each region's ``current_state_<region>`` output exposed by
// the chart-top wrapper (per SOS-08-C §6.10). All routing goes
// through this interface so driver/checker classes do not couple to
// the DUT module directly.

`ifndef {guard}
`define {guard}

interface {iface} #(
    parameter int EVENT_W = 8,
{n_states_params}
) (
    input  logic clk
);

    // Drives (set by driver).
    logic                rst;
    logic                clk_en;
    logic [EVENT_W-1:0]  event_in;

    // Observables (read by checker) — one per region per
    // SOS-08-C §6.10 chart-top wrapper emission.
{region_port_decls}

    modport driver_mp (
        output rst,
        output clk_en,
        output event_in,
{driver_mp_observable_inputs}
        input  clk
    );

    modport checker_mp (
        input  rst,
        input  clk_en,
        input  event_in,
{checker_mp_observable_inputs}
        input  clk
    );

endinterface

`endif // {guard}
"""


def _emit_checker_class_base_parallel(
    chart_name: str,
    regions: list[tuple[str, str | None, list[str]]],
    nested_params: list[tuple[str, str, str]] | None = None,
    path_params: list[tuple[tuple[str, ...], str]] | None = None,
) -> str:
    """``sos_<chart>_checker_base.svh`` — parallel-chart BASE class.

    Wave-3-future (2026-05-24 §15) layered class hierarchy: parallel
    mirror of ``_emit_checker_class_base``. Owns the per-line replay
    loop + per-region parse/resolve/compare logic + chart-vocabulary
    failure-message construction. Declares the four virtual hooks
    (``pre_step`` / ``on_state_transition`` / ``on_invariant_fail`` /
    ``post_step``); the wave-3-default checker overrides them.

    Per-region chart-vocab format strings are constructed inline so
    the byte-identity regression guard holds across the wave-3 →
    layered refactor.
    """
    base = _normalise_chart_name(chart_name)
    cls_base = f"sos_{base}_checker_base"
    iface = virtual_if_name(chart_name)
    symbol_fn = f"sos_{base}_state_id_of"
    region_names = [r[0] for r in regions]
    nested_decls, nested_parse = _render_nested_param_blocks(
        nested_params or [],
        decl_indent="        ",
        parse_indent="            ",
        path_params=path_params or [],
    )

    region_reads = []
    region_parse = []
    region_decls_lines = []
    for rn in region_names:
        ident = _sanitize_sv_identifier(rn)
        region_decls_lines.append(
            f"        int    expected_state_{ident};"
        )
        region_decls_lines.append(
            f"        string expected_state_{ident}_str;"
        )
        region_decls_lines.append(
            f"        int    expected_state_{ident}_resolved;"
        )
        region_decls_lines.append(
            f"        int    parsed_str_{ident};"
        )
        region_decls_lines.append(
            f"        int    bit_idx_{ident};"
        )
        # Per-region parse block: integer + string + resolution. Chart-
        # vocab failure messages are constructed in $sformatf and
        # routed through the on_invariant_fail hook so user-side
        # subclasses can intercept; the format strings are byte-
        # identical to the wave-3 monolithic emit.
        region_parse.append(
            f"            expected_state_{ident}          = -1;\n"
            f"            expected_state_{ident}_str      = \"\";\n"
            f"            expected_state_{ident}_resolved = -1;\n"
            f"            parsed = sos_jsonl_parse_int(\n"
            f"                line, \"expected_state_{ident}\", "
            f"expected_state_{ident}\n"
            f"            );\n"
            f"            parsed_str_{ident} = sos_jsonl_parse_string(\n"
            f"                line, \"expected_state_{ident}_str\", "
            f"expected_state_{ident}_str\n"
            f"            );\n"
            f"            if (parsed_str_{ident}) begin\n"
            f"                bit_idx_{ident} = {symbol_fn}("
            f"expected_state_{ident}_str);\n"
            f"                if (bit_idx_{ident} < 0) begin\n"
            f"                    fail_count = fail_count + 1;\n"
            f"                    fail_msg = $sformatf(\n"
            f"                        \"[FAIL] vector V%0d region "
            f"`{rn}` chart `{chart_name}`: expected_state_{ident}_str=\\\"%s\\\" is not a known chart-state.\",\n"
            f"                        vector_idx + 1, "
            f"expected_state_{ident}_str\n"
            f"                    );\n"
            f"                    on_invariant_fail(1, fail_msg);\n"
            f"                end else begin\n"
            f"                    expected_state_{ident}_resolved = "
            f"1 << bit_idx_{ident};\n"
            f"                end\n"
            f"            end else if (expected_state_{ident} >= 0) begin\n"
            f"                expected_state_{ident}_resolved = "
            f"expected_state_{ident};\n"
            f"            end"
        )
        region_reads.append(
            f"            if (expected_state_{ident}_resolved >= 0) begin\n"
            f"                if (vif.current_state_{ident} != "
            f"expected_state_{ident}_resolved[vif.current_state_{ident}'left:0]) "
            f"begin\n"
            f"                    fail_count = fail_count + 1;\n"
            f"                    // INV-S-HDL-E-4: chart-vocabulary "
            f"failure message; region named.\n"
            f"                    if (parsed_str_{ident}) begin\n"
            f"                        fail_msg = $sformatf(\n"
            f"                            \"[FAIL] vector V%0d region "
            f"`{rn}` chart `{chart_name}`: expected state=\\\"%s\\\" "
            f"(one-hot=0b%0b) at cycle %0t; observed current_state=0b%0b.\",\n"
            f"                            vector_idx, "
            f"expected_state_{ident}_str, "
            f"expected_state_{ident}_resolved, $time, "
            f"vif.current_state_{ident}\n"
            f"                        );\n"
            f"                    end else begin\n"
            f"                        fail_msg = $sformatf(\n"
            f"                            \"[FAIL] vector V%0d region "
            f"`{rn}` chart `{chart_name}`: expected_state=%0d at cycle "
            f"%0t; observed current_state=%0b.\",\n"
            f"                            vector_idx, "
            f"expected_state_{ident}, $time, "
            f"vif.current_state_{ident}\n"
            f"                        );\n"
            f"                    end\n"
            f"                    on_invariant_fail(2, fail_msg);\n"
            f"                end\n"
            f"            end"
        )

    region_decls = "\n".join(region_decls_lines)
    region_parse_block = "\n".join(region_parse)
    region_compare_block = "\n".join(region_reads)

    return _HEADER_PREFIX + f"""//
// Response checker BASE class for chart `{chart_name}` (parallel).
//
// Wave-3-future (2026-05-24 §15) layered class hierarchy: parallel
// mirror of ``sos_<chart>_checker_base``. Owns the per-line replay
// loop + per-region parse/resolve/compare logic + chart-vocabulary
// failure-message construction. The wave-3-default parallel checker
// (``{checker_class_name(chart_name)}``) extends this class and
// overrides the per-step hooks.
//
// Per SOS-08-E wave-3 + INV-S-HDL-E-4 every failure cites the
// failing region in chart vocabulary. Per INV-S-HDL-E-3 the checker
// does NOT inline any ``assert property``.

`ifndef SOS_{base.upper()}_CHECKER_BASE_SVH
`define SOS_{base.upper()}_CHECKER_BASE_SVH

`include "sos_jsonl_parser_pkg.svh"
`include "sos_{base}_state_symbols.svh"

virtual class {cls_base};

    virtual {iface}.checker_mp vif;
    string                     trace_path;
    int                        fail_count;
    int                        vector_idx;

    function new(virtual {iface}.checker_mp vif, string trace_path);
        this.vif        = vif;
        this.trace_path = trace_path;
        this.fail_count = 0;
        this.vector_idx = 0;
    endfunction

    // ------------------------------------------------------------
    // Virtual per-step hooks. Defaults mirror the single-region
    // base class: no-op pre/post + transition, ``$error(message)``
    // on_invariant_fail. Override to customise.
    // ------------------------------------------------------------

    virtual function bit pre_step(int step_idx);
        return 1'b1;
    endfunction

    virtual function void on_state_transition(
        int prev_state,
        int next_state,
        int trigger_event
    );
    endfunction

    virtual function void on_invariant_fail(
        int    invariant_id,
        string message
    );
        $error("%s", message);
    endfunction

    virtual function void post_step(int step_idx);
    endfunction

    task run();
        int    fh;
        string line;
        int    rc;
{region_decls}
        int    cycles_wait;
        int    parsed;
        bit    do_step;
        string fail_msg;{nested_decls}

        fh = $fopen(trace_path, "r");
        if (fh == 0) begin
            $display("[FATAL] {cls_base}: cannot open trace `%s`",
                     trace_path);
            $finish(2);
        end

        // Wait for reset deassertion + first observable settle.
        @(posedge vif.clk_en);
        @(posedge vif.clk);

        while (!$feof(fh)) begin
            rc = $fgets(line, fh);
            if (rc == 0) break;

            do_step = pre_step(vector_idx);
            if (!do_step) continue;

{region_parse_block}
            cycles_wait = 1;
            parsed = sos_jsonl_parse_int(line, "cycles", cycles_wait);
            if (cycles_wait <= 0) cycles_wait = 1;{nested_parse}

            repeat (cycles_wait) @(posedge vif.clk);

            vector_idx = vector_idx + 1;
            on_state_transition(-1, -1, -1);

{region_compare_block}

            post_step(vector_idx);
        end

        $fclose(fh);
    endtask

    function int get_fail_count();
        return fail_count;
    endfunction

endclass

`endif // SOS_{base.upper()}_CHECKER_BASE_SVH
"""


def _emit_checker_class_parallel(
    chart_name: str,
    regions: list[tuple[str, str | None, list[str]]],
    nested_params: list[tuple[str, str, str]] | None = None,
    path_params: list[tuple[tuple[str, ...], str]] | None = None,
) -> str:
    """``sos_checker_<chart>.sv`` — parallel-chart DEFAULT class.

    Wave-3-future (2026-05-24 §15) layered class hierarchy: extends
    ``sos_<chart>_checker_base`` (parallel form, in the ``_base.svh``
    companion file) and overrides the per-step hooks with the
    wave-3-default bodies. The base class owns the run-skeleton +
    per-region parse/resolve/compare + chart-vocabulary failure-
    message construction.

    Per INV-S-HDL-E-4 every failure renders in chart vocabulary +
    names the failing region. Per INV-S-HDL-E-3 no inline
    ``assert property``.

    ``regions``, ``nested_params``, and ``path_params`` are consumed by
    the base emitter; this default class only wires the constructor +
    hook overrides.
    """
    cls = checker_class_name(chart_name)
    base = _normalise_chart_name(chart_name)
    cls_base = f"sos_{base}_checker_base"
    base_svh = f"sos_{base}_checker_base.svh"
    iface = virtual_if_name(chart_name)
    del regions
    del nested_params
    del path_params
    return _HEADER_PREFIX + f"""//
// Response checker DEFAULT class for chart `{chart_name}` (parallel).
//
// Wave-3-future (2026-05-24 §15) layered class hierarchy: extends
// ``{cls_base}`` (declared in ``{base_svh}``) and overrides the
// per-step hooks with the wave-3-default bodies. The base class
// owns the run-skeleton, per-region parse/resolve/compare, and
// chart-vocabulary failure-message construction.
//
// User-side overrides SHOULD extend the base class rather than
// copy-paste this class.

`include "{base_svh}"

class {cls} extends {cls_base};

    function new(virtual {iface}.checker_mp vif, string trace_path);
        super.new(vif, trace_path);
    endfunction

    virtual function bit pre_step(int step_idx);
        return super.pre_step(step_idx);
    endfunction

    virtual function void on_state_transition(
        int prev_state,
        int next_state,
        int trigger_event
    );
        super.on_state_transition(prev_state, next_state, trigger_event);
    endfunction

    virtual function void on_invariant_fail(
        int    invariant_id,
        string message
    );
        super.on_invariant_fail(invariant_id, message);
    endfunction

    virtual function void post_step(int step_idx);
        super.post_step(step_idx);
    endfunction

endclass
"""


def _emit_top_module_parallel(
    chart_name: str,
    regions: list[tuple[str, str | None, list[str]]],
) -> str:
    """``tb_<chart>.sv`` — top-level testbench for a PARALLEL chart.

    Instantiates the chart-top wrapper (``<chart>_fsm`` per SOS-08-C
    §6.10 — the same module name the SVA bind walker targets), wires
    each region's ``current_state_<region>`` observable output to the
    virtual interface, drives clock/reset, fork-joins the driver +
    checker, emits [PASS]/[FAIL] summary per §6.3 / INV-S-HDL-E-4.
    """
    top = tb_module_name(chart_name)
    dut = dut_module_name(chart_name)
    drv = driver_class_name(chart_name)
    chk = checker_class_name(chart_name)
    iface = virtual_if_name(chart_name)
    base = _normalise_chart_name(chart_name)

    n_states_per_region = "\n".join(
        f"    localparam int N_STATES_{_sanitize_sv_identifier(rn).upper()} "
        f"= {max(len(states), 1)};"
        for rn, _initial, states in regions
    )
    region_observable_decls = "\n".join(
        f"    logic [N_STATES_{_sanitize_sv_identifier(rn).upper()}-1:0] "
        f"current_state_{_sanitize_sv_identifier(rn)}_q;"
        for rn, _initial, _states in regions
    )
    region_observable_assigns = "\n".join(
        f"        vif.current_state_{_sanitize_sv_identifier(rn)} = "
        f"current_state_{_sanitize_sv_identifier(rn)}_q;"
        for rn, _initial, _states in regions
    )
    region_n_states_overrides = ",\n".join(
        f"        .N_STATES_{_sanitize_sv_identifier(rn).upper()}"
        f"(N_STATES_{_sanitize_sv_identifier(rn).upper()})"
        for rn, _initial, _states in regions
    )
    vif_n_states_overrides = ",\n".join(
        f"        .N_STATES_{_sanitize_sv_identifier(rn).upper()}"
        f"(N_STATES_{_sanitize_sv_identifier(rn).upper()})"
        for rn, _initial, _states in regions
    )
    dut_region_ports = ",\n".join(
        f"        .current_state_{_sanitize_sv_identifier(rn)}"
        f"(current_state_{_sanitize_sv_identifier(rn)}_q)"
        for rn, _initial, _states in regions
    )

    return _HEADER_PREFIX + f"""//
// Top-level testbench module for chart `{chart_name}` (parallel wave-3).
//
// Per SOS-08-E wave-3 (2026-05-24 §15):
//   1. Instantiates the chart-top wrapper (``{dut}`` per SOS-08-C §6.10).
//   2. Instantiates the virtual interface with per-region N_STATES
//      parameters.
//   3. Drives clock + reset (driver-owned per the modport).
//   4. Wires each region's ``current_state_<region>`` output to the
//      virtual interface.
//   5. Forks driver + checker; on completion emits [PASS] / [FAIL]
//      summary per INV-S-HDL-E-4.
//
// The SVA bind files (one per region per SOS-08-D wave-2b) are
// `include-d so their ``bind`` directives attach concurrently.

`timescale 1ns/1ps

`include "verilator_stubs.svh"
`include "dut_if_{base}.sv"
`include "sos_driver_{base}.sv"
`include "sos_checker_{base}.sv"

module {top};

{n_states_per_region}
    localparam int CLK_PERIOD = 10;  // 100 MHz wave-3 default.

    logic clk;
    initial clk = 1'b0;
    always #(CLK_PERIOD/2) clk = ~clk;

    {iface} #(
{vif_n_states_overrides}
    ) vif (.clk(clk));

    logic rst_q;
    logic clk_en_q;
    logic [7:0] event_in_q;
{region_observable_decls}

    always_comb begin
        rst_q      = vif.rst;
        clk_en_q   = vif.clk_en;
        event_in_q = vif.event_in;
{region_observable_assigns}
    end

    {dut} #(
{region_n_states_overrides}
    ) dut_i (
        .clk           (clk),
        .rst           (rst_q),
        .clk_en        (clk_en_q),
        .event_in      (event_in_q),
{dut_region_ports}
    );

    {drv} driver;
    {chk} checker;

    initial begin
        string trace_path;
        trace_path = "vectors/{base}.jsonl";

        driver  = new(vif.driver_mp,  trace_path);
        checker = new(vif.checker_mp, trace_path);

        fork
            driver.run();
            checker.run();
        join

        if (checker.get_fail_count() == 0) begin
            $display("[PASS] chart `{chart_name}` testbench: all vectors green.");
            $finish(0);
        end else begin
            $display("[FAIL count=%0d] chart `{chart_name}` testbench.",
                     checker.get_fail_count());
            $finish(1);
        end
    end

endmodule
"""


# ---------------------------------------------------------------------------
# Verilator deferred-failure stubs (INV-S-HDL-E-6 wave-3 ratification)
# ---------------------------------------------------------------------------


# Constructs the emit MUST treat as "outside Verilator's documented
# subset" per INV-S-HDL-E-6. Wave-1/wave-2 emit stayed within
# Verilator's subset; wave-3 publishes the catalog + the stub-policy
# header so future emit extensions surface unsupported-construct use
# explicitly. Entries are (regex, label, severity) — severity is
# "deferred-failure" for soft fallbacks and "audit-block" for things
# that MUST never reach the emit (constrained-random would be
# INV-S-HDL-E-1, not -E-6).
_VERILATOR_UNSUPPORTED_CONSTRUCTS: tuple[tuple[str, str], ...] = (
    # SV-2017 constructs Verilator's documented subset does not cover
    # (or covers behind experimental flags). Wave-3 keeps the list
    # tight; future emit-extensions may grow it. Per
    # SOS-08-E-CONCEPTS.md §15 wave-3, adding entries requires a §15
    # amendment so commercial-sim users notice the contract shift.
    #
    # Patterns are deliberately strict (often anchored on the SV
    # keyword as a STATEMENT-OPENER) so usage of the word in
    # identifiers or comments doesn't false-positive. The audit
    # already strips line comments before scanning; identifier-name
    # collision is the remaining concern.
    (r"\bcovergroup\b\s+\w+",      "covergroup (PCDN-E-003 deferred)"),
    (r"\bclocking\s+\w+",          "clocking block"),
    (r"\bjoin_any\b",              "join_any (Verilator: experimental)"),
    (r"\bjoin_none\b",             "join_none (Verilator: experimental)"),
    (r"\bwait\s+fork\b",           "wait fork"),
    (r"\brandcase\b",              "randcase"),
    (r"\brandsequence\b",          "randsequence"),
    # `checker` is an SV-2017 module-style construct; match only its
    # declaration form (`checker <name>;` or `checker <name>(...);`).
    # The word "checker" appearing as an identifier (e.g. our
    # `sos_checker_<chart>` class name or `checker` local variables)
    # MUST NOT trip the audit.
    (r"^\s*checker\s+\w+\s*[(;]",  "checker module"),
    # SV `property` declarations outside bind files; bind files are
    # exempted at the audit-pass entry point.
    (r"^\s*property\s+\w+\s*\(",   "(non-bind) property declaration"),
)


def _emit_verilator_stubs_svh(chart_name: str) -> str:
    """``verilator_stubs.svh`` — Verilator deferred-failure-stub policy
    header.

    Wave-3 (2026-05-24 §15) ratifies INV-S-HDL-E-6 (Verilator-subset
    compliance via deferred-failure stubs per PCDN-SOS-08-E-002
    resolution). The wave-1/2 emit stayed within Verilator's
    documented subset, so the policy header was deferred; wave-3 ships
    it now that the parallel-chart emit increases the surface area
    where SV-2017 constructs outside Verilator's subset could
    accidentally land.

    The header defines two macros:

    - ``SOS_VERILATOR_SKIP_BEGIN`` / ``SOS_VERILATOR_SKIP_END`` —
      wrap a block of code that is compiled on commercial simulators
      but replaced with a chart-vocabulary deferred-failure stub on
      Verilator (the stub emits an ``[INFO] verilator: deferred ...``
      message at simulator start so the chart author knows the gap
      is intentional + which feature is gated).
    - ``SOS_VERILATOR_DEFERRED(feature)`` — single-line stub form for
      a one-statement feature.

    Per INV-S-HDL-E-6 the emit pass scans every emitted file for
    constructs in ``_VERILATOR_UNSUPPORTED_CONSTRUCTS`` and reports
    them in the post-emit audit. Wave-1/wave-2 emit was empty under
    this audit; wave-3 includes the audit step but the emit set
    remains empty under it (the parallel-chart additions stay within
    the Verilator subset).
    """
    chart_id = _normalise_chart_name(chart_name)
    return _HEADER_PREFIX + f"""//
// Verilator deferred-failure-stub policy header (wave-3 ratification
// of INV-S-HDL-E-6 per PCDN-SOS-08-E-002).
//
// Wave-3 (2026-05-24) co-lands this file so the testbench emit set
// has a SINGLE source of truth for the Verilator-subset contract.
// All wave-1/wave-2 emitted files now `include this header so the
// macros below are available without per-file repetition.
//
// Macros:
//   `SOS_VERILATOR_SKIP_BEGIN  / `SOS_VERILATOR_SKIP_END  — wrap a
//     block of SV-2017 code that depends on a feature outside
//     Verilator's documented subset; commercial simulators run it,
//     Verilator stubs it out with a chart-vocabulary
//     [INFO] verilator: deferred ... message.
//   `SOS_VERILATOR_DEFERRED(<feature>)  — single-statement stub form.
//
// The wave-1/wave-2/wave-3 emit set stays within Verilator's subset;
// the macros are infrastructure for future emit extensions that may
// land features outside it (e.g. covergroup-based functional
// coverage per PCDN-SOS-08-E-003).

`ifndef SOS_VERILATOR_STUBS_{chart_id.upper()}_SVH
`define SOS_VERILATOR_STUBS_{chart_id.upper()}_SVH

`ifdef VERILATOR
    // Verilator path: emit the deferred-failure stub. Per
    // INV-S-HDL-E-6 the stub MUST surface in chart vocabulary
    // (INV-S-HDL-E-4 — failure messages name the chart) so a CI
    // failure reads as "feature X deferred for chart `{chart_name}` on
    // Verilator" instead of a silent skip.
    `define SOS_VERILATOR_SKIP_BEGIN \\
        initial begin \\
            $display("[INFO] verilator: deferred SV-2017 block for chart `{chart_name}` (skipped per INV-S-HDL-E-6)."); \\
        end \\
        `ifdef NEVER_DEFINED // begin Verilator-skipped block
    `define SOS_VERILATOR_SKIP_END \\
        `endif // end Verilator-skipped block
    `define SOS_VERILATOR_DEFERRED(feature) \\
        initial $display("[INFO] verilator: deferred ``feature`` for chart `{chart_name}` (INV-S-HDL-E-6).");
`else
    // Commercial simulators: pass through unchanged. The skip-block
    // macros expand to nothing; the deferred macro expands to nothing.
    `define SOS_VERILATOR_SKIP_BEGIN
    `define SOS_VERILATOR_SKIP_END
    `define SOS_VERILATOR_DEFERRED(feature)
`endif

`endif // SOS_VERILATOR_STUBS_{chart_id.upper()}_SVH
"""


def _audit_verilator_subset(filename: str, source: str) -> list[str]:
    """Wave-3 INV-S-HDL-E-6 audit: scan ``source`` for SV-2017
    constructs outside Verilator's documented subset.

    Bind files / Makefiles / Tcl wrappers are exempt — bind files use
    SVA properties by design (which the SVA bind walker emits inside
    `\\`bind`-anchored modules Verilator may handle differently), and
    the build wrappers are not SV. The audit applies to the testbench
    SV files (vif, driver, checker, top) and to the new Verilator
    stubs header itself (where the macros' commercial-path bodies
    obviously contain references to the gated features).

    Returns the list of human-readable violations (empty when clean).
    Pre-wave-3 emit is expected to be empty under this audit; wave-3
    adds the audit step so future emit extensions surface
    unsupported-construct use explicitly.

    Wave-3 surfaces the violations as WARNINGS during emit (the audit
    pass downstream raises only on INV-S-HDL-E-1/2/3 hard violations;
    INV-S-HDL-E-6 is a soft contract — the deferred-failure-stub
    macro is the mitigation, not the rejection).
    """
    # Files exempted from the wave-3 INV-S-HDL-E-6 audit:
    #   * SVA bind files (`assert property` belongs there)
    #   * The Verilator stubs header itself (it documents the
    #     macros — its content names the gated features by design)
    #   * Build wrappers (not SV)
    if filename.endswith(("_sva.sv", "_bind.sv", "verilator_stubs.svh")):
        return []
    if filename.endswith((".mk", ".do", ".sh", ".tcl")):
        return []
    scanned = re.sub(r"//.*$", "", source, flags=re.MULTILINE)
    violations: list[str] = []
    for pat, label in _VERILATOR_UNSUPPORTED_CONSTRUCTS:
        if re.search(pat, scanned, flags=re.MULTILINE):
            violations.append(
                f"INV-S-HDL-E-6 advisory: {label} — wrap with "
                f"`SOS_VERILATOR_SKIP_BEGIN/END or `SOS_VERILATOR_DEFERRED"
            )
    return violations


def _audit_emitted_file(filename: str, source: str) -> list[str]:
    """Scan ``source`` for INV-S-HDL-E-1/2/3 forbidden constructs.

    SVA bind files are exempt from INV-S-HDL-E-3 — properties live
    there by design. Driver/checker/top/vif/build-wrappers are not.
    Returns the list of human-readable violations (empty if clean).
    """
    is_bind_file = filename.endswith("_sva.sv") or filename.endswith("_bind.sv")
    is_makefile = filename.endswith(".mk") or filename.endswith(".do")
    violations: list[str] = []

    # Strip comments for pattern matching to avoid false positives on
    # spec-prose mentions like "// INV-S-HDL-E-1: no `randomize` ...".
    # Wave-1 strips ``//`` line comments and ``# ...`` Makefile comments;
    # ``/* */`` block comments are not used in emitted output.
    if is_makefile:
        scanned = re.sub(r"#.*$", "", source, flags=re.MULTILINE)
    else:
        scanned = re.sub(r"//.*$", "", source, flags=re.MULTILINE)

    for pat, label in _INV_E1_PATTERNS:
        if re.search(pat, scanned, flags=re.MULTILINE):
            violations.append(f"INV-S-HDL-E-1 violation: {label}")
    for pat, label in _INV_E2_PATTERNS:
        if re.search(pat, scanned, flags=re.MULTILINE):
            violations.append(f"INV-S-HDL-E-2 violation: {label}")
    if not is_bind_file:
        for pat, label in _INV_E3_PATTERNS:
            if re.search(pat, scanned, flags=re.MULTILINE):
                violations.append(f"INV-S-HDL-E-3 violation: {label}")
    return violations


def _audit_all(files: dict[str, str]) -> None:
    """Run the invariant audit across all emitted files; raise on any hit."""
    accumulated: list[str] = []
    for filename, source in files.items():
        hits = _audit_emitted_file(filename, source)
        if hits:
            accumulated.append(
                f"{filename}: " + "; ".join(hits)
            )
    if accumulated:
        raise InvariantAuditError(
            "SOS-08-E wave-1 invariant audit failed:\n  "
            + "\n  ".join(accumulated)
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render_target(chart_ir: Any, config: Any = None) -> dict[str, str]:
    """Emit the SOS-08-E wave-1 SV testbench artifact set for a chart.

    Wave-1 contract:
      * Single-region chart → eight files under ``tb/sv/<chart>/``:
          - ``tb_<chart>.sv``
          - ``sos_driver_<chart>.sv``
          - ``sos_checker_<chart>.sv``
          - ``dut_if_<chart>.sv``
          - ``<chart>_fsm_sva.sv`` (byte-identical to SOS-08-D emit)
          - ``<chart>_fsm_bind.sv`` (byte-identical to SOS-08-D emit)
          - ``run_verilator.mk``
          - ``run.do`` (Questa / Riviera reference)
      * Parallel charts raise ``UnsupportedChartError`` with a wave-2
        citation per §15.

    Args:
        chart_ir: raw scjson dict (``ChartAst.raw_scjson``).
        config: optional dict / dataclass. Wave-1 consumes:
            - ``chart_name`` (str): chart identifier; module-name base.
            - ``guard_depth_budget`` (int): forwarded to the SVA bind
              walker (PCDN-C-004 budget override).

    Returns:
        dict mapping output filename (relative path embedding the
        ``tb/sv/<chart>/`` prefix) to emitted file source.

    Raises:
        UnsupportedChartError when the chart names a feature outside
        wave-1 scope (parallel regions; non-dict chart_ir).
        InvariantAuditError when the emitted text violates
        INV-S-HDL-E-1..3 (signals an internal walker bug, not chart-
        author error).
    """
    if not isinstance(chart_ir, dict):
        raise UnsupportedChartError(
            "SOS-08-E wave-1 render_target expects the raw scjson dict, "
            f"not {type(chart_ir).__name__}. The main.py dispatcher "
            "needs to pass the parsed scjson AST "
            "(ChartAst.raw_scjson)."
        )

    if isinstance(config, dict):
        chart_name = config.get("chart_name") or "chart"
    else:
        chart_name = getattr(config, "chart_name", None) or "chart"

    base = _normalise_chart_name(chart_name)

    # Wave-3 (2026-05-24 §15): dispatch on parallel vs single-region.
    # Wave-1 rejected parallel charts; wave-3 lifts the rejection via
    # the per-region observable shape in the chart-top wrapper (per
    # SOS-08-C §6.10) mirrored at the SV testbench's virtual interface.
    regions = _collect_regions(chart_ir)

    # Wave-3-future (2026-05-24 §15): collect state IDs up-front for
    # both paths so the per-chart symbol-table emit has the chart's
    # state list available. For parallel charts we flatten across all
    # regions' states so the symbol table covers every name a
    # per-region `expected_state_<region>_str` field might reference.
    if regions:
        all_state_ids: list[str] = []
        seen: set[str] = set()
        for _region_name, _initial, region_state_ids in regions:
            for sid in region_state_ids:
                if sid not in seen:
                    all_state_ids.append(sid)
                    seen.add(sid)
    else:
        all_state_ids = _collect_state_ids(chart_ir)

    # Wave-3-future-remaining (2026-05-24 §15): collect one-level-deep
    # nested ``<param name="outer.inner"/>`` declarations across all
    # transitions. Wave-3-future-remaining-path (2026-05-24 §15) adds
    # ``_collect_path_params`` for depth-≥2 declarations, lowered to
    # ``sos_jsonl_parse_path_*`` calls in the checker emit. Both
    # collectors share ``_validate_path_segments`` for the build-time
    # chart-vocab gate (empty segments, non-identifier chars, leading/
    # trailing dots).
    nested_params = _collect_nested_params(chart_ir)
    path_params = _collect_path_params(chart_ir)

    if regions:
        # Parallel-chart emit (wave-3): per-region virtual interface +
        # per-region checker + chart-top-wrapper DUT instantiation.
        # Wave-3-future (2026-05-24 §15) layered class hierarchy:
        # ``_checker_base.svh`` + ``_driver_base.svh`` carry the
        # run-skeleton + virtual hooks; the ``_default`` SV files
        # extend them. File counts: parallel emit grows from 16 to 18.
        files: dict[str, str] = {
            f"tb/sv/{base}/dut_if_{base}.sv":
                _emit_virtual_interface_parallel(chart_name, regions),
            f"tb/sv/{base}/sos_{base}_driver_base.svh":
                _emit_driver_class_base(chart_name),
            f"tb/sv/{base}/sos_driver_{base}.sv":
                _emit_driver_class(chart_name),
            f"tb/sv/{base}/sos_{base}_checker_base.svh":
                _emit_checker_class_base_parallel(
                    chart_name, regions, nested_params, path_params
                ),
            f"tb/sv/{base}/sos_checker_{base}.sv":
                _emit_checker_class_parallel(
                    chart_name, regions, nested_params, path_params
                ),
            f"tb/sv/{base}/tb_{base}.sv":
                _emit_top_module_parallel(chart_name, regions),
            f"tb/sv/{base}/run_verilator.mk":
                _emit_verilator_makefile(chart_name),
            f"tb/sv/{base}/run.do": _emit_questa_do(chart_name),
            f"tb/sv/{base}/Makefile.sv": _emit_vcs_makefile(chart_name),
            f"tb/sv/{base}/run_xrun.sh": _emit_xcelium_argfile(chart_name),
            f"tb/sv/{base}/run_riviera.tcl": _emit_riviera_tcl(chart_name),
        }
    else:
        # Single-region emit. Wave-3-future (2026-05-24 §15) layered
        # class hierarchy: ``_checker_base.svh`` + ``_driver_base.svh``
        # carry the run-skeleton + virtual hooks; the ``_default`` SV
        # files extend them. File counts: single-region grows from 14
        # to 16.
        n_states = max(len(all_state_ids), 1)
        files = {
            f"tb/sv/{base}/dut_if_{base}.sv":
                _emit_virtual_interface(chart_name),
            f"tb/sv/{base}/sos_{base}_driver_base.svh":
                _emit_driver_class_base(chart_name),
            f"tb/sv/{base}/sos_driver_{base}.sv":
                _emit_driver_class(chart_name),
            f"tb/sv/{base}/sos_{base}_checker_base.svh":
                _emit_checker_class_base(
                    chart_name, nested_params, path_params
                ),
            f"tb/sv/{base}/sos_checker_{base}.sv":
                _emit_checker_class(chart_name, nested_params, path_params),
            f"tb/sv/{base}/tb_{base}.sv":
                _emit_top_module(chart_name, n_states),
            f"tb/sv/{base}/run_verilator.mk":
                _emit_verilator_makefile(chart_name),
            f"tb/sv/{base}/run.do": _emit_questa_do(chart_name),
            f"tb/sv/{base}/Makefile.sv": _emit_vcs_makefile(chart_name),
            f"tb/sv/{base}/run_xrun.sh": _emit_xcelium_argfile(chart_name),
            f"tb/sv/{base}/run_riviera.tcl": _emit_riviera_tcl(chart_name),
        }

    # Wave-3-future (2026-05-24 §15): shared JSONL parser package +
    # per-chart state-symbol table. Both files are header-only
    # (`\\`include`d by driver + checker) — single-source of the
    # parser implementation and per-chart string-to-bit-position
    # resolution.
    files[f"tb/sv/{base}/sos_jsonl_parser_pkg.svh"] = (
        _emit_jsonl_parser_pkg(chart_name)
    )
    files[f"tb/sv/{base}/sos_{base}_state_symbols.svh"] = (
        _emit_state_symbols(chart_name, all_state_ids)
    )

    # Wave-3 (2026-05-24 §15) co-lands the Verilator deferred-failure-
    # stub policy header per INV-S-HDL-E-6 / PCDN-SOS-08-E-002. Shared
    # across single-region + parallel emits.
    files[f"tb/sv/{base}/verilator_stubs.svh"] = (
        _emit_verilator_stubs_svh(chart_name)
    )

    # Mirror the SOS-08-D SVA bind file artifact, byte-identical, but
    # re-keyed under the SV testbench directory per §5.2 + §6. For
    # parallel charts the SVA bind walker produces 2N files (one
    # _sva.sv + one _bind.sv per region per SOS-08-D wave-2b); the
    # mirror loop passes them all through.
    sva_files = _render_sva_bind(chart_ir, config)
    for sva_filename, sva_source in sva_files.items():
        leaf = sva_filename.rsplit("/", 1)[-1]
        files[f"tb/sv/{base}/{leaf}"] = sva_source

    # Belt-and-suspenders: scan every emitted file for INV-S-HDL-E-1..3
    # violations before returning. Walker contract is by-construction
    # conformance.
    _audit_all(files)

    return files


# ---------------------------------------------------------------------------
# Dev / debug entry
# ---------------------------------------------------------------------------


if __name__ == "__main__":  # pragma: no cover
    import sys
    from pathlib import Path

    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    from loader import load_chart  # noqa: E402

    chart_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        here.parent.parent / "rtos_kernel.scxml"
    )
    ast = load_chart(chart_path)
    out = render_target(ast.raw_scjson, {"chart_name": chart_path.stem})
    for fname, content in out.items():
        sys.stdout.write(f"=== {fname} ===\n{content}\n")

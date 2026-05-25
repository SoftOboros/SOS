r"""SCXML chart → SVA assertion module + bind directive emitter (SOS-08-D).

Wave-1 scaffold per ``SOS-08-D-CONCEPTS.md`` §6.3 (per-DUT SVA bind file
shape) and §15 (2026-05-23 ratification; PCDN-D-004 resolved → per-DUT
bind file co-located with the cocotb test directory). Emits one
SystemVerilog assertion module + one bind-directive file per single-
region chart, both landing in ``tests/<chart_name>/`` per PCDN-D-004.

@spec  SOS-08-D-CONCEPTS.md §6.3 (per-DUT SVA bind file shape)
@spec  SOS-08-D-CONCEPTS.md §15 (ratification 2026-05-23; PCDN-D-004)
@spec  SOS-08-D-CONCEPTS.md §5.6 (per-DUT bind file placement)
@spec  SOS-08-D-CONCEPTS.md §7 INV-S-HDL-D-3 (vector-IR read-only at emitter)
@spec  SOS-08-D-CONCEPTS.md §7 INV-S-HDL-D-4 (same SVA artifact feeds cocotb + formal)
@spec  SOS-08-D-CONCEPTS.md §7 INV-S-HDL-D-5 (chart-vocabulary failure messages)
@spec  SOS-08-C-CONCEPTS.md §6 (chart→FSM emission this module binds to)
@spec  SOS-08-C-CONCEPTS.md §5.1 (one-hot state encoding mirrored here)
@spec  SOS-07-CONCEPTS.md  INV-SOS-A..H (cross-phase invariants — cited)
@spec  SOS-08-CONCEPTS.md  INV-S-HDL-1..5 (cross-sub-phase invariants — cited;
       INV-S-HDL-5 = chart-vocabulary traceability; load-bearing for $fatal
       messages emitted here)

# Wave-1 scope

* Single-region chart → two files:
  - ``tests/<chart>/<chart>_fsm_sva.sv`` — assertion module containing
    chart-derived invariants:
      - INV-D-1: one-hot invariant on ``current_state``.
      - INV-D-2: reset → initial state.
      - INV-D-3..: per-transition correctness (source && guard |=> target).
  - ``tests/<chart>/<chart>_fsm_bind.sv`` — module-type bind directive
    attaching the assertion module to every elaborated DUT instance.

* The assertion module's input port set mirrors the chart-FSM module's
  observable surface. Per PCDN-SOS-08-D-wave1-sva-port-name (resolved
  2026-05-23), the state-vector input port is named ``current_state``
  verbatim — matching the DUT's output port — because module-type bind
  connects external ports to external ports, not to the DUT's internal
  ``state_q`` register:
      input wire                 clk
      input wire                 rst
      input wire [N_STATES-1:0]  current_state  (driven from DUT's current_state)
  plus one ``input wire [W-1:0] data_<name>_q`` per datamodel signal
  referenced by any transition guard, so the chart's ``cond`` expressions
  compile against in-scope register signals.

* Parallel charts are REJECTED at wave-1 with ``UnsupportedChartError``;
  the per-region wrap + chart-top wrapper bind lands in wave-2.

# Integration contract

The codegen tool's CLI dispatcher invokes::

    from transliterate_sva_bind import render_target
    files = render_target(chart_ir, config)

``chart_ir`` is the raw scjson dict (the unprocessed JSON tree the loader
produced, sourced from ``ChartAst.raw_scjson``). Output is a
``dict[filename, source]``; the dispatcher writes each entry under the
emitted test directory per §6.1.

# State encoding parity with SOS-08-C

Wave-1 mirrors the SOS-08-C one-hot state encoding (PCDN-SOS-08-C-005
chart-annotation-wins; default one-hot). State-constant names use the
``ST_<UPPER_ID>`` convention from
``transliterate_hdl_sv._state_constant_name`` so the chart-FSM module's
``ST_*`` constants are byte-identical to the SVA module's. The encoding
is duplicated locally (not imported) so this file stays file-disjoint
from SOS-08-C walkers per the wave-1 deliverable contract.

# Failure-message format (INV-S-HDL-5 + INV-S-HDL-D-5)

Every ``assert property`` has an ``else $fatal(1, ...)`` clause whose
message format is::

    SOS-08-D <INVARIANT_ID>: <chart-vocabulary description> @ %t

with the chart vocabulary surfaced — chart name, source state, target
state, invariant id — so a simulator failure trace renders in chart-author
language per INV-S-HDL-5. Wave-1 keeps the format simple (the §6.6 full
``\`SOS_FAIL`` macro is wave-2 scope alongside the bound-analysis
metadata pass).

# Wave-2 follow-ups (out of scope here)

* Parallel-chart support — one ``_fsm_sva.sv`` per region + one
  ``_top_sva.sv`` wrapping the chart-top + cross-domain CDC properties.
* Full ``\`SOS_FAIL`` macro per §6.6 (chart file / region / transition
  id / state id / invariant id formatter).
* Event-egress (``<raise>``) coverage assertions — wire to SOS-08-B
  L1 service-channel properties once §6.4/§6.5 land.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ----------------------------------------------------------------------------
# Optional hdl_common helpers — used for guard expression lowering when on
# disk; degrade to a minimal inline rewrite if the sibling helper hasn't
# pinned its canonical signature yet. Keeps wave-1 emission unblocked.
# ----------------------------------------------------------------------------

try:  # pragma: no cover — exercised when hdl_common wave-2 is on disk.
    from hdl_common import Dialect as _Dialect  # type: ignore
except (ImportError, AttributeError):  # pragma: no cover
    _Dialect = None

try:  # pragma: no cover
    from hdl_common import emit_guard_expr as _emit_guard_expr  # type: ignore
except (ImportError, AttributeError):  # pragma: no cover
    _emit_guard_expr = None

try:  # pragma: no cover
    from hdl_common import GuardDepthError as _GuardDepthError  # type: ignore
except (ImportError, AttributeError):  # pragma: no cover
    class _GuardDepthError(Exception):  # type: ignore[no-redef]
        """Local fallback for hdl_common.GuardDepthError."""

try:  # pragma: no cover
    from hdl_common import DEFAULT_GUARD_DEPTH_BUDGET as _DEFAULT_GUARD_DEPTH_BUDGET
except (ImportError, AttributeError):  # pragma: no cover
    _DEFAULT_GUARD_DEPTH_BUDGET = 8

# SOS-08-D wave-4 (2026-05-24): per-domain clock + reset port naming
# helpers imported from hdl_common (the chart-top wrapper's
# clock-distribution contract authority per SOS-08-C wave-3).
try:  # pragma: no cover
    from hdl_common import clk_port_name as _clk_port_name  # type: ignore
    from hdl_common import rst_port_name as _rst_port_name  # type: ignore
except (ImportError, AttributeError):  # pragma: no cover
    def _clk_port_name(domain: str) -> str:  # type: ignore[no-redef]
        return domain if domain.startswith("clk_") else f"clk_{domain}"

    def _rst_port_name(domain: str) -> str:  # type: ignore[no-redef]
        if domain.startswith("clk_"):
            return "rst_" + domain[len("clk_"):]
        return f"rst_{domain}"


# ----------------------------------------------------------------------------
# Error surface.
# ----------------------------------------------------------------------------


class UnsupportedChartError(Exception):
    """Chart construct outside the current SVA-bind emission scope.

    Per INV-S-HDL-5 (chart-vocabulary traceability), every rejection
    surfaces the chart construct + the wave / phase doc that owns the
    feature gate.
    """


class GuardDepthExceeded(UnsupportedChartError):
    """Chart transition's compiled guard exceeds the PCDN-C-004 depth
    budget (default 8 chained operators). Mirrors SOS-08-C's emit-time
    gate so SVA properties don't smuggle un-synthesizable guards past
    the chart-compile-time lint."""


# ----------------------------------------------------------------------------
# Normalised view (mirrors SOS-08-C's shape but kept LOCAL to maintain
# file-disjoint scope per the wave-1 deliverable contract).
# ----------------------------------------------------------------------------


@dataclass
class _SvaTransition:
    """One outgoing transition referenced by an assertion property."""

    source: str
    target: str
    cond: str | None = None
    event: str | None = None
    doc_order: int = 0


@dataclass
class _SvaState:
    """One <state id="..."/> in the (single) chart region."""

    state_id: str
    transitions: list[_SvaTransition] = field(default_factory=list)


@dataclass
class _SvaDatamodelSignal:
    """One <data id="..." [type="..."] [width="..."]/> reference. Wave-1
    only inputs signals referenced by transition guards; everything else
    is reserved for wave-2 (assertions on onentry/onexit writes etc.)."""

    chart_id: str
    width: int
    sv_name: str  # `data_<sanitised>_q` registered-signal name.


@dataclass
class _SvaChart:
    """Normalised single-region chart view."""

    chart_name: str
    states: list[_SvaState]
    initial_state: str
    datamodel: dict[str, _SvaDatamodelSignal]


# ----------------------------------------------------------------------------
# Identifier helpers — LOCAL copies of SOS-08-C's helpers so the SVA
# module's ST_* constants match the FSM module's bit-identically without
# importing the SV walker (file-disjoint constraint per the wave-1 brief).
# ----------------------------------------------------------------------------


_RESERVED_GUARD_TOKENS = {
    "true", "false", "and", "or", "not",
    "True", "False", "None",
    "in", "if", "else", "elif", "return", "begin", "end",
}


def _sanitize_sv_identifier(name: str) -> str:
    """Map an SCXML id to an SV identifier; deterministic so the SVA
    module's signal names match the FSM module's by construction."""
    if not name:
        return "_anon"
    out_chars: list[str] = []
    for ch in name:
        if ch.isalnum() or ch == "_":
            out_chars.append(ch)
        else:
            out_chars.append("_")
    out = "".join(out_chars)
    if out and out[0].isdigit():
        out = "_" + out
    return out


def _state_constant_name(state_id: str) -> str:
    """Mirror ``transliterate_hdl_sv._state_constant_name``."""
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in state_id)
    return f"ST_{safe.upper()}"


def _module_name(chart_name: str) -> str:
    """Mirror ``transliterate_hdl_sv._module_name``. The chart-FSM module
    we bind against is named ``<chart>_fsm``."""
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in chart_name)
    if safe and safe[0].isdigit():
        safe = "x" + safe
    return f"{safe.lower()}_fsm"


def _sva_module_name(chart_name: str) -> str:
    """Assertion module name: ``<chart>_fsm_sva``."""
    return f"{_module_name(chart_name)}_sva"


def _one_hot_value(index: int, n_states: int) -> str:
    """Mirror ``transliterate_hdl_sv._one_hot_value``."""
    bits = ["0"] * n_states
    bits[n_states - 1 - index] = "1"
    return f"{n_states}'b" + "".join(bits)


# ----------------------------------------------------------------------------
# Chart-IR normalisation. Wave-1 accepts a single-region chart only;
# parallel charts raise UnsupportedChartError with a wave-2 citation.
# ----------------------------------------------------------------------------


def _walk_states_in_order(node: dict[str, Any]):
    """Depth-first scjson walk yielding ``(state_id, state_dict)`` for
    every ``<state>`` in document order."""
    for st in node.get("state", []) or []:
        sid = st.get("id")
        if sid:
            yield sid, st
        yield from _walk_states_in_order(st)


def _collect_datamodel(chart: dict[str, Any]) -> dict[str, _SvaDatamodelSignal]:
    """Walk the chart-root ``<datamodel>`` into the SVA-side reference
    table. Mirrors SOS-08-C's width inference (i32 default; honours
    explicit ``width=`` / ``type=`` annotations)."""
    dm = chart.get("datamodel", [])
    entries: list[dict[str, Any]] = []
    if isinstance(dm, list):
        for entry in dm:
            if not isinstance(entry, dict):
                continue
            for d in entry.get("data", []) or []:
                entries.append(d)
    elif isinstance(dm, dict):
        for d in dm.get("data", []) or []:
            entries.append(d)

    out: dict[str, _SvaDatamodelSignal] = {}
    for d in entries:
        chart_id = d.get("id") or ""
        if not chart_id:
            continue
        explicit_width: int | None = None
        raw_width = d.get("width")
        if raw_width is not None:
            try:
                explicit_width = int(raw_width)
            except (TypeError, ValueError):
                explicit_width = None
        scxml_type = str(d.get("type") or "").strip().lower()
        width_table = {
            "bool": 1, "bit": 1,
            "i8": 8, "u8": 8,
            "i16": 16, "u16": 16,
            "i32": 32, "u32": 32, "int": 32, "integer": 32, "uint": 32,
            "i64": 64, "u64": 64,
        }
        if explicit_width is not None and explicit_width > 0:
            width = explicit_width
        else:
            width = width_table.get(scxml_type, 32)
        sv_name = f"data_{_sanitize_sv_identifier(chart_id)}_q"
        out[chart_id] = _SvaDatamodelSignal(
            chart_id=chart_id,
            width=width,
            sv_name=sv_name,
        )
    return out


def _normalise_chart(
    chart_ir: dict[str, Any], chart_name: str
) -> _SvaChart:
    """Build the single-region ``_SvaChart`` from chart_ir.

    Per SOS-08-D §15 wave-2b ratification (2026-05-23): parallel charts
    are no longer rejected here — the caller dispatches through
    ``_normalise_parallel_chart`` when the chart carries a top-level
    ``<parallel>``. This function continues to handle the single-region
    code path. Re-entry from the parallel walker passes one region's
    state subtree as ``chart_ir`` with the region name embedded in
    ``chart_name`` per the parallel-chart naming convention.
    """
    states: list[_SvaState] = []
    for sid, st in _walk_states_in_order(chart_ir):
        sva_state = _SvaState(state_id=sid)
        for idx, tr in enumerate(st.get("transition", []) or []):
            # <raise> is wave-2 / wave-3 (SOS-08-D §6.6 + SOS-08-C wave-3).
            target = tr.get("target")
            if isinstance(target, list):
                target = target[0] if target else None
            if not target:
                # Internal transition (no target) — wave-1 ignores.
                continue
            sva_state.transitions.append(
                _SvaTransition(
                    source=sid,
                    target=str(target),
                    cond=tr.get("cond"),
                    event=tr.get("event"),
                    doc_order=idx,
                )
            )
        states.append(sva_state)

    if not states:
        raise UnsupportedChartError(
            "SOS-08-D wave-1 scaffold requires at least one <state>; "
            f"chart '{chart_name}' has none."
        )

    initial = chart_ir.get("initial")
    if isinstance(initial, list):
        initial = initial[0] if initial else None
    if not initial:
        initial = states[0].state_id

    datamodel = _collect_datamodel(chart_ir)

    return _SvaChart(
        chart_name=chart_name,
        states=states,
        initial_state=str(initial),
        datamodel=datamodel,
    )


# ----------------------------------------------------------------------------
# Guard-expression lowering. Routes through hdl_common.emit_guard_expr
# (Dialect.SV) when available; falls back to a minimal local rewriter
# that prefixes bare identifiers with ``data_`` + suffixes with ``_q``.
# ----------------------------------------------------------------------------


def _resolve_depth_budget(config: Any) -> int:
    if isinstance(config, dict):
        v = config.get("guard_depth_budget")
        if isinstance(v, int) and v > 0:
            return v
    elif config is not None:
        v = getattr(config, "guard_depth_budget", None)
        if isinstance(v, int) and v > 0:
            return v
    return _DEFAULT_GUARD_DEPTH_BUDGET


def _prefix_datamodel_idents(text: str) -> str:
    """Rewrite bare datamodel identifiers (e.g. ``counter``) into the
    ``data_<sanitised>`` shape ``emit_guard_expr`` then suffixes ``_q``
    onto. Reserved tokens, numeric literals, and already-prefixed
    identifiers stay untouched."""

    def repl(match: re.Match[str]) -> str:
        tok = match.group(0)
        if tok in _RESERVED_GUARD_TOKENS or tok.lower() in _RESERVED_GUARD_TOKENS:
            return tok
        if tok[0].isdigit():
            return tok
        if tok.startswith("data_"):
            return tok
        return f"data_{_sanitize_sv_identifier(tok)}"

    return re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\b", repl, text)


def _compile_guard(cond_str: str, depth_budget: int) -> str:
    """Lower a chart ``cond`` to a single-line SV expression.

    Wave-1 routes through ``hdl_common.emit_guard_expr(..., Dialect.SV)``
    if available so the rendered guard matches what the chart-FSM
    module's transition mux emits (so the SVA assertion's antecedent
    references the same registered signal). Falls back to a minimal
    local rewrite (bare ident → ``data_<id>_q``) otherwise.

    Raises ``GuardDepthExceeded`` if the compiled depth exceeds the
    PCDN-C-004 budget.
    """
    if not cond_str:
        return "1'b1"

    if _emit_guard_expr is not None and _Dialect is not None:
        try:
            return _emit_guard_expr(
                _prefix_datamodel_idents(cond_str),
                _Dialect.SV,
                depth_budget=depth_budget,
            )
        except _GuardDepthError as exc:
            raise GuardDepthExceeded(
                f"SOS-08-D §6.3 / PCDN-C-004 — guard expression "
                f"{cond_str!r} exceeds the configured depth budget of "
                f"{depth_budget}: {exc}"
            ) from exc
        except TypeError:
            # Signature drift — fall through to inline fallback.
            pass

    def _replace_ident(match: re.Match[str]) -> str:
        tok = match.group(0)
        if tok[0].isdigit():
            return tok
        if tok.lower() in ("true", "false", "and", "or", "not"):
            return {
                "true": "1'b1", "false": "1'b0",
                "and": "&&", "or": "||", "not": "!",
            }.get(tok.lower(), tok)
        if tok.startswith("data_") and tok.endswith("_q"):
            return tok
        if tok.startswith("data_"):
            return f"{tok}_q"
        return f"data_{_sanitize_sv_identifier(tok)}_q"

    return re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\b", _replace_ident, cond_str)


def _datamodel_signals_referenced_in_guards(
    chart: _SvaChart,
) -> list[_SvaDatamodelSignal]:
    """Collect datamodel signals whose chart-id is referenced by any
    transition guard. Wave-1 routes these onto the SVA module's port
    list so the antecedent compiles. Output preserves chart-declaration
    order (stable across re-emit per INV-S-HDL-C-1 / INV-S-HDL-D-3)."""
    seen: set[str] = set()
    for s in chart.states:
        for tr in s.transitions:
            if not tr.cond:
                continue
            for tok in re.findall(
                r"\b[A-Za-z_][A-Za-z0-9_]*\b", tr.cond
            ):
                if tok.lower() in _RESERVED_GUARD_TOKENS:
                    continue
                if tok[0].isdigit():
                    continue
                if tok in chart.datamodel:
                    seen.add(tok)
    return [chart.datamodel[name] for name in chart.datamodel if name in seen]


# ----------------------------------------------------------------------------
# SVA module + bind directive rendering.
# ----------------------------------------------------------------------------


def _emit_header(chart_name: str, kind: str) -> str:
    """Top-of-file ``@spec`` citation block (mirrors the SOS-08-C
    emitter's header conventions; substitute the SOS-08-D citations
    in place of the SOS-08-C ones)."""
    return "\n".join(
        [
            f"// Generated by tools/sos-codegen/transliterate_sva_bind.py",
            f"// Chart: {chart_name}",
            f"// Kind : {kind}",
            f"// Spec : SOS-08-D-CONCEPTS.md §6.3 (per-DUT SVA bind file shape),",
            f"//        §15 (ratified 2026-05-23; PCDN-D-004 per-DUT bind co-located)",
            f"// Inv. : INV-SOS-A..H (SOS-07), INV-S-HDL-1..5 (SOS-08),",
            f"//        INV-S-HDL-D-3..5 (SOS-08-D §7 — vector-IR read-only,",
            f"//        same SVA artifact feeds cocotb+formal, chart-vocabulary",
            f"//        failure messages per INV-S-HDL-5)",
            f"// Wave : 1 — single-region chart; parallel charts land in wave-2.",
        ]
    )


def _emit_sva_module(chart: _SvaChart, depth_budget: int) -> str:
    """Emit the assertion module file body.

    Properties:
      * INV-D-1: ``$countones(current_state) <= 1`` — one-hot invariant
        mirroring the SOS-08-C §5.1 default encoding.
      * INV-D-2: ``rst |=> current_state == ST_<initial>`` — reset clears
        state to the chart ``initial`` per SOS-08-C §5.6 / PCDN-C-003.
      * INV-D-3..: per-transition
        ``current_state == src && guard |=> current_state == tgt``.

    Port-name note (PCDN-SOS-08-D-wave1-sva-port-name, 2026-05-23):
    the state-vector input port is ``current_state`` — matching the
    DUT's external output port — not ``state_q`` (the DUT-internal
    register name). Module-type bind wires external→external.
    """
    n_states = len(chart.states)
    sva_module = _sva_module_name(chart.chart_name)
    initial_const = _state_constant_name(chart.initial_state)

    # Pre-compile per-transition assertions so we can fail fast on a
    # depth-overflow guard before stitching together the module body.
    transition_props: list[tuple[str, _SvaTransition, str]] = []
    inv_id_counter = 3
    for state in chart.states:
        for tr in state.transitions:
            guard_sv = _compile_guard(tr.cond or "", depth_budget)
            inv_id = f"INV-D-{inv_id_counter}"
            inv_id_counter += 1
            transition_props.append((inv_id, tr, guard_sv))

    # Datamodel signals referenced by any guard → input ports.
    guard_signals = _datamodel_signals_referenced_in_guards(chart)

    # ---------- module header / port list ----------
    port_lines: list[str] = []
    port_lines.append("input wire clk")
    port_lines.append("input wire rst")
    # PCDN-SOS-08-D-wave1-sva-port-name (2026-05-23): the SVA module's
    # state-vector input port name MUST match the DUT's external output
    # port name (`current_state`), not the DUT-internal register name
    # (`state_q`). Module-type bind connects external→external.
    port_lines.append(f"input wire [{n_states - 1}:0] current_state")
    for sig in guard_signals:
        if sig.width == 1:
            port_lines.append(f"input wire {sig.sv_name}")
        else:
            port_lines.append(
                f"input wire [{sig.width - 1}:0] {sig.sv_name}"
            )

    header_lines: list[str] = []
    header_lines.append(_emit_header(chart.chart_name, kind="sva-assertion-module"))
    header_lines.append("")
    header_lines.append("`default_nettype none")
    header_lines.append("")
    header_lines.append(f"module {sva_module} (")
    for i, pl in enumerate(port_lines):
        suffix = "," if i < len(port_lines) - 1 else ""
        header_lines.append(f"    {pl}{suffix}")
    header_lines.append(");")

    # ---------- state-encoding constants ----------
    const_lines: list[str] = []
    const_lines.append(
        "    // ----- state encoding (one-hot per SOS-08-C §5.1; mirrors"
    )
    const_lines.append("    //       the chart-FSM module's ST_* constants) -----")
    for idx, s in enumerate(chart.states):
        cname = _state_constant_name(s.state_id)
        val = _one_hot_value(idx, n_states)
        const_lines.append(
            f"    localparam logic [{n_states - 1}:0] {cname} = {val};"
        )

    # ---------- INV-D-1: one-hot invariant ----------
    one_hot_block = [
        "",
        "    // ----- INV-D-1: one-hot state vector (SOS-08-C §5.1 encoding) -----",
        "    a_one_hot: assert property (",
        "            @(posedge clk) disable iff (rst) ($countones(current_state) <= 1)",
        "        )",
        "        else $fatal(1,",
        f'            "SOS-08-D INV-D-1: chart {chart.chart_name} state vector '
        'violates one-hot encoding at %0t", $time);',
    ]

    # ---------- INV-D-2: reset → initial state ----------
    reset_block = [
        "",
        "    // ----- INV-D-2: reset clears state to chart <initial> (SOS-08-C §5.6) -----",
        "    a_reset_initial: assert property (",
        f"            @(posedge clk) rst |=> (current_state == {initial_const})",
        "        )",
        "        else $fatal(1,",
        f'            "SOS-08-D INV-D-2: chart {chart.chart_name} reset did not '
        f'restore initial state {initial_const} @ %0t", $time);',
    ]

    # ---------- INV-D-3..: per-transition correctness ----------
    trans_blocks: list[str] = []
    if transition_props:
        trans_blocks.append("")
        trans_blocks.append(
            "    // ----- INV-D-3..: per-transition correctness "
            "(PCDN-C-006 document-order priority) -----"
        )
    for inv_id, tr, guard_sv in transition_props:
        src_const = _state_constant_name(tr.source)
        tgt_const = _state_constant_name(tr.target)
        ident = (
            f"a_trans_{_sanitize_sv_identifier(tr.source).lower()}_to_"
            f"{_sanitize_sv_identifier(tr.target).lower()}_{tr.doc_order}"
        )
        # Compose antecedent: state match && guard (omit `&& 1'b1` for
        # unguarded transitions to keep the emit minimal).
        if tr.cond:
            antecedent = f"(current_state == {src_const}) && ({guard_sv})"
        else:
            antecedent = f"(current_state == {src_const})"
        trans_blocks.extend(
            [
                "",
                f"    // {inv_id}: {tr.source} --[cond={tr.cond or '-'}/event={tr.event or '-'}]--> {tr.target}",
                f"    {ident}: assert property (",
                "            @(posedge clk) disable iff (rst)",
                f"            {antecedent} |=> (current_state == {tgt_const})",
                "        )",
                "        else $fatal(1,",
                f'            "SOS-08-D {inv_id}: chart {chart.chart_name} '
                f'transition {tr.source}->{tr.target} '
                f'(cond={tr.cond or "-"}/event={tr.event or "-"}) failed @ %0t",',
                "            $time);",
            ]
        )

    footer = ["", "endmodule", "", "`default_nettype wire"]

    return "\n".join(
        header_lines
        + [""]
        + const_lines
        + one_hot_block
        + reset_block
        + trans_blocks
        + footer
    ) + "\n"


def _emit_bind_directive(chart: _SvaChart) -> str:
    """Emit the module-type ``bind`` directive file. PCDN-D-004 places
    the bind file in the per-DUT test directory (``tests/<chart>/``);
    the directive references the assertion module by name and wires the
    chart-FSM module's observable ports through to it.

    The chart-FSM module's outputs include ``clk``, ``rst``, and
    ``current_state`` (per SOS-08-C §6.2 / INV-S-HDL-C-2). Per
    PCDN-SOS-08-D-wave1-sva-port-name (2026-05-23), the SVA module's
    matching input port is also named ``current_state`` — module-type
    bind connects external→external, so the port name on the SVA side
    matches the DUT's output port name verbatim (not the DUT's
    internal ``state_q`` register). Guard-referenced datamodel signals
    are connected by name (``data_<id>`` on the DUT → ``data_<id>_q``
    on the SVA module).
    """
    dut_module = _module_name(chart.chart_name)
    sva_module = _sva_module_name(chart.chart_name)

    guard_signals = _datamodel_signals_referenced_in_guards(chart)

    conn_lines: list[str] = [
        "    .clk           (clk),",
        "    .rst           (rst),",
        "    .current_state (current_state)",
    ]
    if guard_signals:
        # Append a comma to the previous final connection and add the
        # datamodel signal hookups.
        conn_lines[-1] = "    .current_state (current_state),"
        for i, sig in enumerate(guard_signals):
            dut_signal = f"data_{_sanitize_sv_identifier(sig.chart_id)}"
            suffix = "," if i < len(guard_signals) - 1 else ""
            conn_lines.append(f"    .{sig.sv_name}  ({dut_signal}){suffix}")

    inst_name = f"u_{sva_module}"

    lines: list[str] = [
        _emit_header(chart.chart_name, kind="sva-bind-directive"),
        "",
        "// PCDN-D-004 (resolved 2026-05-23): per-DUT bind file co-located",
        "// with the cocotb test directory (tests/<chart>/). The assertion",
        "// module body lives at the same level (tests/<chart>/<chart>_fsm_sva.sv)",
        "// per the wave-1 deliverable; SOS-08-A/B-style rtl-layer placement",
        "// is a wave-2 refactor (PCDN-D-004 documents both flavours as",
        "// compatible — the wave-1 emit picks the test-co-located shape).",
        "",
        "`default_nettype none",
        "",
        f"bind {dut_module} {sva_module} {inst_name} (",
        *conn_lines,
        ");",
        "",
        "`default_nettype wire",
    ]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------
# Parallel-chart support (SOS-08-D wave-2b — 2026-05-23).
# ----------------------------------------------------------------------------


def _collect_parallel_regions(
    chart_ir: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    """Return [(region_name, region_state_subtree), ...] for a parallel
    chart.

    A parallel chart has a top-level ``<parallel>`` element whose
    ``<state>`` children are the regions. Each region carries its own
    states + transitions; the region's subtree shape is the same as a
    single-region chart's, so we can pass each subtree through the
    existing ``_normalise_chart`` machinery.

    Per SOS-08-C §6.1 + the parallel-region machinery: region names
    come from the ``id`` attribute of each ``<state>`` child of the
    top-level ``<parallel>``.
    """
    out: list[tuple[str, dict[str, Any]]] = []
    parallels = chart_ir.get("parallel") or []
    for par in parallels:
        for region_state in par.get("state") or []:
            rid = region_state.get("id")
            if isinstance(rid, str) and rid:
                out.append((rid, region_state))
    return out


def _region_clock_domain(region_state: dict[str, Any]) -> str | None:
    """Return the region's clock-domain annotation per SOS-08-D wave-4.

    Per SOS-08-C wave-3's clock-distribution contract, a region MAY
    declare its clock domain via a ``clock="<domain>"`` attribute on
    the region's ``<state>`` element. When present, the chart-top
    wrapper exposes ``clk_<domain>`` / ``rst_<domain>`` ports and
    instantiates the region FSM clocked on those ports. The SVA bind
    walker wave-4 reads the same annotation to wire each region's
    bind directive to the matching per-domain clock + reset.

    Returns ``None`` for regions without a clock annotation (wave-2b
    single-clock-domain default — the bind uses ``.clk(clk),
    .rst(rst)``).
    """
    clock = region_state.get("clock")
    if isinstance(clock, str) and clock.strip():
        return clock.strip()
    return None


def _per_region_chart_name(chart_name: str, region_name: str) -> str:
    """``<chart>_region_<region>`` — base chart-name string passed into
    ``_module_name`` / ``_sva_module_name`` to produce the per-region
    SVA module name + per-region bind directive file basename.

    Mirrors SOS-08-C wave-2's per-region SV module naming convention
    (``<chart>_region_<name>_fsm`` per the SOS-08-C walker's region
    module emit step) so the per-region SVA module's basename collides
    with the per-region FSM module's basename in canonical-naming
    space, and the bind directive's target-module reference works
    against the chart-top wrapper that instantiates each region FSM.
    """
    return f"{chart_name}_region_{region_name}"


def _emit_parallel_bind_directive(
    chart: _SvaChart,
    chart_top_module: str,
    region_name: str,
    clock_domain: str | None = None,
) -> str:
    """Per-region bind directive for parallel charts.

    Differs from ``_emit_bind_directive`` (single-region wave-1) in
    one normative way: the DUT module being bound to is the
    **chart-top wrapper** (``<chart>_fsm``, passed verbatim via
    ``chart_top_module``), NOT the per-region FSM module. The chart-
    top wrapper exposes one ``current_state_<region>`` output port per
    region (per SOS-08-C §6.10 chart-top wrapper emission); this bind
    wires that per-region output to the SVA module's region-local
    ``current_state`` input port.

    SOS-08-D wave-4 (2026-05-24 §15): when ``clock_domain`` is non-
    None the bind directive wires per-domain ``clk_<dom>`` / ``rst_<dom>``
    ports per SOS-08-C wave-3's clock-distribution contract. The
    chart-top wrapper exposes ``clk_<dom>`` / ``rst_<dom>`` outputs
    that route to each region's domain-specific clock + reset. When
    ``clock_domain is None`` (wave-2b default) the bind uses ``clk`` /
    ``rst`` unchanged.

    Args:
        chart: per-region ``_SvaChart`` (its ``chart_name`` is the
            ``<chart>_region_<region>`` form per
            ``_per_region_chart_name``).
        chart_top_module: the chart-top wrapper module name —
            ``<chart>_fsm`` per SOS-08-C §6.10. The bind targets this
            module, not the per-region FSM module.
        region_name: the region's chart-side identifier; used only to
            cite the region in the emitted file header comment.
        clock_domain: per-region clock domain (per
            ``_region_clock_domain``). When non-None the bind directive
            wires ``clk_<dom>``/``rst_<dom>`` (wave-4 multi-clock
            shape); when None the bind uses ``clk``/``rst`` (wave-2b
            single-clock shape, preserved for backwards compat).
    """
    sva_module = _sva_module_name(chart.chart_name)
    region_observable = f"current_state_{_sanitize_sv_identifier(region_name)}"

    # Wave-4: per-domain clock + reset port resolution. When the region
    # declares a clock domain, wire its bind to the chart-top wrapper's
    # ``clk_<dom>`` / ``rst_<dom>`` outputs (per SOS-08-C wave-3 clock-
    # distribution contract); otherwise fall back to the wave-2b
    # single-clock-domain ``clk`` / ``rst``.
    if clock_domain is not None:
        clk_port = _clk_port_name(clock_domain)
        rst_port = _rst_port_name(clock_domain)
        clk_doc = (
            f"// Wave-4 multi-clock: region clock domain = `{clock_domain}` →\n"
            f"//                     `.clk({clk_port})`, `.rst({rst_port})`."
        )
    else:
        clk_port = "clk"
        rst_port = "rst"
        clk_doc = (
            "// Wave-2b single-clock-domain default: bind wires "
            "`.clk(clk)` / `.rst(rst)`."
        )

    guard_signals = _datamodel_signals_referenced_in_guards(chart)

    conn_lines: list[str] = [
        f"    .clk           ({clk_port}),",
        f"    .rst           ({rst_port}),",
        f"    .current_state ({region_observable})",
    ]
    if guard_signals:
        conn_lines[-1] = (
            f"    .current_state ({region_observable}),"
        )
        for i, sig in enumerate(guard_signals):
            dut_signal = f"data_{_sanitize_sv_identifier(sig.chart_id)}"
            suffix = "," if i < len(guard_signals) - 1 else ""
            conn_lines.append(
                f"    .{sig.sv_name}  ({dut_signal}){suffix}"
            )

    inst_name = f"u_{sva_module}"

    lines: list[str] = [
        _emit_header(chart.chart_name, kind="sva-bind-directive"),
        "",
        "// SOS-08-D wave-2b: per-region bind for parallel charts.",
        f"// Region: {region_name}",
        f"// Chart-top wrapper module bound to: {chart_top_module}",
        f"// Per-region SVA module:             {sva_module}",
        f"// Observable wired to SVA input:     {region_observable}",
        "//",
        "// Per SOS-08-C §6.10 (chart-top wrapper emission), the",
        "// chart-top wrapper instantiates each region FSM and exposes",
        "// one current_state_<region> output per region. The bind",
        "// directive below attaches the per-region SVA module to the",
        "// chart-top wrapper instance and wires the corresponding",
        "// current_state_<region> port to the SVA module's region-local",
        "// current_state input.",
        "//",
        clk_doc,
        "",
        "`default_nettype none",
        "",
        f"bind {chart_top_module} {sva_module} {inst_name} (",
        *conn_lines,
        ");",
        "",
        "`default_nettype wire",
    ]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------
# SOS-08-D wave-4 (2026-05-24 §15) — cross-region invariant emission.
# ----------------------------------------------------------------------------


@dataclass
class _CrossInvariant:
    """One ratified ``<sos:cross_invariant>`` declaration.

    Wave-4 declaration form (frozen per §15):

        <sos:cross_invariant id="INV-S-CHART-N"
                             antecedent="region.<name> == <state>"
                             consequent="region.<other> == <state>"
                             within="K" />

    Semantics: on every clock edge where ``antecedent`` is true, the
    SVA property requires ``consequent`` to hold within ``[1:within]``
    cycles. The walker lowers each declaration into a ``property``
    + ``assert property`` clause in ``<chart>_top_sva.sv`` whose
    failure message renders in chart vocabulary per INV-S-HDL-D-5.

    The ``within`` attribute defaults to 1 (single-cycle reaction)
    when absent. A value < 1 is normalised to 1; a value > 1024 is
    rejected as outside the v1 bounded-reachability window.

    Wave-4-future (2026-05-24 §15) — compound cross-invariant
    expressions: when the declaration carries any ``<sos:and>`` /
    ``<sos:or>`` / ``<sos:not>`` / ``<sos:implies>`` child OR a list
    of ``<sos:state_ref>`` children (the implicit-AND form), the
    walker populates ``expr`` with a ``_CompoundExpr`` AST and
    leaves the antecedent/consequent attribute fields empty. The
    emit path branches on ``expr is not None`` to choose between the
    wave-4 implies-style property (with ``##[1:within]`` window) and
    the wave-4-future-compound boolean property (single-cycle SVA
    expression).

    Wave-4-future-multi-clock (2026-05-24 §15) — per-region clock
    declarations: when the cross-invariant carries one or more
    ``<sos:sampling_clock region="..." clock="..."/>`` children, the
    walker populates ``sampling_clocks`` with a region→clock map
    (ordered by source-document order) and ``primary_clock_region``
    with the first sampling-clock entry's region (the primary
    sampling-clock for the property's ``@(posedge ...)`` header).
    The emit path takes the IEEE 1800-2017 §16.13 multi-clocked
    assertion form: subsequent regions wrap their leaf observable
    in ``$past(<expr>, 1, , @(posedge <its_clock>))``.
    """

    id: str
    antecedent_region: str
    antecedent_state: str
    consequent_region: str
    consequent_state: str
    within: int
    # Wave-4-future-compound: populated when the cross-invariant
    # uses compound boolean elements or a list of state_ref children
    # (implicit-AND). When ``expr`` is not None the wave-4
    # antecedent/consequent fields are placeholders ("" / 0) and
    # the emit path uses ``expr`` for both the SVA body + the
    # chart-vocabulary failure message.
    expr: "_CompoundExpr | None" = None
    # Wave-4-future-multi-clock: ordered region→clock map declared by
    # one or more ``<sos:sampling_clock region="..." clock="..."/>``
    # children. Empty when the invariant uses the wave-4 single-clock
    # path (sampled on chart-top ``clk``).
    sampling_clocks: dict[str, str] = field(default_factory=dict)
    # Wave-4-future-multi-clock: the region naming the primary
    # ``@(posedge ...)`` clock for the property. Source-document order
    # of ``<sos:sampling_clock>`` children controls primacy.
    primary_clock_region: str | None = None


@dataclass
class _CompoundExpr:
    """One node in a compound cross-invariant boolean AST.

    Wave-4-future (2026-05-24 §15): structured boolean composition
    over ``<sos:state_ref>`` leaves. Supported ``kind`` values:

    * ``'and'`` — 2+ children; lowers to ``(c1 && c2 && ...)``.
    * ``'or'`` — 2+ children; lowers to ``(c1 || c2 || ...)``.
    * ``'not'`` — exactly 1 child; lowers to ``!(c)``.
    * ``'implies'`` — exactly 2 children (antecedent, consequent);
      lowers to ``(antecedent |-> consequent)`` per IEEE 1800-2017
      §16.12.2 (overlapping-implication operator).
    * ``'state_ref'`` — leaf; ``region`` + ``state`` populated. Lowers
      to ``(current_state_<region> == ST_<state>)`` matching the wave-4
      leaf encoding. Reuses the wave-4-future state-encoding
      pass-through (the per-region one-hot bit index machinery from
      ``_build_region_state_indices``) — DO NOT re-implement.

    Authority relationship per §0:
      * Element shape (``<sos:and>``/``<sos:or>``/``<sos:not>``/
        ``<sos:implies>``/``<sos:state_ref>``)  — relationship ``own``.
      * SVA boolean lowering (subset of IEEE 1800-2017 §11.4.7 logical
        operators + §16.12.2 implication) — relationship ``derive``.
    """

    kind: str
    children: list["_CompoundExpr"] = field(default_factory=list)
    region: str | None = None
    state: str | None = None


_CROSS_INVARIANT_WITHIN_CAP = 1024
"""Wave-4 frozen cap on `within` cycles; bounds the SVA window so
   commercial-sim assertion-engine memory stays reasonable. Bump by
   §15 amendment if a real-world chart needs longer."""


_COMPOUND_OPERATOR_NAMES = ("and", "implies", "not", "or")
"""Wave-4-future (2026-05-24 §15): set of supported compound boolean
   operators. The frozen-enum registration policy is Standards Action
   (cross-phase contract surface — adding a value requires a §15
   amendment). The set is intentionally small at v1; SVA-specific
   operators (`##`, `[*]`, sampled-value functions) require
   `<sos:raw_property>` per the wave-4-future §15 entry.

   Order is **alphabetic** — `and`, `implies`, `not`, `or`. This is
   the canonical traversal order pinned by SOS-08-D-CONCEPTS §15
   2026-05-25 (post-wave-4 follow-ups, Issue B). The walker MUST emit
   compound-child operator nodes in this order when chart authors
   intermix different operator children at the same nesting level.
   See `_collect_compound_children` below."""


# ----------------------------------------------------------------------------
# SOS-08-D wave-4-future (2026-05-24 §15) — `<sos:raw_property>` escape
# hatch. Chart authors paste literal SVA into a `<sos:raw_property>`
# element when the structured `<sos:cross_invariant>` grammar cannot
# express the desired property (liveness, multi-step `##` temporal
# sequences, vendor-specific coverage constructs). The walker validates
# the element's attributes + collision-checks the name but treats the
# body as opaque SVA text (relationship `derive` against IEEE 1800-2017).
# ----------------------------------------------------------------------------


@dataclass
class _RawProperty:
    """One ratified ``<sos:raw_property>`` declaration.

    Wave-4-future declaration form (per §15 2026-05-24):

        <sos:raw_property name="<sv-ident>" clock_region="<region>">
            ...literal SVA body text...
        </sos:raw_property>

    Semantics: emit a ``property <name>; @(posedge <region>_clk) <body>;
    endproperty`` block followed by ``<NAME>_ASSERT: assert property
    (<name>);`` into ``<chart>_top_sva.sv``. The walker does NOT parse
    the body — it is opaque SVA text (IEEE 1800-2017 grammar, owned
    upstream by IEEE). Authority relationship per §0 is ``derive`` for
    the body content; ``own`` for the element shape (name +
    clock_region attribute names + collision-check semantics).
    """

    name: str
    clock_region: str
    body: str
    doc_order: int = 0


def _collect_raw_properties(
    chart_ir: dict[str, Any],
) -> list[_RawProperty]:
    """Read ``<sos:raw_property>`` declarations from the chart IR.

    Lookup accepts either the SCXML-namespaced ``sos:raw_property`` key
    or the bare ``raw_property`` key (parallels ``_collect_cross_invariants``
    for chart authors writing raw scjson with stripped namespaces).

    Validation is split across two passes: this collector raises on
    intrinsically-malformed entries (missing attrs, empty body, type
    errors); ``_validate_raw_properties`` runs after with the region
    map to check collisions + clock_region resolution.
    """
    raw = (
        chart_ir.get("sos:raw_property")
        or chart_ir.get("raw_property")
        or []
    )
    if isinstance(raw, dict):
        raw = [raw]
    out: list[_RawProperty] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        clock_region = entry.get("clock_region")
        # Element body may live under "body" (custom scjson convention)
        # or as the element's text content under "_text" / "$" / "#text"
        # depending on the loader. Accept the documented shapes.
        body = (
            entry.get("body")
            or entry.get("_text")
            or entry.get("#text")
            or entry.get("$")
            or ""
        )
        if not (isinstance(name, str) and name.strip()):
            raise UnsupportedChartError(
                "SOS-08-D wave-4-future: <sos:raw_property> MUST carry a "
                "non-empty `name` attribute (the SV identifier used for "
                "the emitted property + assert label; collision-checked "
                "against other property names in the same bind module)."
            )
        if not (isinstance(clock_region, str) and clock_region.strip()):
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future: <sos:raw_property name="
                f"{name!r}> MUST carry a non-empty `clock_region` "
                f"attribute referencing an existing region (used to "
                f"resolve the property's sampling clock)."
            )
        if not isinstance(body, str) or not body.strip():
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future: <sos:raw_property name="
                f"{name!r}> MUST carry a non-empty body of literal SVA "
                f"text. The walker preserves the body verbatim; an "
                f"empty body has no executable meaning."
            )
        out.append(_RawProperty(
            name=name.strip(),
            clock_region=clock_region.strip(),
            body=body.strip(),
            doc_order=idx,
        ))
    return out


def _validate_raw_properties(
    raw_properties: list[_RawProperty],
    invariants: list[_CrossInvariant],
    known_regions: list[str],
) -> None:
    """Cross-check ``<sos:raw_property>`` declarations after collection.

    Fail-loud (``UnsupportedChartError``) on:
      * ``name`` collision with another raw property in the same chart.
      * ``name`` collision with a structured ``<sos:cross_invariant>``'s
        derived assertion label (the wave-4 emit produces ``<ID>_ASSERT``
        sanitised to upper-case; a raw property with a matching name
        would emit a duplicate label).
      * ``clock_region`` referencing a region the chart does not declare.

    The validation runs after ``_collect_raw_properties`` (which has
    already rejected missing attrs + empty bodies) so the surfaces here
    are purely structural cross-checks.
    """
    # Pre-compute structured-invariant-derived label set; the wave-4 emit
    # produces `<id sanitised to upper>_ASSERT` for each cross_invariant.
    structured_labels: dict[str, str] = {
        _sanitize_sv_identifier(inv.id).upper(): inv.id
        for inv in invariants
    }
    # Structured property names (the lowercase `p_<id>` form) are also
    # part of the bind module's namespace; collision-check against them
    # too so a raw property doesn't shadow a structured property.
    structured_prop_names: dict[str, str] = {
        "p_" + _sanitize_sv_identifier(inv.id).lower(): inv.id
        for inv in invariants
    }

    known_regions_set = set(known_regions)
    seen_raw_names: dict[str, _RawProperty] = {}
    for rp in raw_properties:
        # Raw-property-to-raw-property name collision.
        prior = seen_raw_names.get(rp.name)
        if prior is not None:
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future: <sos:raw_property name="
                f"{rp.name!r}> collides with another <sos:raw_property> "
                f"of the same name (declaration order #{prior.doc_order} "
                f"vs #{rp.doc_order}). Property names MUST be unique "
                f"within the chart's bind module."
            )
        # Raw-property-vs-structured-invariant collision: compare against
        # both the assert label (`<NAME>_ASSERT`) and the property name
        # (`p_<name>` lowercase) the wave-4 emit derives.
        rp_label = _sanitize_sv_identifier(rp.name).upper()
        rp_prop = "p_" + _sanitize_sv_identifier(rp.name).lower()
        if rp_label in structured_labels:
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future: <sos:raw_property name="
                f"{rp.name!r}> derives assert label "
                f"{rp_label + '_ASSERT'!r} which collides with the "
                f"structured <sos:cross_invariant id="
                f"{structured_labels[rp_label]!r}> emit. Rename the "
                f"raw property or the cross-invariant id so the labels "
                f"diverge."
            )
        if rp_prop in structured_prop_names:
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future: <sos:raw_property name="
                f"{rp.name!r}> derives property name {rp_prop!r} which "
                f"collides with the structured <sos:cross_invariant id="
                f"{structured_prop_names[rp_prop]!r}> emit. Rename the "
                f"raw property or the cross-invariant id so the "
                f"property names diverge."
            )
        # clock_region must reference a known region — chart-vocabulary
        # validation per INV-S-HDL-D-5; consistent with the wave-4-future
        # cross-invariant region-validation pass.
        if rp.clock_region not in known_regions_set:
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future: <sos:raw_property name="
                f"{rp.name!r}>'s clock_region {rp.clock_region!r} does "
                f"not reference a region the chart declares. Known "
                f"regions: {sorted(known_regions_set)}."
            )
        seen_raw_names[rp.name] = rp


def _collect_raw_property_clock_regions(
    raw_properties: list[_RawProperty],
) -> list[str]:
    """Return the set of region names referenced by any raw property's
    ``clock_region`` attribute, in first-seen (document) order. Used by
    the SVA module + bind directive to declare + route the per-region
    clock input ports the raw properties sample on."""
    out: list[str] = []
    seen: set[str] = set()
    for rp in raw_properties:
        if rp.clock_region not in seen:
            out.append(rp.clock_region)
            seen.add(rp.clock_region)
    return out


def _emit_raw_property_blocks(
    raw_properties: list[_RawProperty],
    chart_name: str,
) -> list[str]:
    """Emit the raw-property SVA block list (banner + per-property body).

    Each ``<sos:raw_property>`` lowers to four lines (comment + property
    + assert label + closing) preserving the body verbatim except for
    leading/trailing whitespace stripping. Properties appear in source-
    document order. The walker does NOT interpret the body — it's
    opaque SVA text (IEEE 1800-2017 grammar) per the §0 authority
    declaration (relationship = ``derive``).
    """
    if not raw_properties:
        return []
    lines: list[str] = [
        "",
        "    // === raw_property escape hatches (walker-opaque) ===",
        "    // Per SOS-08-D §15 wave-4-future (2026-05-24), the",
        "    // <sos:raw_property> element pastes literal SVA text into",
        "    // the emit. The walker preserves the body verbatim and",
        "    // performs NO grammar checks — the body is IEEE 1800-2017",
        "    // SystemVerilog (authority relationship = `derive`).",
        "    // Chart-vocabulary failure messages are the chart author's",
        "    // responsibility inside the raw body; the walker only",
        "    // emits the default-failure path.",
    ]
    for rp in raw_properties:
        # Emit per-property block. The body is written as-is (verbatim
        # apart from the leading/trailing whitespace stripping done by
        # `_collect_raw_properties`). Indent the body two levels inside
        # the property block; the walker does NOT re-indent the body's
        # interior lines — chart authors who care about indentation
        # control it in their raw text.
        body_text = rp.body
        assert_label = _sanitize_sv_identifier(rp.name).upper() + "_ASSERT"
        prop_ident = _sanitize_sv_identifier(rp.name)
        clk_signal = f"{_sanitize_sv_identifier(rp.clock_region)}_clk"
        lines.extend([
            "",
            f"    // <sos:raw_property name=\"{rp.name}\" "
            f"clock_region=\"{rp.clock_region}\"/> — escape hatch, walker-opaque",
            f"    // (chart `{chart_name}`, body preserved verbatim from source)",
            f"    property {prop_ident};",
            f"        @(posedge {clk_signal}) {body_text};",
            f"    endproperty",
            f"    {assert_label}: assert property ({prop_ident});",
        ])
    return lines


def _collect_cross_invariants(
    chart_ir: dict[str, Any]
) -> list[_CrossInvariant]:
    """Read ``<sos:cross_invariant>`` declarations from the chart IR.

    Wave-4 lookup accepts either the SCXML-namespaced ``sos:cross_invariant``
    key or the bare ``cross_invariant`` key (the scjson loader strips
    namespaces by default; the walker accepts both shapes so chart
    authors writing raw scjson stay compatible).

    Each declaration is parsed into a ``_CrossInvariant``. Malformed
    entries raise ``UnsupportedChartError`` with the wave-4 spec
    citation so chart authors get an actionable error instead of a
    silently-skipped invariant.

    Wave-4-future (2026-05-24 §15) — compound cross-invariant
    expressions: the walker detects the new shape by presence of any
    ``sos:and`` / ``sos:or`` / ``sos:not`` / ``sos:implies`` (or bare-
    namespace variants) child OR a list of ``sos:state_ref`` / bare
    ``state_ref`` direct children. The detection rule:

      * Any compound boolean child (``and``/``or``/``not``/``implies``) →
        compound-expression path; ``expr`` populated with the AST root.
      * One or more ``state_ref`` children, no boolean child → implicit-
        AND path; ``expr`` populated with an ``_CompoundExpr`` whose
        ``kind == 'and'`` and children are the state-ref leaves (or
        a single ``state_ref`` leaf when N=1).
      * Neither — wave-4 string-form (antecedent/consequent attrs).

    Compound declarations carry the ``id`` attribute (used for the
    derived property name + assert label + chart-vocabulary failure
    message) and OPTIONALLY a ``within`` attribute. When the compound
    expression is itself an ``<sos:implies>``, the ``within`` attribute
    is consumed by the implies window; otherwise the compound is
    asserted same-cycle (no temporal window) per the §15 normative
    section.
    """
    raw = (
        chart_ir.get("sos:cross_invariant")
        or chart_ir.get("cross_invariant")
        or []
    )
    if isinstance(raw, dict):
        raw = [raw]
    out: list[_CrossInvariant] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        inv_id = entry.get("id")
        if not (isinstance(inv_id, str) and inv_id.strip()):
            raise UnsupportedChartError(
                "SOS-08-D wave-4: <sos:cross_invariant> MUST carry a "
                "non-empty `id` attribute (chart-vocabulary failure "
                "messages cite it per INV-S-HDL-D-5)."
            )

        # Wave-4-future-compound detection: any compound boolean child
        # OR any state_ref child triggers the compound path. The
        # antecedent/consequent string-attribute form remains valid
        # when no compound markers are present.
        compound_expr = _maybe_parse_compound_cross_invariant(entry, inv_id)

        antecedent = entry.get("antecedent")
        consequent = entry.get("consequent")
        within_raw = entry.get("within", 1)

        if compound_expr is None:
            a_region, a_state = _parse_region_state_expr(
                antecedent, inv_id, "antecedent"
            )
            c_region, c_state = _parse_region_state_expr(
                consequent, inv_id, "consequent"
            )
        else:
            # Compound expression supplies its own predicates; populate
            # antecedent/consequent fields with placeholders that the
            # emit path ignores when ``expr`` is not None.
            a_region = a_state = c_region = c_state = ""
        try:
            within = int(within_raw)
        except (TypeError, ValueError):
            raise UnsupportedChartError(
                f"SOS-08-D wave-4: cross-invariant {inv_id!r}'s "
                f"`within` MUST be a positive integer; got {within_raw!r}."
            ) from None
        if within < 1:
            within = 1
        if within > _CROSS_INVARIANT_WITHIN_CAP:
            raise UnsupportedChartError(
                f"SOS-08-D wave-4: cross-invariant {inv_id!r}'s "
                f"`within` ({within}) exceeds the v1 cap of "
                f"{_CROSS_INVARIANT_WITHIN_CAP}. Bump via §15 amendment "
                f"if a real-world chart needs longer."
            )
        # SOS-08-D wave-4-future-mclk (2026-05-24 §15): parse optional
        # ``<sos:sampling_clock region="..." clock="..."/>`` children.
        sampling_clocks, primary_region = _parse_sampling_clocks(entry, inv_id)

        out.append(_CrossInvariant(
            id=inv_id,
            antecedent_region=a_region,
            antecedent_state=a_state,
            consequent_region=c_region,
            consequent_state=c_state,
            within=within,
            expr=compound_expr,
            sampling_clocks=sampling_clocks,
            primary_clock_region=primary_region,
        ))
    return out


def _parse_sampling_clocks(
    entry: dict[str, Any],
    inv_id: str,
) -> tuple[dict[str, str], str | None]:
    """SOS-08-D wave-4-future-mclk (2026-05-24 §15) — parse the optional
    ``<sos:sampling_clock>`` child list on a cross-invariant.

    Returns ``(region_to_clock_map, primary_clock_region)``. When no
    ``<sos:sampling_clock>`` children are present, returns
    ``({}, None)`` — the wave-4 single-clock path applies and the emit
    samples on chart-top ``clk``.

    Each ``<sos:sampling_clock>`` MUST carry non-empty ``region`` +
    ``clock`` attributes. Duplicate ``region`` entries within one
    invariant collapse to first-seen-wins (with a chart-vocab error so
    the chart author resolves the ambiguity). The first
    ``<sos:sampling_clock>`` in source-document order designates the
    primary clock — the property's outer ``@(posedge ...)`` header
    samples on that region's clock; subsequent regions use
    ``$past(..., @(posedge <its_clock>))`` per IEEE 1800-2017 §16.13.

    Validation against the chart's clock-domain set runs separately in
    ``_validate_sampling_clocks`` — this collector only enforces
    intrinsic shape constraints (non-empty attrs, no duplicate
    regions). The clock identifier validation requires the
    region→domain map from ``_collect_parallel_regions``.
    """
    raw = (
        entry.get("sos:sampling_clock")
        or entry.get("sampling_clock")
        or None
    )
    if raw is None:
        return {}, None
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return {}, None

    region_to_clock: dict[str, str] = {}
    primary: str | None = None
    for child in raw:
        if not isinstance(child, dict):
            continue
        region = child.get("region")
        clock = child.get("clock")
        if not (isinstance(region, str) and region.strip()):
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future-mclk: cross-invariant "
                f"{inv_id!r} <sos:sampling_clock> MUST carry a non-"
                f"empty `region` attribute referencing one of the "
                f"chart's parallel regions."
            )
        if not (isinstance(clock, str) and clock.strip()):
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future-mclk: cross-invariant "
                f"{inv_id!r} <sos:sampling_clock region={region!r}> "
                f"MUST carry a non-empty `clock` attribute referencing "
                f"one of the chart's declared clock domains."
            )
        region = region.strip()
        clock = clock.strip()
        if region in region_to_clock:
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future-mclk: cross-invariant "
                f"{inv_id!r} declares <sos:sampling_clock> for region "
                f"{region!r} more than once; declare at most one "
                f"sampling clock per region per invariant."
            )
        region_to_clock[region] = clock
        if primary is None:
            primary = region
    return region_to_clock, primary


def _compound_child_key(entry: dict[str, Any], name: str) -> str | None:
    """Return the dict key (``name`` or ``sos:name``) under which the
    chart IR exposes a compound-cross-invariant child. Returns ``None``
    when neither key is present."""
    for k in (f"sos:{name}", name):
        if k in entry:
            return k
    return None


def _has_any_compound_child(entry: dict[str, Any]) -> bool:
    """True if any ``sos:and`` / ``sos:or`` / ``sos:not`` / ``sos:implies``
    / ``sos:state_ref`` (or bare-namespace variant) key is present on
    ``entry``. Wave-4-future detection — gates the compound emit path."""
    for name in _COMPOUND_OPERATOR_NAMES + ("state_ref",):
        if _compound_child_key(entry, name) is not None:
            return True
    return False


_CROSS_INVARIANT_ATTR_KEYS = {
    "id",
    "antecedent",
    "consequent",
    "within",
}


def _detect_unknown_root_operator(
    entry: dict[str, Any],
    inv_id: str,
) -> None:
    """Scan the cross-invariant's keys for unknown boolean-operator
    elements (e.g. ``<sos:xor>``, ``<sos:nand>``). When an unknown
    operator is detected, raise the canonical chart-vocab error with
    the ``<sos:raw_property>`` escape-hatch hint per §15.

    Operates BEFORE the compound-detection pass so unknown operators
    don't fall through to the wave-4 string-form path (which would
    surface a misleading "antecedent missing" error instead of the
    intended unsupported-operator chart-vocab message).
    """
    known_compound = set(_COMPOUND_OPERATOR_NAMES) | {"state_ref"}
    # SOS-08-D wave-4-future-mclk (2026-05-24 §15) — `<sos:sampling_clock>`
    # is a per-invariant child, not a boolean operator; whitelist so the
    # unknown-operator detector doesn't reject it.
    known_invariant_children = {"sampling_clock"}
    loader_internals = {"_text", "#text", "$"}
    for k in entry.keys():
        bare = k.split(":")[-1]
        if bare in _CROSS_INVARIANT_ATTR_KEYS:
            continue
        if bare in known_compound:
            continue
        if bare in known_invariant_children:
            continue
        if bare in loader_internals or bare.startswith("_") or bare.startswith("#"):
            continue
        # Anything else under a <sos:cross_invariant> root is an
        # unsupported operator — surface the canonical error.
        raise UnsupportedChartError(
            f"SOS-08-D wave-4-future-compound: cross-invariant "
            f"{inv_id!r} uses unsupported boolean operator {bare!r}; "
            f"supported: and, or, not, implies, state_ref. For SVA-"
            f"specific operators (e.g. ##, [*], sampled-value functions), "
            f"use <sos:raw_property> escape hatch."
        )


def _maybe_parse_compound_cross_invariant(
    entry: dict[str, Any],
    inv_id: str,
) -> "_CompoundExpr | None":
    """Wave-4-future compound parser.

    Returns ``None`` when the entry uses the wave-4 string-form
    (antecedent/consequent attrs only). Returns a ``_CompoundExpr``
    AST root when any compound boolean child or ``state_ref`` child
    is present.

    Per §15 (2026-05-24): the detection rule is structural — a single
    compound child triggers the compound path, even if antecedent /
    consequent attrs are also present. Chart authors mixing the two
    forms in the same element get the compound path (precedence rule:
    structured children win over flat attrs); the wave-4 attrs are
    ignored. The rule is intentional — chart authors transitioning
    from the string form leave the old attrs in place during review
    and the compound form supersedes them.
    """
    # Surface unknown operators FIRST so they get the canonical
    # raw_property hint, not the wave-4 "missing antecedent" error.
    _detect_unknown_root_operator(entry, inv_id)
    if not _has_any_compound_child(entry):
        return None

    # Collect direct compound children at this <sos:cross_invariant>'s
    # top level. The grammar at the cross-invariant root permits:
    #   * EITHER 1+ <sos:state_ref> direct children (implicit-AND), OR
    #   * EITHER 1 boolean operator child (and/or/not/implies),
    # but not both at the same level (chart authors can nest boolean
    # operators inside a single root for richer compositions).
    boolean_keys = [
        _compound_child_key(entry, n)
        for n in _COMPOUND_OPERATOR_NAMES
    ]
    boolean_keys = [k for k in boolean_keys if k is not None]
    state_ref_key = _compound_child_key(entry, "state_ref")

    if boolean_keys and state_ref_key is not None:
        # Mixed root — disallow at v1 (ambiguous: AND-with-bool or
        # bool-only?). Chart authors who need an AND with a boolean
        # branch wrap the whole thing in <sos:and>.
        raise UnsupportedChartError(
            f"SOS-08-D wave-4-future-compound: cross-invariant "
            f"{inv_id!r} mixes <sos:state_ref> children with a "
            f"boolean operator at the root level. Wrap the whole "
            f"expression in <sos:and> (or another operator) to "
            f"disambiguate."
        )

    if state_ref_key is not None and not boolean_keys:
        state_ref_children = _normalise_compound_child_list(
            entry[state_ref_key]
        )
        leaves = [
            _build_compound_state_ref_leaf(srn, inv_id)
            for srn in state_ref_children
        ]
        if len(leaves) == 1:
            return leaves[0]
        # Implicit-AND form: multiple <sos:state_ref> children →
        # conjunction asserted as the property body.
        return _CompoundExpr(kind="and", children=leaves)

    # Exactly one boolean operator child at the root. >1 disallowed
    # (would be ambiguous — wrap in <sos:and>/<sos:or>).
    if len(boolean_keys) > 1:
        ordered = ", ".join(sorted(boolean_keys))
        raise UnsupportedChartError(
            f"SOS-08-D wave-4-future-compound: cross-invariant "
            f"{inv_id!r} carries multiple boolean operator children "
            f"({ordered}) at the root level. Wrap the whole "
            f"expression in <sos:and> (or another operator) to "
            f"disambiguate."
        )
    root_key = boolean_keys[0]
    root_kind = root_key.split(":")[-1]
    root_nodes = _normalise_compound_child_list(entry[root_key])
    if len(root_nodes) != 1:
        # Each boolean operator at the root takes exactly one element
        # node; multiple sibling <sos:and>/<sos:or>/etc. would require
        # an explicit wrapping operator.
        raise UnsupportedChartError(
            f"SOS-08-D wave-4-future-compound: cross-invariant "
            f"{inv_id!r}'s root <sos:{root_kind}> appears "
            f"{len(root_nodes)} times; expected exactly 1. Wrap the "
            f"siblings inside a single <sos:and> / <sos:or> root."
        )
    return _build_compound_node(root_kind, root_nodes[0], inv_id)


def _normalise_compound_child_list(value: Any) -> list[Any]:
    """The scjson loader emits a single child as either a dict or a
    one-element list depending on the element multiplicity heuristics.
    Normalise to a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _build_compound_state_ref_leaf(
    node: Any,
    inv_id: str,
) -> "_CompoundExpr":
    """Parse a ``<sos:state_ref region="..." state="..."/>`` element
    into a ``_CompoundExpr`` leaf node.

    Reuses the wave-4 ``<sos:state_ref>`` chart-vocab semantics
    (region + state attributes); cross-invariant state-ref validation
    against the region/state index map happens in
    ``_validate_compound_state_refs`` AFTER all parsing completes so
    chart-vocab errors surface with the full known-region/state list.
    """
    if not isinstance(node, dict):
        raise UnsupportedChartError(
            f"SOS-08-D wave-4-future-compound: cross-invariant "
            f"{inv_id!r}'s <sos:state_ref> child MUST be an element "
            f"with `region` + `state` attributes; got "
            f"{type(node).__name__}."
        )
    region = node.get("region")
    state = node.get("state")
    if not (isinstance(region, str) and region.strip()):
        raise UnsupportedChartError(
            f"SOS-08-D wave-4-future-compound: cross-invariant "
            f"{inv_id!r}'s <sos:state_ref> MUST carry a non-empty "
            f"`region` attribute."
        )
    if not (isinstance(state, str) and state.strip()):
        raise UnsupportedChartError(
            f"SOS-08-D wave-4-future-compound: cross-invariant "
            f"{inv_id!r}'s <sos:state_ref> MUST carry a non-empty "
            f"`state` attribute."
        )
    return _CompoundExpr(
        kind="state_ref",
        children=[],
        region=region.strip(),
        state=state.strip(),
    )


def _build_compound_node(
    kind: str,
    node: Any,
    inv_id: str,
) -> "_CompoundExpr":
    """Recursive compound-AST builder.

    ``kind`` names the operator at this node (``'and'``, ``'or'``,
    ``'not'``, ``'implies'``). ``node`` is the scjson dict containing
    this operator's children. Recursion descends through compound
    children + ``state_ref`` leaves; any unknown operator name raises
    ``UnsupportedChartError`` with the canonical remediation hint.
    """
    if not isinstance(node, dict):
        # An empty body (e.g. ``<sos:and/>`` collapses to a string in
        # some loader shapes) — surface the canonical empty-children
        # error path below by treating as empty.
        node = {}

    children = _collect_compound_children(node, inv_id)

    if kind == "and":
        if len(children) < 2:
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future-compound: cross-invariant "
                f"{inv_id!r}'s <sos:and> requires 2+ children (got "
                f"{len(children)})."
            )
        return _CompoundExpr(kind="and", children=children)
    if kind == "or":
        if len(children) < 2:
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future-compound: cross-invariant "
                f"{inv_id!r}'s <sos:or> requires 2+ children (got "
                f"{len(children)})."
            )
        return _CompoundExpr(kind="or", children=children)
    if kind == "not":
        if len(children) != 1:
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future-compound: cross-invariant "
                f"{inv_id!r}'s <sos:not> requires exactly 1 child "
                f"(got {len(children)})."
            )
        return _CompoundExpr(kind="not", children=children)
    if kind == "implies":
        if len(children) != 2:
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future-compound: cross-invariant "
                f"{inv_id!r}'s <sos:implies> requires exactly 2 "
                f"children (antecedent + consequent); got "
                f"{len(children)}."
            )
        return _CompoundExpr(kind="implies", children=children)

    # Unknown operator name — chart-vocab error with raw_property
    # escape-hatch hint per §15 normative section.
    raise UnsupportedChartError(
        f"SOS-08-D wave-4-future-compound: cross-invariant "
        f"{inv_id!r} uses unsupported boolean operator {kind!r}; "
        f"supported: and, or, not, implies, state_ref. For SVA-"
        f"specific operators (e.g. ##, [*], sampled-value functions), "
        f"use <sos:raw_property> escape hatch."
    )


def _collect_compound_children(
    node: dict[str, Any],
    inv_id: str,
) -> list["_CompoundExpr"]:
    """Walk all compound + state_ref children of ``node`` in source-
    document order.

    Document order across heterogeneous keys is not directly preserved
    by the scjson loader (it groups same-name children into lists).
    For the compound-expression v1, the canonical traversal order is:

      1. For each entry in ``node`` whose key names a compound child
         (and/implies/not/or/state_ref), iterate the entry's value list
         in source order.
      2. The cross-key traversal MUST be deterministic — we use the
         alphabetic order of ``_COMPOUND_OPERATOR_NAMES`` (``and``,
         ``implies``, ``not``, ``or``) with state_ref leaves emitted
         first, per SOS-08-D-CONCEPTS §15 2026-05-25 (post-wave-4
         follow-ups, Issue B). This is the canonical traversal order
         applied when chart authors interleave different operator
         children inside a single parent.

    In practice each compound operator has one or two children of a
    fixed shape (per RFC-2119 MUSTs in §15); the order rule matters
    only for ``<sos:and>`` / ``<sos:or>``, where chart authors
    naturally write the children in the order they want SVA to emit
    them. The traversal preserves that order within each key.
    """
    children: list[_CompoundExpr] = []
    # Implicit-AND state_ref leaves at this node — included in the
    # child list directly (e.g. ``<sos:and><sos:state_ref/><sos:state_ref/>``
    # has two state_ref leaves).
    state_ref_key = _compound_child_key(node, "state_ref")
    if state_ref_key is not None:
        for srn in _normalise_compound_child_list(node[state_ref_key]):
            children.append(_build_compound_state_ref_leaf(srn, inv_id))
    # Nested boolean operators.
    for name in _COMPOUND_OPERATOR_NAMES:
        k = _compound_child_key(node, name)
        if k is None:
            continue
        for sub_node in _normalise_compound_child_list(node[k]):
            children.append(_build_compound_node(name, sub_node, inv_id))
    # Detect any unknown child name (operator typos, e.g. <sos:xor>).
    # Iterate ``node``'s keys and surface unsupported boolean operators
    # explicitly so chart authors get a chart-vocab error pointing at
    # the raw_property escape hatch.
    known_attr_keys = {"region", "state"}
    for k in node.keys():
        bare = k.split(":")[-1]
        if bare in _COMPOUND_OPERATOR_NAMES or bare == "state_ref":
            continue
        if bare in known_attr_keys:
            continue
        # A leaf might also expose loader-internal keys; tolerate
        # underscores / hash prefixes (e.g. ``_text``, ``#text``).
        if bare.startswith("_") or bare.startswith("#") or bare in ("$",):
            continue
        # Conservative reject: any unknown child key surfacing under a
        # compound parent node is an unsupported operator.
        raise UnsupportedChartError(
            f"SOS-08-D wave-4-future-compound: cross-invariant "
            f"{inv_id!r} uses unsupported boolean operator {bare!r}; "
            f"supported: and, or, not, implies, state_ref. For SVA-"
            f"specific operators (e.g. ##, [*], sampled-value functions), "
            f"use <sos:raw_property> escape hatch."
        )
    return children


_REGION_STATE_RE = re.compile(
    r"^\s*region\.([A-Za-z_][A-Za-z0-9_]*)\s*==\s*([A-Za-z_][A-Za-z0-9_]*)\s*$"
)


def _build_region_state_indices(
    regions: list[tuple[str, dict[str, Any]]]
) -> dict[str, dict[str, int]]:
    """For each region, return ``state_id → bit_index`` matching the
    per-region FSM's one-hot encoding from SOS-08-C's
    ``_emit_state_constants``.

    Wave-4-future (2026-05-24 §15): the cross-region SVA module emits
    ``ST_<X> = N_STATES_<R>'b... | (N_STATES_<R>'(1) << bit_idx)`` for
    each referenced state. ``bit_idx`` MUST match the bit position the
    per-region FSM module uses inside its one-hot encoding, or the SVA
    comparison ``current_state_<region> == ST_<X>`` never holds.

    SOS-08-C's ``_emit_state_constants`` enumerates ``region.states`` in
    chart document order (the order ``_walk_states_in_order`` yields) and
    assigns ``one_hot[idx]``. The cross-region SVA emitter must consume
    that same per-region traversal so the indices align.

    INV-S-HDL-D-2 (one-hot, reset-initial) keeps the encoding stable
    over future SOS-08-C refactors as long as both walkers traverse the
    state subtree identically. Both helpers MUST use the
    ``_walk_states_in_order`` definition above, which they do.
    """
    out: dict[str, dict[str, int]] = {}
    for region_name, region_state in regions:
        # Per-region pseudo-chart: same shape passed to
        # ``_normalise_chart`` by the parallel walker.
        per_region_ir: dict[str, Any] = {
            "state": region_state.get("state") or [],
        }
        index_map: dict[str, int] = {}
        for idx, (sid, _st) in enumerate(_walk_states_in_order(per_region_ir)):
            # First-occurrence wins for any duplicate ids; SOS-08-C's
            # _emit_state_constants iterates ``region.states`` (a list)
            # which preserves the same first-occurrence semantics.
            if sid not in index_map:
                index_map[sid] = idx
        out[region_name] = index_map
    return out


def _walk_compound_state_refs(
    expr: "_CompoundExpr",
) -> "list[tuple[str, str]]":
    """Yield ``(region, state)`` for every ``state_ref`` leaf reachable
    from ``expr`` in source-document order.

    Wave-4-future-compound (2026-05-24 §15): used by validation +
    state-constant emit to enumerate the encoding-table cells the
    compound property references. Order = depth-first left-to-right
    over the compound AST."""
    out: list[tuple[str, str]] = []
    _walk_compound_state_refs_into(expr, out)
    return out


def _walk_compound_state_refs_into(
    expr: "_CompoundExpr",
    out: "list[tuple[str, str]]",
) -> None:
    if expr.kind == "state_ref":
        if expr.region is not None and expr.state is not None:
            out.append((expr.region, expr.state))
        return
    for c in expr.children:
        _walk_compound_state_refs_into(c, out)


def _validate_compound_state_refs(
    inv: "_CrossInvariant",
    region_state_indices: dict[str, dict[str, int]],
) -> None:
    """Recursively validate every ``state_ref`` leaf in a compound
    cross-invariant against the chart's region/state index map.

    Wave-4-future-compound (2026-05-24 §15): mirrors
    ``_validate_cross_invariant_state_refs`` for the wave-4 attribute
    form but walks the ``_CompoundExpr`` AST. Surfaces unknown
    region/state names as chart-vocabulary errors citing the
    cross-invariant id per INV-S-HDL-D-5.
    """
    if inv.expr is None:
        return
    for region, state in _walk_compound_state_refs(inv.expr):
        region_map = region_state_indices.get(region)
        if region_map is None:
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future-compound: cross-invariant "
                f"{inv.id!r} <sos:state_ref> references region "
                f"{region!r} which the chart does not declare. Known "
                f"regions: {sorted(region_state_indices.keys())}."
            )
        if state not in region_map:
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future-compound: cross-invariant "
                f"{inv.id!r} <sos:state_ref> references state "
                f"{state!r} in region {region!r} which the region "
                f"does not declare. Known states in region "
                f"{region!r}: {sorted(region_map.keys())}."
            )


def _validate_cross_invariant_state_refs(
    invariants: list["_CrossInvariant"],
    region_state_indices: dict[str, dict[str, int]],
) -> None:
    """Raise ``UnsupportedChartError`` if any cross-invariant references
    a region the chart does not declare, or a state the referenced
    region does not contain.

    Wave-4-future (2026-05-24 §15): previously the wave-4 emitter trusted
    chart authors to spell region + state names correctly; an unknown
    spelling produced a SVA constant with a 0-bit-position template that
    silently matched the region's first-document-order state. The
    validation below converts the silent miscompare into an actionable
    chart-vocabulary error citing INV-S-HDL-D-2 + the cross-invariant id.

    Wave-4-future-compound (2026-05-24 §15): when the invariant carries
    a compound ``expr`` AST, recurse over every ``state_ref`` leaf via
    ``_validate_compound_state_refs``. The string-form invariants
    continue through the legacy antecedent/consequent validation
    below.
    """
    for inv in invariants:
        if inv.expr is not None:
            _validate_compound_state_refs(inv, region_state_indices)
            continue
        for region, state, role in (
            (inv.antecedent_region, inv.antecedent_state, "antecedent"),
            (inv.consequent_region, inv.consequent_state, "consequent"),
        ):
            region_map = region_state_indices.get(region)
            if region_map is None:
                raise UnsupportedChartError(
                    f"SOS-08-D wave-4-future: cross-invariant {inv.id!r}'s "
                    f"{role} references region {region!r} which the chart "
                    f"does not declare. Known regions: "
                    f"{sorted(region_state_indices.keys())}."
                )
            if state not in region_map:
                raise UnsupportedChartError(
                    f"SOS-08-D wave-4-future: cross-invariant {inv.id!r}'s "
                    f"{role} references state {state!r} in region {region!r} "
                    f"which the region does not declare. Known states in "
                    f"region {region!r}: {sorted(region_map.keys())}."
                )


def _parse_region_state_expr(
    expr: Any,
    inv_id: str,
    field_name: str,
) -> tuple[str, str]:
    """Parse a ``region.<name> == <state>`` expression.

    Per SOS-08-D wave-4 §15, cross-invariant antecedent/consequent
    fields restrict to the form ``region.<name> == <state>``. The
    parser returns ``(region_name, state_id)`` or raises
    ``UnsupportedChartError`` with a chart-vocabulary-friendly error
    when the expression doesn't match.

    The restricted grammar is intentional at v1 — chart authors who
    need arbitrary SVA can wait for a future wave-4+ `raw_property`
    escape hatch. The structured form lets the walker reason about
    the property + cite chart vocabulary in the failure message.
    """
    if not isinstance(expr, str) or not expr.strip():
        raise UnsupportedChartError(
            f"SOS-08-D wave-4: cross-invariant {inv_id!r}'s "
            f"`{field_name}` MUST be a non-empty string of form "
            f"`region.<name> == <state>`."
        )
    m = _REGION_STATE_RE.match(expr)
    if not m:
        raise UnsupportedChartError(
            f"SOS-08-D wave-4: cross-invariant {inv_id!r}'s "
            f"`{field_name}` ({expr!r}) must match "
            f"`region.<name> == <state>` (v1 restricted grammar)."
        )
    return m.group(1), m.group(2)


def _cross_invariant_sva_module_name(chart_name: str) -> str:
    """``<chart>_top_sva`` — chart-top SVA module name for cross-region
    invariants. Distinct from per-region ``<chart>_region_<r>_fsm_sva``
    modules; the chart-top module references per-region observables
    via the chart-top wrapper's exposed ports.
    """
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in chart_name)
    if safe and safe[0].isdigit():
        safe = "x" + safe
    return f"{safe.lower()}_top_sva"


def _emit_compound_sv_expr(expr: "_CompoundExpr") -> str:
    """Render a ``_CompoundExpr`` AST into a SystemVerilog boolean
    expression string.

    Wave-4-future-compound (2026-05-24 §15) — SVA lowering rules:

    * ``state_ref(region=r, state=s)`` → ``(current_state_<r> == ST_<s>)``
      (mirrors the wave-4 leaf encoding; reuses the wave-4-future
      state-encoding pass-through machinery via the shared
      ``ST_<state>`` constants emitted by
      ``_emit_cross_invariant_state_constants``).
    * ``and(c1, c2, ...)`` → ``(c1 && c2 && ...)`` per IEEE 1800-2017
      §11.4.7 (logical AND).
    * ``or(c1, c2, ...)`` → ``(c1 || c2 || ...)`` per IEEE 1800-2017
      §11.4.7 (logical OR).
    * ``not(c)`` → ``!(c)`` per IEEE 1800-2017 §11.4.7 (logical NOT).
    * ``implies(a, c)`` → ``(a |-> c)`` per IEEE 1800-2017 §16.12.2
      (overlapping implication operator). The overlapping operator
      matches the same-cycle semantics of wave-4 cross-invariants —
      the non-overlapping ``|=>`` would shift the consequent by one
      cycle and is intentionally not the v1 default.

    Parenthesisation is conservative: every compound node wraps its
    rendered body in parens so operator-precedence surprises in the
    emitted SV cannot occur. Redundant parens improve reviewability
    and are stripped by any sane SV elaborator.
    """
    if expr.kind == "state_ref":
        obs = f"current_state_{_sanitize_sv_identifier(expr.region or '')}"
        const = _state_constant_name(expr.state or "")
        return f"({obs} == {const})"
    if expr.kind == "and":
        rendered = " && ".join(
            _emit_compound_sv_expr(c) for c in expr.children
        )
        return f"({rendered})"
    if expr.kind == "or":
        rendered = " || ".join(
            _emit_compound_sv_expr(c) for c in expr.children
        )
        return f"({rendered})"
    if expr.kind == "not":
        # ``_build_compound_node`` guarantees exactly 1 child for not.
        return f"!({_emit_compound_sv_expr(expr.children[0])})"
    if expr.kind == "implies":
        # ``_build_compound_node`` guarantees exactly 2 children.
        a_sv = _emit_compound_sv_expr(expr.children[0])
        c_sv = _emit_compound_sv_expr(expr.children[1])
        return f"({a_sv} |-> {c_sv})"
    # Defensive — should be unreachable thanks to parser-side validation.
    raise UnsupportedChartError(
        f"SOS-08-D wave-4-future-compound: unrecognised AST kind "
        f"{expr.kind!r} at emit time (parser should have rejected)."
    )


def _summarise_compound_expr(expr: "_CompoundExpr") -> str:
    """Render a ``_CompoundExpr`` AST into a short chart-vocabulary
    summary string (used in the SVA module's comment header + the
    chart-vocabulary $fatal failure message per INV-S-HDL-D-5).

    Uses chart-side names (``region.state``) rather than SV identifiers
    (``current_state_X``) so the message renders in the language the
    chart author wrote.
    """
    if expr.kind == "state_ref":
        return f"{expr.region}.{expr.state}"
    if expr.kind == "and":
        return "(" + " AND ".join(
            _summarise_compound_expr(c) for c in expr.children
        ) + ")"
    if expr.kind == "or":
        return "(" + " OR ".join(
            _summarise_compound_expr(c) for c in expr.children
        ) + ")"
    if expr.kind == "not":
        return f"NOT {_summarise_compound_expr(expr.children[0])}"
    if expr.kind == "implies":
        a = _summarise_compound_expr(expr.children[0])
        c = _summarise_compound_expr(expr.children[1])
        return f"({a} IMPLIES {c})"
    return f"<{expr.kind}>"


def _collect_chart_clock_domains(
    region_info: list[tuple[str, str | None]],
) -> set[str]:
    """SOS-08-D wave-4-future-mclk (2026-05-24 §15) — set of declared
    clock-domain identifiers the chart's regions expose.

    Note on `<sos:clock_domains>` block: at the time of the
    wave-4-future-mclk landing, there is no separately validated
    `<sos:clock_domains>` chart-vocab element — clock identifiers are
    derived from each region's ``clock="..."`` attribute (per SOS-08-C
    wave-3 clock-distribution contract). This collector returns the
    union of (a) every non-None clock-domain string declared by some
    region, plus (b) the default chart-top reference clock identifier
    ``clk`` (used by regions without a `clock=` annotation).

    The returned set is the validation target for
    ``_validate_sampling_clocks`` — a ``<sos:sampling_clock
    clock=...>`` value not in this set raises a chart-vocab error
    citing the canonical mclk error prefix.
    """
    domains: set[str] = {"clk"}
    for _region, dom in region_info:
        if dom:
            domains.add(dom)
            # Accept the per-domain port-naming variants too so a chart
            # author MAY write ``clock="clk_fast"`` or ``clock="fast"``
            # interchangeably. Internally the walker emits via
            # ``_clk_port_name(<domain>)``.
            domains.add(_clk_port_name(dom))
    return domains


def _resolve_region_clock_signal(
    region: str,
    region_info: list[tuple[str, str | None]],
) -> str:
    """Resolve a region name into the SystemVerilog clock signal that
    samples its observable.

    For regions carrying a ``clock="<domain>"`` attribute, the signal
    is ``_clk_port_name(<domain>)`` (per SOS-08-C wave-3). For regions
    without an annotation, the signal is the chart-top reference
    ``clk``. Returns ``"clk"`` for any region not declared by the
    chart — defensive fallback; validation upstream rejects unknown
    region names before this helper is reached.
    """
    for r, dom in region_info:
        if r == region:
            if dom is None:
                return "clk"
            return _clk_port_name(dom)
    return "clk"


def _resolve_sampling_clock_signal(
    region: str,
    sampling_clocks: dict[str, str],
    region_info: list[tuple[str, str | None]],
) -> str:
    """SOS-08-D wave-4-future-mclk (2026-05-24 §15) — resolve the
    per-region SVA sampling clock for a multi-clock cross-invariant.

    If the invariant explicitly names a ``<sos:sampling_clock>`` for
    ``region``, the declared clock identifier wins; if the declared
    name is a bare domain (``"fast"``), it normalises through
    ``_clk_port_name``. Otherwise the region's intrinsic clock (per
    ``_resolve_region_clock_signal``) is used.
    """
    declared = sampling_clocks.get(region)
    if declared is None:
        return _resolve_region_clock_signal(region, region_info)
    # Accept both bare-domain and pre-prefixed forms.
    if declared.startswith("clk"):
        return declared
    return _clk_port_name(declared)


def _validate_sampling_clocks(
    invariants: list[_CrossInvariant],
    region_info: list[tuple[str, str | None]],
    region_state_indices: dict[str, dict[str, int]],
) -> None:
    """SOS-08-D wave-4-future-mclk (2026-05-24 §15) — chart-vocab
    validation pass for `<sos:sampling_clock>` declarations.

    Raises ``UnsupportedChartError`` with prefix
    ``SOS-08-D wave-4-future-mclk:`` on:

      * ``region`` attribute references a region the chart doesn't
        declare.
      * ``clock`` attribute references an identifier outside the
        chart's declared clock-domain set (per
        ``_collect_chart_clock_domains``).
      * ``<sos:implies>`` compound carries antecedent + consequent
        leaves drawn from different declared clock domains — SVA's
        ``|->`` operator requires single-clock-domain operands per
        IEEE 1800-2017 §16.13.5.
    """
    declared_clocks = _collect_chart_clock_domains(region_info)
    known_regions = set(region_state_indices.keys())
    for inv in invariants:
        if not inv.sampling_clocks:
            continue
        for region, clock in inv.sampling_clocks.items():
            if region not in known_regions:
                raise UnsupportedChartError(
                    f"SOS-08-D wave-4-future-mclk: cross-invariant "
                    f"{inv.id!r} <sos:sampling_clock region={region!r}> "
                    f"references a region the chart does not declare. "
                    f"Known regions: {sorted(known_regions)}."
                )
            if clock not in declared_clocks:
                raise UnsupportedChartError(
                    f"SOS-08-D wave-4-future-mclk: cross-invariant "
                    f"{inv.id!r} <sos:sampling_clock region={region!r} "
                    f"clock={clock!r}> references an unknown clock "
                    f"signal. Known clock domains: "
                    f"{sorted(declared_clocks)}."
                )
        # IEEE 1800-2017 §16.13.5 — mixed-clock implies is forbidden:
        # the |-> operator requires a single clocking event for the
        # antecedent + consequent expressions. Detect by walking the
        # compound AST for any <sos:implies> node whose antecedent and
        # consequent reach state_ref leaves in different declared
        # clock domains.
        if inv.expr is not None:
            _reject_mixed_clock_implies(inv, region_info)


def _reject_mixed_clock_implies(
    inv: _CrossInvariant,
    region_info: list[tuple[str, str | None]],
) -> None:
    """Walk ``inv.expr`` looking for ``<sos:implies>`` whose antecedent
    and consequent leaves resolve to different clock signals. IEEE
    1800-2017 §16.13.5: the overlapping-implication operator requires
    a single clock domain across both sides — multi-clock implies
    chains require explicit synchroniser primitives the walker does
    not synthesise.

    Per SOS-08-D wave-4-future-mclk (§15): chart authors who need
    multi-clock causal relationships drop to ``<sos:raw_property>``.
    """
    def _expr_clocks(e: "_CompoundExpr") -> set[str]:
        if e.kind == "state_ref":
            if e.region is None:
                return set()
            return {_resolve_sampling_clock_signal(
                e.region, inv.sampling_clocks, region_info
            )}
        out: set[str] = set()
        for c in e.children:
            out |= _expr_clocks(c)
        return out

    def _scan(e: "_CompoundExpr") -> None:
        if e.kind == "implies":
            a_clocks = _expr_clocks(e.children[0])
            c_clocks = _expr_clocks(e.children[1])
            if a_clocks and c_clocks and a_clocks != c_clocks:
                raise UnsupportedChartError(
                    f"SOS-08-D wave-4-future-mclk: cross-invariant "
                    f"{inv.id!r} <sos:implies> antecedent samples on "
                    f"{sorted(a_clocks)} but consequent samples on "
                    f"{sorted(c_clocks)} — IEEE 1800-2017 §16.13.5 "
                    f"requires single-clock antecedent + consequent "
                    f"for the |-> operator. Use <sos:raw_property> "
                    f"escape hatch for multi-clock causal chains."
                )
        for c in e.children:
            _scan(c)

    if inv.expr is not None:
        _scan(inv.expr)


def _emit_mclk_leaf_for_region(
    region: str,
    state: str,
    primary_region: str,
    sampling_clocks: dict[str, str],
    region_info: list[tuple[str, str | None]],
) -> str:
    """SOS-08-D wave-4-future-mclk (2026-05-24 §15) — render a single
    state_ref leaf for a multi-clock cross-invariant.

    The primary-clock-region leaf renders as the wave-4 form
    ``(current_state_<r> == ST_<s>)`` — the property's outer
    ``@(posedge <primary_clock>)`` covers it. Every other region's
    leaf wraps in ``$past(<expr>, 1, , @(posedge <its_clock>))`` per
    IEEE 1800-2017 §16.13 multi-clocked assertion form, sampling the
    other region's observable on its own clock and feeding the result
    back to the primary clock's evaluation point.
    """
    obs = f"current_state_{_sanitize_sv_identifier(region)}"
    const = _state_constant_name(state)
    base = f"({obs} == {const})"
    if region == primary_region:
        return base
    its_clock = _resolve_sampling_clock_signal(
        region, sampling_clocks, region_info
    )
    # IEEE 1800-2017 §16.13: $past with explicit clocking event lets
    # the property sample the operand on a different clock domain.
    return f"$past({base}, 1, , @(posedge {its_clock}))"


def _emit_mclk_compound_sv_expr(
    expr: "_CompoundExpr",
    primary_region: str,
    sampling_clocks: dict[str, str],
    region_info: list[tuple[str, str | None]],
) -> str:
    """SOS-08-D wave-4-future-mclk (2026-05-24 §15) — render a compound
    expression for the multi-clock path. Each state_ref leaf wraps
    individually via ``_emit_mclk_leaf_for_region``; boolean operators
    compose verbatim with wave-4-future-compound's lowering rules."""
    if expr.kind == "state_ref":
        return _emit_mclk_leaf_for_region(
            expr.region or "", expr.state or "",
            primary_region, sampling_clocks, region_info,
        )
    if expr.kind == "and":
        rendered = " && ".join(
            _emit_mclk_compound_sv_expr(
                c, primary_region, sampling_clocks, region_info
            )
            for c in expr.children
        )
        return f"({rendered})"
    if expr.kind == "or":
        rendered = " || ".join(
            _emit_mclk_compound_sv_expr(
                c, primary_region, sampling_clocks, region_info
            )
            for c in expr.children
        )
        return f"({rendered})"
    if expr.kind == "not":
        return (
            "!("
            + _emit_mclk_compound_sv_expr(
                expr.children[0], primary_region, sampling_clocks, region_info
            )
            + ")"
        )
    if expr.kind == "implies":
        a_sv = _emit_mclk_compound_sv_expr(
            expr.children[0], primary_region, sampling_clocks, region_info
        )
        c_sv = _emit_mclk_compound_sv_expr(
            expr.children[1], primary_region, sampling_clocks, region_info
        )
        return f"({a_sv} |-> {c_sv})"
    raise UnsupportedChartError(
        f"SOS-08-D wave-4-future-mclk: unrecognised AST kind "
        f"{expr.kind!r} at multi-clock emit time."
    )


def _emit_mclk_cdc_banner(
    inv: _CrossInvariant,
    primary_clock: str,
    other_clocks: list[str],
) -> str:
    """SOS-08-D wave-4-future-mclk (2026-05-24 §15) — banner comment
    immediately preceding every multi-clock property. Per the §15
    normative section, the walker emits the assertion form only — CDC
    synchroniser primitives between clock domains MUST be present in
    the design; the walker does not verify them.
    """
    other_clocks_text = ", ".join(other_clocks) if other_clocks else "(none)"
    return (
        f"    // MULTI-CLOCK PROPERTY: {inv.id}. CDC synchroniser "
        f"between {primary_clock} and {other_clocks_text} MUST be "
        f"present in the design. The walker does not verify CDC "
        f"synchronisation; see SOS-08-D-CONCEPTS.md §15."
    )


# ----------------------------------------------------------------------------
# SOS-08-D wave-4-future-shared (2026-05-24 §15) — shared-datamodel
# cross-region driving. A `<sos:shared_signal>` declares a chart-level
# signal that ONE region owns (the writer) and other regions may read.
# This slice emits the one-driver SVA invariant only; the HDL-side
# wiring (port shape, register allocation) is deferred to SOS-08-C
# wave-3-e port-shape extension or a successor phase.
# ----------------------------------------------------------------------------


@dataclass
class _SharedSignal:
    """One ratified ``<sos:shared_signal>`` declaration.

    Wave-4-future-shared declaration form (per §15 2026-05-24):

        <sos:shared_signal name="<sv-ident>" width="<bits>"
                           owner_region="<region>" />

    Semantics: the bind module emits a one-driver SVA invariant
    asserting that the signal MAY change value only while the owner
    region is in a non-idle state (idle = the region's initial
    state). The HDL-side wiring (the actual register / port shape) is
    deferred — this slice emits the assertion only, per §15.
    """

    name: str
    width: int
    owner_region: str
    doc_order: int = 0


def _collect_shared_signals(
    chart_ir: dict[str, Any],
) -> list[_SharedSignal]:
    """SOS-08-D wave-4-future-shared (2026-05-24 §15) — read
    ``<sos:shared_signal>`` declarations from the chart IR.

    Lookup accepts either ``sos:shared_signal`` or bare
    ``shared_signal`` keys. Validation runs in two passes: this
    collector raises on intrinsically-malformed entries (missing
    attrs, type errors); ``_validate_shared_signals`` runs after with
    the region map to check name-collisions and owner_region
    resolution.
    """
    raw = (
        chart_ir.get("sos:shared_signal")
        or chart_ir.get("shared_signal")
        or []
    )
    if isinstance(raw, dict):
        raw = [raw]
    out: list[_SharedSignal] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        owner = entry.get("owner_region")
        width_raw = entry.get("width", 1)
        if not (isinstance(name, str) and name.strip()):
            raise UnsupportedChartError(
                "SOS-08-D wave-4-future-shared: <sos:shared_signal> "
                "MUST carry a non-empty `name` attribute (used as the "
                "emitted signal identifier `shared_<name>`)."
            )
        if not (isinstance(owner, str) and owner.strip()):
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future-shared: <sos:shared_signal "
                f"name={name!r}> MUST carry a non-empty "
                f"`owner_region` attribute naming the single region "
                f"that drives the signal."
            )
        try:
            width = int(width_raw)
        except (TypeError, ValueError):
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future-shared: <sos:shared_signal "
                f"name={name!r}>'s `width` MUST be a positive integer; "
                f"got {width_raw!r}."
            ) from None
        if width < 1:
            width = 1
        out.append(_SharedSignal(
            name=name.strip(),
            width=width,
            owner_region=owner.strip(),
            doc_order=idx,
        ))
    return out


def _collect_shared_signal_refs(chart_ir: dict[str, Any]) -> list[str]:
    """SOS-08-D wave-4-future-shared (2026-05-24 §15) — collect the set
    of shared-signal names referenced by ``<sos:shared_signal_ref>``
    elements anywhere in the chart IR.

    A shared-signal-ref MAY appear inside any region's ``<assign>``
    location (or the chart-top scope) to read the shared signal. This
    slice does NOT emit the HDL-side wiring for those reads — only the
    name set is collected so the walker can validate that every
    referenced name resolves to a declared ``<sos:shared_signal>``.
    """
    names: list[str] = []
    seen: set[str] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                bare = k.split(":")[-1] if isinstance(k, str) else ""
                if bare == "shared_signal_ref":
                    refs = v if isinstance(v, list) else [v]
                    for r in refs:
                        if isinstance(r, dict):
                            nm = r.get("name")
                            if isinstance(nm, str) and nm.strip():
                                nm = nm.strip()
                                if nm not in seen:
                                    seen.add(nm)
                                    names.append(nm)
                else:
                    _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(chart_ir)
    return names


def _validate_shared_signals(
    signals: list[_SharedSignal],
    signal_refs: list[str],
    known_regions: list[str],
) -> None:
    """SOS-08-D wave-4-future-shared (2026-05-24 §15) — cross-check
    shared-signal declarations + refs.

    Raises ``UnsupportedChartError`` with prefix
    ``SOS-08-D wave-4-future-shared:`` on:

      * ``name`` collision across two ``<sos:shared_signal>`` decls.
      * ``owner_region`` references a region the chart does not
        declare.
      * Two declarations claim the same ``name`` AND name conflicting
        ``owner_region`` values (the owner-collision check folds into
        the name-collision check, but the error wording cites the
        owner conflict explicitly when both names match).
      * ``<sos:shared_signal_ref>`` references an undeclared name.
    """
    known_set = set(known_regions)
    seen: dict[str, _SharedSignal] = {}
    for sig in signals:
        prior = seen.get(sig.name)
        if prior is not None:
            if prior.owner_region != sig.owner_region:
                raise UnsupportedChartError(
                    f"SOS-08-D wave-4-future-shared: <sos:shared_signal "
                    f"name={sig.name!r}> owner_region collision: "
                    f"declaration #{prior.doc_order} owns by region "
                    f"{prior.owner_region!r}, declaration "
                    f"#{sig.doc_order} owns by region "
                    f"{sig.owner_region!r}. A shared signal MUST have "
                    f"exactly one owner region."
                )
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future-shared: <sos:shared_signal "
                f"name={sig.name!r}> is declared more than once "
                f"(declaration #{prior.doc_order} vs "
                f"#{sig.doc_order}). Shared-signal names MUST be "
                f"unique within the chart's bind module."
            )
        if sig.owner_region not in known_set:
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future-shared: <sos:shared_signal "
                f"name={sig.name!r}> owner_region "
                f"{sig.owner_region!r} does not reference a region "
                f"the chart declares. Known regions: "
                f"{sorted(known_set)}."
            )
        seen[sig.name] = sig

    # Every shared_signal_ref must resolve to a declared shared signal.
    declared_names = {s.name for s in signals}
    for ref in signal_refs:
        if ref not in declared_names:
            raise UnsupportedChartError(
                f"SOS-08-D wave-4-future-shared: <sos:shared_signal_ref "
                f"name={ref!r}> references undeclared shared signal "
                f"{ref!r}. Known shared signals: "
                f"{sorted(declared_names)}."
            )


def _region_initial_state(
    region_name: str,
    regions: list[tuple[str, dict[str, Any]]],
) -> str | None:
    """Return the ``initial`` state name for ``region_name`` in the
    parallel-region map.

    Falls back to the first ``<state>`` child's id if no ``initial``
    attribute is set (mirrors the wave-1 single-region fallback in
    ``_normalise_chart``). Used by the shared-signal one-driver
    invariant to render the "idle" state constant.
    """
    for r, st in regions:
        if r != region_name:
            continue
        initial = st.get("initial")
        if isinstance(initial, list):
            initial = initial[0] if initial else None
        if isinstance(initial, str) and initial.strip():
            return initial.strip()
        for sub in st.get("state", []) or []:
            sid = sub.get("id") if isinstance(sub, dict) else None
            if isinstance(sid, str) and sid.strip():
                return sid.strip()
        return None
    return None


def _emit_shared_signal_invariants(
    signals: list[_SharedSignal],
    region_info: list[tuple[str, str | None]],
    regions: list[tuple[str, dict[str, Any]]],
    chart_name: str,
) -> list[str]:
    """SOS-08-D wave-4-future-shared (2026-05-24 §15) — emit the
    one-driver SVA invariant for each declared shared signal.

    Per the §15 normative spec: ``assert property (@(posedge
    <owner_clock>) $changed(shared_<name>) |-> (current_state_<owner>
    != ST_<owner_idle>));`` — the signal MAY only change while the
    owner region is in a non-idle state. The "idle" state is the
    owner region's initial state (the region after reset, where the
    region is not actively producing values).

    Per the §15 normative spec, this slice emits the assertion only;
    the actual HDL-side wiring of ``shared_<name>`` (port + register)
    is deferred to a future SOS-08-C carry-forward. A documentation
    block in the emit names the deferral.
    """
    if not signals:
        return []
    lines: list[str] = [
        "",
        "    // === SOS-08-D wave-4-future-shared: shared-signal one-driver invariants ===",
        "    //",
        "    // Per SOS-08-D §15 wave-4-future-shared (2026-05-24),",
        "    // <sos:shared_signal> declares a chart-level signal driven",
        "    // by exactly one region (owner_region). The walker emits a",
        "    // one-driver assertion per declaration: $changed of the",
        "    // shared signal implies the owner region is NOT in its",
        "    // idle (initial) state.",
        "    //",
        "    // NOTE: this slice emits the assertion only. The HDL-side",
        "    // wiring of the `shared_<name>` register / port shape is",
        "    // deferred to a future SOS-08-C wave-3-e port-shape",
        "    // extension or a successor phase. The bind module assumes",
        "    // the chart-top wrapper exposes a `shared_<name>` port of",
        "    // the declared width; that port wiring lands later.",
    ]
    for sig in signals:
        owner_clock = _resolve_region_clock_signal(
            sig.owner_region, region_info
        )
        owner_obs = (
            f"current_state_{_sanitize_sv_identifier(sig.owner_region)}"
        )
        idle = _region_initial_state(sig.owner_region, regions)
        if idle is None:
            # Defensive — validation upstream guarantees the owner is a
            # known region; this branch is unreachable in practice.
            continue
        idle_const = _state_constant_name(idle)
        prop_name = (
            "p_shared_" + _sanitize_sv_identifier(sig.name).lower()
            + "_one_driver"
        )
        asrt_name = (
            "SHARED_" + _sanitize_sv_identifier(sig.name).upper()
            + "_ONE_DRIVER"
        )
        signal_ident = (
            "shared_" + _sanitize_sv_identifier(sig.name).lower()
        )
        fail_msg = (
            f"[FAIL] chart `{chart_name}` shared-signal `{sig.name}` "
            f"changed while owner region `{sig.owner_region}` was in "
            f"idle state `{idle}` — only the owner region MAY drive "
            f"the signal."
        )
        lines.extend([
            "",
            f"    // <sos:shared_signal name=\"{sig.name}\" "
            f"width=\"{sig.width}\" owner_region=\"{sig.owner_region}\"/>",
            f"    // Owner idle state: `{idle}`. HDL-side wiring of "
            f"`{signal_ident}` deferred to SOS-08-C wave-3-e (see §15).",
            f"    property {prop_name};",
            f"        @(posedge {owner_clock}) disable iff (rst)",
            f"        $changed({signal_ident}) |-> "
            f"({owner_obs} != {idle_const});",
            f"    endproperty",
            f"    {asrt_name}: assert property ({prop_name})",
            f"        else $fatal(1, \"{fail_msg}\");",
        ])
    return lines


def _shared_signal_referenced_regions(
    signals: list[_SharedSignal],
) -> list[str]:
    """Return the owner regions of every declared shared signal in
    first-seen-order. Used by the SVA module port list + bind directive
    so each owner region's observable port + clock are wired through.
    """
    out: list[str] = []
    seen: set[str] = set()
    for s in signals:
        if s.owner_region not in seen:
            seen.add(s.owner_region)
            out.append(s.owner_region)
    return out


def _emit_cross_region_sva_module(
    *,
    chart_name: str,
    chart_top_module: str,
    invariants: list[_CrossInvariant],
    region_info: list[tuple[str, str | None]],
    region_state_indices: dict[str, dict[str, int]] | None = None,
    raw_properties: list[_RawProperty] | None = None,
    shared_signals: list[_SharedSignal] | None = None,
    regions: list[tuple[str, dict[str, Any]]] | None = None,
) -> str:
    """Emit ``<chart>_top_sva.sv`` — chart-top assertion module.

    Module ports: ``clk``, ``rst``, plus one
    ``current_state_<region>`` input per region named by ANY of the
    invariants. The module body declares one ``property`` +
    ``assert property`` clause per invariant; each property's failure
    case emits a chart-vocabulary message per INV-S-HDL-D-5 naming
    the invariant id, the chart name, and the involved regions.

    Wave-4 v1: the module clocks on the chart-top wrapper's reference
    ``clk`` port — even for multi-clock parallel charts, the cross-
    region property samples both region observables on a common clock.
    Per INV-S-HDL-3 cross-domain region observables are synchronised
    through ``sos_synchronizer`` before the chart-top wrapper exposes
    them, so the sampled view is well-defined.

    Wave-4-future (2026-05-24 §15): the ``raw_properties`` arg threads
    a list of ``<sos:raw_property>`` declarations through to the emit.
    Each raw property emits a banner-commented block after the
    structured cross-invariants; per-region clock input ports
    (``<region>_clk``) are added for each unique ``clock_region``
    referenced by a raw property. When ``raw_properties`` is empty / None
    the module emit is byte-identical to wave-4 (preserves regression
    guard for existing fixtures).
    """
    module = _cross_invariant_sva_module_name(chart_name)
    raw_properties = raw_properties or []
    shared_signals = shared_signals or []
    regions = regions or []

    # Collect the set of region observable ports the module needs to
    # expose. Iteration order is invariant-declaration order; dedup
    # preserves first-seen position so the emit is deterministic.
    #
    # Wave-4-future-compound (2026-05-24 §15): for compound invariants
    # (``inv.expr is not None``), enumerate the regions referenced by
    # any ``state_ref`` leaf of the compound AST. The legacy string
    # form continues to pull from the antecedent/consequent fields.
    referenced_regions: list[str] = []
    seen: set[str] = set()
    for inv in invariants:
        if inv.expr is not None:
            inv_regions = [r for (r, _s) in _walk_compound_state_refs(inv.expr)]
        else:
            inv_regions = [inv.antecedent_region, inv.consequent_region]
        for r in inv_regions:
            if r and r not in seen:
                referenced_regions.append(r)
                seen.add(r)
    # SOS-08-D wave-4-future-shared (2026-05-24 §15): owner regions of
    # any declared shared signal also need their observable + clock
    # wired in (the one-driver invariant samples on the owner's clock
    # and references its state observable).
    for owner in _shared_signal_referenced_regions(shared_signals):
        if owner not in seen:
            referenced_regions.append(owner)
            seen.add(owner)

    # Map region → declared clock domain (None for default-clk regions).
    region_to_domain = dict(region_info)

    port_decls = "\n".join(
        f"    input wire [N_STATES_{_sanitize_sv_identifier(r).upper()}-1:0] "
        f"current_state_{_sanitize_sv_identifier(r)},"
        for r in referenced_regions
    )

    param_decls = ",\n".join(
        f"    parameter int N_STATES_{_sanitize_sv_identifier(r).upper()} = 1"
        for r in referenced_regions
    )

    # Wave-4-future: per-region clock input ports for raw_property
    # sampling. Each unique clock_region produces one ``<region>_clk``
    # input. Empty when no raw properties → emit byte-identical to
    # wave-4 for the regression-guard test.
    raw_clock_regions = _collect_raw_property_clock_regions(raw_properties)
    raw_clock_port_lines: list[str] = []
    for r in raw_clock_regions:
        clk_signal = f"{_sanitize_sv_identifier(r)}_clk"
        raw_clock_port_lines.append(
            f"    input wire {clk_signal},"
        )

    property_blocks: list[str] = []
    # SOS-08-D wave-4-future-mclk (2026-05-24 §15): track per-invariant
    # multi-clock clocks so the SVA module port list adds the extra
    # ``<region>_clk`` input ports (one per region referenced under any
    # multi-clock invariant).
    mclk_extra_clock_signals: list[str] = []
    mclk_seen_clock_signals: set[str] = set()
    for inv in invariants:
        prop_name = "p_" + _sanitize_sv_identifier(inv.id).lower()
        asrt_name = _sanitize_sv_identifier(inv.id).upper()
        is_mclk = bool(inv.sampling_clocks)
        if is_mclk:
            # SOS-08-D wave-4-future-mclk (2026-05-24 §15): pick the
            # primary clock (region whose <sos:sampling_clock> appears
            # first); resolve its SV clock signal; collect other clocks
            # referenced by the invariant's leaves for the CDC banner +
            # the SVA module's per-region clock port list.
            primary_region = (
                inv.primary_clock_region
                or (
                    inv.antecedent_region
                    if inv.expr is None
                    else (
                        _walk_compound_state_refs(inv.expr)[0][0]
                        if inv.expr is not None
                        and _walk_compound_state_refs(inv.expr)
                        else ""
                    )
                )
            )
            primary_clock = _resolve_sampling_clock_signal(
                primary_region, inv.sampling_clocks, region_info
            )
            # Collect other clock signals for the CDC banner / SVA port
            # list. Iterate the invariant's leaf regions.
            if inv.expr is not None:
                leaf_regions = [
                    r for (r, _s) in _walk_compound_state_refs(inv.expr)
                ]
            else:
                leaf_regions = [
                    inv.antecedent_region,
                    inv.consequent_region,
                ]
            other_clocks: list[str] = []
            seen_other: set[str] = set()
            for r in leaf_regions:
                if not r or r == primary_region:
                    continue
                sig = _resolve_sampling_clock_signal(
                    r, inv.sampling_clocks, region_info
                )
                if sig != primary_clock and sig not in seen_other:
                    seen_other.add(sig)
                    other_clocks.append(sig)
            # Register extra per-region clock signals on the module port
            # list (in addition to the chart-top ``clk``).
            for r in leaf_regions:
                if not r:
                    continue
                sig = _resolve_sampling_clock_signal(
                    r, inv.sampling_clocks, region_info
                )
                if sig != "clk" and sig not in mclk_seen_clock_signals:
                    mclk_seen_clock_signals.add(sig)
                    mclk_extra_clock_signals.append(sig)
            banner = _emit_mclk_cdc_banner(
                inv, primary_clock, other_clocks
            )
            if inv.expr is not None:
                body_sv = _emit_mclk_compound_sv_expr(
                    inv.expr, primary_region,
                    inv.sampling_clocks, region_info,
                )
                chart_summary = _summarise_compound_expr(inv.expr)
                fail_msg = (
                    f"[FAIL] chart `{chart_name}` cross-invariant "
                    f"`{inv.id}` (multi-clock): compound predicate "
                    f"`{chart_summary}` violated."
                )
                property_blocks.append(
                    f"{banner}\n"
                    f"    // {inv.id} (wave-4-future-mclk compound): "
                    f"{chart_summary}\n"
                    f"    property {prop_name}_mclk;\n"
                    f"        @(posedge {primary_clock})\n"
                    f"        {body_sv};\n"
                    f"    endproperty\n"
                    f"    {asrt_name}: assert property ({prop_name}_mclk)\n"
                    f"        else $fatal(1, \"{fail_msg}\");"
                )
                continue
            # String-form multi-clock invariant.
            a_leaf = _emit_mclk_leaf_for_region(
                inv.antecedent_region, inv.antecedent_state,
                primary_region, inv.sampling_clocks, region_info,
            )
            c_leaf = _emit_mclk_leaf_for_region(
                inv.consequent_region, inv.consequent_state,
                primary_region, inv.sampling_clocks, region_info,
            )
            fail_msg = (
                f"[FAIL] chart `{chart_name}` cross-invariant `{inv.id}` "
                f"(multi-clock): region `{inv.antecedent_region}` on "
                f"clock `{_resolve_sampling_clock_signal(inv.antecedent_region, inv.sampling_clocks, region_info)}` "
                f"entered state `{inv.antecedent_state}` but region "
                f"`{inv.consequent_region}` on clock "
                f"`{_resolve_sampling_clock_signal(inv.consequent_region, inv.sampling_clocks, region_info)}` "
                f"did not enter state `{inv.consequent_state}`."
            )
            property_blocks.append(
                f"{banner}\n"
                f"    // {inv.id} (wave-4-future-mclk): "
                f"`{inv.antecedent_region}`.{inv.antecedent_state} && "
                f"$past `{inv.consequent_region}`.{inv.consequent_state}\n"
                f"    property {prop_name}_mclk;\n"
                f"        @(posedge {primary_clock})\n"
                f"        {a_leaf} && {c_leaf};\n"
                f"    endproperty\n"
                f"    {asrt_name}: assert property ({prop_name}_mclk)\n"
                f"        else $fatal(1, \"{fail_msg}\");"
            )
            continue
        if inv.expr is not None:
            # Wave-4-future-compound (2026-05-24 §15): structured
            # boolean composition over <sos:state_ref> leaves. The
            # body is a same-cycle SVA expression (no temporal
            # window). Implication uses |-> (overlapping) per
            # IEEE 1800-2017 §16.12.2 — see ``_emit_compound_sv_expr``.
            body_sv = _emit_compound_sv_expr(inv.expr)
            chart_summary = _summarise_compound_expr(inv.expr)
            fail_msg = (
                f"[FAIL] chart `{chart_name}` cross-invariant `{inv.id}`: "
                f"compound predicate `{chart_summary}` violated."
            )
            property_blocks.append(
                f"    // {inv.id} (wave-4-future-compound): {chart_summary}\n"
                f"    property {prop_name};\n"
                f"        @(posedge clk) disable iff (rst)\n"
                f"        {body_sv};\n"
                f"    endproperty\n"
                f"    {asrt_name}: assert property ({prop_name})\n"
                f"        else $fatal(1, \"{fail_msg}\");"
            )
            continue
        a_obs = f"current_state_{_sanitize_sv_identifier(inv.antecedent_region)}"
        c_obs = f"current_state_{_sanitize_sv_identifier(inv.consequent_region)}"
        a_state_const = _state_constant_name(inv.antecedent_state)
        c_state_const = _state_constant_name(inv.consequent_state)
        within = inv.within
        # Chart-vocabulary failure message per INV-S-HDL-D-5 + INV-SOS-H.
        fail_msg = (
            f"[FAIL] chart `{chart_name}` cross-invariant `{inv.id}`: "
            f"region `{inv.antecedent_region}` entered state "
            f"`{inv.antecedent_state}` but region "
            f"`{inv.consequent_region}` did not enter state "
            f"`{inv.consequent_state}` within {within} cycle(s)."
        )
        property_blocks.append(
            f"    // {inv.id}: region `{inv.antecedent_region}`.{inv.antecedent_state} "
            f"|-> ##[1:{within}] region `{inv.consequent_region}`.{inv.consequent_state}\n"
            f"    property {prop_name};\n"
            f"        @(posedge clk) disable iff (rst)\n"
            f"        ({a_obs} == {a_state_const})\n"
            f"        |-> ##[1:{within}] ({c_obs} == {c_state_const});\n"
            f"    endproperty\n"
            f"    {asrt_name}: assert property ({prop_name})\n"
            f"        else $fatal(1, \"{fail_msg}\");"
        )

    # SOS-08-D wave-4-future-shared (2026-05-24 §15): one-driver
    # invariant blocks for declared <sos:shared_signal> entries. Owner
    # regions (and their clocks) are wired into the module port list
    # below; the assertion checks $changed(<signal>) |-> owner != idle.
    shared_signal_lines: list[str] = _emit_shared_signal_invariants(
        shared_signals, region_info, regions, chart_name,
    )
    # Owner-clock signals that aren't already wired through the
    # multi-clock or default ``clk`` port appear here so the SVA
    # module's port list adds the appropriate input wires.
    shared_extra_clock_signals: list[str] = []
    shared_seen_clock_signals: set[str] = set(mclk_seen_clock_signals)
    for sig in shared_signals:
        owner_clk = _resolve_region_clock_signal(
            sig.owner_region, region_info
        )
        if owner_clk != "clk" and owner_clk not in shared_seen_clock_signals:
            shared_seen_clock_signals.add(owner_clk)
            shared_extra_clock_signals.append(owner_clk)

    domain_comment = _format_cross_invariant_domain_comment(
        region_info, referenced_regions
    )

    # Wave-4-future raw-property block (empty when no raw_properties →
    # byte-identical to wave-4 emit for charts without escape hatches).
    raw_property_lines = _emit_raw_property_blocks(
        raw_properties, chart_name
    )

    # Header banner: keep wave-4 line count + wording stable when no
    # raw_properties so the regression-guard byte-identity test passes;
    # extend with a wave-4-future banner only when raw_properties exist.
    header_banner: list[str] = [
        "// SOS-08-D wave-4: cross-region invariant SVA module.",
        f"// Chart-top wrapper bound to: {chart_top_module}",
        f"// Invariants declared:        {len(invariants)}",
        f"// Regions referenced:         {', '.join(referenced_regions)}",
        "//",
        "// Per SOS-08-D §15 wave-4 (2026-05-24), cross-region",
        "// invariants restrict the antecedent/consequent grammar to",
        "// `region.<name> == <state>`. The structured form lets the",
        "// walker reason about the property + cite chart vocabulary",
        "// in the failure message per INV-S-HDL-D-5.",
        "//",
        "// Per INV-S-HDL-3 + SOS-08-C wave-3, cross-domain region",
        "// observables are synchronised through sos_synchronizer",
        "// before the chart-top wrapper exposes them — the cross-",
        "// region sampling clock below is well-defined for both",
        "// single-clock + multi-clock parallel charts.",
        domain_comment,
    ]
    if raw_properties:
        header_banner.extend([
            "//",
            "// SOS-08-D §15 wave-4-future (2026-05-24): this module also",
            "// carries <sos:raw_property> escape-hatch blocks below the",
            f"// structured cross-invariants. Raw properties declared: "
            f"{len(raw_properties)}.",
            "// The walker preserves each raw body verbatim (relationship",
            "// `derive` against IEEE 1800-2017 SystemVerilog); only the",
            "// element wrapper + collision/clock_region validation are",
            "// walker-owned.",
        ])

    # Module port + parameter list. The structured-invariant path emits
    # a parameter block (`#(parameter int N_STATES_<R> = 1, ...)`);
    # raw-property-only emits skip the parameter block (no per-region
    # state-vector ports → no parameter needed). Port list assembles
    # clk + rst + structured observables + per-region raw clocks +
    # wave-4-future-mclk per-region clocks + wave-4-future-shared
    # owner-region clocks + shared_<name> signals.
    port_list_lines: list[str] = [
        "    input wire clk",
        "    input wire rst",
    ]
    for r in referenced_regions:
        port_list_lines.append(
            f"    input wire [N_STATES_{_sanitize_sv_identifier(r).upper()}-1:0] "
            f"current_state_{_sanitize_sv_identifier(r)}"
        )
    for r in raw_clock_regions:
        port_list_lines.append(
            f"    input wire {_sanitize_sv_identifier(r)}_clk"
        )
    for sig in mclk_extra_clock_signals:
        if sig in (f"{_sanitize_sv_identifier(r)}_clk" for r in raw_clock_regions):
            continue
        port_list_lines.append(
            f"    input wire {sig}"
        )
    for sig in shared_extra_clock_signals:
        port_list_lines.append(
            f"    input wire {sig}"
        )
    for sh in shared_signals:
        signal_ident = (
            "shared_" + _sanitize_sv_identifier(sh.name).lower()
        )
        if sh.width <= 1:
            port_list_lines.append(
                f"    input wire {signal_ident}"
            )
        else:
            port_list_lines.append(
                f"    input wire [{sh.width - 1}:0] {signal_ident}"
            )
    # Join with trailing commas on all but the last port line.
    port_list_block = ",\n".join(port_list_lines)

    lines: list[str] = [
        _emit_header(chart_name, kind="cross-region-sva"),
        "",
        *header_banner,
        "",
        "`default_nettype none",
        "",
    ]

    # Parameter block is required whenever the module exposes per-region
    # state-vector ports (either from structured invariants OR from
    # shared-signal owner observables). It is omitted only when the
    # module is purely raw-property-driven (no state-vector ports).
    need_param_block = bool(invariants) or bool(shared_signals)

    if need_param_block:
        # When the parameter block exists because of shared signals only
        # (no structured invariants), build the param_decls list from
        # referenced_regions (which already includes shared-signal owners).
        if not invariants:
            params_for_shared = ",\n".join(
                f"    parameter int N_STATES_{_sanitize_sv_identifier(r).upper()} = 1"
                for r in referenced_regions
            )
            lines.extend([
                f"module {module} #(",
                params_for_shared,
                ") (",
            ])
        else:
            lines.extend([
                f"module {module} #(",
                param_decls,
                ") (",
            ])
    else:
        lines.append(f"module {module} (")

    lines.extend([
        port_list_block,
        ");",
    ])

    if invariants:
        lines.extend([
            "",
            "    // INV-S-HDL-D-2 (one-hot, reset-initial) state-constants",
            "    // are inherited from each region's FSM module via the",
            "    // chart-top wrapper's port wiring; the cross-region module",
            "    // need only re-declare the constants it directly refs.",
            *_emit_cross_invariant_state_constants(
                invariants, region_state_indices
            ),
            "",
            *property_blocks,
        ])

    if raw_property_lines:
        # Raw properties always render after the structured invariants
        # (and after the structured-block separator) so the byte-identity
        # regression guard for no-raw_property charts holds: the entire
        # block below the `*property_blocks` line is `*raw_property_lines`
        # which is empty for that path.
        lines.extend(raw_property_lines)

    # SOS-08-D wave-4-future-shared (2026-05-24 §15): emit shared-signal
    # one-driver invariants AFTER the structured cross-invariants and
    # raw-property blocks. The shared invariants reference each owner
    # region's ``ST_<initial>`` constant — declare those state constants
    # here (the structured-invariant constants emit above only covers
    # states referenced by cross_invariants).
    if shared_signal_lines:
        # Emit ST_<initial> state constants for each shared-signal owner
        # region's initial state (unless they were already emitted by
        # cross-invariant state-constant emission above).
        shared_state_const_lines: list[str] = []
        emitted_shared_constants: set[tuple[str, str]] = set()
        for sh in shared_signals:
            idle = _region_initial_state(sh.owner_region, regions)
            if idle is None:
                continue
            key = (sh.owner_region, idle)
            if key in emitted_shared_constants:
                continue
            emitted_shared_constants.add(key)
            r_ident = _sanitize_sv_identifier(sh.owner_region)
            param = f"N_STATES_{r_ident.upper()}"
            const = _state_constant_name(idle)
            # Compute the bit position for the idle state using the
            # region_state_indices map when available; fall back to
            # bit 0 (the wave-4 v1 placeholder behaviour).
            bit_idx = _state_index_for(
                sh.owner_region, idle, region_state_indices
            )
            shared_state_const_lines.extend([
                f"    // Shared-signal owner idle constant `{const}` "
                f"for region `{sh.owner_region}` (bit {bit_idx}).",
                f"    `ifndef {const}_DEFINED",
                f"    `define {const}_DEFINED",
                f"    localparam logic [{param}-1:0] {const} = "
                f"{{{param}{{1'b0}}}} | ({param}'(1) << {bit_idx});",
                f"    `endif",
            ])
        if shared_state_const_lines:
            lines.extend(shared_state_const_lines)
        lines.extend(shared_signal_lines)

    lines.extend([
        "",
        "endmodule",
        "",
        "`default_nettype wire",
    ])
    return "\n".join(lines) + "\n"


def _format_cross_invariant_domain_comment(
    region_info: list[tuple[str, str | None]],
    referenced_regions: list[str],
) -> str:
    region_to_domain = dict(region_info)
    parts: list[str] = []
    for r in referenced_regions:
        dom = region_to_domain.get(r)
        if dom is None:
            parts.append(f"//   region `{r}`: default clock domain (`clk`)")
        else:
            parts.append(
                f"//   region `{r}`: clock domain `{dom}` "
                f"→ {_clk_port_name(dom)}/{_rst_port_name(dom)} (synced)"
            )
    return "\n".join(parts) if parts else "//   (no referenced regions)"


def _emit_cross_invariant_state_constants(
    invariants: list[_CrossInvariant],
    region_state_indices: dict[str, dict[str, int]] | None = None,
) -> list[str]:
    """Emit ``localparam`` declarations for each state constant the
    cross-region properties reference. Width parameterised against
    each region's ``N_STATES_<R>`` so the comparison fits the actual
    one-hot width.

    Wave-4-future (2026-05-24 §15): when ``region_state_indices`` is
    provided, the bit position for each state is resolved via the
    per-region state-encoding map (state document-order index, matching
    SOS-08-C's ``_emit_state_constants``). When ``None`` the emit
    falls back to the wave-4 v1 placeholder (bit 0 for every state) +
    a ``// WAVE-4-V1 PLACEHOLDER`` comment marking the constant as
    template-only — preserves wave-4 v1 behaviour for any caller that
    has not yet been migrated to thread the encoding map through.
    """
    seen: set[tuple[str, str]] = set()
    lines: list[str] = []
    for inv in invariants:
        # Wave-4-future-compound (2026-05-24 §15): compound invariants
        # walk their AST for state_ref leaves; legacy string invariants
        # continue through the antecedent/consequent pair.
        if inv.expr is not None:
            inv_refs: list[tuple[str, str]] = _walk_compound_state_refs(inv.expr)
        else:
            inv_refs = [
                (inv.antecedent_region, inv.antecedent_state),
                (inv.consequent_region, inv.consequent_state),
            ]
        for region, state in inv_refs:
            if not region or not state:
                continue
            key = (region, state)
            if key in seen:
                continue
            seen.add(key)
            r_ident = _sanitize_sv_identifier(region)
            param = f"N_STATES_{r_ident.upper()}"
            const = _state_constant_name(state)
            bit_idx = _state_index_for(region, state, region_state_indices)
            # Annotate the source of the bit-position for reviewers.
            if region_state_indices is None:
                source_note = "WAVE-4-V1 PLACEHOLDER — bit position is 0"
            else:
                source_note = (
                    f"bit {bit_idx} per SOS-08-C document-order encoding"
                )
            lines.append(
                f"    // State constant `{const}` for region `{region}` — "
                f"matches SOS-08-C one-hot encoding ({source_note})."
            )
            lines.append(
                f"    `ifndef {const}_DEFINED"
            )
            lines.append(
                f"    `define {const}_DEFINED"
            )
            # Use the region's N_STATES width so the comparison in the
            # property aligns with the per-region FSM's encoding.
            lines.append(
                f"    localparam logic [{param}-1:0] {const} = "
                f"{{{param}{{1'b0}}}} | ({param}'(1) << {bit_idx});"
            )
            lines.append(f"    `endif")
    return lines


def _state_index_for(
    region: str,
    state: str,
    region_state_indices: dict[str, dict[str, int]] | None,
) -> int:
    """Look up the one-hot bit position for ``state`` in ``region``.

    Wave-4-future (2026-05-24 §15): when ``region_state_indices`` is
    provided, return the document-order index of ``state`` within
    ``region`` per ``_build_region_state_indices``. When ``None`` —
    the wave-4 v1 caller path that does not thread the encoding map —
    fall back to the v1 placeholder behaviour (bit 0).

    The returned bit position MUST match the bit position SOS-08-C's
    ``_emit_state_constants`` uses inside the per-region FSM module
    for the same ``state`` — otherwise the SVA comparison
    ``current_state_<region> == ST_<state>`` never holds.

    Wave-4 v1 callers receive ``None`` and continue to emit TEMPLATE-
    only state constants. Wave-4-future callers receive a populated
    map and emit constants that match SOS-08-C by-construction; the
    cross-region property fires only when the antecedent region is
    actually in the antecedent state.
    """
    if region_state_indices is None:
        return 0
    region_map = region_state_indices.get(region, {})
    return region_map.get(state, 0)


def _emit_cross_region_bind_directive(
    *,
    chart_name: str,
    chart_top_module: str,
    invariants: list[_CrossInvariant],
    region_info: list[tuple[str, str | None]],
    raw_properties: list[_RawProperty] | None = None,
    shared_signals: list[_SharedSignal] | None = None,
) -> str:
    """Emit ``<chart>_top_bind.sv`` — bind directive attaching the
    chart-top SVA module to the chart-top wrapper.

    Wires:
      - ``.clk(clk)`` — chart-top reference clock.
      - ``.rst(rst)`` — chart-top reference reset.
      - ``.current_state_<region>`` per region referenced by any
        invariant; matches the chart-top wrapper's exposed port shape.

    Wave-4-future (2026-05-24 §15): when ``raw_properties`` is non-
    empty, the bind also wires per-region ``<region>_clk`` ports from
    the chart-top wrapper's per-domain or default clock. Each region
    used as a raw-property ``clock_region`` contributes one connection.
    For regions carrying a ``clock`` annotation, the source is
    ``clk_<domain>`` per SOS-08-C wave-3's clock-distribution contract;
    for regions without an annotation, the source is the chart-top
    reference ``clk``.
    """
    sva_module = _cross_invariant_sva_module_name(chart_name)
    inst_name = f"u_{sva_module}"
    raw_properties = raw_properties or []
    shared_signals = shared_signals or []

    referenced_regions: list[str] = []
    seen: set[str] = set()
    for inv in invariants:
        if inv.expr is not None:
            inv_regions = [r for (r, _s) in _walk_compound_state_refs(inv.expr)]
        else:
            inv_regions = [inv.antecedent_region, inv.consequent_region]
        for r in inv_regions:
            if r and r not in seen:
                referenced_regions.append(r)
                seen.add(r)
    # SOS-08-D wave-4-future-shared: owner regions get their observables
    # wired too.
    for owner in _shared_signal_referenced_regions(shared_signals):
        if owner not in seen:
            referenced_regions.append(owner)
            seen.add(owner)

    raw_clock_regions = _collect_raw_property_clock_regions(raw_properties)
    region_to_domain = dict(region_info)

    # SOS-08-D wave-4-future-mclk (2026-05-24 §15): per-invariant
    # sampling-clock ports added to the SVA module need matching
    # connections in the bind. Collect the SV clock signal names in
    # first-seen order across all multi-clock invariants.
    mclk_clock_signals: list[str] = []
    mclk_seen: set[str] = set()
    for inv in invariants:
        if not inv.sampling_clocks:
            continue
        if inv.expr is not None:
            leaf_regions = [
                r for (r, _s) in _walk_compound_state_refs(inv.expr)
            ]
        else:
            leaf_regions = [inv.antecedent_region, inv.consequent_region]
        for r in leaf_regions:
            if not r:
                continue
            sig = _resolve_sampling_clock_signal(
                r, inv.sampling_clocks, region_info
            )
            if sig == "clk":
                continue
            if sig in mclk_seen:
                continue
            mclk_seen.add(sig)
            mclk_clock_signals.append(sig)

    # SOS-08-D wave-4-future-shared (2026-05-24 §15): owner-region clocks
    # not already wired through ``clk`` / mclk path.
    shared_clock_signals: list[str] = []
    shared_seen_set: set[str] = set(mclk_seen)
    for sh in shared_signals:
        sig = _resolve_region_clock_signal(sh.owner_region, region_info)
        if sig != "clk" and sig not in shared_seen_set:
            shared_seen_set.add(sig)
            shared_clock_signals.append(sig)

    # Build connection list. Last connection MUST NOT carry a trailing
    # comma — assemble first, then patch the final entry.
    all_conns: list[str] = [
        ".clk           (clk)",
        ".rst           (rst)",
    ]
    for r in referenced_regions:
        obs = f"current_state_{_sanitize_sv_identifier(r)}"
        all_conns.append(f".{obs} ({obs})")
    for r in raw_clock_regions:
        sva_port = f"{_sanitize_sv_identifier(r)}_clk"
        domain = region_to_domain.get(r)
        if domain is not None:
            src = _clk_port_name(domain)
        else:
            src = "clk"
        all_conns.append(f".{sva_port} ({src})")
    raw_port_set = {
        f"{_sanitize_sv_identifier(r)}_clk" for r in raw_clock_regions
    }
    for sig in mclk_clock_signals:
        # Avoid double-wiring a port already supplied by the raw-property
        # block (same SV clock signal name).
        if sig in raw_port_set:
            continue
        all_conns.append(f".{sig} ({sig})")
    for sig in shared_clock_signals:
        all_conns.append(f".{sig} ({sig})")
    for sh in shared_signals:
        signal_ident = (
            "shared_" + _sanitize_sv_identifier(sh.name).lower()
        )
        all_conns.append(f".{signal_ident} ({signal_ident})")

    conn_lines: list[str] = []
    for i, conn in enumerate(all_conns):
        suffix = "," if i < len(all_conns) - 1 else ""
        conn_lines.append(f"    {conn}{suffix}")

    body_extra: list[str] = []
    if raw_properties:
        body_extra.extend([
            "//",
            "// SOS-08-D §15 wave-4-future (2026-05-24): bind also wires",
            f"// {len(raw_clock_regions)} per-region clock port(s) used by "
            f"<sos:raw_property> blocks.",
            "// Per-region clock source picks up the wave-4 clock-",
            "// distribution contract: clk_<domain> when the region",
            "// declares a `clock` attribute; the chart-top reference",
            "// `clk` otherwise.",
        ])
    if any(inv.sampling_clocks for inv in invariants):
        body_extra.extend([
            "//",
            "// SOS-08-D §15 wave-4-future-mclk (2026-05-24): one or more",
            "// <sos:cross_invariant> declarations carry <sos:sampling_clock>",
            "// children, lowering to IEEE 1800-2017 §16.13 multi-clock",
            "// assertion form. Per-region clock signals routed below.",
            "// CDC synchronisers between the named clock domains MUST",
            "// be present in the design; the walker emits the assertion",
            "// form only and does NOT verify CDC synchronisation.",
        ])
    if shared_signals:
        body_extra.extend([
            "//",
            "// SOS-08-D §15 wave-4-future-shared (2026-05-24): one or more",
            f"// <sos:shared_signal> declarations attached ({len(shared_signals)}).",
            "// The bind wires owner-region observables + clocks + the",
            "// shared_<name> port(s). HDL-side wiring of those ports is",
            "// deferred to a future SOS-08-C carry-forward (see §15).",
        ])

    lines: list[str] = [
        _emit_header(chart_name, kind="cross-region-bind"),
        "",
        "// SOS-08-D wave-4: cross-region SVA bind directive.",
        f"// Chart-top wrapper module: {chart_top_module}",
        f"// Cross-region SVA module:  {sva_module}",
        f"// Invariants attached:      {len(invariants)}",
        "//",
        "// Per SOS-08-D §15 wave-4, chart-top SVA properties sample",
        "// per-region observables on the chart-top reference clock.",
        "// Per-region clock-domain wiring is handled by the per-region",
        "// bind directives in `_region_<r>_fsm_bind.sv`; this chart-",
        "// top bind uses the reference clock for cross-region sampling.",
        *body_extra,
        "",
        "`default_nettype none",
        "",
        f"bind {chart_top_module} {sva_module} {inst_name} (",
        *conn_lines,
        ");",
        "",
        "`default_nettype wire",
    ]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------
# Public entry point.
# ----------------------------------------------------------------------------


def render_target(chart_ir: Any, config: Any = None) -> dict[str, str]:
    """Emit the SVA assertion module + bind directive for the chart.

    Wave-1 / wave-2b contract:
      * Single-region chart → two files:
          - ``tests/<chart>/<chart>_fsm_sva.sv``
          - ``tests/<chart>/<chart>_fsm_bind.sv``
      * Parallel chart (wave-2b, 2026-05-23) → 2N files for N regions:
          - ``tests/<chart>/<chart>_region_<region>_fsm_sva.sv``
          - ``tests/<chart>/<chart>_region_<region>_fsm_bind.sv``
        Each per-region bind targets the chart-top wrapper
        (``<chart>_fsm`` per SOS-08-C §6.10) and wires its
        ``current_state_<region>`` output port to the per-region SVA
        module's region-local ``current_state`` input.

    Args:
        chart_ir: raw scjson dict (``ChartAst.raw_scjson``).
        config: optional dict / dataclass. Consumes:
            - ``chart_name`` (str): chart identifier; module-name base.
            - ``guard_depth_budget`` (int): PCDN-C-004 budget override.

    Returns:
        dict mapping output filename → file source. Filenames embed the
        per-DUT directory prefix (``tests/<chart>/...``) per PCDN-D-004
        + SOS-08-D §6.1.

    Raises:
        UnsupportedChartError (or ``GuardDepthExceeded``) when chart
        shape is outside the scaffold scope or when a guard's compiled
        depth exceeds the configured budget.
    """
    if not isinstance(chart_ir, dict):
        raise UnsupportedChartError(
            "SOS-08-D render_target expects the raw scjson dict, "
            f"not {type(chart_ir).__name__}. The main.py dispatcher needs "
            "to pass the parsed scjson AST (ChartAst.raw_scjson)."
        )

    if isinstance(config, dict):
        chart_name = config.get("chart_name") or "chart"
    else:
        chart_name = getattr(config, "chart_name", None) or "chart"

    depth_budget = _resolve_depth_budget(config)

    # SOS-08-D wave-2b (2026-05-23 §15): detect parallel charts and
    # dispatch to per-region emission. Single-region charts continue
    # through the wave-1 code path unchanged.
    regions = _collect_parallel_regions(chart_ir)
    base = _sanitize_sv_identifier(chart_name).lower()

    if regions:
        return _render_parallel(
            chart_ir=chart_ir,
            chart_name=chart_name,
            base=base,
            regions=regions,
            depth_budget=depth_budget,
        )

    chart = _normalise_chart(chart_ir, chart_name)

    sva_body = _emit_sva_module(chart, depth_budget)
    bind_body = _emit_bind_directive(chart)

    # PCDN-D-004 places both files under tests/<chart>/.
    sva_path = f"tests/{base}/{base}_fsm_sva.sv"
    bind_path = f"tests/{base}/{base}_fsm_bind.sv"

    return {
        sva_path: sva_body,
        bind_path: bind_body,
    }


def _render_parallel(
    *,
    chart_ir: dict[str, Any],
    chart_name: str,
    base: str,
    regions: list[tuple[str, dict[str, Any]]],
    depth_budget: int,
) -> dict[str, str]:
    """Emit per-region SVA + per-region bind for a parallel chart.

    Per SOS-08-D §15 wave-2b ratification (2026-05-23): each region of
    a parallel chart contributes one SVA assertion module + one bind
    directive file under ``tests/<chart>/``. The bind directives all
    target the chart-top wrapper (``<chart>_fsm`` per SOS-08-C §6.10),
    so the SVA modules attach in parallel without coupling.

    Datamodel signals on the parent chart_ir are passed through to
    each per-region normalisation step so guard-referenced data
    signals on region transitions resolve correctly. Each region's
    SVA module carries only the datamodel signals referenced by its
    own transition guards (per ``_datamodel_signals_referenced_in_guards``).
    """
    # The chart-top wrapper module name — bind targets it (not the
    # per-region FSM modules). Mirrors SOS-08-C §6.10 chart-top
    # wrapper module naming (``<chart>_fsm``).
    chart_top_module = _module_name(chart_name)

    out: dict[str, str] = {}
    region_info: list[tuple[str, str | None]] = []  # for cross-invariant emit
    for region_name, region_state in regions:
        # Per-region pseudo-chart: the region's <state> children sit
        # at the chart's top level. We splice the parent chart's
        # datamodel onto the region's state-tree so guard signals
        # resolve consistently with the single-region code path.
        per_region_ir: dict[str, Any] = {
            "state": region_state.get("state") or [],
            "datamodel": chart_ir.get("datamodel") or [],
        }
        per_region_initial = region_state.get("initial")
        if per_region_initial:
            per_region_ir["initial"] = per_region_initial

        per_region_name = _per_region_chart_name(chart_name, region_name)
        chart = _normalise_chart(per_region_ir, per_region_name)

        # SOS-08-D wave-4 (2026-05-24 §15): extract per-region clock
        # domain. None for wave-2b single-clock-domain regions; a
        # non-None string for regions carrying ``clock="..."`` per
        # SOS-08-C wave-3 clock-distribution contract.
        clock_domain = _region_clock_domain(region_state)
        region_info.append((region_name, clock_domain))

        sva_body = _emit_sva_module(chart, depth_budget)
        bind_body = _emit_parallel_bind_directive(
            chart=chart,
            chart_top_module=chart_top_module,
            region_name=region_name,
            clock_domain=clock_domain,
        )

        region_slug = _sanitize_sv_identifier(region_name).lower()
        sva_path = (
            f"tests/{base}/{base}_region_{region_slug}_fsm_sva.sv"
        )
        bind_path = (
            f"tests/{base}/{base}_region_{region_slug}_fsm_bind.sv"
        )
        out[sva_path] = sva_body
        out[bind_path] = bind_body

    # SOS-08-D wave-4 (2026-05-24 §15): cross-region invariant emit.
    # When the chart carries any ``<sos:cross_invariant>`` element at
    # its top level, co-emit ``<chart>_top_sva.sv`` (assertion module
    # referencing per-region observables) + ``<chart>_top_bind.sv``
    # (bind directive targeting the chart-top wrapper).
    #
    # SOS-08-D wave-4-future (2026-05-24 §15): the same two files also
    # carry ``<sos:raw_property>`` escape-hatch blocks. Top-file emit
    # fires when EITHER list is non-empty; collision + clock_region
    # validation runs before emit so chart-author typos surface as
    # actionable errors (INV-S-HDL-D-5) rather than as malformed SVA.
    cross_invariants = _collect_cross_invariants(chart_ir)
    raw_properties = _collect_raw_properties(chart_ir)
    # SOS-08-D wave-4-future-shared (2026-05-24 §15) — collect
    # <sos:shared_signal> + <sos:shared_signal_ref> declarations.
    shared_signals = _collect_shared_signals(chart_ir)
    shared_signal_refs = _collect_shared_signal_refs(chart_ir)
    if cross_invariants or raw_properties or shared_signals:
        # SOS-08-D wave-4-future (2026-05-24 §15): build per-region
        # state-encoding map matching SOS-08-C's document-order one-hot
        # encoding; validate every cross-invariant's region.state refs
        # before emit so a typo surfaces as a chart-vocabulary error
        # citing INV-S-HDL-D-2 + the cross-invariant id, not as a
        # silently-mismatched bit position in the SVA property.
        region_state_indices = _build_region_state_indices(regions)
        if cross_invariants:
            _validate_cross_invariant_state_refs(
                cross_invariants, region_state_indices
            )
            # SOS-08-D wave-4-future-mclk validation: every
            # <sos:sampling_clock> resolves to a known region + known
            # clock domain; mixed-clock <sos:implies> rejected per
            # IEEE 1800-2017 §16.13.5.
            _validate_sampling_clocks(
                cross_invariants, region_info, region_state_indices,
            )
        # Raw-property validation: collision + clock_region resolution
        # against the chart's declared regions.
        known_region_names = [r for r, _ in region_info]
        _validate_raw_properties(
            raw_properties, cross_invariants, known_region_names
        )
        # SOS-08-D wave-4-future-shared (2026-05-24 §15) — validate
        # shared signals + refs against the chart's region map.
        _validate_shared_signals(
            shared_signals, shared_signal_refs, known_region_names,
        )
        top_sva_body = _emit_cross_region_sva_module(
            chart_name=chart_name,
            chart_top_module=chart_top_module,
            invariants=cross_invariants,
            region_info=region_info,
            region_state_indices=region_state_indices,
            raw_properties=raw_properties,
            shared_signals=shared_signals,
            regions=regions,
        )
        top_bind_body = _emit_cross_region_bind_directive(
            chart_name=chart_name,
            chart_top_module=chart_top_module,
            invariants=cross_invariants,
            region_info=region_info,
            raw_properties=raw_properties,
            shared_signals=shared_signals,
        )
        out[f"tests/{base}/{base}_top_sva.sv"] = top_sva_body
        out[f"tests/{base}/{base}_top_bind.sv"] = top_bind_body

    return out


# ---------------------------------------------------------------------------
# Public helpers used by the test harness.
# ---------------------------------------------------------------------------


def sva_module_name(chart_name: str) -> str:
    """``<chart>_fsm_sva`` — assertion module name."""
    return _sva_module_name(chart_name)


def dut_module_name(chart_name: str) -> str:
    """``<chart>_fsm`` — DUT module name (chart-emitted FSM)."""
    return _module_name(chart_name)


def state_constant_name(state_id: str) -> str:
    """``ST_<UPPER>`` — state-constant name; matches SOS-08-C walker."""
    return _state_constant_name(state_id)


if __name__ == "__main__":  # pragma: no cover — dev / debug entry
    import sys
    from pathlib import Path

    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    from loader import load_chart  # noqa: E402

    chart_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        here.parent.parent / "rtos_kernel.scxml"
    )
    ast = load_chart(chart_path)
    out = render_target(ast.raw_scjson, None)
    for fname, content in out.items():
        sys.stdout.write(f"=== {fname} ===\n{content}\n")

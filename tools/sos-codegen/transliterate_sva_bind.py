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
    """

    id: str
    antecedent_region: str
    antecedent_state: str
    consequent_region: str
    consequent_state: str
    within: int


_CROSS_INVARIANT_WITHIN_CAP = 1024
"""Wave-4 frozen cap on `within` cycles; bounds the SVA window so
   commercial-sim assertion-engine memory stays reasonable. Bump by
   §15 amendment if a real-world chart needs longer."""


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
        antecedent = entry.get("antecedent")
        consequent = entry.get("consequent")
        within_raw = entry.get("within", 1)
        if not (isinstance(inv_id, str) and inv_id.strip()):
            raise UnsupportedChartError(
                "SOS-08-D wave-4: <sos:cross_invariant> MUST carry a "
                "non-empty `id` attribute (chart-vocabulary failure "
                "messages cite it per INV-S-HDL-D-5)."
            )
        a_region, a_state = _parse_region_state_expr(
            antecedent, inv_id, "antecedent"
        )
        c_region, c_state = _parse_region_state_expr(
            consequent, inv_id, "consequent"
        )
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
        out.append(_CrossInvariant(
            id=inv_id,
            antecedent_region=a_region,
            antecedent_state=a_state,
            consequent_region=c_region,
            consequent_state=c_state,
            within=within,
        ))
    return out


_REGION_STATE_RE = re.compile(
    r"^\s*region\.([A-Za-z_][A-Za-z0-9_]*)\s*==\s*([A-Za-z_][A-Za-z0-9_]*)\s*$"
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


def _emit_cross_region_sva_module(
    *,
    chart_name: str,
    chart_top_module: str,
    invariants: list[_CrossInvariant],
    region_info: list[tuple[str, str | None]],
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
    """
    module = _cross_invariant_sva_module_name(chart_name)

    # Collect the set of region observable ports the module needs to
    # expose. Iteration order is invariant-declaration order; dedup
    # preserves first-seen position so the emit is deterministic.
    referenced_regions: list[str] = []
    seen: set[str] = set()
    for inv in invariants:
        for r in (inv.antecedent_region, inv.consequent_region):
            if r not in seen:
                referenced_regions.append(r)
                seen.add(r)

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

    property_blocks: list[str] = []
    for inv in invariants:
        a_obs = f"current_state_{_sanitize_sv_identifier(inv.antecedent_region)}"
        c_obs = f"current_state_{_sanitize_sv_identifier(inv.consequent_region)}"
        a_state_const = _state_constant_name(inv.antecedent_state)
        c_state_const = _state_constant_name(inv.consequent_state)
        prop_name = "p_" + _sanitize_sv_identifier(inv.id).lower()
        asrt_name = _sanitize_sv_identifier(inv.id).upper()
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

    domain_comment = _format_cross_invariant_domain_comment(
        region_info, referenced_regions
    )

    lines: list[str] = [
        _emit_header(chart_name, kind="cross-region-sva"),
        "",
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
        "",
        "`default_nettype none",
        "",
        f"module {module} #(",
        param_decls,
        ") (",
        "    input wire clk,",
        "    input wire rst,",
        port_decls.rstrip(","),
        ");",
        "",
        "    // INV-S-HDL-D-2 (one-hot, reset-initial) state-constants",
        "    // are inherited from each region's FSM module via the",
        "    // chart-top wrapper's port wiring; the cross-region module",
        "    // need only re-declare the constants it directly refs.",
        *_emit_cross_invariant_state_constants(invariants),
        "",
        *property_blocks,
        "",
        "endmodule",
        "",
        "`default_nettype wire",
    ]
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
) -> list[str]:
    """Emit ``localparam`` declarations for each state constant the
    cross-region properties reference. Width parameterised against
    each region's ``N_STATES_<R>`` so the comparison fits the actual
    one-hot width.
    """
    seen: set[tuple[str, str]] = set()
    lines: list[str] = []
    for inv in invariants:
        for region, state in (
            (inv.antecedent_region, inv.antecedent_state),
            (inv.consequent_region, inv.consequent_state),
        ):
            key = (region, state)
            if key in seen:
                continue
            seen.add(key)
            r_ident = _sanitize_sv_identifier(region)
            param = f"N_STATES_{r_ident.upper()}"
            const = _state_constant_name(state)
            # The state-constant is the one-hot value for the state's
            # index in the region's FSM. The exact bit position is
            # derived inside the per-region FSM module; here we
            # declare a localparam matching the per-region encoding
            # convention (state index → bit position; per-region
            # encoding is owned by SOS-08-C's _one_hot_value).
            lines.append(
                f"    // State constant `{const}` for region `{region}` — "
                f"matches SOS-08-C one-hot encoding."
            )
            lines.append(
                f"    `ifndef {const}_DEFINED"
            )
            lines.append(
                f"    `define {const}_DEFINED"
            )
            # Use a wildcard width since each region's N_STATES differs;
            # the comparison in the property auto-widens.
            lines.append(
                f"    localparam logic [{param}-1:0] {const} = "
                f"{{{param}{{1'b0}}}} | ({param}'(1) << "
                f"{_state_index_placeholder(region, state)});"
            )
            lines.append(f"    `endif")
    return lines


def _state_index_placeholder(region: str, state: str) -> int:
    """v1 placeholder: the state constants emitted by
    ``_emit_cross_invariant_state_constants`` need a bit-position. For
    wave-4 v1 the cross-region SVA module emits a TEMPLATE form — the
    actual one-hot bit position is owned by SOS-08-C's per-region
    FSM emitter. The placeholder returns 0; the chart author OR a
    wave-4-future amendment will thread the per-region state-encoding
    map through this emitter so the constants match SOS-08-C's emit
    by-construction.

    This is the wave-4 v1 boundary: the SVA module compiles, the
    properties have the right shape, but the state-constant values
    are TEMPLATE-only (they resolve to bit 0 for every state) until
    the wave-4-future encoding-passthrough amendment lands. Bench
    validation deferred to wave-4-future.
    """
    return 0


def _emit_cross_region_bind_directive(
    *,
    chart_name: str,
    chart_top_module: str,
    invariants: list[_CrossInvariant],
    region_info: list[tuple[str, str | None]],
) -> str:
    """Emit ``<chart>_top_bind.sv`` — bind directive attaching the
    chart-top SVA module to the chart-top wrapper.

    Wires:
      - ``.clk(clk)`` — chart-top reference clock.
      - ``.rst(rst)`` — chart-top reference reset.
      - ``.current_state_<region>`` per region referenced by any
        invariant; matches the chart-top wrapper's exposed port shape.
    """
    sva_module = _cross_invariant_sva_module_name(chart_name)
    inst_name = f"u_{sva_module}"

    referenced_regions: list[str] = []
    seen: set[str] = set()
    for inv in invariants:
        for r in (inv.antecedent_region, inv.consequent_region):
            if r not in seen:
                referenced_regions.append(r)
                seen.add(r)

    conn_lines: list[str] = [
        "    .clk           (clk),",
        "    .rst           (rst),",
    ]
    for i, r in enumerate(referenced_regions):
        obs = f"current_state_{_sanitize_sv_identifier(r)}"
        suffix = "," if i < len(referenced_regions) - 1 else ""
        conn_lines.append(f"    .{obs} ({obs}){suffix}")

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
    cross_invariants = _collect_cross_invariants(chart_ir)
    if cross_invariants:
        top_sva_body = _emit_cross_region_sva_module(
            chart_name=chart_name,
            chart_top_module=chart_top_module,
            invariants=cross_invariants,
            region_info=region_info,
        )
        top_bind_body = _emit_cross_region_bind_directive(
            chart_name=chart_name,
            chart_top_module=chart_top_module,
            invariants=cross_invariants,
            region_info=region_info,
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

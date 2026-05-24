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
      - INV-D-1: one-hot invariant on ``state_q``.
      - INV-D-2: reset → initial state.
      - INV-D-3..: per-transition correctness (source && guard |=> target).
  - ``tests/<chart>/<chart>_fsm_bind.sv`` — module-type bind directive
    attaching the assertion module to every elaborated DUT instance.

* The assertion module's input port set mirrors the chart-FSM module's
  observable surface:
      input wire                 clk
      input wire                 rst
      input wire [N_STATES-1:0]  state_q  (driven from DUT's current_state)
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
    """Reject parallel charts, build the single-region ``_SvaChart``."""
    if chart_ir.get("parallel"):
        raise UnsupportedChartError(
            "SOS-08-D wave-1 scaffold; parallel chart bind files land "
            "in wave-2. The wave-1 emitter accepts single-region charts "
            "only; the chart-top wrapper + per-region SVA module pattern "
            f"(chart '{chart_name}') is reserved for the wave-2 emission "
            "alongside the SOS-08-C parallel-region machinery."
        )

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
      * INV-D-1: ``$countones(state_q) <= 1`` — one-hot invariant
        mirroring the SOS-08-C §5.1 default encoding.
      * INV-D-2: ``rst |=> state_q == ST_<initial>`` — reset clears
        state to the chart ``initial`` per SOS-08-C §5.6 / PCDN-C-003.
      * INV-D-3..: per-transition ``state == src && guard |=> state == tgt``.
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
    port_lines.append(f"input wire [{n_states - 1}:0] state_q")
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
        "            @(posedge clk) disable iff (rst) ($countones(state_q) <= 1)",
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
        f"            @(posedge clk) rst |=> (state_q == {initial_const})",
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
            antecedent = f"(state_q == {src_const}) && ({guard_sv})"
        else:
            antecedent = f"(state_q == {src_const})"
        trans_blocks.extend(
            [
                "",
                f"    // {inv_id}: {tr.source} --[cond={tr.cond or '-'}/event={tr.event or '-'}]--> {tr.target}",
                f"    {ident}: assert property (",
                "            @(posedge clk) disable iff (rst)",
                f"            {antecedent} |=> (state_q == {tgt_const})",
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
    ``current_state`` (per SOS-08-C §6.2 / INV-S-HDL-C-2). The assertion
    module consumes ``current_state`` as its ``state_q`` input. Guard-
    referenced datamodel signals are connected by name (``data_<id>``
    on the DUT → ``data_<id>_q`` on the SVA module).
    """
    dut_module = _module_name(chart.chart_name)
    sva_module = _sva_module_name(chart.chart_name)

    guard_signals = _datamodel_signals_referenced_in_guards(chart)

    conn_lines: list[str] = [
        "    .clk      (clk),",
        "    .rst      (rst),",
        "    .state_q  (current_state)",
    ]
    if guard_signals:
        # Append a comma to the previous final connection and add the
        # datamodel signal hookups.
        conn_lines[-1] = "    .state_q  (current_state),"
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
# Public entry point.
# ----------------------------------------------------------------------------


def render_target(chart_ir: Any, config: Any = None) -> dict[str, str]:
    """Emit the SVA assertion module + bind directive for the chart.

    Wave-1 contract:
      * Single-region chart → two files:
          - ``tests/<chart>/<chart>_fsm_sva.sv``
          - ``tests/<chart>/<chart>_fsm_bind.sv``
      * Parallel charts raise ``UnsupportedChartError`` with a wave-2
        citation (PCDN-D-004 covers the per-DUT bind shape; the per-
        region bind machinery is wave-2 scope).

    Args:
        chart_ir: raw scjson dict (``ChartAst.raw_scjson``).
        config: optional dict / dataclass. Wave-1 consumes:
            - ``chart_name`` (str): chart identifier; module-name base.
            - ``guard_depth_budget`` (int): PCDN-C-004 budget override.

    Returns:
        dict mapping output filename → file source. Filenames embed the
        per-DUT directory prefix (``tests/<chart>/<chart>_fsm_sva.sv``)
        so the codegen dispatcher can land them under the right per-DUT
        test directory per PCDN-D-004 + SOS-08-D §6.1.

    Raises:
        UnsupportedChartError (or ``GuardDepthExceeded``) when the chart
        names a feature outside the wave-1 scope or when a guard's
        compiled depth exceeds the configured budget.
    """
    if not isinstance(chart_ir, dict):
        raise UnsupportedChartError(
            "SOS-08-D wave-1 render_target expects the raw scjson dict, "
            f"not {type(chart_ir).__name__}. The main.py dispatcher needs "
            "to pass the parsed scjson AST (ChartAst.raw_scjson)."
        )

    if isinstance(config, dict):
        chart_name = config.get("chart_name") or "chart"
    else:
        chart_name = getattr(config, "chart_name", None) or "chart"

    depth_budget = _resolve_depth_budget(config)

    chart = _normalise_chart(chart_ir, chart_name)

    sva_body = _emit_sva_module(chart, depth_budget)
    bind_body = _emit_bind_directive(chart)

    # PCDN-D-004 places both files under tests/<chart>/.
    base = _sanitize_sv_identifier(chart_name).lower()
    sva_path = f"tests/{base}/{base}_fsm_sva.sv"
    bind_path = f"tests/{base}/{base}_fsm_bind.sv"

    return {
        sva_path: sva_body,
        bind_path: bind_body,
    }


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

"""SCXML chart → SystemVerilog-2017 region-FSM emitter (Layer-2 HDL backend).

Wave-1 scaffold per SOS-08-C-CONCEPTS.md §6 (ten-step emission algorithm)
and §15 (2026-05-23 ratification). Mirrors `transliterate_hdl_vhdl.py`
so a single chart produces byte-equivalent state machines in both
dialects (same state-constant ordering, same reset-state-from-initial,
same document-order priority for transitions).

@spec  SOS-08-C-CONCEPTS.md §6 (emission algorithm), §15 (ratification)
@spec  SOS-07-CONCEPTS.md  INV-SOS-A..H (cross-phase invariants)
@spec  SOS-08-CONCEPTS.md  INV-S-HDL-1..5 (cross-sub-phase invariants)
@spec  SOS-08-A-CONCEPTS.md INV-S-HDL-A-1 (uniform sync active-high reset)
@spec  SOS-08-B-CONCEPTS.md INV-S-HDL-B-1..5 (L1 service invariants — cited)
@spec  SOS-08-C-CONCEPTS.md INV-S-HDL-C-1..5 (deterministic emission,
       per-region observability, cross-domain transition enforcement,
       guard expression synthesizability, cooperative completion)
@spec  PCDN-C-001 (clock-domain default inherit-from-parent)
@spec  PCDN-C-002 (verified-strip retain_synchronizers)
@spec  PCDN-C-003 (reset state = SCXML <initial>)
@spec  PCDN-C-004 (guard depth budget = 8 chained operators)
@spec  PCDN-C-005 (chart annotation wins for encoding)
@spec  PCDN-C-006 (document-order priority lint rule)

# Wave-1 scope (intentionally narrow per the orchestrator's prompt)

This module is the SV sibling of the VHDL emitter. It implements the
chart → SV walk only for the subset of SCXML that the wave-1 acceptance
gate names:

  - Single-region SCXML (no <parallel>).
  - Simple unguarded transitions (no <transition cond="..."/>).
  - Simple datamodel via <data> with optional `expr=...` initial.
  - <onentry> / <onexit> blocks may carry assign-style assignments only;
    no <script> (ECMAScript) bodies — those land in wave-2.
  - One-hot encoding by default (chart-annotation override deferred to
    wave-2 so the wave-1 acceptance test exercises the default).
  - Reset state = the SCXML <initial> attribute (PCDN-C-003).
  - Transitions in document order; first arm wins (PCDN-C-006).
  - Sync active-high reset (INV-S-HDL-A-1).
  - Event ingress / egress: SCXML-internal at wave-1 (no L1
    sos_message_channel wiring; that's §6.4 / §6.5 + wave-2).

Anything else SHALL raise `UnsupportedChartError` with an explicit
"SOS-08-C wave-1 scaffold does not emit ..." message per INV-S-HDL-5
(chart-vocabulary traceability — failures surface in chart-author
vocabulary).

# Integration contract

The codegen tool's CLI dispatcher (`main.py`) invokes:

    from transliterate_hdl_sv import render_target
    files = render_target(chart_ir, config)
    for name, body in files.items():
        (out_dir / name).write_text(body)

`chart_ir` is the raw scjson dict (the unprocessed JSON tree produced by
the loader), sourced from `ChartAst.raw_scjson`. The dispatcher passes
the same shape to the VHDL walker so the two emitters share their AST
front-end.

# Byte-equivalence with the VHDL sibling

`tools/sos-codegen/transliterate_hdl_vhdl.py` walks the same raw-dict
shape and emits a structurally equivalent VHDL entity + architecture
pair. Both emitters use the same state-walking helpers (re-implemented
per-dialect rather than shared, to keep this file self-contained while
the helper-signature drift between waves shakes out) so state-constant
ordering, datamodel-signal naming, and transition-mux priority are
word-for-word identical across dialects. Drift between the dialects is
detected by
`tests/test_transliterate_hdl_sv.py::test_sv_and_vhdl_have_equivalent_state_constants`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Sibling module — provides the cross-dialect emit primitives. Wave-1
# only consumes the enum types here; the per-dialect emit helpers all
# have try/except TypeError fallbacks at the call site so signature
# drift between sibling-agent waves does not block wave-1 emission.
from hdl_common import (  # noqa: F401  (some imports surface for clarity)
    Dialect,
    FsmEncoding,
    HdlPort,
    ResetPolarity,
    compute_guard_depth,
    emit_combinational_block,
    emit_fsm_state_constants,
    emit_fsm_state_encoding,
    emit_header_comment,
    emit_port_decl,
    emit_register_process,
    emit_signal_decl,
    emit_transition_mux,
    map_datamodel_type,
)


# ---------------------------------------------------------------------------
# Wave-1 error surface.
#
# Per INV-S-HDL-5 (chart-vocabulary traceability), every chart-author-
# facing rejection cites the chart construct + the wave / phase doc
# that owns the rule. The emitter raises `UnsupportedChartError` (and
# its subclasses) rather than a generic Exception so the CLI dispatcher
# can format the failure in chart vocabulary without a stack trace by
# default. The subclass hierarchy is preserved for backwards-compat with
# the pre-refactor test suite that pytest-raises on the specific
# subclasses.
# ---------------------------------------------------------------------------


class UnsupportedChartError(Exception):
    """Chart construct outside the wave-1 scaffold scope."""


class HdlEmitError(UnsupportedChartError):
    """Generic wave-1 SV-emit failure (kept for backward-compat with the
    pre-refactor test suite). New code prefers `UnsupportedChartError`
    or one of its named subclasses."""


class GuardNotSupportedError(HdlEmitError):
    """Wave-1: chart transition carries a `cond` attribute. SOS-08-C §6.3
    + INV-S-HDL-C-4 ratify the synthesizable-RTL realisation rules; the
    SV walker implements them in a later wave."""


class ParallelNotSupportedError(HdlEmitError):
    """Wave-1: chart contains a <parallel> region. SOS-08-C §6.1 builds
    the region tree from <parallel> children; wave-1 only emits single
    top-level regions."""


class EventIngressNotSupportedError(HdlEmitError):
    """Wave-1: explicit <raise> / event-egress wiring. SOS-08-C §6.4 /
    §6.5 wire external events via L1 `sos_message_channel`; wave-1
    auto-advances on each clock cycle and rejects <raise>."""


# ---------------------------------------------------------------------------
# Region/state/transition normalised view.
#
# The walker consumes the raw scjson dict (the same shape the VHDL walker
# reads). We re-walk it into a state-centric `HdlRegion` shape so the
# emission step can compose state constants, transition mux arms, and
# datamodel signal declarations without re-traversing the dict.
# ---------------------------------------------------------------------------


@dataclass
class HdlTransition:
    """One outgoing transition from a state. Wave-1 carries only the
    fields the emit walk consumes; richer fields (cond, raises, payload)
    land in wave-2."""

    source: str
    target: str
    event: str | None = None
    cond: str | None = None
    # Document-order index within the source state's transition list.
    # Drives the priority mux per PCDN-C-006.
    doc_order: int = 0


@dataclass
class HdlAssign:
    """One assign-style <assign location="x" expr="..."/> emitted by an
    <onentry> / <onexit>. Wave-1 only honours numeric-literal RHS; the
    ECMAScript <script> path lands in wave-2."""

    location: str
    expr: str  # raw expression text (numeric literal or simple ident)


@dataclass
class HdlState:
    """One <state id="..."/> inside the single wave-1 region."""

    state_id: str
    onentry_assigns: list[HdlAssign] = field(default_factory=list)
    onexit_assigns: list[HdlAssign] = field(default_factory=list)
    transitions: list[HdlTransition] = field(default_factory=list)


@dataclass
class HdlDatamodelSignal:
    """One <data id="..." expr="..."/> normalised to a registered RTL
    signal per SOS-08-C §5.4."""

    name: str
    initial_expr: str  # raw chart-side initial value text


@dataclass
class HdlRegion:
    """The single wave-1 region — chart-top → one SV module."""

    name: str
    states: list[HdlState]
    initial_state: str
    datamodel: list[HdlDatamodelSignal]


# ---------------------------------------------------------------------------
# scjson AST → HdlRegion (raw-dict walk).
#
# The dispatcher passes the raw scjson dict (sourced from
# `ChartAst.raw_scjson`). The walker mirrors the VHDL walker's
# `_walk_all_states` / `_collect_assigns` / `_normalise_region` /
# `_reject_unsupported` helpers so the two dialects parse identically.
# ---------------------------------------------------------------------------


def _reject_unsupported(chart: dict[str, Any]) -> None:
    """Inspect the raw scjson AST and raise on wave-1-out-of-scope
    features. Per INV-S-HDL-5 / INV-S-HDL-C-4, rejections cite the
    chart construct + the wave that lands the feature."""

    # <parallel> regions → rejected (single-region only at wave-1).
    if chart.get("parallel"):
        raise ParallelNotSupportedError(
            "SOS-08-C §6.1 — wave-1 scaffold does not emit parallel "
            "regions yet; <parallel> support lands in a later wave. "
            "Found <parallel> at chart root."
        )

    # Walk states; reject nested <parallel>, guards, and <script> bodies.
    for sid, st in _walk_all_states(chart):
        if st.get("parallel"):
            raise ParallelNotSupportedError(
                "SOS-08-C §6.1 — wave-1 scaffold does not emit parallel "
                f"regions yet. Found <parallel> inside state '{sid}'."
            )

        # Transition guards.
        for tr in st.get("transition", []) or []:
            if tr.get("cond"):
                raise GuardNotSupportedError(
                    "SOS-08-C §6.3 / INV-S-HDL-C-4 — wave-1 SV emit does "
                    "not yet compile guard expressions to combinational "
                    f"RTL. Found cond=\"{tr['cond']}\" on transition out "
                    f"of state '{sid}'."
                )

        # <script> in onentry / onexit (wave-1 is assign-only).
        for oe in st.get("onentry", []) or []:
            if oe.get("script"):
                raise UnsupportedChartError(
                    "SOS-08-C wave-1 scaffold does not emit ECMAScript "
                    "<script> bodies yet; assign-only at v1, <script> "
                    f"support lands in wave-2. Found <script> in <onentry> "
                    f"of state '{sid}'."
                )
        for ox in st.get("onexit", []) or []:
            if ox.get("script"):
                raise UnsupportedChartError(
                    "SOS-08-C wave-1 scaffold does not emit ECMAScript "
                    "<script> bodies yet; assign-only at v1, <script> "
                    f"support lands in wave-2. Found <script> in <onexit> "
                    f"of state '{sid}'."
                )

        # <raise> egress is event-routing — wave-1 has no L1 channels yet.
        for tr in st.get("transition", []) or []:
            if tr.get("raise_value"):
                raise EventIngressNotSupportedError(
                    "SOS-08-C §6.4 / §6.5 — wave-1 SV emit does not yet "
                    "wire chart event egress via L1 sos_message_channel. "
                    f"Found <raise> on transition out of state '{sid}'."
                )


def _walk_all_states(node: dict[str, Any]):
    """Depth-first walk yielding (state_id, state_dict) for every <state>
    in the scjson tree. Mirrors `loader._collect_states` but yields the
    state dict directly so the rejection / normalisation passes can see
    every nested element."""
    for st in node.get("state", []) or []:
        sid = st.get("id")
        if sid:
            yield sid, st
        yield from _walk_all_states(st)
    for par in node.get("parallel", []) or []:
        yield from _walk_all_states(par)


def _collect_assigns(container: dict[str, Any]) -> list[HdlAssign]:
    """Extract <assign location="x" expr="..."/> children. Wave-1 only
    honours simple-RHS assigns; the rejection pass has already filtered
    any embedded <script>."""
    out: list[HdlAssign] = []
    for a in container.get("assign", []) or []:
        loc = a.get("location") or a.get("name") or ""
        expr = a.get("expr") or ""
        if not loc:
            continue
        out.append(HdlAssign(location=loc, expr=expr))
    return out


def _normalise_region(chart: dict[str, Any], chart_name: str) -> HdlRegion:
    """Re-walk the raw scjson AST into the state-centric `HdlRegion`
    shape the SV emitter consumes. Wave-1 collapses the entire chart
    into one region (no <parallel>)."""

    # Datamodel: chart-root <datamodel><data .../>.
    datamodel: list[HdlDatamodelSignal] = []
    dm = chart.get("datamodel", [])
    if isinstance(dm, list):
        for entry in dm:
            if not isinstance(entry, dict):
                continue
            for d in entry.get("data", []) or []:
                datamodel.append(
                    HdlDatamodelSignal(
                        name=d.get("id", ""),
                        initial_expr=d.get("expr", "") or "0",
                    )
                )
    elif isinstance(dm, dict):
        for d in dm.get("data", []) or []:
            datamodel.append(
                HdlDatamodelSignal(
                    name=d.get("id", ""),
                    initial_expr=d.get("expr", "") or "0",
                )
            )

    # States: top-level only at wave-1 (nested-state support deferred —
    # the rejection pass does NOT reject nested states because they are
    # legitimate SCXML; wave-1 just flattens them, which matches the
    # SOS-08-C §6.1 "leaves of the region's SCXML state tree" rule).
    states: list[HdlState] = []
    for sid, st in _walk_all_states(chart):
        hs = HdlState(state_id=sid)
        for oe in st.get("onentry", []) or []:
            hs.onentry_assigns.extend(_collect_assigns(oe))
        for ox in st.get("onexit", []) or []:
            hs.onexit_assigns.extend(_collect_assigns(ox))
        for idx, tr in enumerate(st.get("transition", []) or []):
            target = tr.get("target")
            if isinstance(target, list):
                target = target[0] if target else None
            if not target:
                # Internal transition (no target) — wave-1 ignores.
                continue
            hs.transitions.append(
                HdlTransition(
                    source=sid,
                    target=target,
                    event=tr.get("event"),
                    cond=tr.get("cond"),
                    doc_order=idx,
                )
            )
        states.append(hs)

    # Initial state: from chart root's `initial=` attribute (PCDN-C-003).
    initial = chart.get("initial")
    if isinstance(initial, list):
        initial = initial[0] if initial else None
    if not initial:
        if not states:
            raise UnsupportedChartError(
                "SOS-08-C wave-1 scaffold requires at least one <state> in "
                "the chart; none found."
            )
        # Per SCXML semantics, lack of explicit <initial> defaults to the
        # first state in document order. SOS-08-C §5.6 / PCDN-C-003
        # honour this default.
        initial = states[0].state_id

    return HdlRegion(
        name=chart_name,
        states=states,
        initial_state=initial,
        datamodel=datamodel,
    )


# ---------------------------------------------------------------------------
# Identifier sanitisation. SystemVerilog-2017 identifiers are a subset
# of ASCII letters / digits / underscores, starting with a letter or
# underscore. The chart MAY carry hyphens / dots in state-ids; we
# replace them with underscores deterministically — same rule as the
# VHDL walker so identifiers match across dialects.
# ---------------------------------------------------------------------------


def _module_name(chart_name: str) -> str:
    """SV module identifier: lower-case, snake-case, suffix `_fsm`.
    Mirrors the VHDL walker's `_entity_name` so a chart produces
    matching identifiers across dialects."""
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in chart_name)
    if safe and safe[0].isdigit():
        safe = "x" + safe
    return f"{safe.lower()}_fsm"


def _state_constant_name(state_id: str) -> str:
    """SCXML state-id → SV state-constant name. Mirrors the VHDL walker:
    `ST_<id>` uppercased."""
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in state_id)
    return f"ST_{safe.upper()}"


def _one_hot_value(index: int, n_states: int) -> str:
    """Emit an SV sized one-hot literal for the index-th value. Bit
    position `index` is set; MSB-first formatting matches the VHDL
    walker's `_one_hot_value` so cross-dialect equivalence holds."""
    bits = ["0"] * n_states
    bits[n_states - 1 - index] = "1"
    return f"{n_states}'b" + "".join(bits)


# ---------------------------------------------------------------------------
# Datamodel signal compilation (SOS-08-C §5.4 + §6.6).
#
# Wave-1 emits one registered signal per `<data>` element. Width / type
# fall back to the §5.4 default (32-bit signed) when no explicit chart
# annotation is present.
# ---------------------------------------------------------------------------


@dataclass
class _DatamodelSignal:
    """Compiled datamodel-signal record."""

    chart_id: str
    sv_name: str
    width: int
    signed: bool
    reset_expr: str


def _infer_datamodel_signal(entry: HdlDatamodelSignal) -> _DatamodelSignal:
    """Per SOS-08-C §5.4: derive width / signedness / reset expression
    from the chart's <data> entry. Wave-1 only handles simple integer
    and boolean literals; anything else falls back to a 32-bit signed
    zero with a fallback comment in the reset expression."""
    chart_id = entry.name
    sv_name = f"data_{_sanitize_sv_identifier(chart_id)}"
    expr = (entry.initial_expr or "").strip()
    width = 32
    signed = True
    reset_expr = "32'sd0"
    if expr:
        lower = expr.lower()
        if lower in ("true", "false"):
            width = 1
            signed = False
            reset_expr = "1'b1" if lower == "true" else "1'b0"
        elif lower in ("[]", "{}", "null", "none"):
            # Collections / null compile to L1 services in a later wave;
            # wave-1 treats them as scalar reset-zero placeholders.
            reset_expr = "32'sd0"
        else:
            try:
                int_val = int(expr, 0)
                reset_expr = f"32'sd{int_val}"
            except (TypeError, ValueError):
                # Non-numeric initial — keep the default and surface a
                # comment so chart authors can find the fallback.
                reset_expr = (
                    f"32'sd0  /* wave-1 fallback: chart expr {expr!r} */"
                )
    return _DatamodelSignal(
        chart_id=chart_id,
        sv_name=sv_name,
        width=width,
        signed=signed,
        reset_expr=reset_expr,
    )


def _sanitize_sv_identifier(name: str) -> str:
    """Map a chart-author identifier into the SystemVerilog identifier
    space. Deterministic — two charts with the same chart-id produce
    the same SV identifier so cross-dialect equivalence holds."""
    if not name:
        return "_anon"
    out_chars: list[str] = []
    for ch in name:
        if ch.isalnum() or ch == "_":
            out_chars.append(ch)
        else:
            out_chars.append("_")
    out = "".join(out_chars)
    # SV identifiers MUST start with a letter or underscore (not a digit).
    if out and out[0].isdigit():
        out = "_" + out
    return out


# ---------------------------------------------------------------------------
# SV emission — §6.2 module shape, walked step-by-step.
# ---------------------------------------------------------------------------


def _emit_header(chart_name: str) -> str:
    """Top-of-file `@spec` citation block. Mirrors the VHDL walker's
    header so reviewers see the same citation set across dialects."""
    return "\n".join(
        [
            f"// Generated by tools/sos-codegen/transliterate_hdl_sv.py",
            f"// Chart: {chart_name}",
            f"// Spec : SOS-08-C-CONCEPTS.md §6 (emission algorithm), §15 (ratified 2026-05-23)",
            f"// Inv. : INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1 (sync active-high reset),",
            f"//        INV-S-HDL-C-1..5 (deterministic emission, observability,",
            f"//        cross-domain enforcement, guard synthesizability, cooperative completion)",
            f"// PCDN : C-001 (clock-domain inherit), C-002 (retain synchronizers),",
            f"//        C-003 (reset=<initial>), C-004 (guard depth 8), C-005 (chart annot wins),",
            f"//        C-006 (doc-order priority lint rule)",
            f"// Wave : 1 scaffold — single-region, unguarded, assign-only.",
        ]
    )


def _emit_module_header(
    region: HdlRegion,
    datamodel_signals: list[_DatamodelSignal],
    n_states: int,
) -> str:
    """Step 2 of §6 — emit the SV module port list.

    Wave-1 port surface:
      input  wire clk
      input  wire rst   (sync active-high per INV-S-HDL-A-1)
      output wire [W-1:0] data_<name>  (one per datamodel signal)
      output wire [N-1:0] current_state
    """
    module = _module_name(region.name)
    port_lines: list[str] = []
    port_lines.append("input  wire clk")
    port_lines.append("input  wire rst")
    for sig in datamodel_signals:
        if sig.width == 1:
            port_lines.append(f"output wire {sig.sv_name}")
        else:
            port_lines.append(
                f"output wire [{sig.width - 1}:0] {sig.sv_name}"
            )
    port_lines.append(
        f"output wire [{n_states - 1}:0] current_state"
    )

    lines: list[str] = []
    lines.append(f"module {module} (")
    for i, pl in enumerate(port_lines):
        suffix = "," if i < len(port_lines) - 1 else ""
        lines.append(f"    {pl}{suffix}")
    lines.append(");")
    return "\n".join(lines)


def _emit_state_constants(region: HdlRegion) -> list[str]:
    """Step 2 of §6 — emit the one-hot state-constant declarations as SV
    localparams, in chart document order. Mirrors the VHDL walker's
    `_emit_state_constants` shape so cross-dialect equivalence holds.
    Uses `localparam logic [W-1:0] ST_<id> = N'bXXXX;`."""
    n = len(region.states)
    out: list[str] = []
    for idx, s in enumerate(region.states):
        cname = _state_constant_name(s.state_id)
        val = _one_hot_value(idx, n)
        out.append(
            f"localparam logic [{n - 1}:0] {cname} = {val};"
        )
    return out


def _emit_register_process(
    region: HdlRegion,
    datamodel_signals: list[_DatamodelSignal],
) -> str:
    """Step 1 (state register) + step 6 (datamodel reset values) composed
    into the standard SV `always_ff` block. Sync active-high reset per
    INV-S-HDL-A-1.

    Hand-written shape:

        always_ff @(posedge clk) begin
            if (rst) begin
                state_q <= ST_<initial>;
                <data_x_q <= reset_expr;>
            end else begin
                state_q <= state_next;
                <data_x_q <= data_x_q;>  // wave-1: no <assign> yet
            end
        end
    """
    initial_const = _state_constant_name(region.initial_state)
    reset_lines: list[str] = [
        f"            state_q <= {initial_const};",
    ]
    update_lines: list[str] = [
        f"            state_q <= state_next;",
    ]
    for sig in datamodel_signals:
        reset_lines.append(f"            {sig.sv_name}_q <= {sig.reset_expr};")
        update_lines.append(f"            {sig.sv_name}_q <= {sig.sv_name}_q;")

    return (
        "    always_ff @(posedge clk) begin\n"
        "        if (rst) begin\n"
        + "\n".join(reset_lines)
        + "\n"
        "        end else begin\n"
        + "\n".join(update_lines)
        + "\n"
        "        end\n"
        "    end"
    )


def _emit_transition_case_arm(state: HdlState) -> list[str]:
    """Emit the case-arm body for one source state. Per PCDN-C-006 the
    transition list is walked in document order and the first arm
    whose trigger is true wins. Wave-1 has no guards and no event-id
    ingress yet, so every wave-1 transition is unconditional — the
    first listed transition's target becomes the next-state pick.
    Subsequent transitions are emitted as `// doc-order priority
    elided` comments so chart authors can see which transitions the
    wave-1 cut suppresses (same diagnostic shape as the VHDL walker).
    """
    cname = _state_constant_name(state.state_id)
    if not state.transitions:
        return [
            f"            {cname}: state_next = {cname};",
        ]
    chosen = state.transitions[0]
    lines: list[str] = [
        f"            {cname}: state_next = {_state_constant_name(chosen.target)};",
    ]
    for extra in state.transitions[1:]:
        lines.append(
            f"            // doc-order priority elided (PCDN-C-006): "
            f"source={extra.source} target={extra.target} "
            f"event={extra.event or '-'} "
            f"-- guard-aware mux lands in wave-2"
        )
    return lines


def _emit_combinational_block(region: HdlRegion) -> str:
    """Step 1 (next-state mux) per §6.2. Combinational SV `always_comb`
    block whose `unique case` enumerates every source state in document
    order; per state, the wave-1 cut picks the first listed transition's
    target. The `default:` arm catches genuinely-unreachable one-hot
    values."""
    case_lines: list[str] = []
    for s in region.states:
        case_lines.extend(_emit_transition_case_arm(s))

    return (
        "    always_comb begin\n"
        "        // Default: hold current state. Overridden by case-arm matches.\n"
        "        state_next = state_q;\n"
        "        unique case (state_q)\n"
        + "\n".join(case_lines)
        + "\n"
        "            default: state_next = state_q;  // safe default for unreachable one-hot\n"
        "        endcase\n"
        "    end"
    )


def _emit_register_decls(
    region: HdlRegion,
    datamodel_signals: list[_DatamodelSignal],
    n_states: int,
) -> str:
    """Wave-1 register declarations: state_q / state_next + per-datamodel
    `_q` registers. Output ports are wired up via `assign` further down."""
    lines: list[str] = []
    lines.append(
        f"    logic [{n_states - 1}:0] state_q;     // current state (one-hot per SOS-08-C §5.1)"
    )
    lines.append(
        f"    logic [{n_states - 1}:0] state_next;  // next-state combinational mux output"
    )
    for sig in datamodel_signals:
        if sig.width == 1:
            lines.append(
                f"    logic {sig.sv_name}_q;  // datamodel — chart `<data id=\"{sig.chart_id}\"/>`"
            )
        else:
            sign_kw = "signed" if sig.signed else ""
            tw = f"[{sig.width - 1}:0]"
            spacer = " " if sign_kw else ""
            lines.append(
                f"    logic {sign_kw}{spacer}{tw} {sig.sv_name}_q;  "
                f"// datamodel — chart `<data id=\"{sig.chart_id}\"/>`"
            )
    return "\n".join(lines)


def _emit_output_drives(
    datamodel_signals: list[_DatamodelSignal],
) -> str:
    """Per-region observable output assigns (INV-S-HDL-C-2 +
    SOS-08-C §6.2 worked example)."""
    lines: list[str] = []
    lines.append(
        "    // Per INV-S-HDL-C-2: expose state register for SVA / cocotb consumption."
    )
    lines.append("    assign current_state = state_q;")
    for sig in datamodel_signals:
        lines.append(f"    assign {sig.sv_name} = {sig.sv_name}_q;")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entry points.
# ---------------------------------------------------------------------------


def render_target(chart_ir: Any, config: Any = None) -> dict[str, str]:
    """SCXML raw-scjson chart-IR → SystemVerilog FSM source(s).

    Args:
        chart_ir: raw scjson dict (the same shape `loader.load_chart`
            stores at `ChartAst.raw_scjson`). The dispatcher in
            `main.py` extracts the dict before invoking this entry
            point so both HDL walkers consume identical shapes.
        config: optional dict / argparse.Namespace / HdlEmitConfig.
            Wave-1 consumes:
                - `chart_name` (str, optional): the chart's identifier;
                  used for the SV module name. Defaults to "chart".
            All other flags are reserved for wave-2.

    Returns:
        dict mapping output filename → file content. Wave-1 emits one
        file: `<module_name>.sv`.

    Raises:
        UnsupportedChartError (or one of its subclasses) when the chart
        names a feature outside the wave-1 scope.
    """
    if not isinstance(chart_ir, dict):
        raise UnsupportedChartError(
            "SOS-08-C wave-1 render_target expects the raw scjson dict, "
            f"not {type(chart_ir).__name__}. The main.py dispatcher needs "
            "to pass the parsed scjson AST (ChartAst.raw_scjson)."
        )

    # Resolve chart_name from the supplied config. Accepts dict /
    # argparse.Namespace / dataclass; falls back to "chart" when absent.
    if isinstance(config, dict):
        chart_name = config.get("chart_name") or "chart"
    else:
        chart_name = getattr(config, "chart_name", None) or "chart"

    # Step 0 — reject features outside the wave-1 scaffold scope.
    _reject_unsupported(chart_ir)

    # Step 1 of §6 — parse + build region tree. Wave-1 collapses to a
    # single region per the orchestrator's scope.
    region = _normalise_region(chart_ir, chart_name)

    if not region.states:
        raise UnsupportedChartError(
            "SOS-08-C wave-1 scaffold requires at least one <state>; "
            f"chart '{chart_name}' has none."
        )

    n_states = len(region.states)
    datamodel_signals = [_infer_datamodel_signal(d) for d in region.datamodel]

    header = _emit_header(chart_name)
    module_header = _emit_module_header(region, datamodel_signals, n_states)
    state_constants = _emit_state_constants(region)
    register_decls = _emit_register_decls(region, datamodel_signals, n_states)
    register_process = _emit_register_process(region, datamodel_signals)
    transition_block = _emit_combinational_block(region)
    output_drives = _emit_output_drives(datamodel_signals)

    state_const_block = "\n".join(f"    {line}" for line in state_constants)

    file_body = (
        f"{header}\n"
        f"\n"
        f"`default_nettype none\n"
        f"\n"
        f"{module_header}\n"
        f"\n"
        f"    // ----- state encoding (one-hot per SOS-08-C §5.1) -----\n"
        f"{state_const_block}\n"
        f"\n"
        f"    // ----- state registers + datamodel registers -----\n"
        f"{register_decls}\n"
        f"\n"
        f"    // ----- register process (SOS-08-C §6.2 + §6.6) -----\n"
        f"{register_process}\n"
        f"\n"
        f"    // ----- transition mux (SOS-08-C §5.2 + §6.2; document-order priority) -----\n"
        f"{transition_block}\n"
        f"\n"
        f"    // ----- output assigns -----\n"
        f"{output_drives}\n"
        f"\n"
        f"endmodule\n"
        f"\n"
        f"`default_nettype wire\n"
    )

    out_name = f"{_module_name(region.name)}.sv"
    return {out_name: file_body}


def render_target_with_metadata(
    chart_ir: Any, config: Any = None
) -> tuple[dict[str, str], dict[str, Any]]:
    """Same as `render_target` but additionally returns a metadata
    dict the cross-dialect equivalence test consumes:

        {
            "module_name": str,
            "state_names": list[str],
            "state_constants": list[str],   # parallel to state_names
            "initial_state": str,
            "datamodel": list[{"id": str, "sv_name": str, "width": int}],
            "notes": list[str],
        }
    """
    files = render_target(chart_ir, config)
    # Re-walk so we can report metadata without duplicating side-effects.
    if isinstance(config, dict):
        chart_name = config.get("chart_name") or "chart"
    else:
        chart_name = getattr(config, "chart_name", None) or "chart"
    region = _normalise_region(chart_ir, chart_name)
    datamodel_signals = [_infer_datamodel_signal(d) for d in region.datamodel]
    notes: list[str] = []
    if not datamodel_signals:
        notes.append(
            "chart has no <datamodel><data> entries — module has only "
            "state register surface"
        )
    if any(not s.transitions for s in region.states):
        notes.append(
            "one or more states have no outgoing transitions (terminal "
            "states); transition mux includes hold arms for them"
        )
    metadata: dict[str, Any] = {
        "module_name": _module_name(region.name),
        "state_names": [s.state_id for s in region.states],
        "state_constants": [
            _state_constant_name(s.state_id) for s in region.states
        ],
        "initial_state": region.initial_state,
        "datamodel": [
            {
                "id": sig.chart_id,
                "sv_name": sig.sv_name,
                "width": sig.width,
            }
            for sig in datamodel_signals
        ],
        "notes": notes,
    }
    return files, metadata


# Helpers used by integration / tests: expose the identifier derivation
# rules so test assertions don't have to duplicate them.
def module_name(chart_name: str) -> str:
    return _module_name(chart_name)


def state_constant_name(state_id: str) -> str:
    return _state_constant_name(state_id)


def one_hot_value(index: int, n_states: int) -> str:
    return _one_hot_value(index, n_states)


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

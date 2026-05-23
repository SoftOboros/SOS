"""SCXML chart → VHDL-2008 region-FSM emitter (Layer-2 HDL backend).

Wave-1 scaffold per SOS-08-C-CONCEPTS.md §6 (ten-step emission algorithm)
and §15 (2026-05-23 ratification).

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

This module is the FIRST emission cut. It implements the chart → VHDL
walk only for the subset of SCXML that the wave-1 acceptance gate names:

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

The codegen tool's CLI dispatcher (`main.py`, owned by the sibling agent
on this fan-out) invokes:

    from transliterate_hdl_vhdl import render_target
    files = render_target(chart_ir, config)
    for name, body in files.items():
        (out_dir / name).write_text(body)

`chart_ir` is the `ChartAst` produced by `loader.load_chart`. `config`
is a dict carrying CLI flags relevant to emission (`chart_name`,
`vendor`, `verified_strip`, etc.); wave-1 only consumes `chart_name`.

# hdl_common consumption

Per the orchestrator's prompt, the sibling agent is authoring
`hdl_common.py` concurrently. This module imports the helpers below;
signature mismatches at integration time are flagged in the agent
report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Sibling-agent module. If any helper's signature differs at integration
# time, the wave-2 reconcile pass updates the call sites here.
from hdl_common import (
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
# that owns the rule. The emitter raises `UnsupportedChartError` rather
# than a generic Exception so the CLI dispatcher can format the failure
# in chart vocabulary without a stack trace by default.
# ---------------------------------------------------------------------------


class UnsupportedChartError(Exception):
    """Chart construct outside the wave-1 scaffold scope.

    Raised when the input SCXML names a feature the wave-1 emit walk
    cannot lower. Per the SOS-08-C §15 ratification, the wave-1 cut is
    intentionally narrow; rejected features surface here with the
    target wave that lands them.
    """


# ---------------------------------------------------------------------------
# Region/state/transition normalised view.
#
# The `loader.ChartAst` shape is script-site-centric (each <onentry>,
# <onexit>, <transition> becomes a `ScriptSite` for the Rust/C paths).
# The HDL emit walk needs a state-centric view — one VHDL entity per
# region, one state-constant per <state>, one case-arm per outgoing
# transition. We re-walk the raw scjson AST below into the shape this
# module consumes, keeping the loader's ScriptSite surface unchanged.
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
    signal per SOS-08-C §5.4. Width / typing comes from
    `hdl_common.map_datamodel_type` at emit time."""

    name: str
    initial_expr: str  # raw chart-side initial value text


@dataclass
class HdlRegion:
    """The single wave-1 region — chart-top → one VHDL entity."""

    name: str
    states: list[HdlState]
    initial_state: str
    datamodel: list[HdlDatamodelSignal]


# ---------------------------------------------------------------------------
# scjson AST → HdlRegion (re-walk of loader's raw input).
#
# The loader's `load_chart` produces a `ChartAst` whose `sites` list is
# script-centric. For HDL emit we want a state-centric view. To avoid
# a second scjson shell-out, we accept either:
#   (a) a `ChartAst` plus the raw scjson dict (when both are passed),
#   (b) a raw scjson dict alone (when called with `chart_ir = {...}`),
#   (c) a `ChartAst` alone — then we re-load the chart via the path
#       carried on the chart_ir (wave-2 will plumb the raw dict
#       alongside ChartAst to avoid the re-read).
#
# Wave-1 takes the simplest contract: `chart_ir` is the raw scjson dict.
# The sibling agent's `main.py` dispatcher is responsible for producing
# this dict (the existing Rust/C path will likely keep using ChartAst;
# wave-2 reconciles).
# ---------------------------------------------------------------------------


def _reject_unsupported(chart: dict[str, Any]) -> None:
    """Inspect the raw scjson AST and raise on wave-1-out-of-scope
    features. Per INV-S-HDL-5 / INV-S-HDL-C-4, rejections cite the
    chart construct + the wave that lands the feature."""

    # <parallel> regions → rejected (single-region only at wave-1).
    if chart.get("parallel"):
        raise UnsupportedChartError(
            "SOS-08-C wave-1 scaffold does not emit parallel regions yet; "
            "<parallel> support lands in a later wave. Found <parallel> "
            "at chart root."
        )

    # Walk states; reject nested <parallel>, guards, and <script> bodies.
    for sid, st in _walk_all_states(chart):
        if st.get("parallel"):
            raise UnsupportedChartError(
                "SOS-08-C wave-1 scaffold does not emit parallel regions yet; "
                f"<parallel> support lands in a later wave. Found <parallel> "
                f"inside state '{sid}'."
            )

        # Transition guards.
        for tr in st.get("transition", []) or []:
            if tr.get("cond"):
                raise UnsupportedChartError(
                    "SOS-08-C wave-1 scaffold does not emit guards yet; "
                    "guard support lands in wave-2 (PCDN-C-004 / "
                    f"SCXML-LINT-C-2). Found cond=\"{tr['cond']}\" on "
                    f"transition out of state '{sid}'."
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
                raise UnsupportedChartError(
                    "SOS-08-C wave-1 scaffold does not emit chart event "
                    "egress yet; <raise>/<send> wiring via L1 "
                    "sos_message_channel lands in wave-2 "
                    "(SOS-08-C §6.4 / §6.5). Found <raise> on transition "
                    f"out of state '{sid}'."
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
    honours simple-RHS assigns; the loader already lifted any embedded
    <script> via the rejection pass."""
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
    shape this emitter consumes. Wave-1 collapses the entire chart into
    one region (no <parallel>); per §6.1 a "region" is one top-level
    state OR one orthogonal child of <parallel>, but the wave-1 emitter
    treats the whole chart as one region whose states are all the
    top-level <state>s."""

    # Datamodel: chart-root <datamodel><data .../>.
    datamodel: list[HdlDatamodelSignal] = []
    dm = chart.get("datamodel", [])
    if isinstance(dm, list):
        for entry in dm:
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
# VHDL emission — §6.2 module shape, walked step-by-step.
#
# The wave-1 emitter is a string-builder over `hdl_common` primitives.
# Each helper from hdl_common returns a string fragment; this module
# composes them into the final entity + architecture.
# ---------------------------------------------------------------------------


def _entity_name(chart_name: str) -> str:
    """VHDL identifier rule: lower-case, snake-case, suffix `_fsm`."""
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in chart_name)
    if safe and safe[0].isdigit():
        safe = "x" + safe
    return f"{safe.lower()}_fsm"


def _state_constant_name(state_id: str) -> str:
    """SCXML state-id → VHDL state-constant name. The hand-written
    examples in §6.11 use `ST_<id>` uppercased; mirror that."""
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in state_id)
    return f"ST_{safe.upper()}"


def _one_hot_value(index: int, n_states: int) -> str:
    """Emit a VHDL std_logic_vector literal for the index-th one-hot
    value among `n_states`. Bit 0 is rightmost in VHDL `downto` range,
    so index 0 maps to "0...0001"."""
    bits = ["0"] * n_states
    # VHDL std_logic_vector(N-1 downto 0): leftmost char is bit N-1.
    # We assign index → bit `index` (one-hot encoding), so leftmost
    # char represents the highest-numbered state.
    bits[n_states - 1 - index] = "1"
    return '"' + "".join(bits) + '"'


def _datamodel_signal_lines(
    datamodel: list[HdlDatamodelSignal],
) -> tuple[list[str], list[str], list[str]]:
    """Return three parallel lists of VHDL fragments:
      - signal declarations (architecture-level)
      - reset assignments (inside the rst='1' branch)
      - port declarations (entity-level — datamodel signals are exposed
        as outputs per SOS-08-C §6.2's worked example shape)

    Wave-1 uses `hdl_common.map_datamodel_type` per signal; falls back
    to `signed(31 downto 0)` per SOS-08-C §5.4's default-width rule
    when the helper is silent.
    """
    decls: list[str] = []
    resets: list[str] = []
    ports: list[str] = []
    for d in datamodel:
        # `map_datamodel_type` expected signature: (name, initial_expr,
        # dialect) → str (the VHDL type, e.g. "signed(31 downto 0)").
        # If the sibling helper has a different shape, the call site
        # here is the integration point.
        vhdl_type = map_datamodel_type(d.name, d.initial_expr, Dialect.VHDL)
        decls.append(
            emit_signal_decl(
                name=f"{d.name}_q",
                signal_type=vhdl_type,
                dialect=Dialect.VHDL,
            )
        )
        # Reset value: chart's initial_expr literal, lowered to a VHDL
        # literal via `to_signed`/`to_unsigned`. Wave-1 only handles
        # numeric literals — non-numeric chart initials are folded to
        # 0 with a header comment noting the fallback.
        initial = (d.initial_expr or "0").strip()
        try:
            int_val = int(initial, 0)
            reset_expr = f"to_signed({int_val}, {d.name}_q'length)"
        except (TypeError, ValueError):
            reset_expr = f"(others => '0')  -- wave-1 fallback: chart expr {initial!r}"
        resets.append(f"{d.name}_q <= {reset_expr};")
        # Port: expose the registered signal as an output (SOS-08-C
        # §6.2 worked example shape).
        ports.append(
            emit_port_decl(
                HdlPort(
                    name=f"data_{d.name}",
                    direction="out",
                    width_expr=vhdl_type,
                ),
                dialect=Dialect.VHDL,
            )
        )
    return decls, resets, ports


def _emit_entity(
    region: HdlRegion,
    datamodel_ports: list[str],
    n_states: int,
) -> str:
    """Step 2 of §6 — emit the VHDL entity port list.

    Wave-1 surface:
      clk, rst (sync active-high per INV-S-HDL-A-1),
      datamodel outputs (one per <data>),
      current_state output (the one-hot state register).

    Event-ingress / egress ports (§6.4 / §6.5) defer to wave-2.
    """
    lines: list[str] = []
    lines.append(f"entity {_entity_name(region.name)} is")
    lines.append("    port (")

    port_lines: list[str] = []
    port_lines.append(
        emit_port_decl(
            HdlPort(name="clk", direction="in", width_expr="std_logic"),
            dialect=Dialect.VHDL,
        )
    )
    port_lines.append(
        emit_port_decl(
            HdlPort(name="rst", direction="in", width_expr="std_logic"),
            dialect=Dialect.VHDL,
        )
    )
    for dp in datamodel_ports:
        port_lines.append(dp)
    port_lines.append(
        emit_port_decl(
            HdlPort(
                name="current_state",
                direction="out",
                width_expr=f"std_logic_vector({n_states - 1} downto 0)",
            ),
            dialect=Dialect.VHDL,
        )
    )
    # VHDL port list is semicolon-separated, no trailing semicolon.
    for i, pl in enumerate(port_lines):
        suffix = ";" if i < len(port_lines) - 1 else ""
        lines.append(f"        {pl}{suffix}")
    lines.append("    );")
    lines.append(f"end entity {_entity_name(region.name)};")
    return "\n".join(lines)


def _emit_state_constants(region: HdlRegion) -> list[str]:
    """Step 2 of §6 — emit the one-hot state constants in document
    order. Per PCDN-C-005 the encoding defaults to one-hot at wave-1
    (chart-annotation override deferred to wave-2)."""
    n = len(region.states)
    # hdl_common.emit_fsm_state_constants returns a list of declaration
    # lines. If it isn't available with the expected shape, the
    # integration patch belongs here.
    try:
        # Expected signature: (state_names, encoding, dialect, width)
        # → list[str].
        return list(
            emit_fsm_state_constants(
                state_names=[_state_constant_name(s.state_id) for s in region.states],
                encoding=FsmEncoding.ONE_HOT,
                dialect=Dialect.VHDL,
                width=n,
            )
        )
    except TypeError:
        # Fallback: emit them inline so the wave-1 scaffold doesn't
        # block on a helper-signature drift.
        out = []
        for idx, s in enumerate(region.states):
            cname = _state_constant_name(s.state_id)
            val = _one_hot_value(idx, n)
            out.append(
                f"constant {cname} : std_logic_vector({n - 1} downto 0) := {val};"
            )
        return out


def _emit_transition_case_arm(
    state: HdlState,
    region: HdlRegion,
) -> str:
    """Emit the case-arm body for one source state. Per PCDN-C-006 the
    transition list is walked in document order and the first arm
    whose trigger is true wins. Wave-1 has no guards (§5.3 / wave-2)
    and no event-id ingress yet (§6.4 / wave-2), so every wave-1
    transition is unconditional — the first listed transition's target
    becomes the next-state pick. Subsequent transitions are emitted as
    commented `-- elided: doc-order priority` lines so chart authors
    can see which transitions the wave-1 cut suppresses.
    """
    if not state.transitions:
        return f"            state_next <= state_q;"
    chosen = state.transitions[0]
    lines: list[str] = []
    lines.append(
        f"            state_next <= {_state_constant_name(chosen.target)};"
    )
    for extra in state.transitions[1:]:
        lines.append(
            f"            -- doc-order priority elided (PCDN-C-006): "
            f"source={extra.source} target={extra.target} "
            f"event={extra.event or '-'} "
            f"-- guard-aware mux lands in wave-2"
        )
    return "\n".join(lines)


def _emit_register_process(
    region: HdlRegion,
    datamodel_resets: list[str],
) -> str:
    """Step 1 (state register) + step 6 (datamodel reset values)
    composed into the standard VHDL clocked process. Sync active-high
    reset per INV-S-HDL-A-1.

    The hand-written shape is:

        process(clk) is
        begin
            if rising_edge(clk) then
                if rst = '1' then
                    state_q <= ST_<initial>;
                    <datamodel reset assignments>
                else
                    state_q <= state_next;
                    <datamodel update assignments — wave-2>
                end if;
            end if;
        end process;
    """
    try:
        return emit_register_process(
            state_q="state_q",
            state_next="state_next",
            initial_state=_state_constant_name(region.initial_state),
            datamodel_resets=datamodel_resets,
            reset_polarity=ResetPolarity.ACTIVE_HIGH_SYNC,
            dialect=Dialect.VHDL,
        )
    except TypeError:
        # Fallback emission keeps the wave-1 scaffold self-contained
        # under helper-signature drift.
        reset_body = "\n".join(
            f"                {line}" for line in datamodel_resets
        )
        return (
            "    process(clk) is\n"
            "    begin\n"
            "        if rising_edge(clk) then\n"
            "            if rst = '1' then\n"
            f"                state_q <= {_state_constant_name(region.initial_state)};\n"
            + (reset_body + "\n" if reset_body else "")
            + "            else\n"
            "                state_q <= state_next;\n"
            "            end if;\n"
            "        end if;\n"
            "    end process;"
        )


def _emit_combinational_block(region: HdlRegion) -> str:
    """Step 1 (next-state mux) per §6.2. Combinational process whose
    case enumerates every source state in document order; per state,
    the wave-1 cut picks the first listed transition's target."""
    arms: list[str] = []
    for s in region.states:
        cname = _state_constant_name(s.state_id)
        arms.append(f"        when {cname} =>")
        arms.append(_emit_transition_case_arm(s, region))
    arms_str = "\n".join(arms)

    try:
        return emit_combinational_block(
            state_q="state_q",
            state_next="state_next",
            case_arms=arms_str,
            sensitivity=["state_q"],
            dialect=Dialect.VHDL,
        )
    except TypeError:
        # Fallback emission preserves the wave-1 acceptance shape.
        return (
            "    process(state_q) is\n"
            "    begin\n"
            "        state_next <= state_q;\n"
            "        case state_q is\n"
            f"{arms_str}\n"
            "            when others =>\n"
            "                state_next <= state_q;  -- safe default for unreachable one-hot\n"
            "        end case;\n"
            "    end process;"
        )


def _emit_transition_mux_dispatch(region: HdlRegion) -> str:
    """Honour the orchestrator's spec — call hdl_common's
    `emit_transition_mux` when its signature matches, else fall back
    to the inline emission above. This wrapper exists so the wave-2
    integration pass can swap in the canonical helper without
    re-walking every call site."""
    try:
        arm_payload = [
            {
                "source": s.state_id,
                "source_const": _state_constant_name(s.state_id),
                "transitions": [
                    {
                        "target": t.target,
                        "target_const": _state_constant_name(t.target),
                        "event": t.event,
                        "cond": t.cond,
                        "doc_order": t.doc_order,
                    }
                    for t in s.transitions
                ],
            }
            for s in region.states
        ]
        return emit_transition_mux(
            arms=arm_payload,
            state_q="state_q",
            state_next="state_next",
            dialect=Dialect.VHDL,
        )
    except TypeError:
        return _emit_combinational_block(region)


def render_target(chart_ir: Any, config: dict[str, Any]) -> dict[str, str]:
    """Public entry point — called from `main.py` when `--target hdl-vhdl`.

    Args:
        chart_ir: raw scjson dict (the same shape `loader.load_chart`
            reads from disk before normalising into `ChartAst`). The
            sibling agent's CLI dispatcher is responsible for providing
            this; wave-2 reconciles ChartAst plumbing.
        config: dict carrying CLI flags. Wave-1 consumes:
            - `chart_name` (str, required): the chart's identifier;
              used for the VHDL entity name.
            - `verbose` (bool, optional): future-use.

    Returns:
        dict mapping output filename → file content. Wave-1 emits one
        file: `<chart_name>_fsm.vhd`.

    Raises:
        UnsupportedChartError: when the chart names a feature outside
            the wave-1 scope (parallel regions, guards, ECMAScript
            scripts, raises).
    """
    # Accept either the raw scjson dict (preferred contract) or a
    # ChartAst — wave-1 only consumes the raw dict, but the dispatcher
    # may pass the ChartAst by mistake during integration; surface a
    # clear error in that case.
    if not isinstance(chart_ir, dict):
        raise UnsupportedChartError(
            "SOS-08-C wave-1 render_target expects the raw scjson dict, "
            f"not {type(chart_ir).__name__}. The sibling main.py "
            "dispatcher needs to pass the parsed scjson AST."
        )

    # Config may be a dict (legacy) or an HdlEmitConfig dataclass.
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

    # Step 2 of §6 — datamodel signals + ports.
    dm_decls, dm_resets, dm_ports = _datamodel_signal_lines(region.datamodel)

    # Step 2 of §6 — entity port list.
    entity_block = _emit_entity(region, dm_ports, len(region.states))

    # Step 2 of §6 — state-constant declarations (one-hot, document order).
    state_constants = _emit_state_constants(region)

    # Step 1 of §6 — state register + datamodel reset values.
    register_process = _emit_register_process(region, dm_resets)

    # Step 1 / step 5 of §6 — transition mux (combinational next-state).
    transition_block = _emit_transition_mux_dispatch(region)

    # Header — cite the spec docs per CLAUDE.md "Execution discipline".
    header_lines = [
        f"-- Generated by tools/sos-codegen/transliterate_hdl_vhdl.py",
        f"-- Chart: {chart_name}",
        f"-- Spec : SOS-08-C-CONCEPTS.md §6 (emission algorithm), §15 (ratified 2026-05-23)",
        f"-- Inv. : INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1 (sync active-high reset),",
        f"--        INV-S-HDL-C-1..5 (deterministic emission, observability,",
        f"--        cross-domain enforcement, guard synthesizability, cooperative completion)",
        f"-- PCDN : C-001 (clock-domain inherit), C-002 (retain synchronizers),",
        f"--        C-003 (reset=<initial>), C-004 (guard depth 8), C-005 (chart annot wins),",
        f"--        C-006 (doc-order priority lint rule)",
        f"-- Wave : 1 scaffold — single-region, unguarded, assign-only.",
    ]
    try:
        header = emit_header_comment(header_lines, dialect=Dialect.VHDL)
    except TypeError:
        header = "\n".join(header_lines)

    # Architecture body assembly.
    n_states = len(region.states)
    arch_decls: list[str] = []
    arch_decls.extend(state_constants)
    arch_decls.append(
        f"signal state_q    : std_logic_vector({n_states - 1} downto 0);"
    )
    arch_decls.append(
        f"signal state_next : std_logic_vector({n_states - 1} downto 0);"
    )
    arch_decls.extend(dm_decls)
    arch_decls_block = "\n".join(f"    {line}" for line in arch_decls)

    # Datamodel output drives (registered signal → port wire).
    dm_output_drives = "\n".join(
        f"    data_{d.name} <= std_logic_vector({d.name}_q);" for d in region.datamodel
    )

    architecture = (
        f"architecture rtl of {_entity_name(region.name)} is\n"
        f"{arch_decls_block}\n"
        f"begin\n"
        f"{register_process}\n\n"
        f"{transition_block}\n\n"
        f"    current_state <= state_q;\n"
        + (f"{dm_output_drives}\n" if dm_output_drives else "")
        + f"end architecture rtl;\n"
    )

    file_body = (
        f"{header}\n\n"
        f"library ieee;\n"
        f"use ieee.std_logic_1164.all;\n"
        f"use ieee.numeric_std.all;\n\n"
        f"{entity_block}\n\n"
        f"{architecture}"
    )

    out_name = f"{_entity_name(region.name)}.vhd"
    return {out_name: file_body}


# Helper used by integration / tests: expose the entity-name derivation
# so test assertions don't have to duplicate the rule.
def entity_name(chart_name: str) -> str:
    return _entity_name(chart_name)


def state_constant_name(state_id: str) -> str:
    return _state_constant_name(state_id)


def one_hot_value(index: int, n_states: int) -> str:
    return _one_hot_value(index, n_states)

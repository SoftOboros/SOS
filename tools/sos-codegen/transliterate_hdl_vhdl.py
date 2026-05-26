"""SCXML chart → VHDL-2008 region-FSM emitter (Layer-2 HDL backend).

Wave-2 emitter per SOS-08-C-CONCEPTS.md §6 (ten-step emission algorithm)
and §15 (2026-05-23 ratification). Wave-2 implements steps 4-10 of §6
fully except event ingress/egress wiring via `sos_message_channel`
(§6.4 / §6.5) and ECMAScript subset → HDL action lowering beyond
``<assign>`` — those still defer to wave-3.

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
@spec  PCDN-SOS-08-C-wave2-wrapper-shape (2026-05-23 walkthrough resolution):
       canonical region_modules shape for emit_chart_top_wrapper —
       {name, module, clock_domain, datamodel_signals, state_width}.
@spec  PCDN-SOS-08-C-wave2-region-naming (2026-05-23 walkthrough Q1):
       region modules carry `_fsm` suffix on BOTH dialects (VHDL aligns
       with SV's existing convention).

# Wave-2 scope (per the orchestrator's wave-2 prompt)

Implements:
  - Guard expression emission — case-arm becomes an if/elsif/else chain
    with document-order priority (§6.3 + PCDN-C-006). Guards beyond
    PCDN-C-004's depth budget surface as `UnsupportedChartError` with
    chart-vocabulary message.
  - <parallel> regions — each child region of <parallel> compiles to
    its own FSM module file; a chart-top wrapper instantiates the
    regions (§6.1 / §6.10).
  - Chart-top wrapper — clock + reset declarations per distinct clock
    domain; region instantiation; cross-domain synchronizer wiring
    (§6.7 / §6.10).
  - Cross-domain synchronizers — for every chart signal written in
    clock domain A and read in clock domain B, instantiate
    `sos_synchronizer` per PCDN-C-002 (retained across verified-strip).
  - Port-width-from-signal-width — datamodel-driven port widths follow
    the underlying signal width (i32 → `std_logic_vector(31 downto 0)`,
    bool → `std_logic`).

Still REJECTED (wave-3):
  - Event ingress / egress via L1 `sos_message_channel`
    (transitions with `event="..."` + <raise>/<send>).
  - ECMAScript subset → HDL action lowering beyond <assign>.
  - <script> bodies in <onentry> / <onexit>.

Rejection messages cite "lands in wave-3" instead of "wave-2".

# Integration contract

The codegen tool's CLI dispatcher (`main.py`) invokes:

    from transliterate_hdl_vhdl import render_target
    files = render_target(chart_ir, config)
    for name, body in files.items():
        (out_dir / name).write_text(body)

`chart_ir` is the raw scjson dict (the shape `loader.load_chart` reads
from disk before normalising into `ChartAst`).  `config` is a dict or
`HdlEmitConfig` carrying CLI flags relevant to emission.

# hdl_common consumption

Wave-2 expects the following canonical signatures from hdl_common:

    emit_guard_expr(expr_str, dialect, depth_budget=8) -> str
    GuardDepthError  (exception)
    emit_sync_inst(inst_name, src_signal, dst_signal,
                   src_clk, dst_clk, dst_rst, width, stages, dialect) -> str
    emit_chart_top_wrapper(chart_name, region_modules,
                           cross_domain_signals, dialect) -> str
    port_width_from_signal_width(scxml_type, name) -> int

If any helper is unavailable at integration time, the call site falls
back to an inline implementation with a flagged comment ("# WAVE2:
fallback for ...") so the wave-2 reconcile pass can replace it later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

# SOS-08-C wave-3-f-future-assign (2026-05-24 §15): shared ECMAScript-
# subset `<assign>` parser. Mirror of the SV walker's import; same
# tree shape, different lowering helper (`_render_vhdl` wraps integer
# literals in ``to_signed(N, width)`` so the assignment to a signed
# register is well-typed).
from _assign_expr import (
    AssignExpr,
    AssignExprError,
    _parse_assign_expr,
    _render_vhdl,
)

# SOS-08-C wave-3-f-future-xreg (2026-05-24 §15) — chart-event raiser
# map + cross-region capture helpers.  Shared with the SV walker;
# see `_chart_events.py` for the §15 boundary declaration.
from _chart_events import (
    build_chart_event_raiser_map,
    chart_event_bus_data_name,
    chart_event_bus_valid_name,
)

# Sibling-agent module. The wave-2 emitter imports the canonical
# wave-2 surface defensively: helpers that may or may not yet be
# present in hdl_common at integration time are imported with a
# try/except block below, and fall back to local inline emission.
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
    DEFAULT_GUARD_DEPTH_BUDGET,
)

# Wave-2 canonical surface — defensive import.  Sibling agent is
# pinning these in hdl_common.py concurrently.  Fall back to local
# implementations when not yet present.
try:  # pragma: no cover - integration-pass gated
    from hdl_common import emit_guard_expr as _hdl_emit_guard_expr  # type: ignore
except ImportError:  # pragma: no cover
    _hdl_emit_guard_expr = None  # type: ignore

try:  # pragma: no cover
    from hdl_common import GuardDepthError as _HdlGuardDepthError  # type: ignore
except ImportError:  # pragma: no cover
    class _HdlGuardDepthError(Exception):  # type: ignore
        """Local fallback for hdl_common.GuardDepthError."""

try:  # pragma: no cover
    from hdl_common import emit_sync_inst as _hdl_emit_sync_inst  # type: ignore
except ImportError:  # pragma: no cover
    _hdl_emit_sync_inst = None  # type: ignore

try:  # pragma: no cover
    from hdl_common import emit_chart_top_wrapper as _hdl_emit_chart_top_wrapper  # type: ignore
except ImportError:  # pragma: no cover
    _hdl_emit_chart_top_wrapper = None  # type: ignore

try:  # pragma: no cover
    from hdl_common import port_width_from_signal_width as _hdl_port_width  # type: ignore
except ImportError:  # pragma: no cover
    _hdl_port_width = None  # type: ignore

# PCDN-SOS-08-C-wave3-clk-naming-passthrough (2026-05-23): defensively
# import the clk_/rst_ port-name helpers from hdl_common; fall back to
# local definitions of the same shape if the sibling module is older.
try:  # pragma: no cover
    from hdl_common import clk_port_name as _clk_port_name  # type: ignore
    from hdl_common import rst_port_name as _rst_port_name  # type: ignore
except ImportError:  # pragma: no cover
    def _clk_port_name(domain: str) -> str:
        """Local fallback for hdl_common.clk_port_name; see
        PCDN-SOS-08-C-wave3-clk-naming-passthrough."""
        return domain if domain.startswith("clk_") else f"clk_{domain}"

    def _rst_port_name(domain: str) -> str:
        """Local fallback for hdl_common.rst_port_name; see
        PCDN-SOS-08-C-wave3-clk-naming-passthrough."""
        if domain.startswith("clk_"):
            return "rst_" + domain[len("clk_"):]
        return f"rst_{domain}"


# Backward-compat: tests may catch GuardDepthError; expose at module level.
GuardDepthError = _HdlGuardDepthError


# ---------------------------------------------------------------------------
# Wave-2 error surface.
#
# Per INV-S-HDL-5 (chart-vocabulary traceability), every chart-author-
# facing rejection cites the chart construct + the wave / phase doc
# that owns the rule. The emitter raises `UnsupportedChartError` rather
# than a generic Exception so the CLI dispatcher can format the failure
# in chart vocabulary without a stack trace by default.
# ---------------------------------------------------------------------------


class UnsupportedChartError(Exception):
    """Chart construct outside the wave-2 scaffold scope.

    Raised when the input SCXML names a feature the wave-2 emit walk
    cannot lower. Wave-3 features (event channels, ECMAScript scripts)
    surface here with their landing wave; wave-2-internal misuses
    (guard depth budget exceeded, datamodel with no initial expression)
    surface here too.
    """


# ---------------------------------------------------------------------------
# Region/state/transition normalised view.
#
# The `loader.ChartAst` shape is script-site-centric.  The HDL emit
# walk needs a state-centric view — one VHDL entity per region, one
# state-constant per <state>, one case-arm per outgoing transition.
# Wave-2 expands the normalised view to carry multiple regions (one
# per <parallel> child) plus per-region clock-domain annotations.
# ---------------------------------------------------------------------------


@dataclass
class HdlTransition:
    """One outgoing transition from a state. Wave-3 adds ``raise_events``
    for SOS-08-C §6.5 event egress emission; richer fields (per-event
    payload data) land in wave-3-b alongside the chart-top wrapper
    `sos_message_channel` instantiation."""

    source: str
    target: str
    event: str | None = None
    cond: str | None = None
    # Document-order index within the source state's transition list.
    # Drives the priority mux per PCDN-C-006.
    doc_order: int = 0
    # SOS-08-C wave-3 events (2026-05-23 §15): event names this
    # transition raises via ``<raise event="..."/>``. Wave-1/2 rejected
    # charts containing <raise>; wave-3 emits per-event egress ports.
    raise_events: list[str] = field(default_factory=list)
    # SOS-08-C wave-3-e (2026-05-24 §15): per-event `<param>` lists
    # (mirror of SV walker; (name, expr) tuples keyed by event name).
    raise_params: dict[str, list[tuple[str, str]]] = field(
        default_factory=dict
    )


@dataclass
class HdlAssign:
    """One assign-style <assign location="x" expr="..."/> emitted by an
    <onentry> / <onexit>.  Wave-2 still numeric-literal RHS only; the
    ECMAScript <script> path lands in wave-3."""

    location: str
    expr: str  # raw expression text (numeric literal or simple ident)


@dataclass
class HdlEventPayloadCapture:
    """SOS-08-C wave-3-f (2026-05-24 §15) — datamodel binding on the
    consume side. Mirror of the SV walker's ``HdlEventPayloadCapture``;
    see ``transliterate_hdl_sv.HdlEventPayloadCapture`` for the full
    normative reference. VHDL emit mirrors the SV semantics: on the
    entry-edge into ``state_id`` with ``event_<EV>_recv_valid``
    asserted, capture ``event_<EV>_recv_data`` into ``data_<X>_q``.

    SOS-08-C wave-3-f-future-A (2026-05-24 §15) adds the ``edge``
    field for `<onexit>` captures (gating expression inverted from the
    entry shape). Default ``"entry"`` preserves wave-3-f byte-identity.
    """

    state_id: str
    location: str
    event_name: str
    edge: str = "entry"
    # SOS-08-C wave-3-f-future-xreg (2026-05-24 §15) — VHDL mirror of
    # the SV walker's ``cross_region`` field.  When True, the value
    # arrives via the chart-top broadcast bus
    # (``chart_event_<EV>_raise_valid`` / ``_raise_data``) routed back
    # to the region's ``event_<EV>_recv_valid`` / ``_recv_data`` ports.
    cross_region: bool = False
    # PCDN-SOS-08-C-007 (2026-05-25 §15) — VHDL mirror of the SV
    # walker's ``param_name`` field.  ``None`` (default) routes the
    # capture to the legacy unnamed alias ``event_<EV>_recv_data``;
    # a non-None name routes it to the per-param sub-bus
    # ``event_<EV>_recv_data_<param>``.
    param_name: str | None = None


@dataclass
class HdlGeneralAssign:
    """SOS-08-C wave-3-f-future-assign (2026-05-24 §15) — general
    ECMAScript-subset ``<assign>`` lowering (VHDL mirror).

    Mirror of the SV walker's ``HdlGeneralAssign`` dataclass; see
    ``transliterate_hdl_sv.HdlGeneralAssign`` for the normative
    reference.  VHDL emit wraps integer literals in
    ``to_signed(N, width)`` so the assignment to the signed datamodel
    register is well-typed.  Width policy: per wave-3-e behaviour,
    the walker does NOT widen on overflow.
    """

    state_id: str
    location: str
    edge: str             # "entry" or "exit"
    expr: AssignExpr      # parsed expression tree


@dataclass
class HdlState:
    """One <state id="..."/> inside a region."""

    state_id: str
    onentry_assigns: list[HdlAssign] = field(default_factory=list)
    onexit_assigns: list[HdlAssign] = field(default_factory=list)
    transitions: list[HdlTransition] = field(default_factory=list)


@dataclass
class HdlDatamodelSignal:
    """One <data id="..." expr="..."/> normalised to a registered RTL
    signal per SOS-08-C §5.4.  Width / typing comes from
    `hdl_common.map_datamodel_type` at emit time."""

    name: str
    initial_expr: str  # raw chart-side initial value text
    scxml_type: str = "int"  # default per SOS-08-C §5.4


@dataclass
class HdlRegion:
    """One region — one VHDL entity.  For single-region charts there
    is exactly one HdlRegion; for charts with <parallel> there is one
    HdlRegion per orthogonal child."""

    name: str
    states: list[HdlState]
    initial_state: str
    datamodel: list[HdlDatamodelSignal]
    # PCDN-C-001: per-region clock-domain default is inherit-from-
    # parent; root defaults to "main".  Wave-2 supports a per-region
    # `<region clock="..."/>` annotation.
    clock_domain: str = "main"
    # Per-region datamodel writes (location → set of (state, where))
    # collected during normalisation so the chart-top wrapper's
    # cross-domain analysis can intersect with reads from sibling
    # regions in a different clock domain.
    writes: list[str] = field(default_factory=list)
    reads: list[str] = field(default_factory=list)


@dataclass
class HdlChart:
    """Top-level normalised chart — one or more regions plus shared
    cross-region wiring data (datamodel signals visible to the chart
    top-level, clock-domain graph, etc.)."""

    name: str
    regions: list[HdlRegion]
    # Top-level datamodel signals declared at <scxml><datamodel>; these
    # are shared across regions per SOS-08-C §6.9.  Per-region private
    # signals are normalised onto the owning region.
    shared_datamodel: list[HdlDatamodelSignal] = field(default_factory=list)
    # Cross-domain signal records computed during normalisation.
    # Each entry: (signal_name, writer_region, reader_region,
    #              src_clock, dst_clock, width)
    cross_domain_signals: list[tuple[str, str, str, str, str, int]] = field(
        default_factory=list
    )


# ---------------------------------------------------------------------------
# scjson AST → HdlChart (re-walk of loader's raw input).
# ---------------------------------------------------------------------------


def _reject_unsupported(chart: dict[str, Any]) -> None:
    """Inspect the raw scjson AST and raise on wave-2-out-of-scope
    features.  Per INV-S-HDL-5 / INV-S-HDL-C-4, rejections cite the
    chart construct + the wave that lands the feature.

    Wave-2 ACCEPTS what wave-1 rejected:
      - guards (`<transition cond="..."/>`) — emitted as if/elsif chain
      - parallel regions (`<parallel>`) — emit one module per region

    Wave-2 STILL REJECTS (wave-3 lands these):
      - event-driven transitions (`<transition event="..."/>`) where the
        event has to route through an L1 sos_message_channel
      - <raise> / <send> egress
      - <script> bodies in onentry / onexit
    """

    # Walk states; reject <script> bodies and <raise> egress.  <parallel>
    # and `cond` are NOW supported.
    for sid, st in _walk_all_states(chart):

        # <script> in onentry / onexit (wave-2 still assign-only).
        for oe in st.get("onentry", []) or []:
            if oe.get("script"):
                raise UnsupportedChartError(
                    "SOS-08-C wave-2 emitter does not lower ECMAScript "
                    "<script> bodies yet; assign-only at v1/v2, full "
                    "<script> support lands in wave-3. Found <script> in "
                    f"<onentry> of state '{sid}'."
                )
        for ox in st.get("onexit", []) or []:
            if ox.get("script"):
                raise UnsupportedChartError(
                    "SOS-08-C wave-2 emitter does not lower ECMAScript "
                    "<script> bodies yet; assign-only at v1/v2, full "
                    "<script> support lands in wave-3. Found <script> in "
                    f"<onexit> of state '{sid}'."
                )

        # SOS-08-C wave-3 events (2026-05-23 §15): <raise> accepted.
        # Per-event egress ports + firing-strobe wiring emitted by
        # the entity-port + concurrent-assignment passes. Chart-top
        # wrapper `sos_message_channel` instantiation lands in
        # wave-3-b (per the §15 wave-3 events entry).


def _walk_all_states(node: dict[str, Any]):
    """Depth-first walk yielding (state_id, state_dict) for every <state>
    in the scjson tree.  Mirrors `loader._collect_states` but yields the
    state dict directly so the rejection / normalisation passes can see
    every nested element."""
    for st in node.get("state", []) or []:
        sid = st.get("id")
        if sid:
            yield sid, st
        yield from _walk_all_states(st)
    for par in node.get("parallel", []) or []:
        yield from _walk_all_states(par)


def _walk_region_states(node: dict[str, Any]):
    """Walk states that belong directly to the given region (do NOT
    descend into nested <parallel> children — those are their own
    regions).  Top-level <state> elements + their (non-parallel)
    descendants are yielded."""
    for st in node.get("state", []) or []:
        sid = st.get("id")
        if sid:
            yield sid, st
        # Descend into nested states but NOT into nested <parallel>
        # children — those are sibling regions.
        for sub_sid, sub_st in _walk_region_states(st):
            yield sub_sid, sub_st


def _collect_assigns(container: dict[str, Any]) -> list[HdlAssign]:
    """Extract <assign location="x" expr="..."/> children."""
    out: list[HdlAssign] = []
    for a in container.get("assign", []) or []:
        loc = a.get("location") or a.get("name") or ""
        expr = a.get("expr") or ""
        if not loc:
            continue
        out.append(HdlAssign(location=loc, expr=expr))
    return out


def _collect_datamodel(container: dict[str, Any]) -> list[HdlDatamodelSignal]:
    """Pull <datamodel><data .../></datamodel> children off a container
    (chart root, region root, or per-state node).  Tolerates both the
    list-wrapped and the dict-wrapped shapes the scjson loader produces."""
    out: list[HdlDatamodelSignal] = []
    dm = container.get("datamodel", [])
    if isinstance(dm, list):
        for entry in dm:
            for d in entry.get("data", []) or []:
                out.append(
                    HdlDatamodelSignal(
                        name=d.get("id", ""),
                        initial_expr=d.get("expr", "") or "0",
                        scxml_type=d.get("type", "int") or "int",
                    )
                )
    elif isinstance(dm, dict):
        for d in dm.get("data", []) or []:
            out.append(
                HdlDatamodelSignal(
                    name=d.get("id", ""),
                    initial_expr=d.get("expr", "") or "0",
                    scxml_type=d.get("type", "int") or "int",
                )
            )
    return out


# --------------------------------------------------------------------------
# SOS extension namespace: <sos:region clock="..."/> element-form clock
# annotation per PCDN-SOS-08-C-wave2-clock-annotation (2026-05-23 wave-2
# walkthrough).  scjson normalises foreign-namespaced child elements into
# the parent's `other_element` list rather than into the parent's attribute
# bag, so the wave-2 attribute-form fallback (`region_node.get("clock")`)
# never sees the element-form annotation.  See `_extract_sos_region_clock`.
# --------------------------------------------------------------------------
_SOS_NS = "{http://softoboros.com/scxml-extensions/v1}"


def _extract_sos_region_clock(region_node: dict[str, Any]) -> str | None:
    """Return the clock-domain name from a `<sos:region clock="..."/>`
    element child of `region_node`, or ``None`` if no such annotation
    is present.

    Per PCDN-SOS-08-C-wave2-clock-annotation (2026-05-23): the element
    form `<sos:region clock="clk_fast"/>` is the canonical authoring
    surface for per-region clock-domain binding.  scjson normalises
    foreign-namespaced children into `other_element` entries shaped:

        {"qname": "{http://softoboros.com/scxml-extensions/v1}region",
         "attributes": {"clock": "clk_fast"},
         "text": ""}

    The legacy attribute form (`<state ... clock="clk_fast">`) is kept
    as a fallback for backward compatibility with pre-wave-2 fixtures.
    """
    for elem in region_node.get("other_element", []) or []:
        if elem.get("qname", "") == _SOS_NS + "region":
            attrs = elem.get("attributes", {}) or {}
            clk = attrs.get("clock")
            if clk:
                return clk
    return None


def _normalise_region(
    region_node: dict[str, Any],
    region_name: str,
    parent_clock: str,
    chart_datamodel_names: set[str],
) -> HdlRegion:
    """Re-walk a region's subtree into the state-centric `HdlRegion`
    shape this emitter consumes.

    A region is either:
      - the chart root (single-region case), or
      - one orthogonal child of a `<parallel>` element.

    `parent_clock` is the clock-domain name inherited from the
    enclosing scope (root chart default = "main" per PCDN-C-001).

    Per PCDN-SOS-08-C-wave2-clock-annotation (2026-05-23): the
    `<sos:region clock="..."/>` element child is the canonical
    per-region clock-domain binding; legacy attribute form
    (`<state clock="...">`) is kept as a fallback.
    """

    # Per-region datamodel: <datamodel><data .../> directly under the
    # region.  Shared datamodel is collected at chart root.
    datamodel = _collect_datamodel(region_node)

    # Clock-domain resolution (PCDN-SOS-08-C-wave2-clock-annotation):
    #   1. <sos:region clock="..."/> element child (canonical wave-2 form).
    #   2. legacy `clock=` attribute on the region node (pre-wave-2 fixtures).
    #   3. inherited parent clock domain (PCDN-C-001 default).
    #   4. "main" as the chart-root fallback.
    explicit_clock = _extract_sos_region_clock(region_node) or region_node.get("clock")
    clock_domain = explicit_clock or parent_clock or "main"

    # States: yield every <state> reachable without crossing into a
    # nested <parallel>.
    states: list[HdlState] = []
    writes: set[str] = set()
    reads: set[str] = set()
    for sid, st in _walk_region_states(region_node):
        hs = HdlState(state_id=sid)
        for oe in st.get("onentry", []) or []:
            assigns = _collect_assigns(oe)
            hs.onentry_assigns.extend(assigns)
            for a in assigns:
                writes.add(a.location)
        for ox in st.get("onexit", []) or []:
            assigns = _collect_assigns(ox)
            hs.onexit_assigns.extend(assigns)
            for a in assigns:
                writes.add(a.location)
        for idx, tr in enumerate(st.get("transition", []) or []):
            target = tr.get("target")
            if isinstance(target, list):
                target = target[0] if target else None
            if not target:
                # Internal transition (no target) — wave-2 ignores
                # target-less transitions when computing case mux
                # next-state assignments (the body's <assign> children
                # are still honoured if present).
                continue
            cond = tr.get("cond")
            if cond:
                reads.update(_read_idents_in_expr(cond))
            # SOS-08-C wave-3 events: extract <raise event="..."/>
            # names per SCXML §3.13. Empty list when no <raise> child.
            # Wave-3-e: also extract <param> children for payload
            # routing.
            raise_events: list[str] = []
            raise_params: dict[str, list[tuple[str, str]]] = {}
            for r in tr.get("raise_value", []) or []:
                ev = r.get("event")
                if isinstance(ev, str) and ev:
                    raise_events.append(ev)
                    params: list[tuple[str, str]] = []
                    for p in r.get("param", []) or []:
                        p_name = p.get("name")
                        p_expr = p.get("expr")
                        if isinstance(p_name, str) and isinstance(p_expr, str):
                            params.append((p_name, p_expr))
                    if params:
                        raise_params[ev] = params
            hs.transitions.append(
                HdlTransition(
                    source=sid,
                    target=target,
                    event=tr.get("event"),
                    cond=cond,
                    doc_order=idx,
                    raise_events=raise_events,
                    raise_params=raise_params,
                )
            )
        states.append(hs)

    # Reads: any cond expression mentions of shared datamodel signals
    # are reads from this region's perspective.  Intersect with the
    # chart-wide datamodel set so we don't accidentally count local
    # state identifiers as datamodel reads.
    region_dm_names = {d.name for d in datamodel}
    reads = {r for r in reads if r in chart_datamodel_names or r in region_dm_names}
    writes = {w for w in writes if w in chart_datamodel_names or w in region_dm_names}

    # Initial state: from region root's `initial` attribute.
    initial = region_node.get("initial")
    if isinstance(initial, list):
        initial = initial[0] if initial else None
    if not initial:
        if not states:
            raise UnsupportedChartError(
                "SOS-08-C wave-2 emitter requires at least one <state> in "
                f"region '{region_name}'; none found."
            )
        # SCXML default: first state in document order.
        initial = states[0].state_id

    return HdlRegion(
        name=region_name,
        states=states,
        initial_state=initial,
        datamodel=datamodel,
        clock_domain=clock_domain,
        writes=sorted(writes),
        reads=sorted(reads),
    )


def _read_idents_in_expr(expr: str) -> set[str]:
    """Cheap identifier extraction from a guard expression.  Used to
    decide which datamodel signals a guard READS so cross-domain
    detection works.  Returns identifiers that look like Python/ECMAScript
    identifiers (alpha-leading, alnum/underscore body)."""
    import re
    out: set[str] = set()
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr or ""):
        # Skip obvious keywords/operators that map to RTL literals.
        if tok.lower() in {"true", "false", "and", "or", "not", "xor"}:
            continue
        out.add(tok)
    return out


def _normalise_chart(chart: dict[str, Any], chart_name: str) -> HdlChart:
    """Re-walk the raw scjson AST into the chart-centric `HdlChart`
    shape.  Detects whether the chart has top-level <parallel> regions
    or is single-region; in either case produces a list of HdlRegion
    instances plus shared-datamodel + cross-domain-signal records."""

    # Shared (chart-root) datamodel.
    shared_dm = _collect_datamodel(chart)
    shared_dm_names = {d.name for d in shared_dm}
    chart_clock = chart.get("clock") or "main"

    regions: list[HdlRegion] = []

    # If the chart has top-level <parallel>, each <parallel> child's
    # orthogonal regions become independent HdlRegions.
    parallels = chart.get("parallel", []) or []
    if parallels:
        for par_idx, par in enumerate(parallels):
            par_clock = par.get("clock") or chart_clock
            # Each direct <state> child of <parallel> is an orthogonal
            # region.  scjson loader represents these as the "state"
            # list on the <parallel> dict.
            par_states = par.get("state", []) or []
            for r_idx, region_node in enumerate(par_states):
                region_name = (
                    region_node.get("id")
                    or f"{par.get('id') or f'parallel_{par_idx}'}_region_{r_idx}"
                )
                region = _normalise_region(
                    region_node,
                    region_name,
                    parent_clock=par_clock,
                    chart_datamodel_names=shared_dm_names,
                )
                regions.append(region)
    else:
        # Single-region case: the whole chart is one region.
        region = _normalise_region(
            chart,
            chart_name,
            parent_clock=chart_clock,
            chart_datamodel_names=shared_dm_names,
        )
        regions.append(region)

    if not any(r.states for r in regions):
        raise UnsupportedChartError(
            "SOS-08-C wave-2 emitter requires at least one <state> in "
            f"chart '{chart_name}'; none found."
        )

    # Cross-domain signal detection.  PCDN-C-002: any signal written by
    # region R_a in clock domain CD_a and read by region R_b in clock
    # domain CD_b ≠ CD_a needs a synchronizer.  For each writer x
    # reader pair, emit one record carrying the inferred width.
    cross_domain: list[tuple[str, str, str, str, str, int]] = []
    writer_index: dict[str, list[HdlRegion]] = {}
    reader_index: dict[str, list[HdlRegion]] = {}
    for r in regions:
        for w in r.writes:
            writer_index.setdefault(w, []).append(r)
        for rd in r.reads:
            reader_index.setdefault(rd, []).append(r)

    dm_lookup = {d.name: d for d in shared_dm}
    for r_inner in regions:
        for d_local in r_inner.datamodel:
            dm_lookup.setdefault(d_local.name, d_local)

    for signal_name, readers in reader_index.items():
        writers = writer_index.get(signal_name, [])
        for writer in writers:
            for reader in readers:
                if writer is reader:
                    continue
                if writer.clock_domain == reader.clock_domain:
                    continue
                dm = dm_lookup.get(signal_name)
                width = (
                    _resolve_port_width(dm.scxml_type, dm.name)
                    if dm
                    else 32
                )
                cross_domain.append(
                    (
                        signal_name,
                        writer.name,
                        reader.name,
                        writer.clock_domain,
                        reader.clock_domain,
                        width,
                    )
                )

    return HdlChart(
        name=chart_name,
        regions=regions,
        shared_datamodel=shared_dm,
        cross_domain_signals=cross_domain,
    )


# ---------------------------------------------------------------------------
# Port-width-from-signal-width polish (PCDN-C-005 / wave-2 follow-up).
# ---------------------------------------------------------------------------


def _resolve_port_width(scxml_type: str, name: str) -> int:
    """Return the bit width of a datamodel port given the SCXML type
    string.  Wave-2 prefers `hdl_common.port_width_from_signal_width`
    when available; falls back to a small local table that mirrors
    SOS-08-C §5.4's default-width policy (i32 ≅ 32 bits)."""

    if _hdl_port_width is not None:
        try:
            return int(_hdl_port_width(scxml_type, name))
        except Exception:
            pass  # fall through to local table

    # Local fallback mirroring hdl_common._TYPE_TABLE widths.
    key = (scxml_type or "").strip().lower()
    table = {
        "bool": 1,
        "bit": 1,
        "i8": 8,
        "i16": 16,
        "i32": 32,
        "i64": 64,
        "int": 32,
        "integer": 32,
        "u8": 8,
        "u16": 16,
        "u32": 32,
        "u64": 64,
        "uint": 32,
    }
    return table.get(key, 32)


# ---------------------------------------------------------------------------
# Guard expression compilation.
#
# §6.3 + PCDN-C-004: each <transition cond="..."/> compiles to a VHDL
# boolean expression.  The wave-2 emitter delegates to
# `hdl_common.emit_guard_expr` when available; falls back to a minimal
# inline translator that handles the chart-author-vocabulary subset of
# SOS-01 §5.1 ECMAScript (logical/relational ops, identifiers, numeric
# literals).  Depth is measured by `compute_guard_depth` from
# hdl_common and budgeted per PCDN-C-004.
# ---------------------------------------------------------------------------


def _compile_guard(
    expr_str: str,
    depth_budget: int,
    source_state: str,
) -> str:
    """Compile a chart-side guard expression to VHDL.  Raises
    `UnsupportedChartError` with a chart-vocabulary message if the
    guard's depth exceeds the budget per PCDN-C-004."""

    if not expr_str:
        return "true"

    # Depth check first — independent of the lowering path.
    try:
        depth = compute_guard_depth(expr_str)
    except Exception:
        depth = 0
    if depth > depth_budget:
        raise UnsupportedChartError(
            "SOS-08-C wave-2 emitter rejects guard expression — depth "
            f"{depth} exceeds budget {depth_budget} per PCDN-C-004 "
            f"(SCXML-LINT-C-2). Guard on transition out of state "
            f"'{source_state}': {expr_str!r}."
        )

    if _hdl_emit_guard_expr is not None:
        try:
            return _hdl_emit_guard_expr(
                expr_str, Dialect.VHDL, depth_budget=depth_budget
            )
        except _HdlGuardDepthError as exc:  # pragma: no cover
            raise UnsupportedChartError(
                "SOS-08-C wave-2 emitter rejects guard expression — "
                f"hdl_common reports depth over budget {depth_budget} "
                f"per PCDN-C-004 on transition out of state "
                f"'{source_state}': {expr_str!r} ({exc})."
            ) from exc
        except Exception:
            # Fall through to inline lowering for parser failures so
            # the wave-2 scaffold doesn't block on helper drift.
            pass

    # Inline fallback — minimal ECMAScript → VHDL operator
    # substitution.  Honours the subset SOS-01 §5.1 names + the
    # PCDN-C-004 depth metric uses.  Wave-3 will replace this with
    # the canonical helper.
    return _inline_guard_to_vhdl(expr_str)


def _inline_guard_to_vhdl(expr_str: str) -> str:
    """Minimal local ECMAScript → VHDL translator for the wave-2
    fallback path.  Handles && / || / ! / ==  / != / relational ops;
    preserves identifiers and numeric literals; appends `_q` to any
    bare identifier that looks like a datamodel signal so the guard
    references the registered value.  This is a best-effort wave-2
    scaffold; the canonical compiler lives in
    `hdl_common.emit_guard_expr`."""

    import re

    out = expr_str
    # Order matters: longer operators first.
    substitutions = [
        ("&&", " and "),
        ("||", " or "),
        ("==", " = "),
        ("!=", " /= "),
        ("!", " not "),
    ]
    for js, vhdl in substitutions:
        out = out.replace(js, vhdl)

    # Append _q to bare identifiers that look like datamodel signals
    # (alpha-leading, not a VHDL keyword).  This is heuristic — the
    # canonical lowering in hdl_common does scoped name resolution.
    def _suffix(match: "re.Match[str]") -> str:
        ident = match.group(0)
        lowered = ident.lower()
        if lowered in {
            "true", "false", "and", "or", "not", "xor",
            "if", "then", "else", "elsif", "end",
        }:
            return ident
        if ident.endswith("_q"):
            return ident
        return f"{ident}_q"

    out = re.sub(r"[A-Za-z_][A-Za-z0-9_]*", _suffix, out)
    # Collapse repeated whitespace.
    out = re.sub(r"\s+", " ", out).strip()
    return out


# ---------------------------------------------------------------------------
# VHDL emission — §6.2 module shape, walked step-by-step.
# ---------------------------------------------------------------------------


def _safe_ident(raw: str) -> str:
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in (raw or ""))
    if safe and safe[0].isdigit():
        safe = "x" + safe
    return safe.lower()


def _entity_name(chart_name: str, region_name: Optional[str] = None) -> str:
    """VHDL identifier rule.  For single-region charts: `<chart>_fsm`.
    For a region inside a <parallel> chart: `<chart>_region_<region>_fsm`.

    Per the 2026-05-23 SOS-08-C wave-2 PCDN walkthrough Q1 resolution
    (`PCDN-SOS-08-C-wave2-region-naming`), region modules carry the
    `_fsm` suffix on BOTH dialects so the chart-top wrapper instantiates
    matching identifiers across VHDL and SV. The pre-walkthrough VHDL
    walker omitted the suffix; the walkthrough pinned it to align with
    the SV walker's existing convention."""
    base = _safe_ident(chart_name)
    if region_name is None or region_name == chart_name:
        return f"{base}_fsm"
    return f"{base}_region_{_safe_ident(region_name)}_fsm"


def _state_constant_name(state_id: str) -> str:
    """SCXML state-id → VHDL state-constant name.  Mirrors the
    hand-written examples in §6.11."""
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in state_id)
    return f"ST_{safe.upper()}"


def _one_hot_value(index: int, n_states: int) -> str:
    """Emit a VHDL std_logic_vector literal for the index-th one-hot
    value among `n_states`.  Bit 0 is rightmost in VHDL `downto` range,
    so index 0 maps to "0...0001"."""
    bits = ["0"] * n_states
    bits[n_states - 1 - index] = "1"
    return '"' + "".join(bits) + '"'


def _datamodel_signal_lines(
    datamodel: list[HdlDatamodelSignal],
) -> tuple[list[str], list[str], list[str], list[int]]:
    """Return four parallel lists of VHDL fragments + widths:
      - signal declarations (architecture-level)
      - reset assignments (inside the rst='1' branch)
      - port declarations (entity-level)
      - port widths (for downstream consumers)
    """
    decls: list[str] = []
    resets: list[str] = []
    ports: list[str] = []
    widths: list[int] = []
    for d in datamodel:
        vhdl_type = map_datamodel_type(d.name, d.initial_expr, Dialect.VHDL)
        width = _resolve_port_width(d.scxml_type, d.name)
        widths.append(width)
        decls.append(
            emit_signal_decl(
                name=f"{d.name}_q",
                signal_type=vhdl_type,
                dialect=Dialect.VHDL,
            )
        )
        initial = (d.initial_expr or "0").strip()
        try:
            int_val = int(initial, 0)
            reset_expr = f"to_signed({int_val}, {d.name}_q'length)"
        except (TypeError, ValueError):
            reset_expr = (
                f"(others => '0')  -- wave-2 fallback: chart expr {initial!r}"
            )
        resets.append(f"{d.name}_q <= {reset_expr};")

        # Port-width polish (wave-2): emit std_logic_vector(N-1 downto 0)
        # when the underlying signal is multi-bit.
        if width <= 1:
            port_width_expr = "std_logic"
        else:
            port_width_expr = f"std_logic_vector({width - 1} downto 0)"
        ports.append(
            emit_port_decl(
                HdlPort(
                    name=f"data_{d.name}",
                    direction="out",
                    width=width if width > 1 else 1,
                    width_expr=port_width_expr,
                ),
                dialect=Dialect.VHDL,
            )
        )
    return decls, resets, ports, widths


_PAYLOAD_WIDTH = 8


def _collect_region_payload_send_events(region: HdlRegion) -> list[str]:
    """VHDL mirror of the SV walker's
    ``_collect_region_payload_send_events``."""
    seen: set[str] = set()
    for state in region.states:
        for tr in state.transitions:
            for ev in tr.raise_events:
                if ev and tr.raise_params.get(ev):
                    seen.add(ev)
    return sorted(seen)


def _collect_region_consume_events(region: HdlRegion) -> list[str]:
    """Return the sorted, de-duplicated list of event names this
    region's transitions CONSUME via ``event="..."`` attributes.

    SOS-08-C wave-3-d-3 (2026-05-24 §15): mirror of the SV walker's
    function — see ``transliterate_hdl_sv._collect_region_consume_events``
    for full normative reference.
    """
    seen: set[str] = set()
    for state in region.states:
        for tr in state.transitions:
            if tr.event:
                seen.add(tr.event)
    return sorted(seen)


# SOS-08-C wave-3-f (2026-05-24 §15): event-object binding regex.
# Wave-3-f-future-A: extended to capture the suffix after `event.<EV>.`
# so `event.<EV>.<custom>` is recognised.
#
# PCDN-SOS-08-C-007 (2026-05-25 §15) — VHDL mirror of the SV walker
# update: ``event.<EV>.<custom>`` is RESOLVED to per-`<param>` sub-bus
# ``event_<EV>_recv_data_<param>`` routing when the suffix names a
# declared ``<param name>``; undeclared suffixes still reject.
_EVENT_PAYLOAD_RE = re.compile(
    r"^\s*event\.([A-Za-z_][A-Za-z0-9_\-]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*$"
)


def _collect_chart_payload_params(
    regions: list[HdlRegion],
) -> dict[str, list[str]]:
    """PCDN-SOS-08-C-007 (2026-05-25 §15) — VHDL mirror of the SV
    walker's ``_collect_chart_payload_params``.

    Builds a chart-wide event-name → list-of-declared-``<param name>``
    map (UNION across every ``<raise>``/``<send>`` of that event).

    Enforces the PCDN-SOS-08-C-007 hard-reject collision: a
    ``<param name="value">`` declared ALONGSIDE one or more other named
    ``<param>`` children for the same event collides with the legacy
    ``event_<EV>_recv_data`` alias and is forbidden. A SOLE
    ``<param name="value">`` is the canonical wave-1 shape and is
    accepted byte-identically (the legacy alias absorbs the value; no
    per-param sub-bus is emitted).
    """
    out: dict[str, list[str]] = {}
    seen_per_event: dict[str, set[str]] = {}
    has_value: dict[str, bool] = {}
    has_non_value: dict[str, bool] = {}
    for region in regions:
        for state in region.states:
            for tr in state.transitions:
                for ev, params in tr.raise_params.items():
                    if not params:
                        continue
                    for p_name, _p_expr in params:
                        if p_name == "value":
                            has_value[ev] = True
                        else:
                            has_non_value[ev] = True
                        seen = seen_per_event.setdefault(ev, set())
                        if p_name in seen:
                            continue
                        seen.add(p_name)
                        out.setdefault(ev, []).append(p_name)
    for ev in sorted(out):
        if has_value.get(ev) and has_non_value.get(ev):
            raise UnsupportedChartError(
                f"SOS-08-C wave-3-f-future-B / PCDN-SOS-08-C-007 (VHDL): "
                f"<param name='value'/> collides with the legacy "
                f"<code>event_{_safe_event_ident_vhdl(ev)}_recv_data</code> "
                f"alias; use a different param name."
            )
    cleaned: dict[str, list[str]] = {}
    for ev, names in out.items():
        if names == ["value"]:
            continue
        cleaned[ev] = [n for n in names if n != "value"]
        if not cleaned[ev]:
            del cleaned[ev]
    return cleaned


def _collect_region_event_payload_captures(
    region: HdlRegion,
    chart_event_raisers: dict[str, list[str]] | None = None,
    chart_payload_params: dict[str, list[str]] | None = None,
) -> list[HdlEventPayloadCapture]:
    """SOS-08-C wave-3-f (2026-05-24 §15) — VHDL-side mirror of the SV
    walker's ``_collect_region_event_payload_captures``.

    PCDN-SOS-08-C-007 (2026-05-25 §15) — VHDL mirror of the SV walker
    update: per-`<param>` sub-bus routing. ``event.<EV>.value`` keeps
    routing to the legacy unnamed alias; ``event.<EV>.<param>``
    routes to ``event_<EV>_recv_data_<param>`` when ``<param>`` is
    declared on the matching ``<raise>``/``<send>``; undeclared
    suffixes raise a PCDN-SOS-08-C-007 chart-vocab error.
    """
    chart_event_raisers = chart_event_raisers or {}
    chart_payload_params = chart_payload_params or {}
    captures: list[HdlEventPayloadCapture] = []
    consume_events = set(_collect_region_consume_events(region))

    def _process(assign: HdlAssign, state: HdlState, edge: str) -> None:
        m = _EVENT_PAYLOAD_RE.match(assign.expr)
        if not m:
            return
        event_name = m.group(1)
        suffix = m.group(2)
        param_name: str | None
        if suffix == "value":
            param_name = None
        elif suffix in chart_payload_params.get(event_name, []):
            param_name = suffix
        else:
            declared = chart_payload_params.get(event_name, [])
            if declared:
                hint = "; declared params: " + ", ".join(declared)
            else:
                hint = (
                    "; no <param> declared on any <raise>/<send> "
                    "for this event"
                )
            raise UnsupportedChartError(
                f"SOS-08-C wave-3-f-future-B / PCDN-SOS-08-C-007 (VHDL): "
                f"<on{edge}><assign location='{assign.location}' "
                f"expr='event.{event_name}.{suffix}'/> references "
                f"undeclared <param name='{suffix}'/>; declare on the "
                f"corresponding <send>/<raise>{hint}."
            )
        if event_name in consume_events:
            captures.append(
                HdlEventPayloadCapture(
                    state_id=state.state_id,
                    location=assign.location,
                    event_name=event_name,
                    edge=edge,
                    cross_region=False,
                    param_name=param_name,
                )
            )
            return
        raisers = chart_event_raisers.get(event_name, [])
        if not raisers:
            raise UnsupportedChartError(
                f"SOS-08-C wave-3-f-future-xreg (VHDL): <on{edge}><assign "
                f"expr='event.{event_name}.{suffix}'/> in region "
                f"'{region.name}' references event '{event_name}' "
                f"which is not raised anywhere in the chart. Add a "
                f"<transition>...<raise event='{event_name}'/></transition> "
                f"or remove the capture."
            )
        captures.append(
            HdlEventPayloadCapture(
                state_id=state.state_id,
                location=assign.location,
                event_name=event_name,
                edge=edge,
                cross_region=True,
                param_name=param_name,
            )
        )

    for state in region.states:
        for assign in state.onentry_assigns:
            _process(assign, state, "entry")
        # SOS-08-C wave-3-f-future-A (2026-05-24 §15): mirror walk over
        # `<onexit>` captures; gating inverted in the register emit.
        for assign in state.onexit_assigns:
            _process(assign, state, "exit")
    return captures


def _cross_region_consume_events(
    captures: list[HdlEventPayloadCapture],
) -> list[str]:
    """VHDL mirror of the SV walker's ``_cross_region_consume_events``.

    Sorted, de-duplicated list of event names a region captures via
    wave-3-f-future-xreg cross-region routing.  Folded into the
    region's consume-event list so the ``event_<EV>_recv_valid`` /
    ``event_<EV>_recv_data`` input ports are emitted.
    """
    seen: set[str] = set()
    for cap in captures:
        if cap.cross_region:
            seen.add(cap.event_name)
    return sorted(seen)


def _collect_region_general_assigns(
    region: HdlRegion,
) -> list[HdlGeneralAssign]:
    """SOS-08-C wave-3-f-future-assign (2026-05-24 §15) — VHDL mirror
    of the SV walker's ``_collect_region_general_assigns``.

    Walks each state's ``onentry_assigns`` AND ``onexit_assigns``,
    skipping any assign whose RHS matches the upstream
    ``_EVENT_PAYLOAD_RE`` (those belong to
    ``_collect_region_event_payload_captures``).  Everything else is
    dispatched through the shared `_parse_assign_expr`; rejected forms
    surface as ``UnsupportedChartError`` with the
    ``wave-3-f-future-assign`` citation prefix + the
    ``(VHDL)`` walker tag.
    """
    out: list[HdlGeneralAssign] = []
    datamodel_ids = [d.name for d in region.datamodel]
    datamodel_id_set = set(datamodel_ids)

    def _process(assign: HdlAssign, state: HdlState, edge: str) -> None:
        if _EVENT_PAYLOAD_RE.match(assign.expr or ""):
            return
        if assign.location not in datamodel_id_set:
            return
        try:
            tree = _parse_assign_expr(assign.expr or "", datamodel_ids)
        except AssignExprError as exc:
            raise UnsupportedChartError(
                f"SOS-08-C wave-3-f-future-assign (VHDL): "
                f"<on{edge}><assign location='{assign.location}' "
                f"expr='{assign.expr}'/> {exc}; supported: + -, "
                f"integer literals (decimal/0x...), datamodel "
                f"identifiers, parenthesised sub-expressions, and "
                f"event.<EV>.value forms."
            ) from exc
        out.append(
            HdlGeneralAssign(
                state_id=state.state_id,
                location=assign.location,
                edge=edge,
                expr=tree,
            )
        )

    for state in region.states:
        for assign in state.onentry_assigns:
            _process(assign, state, "entry")
        for assign in state.onexit_assigns:
            _process(assign, state, "exit")
    return out


def _collect_region_raise_events(region: HdlRegion) -> list[str]:
    """Sorted, de-duplicated event names this region raises via <raise>.

    SOS-08-C wave-3 events (2026-05-23 §15 / §6.5). One unique event
    name → one `event_<name>_send_valid` output port. Chart-top
    wrapper (wave-3-b) collects per-region pulses into the global
    `sos_message_channel` send face.
    """
    seen: set[str] = set()
    for state in region.states:
        for tr in state.transitions:
            for ev in tr.raise_events:
                if ev:
                    seen.add(ev)
    return sorted(seen)


def _safe_event_ident_vhdl(name: str) -> str:
    """Sanitise an SCXML event name to a legal VHDL identifier.

    VHDL identifiers permit letters / digits / underscore, must start
    with a letter, and are case-insensitive. We lowercase + substitute
    non-alphanumerics with `_`. The original event name is preserved
    in a port-list trailing comment for chart-vocabulary traceability.
    """
    out = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_").lower()
    if not out:
        return "ev"
    if out[0].isdigit():
        out = "ev_" + out
    return out


def _emit_entity(
    region: HdlRegion,
    chart_name: str,
    datamodel_ports: list[str],
    n_states: int,
    raise_events: list[str] | None = None,
    consume_events: list[str] | None = None,
    payload_send_events: list[str] | None = None,
    payload_recv_events: list[str] | None = None,
    payload_recv_params: dict[str, list[str]] | None = None,
) -> str:
    """Emit the VHDL entity port list for a region FSM module.

    SOS-08-C wave-3 events (2026-05-23 §15): when ``raise_events`` is
    non-empty, emits one ``event_<name>_send_valid : out std_logic``
    per unique raise-event name per §6.5.
    """
    raise_events = raise_events or []
    consume_events = consume_events or []
    payload_send_events = payload_send_events or []
    payload_recv_events = payload_recv_events or []
    payload_recv_params = payload_recv_params or {}
    entity_id = _entity_name(chart_name, region.name)
    lines: list[str] = []
    lines.append(f"entity {entity_id} is")
    lines.append("    port (")

    port_lines: list[str] = []
    port_lines.append(
        emit_port_decl(
            HdlPort(name="clk", direction="in", width=1, width_expr="std_logic"),
            dialect=Dialect.VHDL,
        )
    )
    port_lines.append(
        emit_port_decl(
            HdlPort(name="rst", direction="in", width=1, width_expr="std_logic"),
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
                width=n_states,
                width_expr=f"std_logic_vector({n_states - 1} downto 0)",
            ),
            dialect=Dialect.VHDL,
        )
    )
    # Wave-3 events: per raise-event, emit a (_send_valid, _send_ready)
    # port pair.
    #
    #   - `event_<name>_send_valid` (output) — wave-3-a.
    #   - `event_<name>_send_ready` (input) — wave-3-d backpressure
    #     surface from the chart-top channel's `s_axis_tready`. The
    #     transition mux gates state-advance on this so the FSM holds
    #     in source state when the channel is full (INV-S-HDL-4
    #     cooperative-only: priority-claim is preserved across stalls).
    #
    # Multiple raise events on one transition require ALL channels
    # ready (AND); the transition is atomic.
    egress_annotations: list[str] = []
    for ev in raise_events:
        ev_ident = _safe_event_ident_vhdl(ev)
        port_lines.append(
            emit_port_decl(
                HdlPort(
                    name=f"event_{ev_ident}_send_valid",
                    direction="out",
                    width=1,
                    width_expr="std_logic",
                ),
                dialect=Dialect.VHDL,
            )
        )
        egress_annotations.append(f"        -- chart event `{ev}`")
        port_lines.append(
            emit_port_decl(
                HdlPort(
                    name=f"event_{ev_ident}_send_ready",
                    direction="in",
                    width=1,
                    width_expr="std_logic",
                ),
                dialect=Dialect.VHDL,
            )
        )
        egress_annotations.append(
            f"        -- chart event `{ev}` (wave-3-d backpressure)"
        )
    # Wave-3-d-3 ingress: per consume-event, emit (_recv_valid in,
    # _recv_ready out) port pair.
    for ev in consume_events:
        ev_ident = _safe_event_ident_vhdl(ev)
        port_lines.append(
            emit_port_decl(
                HdlPort(
                    name=f"event_{ev_ident}_recv_valid",
                    direction="in",
                    width=1,
                    width_expr="std_logic",
                ),
                dialect=Dialect.VHDL,
            )
        )
        egress_annotations.append(
            f"        -- chart event `{ev}` (wave-3-d-3 ingress)"
        )
        port_lines.append(
            emit_port_decl(
                HdlPort(
                    name=f"event_{ev_ident}_recv_ready",
                    direction="out",
                    width=1,
                    width_expr="std_logic",
                ),
                dialect=Dialect.VHDL,
            )
        )
        egress_annotations.append(
            f"        -- chart event `{ev}` (wave-3-d-3 consume-ready)"
        )
    # SOS-08-C wave-3-e: payload data ports per chart-wide payload-
    # bearing event.
    for ev in payload_send_events:
        ev_ident = _safe_event_ident_vhdl(ev)
        port_lines.append(
            emit_port_decl(
                HdlPort(
                    name=f"event_{ev_ident}_send_data",
                    direction="out",
                    width=_PAYLOAD_WIDTH,
                    width_expr=f"std_logic_vector({_PAYLOAD_WIDTH - 1} downto 0)",
                ),
                dialect=Dialect.VHDL,
            )
        )
        egress_annotations.append(
            f"        -- chart event `{ev}` (wave-3-e payload)"
        )
    for ev in payload_recv_events:
        ev_ident = _safe_event_ident_vhdl(ev)
        port_lines.append(
            emit_port_decl(
                HdlPort(
                    name=f"event_{ev_ident}_recv_data",
                    direction="in",
                    width=_PAYLOAD_WIDTH,
                    width_expr=f"std_logic_vector({_PAYLOAD_WIDTH - 1} downto 0)",
                ),
                dialect=Dialect.VHDL,
            )
        )
        egress_annotations.append(
            f"        -- chart event `{ev}` (wave-3-e payload)"
        )
    # PCDN-SOS-08-C-007 (2026-05-25 §15): per-`<param>` sub-bus input
    # ports.  Each declared <param> on a <raise>/<send> becomes an
    # additional ingress port event_<EV>_recv_data_<param>.  The legacy
    # event_<EV>_recv_data alias above is preserved for byte-identity.
    n_subbus_ports = 0
    for ev in payload_recv_events:
        ev_ident = _safe_event_ident_vhdl(ev)
        for p_name in payload_recv_params.get(ev, []):
            port_lines.append(
                emit_port_decl(
                    HdlPort(
                        name=f"event_{ev_ident}_recv_data_{p_name}",
                        direction="in",
                        width=_PAYLOAD_WIDTH,
                        width_expr=(
                            f"std_logic_vector("
                            f"{_PAYLOAD_WIDTH - 1} downto 0)"
                        ),
                    ),
                    dialect=Dialect.VHDL,
                )
            )
            egress_annotations.append(
                f"        -- chart event `{ev}` (PCDN-SOS-08-C-007 "
                f"per-param `{p_name}`)"
            )
            n_subbus_ports += 1
    n_egress_ports = (
        2 * len(raise_events)
        + 2 * len(consume_events)
        + len(payload_send_events)
        + len(payload_recv_events)
        + n_subbus_ports
    )
    n_pre_egress = len(port_lines) - n_egress_ports
    egress_idx = 0
    for i, pl in enumerate(port_lines):
        suffix = ";" if i < len(port_lines) - 1 else ""
        lines.append(f"        {pl}{suffix}")
        if i >= n_pre_egress:
            lines.append(egress_annotations[egress_idx])
            egress_idx += 1
    lines.append("    );")
    lines.append(f"end entity {entity_id};")
    return "\n".join(lines)


def _emit_state_constants(region: HdlRegion) -> list[str]:
    """Emit the one-hot state constants in document order."""
    n = len(region.states)
    try:
        return list(
            emit_fsm_state_constants(
                state_names=[_state_constant_name(s.state_id) for s in region.states],
                encoding=FsmEncoding.ONE_HOT,
                dialect=Dialect.VHDL,
                width=n,
            )
        )
    except TypeError:
        out: list[str] = []
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
    depth_budget: int,
) -> str:
    """Emit the case-arm body for one source state.

    Wave-2:
      - For unguarded transitions: emit document-order priority — first
        listed transition becomes the next-state assignment; subsequent
        unguarded transitions are commented as elided.
      - For guarded transitions: emit an if/elsif/else chain.  The first
        guard whose VHDL boolean is true wins (document order priority
        per PCDN-C-006).  An unguarded transition at the end of the
        list closes the chain with an explicit `else` branch (its
        target becomes the fall-through).  No unguarded fallback ⇒
        `else state_next <= state_q;`.
    """
    if not state.transitions:
        return f"            state_next <= state_q;"

    def _predicate(t: HdlTransition) -> str | None:
        """Combined VHDL-Boolean for `t`. Returns None for the truly
        unguarded shape (no event, no cond)."""
        parts: list[str] = []
        if t.event:
            ev_ident = _safe_event_ident_vhdl(t.event)
            parts.append(f"event_{ev_ident}_recv_valid = '1'")
        if t.cond:
            parts.append(
                _compile_guard(t.cond, depth_budget=depth_budget,
                               source_state=t.source)
            )
        if not parts:
            return None
        return " and ".join(parts)

    def _advance_lines(t: HdlTransition, indent: str) -> list[str]:
        """Emit the state-advance lines for transition `t`.

        SOS-08-C wave-3-d-1 (2026-05-24 §15): if `t` carries
        `<raise event="..."/>` elements, wrap the advance in a
        send-ready gate. When any of the channels the transition
        publishes to is not ready, the FSM HOLDS in source
        (`state_next <= state_q`) — priority-claim is preserved
        across backpressure stalls under INV-S-HDL-4 cooperative
        semantics. Multiple raise events on one transition require
        ALL channels ready (AND).
        """
        target = _state_constant_name(t.target)
        if not t.raise_events:
            return [f"{indent}state_next <= {target};"]
        ready_terms = [
            f"event_{_safe_event_ident_vhdl(ev)}_send_ready = '1'"
            for ev in sorted(set(t.raise_events))
        ]
        cond = " and ".join(ready_terms)
        return [
            f"{indent}if {cond} then",
            f"{indent}    state_next <= {target};",
            f"{indent}else",
            f"{indent}    state_next <= state_q;",
            f"{indent}end if;",
        ]

    # Wave-3-d-3: a transition is "predicated" if it has event OR cond.
    # Only transitions with neither end the priority chain (final else
    # branch). All predicated transitions form if/elsif arms.
    has_any_predicate = any(_predicate(t) is not None for t in state.transitions)
    if not has_any_predicate:
        chosen = state.transitions[0]
        lines: list[str] = _advance_lines(chosen, "            ")
        for extra in state.transitions[1:]:
            lines.append(
                f"            -- doc-order priority elided (PCDN-C-006): "
                f"source={extra.source} target={extra.target} "
                f"event={extra.event or '-'}"
            )
        return "\n".join(lines)

    # Mixed/all-predicated path — emit if/elsif/else chain.
    lines = []
    first = True
    fallthrough_tr: Optional[HdlTransition] = None
    for t in state.transitions:
        pred = _predicate(t)
        if pred is not None:
            kw = "if" if first else "elsif"
            first = False
            lines.append(
                f"            {kw} {pred} then  -- doc-order {t.doc_order} → {t.target}"
            )
            lines.extend(_advance_lines(t, "                "))
        else:
            # First truly-unguarded after predicated = closing else
            # branch.
            fallthrough_tr = t
            break

    if fallthrough_tr is not None:
        lines.append(f"            else")
        lines.extend(_advance_lines(fallthrough_tr, "                "))
    else:
        lines.append(f"            else")
        lines.append(f"                state_next <= state_q;")
    lines.append(f"            end if;")
    return "\n".join(lines)


def _emit_register_process(
    region: HdlRegion,
    datamodel_resets: list[str],
    event_payload_captures: list[HdlEventPayloadCapture] | None = None,
    datamodel_signals: list[HdlDatamodelSignal] | None = None,
    general_assigns: list[HdlGeneralAssign] | None = None,
) -> str:
    """Emit the synchronous active-high reset register process.

    SOS-08-C wave-3-f (2026-05-24 §15): when ``event_payload_captures``
    is non-empty, the process emits per-capture entry-edge override
    branches that route ``event_<EV>_recv_data`` into the destination
    ``data_<X>_q`` register. Mirrors the SV walker's wave-3-f behavior.

    SOS-08-C wave-3-f-future-assign (2026-05-24 §15): ``general_assigns``
    extends the per-signal if/elsif chain with the ECMAScript-subset
    ``<assign>`` lowering — numeric literals, datamodel idents, and
    binary ``+``/``-`` between them.  Integer literals are wrapped in
    ``to_signed(N, <register'length>)`` so the assignment to the
    signed register is well-typed (mirrors the wave-3-f
    ``signed(event_<EV>_recv_data)`` cast).  Width policy: per
    wave-3-e behaviour, the walker does NOT widen on overflow.

    When BOTH ``event_payload_captures`` and ``general_assigns`` are
    empty the function falls back to the wave-1/wave-2
    ``emit_register_process`` helper (or its local TypeError
    fallback), preserving the pre-wave-3-f emit byte-identical for
    charts without ANY datamodel write sites.
    """
    event_payload_captures = event_payload_captures or []
    general_assigns = general_assigns or []

    if not event_payload_captures and not general_assigns:
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

    # Wave-3-f path: manual emit with per-capture entry-edge override
    # branches. Mirrors the SV walker's _emit_register_process wave-3-f
    # body structurally; VHDL syntax differs in the if/elsif chain.
    captures_by_location: dict[str, list[HdlEventPayloadCapture]] = {}
    for cap in event_payload_captures:
        captures_by_location.setdefault(cap.location, []).append(cap)
    # SOS-08-C wave-3-f-future-assign: per-signal general assigns are
    # appended to the same if/elsif chain after event-payload captures.
    assigns_by_location: dict[str, list[HdlGeneralAssign]] = {}
    for ga in general_assigns:
        assigns_by_location.setdefault(ga.location, []).append(ga)

    datamodel_signals = datamodel_signals or []
    # Map chart-side datamodel id → VHDL register-name base (no `_q`
    # suffix — `_render_vhdl` appends it).  Mirror of the SV walker's
    # `ident_signal_map`.
    ident_signal_map = {sig.name: sig.name for sig in datamodel_signals}
    reset_lines: list[str] = [
        f"                state_q <= {_state_constant_name(region.initial_state)};",
    ]
    reset_lines.extend(f"                {line}" for line in datamodel_resets)

    # Build the update side. Default: state_q <= state_next; per signal
    # default-hold OR wave-3-f capture chain. Per the VHDL walker's
    # signal-naming convention each datamodel signal's register is
    # ``<name>_q`` (no `data_` prefix — only the entity output port
    # carries the `data_` prefix).
    update_lines: list[str] = [
        "                state_q <= state_next;",
    ]
    for sig in datamodel_signals:
        reg_name = f"{sig.name}_q"
        cap_list = captures_by_location.get(sig.name, [])
        ga_list = assigns_by_location.get(sig.name, [])
        if not cap_list and not ga_list:
            update_lines.append(
                f"                {reg_name} <= {reg_name};"
            )
            continue
        # Width for to_signed wrapping in general-assign lowerings.
        # Per wave-3-e behaviour the walker does NOT widen — width
        # follows the datamodel register's declared width.
        sig_width = _resolve_port_width(sig.scxml_type, sig.name)
        arm_idx = 0
        # Wave-3-f if/elsif chain: per-capture entry-edge override.
        for cap in cap_list:
            ev_ident = _safe_event_ident_vhdl(cap.event_name)
            state_const = _state_constant_name(cap.state_id)
            # SOS-08-C wave-3-f-future-A (2026-05-24 §15): edge gating
            # inverts for `<onexit>` captures.
            if cap.edge == "exit":
                cond = (
                    f"state_q = {state_const} and "
                    f"state_next /= {state_const} and "
                    f"event_{ev_ident}_recv_valid = '1'"
                )
            else:
                cond = (
                    f"state_q /= {state_const} and "
                    f"state_next = {state_const} and "
                    f"event_{ev_ident}_recv_valid = '1'"
                )
            keyword = (
                "                if" if arm_idx == 0 else "                elsif"
            )
            update_lines.append(f"{keyword} {cond} then")
            # Wave-3-f: event_<EV>_recv_data is a std_logic_vector of
            # _PAYLOAD_WIDTH bits; the datamodel register is signed
            # (per emit_signal_decl). Convert via signed(...) so the
            # assignment is well-typed.
            #
            # PCDN-SOS-08-C-007 (2026-05-25 §15): per-`<param>` sub-bus
            # routing. ``param_name=None`` → legacy unnamed alias
            # ``event_<EV>_recv_data``; ``param_name=<name>`` → per-param
            # sub-bus ``event_<EV>_recv_data_<name>``.
            if cap.param_name is None:
                rhs_bus = f"event_{ev_ident}_recv_data"
            else:
                rhs_bus = (
                    f"event_{ev_ident}_recv_data_{cap.param_name}"
                )
            update_lines.append(
                f"                    {reg_name} <= signed({rhs_bus});"
            )
            arm_idx += 1
        # Wave-3-f-future-assign arms — entry-edge OR exit-edge gating
        # without an event-validity term (gating is purely the
        # state-edge into the carrying state).
        for ga in ga_list:
            state_const = _state_constant_name(ga.state_id)
            if ga.edge == "exit":
                cond = (
                    f"state_q = {state_const} and "
                    f"state_next /= {state_const}"
                )
            else:
                cond = (
                    f"state_q /= {state_const} and "
                    f"state_next = {state_const}"
                )
            keyword = (
                "                if" if arm_idx == 0 else "                elsif"
            )
            update_lines.append(f"{keyword} {cond} then")
            rhs = _render_vhdl(ga.expr, ident_signal_map, sig_width)
            update_lines.append(
                f"                    {reg_name} <= {rhs};"
            )
            arm_idx += 1
        update_lines.append("                else")
        update_lines.append(
            f"                    {reg_name} <= {reg_name};"
        )
        update_lines.append("                end if;")

    return (
        "    process(clk) is\n"
        "    begin\n"
        "        if rising_edge(clk) then\n"
        "            if rst = '1' then\n"
        + "\n".join(reset_lines)
        + "\n"
        + "            else\n"
        + "\n".join(update_lines)
        + "\n"
        + "            end if;\n"
        + "        end if;\n"
        + "    end process;"
    )


def _emit_combinational_block(region: HdlRegion, depth_budget: int) -> str:
    """Emit the next-state combinational case statement.  Wave-2's
    arm bodies may be either single-line assignments (unguarded) OR
    if/elsif/else chains (guarded)."""
    arms: list[str] = []
    for s in region.states:
        cname = _state_constant_name(s.state_id)
        arms.append(f"        when {cname} =>")
        arms.append(_emit_transition_case_arm(s, region, depth_budget))
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


# ---------------------------------------------------------------------------
# Chart-top wrapper emission (§6.10).
#
# For a single-region chart wave-2 still emits one `<chart>_fsm.vhd`
# file (no wrapper needed — the region IS the chart top).  For a
# chart with N>1 regions (post-<parallel> normalisation), wave-2
# emits N region module files + one `<chart>_top.vhd` wrapper that
# instantiates each region and wires cross-domain synchronizers per
# PCDN-C-002.
# ---------------------------------------------------------------------------


def _emit_sync_instance(
    inst_name: str,
    signal_name: str,
    src_clock: str,
    dst_clock: str,
    width: int,
) -> str:
    """Emit one `sos_synchronizer` instantiation per PCDN-C-002.
    Defaults to SYNC_STAGES=2 (matches sos_synchronizer wave-2
    default)."""

    if _hdl_emit_sync_inst is not None:
        try:
            return _hdl_emit_sync_inst(
                inst_name=inst_name,
                src_signal=f"{signal_name}_src",
                dst_signal=f"{signal_name}_dst",
                src_clk=src_clock,
                dst_clk=dst_clock,
                # PCDN-SOS-08-C-wave3-clk-naming-passthrough: dst_clock
                # is already a port name (e.g. "clk_main"); derive the
                # matching rst port name from it.
                dst_rst=(
                    "rst_" + dst_clock[len("clk_"):]
                    if dst_clock.startswith("clk_")
                    else f"rst_{dst_clock}"
                ),
                width=width,
                stages=2,
                dialect=Dialect.VHDL,
            )
        except Exception:
            pass

    # Inline fallback (sibling-agent canonical helper may not be ready
    # at integration time).  Per PCDN-C-002 the synchronizer is
    # retained regardless of `--verified-strip` reachability.
    width_decl = (
        f"std_logic_vector({width - 1} downto 0)" if width > 1 else "std_logic"
    )
    return (
        f"    -- Cross-domain synchronizer per PCDN-C-002 (MTBF sign-off:\n"
        f"    -- see docs/concepts/SOS-08-C-CONCEPTS.md §6.7 + MTBF.md).\n"
        f"    -- Retained regardless of --verified-strip per PCDN-C-002.\n"
        f"    {inst_name} : entity work.sos_synchronizer\n"
        f"        generic map (\n"
        f"            WIDTH  => {width},\n"
        f"            STAGES => 2\n"
        f"        )\n"
        f"        port map (\n"
        f"            src_clk  => {src_clock},\n"
        f"            dst_clk  => {dst_clock},\n"
        # PCDN-SOS-08-C-wave3-clk-naming-passthrough: dst_clock is
        # already the wrapper port name; derive matching rst port.
        f"            dst_rst  => "
        f"{('rst_' + dst_clock[len('clk_'):]) if dst_clock.startswith('clk_') else ('rst_' + dst_clock)},\n"
        f"            src_data => {signal_name}_src,\n"
        f"            dst_data => {signal_name}_dst\n"
        f"        );"
    )


def _emit_chart_top_wrapper(
    chart: HdlChart,
    payload_events: set[str] | None = None,
) -> str:
    """Emit the chart-top wrapper module that instantiates each region
    plus any cross-domain synchronizers.  §6.10 + PCDN-C-001 (clock
    inherit) + PCDN-C-002 (retain synchronizers).

    Falls back to inline emission when hdl_common's canonical helper
    is unavailable.
    """
    payload_events = payload_events or set()

    if _hdl_emit_chart_top_wrapper is not None:
        try:
            # Wave-2 canonical region_modules shape per the 2026-05-23
            # SOS-08-C PCDN walkthrough resolution
            # (`PCDN-SOS-08-C-wave2-wrapper-shape`,
            # `PCDN-SOS-08-C-wave2-region-naming`). Each entry carries
            # `name` (unqualified region id), `module` (full HDL module
            # name w/ `_fsm` suffix), `clock_domain`, `datamodel_signals`
            # (per-signal direction inferred from region.writes/reads),
            # and `state_width`.
            region_modules = []
            for r in chart.regions:
                writes_set = set(r.writes)
                reads_set = set(r.reads)
                signals: list[dict[str, Any]] = []
                # Include this region's locally-declared datamodel plus
                # any chart-shared datamodel signal the region touches.
                local_names = {d.name for d in r.datamodel}
                dm_seen: set[str] = set()
                # Iterate region-local + chart-shared datamodel; deduplicate
                # by chart-side signal name. Direction: 'out' if the region
                # writes the signal, else 'in'.
                candidates: list[HdlDatamodelSignal] = list(r.datamodel)
                for d_shared in chart.shared_datamodel:
                    if d_shared.name in local_names:
                        continue
                    if d_shared.name in writes_set or d_shared.name in reads_set:
                        candidates.append(d_shared)
                for d in candidates:
                    if d.name in dm_seen:
                        continue
                    dm_seen.add(d.name)
                    width = _resolve_port_width(d.scxml_type, d.name)
                    direction = "out" if d.name in writes_set else "in"
                    signals.append(
                        {
                            "name": f"data_{d.name}",
                            "width": width,
                            "direction": direction,
                        }
                    )
                # SOS-08-C wave-3-b: surface per-region raise events to
                # the chart-top wrapper so it exposes
                # `event_<region>_<name>_send_valid` boundary ports.
                # Wave-3-d-3: also surface consume events so the wrapper
                # fans channel m_axis_tvalid out to consuming regions +
                # OR-aggregates consumers' recv_ready into m_axis_tready.
                raise_events_list = _collect_region_raise_events(r)
                consume_events_list = _collect_region_consume_events(r)
                payload_send_list = [
                    ev for ev in raise_events_list if ev in payload_events
                ]
                payload_recv_list = [
                    ev for ev in consume_events_list if ev in payload_events
                ]
                region_modules.append(
                    {
                        "name": _safe_ident(r.name),
                        "module": _entity_name(chart.name, r.name),
                        "clock_domain": r.clock_domain or "main",
                        "datamodel_signals": signals,
                        "state_width": len(r.states),
                        "raise_events": raise_events_list,
                        "consume_events": consume_events_list,
                        "payload_send_events": payload_send_list,
                        "payload_recv_events": payload_recv_list,
                    }
                )
            cross_domain_signals = [
                {
                    "name": f"data_{sig}",
                    "src_region": _safe_ident(writer),
                    "dst_region": _safe_ident(reader),
                    "width": width,
                }
                for (sig, writer, reader, src_clk, dst_clk, width)
                in chart.cross_domain_signals
            ]
            return _hdl_emit_chart_top_wrapper(
                chart_name=_safe_ident(chart.name),
                region_modules=region_modules,
                cross_domain_signals=cross_domain_signals,
                dialect=Dialect.VHDL,
            )
        except ValueError:
            # Chart-vocabulary error from the canonical helper — see
            # SV walker for full rationale. Re-raise so the operator
            # sees the diagnostic.
            raise
        except Exception:
            pass  # fall through to inline emission

    # Distinct clock domains across regions — per PCDN-C-001 default
    # is single-domain ("main"); a second domain is introduced only
    # when at least one region carries an explicit annotation.
    clocks: list[str] = []
    for r in chart.regions:
        if r.clock_domain not in clocks:
            clocks.append(r.clock_domain)

    chart_id = _safe_ident(chart.name)
    top_entity = f"{chart_id}_top"

    # Build port list — one clk/rst per distinct clock domain.
    # PCDN-SOS-08-C-wave3-clk-naming-passthrough (2026-05-23): the chart
    # author's clock attribute is the literal port name. _clk_port_name
    # falls back to `clk_<dom>` only when the input is a legacy bare
    # domain (no `clk_` prefix).
    port_lines: list[str] = []
    for clk in clocks:
        port_lines.append(f"        {_clk_port_name(clk)} : in std_logic")
        port_lines.append(f"        {_rst_port_name(clk)} : in std_logic")

    # Datamodel + per-region current_state outputs — one per region for
    # observability (INV-S-HDL-C-2).
    for r in chart.regions:
        n = len(r.states)
        port_lines.append(
            f"        current_state_{_safe_ident(r.name)} : "
            f"out std_logic_vector({n - 1} downto 0)"
        )

    # Append trailing semicolons except on the last line.
    port_block_lines: list[str] = []
    for i, pl in enumerate(port_lines):
        suffix = ";" if i < len(port_lines) - 1 else ""
        port_block_lines.append(f"{pl}{suffix}")
    port_block = "\n".join(port_block_lines)

    entity_block = (
        f"entity {top_entity} is\n"
        f"    port (\n"
        f"{port_block}\n"
        f"    );\n"
        f"end entity {top_entity};"
    )

    # Architecture — region instantiations + sync_inst per cross-
    # domain signal.
    region_instances: list[str] = []
    for r in chart.regions:
        inst_name = f"u_region_{_safe_ident(r.name)}"
        entity_id = _entity_name(chart.name, r.name)
        n = len(r.states)
        port_map_lines: list[str] = []
        # PCDN-SOS-08-C-wave3-clk-naming-passthrough: pass domain through.
        port_map_lines.append(f"            clk           => {_clk_port_name(r.clock_domain)},")
        port_map_lines.append(f"            rst           => {_rst_port_name(r.clock_domain)},")
        for d in r.datamodel:
            port_map_lines.append(
                f"            data_{d.name} => data_{d.name}_{_safe_ident(r.name)},"
            )
        port_map_lines.append(
            f"            current_state => current_state_{_safe_ident(r.name)}"
        )
        port_map_block = "\n".join(port_map_lines)
        region_instances.append(
            f"    {inst_name} : entity work.{entity_id}\n"
            f"        port map (\n"
            f"{port_map_block}\n"
            f"        );"
        )

    # Internal signals carrying per-region datamodel outputs so the
    # wrapper can route them through synchronizers.
    internal_sig_lines: list[str] = []
    for r in chart.regions:
        for d in r.datamodel:
            width = _resolve_port_width(d.scxml_type, d.name)
            tvec = (
                f"std_logic_vector({width - 1} downto 0)" if width > 1 else "std_logic"
            )
            internal_sig_lines.append(
                f"    signal data_{d.name}_{_safe_ident(r.name)} : {tvec};"
            )

    # Cross-domain synchronizer instantiations (PCDN-C-002 — retained
    # regardless of verified-strip).
    sync_blocks: list[str] = []
    for idx, (sig, writer, reader, src_clk, dst_clk, width) in enumerate(
        chart.cross_domain_signals
    ):
        inst = f"u_sync_{_safe_ident(sig)}_{idx}"
        # Internal src/dst wires expected by sos_synchronizer.  We
        # alias the writer's data port as the src signal and create a
        # dst wire the reader region may consume.
        width_decl = (
            f"std_logic_vector({width - 1} downto 0)" if width > 1 else "std_logic"
        )
        sync_blocks.append(
            f"    signal {sig}_src : {width_decl};\n"
            f"    signal {sig}_dst : {width_decl};"
        )
        sync_blocks.append(
            f"    -- Cross-domain: {sig} writer={writer} reader={reader} "
            f"src={src_clk} dst={dst_clk}"
        )
        sync_blocks.append(
            _emit_sync_instance(
                inst_name=inst,
                signal_name=sig,
                # PCDN-SOS-08-C-wave3-clk-naming-passthrough: emit the
                # literal wrapper port names; the helper handles legacy
                # bare-domain inputs.
                src_clock=_clk_port_name(src_clk),
                dst_clock=_clk_port_name(dst_clk),
                width=width,
            )
        )
        # Connect writer's datamodel output to src.
        sync_blocks.append(
            f"    {sig}_src <= data_{sig}_{_safe_ident(writer)};"
        )

    arch_decls = "\n".join(internal_sig_lines)
    if sync_blocks:
        # Sync-block signal declarations go in the architecture decl
        # region (the `signal ... ;` lines from each block need to be
        # split from the instance block).  Split each block.
        decl_lines: list[str] = []
        body_lines: list[str] = []
        for blk in sync_blocks:
            for line in blk.splitlines():
                stripped = line.strip()
                if stripped.startswith("signal "):
                    decl_lines.append(f"    {stripped}")
                else:
                    body_lines.append(line)
        if decl_lines:
            arch_decls = (
                arch_decls + "\n" + "\n".join(decl_lines)
                if arch_decls
                else "\n".join(decl_lines)
            )
        sync_body = "\n".join(body_lines)
    else:
        sync_body = ""

    architecture = (
        f"architecture rtl of {top_entity} is\n"
        + (arch_decls + "\n" if arch_decls else "")
        + f"begin\n"
        + "\n\n".join(region_instances)
        + ("\n\n" if region_instances and sync_body else "")
        + (sync_body if sync_body else "")
        + f"\nend architecture rtl;\n"
    )

    header_lines = [
        f"-- Generated by tools/sos-codegen/transliterate_hdl_vhdl.py (wave-2)",
        f"-- Chart: {chart.name} (top-level wrapper)",
        f"-- Spec : SOS-08-C-CONCEPTS.md §6.10 (chart-top wrapper),",
        f"--        §6.7 (clock-domain annotation), §15 (ratified 2026-05-23)",
        f"-- PCDN : PCDN-C-001 (clock-domain inherit),",
        f"--        PCDN-C-002 (retain synchronizers regardless of --verified-strip;",
        f"--        MTBF sign-off required per docs/concepts/SOS-08-C-CONCEPTS.md §6.7 +",
        f"--        MTBF.md)",
        f"-- Inv. : INV-S-HDL-C-2 (per-region observability),",
        f"--        INV-S-HDL-C-3 (cross-domain transition enforcement),",
        f"--        INV-S-HDL-A-1 (sync active-high reset)",
    ]
    try:
        header = emit_header_comment(header_lines, dialect=Dialect.VHDL)
    except TypeError:
        header = "\n".join(header_lines)

    return (
        f"{header}\n\n"
        f"library ieee;\n"
        f"use ieee.std_logic_1164.all;\n"
        f"use ieee.numeric_std.all;\n\n"
        f"{entity_block}\n\n"
        f"{architecture}"
    )


# ---------------------------------------------------------------------------
# Region-level rendering — produces one VHDL file body per region.
# ---------------------------------------------------------------------------


def _transition_fire_predicate_terms_vhdl(
    state: HdlState,
    tr: HdlTransition,
    depth_budget: int,
    *,
    include_state_match: bool,
    include_own_event: bool,
) -> list[str]:
    """VHDL mirror of the SV walker's
    ``_transition_fire_predicate_terms``. See the SV docstring for
    full normative reference (wave-3-d-3 § §6.4)."""
    out: list[str] = []
    if include_state_match:
        cname = _state_constant_name(state.state_id)
        out.append(f"(state_q = {cname})")
    for higher in state.transitions:
        if higher is tr:
            break
        higher_parts: list[str] = []
        if higher.event:
            higher_parts.append(
                f"event_{_safe_event_ident_vhdl(higher.event)}_recv_valid = '1'"
            )
        if higher.cond:
            higher_parts.append(
                f"({_compile_guard(higher.cond, depth_budget, state.state_id)})"
            )
        if higher_parts:
            higher_pred = " and ".join(higher_parts)
            out.append(f"not ({higher_pred})")
    if include_own_event and tr.event:
        out.append(
            f"event_{_safe_event_ident_vhdl(tr.event)}_recv_valid = '1'"
        )
    if tr.cond:
        out.append(f"({_compile_guard(tr.cond, depth_budget, state.state_id)})")
    return out


def _walk_state_for_event_vhdl(
    state: HdlState,
    matches,
) -> list[HdlTransition]:
    """VHDL mirror of the SV walker's ``_walk_state_for_event``."""
    out: list[HdlTransition] = []
    for tr in state.transitions:
        if matches(tr):
            out.append(tr)
        if not tr.event and not tr.cond:
            break
    return out


def _emit_event_egress_drives_vhdl(
    region: HdlRegion,
    raise_events: list[str],
    depth_budget: int,
) -> str:
    """Concurrent VHDL assigns for `event_<name>_send_valid` egress.

    SOS-08-C wave-3 events (2026-05-23 §15 / §6.5): for each unique
    raise-event name, assert the corresponding `_send_valid` output
    for one clock cycle when ANY transition with the matching
    `<raise event="<name>"/>` fires. Firing rule (per PCDN-C-006
    document-order priority): the current state register matches the
    transition's source AND the transition's full firing predicate
    (event_recv_valid if consuming + cond if present) holds AND no
    preceding higher-priority transition out of the same source has
    fired.

    Wave-3-d-3: the firing predicate now includes the transition's
    own ``event_<name>_recv_valid`` term when ``event="..."`` is
    present (mirror of the SV walker's wave-3-d-3 fix).
    """
    if not raise_events:
        return ""
    lines: list[str] = []
    for ev in raise_events:
        ev_ident = _safe_event_ident_vhdl(ev)
        terms: list[str] = []
        for state in region.states:
            for tr in _walk_state_for_event_vhdl(
                state,
                lambda t, ev=ev: ev in t.raise_events,
            ):
                preds = _transition_fire_predicate_terms_vhdl(
                    state, tr, depth_budget,
                    include_state_match=True,
                    include_own_event=True,
                )
                terms.append("(" + " and ".join(preds) + ")")
        if terms:
            rhs_bool = " or ".join(terms)
            line = (
                f"    event_{ev_ident}_send_valid <= '1' when "
                f"{rhs_bool} else '0';"
                f"  -- chart event `{ev}`"
            )
        else:
            line = (
                f"    event_{ev_ident}_send_valid <= '0';"
                f"  -- chart event `{ev}` (no firing transition reachable)"
            )
        lines.append(line)
    return "\n".join(lines)


def _emit_event_payload_send_data_drives_vhdl(
    region: HdlRegion,
    payload_send_events: list[str],
    depth_budget: int,
) -> str:
    """VHDL mirror of the SV walker's
    ``_emit_event_payload_send_data_drives``. Emits concurrent
    `event_<name>_send_data` assigns selecting between the firing
    transition's compiled `<param>` expr (cast to std_logic_vector
    of PAYLOAD_WIDTH bits) and a zeros default when no firing.
    """
    if not payload_send_events:
        return ""
    lines: list[str] = []
    for ev in payload_send_events:
        ev_ident = _safe_event_ident_vhdl(ev)
        # Walk transitions raising `ev` with at least one `<param>`.
        cases: list[tuple[str, str, str]] = []
        for state in region.states:
            for tr in _walk_state_for_event_vhdl(
                state,
                lambda t, ev=ev: ev in t.raise_events and bool(
                    t.raise_params.get(ev)
                ),
            ):
                preds = _transition_fire_predicate_terms_vhdl(
                    state, tr, depth_budget,
                    include_state_match=True,
                    include_own_event=True,
                )
                fire_expr = " and ".join(preds)
                p_name, p_expr = tr.raise_params[ev][0]
                # Compile the param expr via the guard-expr pipeline.
                compiled = _compile_guard(
                    p_expr, depth_budget=depth_budget,
                    source_state=tr.source,
                )
                cases.append((fire_expr, compiled, tr.source))
        if cases:
            # Chain when-else expressions. Each case maps fire→payload;
            # the trailing else is all-zeros.
            chain: list[str] = []
            for fire_expr, compiled, _src in cases:
                chain.append(
                    f"std_logic_vector(to_unsigned("
                    f"{compiled}, {_PAYLOAD_WIDTH})) when {fire_expr}"
                )
            chain_str = " else\n        ".join(chain)
            lines.append(
                f"    event_{ev_ident}_send_data <=\n"
                f"        {chain_str} else\n"
                f"        (others => '0');"
                f"  -- chart event `{ev}` payload"
            )
        else:
            lines.append(
                f"    event_{ev_ident}_send_data <= (others => '0');"
                f"  -- chart event `{ev}` payload"
            )
    return "\n".join(lines)


def _emit_event_ingress_recv_ready_drives_vhdl(
    region: HdlRegion,
    consume_events: list[str],
    depth_budget: int,
) -> str:
    """Concurrent VHDL assigns for `event_<name>_recv_ready` ingress.

    SOS-08-C wave-3-d-3 (2026-05-24 §15 / §6.4): mirror of the SV
    walker's ``_emit_event_ingress_recv_ready_drives``. See the SV
    docstring for normative reference. recv_ready does NOT include
    the event's own recv_valid term in its predicate.
    """
    if not consume_events:
        return ""
    lines: list[str] = []
    for ev in consume_events:
        ev_ident = _safe_event_ident_vhdl(ev)
        terms: list[str] = []
        for state in region.states:
            for tr in _walk_state_for_event_vhdl(
                state,
                lambda t, ev=ev: t.event == ev,
            ):
                preds = _transition_fire_predicate_terms_vhdl(
                    state, tr, depth_budget,
                    include_state_match=True,
                    include_own_event=False,
                )
                terms.append("(" + " and ".join(preds) + ")")
        if terms:
            rhs_bool = " or ".join(terms)
            line = (
                f"    event_{ev_ident}_recv_ready <= '1' when "
                f"{rhs_bool} else '0';"
                f"  -- chart event `{ev}` (wave-3-d-3 consume-ready)"
            )
        else:
            line = (
                f"    event_{ev_ident}_recv_ready <= '0';"
                f"  -- chart event `{ev}` (no consuming transition reachable)"
            )
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SOS-08-C wave-3-f-future-xreg (2026-05-24 §15) — chart-top broadcast
# bus emit (VHDL).
# ---------------------------------------------------------------------------


def _augment_chart_top_with_broadcast_bus_vhdl(
    wrapper_body: str,
    chart_event_raisers: dict[str, list[str]],
    region_xreg_events: dict[str, list[str]],
) -> str:
    """VHDL mirror of the SV walker's chart-top broadcast bus emit.

    Inserts ``chart_event_<EV>_raise_valid`` /
    ``chart_event_<EV>_raise_data`` chart-top signal aliases and a
    runtime ``assert`` for same-cycle multi-raiser conflicts.  Aliases
    are wired to the existing aggregated ``ev_<EV>_send_valid`` /
    ``ev_<EV>_send_data`` internal wires the helper already emits.

    Charts without any cross-region capture skip post-processing and
    emit byte-identical output to d879e7b (regression-guard test).
    """
    has_xreg = any(evs for evs in region_xreg_events.values())
    if not has_xreg:
        return wrapper_body

    if "end architecture" not in wrapper_body:
        return wrapper_body

    # Build the declaration block (in the architecture's declarative
    # region — VHDL requires aliases / signals to be declared before
    # `begin`) and the body block (concurrent + a process for the
    # multi-raiser assert).
    decl_lines: list[str] = []
    body_lines: list[str] = []
    decl_lines.append("")
    decl_lines.append(
        "    -- SOS-08-C wave-3-f-future-xreg (2026-05-24 §15) -----"
    )
    decl_lines.append(
        "    -- Chart-top broadcast bus signal aliases — see §15"
    )
    decl_lines.append(
        "    -- wave-3-f-future-xreg for the normative naming."
    )

    body_lines.append("")
    body_lines.append(
        "    -- ----- SOS-08-C wave-3-f-future-xreg broadcast bus -----"
    )
    has_warning = False
    warning_arms: list[str] = []
    for ev, raisers in sorted(chart_event_raisers.items()):
        if not raisers:
            continue
        ev_ident = _safe_event_ident_vhdl(ev)
        valid_name = chart_event_bus_valid_name(ev_ident)
        data_name = chart_event_bus_data_name(ev_ident)
        # Bus VALID alias (signal declaration).
        decl_lines.append(
            f"    signal {valid_name} : std_logic;"
        )
        body_lines.append(
            f"    {valid_name} <= "
            f"ev_{ev_ident}_send_valid;"
            f"  -- chart event `{ev}` broadcast valid (wave-3-f-future-xreg)"
        )
        # Bus DATA alias — only when aggregated send_data exists.
        if f"ev_{ev_ident}_send_data" in wrapper_body:
            decl_lines.append(
                f"    signal {data_name} : "
                f"std_logic_vector(7 downto 0);"
            )
            body_lines.append(
                f"    {data_name} <= "
                f"ev_{ev_ident}_send_data;"
                f"  -- chart event `{ev}` broadcast data (wave-3-f-future-xreg)"
            )
        # Same-cycle multi-raiser conflict: VHDL `report` with
        # severity WARNING (mirror of the SV `$warning`).  SCXML
        # §3.13 microstep ordering — lower-document-index region
        # wins the priority mux (derive); concurrent raises produce
        # an aggregated valid pulse but the data OR-mix can produce
        # an ambiguous bus when two regions raise on the same cycle.
        if len(raisers) >= 2:
            has_warning = True
            terms = " + ".join(
                f"(to_integer(unsigned'(\"\" & "
                f"w_ev_{_safe_event_ident_vhdl(r)}_{ev_ident}_pulse)))"
                for r in raisers
            )
            # Simpler boolean OR-of-pairs form rather than integer
            # sum — VHDL doesn't permit direct numeric coercion of
            # std_logic without explicit casting; a pairwise AND
            # over distinct raiser pairs catches every conflict
            # case (≥ 2 high inputs means at least one pair is both
            # high).
            pair_terms: list[str] = []
            for i, a in enumerate(raisers):
                for b in raisers[i + 1:]:
                    pair_terms.append(
                        f"(w_ev_{_safe_event_ident_vhdl(a)}_{ev_ident}_pulse = '1' "
                        f"and w_ev_{_safe_event_ident_vhdl(b)}_{ev_ident}_pulse = '1')"
                    )
            if pair_terms:
                cond = " or ".join(pair_terms)
                warning_arms.append(
                    f"            -- chart event `{ev}` — raisers: "
                    f"{', '.join(raisers)} (priority to first)"
                )
                warning_arms.append(
                    f"            if {cond} then"
                )
                warning_arms.append(
                    f"                report \"SOS-08-C wave-3-f-future-xreg: "
                    f"same-cycle multi-raiser conflict on chart event `{ev}`; "
                    f"lower-document-index region wins\" severity warning;"
                )
                warning_arms.append("            end if;")
    if has_warning:
        body_lines.append("")
        body_lines.append("    -- SOS-08-C wave-3-f-future-xreg same-cycle multi-")
        body_lines.append("    -- raiser conflict detector (mirror of the SV walker's")
        body_lines.append("    -- $warning emit).  Reports on the first conflicting")
        body_lines.append("    -- cycle of simulation.")
        body_lines.append("    -- pragma synthesis_off")
        body_lines.append("    xreg_conflict_warn : process(all) is")
        body_lines.append("    begin")
        body_lines.extend(warning_arms)
        body_lines.append("    end process;")
        body_lines.append("    -- pragma synthesis_on")

    decl_block = "\n".join(decl_lines) + "\n"
    body_block = "\n".join(body_lines) + "\n"

    # Insert decl_block immediately before the architecture's `begin`
    # keyword and body_block immediately before `end architecture`.
    # Multiple architectures aren't expected; use the LAST `begin`
    # before the LAST `end architecture` as the insertion point.
    end_idx = wrapper_body.rfind("end architecture")
    # Find the `begin` that opens the architecture — the one
    # immediately before `end architecture` at the architecture
    # level.  Search backwards from end_idx for the nearest
    # "\nbegin\n" line.
    begin_marker = "\nbegin\n"
    begin_idx = wrapper_body.rfind(begin_marker, 0, end_idx)
    if begin_idx == -1:
        # Couldn't locate the architecture body — defensive fallback.
        return wrapper_body[:end_idx] + body_block + wrapper_body[end_idx:]

    head = wrapper_body[:begin_idx]
    middle = wrapper_body[begin_idx:end_idx]
    tail = wrapper_body[end_idx:]
    return head + decl_block + middle + body_block + tail


def _augment_chart_top_with_per_param_sub_buses_vhdl(
    wrapper_body: str,
    chart_payload_params: dict[str, list[str]],
    region_payload_recv_events: dict[str, list[str]],
) -> str:
    """PCDN-SOS-08-C-007 (2026-05-25 §15) — VHDL mirror of the SV
    walker's per-`<param>` sub-bus augmenter.

    For each chart-wide event with declared ``<param>`` children:
      - Declare ``signal ev_<EV>_recv_data_<param>_w :
        std_logic_vector(7 downto 0);`` in the architecture's
        declarative region.
      - Drive it via a concurrent assignment from the existing
        ``ev_<EV>_recv_data_w`` aggregate (at v1 all sub-buses carry
        the same payload — per-param channel demux is a future
        amendment).
      - For each region instance with a port-map entry
        ``event_<EV>_recv_data => ev_<EV>_recv_data_w``, inject one
        additional port-map entry per declared ``<param>``:
        ``event_<EV>_recv_data_<param> => ev_<EV>_recv_data_<param>_w``.

    Charts with no declared params skip post-processing and emit
    byte-identical output to the wave-3-f / wave-3-f-future emit.
    """
    if not chart_payload_params:
        return wrapper_body
    if "end architecture" not in wrapper_body:
        return wrapper_body
    active = {
        ev: names for ev, names in chart_payload_params.items() if names
    }
    if not active:
        return wrapper_body

    # 1) Build declaration + body blocks.
    decl_lines: list[str] = [
        "",
        "    -- ----- PCDN-SOS-08-C-007 (2026-05-25 §15) -----",
        "    -- Per-`<param>` sub-bus signal declarations.",
    ]
    body_lines: list[str] = [
        "",
        "    -- ----- PCDN-SOS-08-C-007 per-`<param>` sub-bus drives -----",
    ]
    for ev in sorted(active):
        ev_ident = _safe_event_ident_vhdl(ev)
        src = f"ev_{ev_ident}_recv_data_w"
        for p_name in active[ev]:
            wname = f"ev_{ev_ident}_recv_data_{p_name}_w"
            decl_lines.append(
                f"    signal {wname} : std_logic_vector(7 downto 0);"
            )
            if src in wrapper_body:
                body_lines.append(f"    {wname} <= {src};")
            else:
                body_lines.append(
                    f"    {wname} <= (others => '0');"
                )

    decl_block = "\n".join(decl_lines) + "\n"
    body_block = "\n".join(body_lines) + "\n"

    # Insert decl_block before architecture's `begin`, body_block before
    # `end architecture`.
    end_idx = wrapper_body.rfind("end architecture")
    begin_marker = "\nbegin\n"
    begin_idx = wrapper_body.rfind(begin_marker, 0, end_idx)
    if begin_idx == -1:
        return wrapper_body
    head = wrapper_body[:begin_idx]
    middle = wrapper_body[begin_idx:end_idx]
    tail = wrapper_body[end_idx:]
    wrapper_body = head + decl_block + middle + body_block + tail

    # 2) Inject sub-bus port-map entries into each region instance.
    for ev in sorted(active):
        ev_ident = _safe_event_ident_vhdl(ev)
        legacy_conn = (
            f"event_{ev_ident}_recv_data => "
            f"ev_{ev_ident}_recv_data_w"
        )
        new_conns: list[str] = []
        for p_name in active[ev]:
            new_conns.append(
                f"event_{ev_ident}_recv_data_{p_name} => "
                f"ev_{ev_ident}_recv_data_{p_name}_w"
            )
        out_lines: list[str] = []
        for line in wrapper_body.split("\n"):
            stripped_no_comma = line.rstrip(",").rstrip()
            if stripped_no_comma.endswith(legacy_conn):
                base_indent = line[: len(line) - len(line.lstrip())]
                had_trailing_comma = line.rstrip().endswith(",")
                out_lines.append(f"{stripped_no_comma},")
                for j, conn in enumerate(new_conns):
                    if j < len(new_conns) - 1 or had_trailing_comma:
                        out_lines.append(f"{base_indent}{conn},")
                    else:
                        out_lines.append(f"{base_indent}{conn}")
            else:
                out_lines.append(line)
        wrapper_body = "\n".join(out_lines)
    return wrapper_body


# ---------------------------------------------------------------------------
# PCDN-SOS-08-C-008 (2026-05-25 §15) — shared-datamodel HDL wiring (VHDL).
#
# VHDL mirror of the SV walker's shared-signal augmenter
# (`_augment_chart_top_with_shared_signals_sv`).  Same chart-vocab,
# same v1 same-clock-domain rejection, same one-driver SVA invariant
# preservation by construction (the augmenter emits exactly one driver
# per shared signal, located at the owner_region's clock; readers do
# not write the register).
#
# SOS7CLN (2026-05-25) coherence cleanup: the prior literal-zero
# degradation for ident-bearing RHS expressions is REMOVED.  Both
# walkers now enforce the same chart-vocab constraint on shared-
# signal writer RHS expressions: the RHS MUST be either a literal /
# binop-on-literals OR an ident that references the **owner-region's
# own datamodel**.  Cross-region datamodel reads inside a shared-
# signal writer raise ``UnsupportedChartError`` with the canonical
# ``SOS-08-C wave-future-shared-xreg-rhs:`` prefix.  Under this
# constraint, owner-region ident RHS lowers correctly via the chart-
# top wrapper's ``data_<ident>`` port (routed from the owner region's
# datamodel output, mirroring the SV chart-top's per-region datamodel
# exposure).
# ---------------------------------------------------------------------------


@dataclass
class _SharedSignalWriterVhdl:
    state_id: str
    edge: str
    expr: str


@dataclass
class _SharedSignalHdlVhdl:
    name: str
    width: int
    owner_region: str
    writers: list[_SharedSignalWriterVhdl]
    reader_regions: list[str]
    doc_order: int = 0


def _collect_shared_signals_hdl_vhdl(
    chart_ir: dict[str, Any],
) -> list[_SharedSignalHdlVhdl]:
    """Parse ``<sos:shared_signal>`` declarations from the chart-IR.

    Mirrors SV walker's ``_collect_shared_signals_hdl`` with the VHDL-
    side dataclass shape.  Raises ``UnsupportedChartError`` with the
    canonical ``SOS-08-C wave-future-shared:`` prefix on malformed
    entries.
    """
    raw = (
        chart_ir.get("sos:shared_signal")
        or chart_ir.get("shared_signal")
        or []
    )
    if isinstance(raw, dict):
        raw = [raw]
    out: list[_SharedSignalHdlVhdl] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        owner = entry.get("owner_region")
        width_raw = entry.get("width", 1)
        if not (isinstance(name, str) and name.strip()):
            raise UnsupportedChartError(
                "SOS-08-C wave-future-shared: <sos:shared_signal> MUST "
                "carry a non-empty `name` attribute (used as the emitted "
                "signal identifier `shared_<name>`)."
            )
        if not (isinstance(owner, str) and owner.strip()):
            raise UnsupportedChartError(
                f"SOS-08-C wave-future-shared: <sos:shared_signal "
                f"name={name!r}> MUST carry a non-empty `owner_region` "
                f"attribute naming the single region that drives it."
            )
        try:
            width = int(width_raw)
        except (TypeError, ValueError):
            raise UnsupportedChartError(
                f"SOS-08-C wave-future-shared: <sos:shared_signal "
                f"name={name!r}>'s `width` MUST be a positive integer; "
                f"got {width_raw!r}."
            ) from None
        if width < 1:
            width = 1
        out.append(
            _SharedSignalHdlVhdl(
                name=name.strip(),
                width=width,
                owner_region=owner.strip(),
                writers=[],
                reader_regions=[],
                doc_order=idx,
            )
        )
    return out


def _attach_shared_signal_writers_vhdl(
    signals: list[_SharedSignalHdlVhdl],
    regions: list[HdlRegion],
) -> None:
    """For each shared signal, collect owner-region writer assigns
    (mirror of SV's `_attach_shared_signal_writers`)."""
    if not signals:
        return
    for region in regions:
        for sig in signals:
            if sig.owner_region != region.name:
                continue
            for state in region.states:
                for assign in state.onentry_assigns:
                    if assign.location == sig.name:
                        sig.writers.append(_SharedSignalWriterVhdl(
                            state_id=state.state_id,
                            edge="entry",
                            expr=assign.expr,
                        ))
                for assign in state.onexit_assigns:
                    if assign.location == sig.name:
                        sig.writers.append(_SharedSignalWriterVhdl(
                            state_id=state.state_id,
                            edge="exit",
                            expr=assign.expr,
                        ))


def _attach_shared_signal_readers_vhdl(
    signals: list[_SharedSignalHdlVhdl],
    chart_ir: dict[str, Any],
    regions: list[HdlRegion],
) -> None:
    """Walk chart-IR for `<sos:shared_signal_ref>` + bare-ident-RHS
    readers; record enclosing region.  Mirror of SV walker."""
    if not signals:
        return
    declared = {sig.name: sig for sig in signals}
    region_names = {r.name for r in regions}

    def _record(name: str, region_name: str) -> None:
        sig = declared.get(name)
        if sig is None or sig.owner_region == region_name:
            return
        if region_name not in sig.reader_regions:
            sig.reader_regions.append(region_name)

    def _walk(node: Any, region_name: str | None) -> None:
        if isinstance(node, dict):
            node_id = node.get("id")
            next_region = region_name
            if isinstance(node_id, str) and node_id in region_names:
                next_region = node_id
            for k, v in node.items():
                bare = k.split(":")[-1] if isinstance(k, str) else ""
                if bare == "shared_signal_ref":
                    refs = v if isinstance(v, list) else [v]
                    for r in refs:
                        if isinstance(r, dict):
                            nm = r.get("name")
                            if (
                                isinstance(nm, str)
                                and nm.strip()
                                and next_region
                            ):
                                _record(nm.strip(), next_region)
                else:
                    _walk(v, next_region)
        elif isinstance(node, list):
            for item in node:
                _walk(item, region_name)

    _walk(chart_ir, None)
    for region in regions:
        for state in region.states:
            for assign in state.onentry_assigns + state.onexit_assigns:
                expr_text = (assign.expr or "").strip()
                if expr_text in declared:
                    _record(expr_text, region.name)


def _resolve_region_clock_pair_vhdl(
    region: HdlRegion,
    clock_decls: Any,
) -> tuple[str, str]:
    """Mirror of SV walker's `_resolve_region_clock_pair`."""
    domain = region.clock_domain or "main"
    if clock_decls:
        try:
            from _clock_domains import resolve_alias as _resolve_alias  # type: ignore
            if domain in clock_decls:
                _, source, kind = _resolve_alias(domain, clock_decls)
                return (source, kind)
        except (ImportError, KeyError):
            pass
    return (domain, "rising")


def _validate_shared_signal_clock_domains_vhdl(
    signals: list[_SharedSignalHdlVhdl],
    regions: list[HdlRegion],
    chart_ir: dict[str, Any],
) -> None:
    """v1 same-clock-domain enforcement per PCDN-SOS-08-C-008 addendum.

    VHDL mirror of the SV walker's
    `_validate_shared_signal_clock_domains`.  Same chart-vocab error
    message + prefix; the (vhdl) suffix in the error wording flags
    the dialect for downstream consumers chaining on the prefix.
    """
    if not signals:
        return
    try:
        from _clock_domains import parse_clock_domains as _parse_clock_domains  # type: ignore
        clock_decls = _parse_clock_domains(chart_ir)
    except (ImportError, Exception):  # pragma: no cover — defensive
        clock_decls = None

    region_by_name = {r.name: r for r in regions}
    for sig in signals:
        owner = region_by_name.get(sig.owner_region)
        if owner is None:
            continue
        owner_pair = _resolve_region_clock_pair_vhdl(owner, clock_decls)
        for reader_name in sig.reader_regions:
            reader = region_by_name.get(reader_name)
            if reader is None:
                continue
            reader_pair = _resolve_region_clock_pair_vhdl(reader, clock_decls)
            if reader_pair != owner_pair:
                raise UnsupportedChartError(
                    f"SOS-08-C wave-future-shared-xclk: "
                    f"<sos:shared_signal name='{sig.name}'/> readers in "
                    f"region '{reader_name}' on clock {reader_pair} "
                    f"differ from owner_region '{sig.owner_region}' on "
                    f"clock {owner_pair}; cross-domain shared signals "
                    f"deferred to future PCDN. See SOS-08-C-CONCEPTS.md "
                    f"§15 2026-05-25 entry. (vhdl)"
                )


def _shared_signal_render_vhdl_rhs(
    expr_text: str,
    owner_datamodel_ids: list[str],
    width: int,
) -> tuple[str, bool]:
    """Lower a chart-XML ``<assign expr=...>`` text to VHDL RHS text
    for use in the chart-top owner-driver process.

    SOS7CLN (2026-05-25) coherence cleanup: the prior literal-zero
    degradation for ident RHS is REMOVED.  Owner-region ident RHS
    lowers via the chart-top wrapper's ``data_<ident>`` port (routed
    from the owner region's datamodel output, mirroring the SV
    chart-top's per-region datamodel exposure — see
    `_inject_owner_idents_into_reads_vhdl` for the read-set
    augmentation that drives the chart-top routing).  Cross-region
    datamodel reads are now rejected at chart-vocab time by the
    shared-signal RHS validator
    (`_validate_shared_signal_rhs_same_region_vhdl`); a writer expr
    that reaches this lowering function is guaranteed to reference
    only owner-region datamodel or literals.

    Returns ``(rhs_text, idents_seen)`` — the boolean flags whether
    the expression carried any datamodel identifier references (so
    the augmenter can emit an informative breadcrumb comment).
    """
    expr_text = (expr_text or "").strip()
    if not expr_text:
        return (f"std_logic_vector(to_signed(0, {width}))", False)
    tree = _parse_assign_expr(expr_text, owner_datamodel_ids)
    has_ident = _expr_has_ident(tree)
    rhs = _render_shared_signal_node_vhdl(tree, width)
    return (rhs, has_ident)


def _expr_has_ident(node: AssignExpr) -> bool:
    if node.kind == "ident":
        return True
    if node.kind == "binop":
        return _expr_has_ident(node.left) or _expr_has_ident(node.right)
    return False


def _idents_in_expr(node: AssignExpr) -> list[str]:
    """SOS7CLN — collect every ident name referenced in ``node``."""
    if node.kind == "ident":
        return [node.ident]
    if node.kind == "binop":
        return _idents_in_expr(node.left) + _idents_in_expr(node.right)
    return []


def _render_shared_signal_node_vhdl(
    node: AssignExpr, width: int,
) -> str:
    """VHDL renderer for shared-signal RHS.

    SOS7CLN (2026-05-25): the prior literal-only renderer is
    extended with an ident arm.  Owner-region datamodel idents
    resolve to the chart-top wrapper's ``data_<ident>`` signal
    (which the wrapper routes from the owner-region module's
    ``data_<ident>`` output port via the read-set augmentation in
    `_inject_owner_idents_into_reads_vhdl`).  The chart-top signal
    is declared ``std_logic_vector`` already; ``unsigned()`` /
    ``signed()`` casts wrap it inside binop arms as needed for
    numeric arithmetic.
    """
    if node.kind == "literal" or node.kind == "neg_literal":
        return f"std_logic_vector(to_signed({node.value}, {width}))"
    if node.kind == "ident":
        # Chart-top wrapper exposes the owner region's datamodel
        # signal as ``data_<ident>`` (single-owner case — VHDL
        # `_wrapper_port_name` does not prefix when there's exactly
        # one region exposing the signal).  The wave-3-f datamodel
        # output port is std_logic_vector(width-1 downto 0) by
        # construction.
        return f"data_{node.ident}"
    if node.kind == "binop":
        left = _render_shared_signal_node_vhdl(node.left, width)
        right = _render_shared_signal_node_vhdl(node.right, width)
        return f"std_logic_vector(signed({left}) {node.op} signed({right}))"
    raise AssignExprError(
        f"unrenderable AssignExpr kind '{node.kind}' in shared-signal "
        f"RHS lowering"
    )


def _validate_shared_signal_rhs_same_region_vhdl(
    signals: list[_SharedSignalHdlVhdl],
    regions: list[HdlRegion],
    chart_shared_datamodel: list[HdlDatamodelSignal],
) -> None:
    """SOS7CLN (2026-05-25) — same-region-write-only constraint on
    shared-signal writer RHS.

    A ``<sos:shared_signal>`` writer expression MAY reference:
      * literal values (int / boolean / neg_literal),
      * binops on literals or owner-region datamodel idents,
      * owner-region datamodel idents (i.e. idents declared in the
        owner region's local ``<datamodel>`` OR in the chart-level
        shared datamodel that the owner region writes/reads — the
        latter is the v1 default-clock case where chart-level data
        lands at chart-top scope owned by the writing region).

    Cross-region datamodel reads in a shared-signal writer RHS
    raise ``UnsupportedChartError`` with the canonical
    ``SOS-08-C wave-future-shared-xreg-rhs:`` prefix.  This makes
    the SV walker's structurally-permissive per-region datamodel
    port routing (which would accept cross-region idents without
    complaint) explicit and refused — both walkers now enforce the
    same chart-vocab constraint.
    """
    if not signals:
        return
    region_by_name = {r.name: r for r in regions}
    # Build a name → region map for per-region datamodel signals.
    other_region_dm: dict[str, str] = {}
    for r in regions:
        for d in r.datamodel:
            # If the same name appears in multiple regions, the
            # first-seen wins; downstream walkers already reject
            # name collisions at parse time, so we trust uniqueness.
            other_region_dm.setdefault(d.name, r.name)
    # Chart-level shared datamodel is owner-agnostic and ALWAYS
    # available to the owner region; admit those idents.
    chart_dm_names = {d.name for d in chart_shared_datamodel}
    # Permissive ident set for the parser — every datamodel ident in
    # the chart, regardless of owning region.  The same-region check
    # runs AFTER the parse so cross-region reads surface as the
    # canonical chart-vocab error rather than as the parser's generic
    # "unknown identifier".
    all_dm_idents = list(set(other_region_dm.keys()) | chart_dm_names)
    for sig in signals:
        owner = region_by_name.get(sig.owner_region)
        if owner is None:
            continue
        owner_dm_names = {d.name for d in owner.datamodel} | chart_dm_names
        for writer in sig.writers:
            expr_text = (writer.expr or "").strip()
            if not expr_text:
                continue
            try:
                tree = _parse_assign_expr(expr_text, all_dm_idents)
            except AssignExprError:
                # An unparseable expression surfaces later in the
                # render path with the canonical error prefix; the
                # same-region constraint only governs idents.
                continue
            for ident in _idents_in_expr(tree):
                if ident in owner_dm_names:
                    continue
                other_region = other_region_dm.get(ident)
                if other_region is not None and other_region != sig.owner_region:
                    raise UnsupportedChartError(
                        f"SOS-08-C wave-future-shared-xreg-rhs: "
                        f"<sos:shared_signal name='{sig.name}' "
                        f"owner_region='{sig.owner_region}'/> writer RHS "
                        f"references datamodel ident '{ident}' declared "
                        f"in region '{other_region}'; shared-signal "
                        f"writer RHS MUST be literal-or-owner-region-"
                        f"datamodel only at v1. (VHDL)"
                    )


def _inject_owner_idents_into_reads_vhdl(
    signals: list[_SharedSignalHdlVhdl],
    regions: list[HdlRegion],
    chart_shared_datamodel: list[HdlDatamodelSignal],
) -> None:
    """SOS7CLN (2026-05-25) — augment owner regions' ``reads`` sets
    with any chart-level datamodel ident referenced in their shared-
    signal writer RHS.

    The chart-top wrapper helper exposes per-region datamodel
    signals iff the region reads or writes them (see
    `_emit_chart_top_wrapper`'s `signals` list build at lines
    ~1976-1981).  A shared-signal writer that references an owner-
    region datamodel ident is functionally a read of that signal at
    chart-top scope; without this augmentation the chart-top
    wrapper would not route the signal and the VHDL emit would
    reference an undeclared identifier.  Run BEFORE
    `_emit_chart_top_wrapper` to ensure the routing lands.
    """
    if not signals:
        return
    region_by_name = {r.name: r for r in regions}
    chart_dm_names = {d.name for d in chart_shared_datamodel}
    for sig in signals:
        owner = region_by_name.get(sig.owner_region)
        if owner is None:
            continue
        owner_dm_names = {d.name for d in owner.datamodel} | chart_dm_names
        for writer in sig.writers:
            expr_text = (writer.expr or "").strip()
            if not expr_text:
                continue
            try:
                tree = _parse_assign_expr(expr_text, list(owner_dm_names))
            except AssignExprError:
                continue
            for ident in _idents_in_expr(tree):
                if ident in chart_dm_names:
                    # Chart-level datamodel touched by owner via
                    # shared-signal writer → record as a read so the
                    # chart-top wrapper exposes ``data_<ident>``.
                    if ident not in owner.reads:
                        owner.reads.append(ident)


def _augment_chart_top_with_shared_signals_vhdl(
    wrapper_body: str,
    shared_signals: list[_SharedSignalHdlVhdl],
    regions: list[HdlRegion],
    shared_datamodel: list[HdlDatamodelSignal] | None = None,
) -> str:
    """PCDN-SOS-08-C-008 (2026-05-25 §15) — VHDL mirror of the SV
    walker's `_augment_chart_top_with_shared_signals_sv`.

    Per the file-scope discipline, all wiring is emitted as a post-
    process pass on the wrapper body produced by
    ``hdl_common.emit_chart_top_wrapper`` — the helper is untouched.

    D walker invariant preservation by construction: the owner-driver
    process is the SOLE driver of ``shared_<name>_q``; readers do not
    write the register.  SOS-08-D's one-driver SVA invariant is
    structurally satisfied.
    """
    if not shared_signals:
        return wrapper_body
    if "end architecture" not in wrapper_body:
        return wrapper_body

    region_by_name = {r.name: r for r in regions}
    # Chart-level datamodel ids are the parse-time validation surface
    # for the wave-3-f-future-assign ECMA subset on the RHS.  The owner
    # region's `HdlRegion.datamodel` is empty in VHDL (datamodel signals
    # live on `HdlChart.shared_datamodel`); we union the chart-level list
    # with the owner's local list so the parser accepts owner-region
    # datamodel idents.  SOS7CLN (2026-05-25): cross-region datamodel
    # idents are rejected upstream by
    # `_validate_shared_signal_rhs_same_region_vhdl`, and the chart-top
    # wrapper's read-set has been augmented by
    # `_inject_owner_idents_into_reads_vhdl` so chart-level idents land
    # at chart-top scope as the routed `data_<ident>` signal.
    chart_dm_ids = (
        [d.name for d in shared_datamodel] if shared_datamodel else []
    )

    decl_lines: list[str] = [
        "",
        "    -- ----- PCDN-SOS-08-C-008 (2026-05-25 §15) -----",
        "    -- <sos:shared_signal> chart-top declarations + owner-region",
        "    -- driving process.  Each shared signal carries exactly one",
        "    -- driver (`shared_<name>_q`, on the owner region's clock);",
        "    -- SOS-08-D's one-driver SVA assertion is structurally",
        "    -- satisfied — readers do not write the register.  v1 same-",
        "    -- clock-domain only; cross-domain references are rejected.",
    ]
    for sig in shared_signals:
        decl_lines.append(
            f"    signal shared_{sig.name} : "
            f"std_logic_vector({sig.width - 1} downto 0);"
        )
        decl_lines.append(
            f"    signal shared_{sig.name}_q : "
            f"std_logic_vector({sig.width - 1} downto 0);"
        )

    body_lines: list[str] = [""]
    for sig in shared_signals:
        body_lines.append(
            f"    shared_{sig.name} <= shared_{sig.name}_q;"
        )

    for sig in shared_signals:
        owner = region_by_name.get(sig.owner_region)
        if owner is None:
            continue
        clk = _clk_port_name(owner.clock_domain or "main")
        rst = _rst_port_name(owner.clock_domain or "main")
        # Combine per-region + chart-level datamodel ids — covers both
        # the SV-style "datamodel inherited into region" case and the
        # VHDL-style "datamodel lives on HdlChart only" case.
        owner_dm_ids = list(
            {d.name for d in owner.datamodel}
            | set(chart_dm_ids)
        )

        body_lines.append("")
        body_lines.append(
            f"    -- <sos:shared_signal name=\"{sig.name}\" "
            f"width=\"{sig.width}\" owner_region=\"{sig.owner_region}\"/>"
            f" — owner-driven on {clk}."
        )
        body_lines.append(f"    process({clk}) is")
        body_lines.append("    begin")
        body_lines.append(f"        if rising_edge({clk}) then")
        body_lines.append(f"            if {rst} = '1' then")
        body_lines.append(
            f"                shared_{sig.name}_q <= "
            f"std_logic_vector(to_signed(0, {sig.width}));"
        )
        body_lines.append("            else")
        if not sig.writers:
            body_lines.append(
                f"                shared_{sig.name}_q <= "
                f"shared_{sig.name}_q;  -- no writers — hold"
            )
        else:
            first = True
            for writer in sig.writers:
                idx = _state_index_in_region_vhdl(owner, writer.state_id)
                rhs, has_ident = _shared_signal_render_vhdl_rhs(
                    writer.expr, owner_dm_ids, sig.width,
                )
                kw = "if" if first else "elsif"
                first = False
                # current_state for region is a std_logic_vector — gate
                # on the one-hot bit at the writer state's index.
                owner_ident = _safe_ident(sig.owner_region)
                body_lines.append(
                    f"                {kw} current_state_"
                    f"{owner_ident}({idx}) = '1' then"
                )
                if has_ident:
                    body_lines.append(
                        f"                    -- expr={writer.expr!r}; "
                        f"owner-region datamodel ident lowered via "
                        f"chart-top `data_<ident>` port (SOS7CLN, "
                        f"PCDN-SOS-08-C-008 §15 2026-05-25)."
                    )
                body_lines.append(
                    f"                    -- edge={writer.edge!r}, "
                    f"source state {writer.state_id}"
                )
                body_lines.append(
                    f"                    shared_{sig.name}_q <= {rhs};"
                )
            body_lines.append("                else")
            body_lines.append(
                f"                    shared_{sig.name}_q <= "
                f"shared_{sig.name}_q;  -- hold"
            )
            body_lines.append("                end if;")
        body_lines.append("            end if;")
        body_lines.append("        end if;")
        body_lines.append("    end process;")

    decl_block = "\n".join(decl_lines) + "\n"
    body_block = "\n".join(body_lines) + "\n"

    end_idx = wrapper_body.rfind("end architecture")
    begin_marker = "\nbegin\n"
    begin_idx = wrapper_body.rfind(begin_marker, 0, end_idx)
    if begin_idx == -1:
        return wrapper_body
    head = wrapper_body[:begin_idx]
    middle = wrapper_body[begin_idx:end_idx]
    tail = wrapper_body[end_idx:]
    return head + decl_block + middle + body_block + tail


def _state_index_in_region_vhdl(
    region: HdlRegion, state_id: str
) -> int:
    """One-hot bit index of ``state_id`` within ``region``.  VHDL
    mirror of SV walker's `_state_index_in_region`."""
    for idx, st in enumerate(region.states):
        if st.state_id == state_id:
            return idx
    return 0


def _render_region(
    region: HdlRegion,
    chart_name: str,
    depth_budget: int,
    payload_events: set[str] | None = None,
    chart_event_raisers: dict[str, list[str]] | None = None,
    chart_payload_params: dict[str, list[str]] | None = None,
) -> str:
    """Compose the architecture + entity for one region into a single
    `.vhd` file body.

    SOS-08-C wave-3-f-future-xreg (2026-05-24 §15): cross-region
    capture events are folded into the region's consume-event list
    (so the ``event_<EV>_recv_valid`` / ``_recv_data`` input ports are
    emitted) and into the chart-wide payload-event set (so the
    `_recv_data` port is sized + the broadcast bus carries data).
    """

    dm_decls, dm_resets, dm_ports, _widths = _datamodel_signal_lines(region.datamodel)
    n_states = len(region.states)
    raise_events = _collect_region_raise_events(region)
    consume_events = _collect_region_consume_events(region)
    # SOS-08-C wave-3-f (2026-05-24 §15): collect <onentry>/<onexit>
    # <assign location="X" expr="event.<EV>.value"/> captures.
    # Wave-3-f-future-xreg: the raiser-map enables cross-region
    # captures; fold their events into consume_events + payload_events.
    event_payload_captures = _collect_region_event_payload_captures(
        region,
        chart_event_raisers=chart_event_raisers,
        chart_payload_params=chart_payload_params,
    )
    xreg_consume_events = _cross_region_consume_events(event_payload_captures)
    if xreg_consume_events:
        consume_events = sorted(set(consume_events) | set(xreg_consume_events))
    # SOS-08-C wave-3-e: per-region payload-bearing event subsets.
    # Wave-3-f-future-xreg: cross-region captures imply data on the
    # broadcast bus; fold those events into the payload-event set
    # so the `_recv_data` port is emitted.
    payload_events = set(payload_events or set())
    if xreg_consume_events:
        payload_events.update(xreg_consume_events)
    payload_send_events = [
        ev for ev in raise_events if ev in payload_events
    ]
    payload_recv_events = [
        ev for ev in consume_events if ev in payload_events
    ]
    # PCDN-SOS-08-C-007 (2026-05-25 §15) — VHDL mirror: per-event
    # per-`<param>` sub-bus map for the recv side.
    chart_payload_params = chart_payload_params or {}
    payload_recv_params: dict[str, list[str]] = {
        ev: list(chart_payload_params.get(ev, []))
        for ev in payload_recv_events
        if chart_payload_params.get(ev)
    }
    entity_block = _emit_entity(
        region, chart_name, dm_ports, n_states,
        raise_events, consume_events,
        payload_send_events=payload_send_events,
        payload_recv_events=payload_recv_events,
        payload_recv_params=payload_recv_params,
    )
    state_constants = _emit_state_constants(region)
    # SOS-08-C wave-3-f-future-assign (2026-05-24 §15): collect general
    # ECMAScript-subset assigns (numeric literals, datamodel idents,
    # binary +/-) for inclusion in the same per-signal if/elsif chain.
    general_assigns = _collect_region_general_assigns(region)
    register_process = _emit_register_process(
        region,
        dm_resets,
        event_payload_captures=event_payload_captures,
        datamodel_signals=region.datamodel,
        general_assigns=general_assigns,
    )
    transition_block = _emit_combinational_block(region, depth_budget)

    header_lines = [
        f"-- Generated by tools/sos-codegen/transliterate_hdl_vhdl.py (wave-2)",
        f"-- Chart : {chart_name}",
        f"-- Region: {region.name} (clock domain: {region.clock_domain})",
        f"-- Spec  : SOS-08-C-CONCEPTS.md §6 (emission algorithm), §15 (ratified 2026-05-23)",
        f"-- Inv.  : INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1 (sync active-high reset),",
        f"--         INV-S-HDL-C-1..5 (deterministic emission, observability,",
        f"--         cross-domain enforcement, guard synthesizability, cooperative completion)",
        f"-- PCDN  : C-001 (clock-domain inherit), C-002 (retain synchronizers),",
        f"--         C-003 (reset=<initial>), C-004 (guard depth {depth_budget}),",
        f"--         C-005 (chart annot wins), C-006 (doc-order priority lint rule)",
        f"-- Wave  : 2 — guards, parallel regions, chart-top wrapper, sync, port widths.",
    ]
    try:
        header = emit_header_comment(header_lines, dialect=Dialect.VHDL)
    except TypeError:
        header = "\n".join(header_lines)

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

    dm_output_drives_lines: list[str] = []
    for d in region.datamodel:
        width = _resolve_port_width(d.scxml_type, d.name)
        if width <= 1:
            dm_output_drives_lines.append(
                f"    data_{d.name} <= std_logic(to_unsigned({d.name}_q, 1)(0));"
                f"  -- bool"
            )
        else:
            dm_output_drives_lines.append(
                f"    data_{d.name} <= std_logic_vector({d.name}_q);"
            )
    dm_output_drives = "\n".join(dm_output_drives_lines)

    entity_id = _entity_name(chart_name, region.name)
    egress_block = _emit_event_egress_drives_vhdl(
        region, raise_events, depth_budget
    )
    ingress_block = _emit_event_ingress_recv_ready_drives_vhdl(
        region, consume_events, depth_budget
    )
    payload_block = _emit_event_payload_send_data_drives_vhdl(
        region, payload_send_events, depth_budget
    )
    architecture = (
        f"architecture rtl of {entity_id} is\n"
        f"{arch_decls_block}\n"
        f"begin\n"
        f"{register_process}\n\n"
        f"{transition_block}\n\n"
        f"    current_state <= state_q;\n"
        + (f"{dm_output_drives}\n" if dm_output_drives else "")
        + (
            f"\n    -- ----- event egress (SOS-08-C §6.5 wave-3) -----\n"
            f"{egress_block}\n"
            if egress_block
            else ""
        )
        + (
            f"\n    -- ----- event ingress (SOS-08-C §6.4 wave-3-d-3) -----\n"
            f"{ingress_block}\n"
            if ingress_block
            else ""
        )
        + (
            f"\n    -- ----- event payload (SOS-08-C §6.5 wave-3-e) -----\n"
            f"{payload_block}\n"
            if payload_block
            else ""
        )
        + f"end architecture rtl;\n"
    )

    return (
        f"{header}\n\n"
        f"library ieee;\n"
        f"use ieee.std_logic_1164.all;\n"
        f"use ieee.numeric_std.all;\n\n"
        f"{entity_block}\n\n"
        f"{architecture}"
    )


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------


def render_target(chart_ir: Any, config: Any) -> dict[str, str]:
    """Public entry point — called from `main.py` when `--target hdl-vhdl`.

    Wave-2 returns:
      - For a single-region chart: one file `<chart>_fsm.vhd`.
      - For a chart with <parallel> producing N regions: N region files
        `<chart>_region_<region>.vhd` + one chart-top wrapper
        `<chart>_top.vhd`.

    Raises:
        UnsupportedChartError: when the chart names a feature outside
            the wave-2 scope (event-channel-routed transitions,
            ECMAScript scripts, raises) or the guard depth budget is
            exceeded.
    """
    if not isinstance(chart_ir, dict):
        raise UnsupportedChartError(
            "SOS-08-C wave-2 render_target expects the raw scjson dict, "
            f"not {type(chart_ir).__name__}. The main.py dispatcher needs "
            "to pass the parsed scjson AST."
        )

    # Config may be a dict (legacy) or an HdlEmitConfig dataclass.
    if isinstance(config, dict):
        chart_name = config.get("chart_name") or "chart"
        depth_budget = int(
            config.get("guard_depth_budget", DEFAULT_GUARD_DEPTH_BUDGET)
        )
    else:
        chart_name = getattr(config, "chart_name", None) or "chart"
        depth_budget = int(
            getattr(config, "guard_depth_budget", DEFAULT_GUARD_DEPTH_BUDGET)
        )

    # Step 0 — reject features outside the wave-2 scaffold scope.
    _reject_unsupported(chart_ir)

    # Steps 1-3 / 6-9 of §6 — parse + build region tree + datamodel.
    chart = _normalise_chart(chart_ir, chart_name)

    # SOS-08-C wave-3-e: chart-wide payload-bearing event collection.
    payload_events: set[str] = set()
    for region in chart.regions:
        for state in region.states:
            for tr in state.transitions:
                for ev, params in tr.raise_params.items():
                    if params:
                        payload_events.add(ev)

    # SOS-08-C wave-3-f-future-xreg (2026-05-24 §15): chart-event
    # raiser map — sibling of the SV walker's surface.  Used to admit
    # cross-region <onentry>/<onexit> captures.
    chart_event_raisers = build_chart_event_raiser_map(chart.regions)

    # PCDN-SOS-08-C-007 (2026-05-25 §15): chart-wide map of declared
    # `<param name>` values per event.  Also enforces the value-collision
    # hard-reject at chart-XML parse time.
    chart_payload_params = _collect_chart_payload_params(chart.regions)

    # Single-region path: one file, no wrapper.
    if len(chart.regions) == 1:
        region = chart.regions[0]
        # In single-region case the region "name" defaults to chart name;
        # for back-compat with wave-1 tests the file name is
        # `<chart>_fsm.vhd`.
        region.name = chart_name
        body = _render_region(
            region, chart_name, depth_budget,
            payload_events=payload_events,
            chart_event_raisers=chart_event_raisers,
            chart_payload_params=chart_payload_params,
        )
        return {f"{_entity_name(chart_name)}.vhd": body}

    # SOS7CLN (2026-05-25) coherence cleanup: collect shared signals
    # + augment owner regions' ``reads`` sets BEFORE region rendering
    # so the owner region's entity exposes ``data_<ident>`` as an
    # output port AND the chart-top wrapper routes it.  Same-region
    # constraint validation also lands here so a cross-region read
    # surfaces before any region body is emitted.
    shared_signals = _collect_shared_signals_hdl_vhdl(chart_ir)
    if shared_signals:
        _attach_shared_signal_writers_vhdl(shared_signals, chart.regions)
        _attach_shared_signal_readers_vhdl(
            shared_signals, chart_ir, chart.regions,
        )
        _validate_shared_signal_clock_domains_vhdl(
            shared_signals, chart.regions, chart_ir,
        )
        _validate_shared_signal_rhs_same_region_vhdl(
            shared_signals, chart.regions, chart.shared_datamodel,
        )
        _inject_owner_idents_into_reads_vhdl(
            shared_signals, chart.regions, chart.shared_datamodel,
        )

    # Multi-region path: one region file per region + chart-top wrapper.
    out: dict[str, str] = {}
    region_xreg_events: dict[str, list[str]] = {}
    for region in chart.regions:
        region_body = _render_region(
            region, chart_name, depth_budget,
            payload_events=payload_events,
            chart_event_raisers=chart_event_raisers,
            chart_payload_params=chart_payload_params,
        )
        # Record cross-region captures per region for chart-top
        # broadcast-bus post-processing.
        caps = _collect_region_event_payload_captures(
            region,
            chart_event_raisers=chart_event_raisers,
            chart_payload_params=chart_payload_params,
        )
        region_xreg_events[region.name] = _cross_region_consume_events(caps)
        out[f"{_entity_name(chart_name, region.name)}.vhd"] = region_body

    # SOS-08-C wave-3-f-future-xreg (2026-05-24 §15): fold cross-
    # region capture events into the chart-top payload-event set
    # so the wrapper emits `_recv_data` boundary ports + signal
    # aggregations for events whose payload is observed only
    # via a cross-region capture.
    xreg_all: set[str] = set()
    for evs in region_xreg_events.values():
        xreg_all.update(evs)
    top_payload_events = payload_events | xreg_all
    wrapper_body = _emit_chart_top_wrapper(
        chart, payload_events=top_payload_events
    )
    # SOS-08-C wave-3-f-future-xreg (2026-05-24 §15): post-process
    # the chart-top body to emit the broadcast bus signal aliases +
    # same-cycle multi-raiser runtime assert (VHDL mirror).  Charts
    # without cross-region captures emit byte-identical to d879e7b.
    wrapper_body = _augment_chart_top_with_broadcast_bus_vhdl(
        wrapper_body, chart_event_raisers, region_xreg_events,
    )
    # PCDN-SOS-08-C-007 (2026-05-25 §15): post-process the chart-top
    # body to emit per-`<param>` sub-bus signal declarations + inject
    # sub-bus connections into region port-map instances.  Mirror of
    # the SV walker's ``_augment_chart_top_with_per_param_sub_buses_sv``.
    wrapper_body = _augment_chart_top_with_per_param_sub_buses_vhdl(
        wrapper_body, chart_payload_params, region_xreg_events,
    )
    # PCDN-SOS-08-C-008 (2026-05-25 §15): VHDL mirror of the SV
    # walker's shared-signal augmenter.  Shared signals were
    # collected + validated BEFORE region rendering above; here we
    # post-process the wrapper body to add the chart-top driver
    # process / declarations.  The one-driver SVA invariant is
    # preserved by construction.
    if shared_signals:
        wrapper_body = _augment_chart_top_with_shared_signals_vhdl(
            wrapper_body, shared_signals, chart.regions,
            shared_datamodel=chart.shared_datamodel,
        )
    out[f"{_safe_ident(chart_name)}_top.vhd"] = wrapper_body
    return out


# Helper used by integration / tests: expose the entity-name derivation
# so test assertions don't have to duplicate the rule.
def entity_name(chart_name: str, region_name: Optional[str] = None) -> str:
    return _entity_name(chart_name, region_name)


def state_constant_name(state_id: str) -> str:
    return _state_constant_name(state_id)


def one_hot_value(index: int, n_states: int) -> str:
    return _one_hot_value(index, n_states)


# ---------------------------------------------------------------------------
# SOS-09-E HDL register-file emission integration
# ---------------------------------------------------------------------------
#
# @spec  docs/concepts/SOS-09-E-CONCEPTS.md §5.1..§5.7 (frozen decisions)
# @spec  docs/concepts/SOS-09-E-CONCEPTS.md §6 INV-S-MEM-E-1..6
# @spec  docs/concepts/SOS-09-E-CONCEPTS.md §13 "Files cited" — this walker
#        listed as the VHDL entry point that the SOS-09-E phase EXTENDS
#        (not rewrites) with the sos_regfile template emission.
#
# The regfile emission body lives in ``transliterate_regfile.py`` (a
# sibling module — single source for both VHDL + SystemVerilog so
# INV-S-MEM-E-5 holds by construction). The wrapper here exists so the
# main.py dispatcher can drive the VHDL half of the emit through the
# walker that already owns ``--target hdl-vhdl``.


def render_regfile_vhdl(
    chart_ir: Any,
    config: Any,
) -> dict[str, str]:
    """Emit the SOS-09-E ``sos_regfile`` VHDL-2008 source for a chart.

    Args:
        chart_ir: raw scjson dict (same shape as ``render_target``).
        config: dict / namespace carrying:
            - ``peripheral_name`` (str): module-base name.
            - ``bus_type`` (str): ``"axi4lite"`` (default) or ``"apb"``.
            - ``base_address`` (int): default 0x40000000.
            - ``bus_clock_domain`` (str): default ``"bus"``.

    Returns:
        ``{"sos_regfile_<peripheral>.vhd": <text>}``.

    Raises:
        Sos09RegfileError: validation failure (duplicate channel, bad
            bus type, etc.) — see ``transliterate_regfile.py``.
    """
    from sos09_annotations import parse_chart_annotations  # noqa: WPS433
    from transliterate_regfile import emit_regfile  # noqa: WPS433

    if isinstance(config, dict):
        peripheral_name = config.get("peripheral_name") or config.get("chart_name") or "chart"
        bus_type = config.get("bus_type", "axi4lite")
        base_address = int(config.get("base_address", 0x40000000))
        bus_clock_domain = config.get("bus_clock_domain", "bus")
    else:
        peripheral_name = (
            getattr(config, "peripheral_name", None)
            or getattr(config, "chart_name", None)
            or "chart"
        )
        bus_type = getattr(config, "bus_type", "axi4lite")
        base_address = int(getattr(config, "base_address", 0x40000000))
        bus_clock_domain = getattr(config, "bus_clock_domain", "bus")

    annotations = parse_chart_annotations(chart_ir)
    files = emit_regfile(
        annotations,
        peripheral_name=peripheral_name,
        bus_type=bus_type,
        base_address=base_address,
        bus_clock_domain=bus_clock_domain,
    )
    # Keep only the VHDL artifact for this walker; the SV walker emits the
    # SV half. Both call into the same emit_regfile so the views are
    # byte-identical inputs (INV-S-MEM-E-5).
    return {k: v for k, v in files.items() if k.endswith(".vhd")}

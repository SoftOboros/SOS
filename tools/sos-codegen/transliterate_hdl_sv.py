"""SCXML chart → SystemVerilog-2017 region-FSM emitter (Layer-2 HDL backend).

Wave-2 expansion per SOS-08-C-CONCEPTS.md §6 (ten-step emission algorithm)
and §15 (2026-05-23 ratification). Mirrors `transliterate_hdl_vhdl.py`
so a single chart produces byte-equivalent state machines in both
dialects (same state-constant ordering, same reset-state-from-initial,
same document-order priority for transitions, same parallel-region
decomposition + chart-top wrapper shape).

@spec  SOS-08-C-CONCEPTS.md §6 (emission algorithm), §15 (ratification)
@spec  SOS-08-C-CONCEPTS.md §6.2 (per-region FSM module shape)
@spec  SOS-08-C-CONCEPTS.md §6.3 (guard compilation — wave-2 lands here)
@spec  SOS-08-C-CONCEPTS.md §6.7 (cross-domain clock annotation)
@spec  SOS-08-C-CONCEPTS.md §6.10 (chart-top wrapper — wave-2 lands here)
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
@spec  PCDN-SOS-08-C-wave2-clock-annotation (resolved 2026-05-23) —
       `<sos:region clock="..."/>` element form is the canonical
       declaration site for per-region clock-domain attribution; this
       walker extracts it from each parallel-child state's
       `other_element` list (scjson normalises `xmlns:sos` children
       under that key with `qname=`{NS}region`).
@spec  PCDN-SOS-08-C-wave2-wrapper-shape (resolved 2026-05-23) —
       chart-top wrapper consumes `region_modules` entries shaped
       `{name, module, clock_domain, datamodel_signals, state_width}`;
       the SV walker now routes through `hdl_common.emit_chart_top_wrapper`
       with that shape (wave-3 follow-up to wave-2 ratification).

# Wave-2 scope (delta vs wave-1)

Wave-1 emitted single-region, unguarded, single-clock SV. Wave-2 adds:

  1. **Guard expression emission** (§6.3 / INV-S-HDL-C-4). Each transition
     arm in the case-mux becomes `if (<compiled-guard>) state_next = ST_X;`
     with subsequent guards lowered to `else if` arms. Document-order
     priority (PCDN-C-006) is preserved by the chain order. Guards whose
     compiled-RTL depth exceeds the configured budget surface as
     `UnsupportedChartError` (re-raised from the helper's `GuardDepthError`).
  2. **Parallel regions** (§6.1). `<parallel>` children each become their
     own SV module named `<chart>_region_<name>_fsm`. The chart top is a
     wrapper module that instantiates each region FSM.
  3. **Chart-top wrapper** (§6.10). Single-region charts also gain a
     `<chart>_top` wrapper now, so the integration contract matches the
     parallel case. The wrapper exposes per-clock-domain `clk_<dom>` /
     `rst_<dom>` ports, instantiates each region FSM with the right
     domain wiring, and instantiates `sos_synchronizer` modules for every
     cross-domain signal detected by static analysis (PCDN-C-002).
  4. **Cross-domain synchronizers** (§6.7 / INV-S-HDL-C-3). For each
     cross-clock-domain signal the wrapper detects, emit one
     `sos_synchronizer` instance with `SYNC_STAGES=2` default and a
     citation to PCDN-C-002 + MTBF.md sign-off requirement. Retained
     under `--verified-strip` (PCDN-C-002 resolution = `retain`).
  5. **Port-width-from-signal-width polish** (§5.4 + §6.6). Wave-1 emitted
     scalar `wire` for every datamodel signal; wave-2 honours the
     chart's `width=` annotation (or the SOS-04 / SOS-05 i32 default)
     and emits `wire [N-1:0]` ports.

Still out-of-scope at wave-2 (now rejected with wave-3 messages):

  - **Event ingress / egress** (`event="..."` + `<raise>`). §6.4 / §6.5
    wire external events via L1 `sos_message_channel`; wave-2 still
    auto-advances on each clock cycle and rejects `<raise>`.
  - **ECMAScript subset beyond `<assign>`** — wave-3 lands the §5.3
    table's full RTL realisation pass.
  - **`<script>` bodies** — wave-3.

Rejection messages cite "wave-3" for these constructs (per INV-S-HDL-5
chart-vocabulary traceability — failures surface in chart-author
vocabulary with the wave that lands the feature).

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
shape and emits a structurally equivalent VHDL set: identical
state-constant ordering, datamodel-signal naming, transition-mux
priority, region-module naming convention (`<chart>_region_<name>_fsm`
mirrors the VHDL `<chart>_region_<name>_fsm` entity), and chart-top
wrapper shape (`<chart>_top`). Cross-dialect drift detection lives in
`tests/test_transliterate_hdl_sv.py::test_sv_and_vhdl_have_equivalent_state_constants`.

# hdl_common consumption

This module imports the wave-2 canonical helpers from `hdl_common`:

  - `emit_guard_expr` + `GuardDepthError` — §6.3 guard compilation.
  - `emit_sync_inst` — §6.7 cross-domain synchronizer instantiation.
  - `emit_chart_top_wrapper` — §6.10 chart-top wrapper emission.
  - `port_width_from_signal_width` — §5.4 width inference.

The sibling agent pins these helpers concurrently; if the canonical
signature isn't yet on disk, the call sites here fall back to inline
emission via `try / except (TypeError, ImportError, AttributeError)`
so wave-2 emission doesn't block on integration drift. Fallback paths
emit the same byte-equivalent output as the canonical helpers would.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Sibling module — provides the cross-dialect emit primitives. Wave-2
# imports the new canonical names alongside the wave-1 surface; missing
# names degrade to inline fallbacks at the call site.
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

# Wave-2 canonical helpers — optional imports. If the sibling agent's
# wave-2 commit lands first, we route through these; otherwise the
# fallback paths emit byte-equivalent output.
try:  # pragma: no cover — exercised only when hdl_common wave-2 lands.
    from hdl_common import emit_guard_expr as _emit_guard_expr  # type: ignore
except (ImportError, AttributeError):  # pragma: no cover
    _emit_guard_expr = None

try:  # pragma: no cover
    from hdl_common import GuardDepthError as _GuardDepthError  # type: ignore
except (ImportError, AttributeError):  # pragma: no cover
    class _GuardDepthError(Exception):  # type: ignore[no-redef]
        """Local fallback when hdl_common.GuardDepthError is unavailable."""

try:  # pragma: no cover
    from hdl_common import emit_sync_inst as _emit_sync_inst  # type: ignore
except (ImportError, AttributeError):  # pragma: no cover
    _emit_sync_inst = None

try:  # pragma: no cover
    from hdl_common import emit_chart_top_wrapper as _emit_chart_top_wrapper  # type: ignore
except (ImportError, AttributeError):  # pragma: no cover
    _emit_chart_top_wrapper = None

try:  # pragma: no cover
    from hdl_common import (  # type: ignore
        port_width_from_signal_width as _port_width_from_signal_width,
    )
except (ImportError, AttributeError):  # pragma: no cover
    _port_width_from_signal_width = None

try:  # pragma: no cover
    from hdl_common import DEFAULT_GUARD_DEPTH_BUDGET as _DEFAULT_GUARD_DEPTH_BUDGET
except (ImportError, AttributeError):  # pragma: no cover
    _DEFAULT_GUARD_DEPTH_BUDGET = 8

# PCDN-SOS-08-C-wave3-clk-naming-passthrough (2026-05-23): defensively
# import the clk_/rst_ port-name helpers from hdl_common; fall back to
# local definitions of the same shape if the sibling module is older.
try:  # pragma: no cover
    from hdl_common import clk_port_name as _clk_port_name  # type: ignore
    from hdl_common import rst_port_name as _rst_port_name  # type: ignore
except (ImportError, AttributeError):  # pragma: no cover
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


# ---------------------------------------------------------------------------
# Wave-2 error surface.
#
# Per INV-S-HDL-5 (chart-vocabulary traceability), every chart-author-
# facing rejection cites the chart construct + the wave / phase doc
# that owns the rule. Wave-2 expands the surface:
#
#   - GuardNotSupportedError is RETAINED as a subclass alias so the
#     wave-1 reject tests still import the name, but no scope-check
#     path raises it now — guards are accepted at wave-2. New code
#     prefers `UnsupportedChartError` or `GuardDepthExceeded`.
#   - GuardDepthExceeded surfaces a guard whose compiled-RTL depth
#     exceeds the PCDN-C-004 budget. We re-raise hdl_common's
#     `GuardDepthError` as this subclass so chart authors get a
#     chart-vocabulary message regardless of which raised it.
#   - EventIngressNotSupportedError now cites wave-3 (was wave-2).
# ---------------------------------------------------------------------------


class UnsupportedChartError(Exception):
    """Chart construct outside the current emission scope."""


class HdlEmitError(UnsupportedChartError):
    """Generic SV-emit failure (kept for backward-compat with the
    pre-refactor test suite). New code prefers `UnsupportedChartError`
    or one of its named subclasses."""


class GuardNotSupportedError(HdlEmitError):
    """Retained for backward-compat with wave-1's reject tests. Wave-2
    accepts guards by default; this class is no longer raised by the
    scope-check pass, but the symbol stays exported so older tests
    still import the name without ImportError. New code prefers
    `GuardDepthExceeded` for the budget-overflow case."""


class GuardDepthExceeded(HdlEmitError):
    """Chart transition's compiled guard exceeds the PCDN-C-004 depth
    budget. SOS-08-C §6.3 + INV-S-HDL-C-4 ratify the synthesizability
    threshold (default 8 chained operators); SCXML-LINT-C-2 enforces
    the same limit at lint time."""


class ParallelNotSupportedError(HdlEmitError):
    """Retained for backward-compat with wave-1's reject tests. Wave-2
    accepts <parallel> by emitting one SV module per region + a
    chart-top wrapper; this class is no longer raised by the scope-
    check pass, but the symbol stays exported."""


class EventIngressNotSupportedError(HdlEmitError):
    """Wave-2 still rejects explicit <raise> / event-egress wiring.
    SOS-08-C §6.4 / §6.5 wire external events via L1
    `sos_message_channel`; wave-3 lands the wiring."""


# ---------------------------------------------------------------------------
# sos: namespace — `<sos:region clock="..."/>` extraction
# (PCDN-SOS-08-C-wave2-clock-annotation, resolved 2026-05-23).
#
# scjson normalises every non-SCXML-namespaced element child into the
# state node's `other_element` list as `{qname, attributes, text}`.
# The `sos:` prefix expands to the namespace ratified at SOS-01 §15.
# ---------------------------------------------------------------------------


_SOS_NS = "{http://softoboros.com/scxml-extensions/v1}"


def _extract_sos_region_clock(state_node: dict) -> str | None:
    """Extract clock domain from ``<sos:region clock="..."/>`` child element.

    Returns ``None`` if no annotation present. Per
    PCDN-SOS-08-C-wave2-clock-annotation (resolved 2026-05-23):
    element-form is the canonical declaration site for per-region
    clock domains under the ``sos:`` namespace ratified in SOS-01 §15.
    """
    for elem in state_node.get("other_element", []) or []:
        if elem.get("qname") == _SOS_NS + "region":
            attrs = elem.get("attributes", {}) or {}
            clk = attrs.get("clock")
            if clk:
                return clk
    return None


# ---------------------------------------------------------------------------
# Region/state/transition normalised view.
# ---------------------------------------------------------------------------


@dataclass
class HdlTransition:
    """One outgoing transition from a state."""

    source: str
    target: str
    event: str | None = None
    cond: str | None = None
    # Document-order index within the source state's transition list.
    # Drives the priority chain per PCDN-C-006.
    doc_order: int = 0
    # SOS-08-C wave-3 events (2026-05-23 §15): list of event names this
    # transition raises (<raise event="..."/>) per §6.5. Wave-1/2
    # rejected charts with <raise>; wave-3 emits per-event egress
    # ports + drives `event_<name>_send_valid` for one cycle when the
    # transition fires. Empty for transitions with no <raise>.
    raise_events: list[str] = field(default_factory=list)


@dataclass
class HdlAssign:
    """One assign-style <assign location="x" expr="..."/> emitted by an
    <onentry> / <onexit>. Wave-2 still only honours numeric-literal RHS;
    the ECMAScript <script> path lands in wave-3."""

    location: str
    expr: str  # raw expression text (numeric literal or simple ident)


@dataclass
class HdlState:
    """One <state id="..."/> inside a region."""

    state_id: str
    onentry_assigns: list[HdlAssign] = field(default_factory=list)
    onexit_assigns: list[HdlAssign] = field(default_factory=list)
    transitions: list[HdlTransition] = field(default_factory=list)


@dataclass
class HdlDatamodelSignal:
    """One <data id="..." expr="..." [width="N"] [type="T"]/> normalised
    to a registered RTL signal per SOS-08-C §5.4."""

    name: str
    initial_expr: str  # raw chart-side initial value text
    scxml_type: str = ""  # optional `type=` attribute (`int`, `bool`, `i32`)
    width_hint: int | None = None  # optional explicit `width=` annotation


@dataclass
class HdlRegion:
    """One region — chart-top → one SV module. A chart with <parallel>
    yields N regions; a flat chart yields one."""

    name: str
    states: list[HdlState]
    initial_state: str
    datamodel: list[HdlDatamodelSignal]
    clock_domain: str = "main"  # per §6.7 / PCDN-C-001


@dataclass
class HdlCrossDomainSignal:
    """One signal that crosses clock domains in the chart-top wrapper.
    Wave-2 detects these via static analysis of the region tree:
    whenever a datamodel signal is read in one region and written in
    another (or transitively raised across regions), the chart-top
    wrapper instantiates a `sos_synchronizer` to convey it.

    Per PCDN-C-002 (verified-strip retains synchronizers), the wrapper
    keeps the instance even when bound analysis prunes the consumer
    transition; the synchronizer's MTBF claim is independent of chart
    reachability.
    """

    name: str
    src_region: str
    dst_region: str
    src_clock: str
    dst_clock: str
    width: int
    stages: int = 2  # PCDN-C-002 default


# ---------------------------------------------------------------------------
# Scope-check pass.
#
# Wave-2 narrows the rejection surface: guards + <parallel> are now
# accepted. <raise> + <script> remain rejected with wave-3 messages.
# ---------------------------------------------------------------------------


def _reject_unsupported(chart: dict[str, Any]) -> None:
    """Inspect the raw scjson AST and raise on out-of-scope features.

    Wave-2 rejections cover only the wave-3 surface (<script>, <raise>).
    Guards + <parallel> are accepted; <parallel> is normalised into
    multiple regions, guards are compiled via `_compile_guard_expr`.
    """
    for sid, st in _walk_all_states(chart):
        # <script> in onentry / onexit (wave-3 lands ECMAScript).
        for oe in st.get("onentry", []) or []:
            if oe.get("script"):
                raise UnsupportedChartError(
                    "SOS-08-C wave-2 scaffold does not emit ECMAScript "
                    "<script> bodies yet; assign-only at v2, <script> "
                    f"support lands in wave-3. Found <script> in <onentry> "
                    f"of state '{sid}'."
                )
        for ox in st.get("onexit", []) or []:
            if ox.get("script"):
                raise UnsupportedChartError(
                    "SOS-08-C wave-2 scaffold does not emit ECMAScript "
                    "<script> bodies yet; assign-only at v2, <script> "
                    f"support lands in wave-3. Found <script> in <onexit> "
                    f"of state '{sid}'."
                )

        # SOS-08-C wave-3 events (2026-05-23 §15): <raise> accepted.
        # Per-event egress ports + firing-strobe wiring emitted by
        # `_emit_module_header` + `_emit_transition_case_arm`. Chart-
        # top wrapper `sos_message_channel` instantiation lands in
        # wave-3-b (per the §15 wave-3 events entry).


def _walk_all_states(node: dict[str, Any]):
    """Depth-first walk yielding (state_id, state_dict) for every <state>
    in the scjson tree, INCLUDING those nested inside <parallel>."""
    for st in node.get("state", []) or []:
        sid = st.get("id")
        if sid:
            yield sid, st
        yield from _walk_all_states(st)
    for par in node.get("parallel", []) or []:
        # Recurse into the parallel block; its children may be states
        # OR further parallels. The region normalisation below handles
        # parallel-as-region-boundary; this walker just collects states.
        yield from _walk_all_states(par)


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


def _collect_datamodel(chart: dict[str, Any]) -> list[HdlDatamodelSignal]:
    """Re-walk the chart-root `<datamodel>` into HdlDatamodelSignal
    records. Handles both list-of-{data:[...]} and flat-data shapes,
    plus the optional `type` / `width` annotations per §5.4."""
    datamodel: list[HdlDatamodelSignal] = []
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
    for d in entries:
        width_hint: int | None = None
        raw_width = d.get("width")
        if raw_width is not None:
            try:
                width_hint = int(raw_width)
            except (TypeError, ValueError):
                width_hint = None
        datamodel.append(
            HdlDatamodelSignal(
                name=d.get("id", ""),
                initial_expr=d.get("expr", "") or "0",
                scxml_type=str(d.get("type") or ""),
                width_hint=width_hint,
            )
        )
    return datamodel


def _states_from_container(container: dict[str, Any]) -> list[HdlState]:
    """Flatten a region container (chart root, parallel child, or any
    intermediate state node) into a list of `HdlState`. Mirrors the
    wave-1 normaliser; wave-2 just calls it once per region."""
    states: list[HdlState] = []
    for sid, st in _walk_all_states(container):
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
                # Internal transition (no target) — wave-2 ignores.
                continue
            # SOS-08-C wave-3 events (2026-05-23 §15): extract <raise>
            # event names — list of `event="..."` attributes on each
            # <raise> child of the transition per SCXML §3.13.
            raise_events: list[str] = []
            for r in tr.get("raise_value", []) or []:
                ev = r.get("event")
                if isinstance(ev, str) and ev:
                    raise_events.append(ev)
            hs.transitions.append(
                HdlTransition(
                    source=sid,
                    target=target,
                    event=tr.get("event"),
                    cond=tr.get("cond"),
                    doc_order=idx,
                    raise_events=raise_events,
                )
            )
        states.append(hs)
    return states


def _resolve_initial(container: dict[str, Any], states: list[HdlState]) -> str:
    """Resolve a region's initial state per SCXML semantics + PCDN-C-003."""
    initial = container.get("initial")
    if isinstance(initial, list):
        initial = initial[0] if initial else None
    if not initial:
        if not states:
            raise UnsupportedChartError(
                "SOS-08-C wave-2 scaffold requires at least one <state> in "
                "every region; none found."
            )
        initial = states[0].state_id
    return initial


def _normalise_regions(
    chart: dict[str, Any], chart_name: str
) -> list[HdlRegion]:
    """Re-walk the raw scjson AST into one or more `HdlRegion` records.

    Wave-2 rule:
      * If the chart-root contains a `<parallel>` block, each parallel
        child becomes its own region (per §6.1: "one region per child
        of every <parallel>"). The region name comes from the parallel
        child's `id=` (or a synthetic `region_<n>` fallback).
      * If no `<parallel>`, the entire chart collapses to one region
        named `<chart_name>` — same as the wave-1 behaviour.
    """
    datamodel = _collect_datamodel(chart)
    parallels = chart.get("parallel", []) or []

    regions: list[HdlRegion] = []
    if parallels:
        # Per §6.1: "one region per child of every <parallel>".
        # A <parallel> element's children (the <state> elements inside
        # it) are the regions — NOT the parallel block itself.
        for par_idx, par in enumerate(parallels):
            par_children = par.get("state", []) or []
            if not par_children:
                par_label = par.get("id") or f"parallel_{par_idx}"
                raise UnsupportedChartError(
                    f"SOS-08-C §6.1 — <parallel> '{par_label}' has no <state> "
                    "children; every parallel must declare at least one "
                    "orthogonal child region."
                )
            for child_idx, child_state in enumerate(par_children):
                region_name = (
                    child_state.get("id") or f"region_{par_idx}_{child_idx}"
                )
                # Each parallel child becomes its own region, carrying
                # only its own descendants (no sibling cross-talk).
                states = _states_from_container({"state": [child_state]})
                # Clock domain resolution order (PCDN-SOS-08-C-001 +
                # PCDN-SOS-08-C-wave2-clock-annotation, resolved
                # 2026-05-23):
                #   1. ``<sos:region clock="..."/>`` child element on
                #      this region — canonical chart-author surface.
                #   2. Legacy attribute fallbacks (``clock=``,
                #      ``region_clock=``) for in-flight charts that
                #      pre-date the element-form ratification.
                #   3. Inherit from the parent ``<parallel>``'s
                #      ``clock=`` attribute, if any.
                #   4. Default ``"main"`` per PCDN-SOS-08-C-001.
                clock_domain = (
                    _extract_sos_region_clock(child_state)
                    or child_state.get("clock")
                    or child_state.get("region_clock")
                    or par.get("clock")
                    or "main"
                )
                initial = _resolve_initial(child_state, states)
                regions.append(
                    HdlRegion(
                        name=region_name,
                        states=states,
                        initial_state=initial,
                        datamodel=datamodel,
                        clock_domain=clock_domain,
                    )
                )
        # Top-level <state> children outside the <parallel> become an
        # additional "main" region IF any exist. This handles charts
        # that mix sequential + parallel children at the top level.
        loose_states = _states_from_container({"state": chart.get("state", [])})
        if loose_states:
            initial = _resolve_initial(chart, loose_states)
            regions.append(
                HdlRegion(
                    name="main",
                    states=loose_states,
                    initial_state=initial,
                    datamodel=datamodel,
                    clock_domain=chart.get("clock") or "main",
                )
            )
        return regions

    # Single-region path (wave-1 shape preserved).
    states = _states_from_container(chart)
    if not states:
        raise UnsupportedChartError(
            "SOS-08-C wave-2 scaffold requires at least one <state>; "
            f"chart '{chart_name}' has none."
        )
    initial = _resolve_initial(chart, states)
    # Single-region path uses the same clock-domain precedence as the
    # parallel path (PCDN-SOS-08-C-wave2-clock-annotation, 2026-05-23):
    # element-form ``<sos:region clock=.../>`` on the chart root wins
    # over the legacy chart-root ``clock=`` attribute.
    clock_domain = (
        _extract_sos_region_clock(chart)
        or chart.get("clock")
        or "main"
    )
    return [
        HdlRegion(
            name=chart_name,
            states=states,
            initial_state=initial,
            datamodel=datamodel,
            clock_domain=clock_domain,
        )
    ]


# ---------------------------------------------------------------------------
# Identifier sanitisation.
# ---------------------------------------------------------------------------


def _module_name(chart_name: str) -> str:
    """SV module identifier: lower-case, snake-case, suffix `_fsm`.
    Wave-1 single-region behaviour. Wave-2 keeps this for the single-
    region case; parallel charts use `_region_<name>_module_name` instead."""
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in chart_name)
    if safe and safe[0].isdigit():
        safe = "x" + safe
    return f"{safe.lower()}_fsm"


def _region_module_name(chart_name: str, region_name: str) -> str:
    """Region-FSM module name when the chart has multiple regions:
    `<chart>_region_<region>_fsm`. Mirrors the VHDL sibling so the
    chart-top wrapper instantiates matching identifiers across dialects."""
    chart_safe = "".join(
        c if (c.isalnum() or c == "_") else "_" for c in chart_name
    )
    region_safe = "".join(
        c if (c.isalnum() or c == "_") else "_" for c in region_name
    )
    if chart_safe and chart_safe[0].isdigit():
        chart_safe = "x" + chart_safe
    return f"{chart_safe.lower()}_region_{region_safe.lower()}_fsm"


def _chart_top_module_name(chart_name: str) -> str:
    """Chart-top wrapper module name: `<chart>_top`."""
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in chart_name)
    if safe and safe[0].isdigit():
        safe = "x" + safe
    return f"{safe.lower()}_top"


def _state_constant_name(state_id: str) -> str:
    """SCXML state-id → SV state-constant name. Mirrors the VHDL walker:
    `ST_<id>` uppercased."""
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in state_id)
    return f"ST_{safe.upper()}"


def _one_hot_value(index: int, n_states: int) -> str:
    """Emit an SV sized one-hot literal for the index-th value."""
    bits = ["0"] * n_states
    bits[n_states - 1 - index] = "1"
    return f"{n_states}'b" + "".join(bits)


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
    if out and out[0].isdigit():
        out = "_" + out
    return out


# ---------------------------------------------------------------------------
# Datamodel signal compilation (SOS-08-C §5.4 + §6.6).
# ---------------------------------------------------------------------------


@dataclass
class _DatamodelSignal:
    """Compiled datamodel-signal record."""

    chart_id: str
    sv_name: str
    width: int
    signed: bool
    reset_expr: str


def _port_width(scxml_type: str, name: str, explicit_width: int | None) -> int:
    """Resolve a datamodel signal's bit-width.

    Order of precedence (per §5.4):
      1. Explicit chart annotation `<data width="N"/>` — caller-supplied.
      2. The canonical hdl_common helper `port_width_from_signal_width(...)`
         if available — bridges to the sibling agent's wave-2 pin.
      3. Local fallback: inspect the SCXML type identifier (`bool`, `i8`,
         `int`, etc.) against the SOS-04 / SOS-05 width table.
      4. Default — 32 bits (SOS-04 i32 default).
    """
    if explicit_width is not None and explicit_width > 0:
        return explicit_width
    if _port_width_from_signal_width is not None:
        try:
            width = _port_width_from_signal_width(scxml_type, name)
            if isinstance(width, int) and width > 0:
                return width
        except TypeError:
            # Helper signature drift — fall through to local table.
            pass
    key = (scxml_type or "").strip().lower()
    table = {
        "bool": 1, "bit": 1,
        "i8": 8, "u8": 8,
        "i16": 16, "u16": 16,
        "i32": 32, "u32": 32, "int": 32, "integer": 32, "uint": 32,
        "i64": 64, "u64": 64,
    }
    return table.get(key, 32)


def _infer_datamodel_signal(entry: HdlDatamodelSignal) -> _DatamodelSignal:
    """Derive width / signedness / reset expression from a `<data>` entry.

    Wave-2 honours the chart's `width=` / `type=` annotations via
    `_port_width`. Reset expression compiles numeric literals; non-
    numeric initials fall back to zero with a comment.
    """
    chart_id = entry.name
    sv_name = f"data_{_sanitize_sv_identifier(chart_id)}"
    expr = (entry.initial_expr or "").strip()

    width = _port_width(entry.scxml_type, chart_id, entry.width_hint)
    # Signedness follows the SCXML type identifier where present; default
    # to signed for SOS-04's i32 default.
    scxml_lower = (entry.scxml_type or "").strip().lower()
    if scxml_lower.startswith("u") or scxml_lower in ("bool", "bit"):
        signed = False
    else:
        signed = True

    # Reset expression compilation.
    if width == 1:
        if expr.lower() in ("true", "1"):
            reset_expr = "1'b1"
        elif expr.lower() in ("false", "0", ""):
            reset_expr = "1'b0"
        else:
            try:
                int_val = int(expr, 0)
                reset_expr = f"1'b{1 if int_val else 0}"
            except (TypeError, ValueError):
                reset_expr = (
                    f"1'b0  /* wave-2 fallback: chart expr {expr!r} */"
                )
    else:
        sign_prefix = "s" if signed else ""
        try:
            int_val = int(expr, 0)
            reset_expr = f"{width}'{sign_prefix}d{int_val}"
        except (TypeError, ValueError):
            if expr.lower() in ("[]", "{}", "null", "none", ""):
                reset_expr = f"{width}'{sign_prefix}d0"
            elif expr.lower() == "true":
                reset_expr = f"{width}'{sign_prefix}d1"
            elif expr.lower() == "false":
                reset_expr = f"{width}'{sign_prefix}d0"
            else:
                reset_expr = (
                    f"{width}'{sign_prefix}d0  /* wave-2 fallback: chart expr {expr!r} */"
                )

    return _DatamodelSignal(
        chart_id=chart_id,
        sv_name=sv_name,
        width=width,
        signed=signed,
        reset_expr=reset_expr,
    )


# ---------------------------------------------------------------------------
# Guard expression compilation (SOS-08-C §6.3).
# ---------------------------------------------------------------------------


def _compile_guard_expr(cond_str: str, depth_budget: int) -> str:
    """Compile a chart-side `cond="..."` expression to SV combinational
    syntax. Wave-2 routes through `hdl_common.emit_guard_expr` when
    available; otherwise applies a minimal local transform that:

      - Maps ECMAScript boolean operators (`&&`, `||`, `!`) verbatim
        (SV uses the same lexemes).
      - Maps equality / inequality operators verbatim.
      - Rewrites bare datamodel identifiers (`foo`) into `data_foo_q`
        to match the registered-signal naming in this module.
      - Honours the PCDN-C-004 depth budget; over-budget raises
        `GuardDepthExceeded` (re-raised from `GuardDepthError`).

    The fallback is intentionally minimal — wave-3 lands the full §5.3
    table — but it covers the smoke-test wave-2 shape (simple boolean
    + comparison expressions on datamodel signals).
    """
    if not cond_str:
        return "1'b1"

    # Pre-rewrite bare datamodel identifiers (e.g. `counter`) into the
    # `data_<name>` form so that hdl_common's guard compiler — which
    # appends `_q` to each identifier per the registered-signal naming
    # convention — produces `data_<name>_q`, matching the registers this
    # module declares. The pre-rewrite is conservative: tokens that are
    # already prefixed `data_`, are SV/Python keywords, or look like
    # numeric literals stay untouched.
    _RESERVED = {
        "true", "false", "and", "or", "not",
        "True", "False", "None",
        "in", "if", "else", "elif", "return", "begin", "end",
    }

    def _prefix_datamodel(text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            tok = match.group(0)
            if tok in _RESERVED or tok.lower() in _RESERVED:
                return tok
            if tok[0].isdigit():
                return tok
            if tok.startswith("data_"):
                return tok
            return f"data_{_sanitize_sv_identifier(tok)}"
        return re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\b", repl, text)

    if _emit_guard_expr is not None:
        try:
            return _emit_guard_expr(
                _prefix_datamodel(cond_str),
                Dialect.SV,
                depth_budget=depth_budget,
            )
        except _GuardDepthError as exc:
            raise GuardDepthExceeded(
                f"SOS-08-C §6.3 / PCDN-C-004 — guard expression "
                f"{cond_str!r} exceeds the configured depth budget of "
                f"{depth_budget}: {exc}"
            ) from exc
        except TypeError:
            # Signature drift — fall through to inline fallback.
            pass

    # Local depth count (mirrors hdl_common.compute_guard_depth).
    try:
        depth = compute_guard_depth(cond_str)
    except Exception:
        depth = 0
    if depth > depth_budget:
        raise GuardDepthExceeded(
            f"SOS-08-C §6.3 / PCDN-C-004 — guard expression "
            f"{cond_str!r} has compiled-RTL depth {depth} which "
            f"exceeds the configured budget of {depth_budget}."
        )

    # Minimal lexical rewrite: turn bare identifiers (chart datamodel
    # references) into the registered-signal name we emit elsewhere.
    # Tokens that look like SV keywords / numeric literals / operators
    # are left alone. This is a wave-2 stopgap; wave-3 binds to the
    # full ECMAScript subset.
    def _replace_ident(match: re.Match[str]) -> str:
        tok = match.group(0)
        # Preserve numeric literals.
        if tok[0].isdigit():
            return tok
        # Preserve SV keywords + boolean literals.
        if tok.lower() in ("true", "false", "and", "or", "not"):
            mapping = {"true": "1'b1", "false": "1'b0",
                       "and": "&&", "or": "||", "not": "!"}
            return mapping.get(tok.lower(), tok)
        # Already-prefixed datamodel identifiers stay untouched.
        if tok.startswith("data_"):
            return tok
        # Bare identifier → registered-signal naming convention.
        return f"data_{_sanitize_sv_identifier(tok)}_q"

    out = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\b", _replace_ident, cond_str)
    return out


# ---------------------------------------------------------------------------
# Cross-domain signal detection (PCDN-C-002 / INV-S-HDL-C-3).
# ---------------------------------------------------------------------------


def _detect_cross_domain_signals(
    regions: list[HdlRegion],
) -> list[HdlCrossDomainSignal]:
    """Static analysis: detect datamodel signals that cross clock domains.

    Wave-2 detection rule (intentionally narrow):
      For each datamodel signal, if region A's clock domain differs
      from region B's, and at least one transition or onentry/onexit
      assignment in A references that signal AND at least one transition
      / onentry / onexit in B references the same signal, then the
      signal needs a synchronizer when conveyed across A→B's boundary.

    Wave-2 reports one synchronizer per (signal × cross-domain pair).
    Wave-3 will tighten the analysis once event-routing semantics land.
    """
    # Map region → set(referenced_signal_names)
    refs: dict[str, set[str]] = {}
    for region in regions:
        names: set[str] = set()
        for state in region.states:
            for a in state.onentry_assigns:
                names.add(a.location)
            for a in state.onexit_assigns:
                names.add(a.location)
            for tr in state.transitions:
                if tr.cond:
                    # Pull bare identifiers from cond expression.
                    for tok in re.findall(
                        r"\b[A-Za-z_][A-Za-z0-9_]*\b", tr.cond
                    ):
                        if tok.lower() not in (
                            "true", "false", "and", "or", "not"
                        ):
                            names.add(tok)
        refs[region.name] = names

    # All declared datamodel signal names (any region — datamodel is
    # chart-wide at wave-2).
    datamodel_names: set[str] = set()
    if regions:
        for d in regions[0].datamodel:
            if d.name:
                datamodel_names.add(d.name)

    out: list[HdlCrossDomainSignal] = []
    for sig_name in sorted(datamodel_names):
        # For every ordered pair of regions on different clocks where
        # both reference sig_name, emit one synchronizer entry (A→B).
        # Use ordered pairs so the wrapper can wire the right direction.
        for src in regions:
            for dst in regions:
                if src.name == dst.name:
                    continue
                if src.clock_domain == dst.clock_domain:
                    continue
                if sig_name in refs.get(src.name, set()) and \
                        sig_name in refs.get(dst.name, set()):
                    width = 32
                    for d in src.datamodel:
                        if d.name == sig_name:
                            width = _port_width(d.scxml_type, d.name, d.width_hint)
                            break
                    out.append(
                        HdlCrossDomainSignal(
                            name=sig_name,
                            src_region=src.name,
                            dst_region=dst.name,
                            src_clock=src.clock_domain,
                            dst_clock=dst.clock_domain,
                            width=width,
                            stages=2,
                        )
                    )
    return out


def _emit_sync_inst_local(sig: HdlCrossDomainSignal, idx: int) -> str:
    """Local fallback for `hdl_common.emit_sync_inst` — emit one
    `sos_synchronizer` instance for a cross-domain signal."""
    inst_name = (
        f"u_sync_{_sanitize_sv_identifier(sig.name)}_"
        f"{_sanitize_sv_identifier(sig.src_region)}_to_"
        f"{_sanitize_sv_identifier(sig.dst_region)}_{idx}"
    )
    src_signal = f"data_{_sanitize_sv_identifier(sig.name)}_from_{_sanitize_sv_identifier(sig.src_region)}"
    dst_signal = f"data_{_sanitize_sv_identifier(sig.name)}_to_{_sanitize_sv_identifier(sig.dst_region)}"
    width = max(1, sig.width)
    # PCDN-SOS-08-C-wave3-clk-naming-passthrough: emit the literal
    # wrapper port names; the helpers handle legacy bare-domain inputs.
    src_clk_port = _clk_port_name(sig.src_clock)
    dst_clk_port = _clk_port_name(sig.dst_clock)
    dst_rst_port = _rst_port_name(sig.dst_clock)
    lines = [
        f"    // Cross-domain synchronizer for chart `<data id=\"{sig.name}\"/>`",
        f"    // src region={sig.src_region} {src_clk_port} -> dst region={sig.dst_region} {dst_clk_port}",
        f"    // Per PCDN-C-002 (retain_synchronizers) + INV-S-HDL-C-3 (cross-domain enforcement).",
        f"    // MTBF claim sign-off requirement: see docs/MTBF.md.",
        f"    sos_synchronizer #(",
        f"        .WIDTH({width}),",
        f"        .STAGES({sig.stages})",
        f"    ) {inst_name} (",
        f"        .src_clk({src_clk_port}),",
        f"        .dst_clk({dst_clk_port}),",
        f"        .dst_rst({dst_rst_port}),",
        f"        .src_data({src_signal}),",
        f"        .dst_data({dst_signal})",
        f"    );",
    ]
    return "\n".join(lines)


def _emit_sync_inst_dispatch(
    sig: HdlCrossDomainSignal, idx: int
) -> str:
    """Route to `hdl_common.emit_sync_inst` if available; else fall back
    to the inline emission. The canonical signature per the orchestrator
    is `(inst_name, src_signal, dst_signal, src_clk, dst_clk, dst_rst,
    width, stages, dialect)`."""
    if _emit_sync_inst is None:
        return _emit_sync_inst_local(sig, idx)
    inst_name = (
        f"u_sync_{_sanitize_sv_identifier(sig.name)}_"
        f"{_sanitize_sv_identifier(sig.src_region)}_to_"
        f"{_sanitize_sv_identifier(sig.dst_region)}_{idx}"
    )
    src_signal = f"data_{_sanitize_sv_identifier(sig.name)}_from_{_sanitize_sv_identifier(sig.src_region)}"
    dst_signal = f"data_{_sanitize_sv_identifier(sig.name)}_to_{_sanitize_sv_identifier(sig.dst_region)}"
    try:
        return _emit_sync_inst(
            inst_name=inst_name,
            src_signal=src_signal,
            dst_signal=dst_signal,
            # PCDN-SOS-08-C-wave3-clk-naming-passthrough: walker passes
            # the chart-author's clock-domain value through verbatim.
            src_clk=_clk_port_name(sig.src_clock),
            dst_clk=_clk_port_name(sig.dst_clock),
            dst_rst=_rst_port_name(sig.dst_clock),
            width=max(1, sig.width),
            stages=sig.stages,
            dialect=Dialect.SV,
        )
    except TypeError:
        return _emit_sync_inst_local(sig, idx)


# ---------------------------------------------------------------------------
# SV emission — per-region module.
# ---------------------------------------------------------------------------


def _emit_header(chart_name: str, kind: str = "region-fsm") -> str:
    """Top-of-file `@spec` citation block."""
    return "\n".join(
        [
            f"// Generated by tools/sos-codegen/transliterate_hdl_sv.py",
            f"// Chart: {chart_name}",
            f"// Kind : {kind}",
            f"// Spec : SOS-08-C-CONCEPTS.md §6 (emission algorithm), §15 (ratified 2026-05-23)",
            f"// Inv. : INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1 (sync active-high reset),",
            f"//        INV-S-HDL-C-1..5 (deterministic emission, observability,",
            f"//        cross-domain enforcement, guard synthesizability, cooperative completion)",
            f"// PCDN : C-001 (clock-domain inherit), C-002 (retain synchronizers),",
            f"//        C-003 (reset=<initial>), C-004 (guard depth 8), C-005 (chart annot wins),",
            f"//        C-006 (doc-order priority lint rule)",
            f"// Wave : 2 — guards + parallel regions + chart-top wrapper + sync.",
        ]
    )


def _collect_region_raise_events(region: HdlRegion) -> list[str]:
    """Return the sorted, de-duplicated list of event names this
    region's transitions raise via ``<raise event="..."/>``.

    SOS-08-C wave-3 events (2026-05-23 §15): each unique raise-event
    name becomes one ``event_<name>_send_valid`` output port on the
    per-region FSM module per §6.5. The chart-top wrapper (wave-3-b)
    will collect these per-region outputs into the global
    ``sos_message_channel`` send-face for the named event.

    Ordering is sorted-alphabetical for deterministic emission per
    INV-S-HDL-C-1.
    """
    seen: set[str] = set()
    for state in region.states:
        for tr in state.transitions:
            for ev in tr.raise_events:
                if ev:
                    seen.add(ev)
    return sorted(seen)


def _collect_region_consume_events(region: HdlRegion) -> list[str]:
    """Return the sorted, de-duplicated list of event names this
    region's transitions CONSUME via ``event="..."`` attributes.

    SOS-08-C wave-3-d-3 (2026-05-24 §15): each unique consume-event
    name becomes a ``(event_<name>_recv_valid, event_<name>_recv_ready)``
    port pair on the per-region FSM per §6.4. The chart-top wrapper
    fans the channel's ``m_axis_tvalid`` to every consuming region's
    ``_recv_valid`` input + OR-aggregates the consuming regions'
    ``_recv_ready`` outputs into the channel's ``m_axis_tready`` input.

    Transitions with ``event="..."`` attributes are gated on
    ``event_<name>_recv_valid`` in the case-arm — until now (wave-1
    through wave-3-d-1) the ``event`` attribute was captured but
    UNUSED at emission time, so transitions fired combinationally on
    state + guard regardless of whether the chart-side event had
    actually been raised. Wave-3-d-3 is the load-bearing §6.4 fix
    closing that gap.

    Ordering is sorted-alphabetical for deterministic emission per
    INV-S-HDL-C-1.
    """
    seen: set[str] = set()
    for state in region.states:
        for tr in state.transitions:
            if tr.event:
                seen.add(tr.event)
    return sorted(seen)


def _safe_event_ident(name: str) -> str:
    """Sanitise an SCXML event name for use in a Verilog identifier.

    SCXML event names use dots as namespace separators (`sem.give`);
    Verilog identifiers don't permit dots, so we substitute `_`. The
    mapping is documented in the emitted module's header comment so a
    reviewer reading the SV can recover the chart-side event name.
    """
    return re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_") or "ev"


def _emit_module_header(
    module_name: str,
    datamodel_signals: list[_DatamodelSignal],
    n_states: int,
    raise_events: list[str] | None = None,
    consume_events: list[str] | None = None,
) -> str:
    """Emit the SV module port list for a region FSM.

    SOS-08-C wave-3 events: per raise-event AND per consume-event,
    emits the matching port quad — `(_send_valid, _send_ready)` for
    raise (egress) and `(_recv_valid, _recv_ready)` for consume
    (ingress). Both quads share the trailing-comment annotation
    discipline.
    """
    raise_events = raise_events or []
    consume_events = consume_events or []
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
    # Wave-3 events: per raise-event, emit a (_send_valid, _send_ready)
    # port pair. Per consume-event (wave-3-d-3), emit a
    # (_recv_valid, _recv_ready) port pair.
    #
    #   - `event_<name>_send_valid` (output) — wave-3-a; combinational
    #     pulse driven from the raise-transition-firing predicate.
    #   - `event_<name>_send_ready` (input) — wave-3-d-1; backpressure
    #     surface from the chart-top channel's `s_axis_tready`. The
    #     transition mux gates state-advance on this so the FSM holds
    #     in the source state when the channel is full (cooperative
    #     INV-S-HDL-4: priority-claim is preserved across backpressure
    #     stalls; lower-priority transitions MUST NOT take over).
    #   - `event_<name>_recv_valid` (input) — wave-3-d-3; the chart-top
    #     channel's `m_axis_tvalid` fanned out to this region. The
    #     transition mux gates `event="..."`-bearing transitions on
    #     `_recv_valid` so the FSM advances only when the chart-side
    #     event has been raised.
    #   - `event_<name>_recv_ready` (output) — wave-3-d-3; the
    #     combinational predicate "I'm in a state with a non-elided
    #     transition consuming this event". OR-aggregated with other
    #     consumers' readies at the chart-top to drive the channel's
    #     `m_axis_tready`.
    #
    # The trailing-comment form puts the chart-event-name annotation on
    # a separate line from the port declaration so the comma-suffix
    # logic doesn't end up inside the comment.
    egress_annotations: list[str] = []
    for ev in raise_events:
        ev_ident = _safe_event_ident(ev)
        port_lines.append(f"output wire event_{ev_ident}_send_valid")
        egress_annotations.append(f"        // chart event `{ev}`")
        port_lines.append(f"input  wire event_{ev_ident}_send_ready")
        egress_annotations.append(
            f"        // chart event `{ev}` (wave-3-d backpressure)"
        )
    for ev in consume_events:
        ev_ident = _safe_event_ident(ev)
        port_lines.append(f"input  wire event_{ev_ident}_recv_valid")
        egress_annotations.append(
            f"        // chart event `{ev}` (wave-3-d-3 ingress)"
        )
        port_lines.append(f"output wire event_{ev_ident}_recv_ready")
        egress_annotations.append(
            f"        // chart event `{ev}` (wave-3-d-3 consume-ready)"
        )

    lines: list[str] = []
    lines.append(f"module {module_name} (")
    # Track which port declarations have a trailing-comment annotation
    # so the comma lands BEFORE the comment, not at end-of-line. Raise
    # events contribute 2 ports each; consume events contribute 2
    # ports each.
    n_egress_ports = 2 * len(raise_events) + 2 * len(consume_events)
    n_pre_egress = len(port_lines) - n_egress_ports
    egress_idx = 0
    for i, pl in enumerate(port_lines):
        suffix = "," if i < len(port_lines) - 1 else ""
        lines.append(f"    {pl}{suffix}")
        if i >= n_pre_egress:
            lines.append(egress_annotations[egress_idx])
            egress_idx += 1
    lines.append(");")
    return "\n".join(lines)


def _emit_state_constants(region: HdlRegion) -> list[str]:
    """Emit one-hot state-constant declarations as SV localparams, in
    chart document order."""
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
    """Step 1 + step 6: state register + datamodel reset values."""
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


def _emit_transition_case_arm(
    state: HdlState, depth_budget: int
) -> list[str]:
    """Emit the case-arm body for one source state.

    Wave-2 rule (PCDN-C-006 document-order priority):
      * Walk transitions in document order.
      * Guarded transitions become `if (<guard>) state_next = ST_X;`
        chained as `else if`.
      * The first unguarded transition (if any) becomes the final
        `else state_next = ST_Y;` arm; transitions after an unguarded
        one are emitted as `// dead transition` comments because the
        chain cuts there per first-match-wins semantics.
      * If no unguarded transition is present, the chain ends with
        `else state_next = state_q;` (hold-state default).

    Wave-3-d-3 (2026-05-24 §15) — event ingress refactor: a transition
    with ``event="..."`` is no longer treated as "unguarded" — the
    event-validity (``event_<name>_recv_valid``) is part of its
    predicate. Combined gating shapes:
      - ``event="X" cond="Y"``  → ``event_X_recv_valid && Y``
      - ``event="X"`` no cond   → ``event_X_recv_valid``
      - no event ``cond="Y"``   → ``Y``
      - no event no cond        → unguarded (final else arm)
    Only the last shape ends the priority chain. Prior shapes form
    ``if/else if`` arms preserving PCDN-C-006 doc-order priority.
    """
    cname = _state_constant_name(state.state_id)
    if not state.transitions:
        return [f"            {cname}: state_next = {cname};"]

    def _predicate(tr: HdlTransition) -> str | None:
        """Combined SV-Boolean for `tr`. Returns None for the truly
        unguarded shape (no event, no cond) — the caller treats those
        as the final else arm."""
        parts: list[str] = []
        if tr.event:
            ev_ident = _safe_event_ident(tr.event)
            parts.append(f"event_{ev_ident}_recv_valid")
        if tr.cond:
            parts.append(f"({_compile_guard_expr(tr.cond, depth_budget)})")
        if not parts:
            return None
        return " && ".join(parts)

    # Split: guarded prefix (any number) → first unguarded → tail.
    # Wave-3-d-3: "guarded" now includes any transition with a
    # non-None predicate (event OR cond OR both).
    guarded: list[HdlTransition] = []
    unguarded: HdlTransition | None = None
    dead_tail: list[HdlTransition] = []
    for tr in state.transitions:
        if unguarded is not None:
            dead_tail.append(tr)
            continue
        if _predicate(tr) is not None:
            guarded.append(tr)
        else:
            unguarded = tr

    def _advance(tr: HdlTransition) -> str:
        """Render the state-advance statement for transition `tr`.

        SOS-08-C wave-3-d-1 (2026-05-24 §15): if `tr` carries
        `<raise event="..."/>` elements, wrap the advance in a
        send-ready gate. When any of the channels the transition
        publishes to is not ready, the FSM HOLDS in the source state
        (`state_next = state_q`) — priority-claim is preserved across
        backpressure stalls under INV-S-HDL-4 cooperative semantics.

        Multiple raise events on one transition require ALL channels
        ready (AND); the transition is atomic.
        """
        target = _state_constant_name(tr.target)
        advance = f"state_next = {target};"
        if not tr.raise_events:
            return advance
        ready_terms = [
            f"event_{_safe_event_ident(ev)}_send_ready"
            for ev in sorted(set(tr.raise_events))
        ]
        cond = " && ".join(ready_terms)
        # Inline begin/end: keeps the case-arm body single-line per
        # transition so the existing if/else-if chain stays readable.
        return (
            f"begin if ({cond}) {advance} "
            f"else state_next = {cname}; end"
        )

    lines: list[str] = [f"            {cname}: begin"]
    if not guarded:
        # No guards (no event + no cond) — fast path matches wave-1
        # emission shape, plus wave-3-d-1 send_ready wrap when
        # unguarded transition raises.
        if unguarded is not None:
            lines.append(
                f"                {_advance(unguarded)}"
            )
        else:
            lines.append(f"                state_next = {cname};")
    else:
        first = True
        for tr in guarded:
            pred = _predicate(tr)
            kw = "if" if first else "else if"
            first = False
            lines.append(
                f"                {kw} ({pred}) {_advance(tr)}"
            )
        if unguarded is not None:
            lines.append(
                f"                else {_advance(unguarded)}"
            )
        else:
            lines.append(f"                else state_next = {cname};")

    for extra in dead_tail:
        lines.append(
            f"                // doc-order priority elided (PCDN-C-006): "
            f"source={extra.source} target={extra.target} "
            f"event={extra.event or '-'} "
            f"-- unreachable after preceding unguarded transition"
        )

    lines.append("            end")
    return lines


def _emit_combinational_block(
    region: HdlRegion, depth_budget: int
) -> str:
    """Combinational SV `always_comb` block with `unique case`."""
    case_lines: list[str] = []
    for s in region.states:
        case_lines.extend(_emit_transition_case_arm(s, depth_budget))

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
    """Wave-2 register declarations."""
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
    """Per-region observable output assigns (INV-S-HDL-C-2)."""
    lines: list[str] = []
    lines.append(
        "    // Per INV-S-HDL-C-2: expose state register for SVA / cocotb consumption."
    )
    lines.append("    assign current_state = state_q;")
    for sig in datamodel_signals:
        lines.append(f"    assign {sig.sv_name} = {sig.sv_name}_q;")
    return "\n".join(lines)


def _transition_fire_predicate_terms(
    state: HdlState,
    tr: HdlTransition,
    depth_budget: int,
    *,
    include_state_match: bool,
    include_own_event: bool,
) -> list[str]:
    """Build the AND-terms of ``tr``'s firing predicate within ``state``.

    Returns a list of SV-Boolean terms ready to join with ``&&``.

    Wave-3-d-3: a transition's predicate is the conjunction of:
      - ``state_q == <source>`` (optional via ``include_state_match``;
        omitted when the caller already gates the entire expression on
        state match);
      - for every higher-priority transition in document order,
        ``!(higher full predicate)`` — higher's event-recv-valid (if
        consumed) AND higher's cond (if present);
      - the own ``event_<name>_recv_valid`` term (optional via
        ``include_own_event``; the consume-side recv_ready drive
        OMITS this term to avoid asserting consume-ready in response
        to the channel's own data offer);
      - the own ``cond`` term (always included if present).
    """
    out: list[str] = []
    if include_state_match:
        cname = _state_constant_name(state.state_id)
        out.append(f"state_q == {cname}")
    # Higher-priority transitions must not actually fire this cycle.
    for higher in state.transitions:
        if higher is tr:
            break
        higher_parts: list[str] = []
        if higher.event:
            higher_parts.append(
                f"event_{_safe_event_ident(higher.event)}_recv_valid"
            )
        if higher.cond:
            higher_parts.append(
                f"({_compile_guard_expr(higher.cond, depth_budget)})"
            )
        if higher_parts:
            higher_pred = " && ".join(higher_parts)
            out.append(f"!({higher_pred})")
        # Truly-unguarded (no event, no cond) higher — would always
        # fire — but we'd never reach `tr` past it, so the document-
        # order walker stops before adding `tr` to the chain.
    # Own predicate components.
    if include_own_event and tr.event:
        out.append(
            f"event_{_safe_event_ident(tr.event)}_recv_valid"
        )
    if tr.cond:
        out.append(f"({_compile_guard_expr(tr.cond, depth_budget)})")
    return out


def _walk_state_for_event(
    state: HdlState,
    matches: callable,
) -> list[HdlTransition]:
    """Walk state's transitions in document order, returning the list
    of transitions where ``matches(tr)`` is True, stopping at the first
    truly-unguarded transition (no event, no cond) — those end the
    priority chain per PCDN-C-006.
    """
    out: list[HdlTransition] = []
    for tr in state.transitions:
        if matches(tr):
            out.append(tr)
        if not tr.event and not tr.cond:
            # Chain-ender — subsequent transitions are dead.
            break
    return out


def _emit_event_egress_drives(
    region: HdlRegion,
    raise_events: list[str],
    depth_budget: int,
) -> str:
    """Combinational drives for ``event_<name>_send_valid`` egress ports.

    SOS-08-C wave-3 events (2026-05-23 §15 / §6.5): for each unique
    raise-event name, assert the corresponding `_send_valid` output
    for one clock cycle when ANY transition with `<raise event="<name>"/>`
    in this region fires. "Fires" is defined as: the current state
    register holds the transition's source state AND the transition's
    full firing predicate (event_recv_valid if consuming + cond if
    present) evaluates true AND no preceding higher-priority
    transition has fired per PCDN-C-006 document-order.

    Wave-3-d-3: the firing predicate now includes the transition's
    own ``event_<name>_recv_valid`` term when the transition has an
    ``event="..."`` attribute. Without that, the egress would pulse
    even when the chart-side event hasn't arrived — breaking the
    semantics §6.4 establishes.

    Pure combinational: depends only on `state_q` + guard expressions +
    `event_<name>_recv_valid` inputs. Safe to drive alongside
    `state_next`. No combinational loop through the channel because
    `m_axis_tvalid` (the channel's source for ``_recv_valid``) is
    derived from a registered FIFO empty flag.
    """
    if not raise_events:
        return ""
    lines: list[str] = []
    for ev in raise_events:
        ev_ident = _safe_event_ident(ev)
        terms: list[str] = []
        for state in region.states:
            # Walk state's transitions stopping at chain-ender; collect
            # those that raise `ev`.
            for tr in _walk_state_for_event(
                state,
                lambda t, ev=ev: ev in t.raise_events,
            ):
                preds = _transition_fire_predicate_terms(
                    state, tr, depth_budget,
                    include_state_match=True,
                    include_own_event=True,
                )
                terms.append("(" + " && ".join(preds) + ")")
        if terms:
            rhs = " || ".join(terms)
        else:
            rhs = "1'b0"
        lines.append(
            f"    assign event_{ev_ident}_send_valid = {rhs};"
            f"  // chart event `{ev}`"
        )
    return "\n".join(lines)


def _emit_event_ingress_recv_ready_drives(
    region: HdlRegion,
    consume_events: list[str],
    depth_budget: int,
) -> str:
    """Combinational drives for ``event_<name>_recv_ready`` ingress ports.

    SOS-08-C wave-3-d-3 (2026-05-24 §15 / §6.4): for each unique
    consume-event name, assert the corresponding `_recv_ready` output
    when this region is in a state with a non-elided transition that
    would consume the event THIS cycle IF the event were offered. The
    chart-top wrapper OR-aggregates ``_recv_ready`` across all
    consuming regions (and the external observer's boundary
    ``event_<name>_recv_ready`` input) into the channel's
    ``m_axis_tready``.

    Critically, ``_recv_ready`` does NOT include the event's own
    ``_recv_valid`` term in its predicate. Doing so would create a
    combinational dependency through the channel (recv_ready →
    m_axis_tready → channel pop → m_axis_tvalid → recv_valid →
    recv_ready). The channel's tvalid is derived from a registered
    FIFO empty flag, so a small dependency is safe in practice, but
    omitting the self-event term keeps the recv_ready predicate
    state-local and easier to reason about: "I'm ready to consume X
    NOW if you offer it" is independent of "you ARE offering X".

    Higher-priority transitions' predicates DO include their full
    firing condition (event_recv_valid + cond) — if a higher-priority
    transition would actually fire this cycle, recv_ready for THIS
    transition is suppressed so the channel doesn't pop data that
    nobody consumes.
    """
    if not consume_events:
        return ""
    lines: list[str] = []
    for ev in consume_events:
        ev_ident = _safe_event_ident(ev)
        terms: list[str] = []
        for state in region.states:
            for tr in _walk_state_for_event(
                state,
                lambda t, ev=ev: t.event == ev,
            ):
                preds = _transition_fire_predicate_terms(
                    state, tr, depth_budget,
                    include_state_match=True,
                    include_own_event=False,
                )
                terms.append("(" + " && ".join(preds) + ")")
        if terms:
            rhs = " || ".join(terms)
        else:
            rhs = "1'b0"
        lines.append(
            f"    assign event_{ev_ident}_recv_ready = {rhs};"
            f"  // chart event `{ev}` (wave-3-d-3 consume-ready)"
        )
    return "\n".join(lines)


def _render_region_module(
    region: HdlRegion,
    chart_name: str,
    multi_region: bool,
    depth_budget: int,
) -> tuple[str, str, list[_DatamodelSignal]]:
    """Render a single region into a complete SV module file body.

    Returns (filename, body, compiled-datamodel-signals).
    """
    module_name = (
        _region_module_name(chart_name, region.name)
        if multi_region
        else _module_name(region.name)
    )
    n_states = len(region.states)
    datamodel_signals = [_infer_datamodel_signal(d) for d in region.datamodel]

    raise_events = _collect_region_raise_events(region)
    consume_events = _collect_region_consume_events(region)

    header = _emit_header(chart_name, kind=f"region-fsm:{region.name}")
    module_header = _emit_module_header(
        module_name, datamodel_signals, n_states,
        raise_events, consume_events,
    )
    state_constants = _emit_state_constants(region)
    register_decls = _emit_register_decls(region, datamodel_signals, n_states)
    register_process = _emit_register_process(region, datamodel_signals)
    transition_block = _emit_combinational_block(region, depth_budget)
    output_drives = _emit_output_drives(datamodel_signals)
    state_const_block = "\n".join(f"    {line}" for line in state_constants)

    # SOS-08-C wave-3 events (2026-05-23 §15 / §6.5): combinational
    # `event_<name>_send_valid` drives — assert for one cycle when a
    # transition with the matching `<raise>` fires. Pure combinational
    # in terms of the current state register + the same guard
    # expressions the transition mux already evaluates; safe to drive
    # alongside `state_next`.
    egress_drives = _emit_event_egress_drives(region, raise_events, depth_budget)
    egress_block = (
        f"\n    // ----- event egress (SOS-08-C §6.5 wave-3) -----\n"
        f"{egress_drives}\n"
        if raise_events
        else ""
    )
    # SOS-08-C wave-3-d-3 (2026-05-24 §15 / §6.4): combinational
    # `event_<name>_recv_ready` drives — assert when this region is in
    # a state with a non-elided transition consuming the event.
    ingress_drives = _emit_event_ingress_recv_ready_drives(
        region, consume_events, depth_budget
    )
    ingress_block = (
        f"\n    // ----- event ingress (SOS-08-C §6.4 wave-3-d-3) -----\n"
        f"{ingress_drives}\n"
        if consume_events
        else ""
    )

    body = (
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
        f"    // ----- transition mux (SOS-08-C §5.2 + §6.2/§6.3; document-order priority) -----\n"
        f"{transition_block}\n"
        f"\n"
        f"    // ----- output assigns -----\n"
        f"{output_drives}\n"
        f"{egress_block}"
        f"{ingress_block}"
        f"\n"
        f"endmodule\n"
        f"\n"
        f"`default_nettype wire\n"
    )

    fname = f"{module_name}.sv"
    return fname, body, datamodel_signals


# ---------------------------------------------------------------------------
# Chart-top wrapper emission (SOS-08-C §6.10).
# ---------------------------------------------------------------------------


def _render_chart_top_local(
    chart_name: str,
    regions: list[HdlRegion],
    region_datamodel_signals: dict[str, list[_DatamodelSignal]],
    cross_domain_signals: list[HdlCrossDomainSignal],
) -> tuple[str, str]:
    """Local fallback for `hdl_common.emit_chart_top_wrapper` —
    instantiates each region FSM and wires per-clock-domain clk/rst,
    plus `sos_synchronizer` instances for cross-domain signals."""
    top_module = _chart_top_module_name(chart_name)

    # Determine the set of clock domains in use.
    clock_domains: list[str] = []
    seen: set[str] = set()
    for region in regions:
        if region.clock_domain not in seen:
            seen.add(region.clock_domain)
            clock_domains.append(region.clock_domain)

    # Port list — per-domain clk/rst + chart-wide datamodel exposure.
    # PCDN-SOS-08-C-wave3-clk-naming-passthrough (2026-05-23): walker
    # passes the chart-author's clock-domain value through verbatim;
    # helpers fall back to `clk_<dom>` only for legacy bare-domain
    # fixtures.
    port_lines: list[str] = []
    for dom in clock_domains:
        port_lines.append(f"input  wire {_clk_port_name(dom)}")
        port_lines.append(f"input  wire {_rst_port_name(dom)}")
    # Expose each region's datamodel signals through the chart top.
    chart_datamodel_done: set[str] = set()
    for region in regions:
        for sig in region_datamodel_signals.get(region.name, []):
            if sig.chart_id in chart_datamodel_done:
                continue
            chart_datamodel_done.add(sig.chart_id)
            if sig.width == 1:
                port_lines.append(f"output wire {sig.sv_name}")
            else:
                port_lines.append(
                    f"output wire [{sig.width - 1}:0] {sig.sv_name}"
                )
    # Expose each region's current_state.
    for region in regions:
        rmod = _region_module_name(chart_name, region.name)
        n_states = len(region.states)
        port_lines.append(
            f"output wire [{n_states - 1}:0] current_state_{_sanitize_sv_identifier(region.name)}  "
            f"/* from {rmod} */"
        )

    header = _emit_header(chart_name, kind="chart-top")
    lines: list[str] = [header, "", "`default_nettype none", ""]
    lines.append(f"module {top_module} (")
    for i, pl in enumerate(port_lines):
        suffix = "," if i < len(port_lines) - 1 else ""
        lines.append(f"    {pl}{suffix}")
    lines.append(");")
    lines.append("")
    lines.append("    // Per PCDN-C-001 (clock-domain inherit-from-parent) +")
    lines.append("    // SOS-08-C §6.7 (region clock annotation):")
    lines.append(
        "    // each region runs on the clock domain declared by its "
        "<parallel><region clock=.../>"
    )
    lines.append("    // attribute; unannotated regions inherit clk_main.")
    lines.append("")

    # Cross-domain synchronizer instances.
    if cross_domain_signals:
        lines.append(
            "    // ----- cross-domain synchronizers (PCDN-C-002 + INV-S-HDL-C-3) -----"
        )
        for idx, sig in enumerate(cross_domain_signals):
            lines.append(
                f"    wire [{max(0, sig.width - 1)}:0] data_{_sanitize_sv_identifier(sig.name)}_from_{_sanitize_sv_identifier(sig.src_region)};"
            )
            lines.append(
                f"    wire [{max(0, sig.width - 1)}:0] data_{_sanitize_sv_identifier(sig.name)}_to_{_sanitize_sv_identifier(sig.dst_region)};"
            )
            lines.append(_emit_sync_inst_dispatch(sig, idx))
            lines.append("")

    # Region instances.
    lines.append("    // ----- region FSM instances (SOS-08-C §6.10) -----")
    for region in regions:
        rmod = _region_module_name(chart_name, region.name)
        inst_name = f"u_region_{_sanitize_sv_identifier(region.name)}"
        dom = region.clock_domain
        lines.append(f"    {rmod} {inst_name} (")
        # PCDN-SOS-08-C-wave3-clk-naming-passthrough: pass domain through.
        conns = [
            f"        .clk({_clk_port_name(dom)})",
            f"        .rst({_rst_port_name(dom)})",
        ]
        for sig in region_datamodel_signals.get(region.name, []):
            conns.append(f"        .{sig.sv_name}({sig.sv_name})")
        conns.append(
            f"        .current_state(current_state_{_sanitize_sv_identifier(region.name)})"
        )
        for i, conn in enumerate(conns):
            suffix = "," if i < len(conns) - 1 else ""
            lines.append(f"{conn}{suffix}")
        lines.append("    );")
        lines.append("")

    lines.append("endmodule")
    lines.append("")
    lines.append("`default_nettype wire")
    return f"{top_module}.sv", "\n".join(lines)


def _build_region_modules_canonical(
    chart_name: str,
    regions: list[HdlRegion],
    region_datamodel_signals: dict[str, list[_DatamodelSignal]],
) -> list[dict[str, Any]]:
    """Build the canonical ``region_modules`` list per
    PCDN-SOS-08-C-wave2-wrapper-shape (resolved 2026-05-23):
    ``{name, module, clock_domain, datamodel_signals, state_width}``.

    Per-region direction inference: a datamodel signal is ``"out"`` if
    any state in the region writes it (via ``<onentry>`` / ``<onexit>``
    ``<assign location="..."/>``); else it is ``"in"`` (the region only
    reads it, e.g. through a transition guard). Both directions land
    on the wrapper boundary so the chart-top can wire reads from one
    region to writes from another (synchronised across clock domains
    by ``cross_domain_signals``).
    """
    region_modules: list[dict[str, Any]] = []
    for region in regions:
        # Determine writes / reads for this region by walking its
        # states once. Mirrors the analysis in
        # ``_detect_cross_domain_signals`` but per-region.
        writes: set[str] = set()
        reads: set[str] = set()
        for state in region.states:
            for a in state.onentry_assigns:
                writes.add(a.location)
            for a in state.onexit_assigns:
                writes.add(a.location)
            for tr in state.transitions:
                if tr.cond:
                    for tok in re.findall(
                        r"\b[A-Za-z_][A-Za-z0-9_]*\b", tr.cond
                    ):
                        if tok.lower() not in (
                            "true", "false", "and", "or", "not",
                        ):
                            reads.add(tok)

        signals: list[dict[str, Any]] = []
        for sig in region_datamodel_signals.get(region.name, []):
            chart_id = sig.chart_id
            if chart_id in writes:
                direction = "out"
            elif chart_id in reads:
                direction = "in"
            else:
                # Region neither reads nor writes the signal — wave-2
                # still surfaces it as an output observable per
                # INV-S-HDL-C-2. Cheap default: "out" matches the
                # wave-2 per-region module shape (every datamodel
                # signal is exposed as an output of the FSM).
                direction = "out"
            signals.append(
                {
                    "name": sig.sv_name,
                    "width": max(1, sig.width),
                    "direction": direction,
                }
            )

        # SOS-08-C wave-3-b (2026-05-24 §15): per-region raise events
        # surfaced into the chart-top wrapper's region_modules entry so
        # the wrapper exposes `event_<region>_<name>_send_valid` per
        # boundary port.
        # SOS-08-C wave-3-d-3 (2026-05-24 §15): per-region consume
        # events surfaced so the wrapper fans out the channel's
        # `m_axis_tvalid` to each consuming region + OR-aggregates the
        # consumers' `_recv_ready` outputs into the channel's
        # `m_axis_tready`.
        raise_events_list = _collect_region_raise_events(region)
        consume_events_list = _collect_region_consume_events(region)
        region_modules.append(
            {
                "name": _sanitize_sv_identifier(region.name),
                "module": _region_module_name(chart_name, region.name),
                "clock_domain": region.clock_domain or "main",
                "datamodel_signals": signals,
                "state_width": max(1, len(region.states)),
                "raise_events": raise_events_list,
                "consume_events": consume_events_list,
            }
        )
    return region_modules


def _build_cross_domain_signals_canonical(
    cross_domain_signals: list[HdlCrossDomainSignal],
    region_modules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Adapt ``HdlCrossDomainSignal`` records into the dict shape the
    canonical helper consumes: ``{name, src_region, dst_region, width,
    stages}``. The signal name is rewritten into the registered-
    datamodel form (``data_<sanitised>``) so it matches both the per-
    region module's port name and the wrapper's CDC wire declaration.
    Region names are sanitised consistently with
    ``_build_region_modules_canonical`` so the helper can resolve them
    against ``region_modules``.
    """
    out: list[dict[str, Any]] = []
    region_name_index = {rm["name"] for rm in region_modules}
    for sig in cross_domain_signals:
        src = _sanitize_sv_identifier(sig.src_region)
        dst = _sanitize_sv_identifier(sig.dst_region)
        if src not in region_name_index or dst not in region_name_index:
            # Defensive — should not happen with current detection
            # rules; skip rather than crash so emission stays robust.
            continue
        out.append(
            {
                "name": f"data_{_sanitize_sv_identifier(sig.name)}",
                "src_region": src,
                "dst_region": dst,
                "width": max(1, sig.width),
                "stages": sig.stages,
            }
        )
    return out


def _render_chart_top(
    chart_name: str,
    regions: list[HdlRegion],
    region_datamodel_signals: dict[str, list[_DatamodelSignal]],
    cross_domain_signals: list[HdlCrossDomainSignal],
) -> tuple[str, str]:
    """Emit the chart-top wrapper.

    Wave-3 follow-up to wave-2 ratification (2026-05-23): per
    ``PCDN-SOS-08-C-wave2-wrapper-shape``, ``hdl_common.emit_chart_top_wrapper``
    is now reshaped to consume the canonical
    ``{name, module, clock_domain, datamodel_signals, state_width}``
    region_modules entries and authors the wrapper for both dialects.
    The SV walker now routes through the helper (VHDL sibling already
    migrated). The local ``_render_chart_top_local`` is retained as a
    private fallback so wave-2 emission keeps working if a future
    helper signature drift breaks the call site.
    """
    if _emit_chart_top_wrapper is not None:
        try:
            region_modules = _build_region_modules_canonical(
                chart_name, regions, region_datamodel_signals
            )
            cds_dicts = _build_cross_domain_signals_canonical(
                cross_domain_signals, region_modules
            )
            # Pass the canonical lowercased+sanitised chart base so the
            # helper's ``f"{chart_name}_top"`` matches our local
            # ``_chart_top_module_name`` (lowercased). The trailing
            # ``_top`` is appended by the helper.
            top_name = _chart_top_module_name(chart_name)
            chart_base = top_name[: -len("_top")] if top_name.endswith(
                "_top"
            ) else top_name
            body = _emit_chart_top_wrapper(
                chart_name=chart_base or "chart",
                region_modules=region_modules,
                cross_domain_signals=cds_dicts,
                dialect=Dialect.SV,
            )
            fname = f"{top_name}.sv"
            return fname, body
        except Exception:
            # Signature drift or runtime error — fall back to the
            # local emitter so wave-2 emission stays unblocked.
            pass
    return _render_chart_top_local(
        chart_name, regions, region_datamodel_signals, cross_domain_signals
    )


# ---------------------------------------------------------------------------
# Public entry points.
# ---------------------------------------------------------------------------


def _resolve_depth_budget(config: Any) -> int:
    """Resolve guard depth budget from config (dict / dataclass / None)."""
    if isinstance(config, dict):
        v = config.get("guard_depth_budget")
        if isinstance(v, int) and v > 0:
            return v
    elif config is not None:
        v = getattr(config, "guard_depth_budget", None)
        if isinstance(v, int) and v > 0:
            return v
    return _DEFAULT_GUARD_DEPTH_BUDGET


def render_target(chart_ir: Any, config: Any = None) -> dict[str, str]:
    """SCXML raw-scjson chart-IR → SystemVerilog FSM source(s).

    Wave-2 contract:
      - Single-region chart → one `<chart>_fsm.sv` (wave-1 shape).
        NO chart-top wrapper is emitted in the single-region path so the
        wave-1 acceptance tests + the cross-dialect equivalence test
        continue to see exactly one output file.
      - Multi-region chart (chart contains `<parallel>`) → N+1 files:
        one `<chart>_region_<name>_fsm.sv` per region + one
        `<chart>_top.sv` wrapper.

    Args:
        chart_ir: raw scjson dict.
        config: optional dict / namespace. Wave-2 consumes:
            - `chart_name` (str): chart identifier; SV module-name base.
            - `guard_depth_budget` (int): PCDN-C-004 budget override.

    Returns:
        dict mapping output filename → file content.

    Raises:
        UnsupportedChartError (or subclass) when the chart names a
        feature outside the wave-2 scope, or when a guard's compiled
        depth exceeds the configured budget (`GuardDepthExceeded`).
    """
    if not isinstance(chart_ir, dict):
        raise UnsupportedChartError(
            "SOS-08-C wave-2 render_target expects the raw scjson dict, "
            f"not {type(chart_ir).__name__}. The main.py dispatcher needs "
            "to pass the parsed scjson AST (ChartAst.raw_scjson)."
        )

    if isinstance(config, dict):
        chart_name = config.get("chart_name") or "chart"
    else:
        chart_name = getattr(config, "chart_name", None) or "chart"

    depth_budget = _resolve_depth_budget(config)

    # Step 0 — reject features outside the wave-2 scope.
    _reject_unsupported(chart_ir)

    # Step 1 — parse + build region tree.
    regions = _normalise_regions(chart_ir, chart_name)

    if not regions:
        raise UnsupportedChartError(
            "SOS-08-C wave-2 scaffold requires at least one region; "
            f"chart '{chart_name}' produced none."
        )

    multi_region = len(regions) > 1 or bool(chart_ir.get("parallel"))

    files: dict[str, str] = {}
    region_datamodel_signals: dict[str, list[_DatamodelSignal]] = {}

    for region in regions:
        fname, body, dmsigs = _render_region_module(
            region, chart_name, multi_region, depth_budget
        )
        files[fname] = body
        region_datamodel_signals[region.name] = dmsigs

    if multi_region:
        # Step 7 + step 10 — detect cross-domain signals, emit wrapper.
        cds = _detect_cross_domain_signals(regions)
        wrapper_name, wrapper_body = _render_chart_top(
            chart_name, regions, region_datamodel_signals, cds
        )
        files[wrapper_name] = wrapper_body

    return files


def render_target_with_metadata(
    chart_ir: Any, config: Any = None
) -> tuple[dict[str, str], dict[str, Any]]:
    """Same as `render_target` but additionally returns a metadata dict
    the cross-dialect equivalence test consumes."""
    files = render_target(chart_ir, config)
    if isinstance(config, dict):
        chart_name = config.get("chart_name") or "chart"
    else:
        chart_name = getattr(config, "chart_name", None) or "chart"
    regions = _normalise_regions(chart_ir, chart_name)
    multi_region = len(regions) > 1 or bool(chart_ir.get("parallel"))

    notes: list[str] = []
    # Wave-1 cross-dialect equivalence test consumes state_names +
    # state_constants from the first region. Preserve that surface.
    primary = regions[0]
    datamodel_signals = [_infer_datamodel_signal(d) for d in primary.datamodel]

    if not datamodel_signals:
        notes.append(
            "chart has no <datamodel><data> entries — module has only "
            "state register surface"
        )
    if any(not s.transitions for s in primary.states):
        notes.append(
            "one or more states have no outgoing transitions (terminal "
            "states); transition mux includes hold arms for them"
        )

    metadata: dict[str, Any] = {
        "module_name": (
            _region_module_name(chart_name, primary.name)
            if multi_region
            else _module_name(primary.name)
        ),
        "state_names": [s.state_id for s in primary.states],
        "state_constants": [
            _state_constant_name(s.state_id) for s in primary.states
        ],
        "initial_state": primary.initial_state,
        "datamodel": [
            {
                "id": sig.chart_id,
                "sv_name": sig.sv_name,
                "width": sig.width,
            }
            for sig in datamodel_signals
        ],
        "regions": [
            {
                "name": r.name,
                "clock_domain": r.clock_domain,
                "module_name": (
                    _region_module_name(chart_name, r.name)
                    if multi_region
                    else _module_name(r.name)
                ),
                "state_names": [s.state_id for s in r.states],
            }
            for r in regions
        ],
        "multi_region": multi_region,
        "chart_top": (
            _chart_top_module_name(chart_name) if multi_region else None
        ),
        "notes": notes,
    }
    return files, metadata


# Helpers used by integration / tests.
def module_name(chart_name: str) -> str:
    return _module_name(chart_name)


def region_module_name(chart_name: str, region_name: str) -> str:
    return _region_module_name(chart_name, region_name)


def chart_top_module_name(chart_name: str) -> str:
    return _chart_top_module_name(chart_name)


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

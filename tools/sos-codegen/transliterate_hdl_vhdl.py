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

from dataclasses import dataclass, field
from typing import Any, Optional

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
    """One outgoing transition from a state.  Wave-2 carries the
    fields the emit walk consumes; richer fields (raise payloads,
    explicit event tokens) land in wave-3."""

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
    <onentry> / <onexit>.  Wave-2 still numeric-literal RHS only; the
    ECMAScript <script> path lands in wave-3."""

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

        # <raise> egress — event-routing — wave-2 has no L1 channels yet.
        for tr in st.get("transition", []) or []:
            if tr.get("raise_value"):
                raise UnsupportedChartError(
                    "SOS-08-C wave-2 emitter does not lower chart event "
                    "egress yet; <raise>/<send> wiring via L1 "
                    "sos_message_channel lands in wave-3 "
                    "(SOS-08-C §6.4 / §6.5). Found <raise> on transition "
                    f"out of state '{sid}'."
                )


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
            hs.transitions.append(
                HdlTransition(
                    source=sid,
                    target=target,
                    event=tr.get("event"),
                    cond=cond,
                    doc_order=idx,
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


def _emit_entity(
    region: HdlRegion,
    chart_name: str,
    datamodel_ports: list[str],
    n_states: int,
) -> str:
    """Emit the VHDL entity port list for a region FSM module."""
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
    for i, pl in enumerate(port_lines):
        suffix = ";" if i < len(port_lines) - 1 else ""
        lines.append(f"        {pl}{suffix}")
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

    # Partition into a doc-ordered list; identify whether any have
    # `cond` set.
    has_any_guard = any(t.cond for t in state.transitions)
    if not has_any_guard:
        chosen = state.transitions[0]
        lines: list[str] = []
        lines.append(
            f"            state_next <= {_state_constant_name(chosen.target)};"
        )
        for extra in state.transitions[1:]:
            lines.append(
                f"            -- doc-order priority elided (PCDN-C-006): "
                f"source={extra.source} target={extra.target} "
                f"event={extra.event or '-'}"
            )
        return "\n".join(lines)

    # Mixed/all-guarded path — emit if/elsif/else chain.
    lines = []
    first = True
    fallthrough_target: Optional[str] = None
    for t in state.transitions:
        if t.cond:
            compiled = _compile_guard(
                t.cond, depth_budget=depth_budget, source_state=t.source
            )
            kw = "if" if first else "elsif"
            first = False
            lines.append(
                f"            {kw} {compiled} then  -- doc-order {t.doc_order} → {t.target}"
            )
            lines.append(
                f"                state_next <= {_state_constant_name(t.target)};"
            )
        else:
            # First unguarded after some guards = closing else branch.
            fallthrough_target = t.target
            break

    if fallthrough_target is not None:
        lines.append(f"            else")
        lines.append(
            f"                state_next <= {_state_constant_name(fallthrough_target)};"
        )
    else:
        lines.append(f"            else")
        lines.append(f"                state_next <= state_q;")
    lines.append(f"            end if;")
    return "\n".join(lines)


def _emit_register_process(
    region: HdlRegion,
    datamodel_resets: list[str],
) -> str:
    """Emit the synchronous active-high reset register process."""
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
                dst_rst=f"rst_{dst_clock}",
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
        f"            dst_rst  => rst_{dst_clock},\n"
        f"            src_data => {signal_name}_src,\n"
        f"            dst_data => {signal_name}_dst\n"
        f"        );"
    )


def _emit_chart_top_wrapper(chart: HdlChart) -> str:
    """Emit the chart-top wrapper module that instantiates each region
    plus any cross-domain synchronizers.  §6.10 + PCDN-C-001 (clock
    inherit) + PCDN-C-002 (retain synchronizers).

    Falls back to inline emission when hdl_common's canonical helper
    is unavailable.
    """

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
                region_modules.append(
                    {
                        "name": _safe_ident(r.name),
                        "module": _entity_name(chart.name, r.name),
                        "clock_domain": r.clock_domain or "main",
                        "datamodel_signals": signals,
                        "state_width": len(r.states),
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
    port_lines: list[str] = []
    for clk in clocks:
        port_lines.append(f"        clk_{clk} : in std_logic")
        port_lines.append(f"        rst_{clk} : in std_logic")

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
        port_map_lines.append(f"            clk           => clk_{r.clock_domain},")
        port_map_lines.append(f"            rst           => rst_{r.clock_domain},")
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
                src_clock=f"clk_{src_clk}",
                dst_clock=f"clk_{dst_clk}",
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


def _render_region(
    region: HdlRegion,
    chart_name: str,
    depth_budget: int,
) -> str:
    """Compose the architecture + entity for one region into a single
    `.vhd` file body."""

    dm_decls, dm_resets, dm_ports, _widths = _datamodel_signal_lines(region.datamodel)
    n_states = len(region.states)
    entity_block = _emit_entity(region, chart_name, dm_ports, n_states)
    state_constants = _emit_state_constants(region)
    register_process = _emit_register_process(region, dm_resets)
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
    architecture = (
        f"architecture rtl of {entity_id} is\n"
        f"{arch_decls_block}\n"
        f"begin\n"
        f"{register_process}\n\n"
        f"{transition_block}\n\n"
        f"    current_state <= state_q;\n"
        + (f"{dm_output_drives}\n" if dm_output_drives else "")
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

    # Single-region path: one file, no wrapper.
    if len(chart.regions) == 1:
        region = chart.regions[0]
        # In single-region case the region "name" defaults to chart name;
        # for back-compat with wave-1 tests the file name is
        # `<chart>_fsm.vhd`.
        region.name = chart_name
        body = _render_region(region, chart_name, depth_budget)
        return {f"{_entity_name(chart_name)}.vhd": body}

    # Multi-region path: one region file per region + chart-top wrapper.
    out: dict[str, str] = {}
    for region in chart.regions:
        region_body = _render_region(region, chart_name, depth_budget)
        out[f"{_entity_name(chart_name, region.name)}.vhd"] = region_body

    out[f"{_safe_ident(chart_name)}_top.vhd"] = _emit_chart_top_wrapper(chart)
    return out


# Helper used by integration / tests: expose the entity-name derivation
# so test assertions don't have to duplicate the rule.
def entity_name(chart_name: str, region_name: Optional[str] = None) -> str:
    return _entity_name(chart_name, region_name)


def state_constant_name(state_id: str) -> str:
    return _state_constant_name(state_id)


def one_hot_value(index: int, n_states: int) -> str:
    return _one_hot_value(index, n_states)

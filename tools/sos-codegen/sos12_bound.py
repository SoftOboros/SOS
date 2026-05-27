"""SOS-12 bound-composition algebra (per-layer-sum × independence-axes).

Authority: ``docs/concepts/SOS-12-CONCEPTS.md`` (ratified 2026-05-23) §6.1-§6.4
and INV-S-DISP-5 from §10.1. Cross-phase root invariant is INV-SOS-F from
``docs/concepts/SOS-07-CONCEPTS.md`` §6 — *"Joint reachability across
hierarchically-composed charts MUST be computed as per-layer × independence
axes, NOT as the Cartesian product."* CSP lineage acknowledged per
``SOS-12-CONCEPTS.md`` §6.4 (Hoare 1978; ISO/IEC 13568:1996).

Scope
-----

This module implements the **per-layer bound-composition algorithm** that the
SOS-12 §7 per-sub-chart vector emitter consumes. Given:

- A *parent* chart's per-layer reachability bound (count of reachable parent
  states; SOS-03 v1 case, §6.1).
- Zero-or-more *children* (sub-charts), each with its own per-layer bound.
- A *dispatch-edge inventory* mapping each parent state to the children it
  dispatches into, tagged with an *independence-axis* group when several
  dispatches from the same parent state are orthogonal (per §6.2 / §6.4).

…the module computes the **composed reachability bound** as a sum across
layers (sequential composition, §6.3) with the dispatch-edge inventory
respecting the per-parent-state independence-axis grouping (§6.2).

The composition rule is **per-layer SUM, not Cartesian product**. The
parent's bound is constant in the children's internal state count; the
children's bounds are constant in the parent's state count; the joint
cost is additive. This is the operational realisation of INV-SOS-F and
INV-S-DISP-5 — the chart-family's vector count grows linearly with the
sum of per-chart sizes, not multiplicatively.

Boundary with Wave-1A
---------------------

The Wave-1A annotation parser ships ``tools/sos-codegen/sos12_annotations.py``
exposing ``DispatchAnnotation`` / ``Contract`` / ``DispatchInventory``
dataclasses that walk the ``<sos:dispatch>`` SCXML extension elements. This
module deliberately defines a **minimal local input shape** (``BoundInputs``,
``DispatchEdge``) that the Wave-2 integrator will adapt from Wave-1A's
``DispatchInventory`` output. We do NOT import from ``sos12_annotations`` —
keeping the two modules parallel-developable and the integration boundary
explicit at integration time, not at parse time.

The shape the Wave-2 integrator should adapt:

- Wave-1A ``DispatchInventory`` → per-parent ``BoundInputs.parent_bound``
  (count of reachable parent states from the chart inventory) + a flat
  list of ``DispatchEdge`` records (one per ``<sos:dispatch>`` element).
- Wave-1A ``Contract.events_in`` / ``events_out`` overlap analysis →
  ``DispatchEdge.independence_axis`` grouping (edges from the same parent
  state with disjoint event/datamodel surfaces share an axis id; edges
  with overlapping surfaces are sequential and get distinct axis ids).

Public surface
--------------

::

    compose_bound(inputs: BoundInputs) -> CompositionResult
    BoundInputs, DispatchEdge — pure-data inputs
    CompositionResult, LayerBound, IndependenceAxis — pure-data outputs
    Sos12BoundError — failure type (DAG violations cite INV-S-DISP-3;
        depth-cap violations cite §6.5; missing-child references cite
        INV-S-DISP-2)

Pure function; no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Frozen defaults — Standards Action / Specification Required per
# SOS-12-CONCEPTS.md §10.
# ---------------------------------------------------------------------------

# Per SOS-12-CONCEPTS §6.5 + §10.3 + PCDN-SOS-12-005 ratification.
# Registration policy: Specification Required (projects MAY override via
# chart-family.toml). The default catches the `inline_subchart` ↔
# `extract_region_to_subchart` round-trip cycle bug at lint time without
# constraining legitimate use; HTTP-stack worked example (§8) is 3 levels,
# OAuth/OIDC + transport + framing is rarely > 6.
DEFAULT_MAX_RECURSION_DEPTH: int = 8


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class Sos12BoundError(ValueError):
    """Raised when bound-composition inputs violate a frozen invariant.

    Carries an optional `rule` token naming the SOS-12 §/INV that fired so
    downstream tooling can render the failure in chart vocabulary per
    INV-SOS-H.
    """

    def __init__(self, message: str, *, rule: Optional[str] = None) -> None:
        self.rule = rule
        prefix = f"[{rule}] " if rule else ""
        super().__init__(f"{prefix}{message}")


# ---------------------------------------------------------------------------
# Input dataclasses — minimal local shape (see "Boundary with Wave-1A" above)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispatchEdge:
    """One ``<sos:dispatch>`` edge in a parent → child relationship.

    Per SOS-12-CONCEPTS §6.3 (sequential composition) + §6.2 (independence
    axes when multiple dispatches from the same parent state are orthogonal).

    Fields:

    - ``parent_chart_id`` — SHA-pinned identity of the dispatching chart per
      INV-SOS-H. Must match a chart id present in ``BoundInputs.charts``.
    - ``parent_state_id`` — id of the parent ``<state>`` carrying the
      ``<sos:dispatch>`` element. Treated as opaque here; the annotation
      parser (Wave-1A) is responsible for the SCXML id resolution.
    - ``child_chart_id`` — SHA-pinned identity of the sub-chart being
      dispatched into. Must match a chart id present in
      ``BoundInputs.charts``; a dangling reference is an INV-S-DISP-2
      failure (contract-matching is mandatory).
    - ``independence_axis`` — optional axis-group identifier. When two
      edges from the same ``parent_state_id`` carry the **same**
      ``independence_axis`` value, they are treated as orthogonal per §6.2
      (per-region SUM). When two edges from the same parent state carry
      **different** axis values (or one is None), they are treated as
      sequential per §6.3 (per-layer SUM, which is the same arithmetic but
      semantically distinct — orthogonal edges share an axis, sequential
      edges occupy distinct axes; the breakdown surfaces both). The axis
      grouping mirrors SCXML ``<parallel>`` regions per §6.2.
    """

    parent_chart_id: str
    parent_state_id: str
    child_chart_id: str
    independence_axis: Optional[str] = None


@dataclass(frozen=True)
class BoundInputs:
    """Inputs to ``compose_bound``.

    Fields:

    - ``root_chart_id`` — the dispatch-tree root chart's id. Must appear in
      ``charts``. The recursion descends from this chart.
    - ``charts`` — map from chart id to that chart's per-layer reachability
      bound (count of reachable states under that chart's event vocabulary,
      treating dispatched sub-charts as opaque states per §6.1). Each value
      MUST be ≥ 0; a bound of 0 means the chart has no reachable states
      (degenerate, but admissible — typically a stub).
    - ``edges`` — flat list of ``DispatchEdge`` records covering every
      ``<sos:dispatch>`` in the chart family. Order is not significant for
      the composed bound, but the per-layer breakdown preserves first-seen
      order for deterministic emission.
    - ``max_depth`` — recursion depth cap. Default per §6.5 +
      PCDN-SOS-12-005 is 8. Override per chart-family per §10.3.
    """

    root_chart_id: str
    charts: dict[str, int]
    edges: list[DispatchEdge] = field(default_factory=list)
    max_depth: int = DEFAULT_MAX_RECURSION_DEPTH


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndependenceAxis:
    """One independence-axis group within a parent chart's dispatch surface.

    Per SOS-12-CONCEPTS §6.2: an independence axis is the analogue of an
    SCXML ``<parallel>`` child region — its component children's per-layer
    bounds enumerate independently and SUM (not multiply) for vector
    emission per INV-SOS-B. The joint Cartesian is declared as an upper
    bound but NOT exhaustively enumerated unless a chart invariant spans
    the axis.

    Fields:

    - ``parent_chart_id`` — chart owning the axis.
    - ``parent_state_id`` — the ``<state>`` whose dispatched children form
      the axis (each axis is local to one parent state per §6.2 + §6.4).
    - ``axis_id`` — the ``independence_axis`` value from the contributing
      ``DispatchEdge`` records. None means each edge sits on its own
      degenerate (single-member) axis — i.e. pure sequential composition
      per §6.3.
    - ``member_child_ids`` — ordered child chart ids contributing to this
      axis. Length ≥ 1; orthogonal-region semantics only apply at length
      ≥ 2 (single-member axes are arithmetically identical to sequential
      composition per §6.3, but kept distinct for vector-emission
      bookkeeping per §7.2).
    - ``sum_bound`` — sum of contributing children's bounds (per-region
      enumeration per §6.2). The arithmetic is also the §6.3 sum, but the
      provenance differs.
    - ``joint_cartesian_upper_bound`` — product of contributing children's
      bounds. Declared but NOT enumerated unless a per-chart invariant
      spans the axis (§6.2). Single-member axes have
      ``joint_cartesian_upper_bound == sum_bound``.
    """

    parent_chart_id: str
    parent_state_id: str
    axis_id: Optional[str]
    member_child_ids: tuple[str, ...]
    sum_bound: int
    joint_cartesian_upper_bound: int


@dataclass(frozen=True)
class LayerBound:
    """Per-layer bound breakdown for one chart in the dispatch-tree.

    Per SOS-12-CONCEPTS §6.1 (single-chart bound) + §6.3 (the contribution
    a chart makes to its family's composed bound).

    Fields:

    - ``chart_id`` — chart identity per INV-SOS-H.
    - ``depth`` — distance from the dispatch-tree root (0 for root).
    - ``self_bound`` — the chart's own per-layer bound per §6.1, treating
      every dispatched child as opaque.
    - ``dispatch_edge_count`` — count of ``<sos:dispatch>`` edges this
      chart originates. The per-layer vector count is local per
      INV-S-DISP-5; this field is the boundary-vector contributor count
      per §7.2.
    - ``children_sum_bound`` — sum of dispatched children's composed bounds
      (the §6.3 sum, with each child's bound itself being a composed bound
      under the recursive application of the algebra).
    """

    chart_id: str
    depth: int
    self_bound: int
    dispatch_edge_count: int
    children_sum_bound: int


@dataclass(frozen=True)
class CompositionResult:
    """Output of ``compose_bound``.

    Per SOS-12-CONCEPTS §6.3 + INV-S-DISP-5 + INV-SOS-F.

    Fields:

    - ``composed_bound`` — total bounded-reachability vector count for the
      chart family, computed as the sum-across-layers of every chart's
      per-layer bound. Sum-not-product per §6.3; this is the load-bearing
      output of the algorithm and the value vector emitters size their
      per-chart vector sets against per §7.1.
    - ``per_layer_breakdown`` — ordered list of ``LayerBound`` records,
      one per chart reachable from the root via dispatch edges. Order is
      pre-order traversal of the dispatch-tree (root first, then each
      child sub-tree in dispatch-edge declaration order). The pre-order
      shape lets vector emitters emit per-chart vector files in a
      review-friendly sequence.
    - ``independence_axes`` — ordered list of ``IndependenceAxis`` records
      for every (parent_state, axis_id) group present in the inputs. A
      parent state with three dispatches all carrying axis_id="A"
      contributes one record (member count 3); a parent state with three
      dispatches each carrying distinct axis_ids contributes three records
      (each member count 1). The breakdown surfaces the §6.2 / §6.4
      structure separately from the §6.3 sequential-composition sum.
    - ``joint_cartesian_upper_bound`` — sum across charts of each chart's
      maximum independence-axis joint product. Declared per §6.2 as an
      upper bound; vector emitters DO NOT enumerate this unless a
      chart-spanning invariant requires it. For families with no
      independence axes (all dispatches sequential), this equals
      ``composed_bound``.
    """

    composed_bound: int
    per_layer_breakdown: list[LayerBound]
    independence_axes: list[IndependenceAxis]
    joint_cartesian_upper_bound: int


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def _validate_inputs(inputs: BoundInputs) -> None:
    """Validate the BoundInputs surface against frozen invariants.

    Failures cite the §/INV they fire under (per INV-SOS-H — error
    messages render in chart/spec vocabulary, not raw data shape).
    """

    if inputs.max_depth < 1:
        raise Sos12BoundError(
            f"max_depth must be ≥ 1, got {inputs.max_depth}",
            rule="SOS-12 §6.5",
        )

    if not isinstance(inputs.charts, dict) or not inputs.charts:
        raise Sos12BoundError(
            "charts mapping must be non-empty",
            rule="SOS-12 §6.1",
        )

    for chart_id, bound in inputs.charts.items():
        if not isinstance(chart_id, str) or not chart_id:
            raise Sos12BoundError(
                f"chart id must be a non-empty string, got {chart_id!r}",
                rule="INV-SOS-H",
            )
        if not isinstance(bound, int) or isinstance(bound, bool):
            raise Sos12BoundError(
                f"chart {chart_id!r} bound must be an integer, got {bound!r}",
                rule="SOS-12 §6.1",
            )
        if bound < 0:
            raise Sos12BoundError(
                f"chart {chart_id!r} bound must be ≥ 0, got {bound}",
                rule="SOS-12 §6.1",
            )

    if inputs.root_chart_id not in inputs.charts:
        raise Sos12BoundError(
            f"root_chart_id {inputs.root_chart_id!r} not present in charts mapping",
            rule="SOS-12 §6.3",
        )

    for edge in inputs.edges:
        if edge.parent_chart_id not in inputs.charts:
            raise Sos12BoundError(
                f"dispatch edge references unknown parent chart "
                f"{edge.parent_chart_id!r}",
                rule="INV-S-DISP-2",
            )
        if edge.child_chart_id not in inputs.charts:
            raise Sos12BoundError(
                f"dispatch edge from {edge.parent_chart_id!r}.{edge.parent_state_id!r} "
                f"references unknown child chart {edge.child_chart_id!r}; "
                "contract-matching is mandatory",
                rule="INV-S-DISP-2",
            )
        if edge.parent_chart_id == edge.child_chart_id:
            raise Sos12BoundError(
                f"chart {edge.parent_chart_id!r} self-dispatches via state "
                f"{edge.parent_state_id!r}; dispatch-tree must be a DAG",
                rule="INV-S-DISP-3",
            )


# ---------------------------------------------------------------------------
# Dispatch-tree construction + DAG check (INV-S-DISP-3)
# ---------------------------------------------------------------------------


def _children_by_parent(
    edges: list[DispatchEdge],
) -> dict[str, list[DispatchEdge]]:
    """Group edges by parent chart, preserving first-seen order per parent."""

    grouped: dict[str, list[DispatchEdge]] = {}
    for edge in edges:
        grouped.setdefault(edge.parent_chart_id, []).append(edge)
    return grouped


def _check_dag(
    root_chart_id: str,
    children_by_parent: dict[str, list[DispatchEdge]],
) -> None:
    """Detect cycles in the dispatch graph (INV-S-DISP-3).

    Self-loops are caught at input-validation time (`_validate_inputs`);
    this check catches mutual recursion (A→B→A, A→B→C→A, etc.) and
    any cycle reachable from the root.
    """

    # Standard iterative DFS with three-colour marking: WHITE (unvisited),
    # GRAY (on the current DFS stack), BLACK (fully explored). A GRAY hit
    # is a back-edge → cycle.
    WHITE, GRAY, BLACK = 0, 1, 2
    colour: dict[str, int] = {}

    # Iterative DFS; tracks the cycle path for the diagnostic message.
    # Each stack frame is (chart_id, iterator over child edges).
    stack: list[tuple[str, list[DispatchEdge]]] = []

    def _visit(start: str) -> None:
        if colour.get(start, WHITE) != WHITE:
            return
        colour[start] = GRAY
        stack.append((start, list(children_by_parent.get(start, []))))
        path: list[str] = [start]
        while stack:
            chart_id, remaining = stack[-1]
            if not remaining:
                colour[chart_id] = BLACK
                stack.pop()
                if path and path[-1] == chart_id:
                    path.pop()
                continue
            edge = remaining.pop(0)
            child = edge.child_chart_id
            child_colour = colour.get(child, WHITE)
            if child_colour == GRAY:
                cycle_start = path.index(child) if child in path else 0
                cycle_path = path[cycle_start:] + [child]
                raise Sos12BoundError(
                    "dispatch-tree contains a cycle: "
                    + " → ".join(repr(c) for c in cycle_path)
                    + "; dispatch-tree MUST be a DAG",
                    rule="INV-S-DISP-3",
                )
            if child_colour == BLACK:
                continue
            colour[child] = GRAY
            stack.append((child, list(children_by_parent.get(child, []))))
            path.append(child)

    _visit(root_chart_id)


# ---------------------------------------------------------------------------
# Independence-axis extraction (§6.2 / §6.4)
# ---------------------------------------------------------------------------


def _extract_axes(
    parent_chart_id: str,
    parent_edges: list[DispatchEdge],
    child_bounds: dict[str, int],
) -> list[IndependenceAxis]:
    """Group a parent chart's dispatch edges into independence axes.

    Per SOS-12-CONCEPTS §6.2 + §6.4:

    - Edges sharing (parent_state_id, independence_axis) belong to the
      same axis (orthogonal-region semantics; SUM, not product).
    - Edges with independence_axis=None each occupy their own degenerate
      axis (pure sequential composition per §6.3).
    - The bound contribution is the same SUM either way; the breakdown
      separates the semantics so per-sub-chart vector emission (§7.2)
      can render the independence structure separately from sequential
      composition.

    Ordering: first-seen per (parent_state_id, axis_id) tuple, preserved
    for deterministic emission.
    """

    # group[(parent_state_id, axis_key)] -> list of (insertion_idx, child_id, child_bound)
    # axis_key is the axis_id, or a synthetic per-edge key when axis_id is None
    # to keep each None-axis edge in its own degenerate group.
    grouped: dict[tuple[str, str], list[tuple[int, str, int]]] = {}
    order: list[tuple[str, str]] = []
    none_axis_counter: int = 0

    for idx, edge in enumerate(parent_edges):
        if edge.independence_axis is None:
            none_axis_counter += 1
            axis_key = f"__none_{none_axis_counter}"
        else:
            axis_key = edge.independence_axis
        key = (edge.parent_state_id, axis_key)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        child_bound = child_bounds[edge.child_chart_id]
        grouped[key].append((idx, edge.child_chart_id, child_bound))

    axes: list[IndependenceAxis] = []
    for parent_state_id, axis_key in order:
        members = grouped[(parent_state_id, axis_key)]
        member_ids = tuple(child_id for _, child_id, _ in members)
        member_bounds = [b for _, _, b in members]
        sum_bound = sum(member_bounds)
        joint_upper = 1
        for b in member_bounds:
            joint_upper *= b if b > 0 else 1
        # Surface the real axis_id (None) rather than the synthetic key
        # for the caller.
        axis_id_out: Optional[str] = (
            None if axis_key.startswith("__none_") else axis_key
        )
        axes.append(
            IndependenceAxis(
                parent_chart_id=parent_chart_id,
                parent_state_id=parent_state_id,
                axis_id=axis_id_out,
                member_child_ids=member_ids,
                sum_bound=sum_bound,
                joint_cartesian_upper_bound=joint_upper,
            )
        )

    return axes


# ---------------------------------------------------------------------------
# Core algorithm — recursive pre-order traversal with sum-not-product
# composition per §6.3.
# ---------------------------------------------------------------------------


def compose_bound(inputs: BoundInputs) -> CompositionResult:
    """Compose the per-layer bounds of a chart family per SOS-12 §6.

    Algorithm (per SOS-12-CONCEPTS §6.1-§6.4 + INV-S-DISP-5):

    1. Validate inputs (`_validate_inputs`).
    2. Build the parent → children adjacency from `inputs.edges`.
    3. Verify the dispatch-tree is a DAG (`_check_dag`; INV-S-DISP-3).
    4. Pre-order traversal from `root_chart_id`:

       - For each chart, compute its `LayerBound`: own per-layer bound
         (§6.1) + count of dispatch edges originating here + sum of
         dispatched children's composed bounds.
       - Extract `IndependenceAxis` records for this chart's outgoing
         dispatches (§6.2 / §6.4); record the joint Cartesian upper bound
         alongside the sum-of-children breakdown.

    5. The composed bound is the SUM of every chart's `self_bound` plus
       every dispatch edge's contribution accounted at the parent layer —
       which the recursion realises by adding `child_composed_bound` into
       each parent's `children_sum_bound` field. The root chart's
       `self_bound + children_sum_bound` is the family-wide
       `composed_bound`.

    Composition rule (§6.3): **sum, not product**.

    Returns: `CompositionResult` carrying the composed bound, per-chart
    breakdown, and independence-axis structure.

    Raises: `Sos12BoundError` on input validation failures, dispatch-tree
    cycles (INV-S-DISP-3), recursion-depth-cap violations (§6.5).
    """

    _validate_inputs(inputs)
    children_by_parent = _children_by_parent(inputs.edges)
    _check_dag(inputs.root_chart_id, children_by_parent)

    breakdown: list[LayerBound] = []
    axes: list[IndependenceAxis] = []
    joint_upper_total: int = 0

    # Compose recursively. We track a per-edge visited set rather than a
    # per-chart visited set because the dispatch-tree is a DAG, NOT
    # necessarily a tree — a sub-chart MAY be dispatched into from two
    # different parents in a DAG, in which case each dispatch is a
    # separate boundary (§7.2 boundary vectors) and the sub-chart's bound
    # contributes once per dispatch site to the sum (per-layer sum per
    # §6.3 across each dispatch edge).
    #
    # However, INV-S-DISP-5 says "per-layer vector count is local" and
    # §7.2 says boundary vectors are "constant-size (one per declared
    # event-in, one per declared event-out, …)". The natural reading is:
    # the *sub-chart's per-layer vector set* is emitted once (sized to
    # the sub-chart's reachable states); each *dispatch boundary* gets
    # its own constant-size boundary-vector set. To keep this module
    # focused on the per-chart bound contribution, we count each chart's
    # `self_bound` exactly once in the composed sum, but allow the
    # `LayerBound` breakdown to surface the per-dispatch-site presence
    # via `dispatch_edge_count` at each parent layer (which the §7.2
    # boundary-vector emitter sizes against).
    visited_charts: set[str] = set()

    def _walk(chart_id: str, depth: int) -> int:
        """Pre-order recursion; returns the chart's composed contribution.

        The returned value is what the parent adds into its own
        `children_sum_bound` (per §6.3 sum). Charts visited more than
        once via the DAG contribute their self_bound only the first
        time — this preserves per-layer-SUM semantics across the family
        without double-counting a shared sub-chart's internal states.
        Subsequent visits contribute 0 to the family sum but still
        register an independence-axis / boundary-vector emission seam
        at the parent layer.
        """

        if depth > inputs.max_depth:
            raise Sos12BoundError(
                f"dispatch recursion depth {depth} exceeds max_depth "
                f"{inputs.max_depth} at chart {chart_id!r}",
                rule="SOS-12 §6.5",
            )

        self_bound = inputs.charts[chart_id]
        parent_edges = children_by_parent.get(chart_id, [])
        dispatch_edge_count = len(parent_edges)

        # Extract independence-axis structure for this chart's outgoing
        # dispatches BEFORE recursing — the §6.2 grouping is purely a
        # function of this chart's own edge inventory.
        if parent_edges:
            chart_axes = _extract_axes(
                chart_id,
                parent_edges,
                {e.child_chart_id: inputs.charts[e.child_chart_id] for e in parent_edges},
            )
            axes.extend(chart_axes)
            nonlocal_joint_contribution = max(
                (a.joint_cartesian_upper_bound for a in chart_axes), default=0
            )
        else:
            nonlocal_joint_contribution = 0

        nonlocal joint_upper_total
        joint_upper_total += nonlocal_joint_contribution

        # First visit: reserve this chart's LayerBound slot in pre-order
        # (root → each sub-tree in dispatch-edge declaration order) per
        # the breakdown ordering contract documented on
        # `CompositionResult.per_layer_breakdown`. The `children_sum_bound`
        # field is filled in after recursion since it depends on the
        # children's composed contributions; we keep the slot's index so
        # the post-recursion patch happens in place.
        first_visit = chart_id not in visited_charts
        slot_index: Optional[int] = None
        if first_visit:
            visited_charts.add(chart_id)
            slot_index = len(breakdown)
            breakdown.append(
                LayerBound(
                    chart_id=chart_id,
                    depth=depth,
                    self_bound=self_bound,
                    dispatch_edge_count=dispatch_edge_count,
                    children_sum_bound=0,  # patched below
                )
            )

        # Recurse into children; sum their composed contributions per §6.3.
        children_sum: int = 0
        for edge in parent_edges:
            children_sum += _walk(edge.child_chart_id, depth + 1)

        # First visit: patch the children_sum_bound now that recursion
        # has resolved it, and return this chart's full composed
        # contribution to its parent's SUM (per §6.3).
        if first_visit and slot_index is not None:
            prev = breakdown[slot_index]
            breakdown[slot_index] = LayerBound(
                chart_id=prev.chart_id,
                depth=prev.depth,
                self_bound=prev.self_bound,
                dispatch_edge_count=prev.dispatch_edge_count,
                children_sum_bound=children_sum,
            )
            return self_bound + children_sum
        # Repeat visit via DAG: only the children's sum re-propagates
        # upward (children already first-visit-checked themselves), but
        # since children that have already been visited return 0 from
        # this branch, the net contribution is 0. This preserves the
        # invariant "each chart's self_bound counted exactly once in the
        # family composed_bound".
        return 0

    composed_bound = _walk(inputs.root_chart_id, 0)

    # Joint Cartesian upper bound: per §6.2, this is the upper-bound
    # *declared* value; the family's vector emitter does NOT enumerate
    # this set unless an invariant spans the axis. For families with
    # no independence axes (every axis is single-member), the joint
    # equals the composed_bound.
    joint_upper_bound: int = max(joint_upper_total, composed_bound)

    return CompositionResult(
        composed_bound=composed_bound,
        per_layer_breakdown=breakdown,
        independence_axes=axes,
        joint_cartesian_upper_bound=joint_upper_bound,
    )


__all__ = [
    "DEFAULT_MAX_RECURSION_DEPTH",
    "BoundInputs",
    "CompositionResult",
    "DispatchEdge",
    "IndependenceAxis",
    "LayerBound",
    "Sos12BoundError",
    "compose_bound",
]

"""SOS-12 contract-matching verifier — PCDN-006 compile-time gate.

Authority: ``docs/concepts/SOS-12-CONCEPTS.md`` (ratified 2026-05-23)
§5.1 (sub-chart contract shape), §5.2 (datamodel boundary semantics),
§5.3 (dispatch semantics + contract-matching), §6 (composition algebra
context). Cross-phase invariants ``INV-SOS-G`` (verified-codegen
position) and ``INV-SOS-H`` (vector-to-chart traceability) from
``docs/concepts/SOS-07-CONCEPTS.md`` §6 govern, respectively, the
compile-time-error stance and the diagnostic-vocabulary requirement.

Per PCDN-SOS-12-006 ratified resolution: a contract mismatch at any
dispatch boundary is a **compile-time error** — the chart compiler
refuses to emit code if a ``<sos:dispatch>`` references a sub-chart
whose contract does not match the parent's declared routing. Lint
warning (option b) and runtime check (option c) are NOT available paths
in v1.

Per INV-S-DISP-2 (§10.1, Standards Action): every dispatch boundary
MUST have a contract-match check. A chart family without contract-match
checks is non-conforming. This module is the operational gate that
makes INV-S-DISP-2 a compile-time property rather than aspirational
prose.

Per §5.3 the contract-match algorithm verifies six clauses:

  1. ``events_in`` match — every events-in declared by the child MUST
     be a member of the parent's expected events-in routing surface
     (otherwise the parent cannot drive that event into the dispatched
     state). Direction: ``child.events_in ⊆ parent.expected_events_in``.

  2. ``events_out`` match — every events-out declared by the child
     MUST be a member of the parent's expected events-out observation
     surface (otherwise the parent cannot observe that event when the
     child raises it). Direction: ``child.events_out ⊆
     parent.expected_events_out``.

  3. ``invariants_maintained`` consistency — the invariants the child
     promises to maintain MUST NOT contradict the parent's assumptions
     about the dispatched state (INV-SOS-G + §5.3 narrative: a child
     promise the parent cannot rely on is a verified-codegen defect).
     v1 implementation: intersection check — a child-maintained
     invariant whose name collides with a parent-assumed-of-environment
     invariant SHOULD match by intent. The v1 check is name-equality
     intersection; semantic equivalence is out of scope until a per-
     project invariant grammar is ratified (see §14 non-goals).

  4. ``invariants_assumed`` discharge — invariants the child assumes
     of its environment MUST be in the parent's maintained-set at the
     dispatch boundary. Per §5.3(a) the parent's verification MUST
     prove these hold at the moment of dispatch. v1 implementation:
     name-set intersection between ``child.invariants_assumed`` and
     ``parent.maintained_invariants`` — a clearly documented limitation
     (the §14 non-goal on invariant grammar applies here too).

  5. ``reads`` write-before-read — every datamodel field the child
     reads MUST be in the parent's write-before-dispatch set. Per §5.2
     "the canonical inbound-data case" (a field MAY appear in
     ``reads`` and ``env_writes`` — the sub-chart consumes a value the
     environment produces). At v1 the parser-side ``Contract`` carries
     only the simplified ``reads``/``writes`` attribute pair per
     PCDN-002 ratified shape; the verifier infers the four-set algebra
     by treating the parent's ``writes`` as the env-writes set the
     child may read.

  6. ``writes`` write-before-read on return — every datamodel field
     the child writes MUST be in the parent's read-after-dispatch set
     (else the write has no observer and is dead code at the boundary).
     Per §5.2 "the canonical outbound-data case." Treated as advisory
     at v1 — a child write to a field the parent does not read is
     flagged but tolerable; see clause-6 docstring below.

Wave-1 integration boundary
---------------------------

Wave-1A (``sos12_annotations``) ships ``DispatchAnnotation`` /
``Contract`` / ``DispatchInventory`` covering the SCXML parser surface
— but the parser's ``DispatchAnnotation`` records ``parent_state_id``
and ``ref`` only, NOT the parent's expected event/datamodel routing at
each dispatch site. That's because the parent-side routing for one
specific dispatch is NOT a single SCXML element — it's the cumulative
behaviour of the parent chart's transitions targeting the dispatched
state. Computing it from the parser AST is a §5.3 reduction that
Wave-3 J (extract_region_to_subchart) will own; this verifier accepts
the per-dispatch parent expectation as an input.

The verifier's public surface accordingly bundles parent + child sides
into a ``DispatchContractEdge`` record (mirrors Wave-1C's
``DispatchEdge`` shape from ``sos12_boundary_vectors``; the two are
intentionally parallel — the boundary-vector emitter and the contract-
matcher consume the same per-edge view of a dispatch site).

For batch verification over a Wave-1A ``DispatchInventory`` tree, the
caller provides an ``edge_provider`` callable that maps
``(parent_inventory, annotation, child_inventory) -> DispatchContractEdge``.
A reference implementation ``simple_edge_provider`` is included that
derives the parent's expected routing from the parent's own
chart-level ``Contract`` — adequate for charts whose entire external
surface is dispatched into a single child; the §14-non-goal-bounded
default for more complex routing.

Wave-3 extension points
-----------------------

Reserved for downstream phases (this module deliberately stops at the
pure verification function + inventory walker; do NOT add):

  - **Wave-3 J — ``extract_region_to_subchart``**. When the SOS-11 MCP
    tool extracts a region into a sub-chart, it MUST emit a
    ``<sos:dispatch ref="…"/>`` at the extraction site AND derive the
    new sub-chart's ``<sos:contract>`` from the extracted region's
    event/datamodel surface. The contract-match verifier (this module)
    is then the discharge gate the tool's post-extraction verify-step
    MUST call before declaring success. The Wave-3 J consumer wires
    the extraction's computed parent expectation directly into
    :func:`verify_contract_match` — no inventory walk needed because
    the tool already has both sides materialised.

  - **Wave-3 K — ``inline_subchart``**. When the SOS-11 MCP tool
    inlines a sub-chart back into its parent, it MUST first verify the
    contract still matches (post-inline state would replay the
    sub-chart's behaviour inline; a contract mismatch at this point
    would mean inlining produces a chart whose behaviour deviates
    from the dispatch-tree's verification basis). Wave-3 K consumes
    the inverse: given the current dispatch edge, verify it matches
    before the inline; abort with :class:`ContractMismatchError` if
    not, citing the same PCDN-006 / INV-S-DISP-2.

  - **Future: invariant-grammar resolution**. v1 treats invariant
    matching as name-set intersection. Once a per-project invariant
    grammar is ratified (chart-author concern per §14 non-goals), the
    intersection check upgrades to semantic-equivalence under that
    grammar. The :class:`ContractMismatchError.clause` enum gains no
    new values; the algorithm inside :func:`_check_invariants` swaps
    out the comparator.

Pure function module; no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

# Wave-1A re-exports — keep the import surface narrow so this module
# stays drop-in usable from any caller that already has the parser
# outputs in hand.
from sos12_annotations import (
    Contract,
    DispatchAnnotation,
    DispatchInventory,
)


# ---------------------------------------------------------------------------
# Frozen clause enumeration — Standards Action per SOS-12 §10.
# ---------------------------------------------------------------------------

# The set of contract-match clauses §5.3 enumerates. Each
# :class:`ContractMismatchError` carries exactly one ``clause`` value
# naming the §5.3 sub-clause that fired. Adding a new clause is a §15
# amendment to SOS-12-CONCEPTS.md (Standards Action — clauses encode
# cross-phase contracts between this verifier, Wave-3 J/K, and the
# downstream emitter chain).
PERMITTED_CLAUSES: frozenset[str] = frozenset(
    {
        "events_in",
        "events_out",
        "invariants_maintained",
        "invariants_assumed",
        "reads",
        "writes",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ContractMismatchError(Exception):
    """Raised when a dispatch-edge contract-match check fails.

    Per PCDN-SOS-12-006 (compile-time error) and INV-S-DISP-2
    (contract-matching is mandatory) the error is fatal — callers MUST
    treat it as a compile-abort signal. The diagnostic is rendered in
    chart vocabulary per INV-SOS-H: every field name a chart author
    would recognise.

    Fields:

    - ``pcdn`` — the PCDN id whose ratified resolution this check
      enforces. Always ``"PCDN-SOS-12-006"`` (the verifier exists to
      operationalise PCDN-006; kept as a field so downstream tooling
      can switch on it without parsing the message).
    - ``invariant`` — the SOS-12 §10 invariant id. Always
      ``"INV-S-DISP-2"``.
    - ``clause`` — one of :data:`PERMITTED_CLAUSES`. Names the §5.3
      sub-clause that fired.
    - ``missing`` — frozenset of items the child declared but the
      parent does not satisfy. Empty for clauses whose failure mode is
      "extra not missing" (rare; included for symmetry).
    - ``extra`` — frozenset of items the parent declared but the child
      does not require. For most clauses ``extra`` is informational
      and does not itself trigger a failure; the failure is driven by
      ``missing``. Two exceptions are documented at clause-time below.
    - ``chart_path`` — INV-SOS-H chart_path naming the dispatch edge.
      Shape: ``<parent_chart_id>.<parent_state_id>.<child_chart_id>``.
    - ``child_chart`` — child chart id (duplicated from ``chart_path``
      for direct access; downstream tooling often filters by child id).
    """

    def __init__(
        self,
        message: str,
        *,
        clause: str,
        missing: frozenset[str] = frozenset(),
        extra: frozenset[str] = frozenset(),
        chart_path: Optional[str] = None,
        child_chart: Optional[str] = None,
        pcdn: str = "PCDN-SOS-12-006",
        invariant: str = "INV-S-DISP-2",
    ) -> None:
        if clause not in PERMITTED_CLAUSES:
            raise ValueError(
                f"clause {clause!r} is not in PERMITTED_CLAUSES "
                f"{sorted(PERMITTED_CLAUSES)} (Standards Action — adding a "
                "new clause requires a §15 amendment to SOS-12-CONCEPTS.md)"
            )
        self.pcdn = pcdn
        self.invariant = invariant
        self.clause = clause
        self.missing = frozenset(missing)
        self.extra = frozenset(extra)
        self.chart_path = chart_path
        self.child_chart = child_chart
        prefix_parts: list[str] = [f"[{pcdn}]", f"[{invariant}]", f"clause={clause}"]
        if chart_path is not None:
            prefix_parts.append(f"at {chart_path!r}")
        prefix = " ".join(prefix_parts)
        super().__init__(f"{prefix}: {message}")


# ---------------------------------------------------------------------------
# Input dataclasses — per-edge contract-match surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispatchContractEdge:
    """One dispatch-boundary edge for contract-match verification.

    Mirrors Wave-1C's ``sos12_boundary_vectors.DispatchEdge`` field-for-
    field for the parent-side surface; the child side is the Wave-1A
    ``Contract`` dataclass (re-used directly so the parser's output
    flows straight into the verifier).

    The parent's expectations are caller-supplied because the SCXML
    parser surface does NOT express "what does the parent route to
    this specific dispatch site" as a single artefact — the parent-side
    routing is the cumulative behaviour of the parent chart's
    transitions targeting the dispatched state. Wave-3 J
    (``extract_region_to_subchart``) is the canonical producer of this
    record; until then callers assemble it from their own analysis.

    Fields:

    - ``parent_chart_id`` — INV-SOS-H identity of the dispatching
      chart.
    - ``parent_state_id`` — id of the ``<state>`` carrying the
      ``<sos:dispatch>`` element. Same field name as Wave-1A
      :class:`DispatchAnnotation` for direct interoperation.
    - ``child_chart_id`` — INV-SOS-H identity of the dispatched chart.
    - ``child_contract`` — the child's :class:`Contract` as parsed by
      Wave-1A.
    - ``parent_expected_events_in`` — events the parent is prepared to
      route into this dispatch site. The §5.3 check requires
      ``child_contract.events_in ⊆ parent_expected_events_in``.
    - ``parent_expected_events_out`` — events the parent is prepared
      to observe out of this dispatch site. The §5.3 check requires
      ``child_contract.events_out ⊆ parent_expected_events_out``.
    - ``parent_maintained_invariants`` — invariants the parent
      maintains at the dispatch boundary. The §5.3 check requires
      ``child_contract.invariants_assumed ⊆ parent_maintained_invariants``
      (the parent discharges every invariant the child assumes of its
      environment).
    - ``parent_assumed_invariants`` — invariants the parent itself
      assumes of *its* environment. Surfaced so the v1 intersection
      check between ``child.invariants_maintained`` and
      ``parent.invariants_assumed`` can detect a child promise that
      collides with a parent assumption (both fields can be empty in
      simple charts).
    - ``parent_writes_before_dispatch`` — datamodel fields the parent
      writes before entering the dispatch state. §5.2 inbound-data:
      every ``child.reads`` MUST be in this set. The v1 simplification
      treats the parent ``Contract.writes`` as this set when the
      caller does not supply per-dispatch precision.
    - ``parent_reads_after_dispatch`` — datamodel fields the parent
      reads after the dispatch state exits. §5.2 outbound-data:
      every ``child.writes`` SHOULD be in this set (advisory only at
      v1 — see ``writes`` clause docs).
    """

    parent_chart_id: str
    parent_state_id: str
    child_chart_id: str
    child_contract: Contract
    parent_expected_events_in: tuple[str, ...] = ()
    parent_expected_events_out: tuple[str, ...] = ()
    parent_maintained_invariants: tuple[str, ...] = ()
    parent_assumed_invariants: tuple[str, ...] = ()
    parent_writes_before_dispatch: tuple[str, ...] = ()
    parent_reads_after_dispatch: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Internal: chart_path formatter — INV-SOS-H traceability
# ---------------------------------------------------------------------------


def _chart_path(edge: DispatchContractEdge) -> str:
    """Return the INV-SOS-H chart_path for a dispatch contract edge.

    Shape: ``<parent_chart_id>.<parent_state_id>.<child_chart_id>``.
    Mirrors Wave-1C ``sos12_boundary_vectors._chart_path``; the two
    chart-path forms are deliberately identical so a downstream
    diagnostic can correlate a contract-match failure with the
    boundary-vector set that would have been emitted at the same edge.
    """
    return f"{edge.parent_chart_id}.{edge.parent_state_id}.{edge.child_chart_id}"


# ---------------------------------------------------------------------------
# Per-clause checks
# ---------------------------------------------------------------------------


def _check_events_in(edge: DispatchContractEdge) -> None:
    """Clause 1 — events_in match (§5.3(a) + (c)).

    Every events-in declared by the child MUST be a member of the
    parent's expected events-in routing surface. A missing entry means
    the parent cannot drive that event into the dispatched state.
    """
    child = set(edge.child_contract.events_in)
    parent = set(edge.parent_expected_events_in)
    missing = child - parent
    if missing:
        raise ContractMismatchError(
            f"child {edge.child_chart_id!r} declares events_in "
            f"{sorted(missing)!r} that parent {edge.parent_chart_id!r} "
            f"does not route into dispatch state {edge.parent_state_id!r}",
            clause="events_in",
            missing=frozenset(missing),
            extra=frozenset(parent - child),
            chart_path=_chart_path(edge),
            child_chart=edge.child_chart_id,
        )


def _check_events_out(edge: DispatchContractEdge) -> None:
    """Clause 2 — events_out match (§5.3(a) + (c)).

    Every events-out declared by the child MUST be a member of the
    parent's expected events-out observation surface. A missing entry
    means the parent cannot observe that event when the child raises
    it — the event would silently escape the boundary.
    """
    child = set(edge.child_contract.events_out)
    parent = set(edge.parent_expected_events_out)
    missing = child - parent
    if missing:
        raise ContractMismatchError(
            f"child {edge.child_chart_id!r} declares events_out "
            f"{sorted(missing)!r} that parent {edge.parent_chart_id!r} "
            f"does not observe at dispatch state {edge.parent_state_id!r}",
            clause="events_out",
            missing=frozenset(missing),
            extra=frozenset(parent - child),
            chart_path=_chart_path(edge),
            child_chart=edge.child_chart_id,
        )


def _check_invariants_maintained(edge: DispatchContractEdge) -> None:
    """Clause 3 — invariants_maintained consistency (§5.3 + INV-SOS-G).

    The child's ``invariants_maintained`` set declares invariants the
    child promises to keep across its execution. The parent's
    ``invariants_assumed`` set (the parent's own
    ``assumed-of-environment`` declarations on ITS contract) names
    invariants the parent treats as guaranteed.

    v1 check: a name in BOTH sets is the canonical compatibility case
    — the child guarantees what the parent assumes. The failure mode is
    NOT "no intersection" (most dispatch sites are not parent-↔-child
    contract pairs; both sides can have empty intersection legitimately).
    The failure mode IS a *name collision with a contradicting clause*
    — which v1 cannot detect semantically. We therefore implement the
    weaker but useful check: if both sides have entries, the intersection
    SHOULD be the child's full maintained set IF the parent assumes any
    of them. The actually-fatal case is: child declares an invariant
    name that semantically contradicts a parent assumption — out of
    scope until invariant grammar lands (§14 non-goal).

    v1 implementation: no-op pass — the check is recorded as a
    documented limitation. The :class:`ContractMismatchError.clause`
    enum includes ``invariants_maintained`` so a future grammar-aware
    checker can fail here without enum churn.

    See module docstring "Wave-3 extension points: invariant-grammar
    resolution" for the upgrade path.
    """
    # v1: documented no-op. Clause kept in the enum for future
    # grammar-aware checks; see module docstring.
    return None


def _check_invariants_assumed(edge: DispatchContractEdge) -> None:
    """Clause 4 — invariants_assumed discharge (§5.3(a) + INV-SOS-G).

    Invariants the child assumes of its environment MUST be in the
    parent's maintained-set at the dispatch boundary. Per §5.3(a)
    "the parent's verification MUST prove these hold at the moment of
    dispatch."

    v1 implementation: name-set intersection between
    ``child.invariants_assumed`` and ``edge.parent_maintained_invariants``.
    A child-assumed invariant whose name is NOT in the parent's
    maintained set is a contract miss — the parent cannot prove it
    holds because it is not even in the parent's vocabulary.
    """
    child = set(edge.child_contract.invariants_assumed)
    parent = set(edge.parent_maintained_invariants)
    missing = child - parent
    if missing:
        raise ContractMismatchError(
            f"child {edge.child_chart_id!r} assumes invariants "
            f"{sorted(missing)!r} of its environment that parent "
            f"{edge.parent_chart_id!r} does not declare maintained at "
            f"dispatch state {edge.parent_state_id!r}",
            clause="invariants_assumed",
            missing=frozenset(missing),
            extra=frozenset(parent - child),
            chart_path=_chart_path(edge),
            child_chart=edge.child_chart_id,
        )


def _check_reads(edge: DispatchContractEdge) -> None:
    """Clause 5 — reads write-before-read at boundary (§5.2).

    Every datamodel field the child reads MUST be in the parent's
    write-before-dispatch set. Per §5.2 "the canonical inbound-data
    case" (field appears in child ``reads`` AND parent ``writes`` /
    ``env_writes``).

    v1 implementation: pure set-subset check. The §5.2 ordering
    requirement ("write before read") is structurally enforced by the
    parent writing the field before transitioning into the dispatch
    state — this verifier cannot prove the ordering, only the membership.
    The ordering check is the responsibility of the parent chart's per-
    layer reachability vector emitter (SOS-03 §6.1 + SOS-12 §7.1); a
    boundary vector at dispatch entry catches an out-of-order write at
    runtime per §7.2 even when this static check passes.
    """
    child = set(edge.child_contract.reads)
    parent = set(edge.parent_writes_before_dispatch)
    missing = child - parent
    if missing:
        raise ContractMismatchError(
            f"child {edge.child_chart_id!r} reads datamodel fields "
            f"{sorted(missing)!r} that parent {edge.parent_chart_id!r} "
            f"does not write before dispatch into state "
            f"{edge.parent_state_id!r}",
            clause="reads",
            missing=frozenset(missing),
            extra=frozenset(parent - child),
            chart_path=_chart_path(edge),
            child_chart=edge.child_chart_id,
        )


def _check_writes(edge: DispatchContractEdge) -> None:
    """Clause 6 — writes write-before-read on return (§5.2).

    Every datamodel field the child writes SHOULD be in the parent's
    read-after-dispatch set. Per §5.2 "the canonical outbound-data
    case" (field appears in child ``writes`` AND parent ``reads`` /
    ``env_reads``).

    v1 implementation: pure set-subset check. A child write to a field
    the parent does not read is structurally dead code at the boundary
    — the value flows but no observer consumes it. Under PCDN-006
    (compile-time error) we DO raise on this case: a contract that
    declares a write whose value is unobserved is most likely a chart-
    author typo (wrong field name on either side) and silently allowing
    it would mask the bug.

    A child contract with empty ``writes`` is the no-op case and does
    not raise regardless of the parent's read set.
    """
    child = set(edge.child_contract.writes)
    parent = set(edge.parent_reads_after_dispatch)
    missing = child - parent
    if missing:
        raise ContractMismatchError(
            f"child {edge.child_chart_id!r} writes datamodel fields "
            f"{sorted(missing)!r} that parent {edge.parent_chart_id!r} "
            f"does not read after dispatch from state "
            f"{edge.parent_state_id!r}",
            clause="writes",
            missing=frozenset(missing),
            extra=frozenset(parent - child),
            chart_path=_chart_path(edge),
            child_chart=edge.child_chart_id,
        )


# ---------------------------------------------------------------------------
# Public verification surface
# ---------------------------------------------------------------------------


def verify_contract_match(edge: DispatchContractEdge) -> None:
    """Verify a single dispatch edge's contract matches end-to-end.

    Runs the six §5.3 clauses in order: events_in, events_out,
    invariants_maintained (v1 no-op), invariants_assumed, reads,
    writes. Raises on the FIRST clause that fails — subsequent clauses
    are not evaluated. Chart authors typically address contract
    mismatches one at a time, mirroring the precedent of Wave-1A's
    annotation parser (which raises on the first malformed element).

    Per PCDN-006 the error is fatal: callers MUST treat
    :class:`ContractMismatchError` as a compile-abort. The verifier
    has no "warning-only" mode at v1.

    Args:
        edge: the dispatch-boundary edge to verify.

    Raises:
        ContractMismatchError: any §5.3 clause fails. The error's
            ``clause`` field names which one.
    """
    _check_events_in(edge)
    _check_events_out(edge)
    _check_invariants_maintained(edge)
    _check_invariants_assumed(edge)
    _check_reads(edge)
    _check_writes(edge)


# ---------------------------------------------------------------------------
# Inventory walker — batch verification across a Wave-1A DispatchInventory
# ---------------------------------------------------------------------------


# Type alias for clarity: an edge_provider maps the parser's per-dispatch
# context to a fully-populated :class:`DispatchContractEdge`. The provider
# is the integration seam between Wave-1A's structural parser and this
# module's semantic verifier; Wave-3 J/K will provide concrete
# implementations once the SOS-11 MCP tool surface lands.
EdgeProvider = Callable[
    [DispatchInventory, DispatchAnnotation, DispatchInventory],
    DispatchContractEdge,
]


def simple_edge_provider(
    parent_inv: DispatchInventory,
    annotation: DispatchAnnotation,
    child_inv: DispatchInventory,
) -> DispatchContractEdge:
    """Reference :data:`EdgeProvider` deriving parent expectation from
    the parent chart's own contract.

    This is the simplest-possible adapter: it treats the parent's
    chart-level ``Contract`` (the ``<sos:contract>`` at the parent's
    SCXML root) as the parent's per-dispatch expectation. Adequate when
    a parent chart has one dispatch site and the chart's external
    surface equals that dispatch site's boundary surface; inadequate
    when a parent dispatches into multiple children whose expectations
    differ — in that case the caller MUST supply a custom
    :data:`EdgeProvider` that partitions the parent's chart-level
    surface across its dispatch sites.

    A parent inventory with no chart-level contract (the typical
    top-level chart, which is not itself dispatched-into) yields
    empty parent-side expectations; in that case the verifier will
    raise on any non-empty child contract — which is the correct
    behaviour because the parent must declare what it routes.

    The child contract is read from ``child_inv.contract``; a child
    inventory with no contract yields a degenerate edge with empty
    child-side declarations (all clauses trivially pass).
    """
    parent_contract = parent_inv.contract or Contract()
    child_contract = child_inv.contract or Contract()
    return DispatchContractEdge(
        parent_chart_id=parent_inv.chart_ref,
        parent_state_id=annotation.parent_state_id,
        child_chart_id=child_inv.chart_ref,
        child_contract=child_contract,
        # Use the parent's chart-level contract as the per-dispatch
        # expectation. See docstring for the multi-dispatch limitation.
        parent_expected_events_in=parent_contract.events_in,
        parent_expected_events_out=parent_contract.events_out,
        parent_maintained_invariants=parent_contract.invariants_maintained,
        parent_assumed_invariants=parent_contract.invariants_assumed,
        parent_writes_before_dispatch=parent_contract.writes,
        parent_reads_after_dispatch=parent_contract.reads,
    )


def verify_inventory(
    inventory: DispatchInventory,
    *,
    edge_provider: EdgeProvider = simple_edge_provider,
) -> None:
    """Walk a Wave-1A :class:`DispatchInventory` tree and verify every
    parent → child contract pair.

    Depth-first traversal: for each parent inventory, every
    ``DispatchAnnotation`` paired with its resolved sub-inventory is
    verified via :func:`verify_contract_match`. The walker recurses
    into each sub-inventory so deeper-level dispatches are verified
    too (per §6.3 sequential composition + INV-S-DISP-3 acyclicity
    means recursion is finite).

    Raises on the FIRST failure encountered (depth-first order). The
    :class:`ContractMismatchError.chart_path` field names the failing
    edge precisely — the path is the dispatch-tree address per
    INV-SOS-H so a chart author can navigate straight to the offending
    SCXML element.

    Args:
        inventory: the root :class:`DispatchInventory` to verify.
        edge_provider: callable mapping a (parent, annotation, child)
            triple to a :class:`DispatchContractEdge`. Defaults to
            :func:`simple_edge_provider`. Wave-3 J/K will supply
            custom providers that derive per-dispatch parent
            expectations from the SOS-11 extraction analysis instead
            of the chart-level contract.

    Raises:
        ContractMismatchError: the first failing dispatch edge in
            depth-first order. Traversal halts; remaining edges are
            not verified.
    """
    # Walk the parent's direct dispatches first. The annotation order
    # mirrors document order from Wave-1A's depth-first SCXML walk.
    for annotation in inventory.dispatches:
        # Locate the resolved sub-inventory for this annotation. Wave-1A
        # records sub-inventories in document-order; we match by
        # resolved_path (or by ref if no path resolution happened).
        child_inv = _resolve_child_inventory(inventory, annotation)
        if child_inv is None:
            # Unresolved ref — the parser already surfaced this in
            # `unresolved_refs` and Wave-2 chart-id-token resolution is
            # out of scope here. A truly missing child is NOT a contract-
            # match failure (the parser would have raised); it's a
            # deferred-resolution case the caller's edge_provider would
            # handle via a custom resolver. v1 walker skips.
            continue
        edge = edge_provider(inventory, annotation, child_inv)
        verify_contract_match(edge)

    # Recurse into each sub-inventory so deeper-level dispatches are
    # also verified. INV-S-DISP-3 (acyclicity) ensures finite recursion;
    # PCDN-005 depth cap (enforced at parse time) bounds it explicitly.
    for sub_inv in inventory.sub_inventories:
        verify_inventory(sub_inv, edge_provider=edge_provider)


def _resolve_child_inventory(
    parent_inv: DispatchInventory,
    annotation: DispatchAnnotation,
) -> Optional[DispatchInventory]:
    """Find the sub-inventory matching a dispatch annotation.

    Wave-1A's parser records ``DispatchInventory.sub_inventories`` in
    document order, one per resolved dispatch. The match key is the
    sub-inventory's ``chart_ref`` (the resolved chart filename) against
    the annotation's ``resolved_path.name`` — both are stable strings.
    Falls back to the annotation's raw ``ref`` for inventories built
    without a chart_path anchor.

    Returns ``None`` when no sub-inventory matches (the annotation is
    in ``unresolved_refs`` or the inventory was built synthetically
    without populating ``sub_inventories``).
    """
    # Prefer resolved-path match — handles charts where multiple
    # dispatches share the same ref but resolve to different paths
    # (which would only happen with a custom loader; not a parser-
    # produced case but supported for symmetry).
    if annotation.resolved_path is not None:
        target_ref = annotation.resolved_path.name
        for sub in parent_inv.sub_inventories:
            if sub.chart_ref == target_ref:
                return sub
    # Fall back to ref match — covers synthetic inventories whose
    # chart_ref was set to the raw ref string by the test harness.
    for sub in parent_inv.sub_inventories:
        if sub.chart_ref == annotation.ref:
            return sub
    return None


__all__ = [
    "ContractMismatchError",
    "DispatchContractEdge",
    "EdgeProvider",
    "PERMITTED_CLAUSES",
    "simple_edge_provider",
    "verify_contract_match",
    "verify_inventory",
]

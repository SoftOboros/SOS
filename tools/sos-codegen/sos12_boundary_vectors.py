"""SOS-12 boundary-vector emitter — dispatch-boundary contract verification.

Authority: ``docs/concepts/SOS-12-CONCEPTS.md`` §7.2 (boundary-vector
emission, normative) + §7.1 (per-sub-chart vector emission, informative
context). Cross-phase invariant `INV-SOS-B` (vectors-as-deliverable-at-
every-layer) from ``docs/concepts/SOS-07-CONCEPTS.md`` §6 governs the
deliverable; `INV-SOS-H` (vector-to-chart traceability) governs the
metadata each emitted vector carries.

Per §7.2 a parent chart that dispatches into a sub-chart emits, **at
the dispatch boundary**, a constant-size vector set that tests the
parent ↔ child contract end:

  1. For each ``events_in`` declared in the child's contract — a vector
     drives that event from the parent at the dispatch instant and
     asserts the child enters its initial state cleanly.

  2. For each ``events_out`` declared in the child's contract — a
     vector runs the child until it produces that event and asserts the
     parent receives it (return path).

  3. For each ``invariants`` declared in the contract — a vector that
     the parent + child round-trip preserves the invariant.

Boundary vectors are **constant-size** (do not depend on the sub-chart's
internal state count). This is the operational realisation of
``INV-SOS-F`` (per-layer × independence-axes, NOT Cartesian) at the
vector-emission surface — declared as ``INV-S-DISP-5`` in SOS-12 §10.1.

Per ``INV-SOS-H`` each emitted vector carries::

    {
      "chart_path":          "<parent>.<dispatch_state>.<child_chart_id>",
      "trigger":             <event-name-or-tick>,
      "expected":            <state-id-or-event-name>,
      "originating_invariant": <invariant-id-if-applicable>,
    }

The chart_path is the dispatch-tree address the vector probes; the
trigger/expected/invariant trio renders in chart vocabulary per the
``INV-S-DISP-1`` (no replay across layers) shape — a boundary vector
NEVER enumerates the sub-chart's internal states.

Output is per-vector JSON, shape-compatible with the SOS-03 vector
fixture schema (``docs/concepts/SOS-03-CONCEPTS.md`` §6.2). The JSONL
emission framework (§5 / §6 of SOS-03) is the wire-shape consumer.

PCDN-SOS-12-006 resolution (compile-time error): contract-mismatched
inputs are rejected with :class:`BoundaryVectorError` referencing
PCDN-006. The emitter refuses to ship a vector when the parent's
expected events-in / events-out do not cover the child's declared
contract — defeating the verified-codegen story at the dispatch edge
would defeat INV-SOS-G.

Wave-2 integration boundary
---------------------------

This module deliberately does NOT import from sibling-worktree modules
(``sos12_annotations``, ``sos12_bound``). Instead it defines minimal
local input dataclasses (:class:`SubChartContract`, :class:`DispatchEdge`)
that mirror the §5.1 four-tuple contract shape. Wave-2 will:

  - Replace these local inputs with the ratified ``sos12_annotations``
    annotation walker outputs.
  - Wire :func:`emit_boundary_vectors` into the chart-family JSONL
    emission framework so per-sub-chart vector files (§7.1) and
    boundary vector files (§7.2) share an emit driver.

Until then the function surface is stable on the local input shape; the
Wave-2 swap is a constructor-level adapter, not a vector-shape change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Local input shapes — Wave-2 will replace with sos12_annotations outputs.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DatamodelBoundary:
    """Four-set datamodel boundary per SOS-12 §5.2.

    Per the §5.2 four-set algebra:

      - ``reads``      — fields the sub-chart consumes from parent datamodel
      - ``writes``     — fields the sub-chart writes back to parent datamodel
      - ``env_reads``  — fields the environment (parent) consumes (sub-chart writes)
      - ``env_writes`` — fields the environment (parent) writes (sub-chart reads)

    A field MAY appear in both ``reads`` and ``writes`` only if it does
    NOT appear in ``env_writes`` / ``env_reads`` (else it is a
    concurrent-access pattern requiring an SCXML ``<parallel>`` sync
    primitive, deferred to SOS-12 v2 per §5.2).
    """

    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    env_reads: tuple[str, ...] = ()
    env_writes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SubChartContract:
    """Sub-chart contract four-tuple per SOS-12 §5.1.

    The contract is what the parent verifies against, and what the
    sub-chart's environment is assumed to satisfy. Contract shape is
    Standards Action via SOS-12 §10 — the four field names + four
    sub-field names of ``invariants`` and ``datamodel_boundary`` are
    frozen.

    ``initial_state`` is the child's named root-initial state — the
    state the boundary vector asserts the child enters cleanly on a
    valid events-in stimulus. Per §7.2, the boundary vector references
    the contract-declared initial state (NOT any internal state); this
    keeps the vector at the dispatch edge per INV-S-DISP-1.
    """

    chart_id: str
    initial_state: str
    events_in: tuple[str, ...] = ()
    events_out: tuple[str, ...] = ()
    invariants_maintained: tuple[str, ...] = ()
    invariants_assumed: tuple[str, ...] = ()
    datamodel_boundary: DatamodelBoundary = field(default_factory=DatamodelBoundary)


@dataclass(frozen=True)
class DispatchEdge:
    """One parent → child dispatch edge in a dispatch-tree (§3 glossary).

    The parent chart names a dispatched state; that state's
    instantiation routes events-in / events-out per the child's
    declared contract (§5.3). One :class:`DispatchEdge` describes one
    such instantiation point; a parent dispatching into N sub-charts
    yields N edges.

    ``parent_expected_events_in`` / ``parent_expected_events_out`` are
    the parent's declared expectations — the routing table the parent
    side promises. Contract-matching (§5.3) compares these against the
    child's :class:`SubChartContract`; mismatch is a compile-time error
    per PCDN-SOS-12-006.
    """

    parent_chart_id: str
    dispatch_state: str
    child_contract: SubChartContract
    parent_expected_events_in: tuple[str, ...] = ()
    parent_expected_events_out: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BoundaryVectorError(Exception):
    """Raised when boundary-vector emission cannot proceed.

    The dispatch-edge contract is the load-bearing artifact at the
    boundary; an emission that violates it is rejected before any
    vector ships, per PCDN-SOS-12-006 (compile-time error) and
    INV-S-DISP-2 (contract-matching is mandatory).
    """

    def __init__(
        self,
        message: str,
        *,
        pcdn: Optional[str] = None,
        invariant: Optional[str] = None,
        parent_chart_id: Optional[str] = None,
        child_chart_id: Optional[str] = None,
    ) -> None:
        self.pcdn = pcdn
        self.invariant = invariant
        self.parent_chart_id = parent_chart_id
        self.child_chart_id = child_chart_id
        prefix_parts: list[str] = []
        if pcdn:
            prefix_parts.append(f"[{pcdn}]")
        if invariant:
            prefix_parts.append(f"[{invariant}]")
        if parent_chart_id and child_chart_id:
            prefix_parts.append(
                f"edge={parent_chart_id!r}->{child_chart_id!r}"
            )
        elif parent_chart_id:
            prefix_parts.append(f"parent={parent_chart_id!r}")
        elif child_chart_id:
            prefix_parts.append(f"child={child_chart_id!r}")
        prefix = " ".join(prefix_parts)
        super().__init__(f"{prefix}: {message}" if prefix else message)


# ---------------------------------------------------------------------------
# Contract-matching — PCDN-SOS-12-006 (compile-time error)
# ---------------------------------------------------------------------------


def _check_contract_match(edge: DispatchEdge) -> None:
    """Verify the parent's declared routing covers the child's contract.

    Per §5.3 contract-match check:

      - Every event the child declares as events-in MUST appear in the
        parent's declared events-in (otherwise the parent cannot route
        the event into the dispatched state).
      - Every event the child declares as events-out MUST appear in the
        parent's declared events-out (otherwise the parent cannot
        observe the event when the child raises it).

    Failure mode per PCDN-SOS-12-006: compile-time error. The chart
    family fails to emit if any contract is unmatched. Lint warning
    (option b in the draft) and runtime check (option c) are NOT
    available paths in v1; this matches the §15 ratification entry
    that selected option (a).

    Raises:
        BoundaryVectorError: any required event is missing from the
            parent's declared routing. Error message cites PCDN-006
            and names the missing event.
    """
    contract = edge.child_contract
    parent_in = set(edge.parent_expected_events_in)
    parent_out = set(edge.parent_expected_events_out)

    missing_in = [e for e in contract.events_in if e not in parent_in]
    if missing_in:
        raise BoundaryVectorError(
            f"parent does not route required events-in {missing_in!r} into "
            f"dispatched state {edge.dispatch_state!r}; child contract is "
            f"unmatched (PCDN-SOS-12-006: compile-time error)",
            pcdn="PCDN-SOS-12-006",
            invariant="INV-S-DISP-2",
            parent_chart_id=edge.parent_chart_id,
            child_chart_id=contract.chart_id,
        )
    missing_out = [e for e in contract.events_out if e not in parent_out]
    if missing_out:
        raise BoundaryVectorError(
            f"parent does not observe required events-out {missing_out!r} from "
            f"dispatched state {edge.dispatch_state!r}; child contract is "
            f"unmatched (PCDN-SOS-12-006: compile-time error)",
            pcdn="PCDN-SOS-12-006",
            invariant="INV-S-DISP-2",
            parent_chart_id=edge.parent_chart_id,
            child_chart_id=contract.chart_id,
        )


# ---------------------------------------------------------------------------
# Vector-id formatter — §7.2 traceability surface
# ---------------------------------------------------------------------------


def _vector_id(parent_id: str, child_id: str, seq: int) -> str:
    """Return ``sos12-boundary-<parent_id>-<child_id>-<NNNN>``.

    The shape mirrors SOS-09-F's ``MV-<UUID>-<family>-<seq>`` (vectors/
    base.py §5.3) — a stable, chart-vocabulary key the harness uses
    when reporting per-vector pass/fail. Per INV-SOS-H every diagnostic
    names the chart path that produced it; the vector-id is the index
    surface.
    """
    if seq < 0:
        raise BoundaryVectorError(
            f"vector-id seq MUST be non-negative; got {seq!r}",
            invariant="§7.2",
        )
    return f"sos12-boundary-{parent_id}-{child_id}-{seq:04d}"


def _chart_path(edge: DispatchEdge) -> str:
    """Return the INV-SOS-H chart_path for a dispatch edge.

    Shape: ``<parent_chart_id>.<dispatch_state>.<child_chart_id>``.
    Per §7.1 / INV-SOS-H every emitted vector carries this path in
    metadata; the path is the dispatch-tree address (§3 glossary) at
    the boundary the vector probes.
    """
    return (
        f"{edge.parent_chart_id}.{edge.dispatch_state}."
        f"{edge.child_contract.chart_id}"
    )


# ---------------------------------------------------------------------------
# Per-category vector emitters — events-in / events-out / invariants
# ---------------------------------------------------------------------------


def _events_in_vectors(
    edge: DispatchEdge, *, start_seq: int = 0
) -> list[dict[str, Any]]:
    """Emit one boundary vector per declared events-in member.

    Per §7.2 first clause: for each events-in member, drive that event
    from the parent at the dispatch instant; assert the child enters
    its declared initial state cleanly. The expected behaviour
    references the contract-declared ``initial_state`` ONLY — never
    any sub-chart-internal state (INV-S-DISP-1: no replay across
    layers).
    """
    contract = edge.child_contract
    chart_path = _chart_path(edge)
    out: list[dict[str, Any]] = []
    for offset, ev in enumerate(contract.events_in):
        seq = start_seq + offset
        out.append(
            {
                "vector_id": _vector_id(
                    edge.parent_chart_id, contract.chart_id, seq
                ),
                "category": "Boundary",
                "origin": "Authored",
                "kind": "events_in",
                "description": (
                    f"SOS-12 §7.2 boundary vector: parent {edge.parent_chart_id!r} "
                    f"dispatches into {contract.chart_id!r} via state "
                    f"{edge.dispatch_state!r}; drives events-in event {ev!r}; "
                    f"asserts child enters initial state {contract.initial_state!r}."
                ),
                "tags": [
                    "sos12",
                    "boundary",
                    "events_in",
                    edge.parent_chart_id,
                    contract.chart_id,
                ],
                "metadata": {
                    "chart_path": chart_path,
                    "trigger": ev,
                    "expected": contract.initial_state,
                    "originating_invariant": None,
                },
            }
        )
    return out


def _events_out_vectors(
    edge: DispatchEdge, *, start_seq: int = 0
) -> list[dict[str, Any]]:
    """Emit one boundary vector per declared events-out member.

    Per §7.2 second clause: for each events-out member, run the child
    until it produces the event; assert the parent receives it on the
    return path. The expected value is the event name itself — the
    parent's observability surface at the boundary is the event, not
    any internal-state probe (INV-S-DISP-1).
    """
    contract = edge.child_contract
    chart_path = _chart_path(edge)
    out: list[dict[str, Any]] = []
    for offset, ev in enumerate(contract.events_out):
        seq = start_seq + offset
        out.append(
            {
                "vector_id": _vector_id(
                    edge.parent_chart_id, contract.chart_id, seq
                ),
                "category": "Boundary",
                "origin": "Authored",
                "kind": "events_out",
                "description": (
                    f"SOS-12 §7.2 boundary vector: child {contract.chart_id!r} "
                    f"under parent {edge.parent_chart_id!r} dispatch raises "
                    f"events-out event {ev!r}; asserts parent observes the "
                    f"event at dispatch state {edge.dispatch_state!r}."
                ),
                "tags": [
                    "sos12",
                    "boundary",
                    "events_out",
                    edge.parent_chart_id,
                    contract.chart_id,
                ],
                "metadata": {
                    "chart_path": chart_path,
                    "trigger": "child.run_to_event",
                    "expected": ev,
                    "originating_invariant": None,
                },
            }
        )
    return out


def _invariant_vectors(
    edge: DispatchEdge, *, start_seq: int = 0
) -> list[dict[str, Any]]:
    """Emit one boundary vector per declared invariant.

    Per §7.2 third clause: for each invariant declared in the
    contract, emit a vector that the parent + child round-trip
    preserves the invariant. ``invariants_maintained`` are the
    sub-chart's own assertions (it MUST preserve them across dispatch);
    ``invariants_assumed`` are the parent's obligations at the
    dispatch boundary (the parent MUST establish them before
    dispatch). Both flavours yield a boundary vector — each names its
    originating-invariant id in metadata per INV-SOS-H.
    """
    contract = edge.child_contract
    chart_path = _chart_path(edge)
    out: list[dict[str, Any]] = []
    cursor = start_seq
    for inv_id in contract.invariants_maintained:
        out.append(
            {
                "vector_id": _vector_id(
                    edge.parent_chart_id, contract.chart_id, cursor
                ),
                "category": "Boundary",
                "origin": "Authored",
                "kind": "invariant_maintained",
                "description": (
                    f"SOS-12 §7.2 boundary vector: child {contract.chart_id!r} "
                    f"maintains invariant {inv_id!r} across dispatch from "
                    f"parent {edge.parent_chart_id!r}; asserts round-trip "
                    f"preserves the invariant."
                ),
                "tags": [
                    "sos12",
                    "boundary",
                    "invariant",
                    "maintained",
                    edge.parent_chart_id,
                    contract.chart_id,
                ],
                "metadata": {
                    "chart_path": chart_path,
                    "trigger": "dispatch.round_trip",
                    "expected": "invariant_holds",
                    "originating_invariant": inv_id,
                },
            }
        )
        cursor += 1
    for inv_id in contract.invariants_assumed:
        out.append(
            {
                "vector_id": _vector_id(
                    edge.parent_chart_id, contract.chart_id, cursor
                ),
                "category": "Boundary",
                "origin": "Authored",
                "kind": "invariant_assumed",
                "description": (
                    f"SOS-12 §7.2 boundary vector: parent {edge.parent_chart_id!r} "
                    f"discharges environmental invariant {inv_id!r} at the "
                    f"dispatch boundary into {contract.chart_id!r}; asserts "
                    f"the invariant holds at dispatch instant."
                ),
                "tags": [
                    "sos12",
                    "boundary",
                    "invariant",
                    "assumed",
                    edge.parent_chart_id,
                    contract.chart_id,
                ],
                "metadata": {
                    "chart_path": chart_path,
                    "trigger": "dispatch.entry",
                    "expected": "invariant_holds",
                    "originating_invariant": inv_id,
                },
            }
        )
        cursor += 1
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def emit_boundary_vectors(
    edge: DispatchEdge,
) -> list[dict[str, Any]]:
    """Emit the constant-size boundary vector set for one dispatch edge.

    The vector set per §7.2 has exactly
    ``|events_in| + |events_out| + |invariants_maintained| + |invariants_assumed|``
    members. Empty contracts yield empty lists; the empty case is
    permitted (it is the degenerate dispatch — a parent that dispatches
    into a contract-free sub-chart still has a dispatch edge, just no
    boundary obligations beyond the contract-match check itself).

    Vectors are emitted in three blocks: events-in, then events-out,
    then invariants (maintained, then assumed). Sequential ids are
    monotonically increasing within the edge — vectors are stable
    across re-emissions so the harness's per-vector pass/fail history
    stays attached.

    Args:
        edge: the parent → child dispatch edge to emit vectors for.

    Returns:
        Ordered list of vector record dicts. Each carries the
        INV-SOS-H ``metadata`` block (chart_path / trigger / expected
        / originating_invariant). Empty list if the contract declares
        zero obligations across all three categories.

    Raises:
        BoundaryVectorError: contract-match check fails per
            PCDN-SOS-12-006 (compile-time error). Any declared
            events-in or events-out the parent's routing does not
            cover is a fatal emission error.
    """
    _check_contract_match(edge)

    out: list[dict[str, Any]] = []
    cursor = 0
    in_vecs = _events_in_vectors(edge, start_seq=cursor)
    out.extend(in_vecs)
    cursor += len(in_vecs)
    out_vecs = _events_out_vectors(edge, start_seq=cursor)
    out.extend(out_vecs)
    cursor += len(out_vecs)
    inv_vecs = _invariant_vectors(edge, start_seq=cursor)
    out.extend(inv_vecs)
    return out


def emit_dispatch_tree_boundary_vectors(
    edges: Iterable[DispatchEdge],
) -> list[dict[str, Any]]:
    """Emit boundary vectors for every edge in a dispatch-tree.

    Per §7.2 boundary-vector emission is per-edge; for a tree of N
    edges the family-level boundary vector count is the sum of the
    per-edge counts — this is the sum-not-product property INV-SOS-F
    promises (§6.3) realised at the vector-emission surface. The
    aggregate count is constant in the sub-charts' internal state
    counts; it depends only on each contract's declared surface.

    Args:
        edges: iterable of :class:`DispatchEdge`. Order is preserved
            in the output (caller-supplied iteration order).

    Returns:
        Concatenated vector list across all edges. Each vector retains
        its per-edge chart_path so a downstream consumer can group by
        edge if it wishes.

    Raises:
        BoundaryVectorError: any single edge fails contract-match;
            emission is halted at the first failure per PCDN-006.
    """
    out: list[dict[str, Any]] = []
    for edge in edges:
        out.extend(emit_boundary_vectors(edge))
    return out


def write_boundary_vectors_jsonl(
    edge: DispatchEdge,
    out_path: Path | str,
) -> Path:
    """Write a dispatch edge's boundary vectors as JSONL.

    Per SOS-03 §6 the vector wire format is JSON / JSONL (boundary
    vectors are emitted one-per-line into a ``.jsonl`` file matching
    the SOS-03 boundary-vector subtype ratified at the §15 amendment
    SOS-12 §12 promises). Each line is exactly one vector record;
    ``json.dumps`` is invoked with ``sort_keys=False`` to preserve the
    insertion order documented above (vector_id first → metadata last).

    Returns:
        The absolute path written.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    vectors = emit_boundary_vectors(edge)
    with out_path.open("w", encoding="utf-8") as fh:
        for vec in vectors:
            fh.write(json.dumps(vec, ensure_ascii=False))
            fh.write("\n")
    return out_path.resolve()


__all__ = [
    "BoundaryVectorError",
    "DatamodelBoundary",
    "DispatchEdge",
    "SubChartContract",
    "emit_boundary_vectors",
    "emit_dispatch_tree_boundary_vectors",
    "write_boundary_vectors_jsonl",
]

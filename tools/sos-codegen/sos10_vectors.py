"""SOS-10E1 cross-piece bound-reachability vector emitter.

Authority: ``docs/concepts/SOS-10-CONCEPTS.md`` §12(d) (acceptance gate:
"Cross-piece bounded-reachability vectors + INV-SOS-H broken-protocol
render"), §7/§8 (per-medium emission shape), §5.2 (frozen 4-value medium
enum, Standards Action), and INV-S-ORCH-6 (vector-to-chart traceability
across pieces). Cross-phase invariant: INV-SOS-B (vectors-as-deliverable)
and INV-SOS-H (chart-vocabulary failure rendering).

Input contract is owned by SOS-10-ANNOT (``sos10_annotations.py``); this
module is a *consumer* of that contract and MUST NOT redefine its types
or value grammars (per the source-of-truth doctrine, parent CLAUDE.md
"Definitions — reference vs. restatement").

What this module emits
----------------------

A ``list[CrossPieceVectorRecord]`` per orchestrator chart. Each record is
the joint-protocol bounded-reachability vector for one cross-piece
contract: a single (sender, medium, event, receiver) tuple plus the
vector category (transition / timeout / idempotent_retry /
broken_protocol / multi_hop). Records are intended to be serialised to
JSON for downstream cocotb-equivalent harness consumption per
PCDN-SOS-10-008 ("docker compose + per-piece test scripts + a top-level
Python coordinator").

Vector families (§12(d) acceptance + §7 cross-piece invariants):

1. **transition** — one vector per cross-piece transition in the
   orchestrator chart. Exercises the sender-piece → medium → receiver-
   piece round trip end-to-end. ``expected_outcome="success"``.
2. **timeout** — one vector per medium kind exercised by the chart
   (≤ 4 vectors). Uses the per-medium default from PCDN-SOS-10-006
   unless overridden by a ``<sos:timeout>`` annotation on the
   transition. ``expected_outcome="timeout"``.
3. **idempotent_retry** — one vector per ``<sos:idempotent value="true"/>``
   annotation (medium-level or transition-level per PCDN-SOS-10-005).
   Exercises retry-collapse: two emissions ⇒ one observable effect.
   ``expected_outcome="retry_collapsed"``.
4. **broken_protocol** — emitted whenever a vector represents a
   contract-mismatch (see ``BrokenProtocolReason`` enum for the named
   failure shapes). Per INV-SOS-H, the failure message renders in chart
   vocabulary (sender piece id, receiver piece id, event name, medium
   kind), NOT in raw medium primitives (no protobuf field numbers, no
   ring-buffer offsets, no NVIC vector numbers).
5. **multi_hop** — for any cross-piece chain A→B→C inferable from the
   orchestrator's transition graph (B is the target of an A-sourced
   transition AND the source of a separate transition into C). One
   vector per discovered chain. ``expected_outcome="success"``.

INV-SOS-H metadata
------------------

Every emitted record carries the §12(d)-mandated metadata block:

    {
        "orchestrator_chart": <chart sos:id UUID or "<unidentified>">,
        "transition_id": <vector trace key — V-<ord>-<family> per §7>,
        "sender_piece": <piece state id>,
        "receiver_piece": <piece state id>,
        "medium": <medium kind from §5.2 frozen enum>,
        "expected_outcome": <one of {success, timeout, retry_collapsed,
                                     broken_protocol}>,
    }

Multi-hop records additionally carry a ``hops`` list naming each
intermediate piece + medium pair in chart vocabulary.

Public surface
--------------

    CrossPieceVectorRecord         — frozen dataclass per §12(d).
    BrokenProtocolReason           — frozen enum (Standards Action).
    VectorFamily                   — frozen 5-value enum (Standards
                                     Action; §15 amendment required to
                                     add a sixth family).
    PER_MEDIUM_TIMEOUT_MS          — PCDN-SOS-10-006 default table.
    emit_cross_piece_vectors(orch) — pure entry point.
    Sos10VectorEmissionError       — emitter-side error (subclasses
                                     ValueError, mirrors the
                                     ``Sos10AnnotationError`` shape from
                                     the parser side).

Strict one-orchestrator-per-system (PCDN-SOS-10-007) is enforced at the
caller boundary: the input MUST be exactly one
``OrchestratorAnnotations`` instance produced by
``parse_orchestrator_annotations``. Multi-orchestrator composition is
explicitly out of v1 scope; callers passing chart data that violates
INV-S-ORCH-1 receive a clear ``Sos10VectorEmissionError``.

@spec citations on every emitted record
---------------------------------------

Each record's ``spec_refs`` field carries a tuple of citation strings:

- ``SOS-10-CONCEPTS §12(d)`` — acceptance gate.
- ``INV-S-ORCH-6`` — vector-to-chart traceability across pieces.
- ``INV-SOS-B`` — vectors-as-deliverable (the cross-phase invariant the
  whole vector-emission concept rides on).
- ``INV-SOS-H`` — chart-vocabulary failure rendering.
- ``PCDN-SOS-10-005`` — idempotency annotation (idempotent_retry
  vectors only).
- ``PCDN-SOS-10-006`` — per-medium timeout defaults (timeout vectors
  only).
- ``PCDN-SOS-10-007`` — strict one-orchestrator-per-system
  (broken_protocol vectors only).

This mirrors the ``@spec`` discipline established in SOS-10 wave-16 /
wave-17 (every emitted artifact cites the §6.x medium contract + the
relevant INV-S-ORCH-N invariants + INV-SOS-A).
"""

from __future__ import annotations

import enum
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Self-relative import — this module lives at tools/sos-codegen/.
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos10_annotations import (  # noqa: E402
    ALLOWED_MEDIUM_KINDS,
    CrossPieceTransitionAnnotation,
    MediumAnnotation,
    OrchestratorAnnotations,
    PieceAnnotation,
)


# ---------------------------------------------------------------------------
# Frozen enums — Standards Action registration policy.
# ---------------------------------------------------------------------------


class VectorFamily(str, enum.Enum):
    """The §12(d) cross-piece vector family taxonomy.

    Standards Action: adding a sixth family changes which vectors the
    emitter ships and requires a §15 amendment to SOS-10-CONCEPTS.md.
    """

    TRANSITION = "transition"
    TIMEOUT = "timeout"
    IDEMPOTENT_RETRY = "idempotent_retry"
    BROKEN_PROTOCOL = "broken_protocol"
    MULTI_HOP = "multi_hop"


class BrokenProtocolReason(str, enum.Enum):
    """Named contract-mismatch shapes per INV-SOS-H rendering vocabulary.

    Standards Action. These names appear in the chart-vocabulary failure
    messages the cocotb-equivalent harness surfaces to the operator;
    adding a new reason changes the operator-facing UX and requires a
    §15 amendment.
    """

    # Sender emits an event whose name the receiver-piece doesn't declare
    # as an event-in on any of its transitions. The canonical §12(d)
    # "deliberate broken-protocol case".
    UNDECLARED_EVENT = "undeclared_event"
    # Receiver-piece references a medium-incompatible payload assumption
    # (e.g. expects an in-process function-pointer dispatch but the
    # orchestrator declared mmio). Reserved for the integration harness.
    MEDIUM_MISMATCH = "medium_mismatch"
    # Sender claims idempotent semantics on a medium that does not
    # provide them (e.g. fire-and-forget shared-memory writes with no
    # consumer acknowledgement). Reserved for the integration harness.
    IDEMPOTENCY_VIOLATED = "idempotency_violated"


# PCDN-SOS-10-006 ratified table. The values mirror §15's "ratified
# after PCDN walkthrough" entry exactly; changes require §15 amendment.
PER_MEDIUM_TIMEOUT_MS: dict[str, Optional[int]] = {
    "in-process": None,        # no timeout — synchronous dispatch
    "shared-memory": None,     # no timeout — caller-driven wait
    "mmio": None,              # no timeout — IRQ-driven
    # Network timeouts depend on transport; the per-transport default
    # lives in ``PER_TRANSPORT_TIMEOUT_MS``. The "network" entry here is
    # a sentinel meaning "look up by transport name".
    "network": None,
}

PER_TRANSPORT_TIMEOUT_MS: dict[str, int] = {
    "gRPC": 5000,
    "AMQP": 10000,
}


# Outcome tokens — Standards Action.
class ExpectedOutcome(str, enum.Enum):
    """Outcome a vector asserts at the cocotb-equivalent harness boundary."""

    SUCCESS = "success"
    TIMEOUT = "timeout"
    RETRY_COLLAPSED = "retry_collapsed"
    BROKEN_PROTOCOL = "broken_protocol"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class Sos10VectorEmissionError(ValueError):
    """Raised when cross-piece vector emission cannot proceed.

    Mirrors the ``Sos10AnnotationError`` shape (parser side) for symmetry
    in downstream error-reporting tooling.
    """

    def __init__(
        self,
        message: str,
        *,
        chart_id: Optional[str] = None,
        rule: Optional[str] = None,
    ) -> None:
        self.chart_id = chart_id
        self.rule = rule
        prefix_parts: list[str] = []
        if rule:
            prefix_parts.append(f"[{rule}]")
        if chart_id:
            prefix_parts.append(f"chart={chart_id!r}")
        prefix = " ".join(prefix_parts)
        super().__init__(f"{prefix}: {message}" if prefix else message)


# ---------------------------------------------------------------------------
# VectorRecord dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossPieceVectorRecord:
    """One bounded-reachability vector for a cross-piece contract.

    Per §12(d) every record carries the INV-SOS-H metadata block plus the
    family-specific extras. Frozen-dataclass shape keeps the emitter
    deterministic — same orchestrator annotations + same iteration order
    produce bit-identical record lists across replays.

    The ``failure_message`` field is populated only for
    ``family=broken_protocol`` records; it renders in chart vocabulary
    per INV-SOS-H (sender piece id, receiver piece id, event name,
    medium kind), never in raw medium primitives.
    """

    family: VectorFamily
    orchestrator_chart: str
    transition_id: str
    sender_piece: str
    receiver_piece: str
    medium: str
    expected_outcome: ExpectedOutcome
    event: str
    spec_refs: tuple[str, ...]
    # Optional/family-specific:
    transport: Optional[str] = None
    timeout_ms: Optional[int] = None
    idempotent: Optional[bool] = None
    broken_protocol_reason: Optional[BrokenProtocolReason] = None
    failure_message: Optional[str] = None
    hops: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        """Serialise to the §12(d) INV-SOS-H metadata block + family extras.

        Suitable for JSON serialisation; consumers (cocotb-equivalent
        harness per PCDN-SOS-10-008) read this back as the joint-
        protocol vector descriptor.
        """
        out: dict = {
            "family": self.family.value,
            "orchestrator_chart": self.orchestrator_chart,
            "transition_id": self.transition_id,
            "sender_piece": self.sender_piece,
            "receiver_piece": self.receiver_piece,
            "medium": self.medium,
            "expected_outcome": self.expected_outcome.value,
            "event": self.event,
            "spec_refs": list(self.spec_refs),
        }
        if self.transport is not None:
            out["transport"] = self.transport
        if self.timeout_ms is not None:
            out["timeout_ms"] = self.timeout_ms
        if self.idempotent is not None:
            out["idempotent"] = self.idempotent
        if self.broken_protocol_reason is not None:
            out["broken_protocol_reason"] = self.broken_protocol_reason.value
            out["failure_message"] = self.failure_message
        if self.hops:
            out["hops"] = [dict(h) for h in self.hops]
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SPEC_REFS_BASE: tuple[str, ...] = (
    "SOS-10-CONCEPTS §12(d)",
    "INV-S-ORCH-6",
    "INV-SOS-B",
    "INV-SOS-H",
)


def _resolved_idempotency(
    tr: CrossPieceTransitionAnnotation,
) -> Optional[bool]:
    """Per-transition idempotent attribute wins over medium-level (§5.4)."""
    if tr.idempotent is not None:
        return tr.idempotent
    return tr.medium.idempotent


def _resolve_timeout_ms(
    medium: MediumAnnotation,
) -> Optional[int]:
    """Resolve the timeout per PCDN-SOS-10-006 precedence.

    Precedence (lowest → highest priority):
      1. Per-medium default from ``PER_MEDIUM_TIMEOUT_MS``.
      2. For ``kind="network"``: per-transport default from
         ``PER_TRANSPORT_TIMEOUT_MS``.
      3. Transport-level ``timeout-ms`` attribute.
      4. Medium-level ``<sos:timeout ms="..."/>`` sub-element.
    """
    # Start with the per-medium default.
    timeout = PER_MEDIUM_TIMEOUT_MS.get(medium.kind)

    # Network: per-transport default.
    if medium.kind == "network" and medium.transport is not None:
        per_transport = PER_TRANSPORT_TIMEOUT_MS.get(
            medium.transport.name
        )
        if per_transport is not None:
            timeout = per_transport
        # Transport-level override.
        if medium.transport.timeout_ms is not None:
            timeout = medium.transport.timeout_ms

    # Medium-level override (highest priority).
    if medium.timeout is not None:
        timeout = medium.timeout

    return timeout


def _make_transition_id(
    family: VectorFamily, ord_index: int, *, event: str
) -> str:
    """Per INV-S-ORCH-6: stable trace key for this vector.

    Shape: ``V-<ord>-<family>-<event>``. Ordering is the document order
    the orchestrator chart presents transitions in; ``ord_index`` is
    monotonically assigned across all families so each record has a
    globally-unique handle within the chart.
    """
    return f"V-{ord_index:04d}-{family.value}-{event}"


def _render_chart_vocabulary_failure(
    *,
    sender_piece: str,
    receiver_piece: str,
    event: str,
    medium: str,
    reason: BrokenProtocolReason,
    receiver_declared_events: list[str],
) -> str:
    """Render an INV-SOS-H chart-vocabulary failure message.

    No raw medium primitives — no protobuf field numbers, no ring-buffer
    offsets, no NVIC vector numbers. Sender piece id, receiver piece id,
    event name, medium kind are all chart-vocabulary; the receiver's
    declared-events list is also chart vocabulary (event names, not wire
    protocol opcodes).
    """
    if reason is BrokenProtocolReason.UNDECLARED_EVENT:
        declared = (
            ", ".join(sorted(receiver_declared_events))
            if receiver_declared_events
            else "<none>"
        )
        return (
            f"piece {sender_piece!r} fires cross-piece event "
            f"{event!r} over medium {medium!r} to piece "
            f"{receiver_piece!r}, but piece {receiver_piece!r} does not "
            f"declare {event!r} on any of its transitions "
            f"(declared events: {declared}); broken-protocol contract "
            f"per INV-SOS-H + INV-S-ORCH-6"
        )
    if reason is BrokenProtocolReason.MEDIUM_MISMATCH:
        return (
            f"piece {sender_piece!r} → piece {receiver_piece!r} on event "
            f"{event!r} uses medium {medium!r}, which is incompatible "
            f"with the receiver's declared transport binding; broken-"
            f"protocol contract per INV-SOS-H + INV-S-ORCH-5"
        )
    if reason is BrokenProtocolReason.IDEMPOTENCY_VIOLATED:
        return (
            f"piece {sender_piece!r} → piece {receiver_piece!r} on event "
            f"{event!r} declares idempotency over medium {medium!r}, "
            f"which does not provide retry-collapse semantics at the "
            f"medium layer; broken-protocol contract per INV-SOS-H + "
            f"PCDN-SOS-10-005"
        )
    # Fallthrough should be unreachable given the frozen enum.
    return (
        f"piece {sender_piece!r} → piece {receiver_piece!r} on event "
        f"{event!r} over medium {medium!r}: broken-protocol contract"
    )


def _extract_chart_sos_id(
    chart_ast: Optional[dict],
) -> str:
    """Best-effort sos:id extraction from the orchestrator's scxml root.

    Returns ``"<unidentified>"`` when the chart carries no ``sos:id``
    other_attribute, so downstream tooling never has to handle ``None``.
    """
    if not isinstance(chart_ast, dict):
        return "<unidentified>"
    import json
    oa = chart_ast.get("other_attributes")
    if oa is None:
        return "<unidentified>"
    if isinstance(oa, dict):
        inner = oa.get("other_attributes")
        if isinstance(inner, str):
            try:
                parsed = json.loads(inner)
            except json.JSONDecodeError:
                return "<unidentified>"
            sid = parsed.get("sos:id") if isinstance(parsed, dict) else None
            if isinstance(sid, str) and sid:
                return sid
        elif isinstance(inner, dict):
            sid = inner.get("sos:id")
            if isinstance(sid, str) and sid:
                return sid
    return "<unidentified>"


# ---------------------------------------------------------------------------
# Multi-hop chain discovery
# ---------------------------------------------------------------------------


def _discover_multi_hop_chains(
    transitions: list[CrossPieceTransitionAnnotation],
) -> list[list[CrossPieceTransitionAnnotation]]:
    """Discover linear A→B→C chains in the orchestrator transition graph.

    A chain is a sequence of ≥ 2 transitions where each subsequent
    transition's source piece matches the previous transition's target
    piece. Cycles are NOT chains for this emitter's purpose (the
    transition-family vector already covers each edge); we surface only
    distinct LINEAR chains of length 2 (one intermediate piece) to keep
    the vector budget bounded.

    Returned chains preserve document order: the outer list is sorted by
    the index of the first transition in the input ``transitions`` list.
    """
    by_source: dict[str, list[CrossPieceTransitionAnnotation]] = {}
    for tr in transitions:
        by_source.setdefault(tr.source_state_id, []).append(tr)

    chains: list[list[CrossPieceTransitionAnnotation]] = []
    for tr in transitions:
        # Find any transition whose source is this transition's target.
        nexts = by_source.get(tr.target_state_id, [])
        for nxt in nexts:
            # Skip cycles: avoid A→B→A as a "multi-hop chain" because the
            # transition-family vector already covers each edge and the
            # cycle adds no new contract verification.
            if nxt.target_state_id == tr.source_state_id:
                continue
            # Skip self-loops on the intermediate piece.
            if nxt.source_state_id == nxt.target_state_id:
                continue
            chains.append([tr, nxt])
    return chains


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def emit_cross_piece_vectors(
    orchestrator_inventory: OrchestratorAnnotations,
    *,
    chart_ast: Optional[dict] = None,
    receiver_event_index: Optional[dict[str, list[str]]] = None,
) -> list[CrossPieceVectorRecord]:
    """Emit the joint-protocol bounded-reachability vector set.

    Args:
        orchestrator_inventory: the typed annotation model produced by
            ``sos10_annotations.parse_orchestrator_annotations``. Strict
            one-orchestrator-per-system per PCDN-SOS-10-007.
        chart_ast: optional raw scjson dict for the orchestrator chart
            (used only to extract ``sos:id`` for the
            ``orchestrator_chart`` metadata field). When None or
            ``sos:id`` is absent, the field renders as ``"<unidentified>"``.
        receiver_event_index: optional ``{piece_id: [event_name, ...]}``
            map naming the events each receiver-piece declares as an
            event-in (per the per-piece chart's contract). When provided,
            the emitter generates ``broken_protocol`` vectors for every
            cross-piece transition whose event isn't declared by the
            receiver. When None, broken-protocol synthesis is skipped
            (the integration harness drives this path explicitly via the
            ``receiver_event_index`` parameter).

    Returns:
        A list of ``CrossPieceVectorRecord``, document-ordered as:
        transition vectors first (in chart document order), then
        timeouts (one per distinct medium / transport actually used by
        the chart), then idempotent_retry vectors, then broken_protocol
        vectors, then multi_hop vectors.

    Raises:
        Sos10VectorEmissionError: ``orchestrator_inventory`` is not an
            ``OrchestratorAnnotations`` instance (the
            strict-one-orchestrator-per-system policy at the type
            boundary), or carries no pieces.
    """
    if not isinstance(orchestrator_inventory, OrchestratorAnnotations):
        raise Sos10VectorEmissionError(
            f"orchestrator_inventory MUST be an OrchestratorAnnotations "
            f"instance per PCDN-SOS-10-007 (strict one-orchestrator-per-"
            f"system); got {type(orchestrator_inventory).__name__}",
            rule="PCDN-SOS-10-007",
        )
    if not orchestrator_inventory.pieces:
        raise Sos10VectorEmissionError(
            "orchestrator chart has zero pieces; an orchestrator with no "
            "pieces cannot host cross-piece events and violates INV-S-ORCH-1",
            rule="INV-S-ORCH-1",
        )

    chart_id = _extract_chart_sos_id(chart_ast)
    piece_ids = {p.state_id for p in orchestrator_inventory.pieces}

    records: list[CrossPieceVectorRecord] = []
    ord_index = 0

    # -----------------------------------------------------------------
    # (1) transition family — one vector per cross-piece transition.
    # -----------------------------------------------------------------
    for tr in orchestrator_inventory.transitions:
        # Guard: every cross-piece transition's source/target MUST be a
        # known piece. The parser already enforces target ∈ piece_ids,
        # but we re-assert here so that a hand-constructed inventory
        # that bypassed the parser still gets a clear error.
        if tr.source_state_id not in piece_ids:
            raise Sos10VectorEmissionError(
                f"transition source piece {tr.source_state_id!r} is not a "
                f"known piece (declared: {sorted(piece_ids)}); violates "
                f"INV-S-ORCH-1 / INV-S-ORCH-2",
                chart_id=chart_id,
                rule="INV-S-ORCH-1",
            )
        if tr.target_state_id not in piece_ids:
            raise Sos10VectorEmissionError(
                f"transition target piece {tr.target_state_id!r} is not a "
                f"known piece (declared: {sorted(piece_ids)}); violates "
                f"INV-S-ORCH-1 / INV-S-ORCH-2",
                chart_id=chart_id,
                rule="INV-S-ORCH-1",
            )

        ord_index += 1
        records.append(
            CrossPieceVectorRecord(
                family=VectorFamily.TRANSITION,
                orchestrator_chart=chart_id,
                transition_id=_make_transition_id(
                    VectorFamily.TRANSITION, ord_index, event=tr.event
                ),
                sender_piece=tr.source_state_id,
                receiver_piece=tr.target_state_id,
                medium=tr.medium.kind,
                expected_outcome=ExpectedOutcome.SUCCESS,
                event=tr.event,
                spec_refs=_SPEC_REFS_BASE,
                transport=(
                    tr.medium.transport.name
                    if tr.medium.transport is not None
                    else None
                ),
                timeout_ms=_resolve_timeout_ms(tr.medium),
                idempotent=_resolved_idempotency(tr),
            )
        )

    # -----------------------------------------------------------------
    # (2) timeout family — one vector per medium kind actually used by
    # the chart. For "network" we emit one timeout per (kind, transport)
    # pair so gRPC and AMQP are both covered when both transports appear.
    # -----------------------------------------------------------------
    seen_timeout_keys: set[tuple[str, Optional[str]]] = set()
    for tr in orchestrator_inventory.transitions:
        kind = tr.medium.kind
        transport = (
            tr.medium.transport.name
            if tr.medium.transport is not None
            else None
        )
        key = (kind, transport)
        if key in seen_timeout_keys:
            continue
        seen_timeout_keys.add(key)

        timeout_ms = _resolve_timeout_ms(tr.medium)
        # For media whose default is None (in-process / shared-memory /
        # mmio), the timeout vector still emits — it documents the
        # "caller's wait deadline is unbounded; the harness asserts the
        # consumer never starves" contract. Cocotb-side this becomes an
        # explicit timeout_ms=0 with a "non-applicable" disposition.
        ord_index += 1
        spec_refs = _SPEC_REFS_BASE + ("PCDN-SOS-10-006",)
        records.append(
            CrossPieceVectorRecord(
                family=VectorFamily.TIMEOUT,
                orchestrator_chart=chart_id,
                transition_id=_make_transition_id(
                    VectorFamily.TIMEOUT, ord_index, event=tr.event
                ),
                sender_piece=tr.source_state_id,
                receiver_piece=tr.target_state_id,
                medium=kind,
                expected_outcome=ExpectedOutcome.TIMEOUT,
                event=tr.event,
                spec_refs=spec_refs,
                transport=transport,
                timeout_ms=timeout_ms,
            )
        )

    # -----------------------------------------------------------------
    # (3) idempotent_retry family — one vector per <sos:idempotent
    # value="true"/> annotation (medium-level or transition-level
    # override resolved per PCDN-SOS-10-005).
    # -----------------------------------------------------------------
    for tr in orchestrator_inventory.transitions:
        resolved = _resolved_idempotency(tr)
        if resolved is not True:
            continue
        ord_index += 1
        spec_refs = _SPEC_REFS_BASE + ("PCDN-SOS-10-005",)
        records.append(
            CrossPieceVectorRecord(
                family=VectorFamily.IDEMPOTENT_RETRY,
                orchestrator_chart=chart_id,
                transition_id=_make_transition_id(
                    VectorFamily.IDEMPOTENT_RETRY, ord_index, event=tr.event
                ),
                sender_piece=tr.source_state_id,
                receiver_piece=tr.target_state_id,
                medium=tr.medium.kind,
                expected_outcome=ExpectedOutcome.RETRY_COLLAPSED,
                event=tr.event,
                spec_refs=spec_refs,
                transport=(
                    tr.medium.transport.name
                    if tr.medium.transport is not None
                    else None
                ),
                timeout_ms=_resolve_timeout_ms(tr.medium),
                idempotent=True,
            )
        )

    # -----------------------------------------------------------------
    # (4) broken_protocol family — one vector per cross-piece transition
    # whose event is NOT declared by the receiver-piece in the supplied
    # receiver_event_index. Per §12(d) this is the "deliberate broken-
    # protocol case" with INV-SOS-H chart-vocabulary rendering.
    # -----------------------------------------------------------------
    if receiver_event_index is not None:
        for tr in orchestrator_inventory.transitions:
            declared_events = list(
                receiver_event_index.get(tr.target_state_id, [])
            )
            if tr.event in declared_events:
                continue
            ord_index += 1
            spec_refs = _SPEC_REFS_BASE + ("PCDN-SOS-10-007",)
            failure_msg = _render_chart_vocabulary_failure(
                sender_piece=tr.source_state_id,
                receiver_piece=tr.target_state_id,
                event=tr.event,
                medium=tr.medium.kind,
                reason=BrokenProtocolReason.UNDECLARED_EVENT,
                receiver_declared_events=declared_events,
            )
            records.append(
                CrossPieceVectorRecord(
                    family=VectorFamily.BROKEN_PROTOCOL,
                    orchestrator_chart=chart_id,
                    transition_id=_make_transition_id(
                        VectorFamily.BROKEN_PROTOCOL,
                        ord_index,
                        event=tr.event,
                    ),
                    sender_piece=tr.source_state_id,
                    receiver_piece=tr.target_state_id,
                    medium=tr.medium.kind,
                    expected_outcome=ExpectedOutcome.BROKEN_PROTOCOL,
                    event=tr.event,
                    spec_refs=spec_refs,
                    transport=(
                        tr.medium.transport.name
                        if tr.medium.transport is not None
                        else None
                    ),
                    broken_protocol_reason=BrokenProtocolReason.UNDECLARED_EVENT,
                    failure_message=failure_msg,
                )
            )

    # -----------------------------------------------------------------
    # (5) multi_hop family — one vector per discovered A→B→C chain.
    # -----------------------------------------------------------------
    chains = _discover_multi_hop_chains(orchestrator_inventory.transitions)
    for chain in chains:
        ord_index += 1
        first = chain[0]
        last = chain[-1]
        hops = tuple(
            {
                "sender_piece": hop.source_state_id,
                "receiver_piece": hop.target_state_id,
                "event": hop.event,
                "medium": hop.medium.kind,
                "transport": (
                    hop.medium.transport.name
                    if hop.medium.transport is not None
                    else None
                ),
            }
            for hop in chain
        )
        records.append(
            CrossPieceVectorRecord(
                family=VectorFamily.MULTI_HOP,
                orchestrator_chart=chart_id,
                transition_id=_make_transition_id(
                    VectorFamily.MULTI_HOP, ord_index, event=first.event
                ),
                sender_piece=first.source_state_id,
                receiver_piece=last.target_state_id,
                medium=first.medium.kind,
                expected_outcome=ExpectedOutcome.SUCCESS,
                event=first.event,
                spec_refs=_SPEC_REFS_BASE,
                hops=hops,
            )
        )

    return records


__all__ = [
    "BrokenProtocolReason",
    "CrossPieceVectorRecord",
    "ExpectedOutcome",
    "PER_MEDIUM_TIMEOUT_MS",
    "PER_TRANSPORT_TIMEOUT_MS",
    "Sos10VectorEmissionError",
    "VectorFamily",
    "emit_cross_piece_vectors",
]

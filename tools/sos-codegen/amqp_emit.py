"""SOS-10 ``network`` medium AMQP message-handler emitter.

Authority: ``docs/concepts/SOS-10-CONCEPTS.md`` §6.4 (network medium —
AMQP secondary at v1; ratified 2026-05-23, all 8 PCDNs resolved).
Per PCDN-SOS-10-002 protobuf is the canonical wire-format IDL and AMQP
message bodies are protobuf-encoded (one IDL, two transports). This
module is the wave-17b sibling to the gRPC emitter: it consumes the
same :class:`sos10_annotations.OrchestratorAnnotations` model + the
``amqp_routing.json`` artifact produced by :mod:`protobuf_emit` and
emits per-piece Rust AMQP producer / consumer / topology artifacts
plus a Cargo.toml seed.

Public surface:
    emit_amqp(annotations, *, chart_sos_id, chart_id=None,
              routing_config=None, output_dir=None) -> dict[str, str]
    emit_amqp_from_chart(chart_path, **kwargs) -> dict[str, str]
    AmqpEmitError                              — ValueError subclass.
    DEFAULT_AMQP_TIMEOUT_MS                    — 10000 per PCDN-SOS-10-006.

What this module emits
----------------------

For each piece P involved in at least one AMQP cross-piece transition,
under ``build/network/<chart_id>/`` (filenames carry no directory
component):

1. ``<P>_amqp_producer.rs`` — one ``pub async fn send_<event>(...)``
   per outgoing AMQP event whose ``source_state_id == P``. Encodes the
   payload via ``prost::Message::encode_to_vec`` and publishes to the
   routing-config-declared exchange with the routing key being the
   event name. Per PCDN-SOS-10-006 the AMQP timeout default is
   10000ms; chart-author MAY override via ``<sos:transport
   timeout-ms="..."/>``.

2. ``<P>_amqp_consumer.rs`` — one ``pub async fn
   handle_<event>(payload_bytes: &[u8])`` per incoming AMQP event
   whose ``target_state_id == P`` (decodes via
   ``<EventRequest>::decode(...)``), plus a ``pub async fn
   consume(channel, queue)`` boilerplate consumer loop that routes
   each delivery to the matching handler by inspecting its routing
   key.

3. ``<P>_amqp_topology.rs`` — ``pub async fn declare_topology(channel)``
   that declares every exchange + queue + binding listed in
   ``amqp_routing.json`` (per chart-explicit routing-key matching, the
   exchange kind is :data:`lapin::ExchangeKind::Direct`).

4. ``<P>_amqp_Cargo.toml`` — workspace-fragment Cargo.toml listing
   ``lapin``, ``prost``, ``tokio`` (multi-thread features). A leading
   comment notes that ``tonic-build`` is NOT required for an AMQP-only
   piece (only the protobuf message types, not gRPC services).

Filter rule
-----------

This emitter walks only ``network``-medium transitions whose
``transport.name == "AMQP"``. Other media (in-process / shared-memory
/ mmio) are SILENTLY skipped; non-AMQP network transitions (gRPC) are
likewise silently skipped (the gRPC sibling owns them).

Idempotency warning (INV-S-ORCH-5 + PCDN-SOS-10-005)
----------------------------------------------------

Per the §6.4 footnote, AMQP MAY drop, reorder or duplicate messages.
When a transition's ``idempotent`` (or its medium's ``idempotent``)
flag is explicitly ``False`` the emitter logs a warning naming the
transition. ``None`` (no explicit annotation) yields no warning at v1;
PCDN-SOS-10-005's "warn if non-idempotent transition is the only path
from a state" check is owned by the orchestrator-level vector emitter,
not by this per-medium emitter — but we keep the warning hook here for
the explicit ``False`` case so chart-authors get told at code-gen.

Determinism
-----------

Event-method ordering: alphabetical by event name. Topology
declaration order: alphabetical by exchange, then queue, then routing
key. Two emit runs over the same annotations produce byte-identical
output.

@spec citations on every emitted file
-------------------------------------

Each emitted Rust file carries a banner block citing:

- SOS-10-CONCEPTS §6.4 (network medium contract).
- PCDN-SOS-10-001 (Rust as default piece language).
- PCDN-SOS-10-002 (protobuf canonical IDL; AMQP body encoding).
- PCDN-SOS-10-006 (AMQP default timeout 10000ms; chart override).
- INV-S-ORCH-1 (one orchestrator per system).
- INV-S-ORCH-4 (wire format derived, not authored).
- INV-S-ORCH-5 (AMQP MAY drop/reorder/duplicate per §6.4 footnote).
- INV-SOS-A (every emitted file is a build output).
- The chart's ``sos:id`` UUID.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Self-relative import — this module lives at tools/sos-codegen/.
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos10_annotations import (  # noqa: E402
    CrossPieceTransitionAnnotation,
    OrchestratorAnnotations,
    parse_orchestrator_annotations,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Per PCDN-SOS-10-006: AMQP default timeout. Chart-author MAY override
#: via ``<sos:transport timeout-ms="..."/>`` (transport-level) or
#: ``<sos:medium><sos:timeout ms="..."/></sos:medium>`` (medium-level).
DEFAULT_AMQP_TIMEOUT_MS: int = 10_000

#: This emitter handles only ``network`` medium with ``AMQP`` transport.
_NETWORK_KIND: str = "network"
_AMQP_TRANSPORT: str = "AMQP"

#: SV-identifier shape — piece ids and event names that don't satisfy
#: this can't safely appear in Rust identifier positions.
_SV_IDENTIFIER_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

#: Module-private logger; tests assert on ``WARNING``-level records via
#: ``caplog``.
_LOGGER: logging.Logger = logging.getLogger("sos10.amqp_emit")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AmqpEmitError(ValueError):
    """Raised on malformed inputs to the AMQP emitter.

    Carries the offending transition's source/target/event tokens when
    known, mirroring :class:`protobuf_emit.ProtobufEmitError` (the gRPC
    sibling raises a parallel error type; both surface the chart-author
    error in chart vocabulary for INV-S-ORCH-6 traceability).
    """

    def __init__(
        self,
        message: str,
        *,
        source: Optional[str] = None,
        target: Optional[str] = None,
        event: Optional[str] = None,
    ) -> None:
        self.source = source
        self.target = target
        self.event = event
        prefix_parts: list[str] = []
        if source and target:
            ev_part = f"/{event}" if event else ""
            prefix_parts.append(f"[{source} -> {target}{ev_part}]")
        prefix = " ".join(prefix_parts)
        super().__init__(f"{prefix}: {message}" if prefix else message)


# ---------------------------------------------------------------------------
# Internal dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _AmqpEvent:
    """One AMQP-medium cross-piece event, resolved to its emission shape.

    ``timeout_ms`` is the per-transition timeout the producer stub will
    embed: chart-author transport-level override > chart-author medium-
    level override > :data:`DEFAULT_AMQP_TIMEOUT_MS`.

    ``idempotent`` carries the resolved tri-state per
    PCDN-SOS-10-005: ``True`` / ``False`` / ``None`` (unspecified).
    Transition-level override wins over medium-level when both are set.
    """

    source_piece: str
    target_piece: str
    event: str
    timeout_ms: int
    idempotent: Optional[bool]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_amqp(transition: CrossPieceTransitionAnnotation) -> bool:
    """True iff the transition is a network-medium AMQP transport."""
    if transition.medium.kind != _NETWORK_KIND:
        return False
    transport = transition.medium.transport
    if transport is None:
        return False
    return transport.name == _AMQP_TRANSPORT


def _validate_piece_id(piece_id: str) -> None:
    """Raise if a piece id isn't a valid Rust identifier."""
    if not _SV_IDENTIFIER_RE.match(piece_id):
        raise AmqpEmitError(
            f"piece id {piece_id!r} is not an SV identifier; cannot be "
            f"used as a Rust identifier (module names, function names)",
            source=piece_id,
        )


def _safe_event_token(event_name: str) -> str:
    """Map an event name (e.g. ``"audio.start"``) to a Rust-safe ident.

    Mirrors :func:`protobuf_emit._safe_event_token` so the message-type
    naming stays consistent across the two emitters.
    """
    safe = re.sub(r"[^A-Za-z0-9_]", "_", event_name)
    if safe and safe[0].isdigit():
        safe = f"ev_{safe}"
    return safe or "ev_unnamed"


def _pascal(token: str) -> str:
    """snake_case → PascalCase. Identity for already-PascalCase tokens."""
    parts = re.split(r"[^A-Za-z0-9]+", token)
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _proto_message_root(src: str, dst: str, event: str) -> str:
    """Build the protobuf message-type root (matches protobuf_emit)."""
    return f"{_pascal(src)}To{_pascal(dst)}_{_safe_event_token(event)}"


def _resolve_timeout(transition: CrossPieceTransitionAnnotation) -> int:
    """Resolve the per-event AMQP timeout (ms).

    Precedence per PCDN-SOS-10-006:
        1. ``<sos:transport timeout-ms="...">`` (transport-level)
        2. ``<sos:medium><sos:timeout ms="..."/></sos:medium>`` (medium-level)
        3. :data:`DEFAULT_AMQP_TIMEOUT_MS` (10000).
    """
    transport = transition.medium.transport
    if transport is not None and transport.timeout_ms is not None:
        return transport.timeout_ms
    if transition.medium.timeout is not None:
        return transition.medium.timeout
    return DEFAULT_AMQP_TIMEOUT_MS


def _resolve_idempotent(
    transition: CrossPieceTransitionAnnotation,
) -> Optional[bool]:
    """Resolve the per-event idempotency tri-state.

    Transition-level ``sos:idempotent`` override (PCDN-SOS-10-005) wins;
    medium-level ``<sos:idempotent>`` is the fallback; ``None`` means
    unspecified.
    """
    if transition.idempotent is not None:
        return transition.idempotent
    return transition.medium.idempotent


def _build_amqp_events(
    transitions: list[CrossPieceTransitionAnnotation],
) -> list[_AmqpEvent]:
    """Construct sorted, deduplicated AMQP-event entries.

    Deterministic order: alphabetical by (source_piece, target_piece,
    event). Duplicate ``(src, dst, event)`` triples with diverging
    timeout / idempotency declarations raise an :class:`AmqpEmitError`
    (chart-author error); identical duplicates dedupe silently.
    """
    events: dict[tuple[str, str, str], _AmqpEvent] = {}
    for t in transitions:
        if not _is_amqp(t):
            continue
        key = (t.source_state_id, t.target_state_id, t.event)
        ev = _AmqpEvent(
            source_piece=t.source_state_id,
            target_piece=t.target_state_id,
            event=t.event,
            timeout_ms=_resolve_timeout(t),
            idempotent=_resolve_idempotent(t),
        )
        if key in events:
            existing = events[key]
            if (
                existing.timeout_ms != ev.timeout_ms
                or existing.idempotent != ev.idempotent
            ):
                raise AmqpEmitError(
                    f"duplicate AMQP cross-piece event with diverging "
                    f"timeout / idempotency: existing="
                    f"(timeout_ms={existing.timeout_ms}, "
                    f"idempotent={existing.idempotent}) new="
                    f"(timeout_ms={ev.timeout_ms}, "
                    f"idempotent={ev.idempotent})",
                    source=t.source_state_id,
                    target=t.target_state_id,
                    event=t.event,
                )
            continue
        events[key] = ev
    return [events[k] for k in sorted(events.keys())]


def _maybe_warn_non_idempotent(events: list[_AmqpEvent]) -> None:
    """Emit a WARNING per AMQP transition with ``idempotent=False``.

    Per INV-S-ORCH-5 + PCDN-SOS-10-005 footnote: AMQP MAY drop /
    reorder / duplicate; a chart-author who explicitly declares a
    cross-piece event as non-idempotent gets a code-gen-time warning
    naming the transition. ``None`` (unspecified) yields no warning at
    v1 — PCDN-SOS-10-005's "only path from a state" check is the
    orchestrator-level vector emitter's responsibility, not this
    per-medium emitter's.
    """
    for ev in events:
        if ev.idempotent is False:
            _LOGGER.warning(
                "SOS-10 §6.4 + PCDN-SOS-10-005: AMQP transition "
                "%s -> %s / %s is declared non-idempotent; AMQP MAY "
                "drop / reorder / duplicate messages (INV-S-ORCH-5). "
                "Producer/consumer stubs do not add retry semantics; "
                "chart-author is responsible for idempotency at the "
                "piece's handler.",
                ev.source_piece,
                ev.target_piece,
                ev.event,
            )


# ---------------------------------------------------------------------------
# Routing-config consumption
# ---------------------------------------------------------------------------


def _load_routing_config(
    routing_config: Optional[dict | Path | str],
    *,
    chart_id: str,
    events: list[_AmqpEvent],
) -> dict[str, object]:
    """Return the AMQP routing-config dict.

    If ``routing_config`` is a dict, use it directly (typically passed by
    a caller who has just produced it via :func:`protobuf_emit.emit_protobuf`).
    If it's a Path / str, read JSON from disk. If None, synthesise an
    equivalent in-memory config from the emitter's own ``events`` list —
    deterministic and matches what the protobuf emitter would produce
    for the same chart.

    Schema (matches :func:`protobuf_emit._render_amqp_routing_json`):
        {
            "_spec": { ... },
            "chart_id": "<chart_id>",
            "entries": [
                {
                    "source_piece": ..., "target_piece": ...,
                    "exchange": ..., "queue": ...,
                    "routing_keys": [...],
                },
                ...
            ]
        }
    """
    if isinstance(routing_config, dict):
        return routing_config
    if isinstance(routing_config, (str, Path)):
        path = Path(routing_config)
        with path.open("r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if not isinstance(loaded, dict):
            raise AmqpEmitError(
                f"amqp_routing.json at {path!s} must be a JSON object; "
                f"got {type(loaded).__name__}"
            )
        return loaded

    # Synthesise from the emitter's own event list. Group by (src, dst).
    grouped: dict[tuple[str, str], list[str]] = {}
    for ev in events:
        grouped.setdefault((ev.source_piece, ev.target_piece), []).append(ev.event)
    entries: list[dict[str, object]] = []
    for (src, dst) in sorted(grouped.keys()):
        keys = sorted(set(grouped[(src, dst)]))
        entries.append(
            {
                "source_piece": src,
                "target_piece": dst,
                "exchange": f"{chart_id}.{src}",
                "queue": f"{chart_id}.{dst}",
                "routing_keys": keys,
            }
        )
    return {"chart_id": chart_id, "entries": entries}


def _entries_for_piece(
    config: dict[str, object],
    piece: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Partition routing entries into (outgoing, incoming) for ``piece``.

    Outgoing: entries with ``source_piece == piece`` (this piece
    publishes). Incoming: entries with ``target_piece == piece`` (this
    piece consumes). Topology setup needs BOTH sets (a piece must
    declare every exchange it publishes to AND every queue it consumes
    from, alongside the corresponding bindings).
    """
    raw_entries = config.get("entries") or []
    if not isinstance(raw_entries, list):
        raise AmqpEmitError("amqp_routing.json `entries` must be a list")
    outgoing: list[dict[str, object]] = []
    incoming: list[dict[str, object]] = []
    for e in raw_entries:
        if not isinstance(e, dict):
            continue
        if e.get("source_piece") == piece:
            outgoing.append(e)
        if e.get("target_piece") == piece:
            incoming.append(e)
    return outgoing, incoming


# ---------------------------------------------------------------------------
# @spec banner
# ---------------------------------------------------------------------------


def _spec_banner(chart_sos_id: str) -> str:
    """Return the @spec citation block as a leading Rust line-comment."""
    return (
        "// @spec SOS-10-CONCEPTS §6.4 (network medium contract; AMQP secondary)\n"
        "// @spec PCDN-SOS-10-001 (Rust default piece language)\n"
        "// @spec PCDN-SOS-10-002 (protobuf canonical IDL; AMQP body encoding)\n"
        "// @spec PCDN-SOS-10-006 (AMQP default timeout 10000ms; chart override)\n"
        "// @spec INV-S-ORCH-1 (one orchestrator per system)\n"
        "// @spec INV-S-ORCH-4 (wire format derived, not authored)\n"
        "// @spec INV-S-ORCH-5 (AMQP MAY drop / reorder / duplicate per §6.4 footnote)\n"
        "// @spec INV-SOS-A (every emitted file is a build output)\n"
        f"// @spec chart sos:id {chart_sos_id}\n"
        "// AUTO-GENERATED by sos-codegen/amqp_emit.py — do not edit.\n"
    )


def _spec_banner_toml(chart_sos_id: str) -> str:
    """Return a TOML-comment-prefixed @spec banner."""
    return (
        "# @spec SOS-10-CONCEPTS §6.4 (network medium contract; AMQP secondary)\n"
        "# @spec PCDN-SOS-10-001 (Rust default piece language)\n"
        "# @spec PCDN-SOS-10-002 (protobuf canonical IDL; AMQP body encoding)\n"
        "# @spec PCDN-SOS-10-006 (AMQP default timeout 10000ms; chart override)\n"
        "# @spec INV-S-ORCH-1 (one orchestrator per system)\n"
        "# @spec INV-S-ORCH-4 (wire format derived, not authored)\n"
        "# @spec INV-S-ORCH-5 (AMQP MAY drop / reorder / duplicate per §6.4)\n"
        "# @spec INV-SOS-A (every emitted file is a build output)\n"
        f"# @spec chart sos:id {chart_sos_id}\n"
        "# AUTO-GENERATED by sos-codegen/amqp_emit.py — do not edit.\n"
    )


# ---------------------------------------------------------------------------
# Rendering — producer
# ---------------------------------------------------------------------------


def _render_producer(
    *,
    chart_sos_id: str,
    piece_id: str,
    outgoing_events: list[_AmqpEvent],
    outgoing_entries: list[dict[str, object]],
) -> str:
    """Render ``<piece>_amqp_producer.rs`` for one piece.

    One ``pub async fn send_<event>(...)`` per outgoing AMQP event.
    Each publishes to the routing-config-declared exchange (matched by
    ``source_piece``) with the event name as the routing key. Payload
    encoded via ``prost::Message::encode_to_vec(payload)``. Per
    PCDN-SOS-10-006 timeout default 10s, embedded as a
    ``tokio::time::timeout(Duration::from_millis(...))`` wrapper around
    the publish + confirm round-trip.
    """
    # Build an (exchange, source_piece) lookup so each event maps to
    # the right exchange when there are multiple outgoing pairings.
    exchange_for_target: dict[str, str] = {}
    for entry in outgoing_entries:
        tgt = entry.get("target_piece")
        ex = entry.get("exchange")
        if isinstance(tgt, str) and isinstance(ex, str):
            exchange_for_target[tgt] = ex

    lines: list[str] = []
    lines.append(_spec_banner(chart_sos_id))
    lines.append("//\n")
    lines.append(
        f"// AMQP producer for piece `{piece_id}` — one async fn per outgoing\n"
        f"// cross-piece AMQP event. Each fn encodes the payload via prost\n"
        f"// and publishes to the chart-declared exchange with the event name\n"
        f"// as the routing key.\n\n"
    )
    lines.append("use std::time::Duration;\n\n")
    lines.append("use lapin::{options::BasicPublishOptions, BasicProperties, Channel};\n")
    lines.append("use prost::Message;\n")
    lines.append("use tokio::time::timeout;\n\n")
    lines.append(
        "/// Errors a producer can encounter. Wraps lapin transport errors,\n"
        "/// the tokio timeout sentinel, and a per-confirm-failure variant.\n"
        "#[derive(Debug)]\n"
        "pub enum AmqpPublishError {\n"
        "    Lapin(lapin::Error),\n"
        "    Timeout,\n"
        "    NotConfirmed,\n"
        "}\n\n"
        "impl From<lapin::Error> for AmqpPublishError {\n"
        "    fn from(e: lapin::Error) -> Self { AmqpPublishError::Lapin(e) }\n"
        "}\n\n"
    )

    if not outgoing_events:
        lines.append(
            "// no outgoing AMQP events from this piece — file emitted as a\n"
            "// build-output sentinel per INV-SOS-A.\n"
        )
        return "".join(lines)

    for ev in outgoing_events:
        msg_root = _proto_message_root(ev.source_piece, ev.target_piece, ev.event)
        fn_name = f"send_{_safe_event_token(ev.event)}_to_{ev.target_piece}"
        exchange = exchange_for_target.get(ev.target_piece, "<unknown>")
        routing_key = ev.event
        timeout_ms = ev.timeout_ms
        lines.append(
            f"/// Publish `{ev.event}` from `{ev.source_piece}` to "
            f"`{ev.target_piece}` over AMQP.\n"
            f"///\n"
            f"/// Exchange: `{exchange}` (declared by `declare_topology`).\n"
            f"/// Routing key: `{routing_key}`.\n"
            f"/// Timeout: {timeout_ms} ms "
            f"(per PCDN-SOS-10-006; chart-overridable).\n"
            f"pub async fn {fn_name}(\n"
            f"    channel: &Channel,\n"
            f"    payload: &super::orchestrator::{msg_root}_Request,\n"
            f") -> Result<(), AmqpPublishError> {{\n"
            f"    let body = payload.encode_to_vec();\n"
            f"    let publish = channel.basic_publish(\n"
            f'        "{exchange}",\n'
            f'        "{routing_key}",\n'
            f"        BasicPublishOptions::default(),\n"
            f"        &body,\n"
            f"        BasicProperties::default(),\n"
            f"    );\n"
            f"    let confirm = timeout(\n"
            f"        Duration::from_millis({timeout_ms}),\n"
            f"        async {{ publish.await?.await }},\n"
            f"    )\n"
            f"    .await\n"
            f"    .map_err(|_| AmqpPublishError::Timeout)??;\n"
            f"    if confirm.is_nack() {{\n"
            f"        return Err(AmqpPublishError::NotConfirmed);\n"
            f"    }}\n"
            f"    Ok(())\n"
            f"}}\n\n"
        )
    return "".join(lines)


# ---------------------------------------------------------------------------
# Rendering — consumer
# ---------------------------------------------------------------------------


def _render_consumer(
    *,
    chart_sos_id: str,
    piece_id: str,
    incoming_events: list[_AmqpEvent],
    incoming_entries: list[dict[str, object]],
) -> str:
    """Render ``<piece>_amqp_consumer.rs`` for one piece.

    One ``pub async fn handle_<event>(payload_bytes)`` per incoming
    AMQP event. The boilerplate ``pub async fn consume(channel,
    queue)`` reads from the chart-declared queue and dispatches each
    delivery to the matching handler by inspecting its routing key.

    Per INV-S-ORCH-5, AMQP MAY drop / reorder / duplicate; the v1
    consumer ACKs after the handler returns ``Ok`` and re-queues
    (``nack`` with requeue) on handler error. Chart-author owns
    idempotency at the handler when PCDN-SOS-10-005 declares the
    event non-idempotent (see code-gen-time warning).
    """
    # Distinct queue names referenced. At v1 a chart canonical form is
    # one queue per target_piece (per protobuf_emit's routing-config),
    # so all incoming entries for a piece share the same queue. Keep the
    # set surface flexible for future N-queues-per-piece configs.
    queue_for_source: dict[str, str] = {}
    for entry in incoming_entries:
        src = entry.get("source_piece")
        q = entry.get("queue")
        if isinstance(src, str) and isinstance(q, str):
            queue_for_source[src] = q

    lines: list[str] = []
    lines.append(_spec_banner(chart_sos_id))
    lines.append("//\n")
    lines.append(
        f"// AMQP consumer for piece `{piece_id}` — one async handler per\n"
        f"// incoming cross-piece AMQP event + a boilerplate consume() loop\n"
        f"// that routes deliveries to the matching handler by routing key.\n\n"
    )
    lines.append("use futures_util::StreamExt;\n")
    lines.append(
        "use lapin::{options::{BasicAckOptions, BasicConsumeOptions, BasicNackOptions}, "
        "types::FieldTable, Channel};\n"
    )
    lines.append("use prost::Message;\n\n")
    lines.append(
        "/// Errors the consumer can encounter while decoding a payload.\n"
        "#[derive(Debug)]\n"
        "pub enum AmqpDecodeError {\n"
        "    Prost(prost::DecodeError),\n"
        "    UnknownRoutingKey(String),\n"
        "}\n\n"
        "impl From<prost::DecodeError> for AmqpDecodeError {\n"
        "    fn from(e: prost::DecodeError) -> Self { AmqpDecodeError::Prost(e) }\n"
        "}\n\n"
    )

    if not incoming_events:
        lines.append(
            "// no incoming AMQP events on this piece — file emitted as a\n"
            "// build-output sentinel per INV-SOS-A.\n"
        )
        lines.append(
            "pub async fn consume(_channel: &Channel, _queue: &str) "
            "-> Result<(), lapin::Error> { Ok(()) }\n"
        )
        return "".join(lines)

    # Per-event handler functions.
    for ev in incoming_events:
        msg_root = _proto_message_root(ev.source_piece, ev.target_piece, ev.event)
        fn_name = f"handle_{_safe_event_token(ev.event)}_from_{ev.source_piece}"
        lines.append(
            f"/// Handle one AMQP delivery carrying `{ev.event}` from "
            f"`{ev.source_piece}`.\n"
            f"///\n"
            f"/// Decodes the protobuf payload and forwards to the user's\n"
            f"/// piece-side handler. v1 returns Empty per "
            f"PCDN-SOS-10-002's response-default.\n"
            f"pub async fn {fn_name}(\n"
            f"    payload_bytes: &[u8],\n"
            f") -> Result<super::orchestrator::{msg_root}_Response, "
            f"AmqpDecodeError> {{\n"
            f"    let _req = super::orchestrator::{msg_root}_Request::decode(\n"
            f"        payload_bytes,\n"
            f"    )?;\n"
            f"    // TODO(SOS-10-handler): user-supplied logic for "
            f"`{ev.event}` lives here.\n"
            f"    Ok(super::orchestrator::{msg_root}_Response::default())\n"
            f"}}\n\n"
        )

    # consume() boilerplate.
    lines.append(
        "/// Consumer loop: read the chart-declared queue and dispatch each\n"
        "/// delivery to the matching handler by routing key. Per "
        "INV-S-ORCH-5\n"
        "/// AMQP MAY drop / reorder / duplicate; the loop ACKs on "
        "handler-Ok\n"
        "/// and Nack-requeues on handler-Err. Chart-author owns "
        "idempotency\n"
        "/// at the handler when the event is declared non-idempotent.\n"
        "pub async fn consume(channel: &Channel, queue: &str) -> "
        "Result<(), lapin::Error> {\n"
        "    let mut consumer = channel\n"
        "        .basic_consume(\n"
        "            queue,\n"
        f'            "sos10_{piece_id}_consumer",\n'
        "            BasicConsumeOptions::default(),\n"
        "            FieldTable::default(),\n"
        "        )\n"
        "        .await?;\n"
        "    while let Some(delivery) = consumer.next().await {\n"
        "        let delivery = delivery?;\n"
        "        let routing_key = delivery.routing_key.as_str();\n"
        "        let body = &delivery.data;\n"
        "        let dispatch: Result<(), AmqpDecodeError> = match routing_key {\n"
    )
    for ev in incoming_events:
        fn_name = f"handle_{_safe_event_token(ev.event)}_from_{ev.source_piece}"
        lines.append(
            f'            "{ev.event}" => {fn_name}(body).await.map(|_| ()),\n'
        )
    lines.append(
        "            other => Err(AmqpDecodeError::UnknownRoutingKey("
        "other.to_string())),\n"
        "        };\n"
        "        match dispatch {\n"
        "            Ok(()) => {\n"
        "                delivery.ack(BasicAckOptions::default()).await?;\n"
        "            }\n"
        "            Err(_) => {\n"
        "                delivery\n"
        "                    .nack(BasicNackOptions { requeue: true, "
        "..BasicNackOptions::default() })\n"
        "                    .await?;\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "    Ok(())\n"
        "}\n"
    )
    return "".join(lines)


# ---------------------------------------------------------------------------
# Rendering — topology
# ---------------------------------------------------------------------------


def _render_topology(
    *,
    chart_sos_id: str,
    piece_id: str,
    outgoing_entries: list[dict[str, object]],
    incoming_entries: list[dict[str, object]],
) -> str:
    """Render ``<piece>_amqp_topology.rs``.

    One ``pub async fn declare_topology(channel)`` that declares every
    exchange this piece publishes to, every queue this piece consumes
    from, and the bindings between them. Per the chart-explicit
    routing-key matching the exchange kind is
    :data:`lapin::ExchangeKind::Direct`.

    Order: alphabetical by exchange, then by queue, then by routing
    key. Two emit runs over the same chart produce byte-identical
    output.
    """
    # Collapse outgoing + incoming into a deduplicated set of
    # (exchange, queue, routing_key) bindings + the standalone
    # exchanges-to-declare + queues-to-declare.
    exchanges: set[str] = set()
    queues: set[str] = set()
    bindings: set[tuple[str, str, str]] = set()
    for entry in outgoing_entries:
        ex = entry.get("exchange")
        q = entry.get("queue")
        keys = entry.get("routing_keys") or []
        if isinstance(ex, str):
            exchanges.add(ex)
        if isinstance(q, str):
            queues.add(q)
        if isinstance(ex, str) and isinstance(q, str) and isinstance(keys, list):
            for k in keys:
                if isinstance(k, str):
                    bindings.add((ex, q, k))
    for entry in incoming_entries:
        ex = entry.get("exchange")
        q = entry.get("queue")
        keys = entry.get("routing_keys") or []
        if isinstance(ex, str):
            exchanges.add(ex)
        if isinstance(q, str):
            queues.add(q)
        if isinstance(ex, str) and isinstance(q, str) and isinstance(keys, list):
            for k in keys:
                if isinstance(k, str):
                    bindings.add((ex, q, k))

    lines: list[str] = []
    lines.append(_spec_banner(chart_sos_id))
    lines.append("//\n")
    lines.append(
        f"// AMQP topology setup for piece `{piece_id}`. Declares every\n"
        f"// exchange this piece publishes to + every queue it consumes "
        f"from\n"
        f"// + the bindings between them. ExchangeKind is `Direct` per the\n"
        f"// chart-explicit routing-key matching model.\n\n"
    )
    lines.append(
        "use lapin::{options::{ExchangeDeclareOptions, QueueBindOptions, "
        "QueueDeclareOptions}, types::FieldTable, Channel, ExchangeKind};\n\n"
    )
    lines.append(
        "/// Declare every exchange / queue / binding this piece needs.\n"
        "/// Idempotent — safe to call on every connect.\n"
        "pub async fn declare_topology(channel: &Channel) -> "
        "Result<(), lapin::Error> {\n"
    )

    if not exchanges and not queues and not bindings:
        lines.append(
            "    // no AMQP topology for this piece — sentinel call.\n"
            "    let _ = channel;\n"
            "    Ok(())\n"
            "}\n"
        )
        return "".join(lines)

    for ex in sorted(exchanges):
        lines.append(
            "    channel\n"
            "        .exchange_declare(\n"
            f'            "{ex}",\n'
            "            ExchangeKind::Direct,\n"
            "            ExchangeDeclareOptions::default(),\n"
            "            FieldTable::default(),\n"
            "        )\n"
            "        .await?;\n"
        )
    for q in sorted(queues):
        lines.append(
            "    channel\n"
            "        .queue_declare(\n"
            f'            "{q}",\n'
            "            QueueDeclareOptions::default(),\n"
            "            FieldTable::default(),\n"
            "        )\n"
            "        .await?;\n"
        )
    for (ex, q, key) in sorted(bindings):
        lines.append(
            "    channel\n"
            "        .queue_bind(\n"
            f'            "{q}",\n'
            f'            "{ex}",\n'
            f'            "{key}",\n'
            "            QueueBindOptions::default(),\n"
            "            FieldTable::default(),\n"
            "        )\n"
            "        .await?;\n"
        )
    lines.append("    Ok(())\n")
    lines.append("}\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Rendering — Cargo.toml seed
# ---------------------------------------------------------------------------


def _render_cargo_toml(*, chart_sos_id: str, piece_id: str) -> str:
    """Render ``<piece>_amqp_Cargo.toml`` workspace fragment.

    Lists ``lapin``, ``prost``, ``tokio`` (multi-thread features), plus
    ``futures-util`` for the consumer's stream adapter. ``tonic-build``
    is intentionally NOT a dependency — an AMQP-only piece needs the
    protobuf message types but not the gRPC service plumbing.
    """
    lines: list[str] = []
    lines.append(_spec_banner_toml(chart_sos_id))
    lines.append("#\n")
    lines.append(
        f"# Workspace-fragment Cargo.toml seed for piece `{piece_id}`. The\n"
        f"# AMQP-only piece needs the protobuf message types (via `prost`)\n"
        f"# but NOT the gRPC service plumbing — `tonic-build` is intentionally\n"
        f"# omitted from build-dependencies.\n\n"
    )
    lines.append("[package]\n")
    lines.append(f'name = "sos10_{piece_id}_amqp"\n')
    lines.append('version = "0.1.0"\n')
    lines.append('edition = "2021"\n\n')
    lines.append("[dependencies]\n")
    lines.append('lapin = "2"\n')
    lines.append('prost = "0.12"\n')
    lines.append('tokio = { version = "1", features = ["macros", "rt-multi-thread", "time"] }\n')
    lines.append('futures-util = "0.3"\n\n')
    lines.append("[build-dependencies]\n")
    lines.append("# tonic-build NOT needed for AMQP-only pieces — we use the\n")
    lines.append("# protobuf message types only, not the gRPC service surface.\n")
    lines.append('prost-build = "0.12"\n')
    return "".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def emit_amqp(
    annotations: OrchestratorAnnotations,
    *,
    chart_sos_id: str,
    chart_id: Optional[str] = None,
    routing_config: Optional[dict | Path | str] = None,
    output_dir: Optional[Path | str] = None,
) -> dict[str, str]:
    """Emit AMQP producer / consumer / topology / Cargo.toml artifacts.

    Args:
        annotations: parsed SOS-10 orchestrator annotations.
        chart_sos_id: the orchestrator chart's ``sos:id`` UUID. Carried
            verbatim into every emitted file's @spec banner.
        chart_id: chart-level identifier used for exchange / queue
            naming (matches :func:`protobuf_emit.emit_protobuf`'s
            ``chart_id``). Defaults to the leading-8 hex of
            ``chart_sos_id`` when omitted.
        routing_config: optional pre-built routing config. Accepts a
            dict (as returned in the in-memory artifact map from the
            protobuf emitter), a Path / str pointing at an
            ``amqp_routing.json`` on disk, or None (emitter synthesises
            an equivalent in-memory config). The synthesised form is
            byte-equivalent to what the protobuf emitter would produce
            for the same chart.
        output_dir: optional disk write target. When provided, every
            emitted file is written under
            ``{output_dir}/network/{chart_id}/<filename>``.

    Returns:
        Mapping ``relative_filename -> file contents``. Filenames carry
        no directory component; they are relative to
        ``build/network/<chart_id>/``.

    Determinism: byte-identical output for byte-identical input. No
    clock reads, no randomness, no env reads.

    Raises:
        AmqpEmitError: chart_sos_id missing; a piece id isn't an SV
            identifier; the chart declares duplicate AMQP events with
            diverging timeout / idempotency.
    """
    if not isinstance(chart_sos_id, str) or not chart_sos_id:
        raise AmqpEmitError(
            f"chart_sos_id must be a non-empty string; got {chart_sos_id!r}"
        )

    # Effective chart-id mirrors the protobuf emitter's derivation.
    effective_chart_id: str
    if chart_id:
        effective_chart_id = chart_id
    else:
        stripped = chart_sos_id.replace("-", "").lower()
        if len(stripped) < 8:
            raise AmqpEmitError(
                f"chart_sos_id {chart_sos_id!r} must be a UUID-shaped "
                f"string with at least 8 hex chars after hyphen-stripping; "
                f"got {stripped!r}"
            )
        effective_chart_id = stripped[:8]

    # Walk every cross-piece AMQP transition.
    events = _build_amqp_events(list(annotations.transitions))

    # Validate piece ids only for pieces actually involved in AMQP
    # transitions.
    participating: set[str] = set()
    for ev in events:
        participating.add(ev.source_piece)
        participating.add(ev.target_piece)
    for pid in sorted(participating):
        _validate_piece_id(pid)

    # Code-gen-time warning for explicitly non-idempotent transitions.
    _maybe_warn_non_idempotent(events)

    # Load (or synthesise) the routing config.
    config = _load_routing_config(
        routing_config, chart_id=effective_chart_id, events=events
    )

    out: dict[str, str] = {}
    for piece in annotations.pieces:
        pid = piece.state_id
        if pid not in participating:
            continue
        outgoing_events = [ev for ev in events if ev.source_piece == pid]
        incoming_events = [ev for ev in events if ev.target_piece == pid]
        outgoing_entries, incoming_entries = _entries_for_piece(config, pid)

        if outgoing_events:
            out[f"{pid}_amqp_producer.rs"] = _render_producer(
                chart_sos_id=chart_sos_id,
                piece_id=pid,
                outgoing_events=outgoing_events,
                outgoing_entries=outgoing_entries,
            )
        if incoming_events:
            out[f"{pid}_amqp_consumer.rs"] = _render_consumer(
                chart_sos_id=chart_sos_id,
                piece_id=pid,
                incoming_events=incoming_events,
                incoming_entries=incoming_entries,
            )
        # Topology is always emitted for any participating piece.
        out[f"{pid}_amqp_topology.rs"] = _render_topology(
            chart_sos_id=chart_sos_id,
            piece_id=pid,
            outgoing_entries=outgoing_entries,
            incoming_entries=incoming_entries,
        )
        out[f"{pid}_amqp_Cargo.toml"] = _render_cargo_toml(
            chart_sos_id=chart_sos_id,
            piece_id=pid,
        )

    if output_dir is not None:
        out_root = Path(output_dir) / "network" / effective_chart_id
        out_root.mkdir(parents=True, exist_ok=True)
        for rel_path, body in out.items():
            target = out_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")

    return out


def emit_amqp_from_chart(
    chart_path: str | Path,
    *,
    chart_sos_id: Optional[str] = None,
    chart_id: Optional[str] = None,
    routing_config: Optional[dict | Path | str] = None,
    output_dir: Optional[Path | str] = None,
) -> dict[str, str]:
    """Convenience wrapper: loader → parser → emitter.

    ``chart_sos_id`` defaults to the root scxml's ``sos:id`` attribute
    when present; raises :class:`AmqpEmitError` when neither is
    supplied.
    """
    from loader import load_chart  # noqa: WPS433 - lazy import

    ast = load_chart(Path(chart_path))
    if ast.raw_scjson is None:
        raise RuntimeError(
            f"loader returned ChartAst without raw_scjson for {chart_path!r}"
        )
    annotations = parse_orchestrator_annotations(ast.raw_scjson)
    sos_id = chart_sos_id or _extract_chart_sos_id(ast.raw_scjson)
    if not sos_id:
        raise AmqpEmitError(
            f"chart {chart_path!r} has no root sos:id and no chart_sos_id "
            f"override supplied; cannot emit deterministic AMQP artifacts "
            f"(INV-S-ORCH-4 + INV-SOS-G)."
        )
    return emit_amqp(
        annotations,
        chart_sos_id=sos_id,
        chart_id=chart_id,
        routing_config=routing_config,
        output_dir=output_dir,
    )


def _extract_chart_sos_id(chart_ast: dict) -> Optional[str]:
    """Pull ``sos:id`` off the root scxml ``other_attributes``.

    Mirrors :func:`protobuf_emit._extract_chart_sos_id`; kept private
    here to avoid creating an import-edge between sibling emitters.
    """
    oa = chart_ast.get("other_attributes")
    if oa is None:
        return None
    raw: Optional[str]
    if isinstance(oa, str):
        raw = oa
    elif isinstance(oa, dict):
        inner = oa.get("other_attributes")
        if isinstance(inner, str):
            raw = inner
        elif isinstance(inner, dict):
            v = inner.get("sos:id")
            return v if isinstance(v, str) else None
        else:
            v = oa.get("sos:id")
            return v if isinstance(v, str) else None
    else:
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    v = parsed.get("sos:id")
    return v if isinstance(v, str) else None


__all__ = [
    "emit_amqp",
    "emit_amqp_from_chart",
    "AmqpEmitError",
    "DEFAULT_AMQP_TIMEOUT_MS",
]

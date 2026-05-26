"""SOS-10 `network` medium protobuf IDL emitter — canonical wire format.

Authority: ``docs/concepts/SOS-10-CONCEPTS.md`` §6.4 (ratified 2026-05-23;
all 8 PCDNs resolved). Per PCDN-SOS-10-002 protobuf IS the canonical
wire-format IDL for the network medium; gRPC services AND AMQP message
bodies BOTH derive from protobuf-encoded schemas (one IDL, two
transports). This module is the load-bearing input for the gRPC stub
emitter and the AMQP message emitter that fan out in the next wave.

Public surface:
    emit_protobuf(annotations, *, chart_sos_id, output_dir=None)
        -> dict[str, str]
    emit_protobuf_from_chart(chart_path, **kwargs) -> dict[str, str]
    ProtobufEmitError                              — ValueError subclass.
    SCALAR_TYPE_MAP                                — protobuf scalar map.

What this module emits
----------------------

For each chart, three artifact families are produced (filenames relative
to ``build/network/<chart_id>/``):

1. **``orchestrator.proto``** — a single proto3 file declaring one
   request / response message pair per cross-piece network transition.
   Per PCDN-SOS-10-002 the SAME ``.proto`` is the source of truth for
   the gRPC service IDL AND the AMQP message body shape.

2. **``<piece_id>_service.proto``** — one per piece. Imports
   ``orchestrator.proto`` and declares a ``service <Piece>Orchestrator``
   with one ``rpc`` per cross-piece event whose ``target_state_id ==
   piece_id``. Pieces receiving no incoming RPCs emit an empty service
   stub with an explanatory comment (still a valid proto3 file).

3. **``amqp_routing.json``** — metadata for the AMQP emitter (wave 17b).
   One entry per ``(source_piece, target_piece)`` pairing carrying any
   AMQP transitions; declares the exchange / queue / routing-keys triad
   the AMQP runtime will install. NOT itself an emitted runtime
   artifact — purely IDL-derived metadata.

Network-only filter
-------------------

Only transitions whose ``medium.kind == "network"`` are walked. The
sibling emitters (``in_process_emit.py``, ``shared_memory_emit.py``,
``mmio_emit.py``) own the other three medium kinds.

Determinism
-----------

- Package name: ``sos_orchestrator_<hex8>`` where ``hex8`` is the
  leading 8 hex chars of the chart's ``sos:id`` (UUID with hyphens
  stripped, lowercased).
- Message-type and RPC ordering: alphabetical by
  ``(src_piece, dst_piece, event_name)``.
- AMQP routing entries: alphabetical by ``(src, dst)``; ``routing_keys``
  within an entry are alphabetical.
- No timestamps, no env, no clock reads. Two emit runs against the same
  ``OrchestratorAnnotations`` produce byte-identical output.

Payload-type mapping
--------------------

The chart MAY carry ``payload_type="<scalar>"`` on the ``<sos:medium>``
element. The SOS-10-A parser preserves the non-``kind`` attribute in
``medium.extras["payload_type"]`` (forward-compat policy). The emitter
maps the chart-declared scalar to the corresponding protobuf type via
:data:`SCALAR_TYPE_MAP`; absent or unknown types fall through to
``bytes`` with a ``TODO`` comment per INV-S-ORCH-4 (wire format derived,
not authored — the chart-author is encouraged to declare an explicit
schema).

@spec citations on every emitted file
-------------------------------------

Each emitted file carries a banner block citing:

- SOS-10-CONCEPTS §6.4 (network medium contract).
- PCDN-SOS-10-002 (protobuf canonical IDL; gRPC+AMQP both derived).
- INV-S-ORCH-1 (one orchestrator per system).
- INV-S-ORCH-4 (wire format derived, not authored).
- INV-SOS-A (every emitted file is a build output).
- The chart's ``sos:id`` UUID.
"""

from __future__ import annotations

import json
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

#: Network is the only medium kind this emitter handles. Sibling emitters
#: own the other three.
_NETWORK_KIND: str = "network"

#: SV-identifier shape — piece ids and event names that don't satisfy
#: this can't safely appear in protobuf identifier positions.
_SV_IDENTIFIER_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

#: Chart payload-type token → protobuf scalar type. The chart-side
#: surface uses the protobuf scalar name verbatim so the mapping is
#: identity for the documented cases; we keep the table explicit so a
#: future chart-side alias (e.g. ``u32 -> uint32``) can be added in one
#: place.
SCALAR_TYPE_MAP: dict[str, str] = {
    "uint32": "uint32",
    "int32": "int32",
    "uint64": "uint64",
    "int64": "int64",
    "float": "float",
    "double": "double",
    "bool": "bool",
    "string": "string",
    "bytes": "bytes",
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProtobufEmitError(ValueError):
    """Raised on malformed inputs to the protobuf emitter.

    Carries the offending transition's source/target/event tokens when
    known, for downstream tooling that wants to surface the chart-author
    error in chart vocabulary (INV-S-ORCH-6 traceability).
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
class _MessagePair:
    """One request/response message pair for a cross-piece network event.

    The pair is rendered as two adjacent ``message`` declarations in the
    canonical ``orchestrator.proto`` file. ``source_piece`` and
    ``target_piece`` drive the message-name shape (``<Src>To<Dst>_<Event>
    _Request`` / ``_Response``); ``transport`` is preserved so the AMQP
    routing emitter can filter by transport.
    """

    source_piece: str
    target_piece: str
    event: str
    payload_proto_type: str
    payload_explicit: bool  # True iff chart declared a scalar; False = default bytes
    transport: str  # "gRPC" or "AMQP"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _network_transitions(
    annotations: OrchestratorAnnotations,
) -> list[CrossPieceTransitionAnnotation]:
    """Return only the cross-piece transitions whose medium is network."""
    return [
        t for t in annotations.transitions
        if t.medium.kind == _NETWORK_KIND
    ]


def _piece_lang_map(annotations: OrchestratorAnnotations) -> dict[str, str]:
    """Map ``piece_id -> lang`` for fast lookup. Currently informational
    only — the protobuf IDL is language-agnostic — but kept symmetric
    with the in-process/shared-memory emitters."""
    return {p.state_id: p.lang for p in annotations.pieces}


def _validate_piece_id(piece_id: str) -> None:
    """Raise if a piece id is not a valid protobuf identifier root."""
    if not _SV_IDENTIFIER_RE.match(piece_id):
        raise ProtobufEmitError(
            f"piece id {piece_id!r} is not an SV identifier; cannot be "
            f"used as a protobuf identifier (message names, service names, "
            f"package suffixes)",
            source=piece_id,
        )


def _extract_chart_sos_id(chart_ast: dict) -> Optional[str]:
    """Pull ``sos:id`` off the root scxml ``other_attributes`` (or None).

    Mirrors the helper in ``in_process_emit.py`` so the chart-id-driven
    deterministic derivation works the same way across emitters.
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


def _short_package_suffix(chart_sos_id: str) -> str:
    """Derive the protobuf package suffix from the chart's sos:id UUID.

    Strip hyphens, lowercase, take the leading 8 hex chars. If the
    resulting string is empty or non-hex, raise. The output is suitable
    as a protobuf-package-name segment (``[a-z0-9]+`` is always a valid
    proto3 identifier root).
    """
    stripped = chart_sos_id.replace("-", "").lower()
    if len(stripped) < 8:
        raise ProtobufEmitError(
            f"chart_sos_id {chart_sos_id!r} must be a UUID-shaped string "
            f"with at least 8 hex chars after hyphen-stripping; got "
            f"{stripped!r}"
        )
    hex8 = stripped[:8]
    if not re.fullmatch(r"[0-9a-f]{8}", hex8):
        raise ProtobufEmitError(
            f"chart_sos_id {chart_sos_id!r} does not yield 8 hex chars at "
            f"its start; got {hex8!r}"
        )
    return hex8


def _proto_message_root(src: str, dst: str, event: str) -> str:
    """Build the canonical message-name root for one cross-piece event.

    Output shape: ``<SrcCamel>To<DstCamel>_<EventToken>`` — protobuf-
    style PascalCase for piece names + a safe SV-identifier event token.
    The full message names append ``_Request`` / ``_Response``.
    """
    return f"{_pascal(src)}To{_pascal(dst)}_{_safe_event_token(event)}"


def _pascal(token: str) -> str:
    """Map a snake_case identifier to PascalCase. Identity for already-
    PascalCase tokens. Treats non-alphanumeric as a word boundary."""
    parts = re.split(r"[^A-Za-z0-9]+", token)
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _safe_event_token(event_name: str) -> str:
    """Map an event name (e.g. ``"audio.start"``) to a protobuf-safe
    identifier token. Replaces every non-``[A-Za-z0-9_]`` with ``_``;
    prepends ``ev_`` when the first char is a digit."""
    safe = re.sub(r"[^A-Za-z0-9_]", "_", event_name)
    if safe and safe[0].isdigit():
        safe = f"ev_{safe}"
    return safe or "ev_unnamed"


def _resolve_payload_type(
    transition: CrossPieceTransitionAnnotation,
) -> tuple[str, bool]:
    """Resolve the protobuf scalar type for a transition's payload.

    Returns ``(proto_type, explicit)`` — ``proto_type`` is the mapped
    protobuf scalar (e.g. ``"uint32"``), and ``explicit`` is True iff
    the chart declared a known scalar. Unknown / absent types fall
    through to ``("bytes", False)`` so the emitter can attach a TODO
    comment to the field.

    The chart-side surface lives in ``medium.extras["payload_type"]``
    per the SOS-10-A parser's forward-compat policy (non-``kind``
    attributes on ``<sos:medium>`` land in ``extras``).
    """
    raw = transition.medium.extras.get("payload_type")
    if raw is None:
        return ("bytes", False)
    if not isinstance(raw, str):
        raise ProtobufEmitError(
            f"payload_type must be a string scalar token; got "
            f"{raw!r} (type={type(raw).__name__})",
            source=transition.source_state_id,
            target=transition.target_state_id,
            event=transition.event,
        )
    mapped = SCALAR_TYPE_MAP.get(raw.strip())
    if mapped is None:
        # Unknown chart-declared scalar — surface as bytes + TODO. Per
        # INV-S-ORCH-4 the chart-author owns the payload schema; the
        # emitter does not invent a type the chart didn't declare.
        return ("bytes", False)
    return (mapped, True)


def _transport_for(transition: CrossPieceTransitionAnnotation) -> str:
    """Return the transport name. Per SOS-10-A parser, network medium
    REQUIRES a ``<sos:transport>`` sub-element; the parser raises on
    omission, so this helper can safely dereference."""
    if transition.medium.transport is None:
        # Belt-and-braces — should already be caught by SOS-10-A parser.
        raise ProtobufEmitError(
            "network-medium transition missing <sos:transport>; SOS-10 §6.4 "
            "+ INV-S-ORCH-3 require an explicit transport",
            source=transition.source_state_id,
            target=transition.target_state_id,
            event=transition.event,
        )
    return transition.medium.transport.name


def _build_message_pairs(
    transitions: list[CrossPieceTransitionAnnotation],
) -> list[_MessagePair]:
    """Construct sorted, deduplicated _MessagePair entries.

    Per the determinism contract, ordering is alphabetical by
    ``(src_piece, dst_piece, event_name)``. Duplicate ``(src, dst,
    event)`` triples are an error — the chart-author cannot declare two
    different transports for the same pairing/event at v1.
    """
    pairs: dict[tuple[str, str, str], _MessagePair] = {}
    for t in transitions:
        key = (t.source_state_id, t.target_state_id, t.event)
        proto_type, explicit = _resolve_payload_type(t)
        transport = _transport_for(t)
        if key in pairs:
            existing = pairs[key]
            if (
                existing.payload_proto_type != proto_type
                or existing.transport != transport
            ):
                raise ProtobufEmitError(
                    f"duplicate cross-piece event with diverging payload "
                    f"or transport: existing="
                    f"({existing.payload_proto_type}, {existing.transport}) "
                    f"new=({proto_type}, {transport})",
                    source=t.source_state_id,
                    target=t.target_state_id,
                    event=t.event,
                )
            continue
        pairs[key] = _MessagePair(
            source_piece=t.source_state_id,
            target_piece=t.target_state_id,
            event=t.event,
            payload_proto_type=proto_type,
            payload_explicit=explicit,
            transport=transport,
        )
    return [pairs[k] for k in sorted(pairs.keys())]


# ---------------------------------------------------------------------------
# @spec banner
# ---------------------------------------------------------------------------


def _spec_banner(chart_sos_id: str) -> str:
    """Return the @spec citation block as a leading proto comment."""
    return (
        "// @spec SOS-10-CONCEPTS §6.4 (network medium contract)\n"
        "// @spec PCDN-SOS-10-002 (protobuf canonical IDL; gRPC + AMQP both derived)\n"
        "// @spec INV-S-ORCH-1 (one orchestrator per system)\n"
        "// @spec INV-S-ORCH-4 (wire format derived, not authored)\n"
        "// @spec INV-SOS-A (every emitted file is a build output)\n"
        f"// @spec chart sos:id {chart_sos_id}\n"
        "// AUTO-GENERATED by sos-codegen/protobuf_emit.py — do not edit.\n"
    )


def _spec_banner_json(chart_sos_id: str) -> dict[str, object]:
    """JSON-shaped @spec banner for amqp_routing.json (no comments in
    canonical JSON; surface the citation block as a top-level ``_spec``
    key the AMQP emitter can read and round-trip)."""
    return {
        "_spec": {
            "section": "SOS-10-CONCEPTS §6.4 (network medium contract)",
            "pcdn": "PCDN-SOS-10-002 (protobuf canonical IDL)",
            "invariants": [
                "INV-S-ORCH-1",
                "INV-S-ORCH-4",
                "INV-SOS-A",
            ],
            "chart_sos_id": chart_sos_id,
            "generator": "tools/sos-codegen/protobuf_emit.py",
            "note": "AUTO-GENERATED — do not edit.",
        }
    }


# ---------------------------------------------------------------------------
# Rendering — orchestrator.proto
# ---------------------------------------------------------------------------


def _render_orchestrator_proto(
    *,
    chart_sos_id: str,
    package_suffix: str,
    pairs: list[_MessagePair],
) -> str:
    """Render the canonical ``orchestrator.proto`` file.

    Layout:
        @spec banner
        syntax = "proto3";
        package sos_orchestrator_<hex8>;
        import "google/protobuf/empty.proto";

        // message pairs in alphabetical order
        message <Src>To<Dst>_<Event>_Request {
            <proto_type> payload = 1;
        }
        message <Src>To<Dst>_<Event>_Response {
            // For v1 every cross-piece RPC returns Empty by default
            // (chart-author opts in to a richer response by adding a
            // future <sos:response payload_type="..."/> annotation —
            // tracked as SOS-10 §14 unblock).
        }
    """
    lines: list[str] = []
    lines.append(_spec_banner(chart_sos_id))
    lines.append('syntax = "proto3";\n\n')
    lines.append(f"package sos_orchestrator_{package_suffix};\n\n")
    lines.append('import "google/protobuf/empty.proto";\n\n')
    if not pairs:
        lines.append(
            "// No cross-piece network transitions in this chart; this "
            "file is emitted as a build output sentinel (INV-SOS-A).\n"
        )
        return "".join(lines)
    for pair in pairs:
        root = _proto_message_root(pair.source_piece, pair.target_piece, pair.event)
        # Request message.
        lines.append(
            f"// Cross-piece event `{pair.event}`: "
            f"{pair.source_piece} -> {pair.target_piece} "
            f"({pair.transport}).\n"
        )
        lines.append(f"message {root}_Request {{\n")
        if pair.payload_explicit:
            lines.append(
                f"    {pair.payload_proto_type} payload = 1;\n"
            )
        else:
            lines.append(
                "    // TODO(SOS-10-payload-type): chart did not declare a "
                "`payload_type` attribute on <sos:medium>; defaulting to "
                "`bytes` per INV-S-ORCH-4 (wire format derived, not "
                "authored — chart-author owns the payload schema).\n"
            )
            lines.append(f"    {pair.payload_proto_type} payload = 1;\n")
        lines.append("}\n\n")
        # Response message — Empty by default at v1.
        lines.append(
            f"// Response for `{pair.event}` — v1 default is "
            "`google.protobuf.Empty` (no semantic payload). Chart-author "
            "may declare a richer response in a future SOS-10 sub-phase.\n"
        )
        lines.append(
            f"message {root}_Response {{\n"
            "    // Wraps google.protobuf.Empty by reference; emitted as\n"
            "    // a named message so the gRPC stub emitter can pin the\n"
            "    // response type without an inline Empty.\n"
            "    google.protobuf.Empty empty = 1;\n"
            "}\n\n"
        )
    return "".join(lines)


# ---------------------------------------------------------------------------
# Rendering — per-piece service .proto
# ---------------------------------------------------------------------------


def _render_piece_service_proto(
    *,
    chart_sos_id: str,
    package_suffix: str,
    piece_id: str,
    incoming_pairs: list[_MessagePair],
) -> str:
    """Render ``<piece_id>_service.proto`` for one piece.

    Layout:
        @spec banner
        syntax = "proto3";
        package sos_orchestrator_<hex8>;
        import "orchestrator.proto";

        service <Piece>Orchestrator {
            rpc <Event>(<Req>) returns (<Resp>);
            ...
        }

    A piece with no incoming network RPCs emits an empty service stub
    with a ``// no incoming RPCs`` comment (still a valid proto3 file).
    """
    lines: list[str] = []
    lines.append(_spec_banner(chart_sos_id))
    lines.append('syntax = "proto3";\n\n')
    lines.append(f"package sos_orchestrator_{package_suffix};\n\n")
    lines.append('import "orchestrator.proto";\n\n')
    service_name = f"{_pascal(piece_id)}Orchestrator"
    lines.append(
        f"// Per-piece orchestrator service for `{piece_id}`. Each rpc "
        f"corresponds to one cross-piece event whose target_state_id == "
        f"`{piece_id}` (i.e. events INCOMING to this piece). Per "
        f"PCDN-SOS-10-002 the same message types feed the AMQP emitter "
        f"(wave 17b) — one IDL, two transports.\n"
    )
    lines.append(f"service {service_name} {{\n")
    if not incoming_pairs:
        lines.append(
            "    // no incoming RPCs — this piece is a pure event source "
            "or a non-network target; service stub emitted as a build "
            "output sentinel per INV-SOS-A.\n"
        )
    else:
        for pair in incoming_pairs:
            root = _proto_message_root(
                pair.source_piece, pair.target_piece, pair.event
            )
            rpc_name = f"{_pascal(pair.source_piece)}_{_safe_event_token(pair.event)}"
            lines.append(
                f"    // From `{pair.source_piece}` over {pair.transport}.\n"
            )
            lines.append(
                f"    rpc {rpc_name}({root}_Request) "
                f"returns ({root}_Response);\n"
            )
    lines.append("}\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Rendering — amqp_routing.json
# ---------------------------------------------------------------------------


def _render_amqp_routing_json(
    *,
    chart_id: str,
    chart_sos_id: str,
    pairs: list[_MessagePair],
) -> str:
    """Render the per-pairing AMQP routing metadata.

    Schema:
        {
            "_spec": { ... },
            "entries": [
                {
                    "source_piece": "<src>",
                    "target_piece": "<dst>",
                    "exchange":     "<chart_id>.<src>",
                    "queue":        "<chart_id>.<dst>",
                    "routing_keys": ["<event_name>", ...]
                },
                ...
            ]
        }

    One entry per ``(src, dst)`` pairing carrying AMQP transitions.
    Entries are alphabetical by ``(src, dst)``; routing-keys within an
    entry are alphabetical. Pairings that carry only gRPC transitions
    are SKIPPED (gRPC emitter handles them, not AMQP).
    """
    grouped: dict[tuple[str, str], list[str]] = {}
    for pair in pairs:
        if pair.transport != "AMQP":
            continue
        key = (pair.source_piece, pair.target_piece)
        grouped.setdefault(key, []).append(pair.event)

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

    payload: dict[str, object] = _spec_banner_json(chart_sos_id)
    payload["chart_id"] = chart_id
    payload["entries"] = entries
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def emit_protobuf(
    annotations: OrchestratorAnnotations,
    *,
    chart_sos_id: str,
    chart_id: Optional[str] = None,
    output_dir: Optional[Path | str] = None,
) -> dict[str, str]:
    """Emit protobuf IDL artifacts for every network-medium pairing.

    Args:
        annotations: parsed SOS-10 orchestrator annotations.
        chart_sos_id: the orchestrator chart's ``sos:id`` UUID. Drives
            the deterministic protobuf package suffix
            (``sos_orchestrator_<hex8>``).
        chart_id: chart-level identifier used for the AMQP routing
            exchange / queue naming and (when ``output_dir`` is set) the
            sub-directory under ``build/network/``. Defaults to the
            leading-8 hex of ``chart_sos_id`` when omitted.
        output_dir: optional disk write target. When provided, every
            emitted file is written under
            ``{output_dir}/network/{chart_id}/<filename>``; when None,
            the function is pure (returns the file map only).

    Returns:
        Mapping ``relative_filename -> file contents`` for every emitted
        artifact (orchestrator.proto + per-piece *_service.proto +
        amqp_routing.json). Filenames carry no directory component; they
        are relative to ``build/network/<chart_id>/``.

    Determinism: byte-identical output for byte-identical input. No
    randomness, no clock reads. Two runs over the same annotations
    produce identical bytes.

    Raises:
        ProtobufEmitError: chart_sos_id is malformed; a piece id isn't
            an SV identifier; the chart carries duplicate cross-piece
            events with diverging payload/transport declarations.
    """
    if not isinstance(chart_sos_id, str) or not chart_sos_id:
        raise ProtobufEmitError(
            f"chart_sos_id must be a non-empty string; got {chart_sos_id!r}"
        )

    package_suffix = _short_package_suffix(chart_sos_id)
    effective_chart_id = chart_id if chart_id else package_suffix

    transitions = _network_transitions(annotations)
    # Validate piece ids only for pieces actually participating in
    # network transitions. Non-network pieces remain the siblings'
    # concern.
    participating: set[str] = set()
    for t in transitions:
        participating.add(t.source_state_id)
        participating.add(t.target_state_id)
    for pid in sorted(participating):
        _validate_piece_id(pid)

    pairs = _build_message_pairs(transitions)

    out: dict[str, str] = {}

    # 1. Canonical orchestrator.proto — one file per chart, always
    # emitted (even when the chart has zero network transitions, so the
    # gRPC + AMQP emitters can read a stable artifact path).
    out["orchestrator.proto"] = _render_orchestrator_proto(
        chart_sos_id=chart_sos_id,
        package_suffix=package_suffix,
        pairs=pairs,
    )

    # 2. Per-piece service .proto — one per participating piece. Walk
    # the chart's pieces in document order so the filename set is
    # stable; only emit for pieces touching the network medium (sibling
    # emitters handle the others).
    for piece in annotations.pieces:
        pid = piece.state_id
        if pid not in participating:
            continue
        incoming = [p for p in pairs if p.target_piece == pid]
        # `incoming` is already sorted because `pairs` is sorted by
        # (src, dst, event).
        out[f"{pid}_service.proto"] = _render_piece_service_proto(
            chart_sos_id=chart_sos_id,
            package_suffix=package_suffix,
            piece_id=pid,
            incoming_pairs=incoming,
        )

    # 3. AMQP routing metadata — one JSON per chart. Always emitted so
    # the AMQP runtime emitter (wave 17b) can read a stable artifact
    # path; an empty `entries` list is a valid "no AMQP transitions in
    # this chart" sentinel.
    out["amqp_routing.json"] = _render_amqp_routing_json(
        chart_id=effective_chart_id,
        chart_sos_id=chart_sos_id,
        pairs=pairs,
    )

    if output_dir is not None:
        out_root = Path(output_dir) / "network" / effective_chart_id
        out_root.mkdir(parents=True, exist_ok=True)
        for rel_path, body in out.items():
            target = out_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")

    return out


def emit_protobuf_from_chart(
    chart_path: str | Path,
    *,
    chart_sos_id: Optional[str] = None,
    chart_id: Optional[str] = None,
    output_dir: Optional[Path | str] = None,
) -> dict[str, str]:
    """Convenience wrapper: loader → parser → emitter.

    ``chart_sos_id`` defaults to the root scxml's ``sos:id`` attribute
    when present; raises :class:`ProtobufEmitError` when neither is
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
        raise ProtobufEmitError(
            f"chart {chart_path!r} has no root sos:id and no chart_sos_id "
            f"override supplied; cannot derive deterministic protobuf "
            f"package name (INV-S-ORCH-4 + INV-SOS-G)."
        )
    return emit_protobuf(
        annotations,
        chart_sos_id=sos_id,
        chart_id=chart_id,
        output_dir=output_dir,
    )


__all__ = [
    "emit_protobuf",
    "emit_protobuf_from_chart",
    "ProtobufEmitError",
    "SCALAR_TYPE_MAP",
]

"""SOS-10 gRPC service-stub emitter — Rust (tonic) server + client.

Authority: ``docs/concepts/SOS-10-CONCEPTS.md`` §6.4 (network medium contract;
ratified 2026-05-23). Per PCDN-SOS-10-002 the gRPC service IDL DERIVES from
the canonical protobuf IDL emitted by ``protobuf_emit.py``; this module
authors NO wire vocabulary of its own — every name on the wire round-trips a
protobuf identifier produced by the sibling protobuf emitter. Per
PCDN-SOS-10-001 the v1 emitted piece language is Rust (tonic + tokio).
Per PCDN-SOS-10-005 the per-transition ``sos:idempotent`` attribute drives a
SAFETY comment block on the client stub; per PCDN-SOS-10-006 the
gRPC-medium default per-request timeout is 5000 ms, overridable via the
chart-author's ``<sos:timeout ms="..."/>`` sub-element.

Public surface:
    emit_grpc(annotations, *, chart_sos_id, output_dir=None) -> dict[str, str]
    emit_grpc_from_chart(chart_path, **kwargs) -> dict[str, str]
    GrpcEmitError                                  — ValueError subclass.

What this module emits
----------------------

For each piece P that participates in at least one gRPC-medium cross-piece
transition, the following Rust artifacts are emitted under
``build/network/<chart_id>/``:

1. ``<piece_id>_grpc_server.rs`` — emitted iff P is the TARGET of at least
   one gRPC transition.
    - ``pub mod proto { tonic::include_proto!("<package_name>"); }``.
    - ``pub struct <PieceName>OrchestratorImpl { /* user state */ }``.
    - ``#[tonic::async_trait]`` impl of the tonic-generated trait, with one
      ``async fn <event_name>(&self, ...) -> Result<Response<_>, Status>``
      stub per INCOMING event. Body: ``Err(Status::unimplemented(...))``.
    - ``pub async fn serve(addr: SocketAddr, impl_: ...) -> Result<...>``
      ``tonic::transport::Server`` boilerplate.

2. ``<piece_id>_grpc_client.rs`` — emitted iff P is the SOURCE of at least
   one gRPC transition.
    - One ``pub async fn send_<event_name>(client: &mut <Dst>OrchestratorClient<Channel>, req: ...)``
      per OUTGOING gRPC event.
    - Timeout = ``std::time::Duration::from_millis(<ms>)`` where ``<ms>`` is
      ``transport.timeout_ms`` if set, else ``medium.timeout`` if set,
      else the PCDN-SOS-10-006 gRPC default of 5000.
    - When the transition's ``idempotent`` (transition-level override) and
      ``medium.idempotent`` are BOTH not True, emit a SAFETY comment
      flagging that retry policy is the caller's responsibility.

3. ``<piece_id>_grpc_Cargo.toml`` — workspace-shape Cargo.toml SEED listing
   tonic / prost / tokio / serde + a ``[build-dependencies]`` block with
   tonic-build. NOT a complete crate; chart authors integrate into their
   own workspace.

4. ``<piece_id>_grpc_build.rs`` — ``build.rs`` SEED calling
   ``tonic_build::compile_protos`` against the two .proto files the
   protobuf emitter produced (``orchestrator.proto`` + ``<piece>_service.proto``).

Filter rule
-----------

This emitter consumes the SAME annotation surface as the protobuf and AMQP
emitters but emits ONLY for gRPC. Specifically:

- ``medium.kind != "network"`` transitions are SKIPPED silently (sibling
  emitters in §6.1/§6.2/§6.3 own those).
- ``medium.transport.name == "AMQP"`` transitions are SKIPPED silently (the
  AMQP emitter, wave-17c, handles those).
- Only ``kind=="network"`` + ``transport.name=="gRPC"`` produce output.

Determinism
-----------

- Service trait method order: alphabetical by event name within each piece.
- Cargo.toml dependency order: alphabetical by crate name.
- Output filename set is a deterministic function of the participating
  pieces (sorted by document order, walked once per piece role).
- Two emit runs over the same annotations produce byte-identical output.

@spec citations
---------------

Every emitted Rust file carries a leading ``//`` banner citing:
- SOS-10-CONCEPTS §6.4 (network medium contract).
- PCDN-SOS-10-001 (Rust at v1).
- PCDN-SOS-10-002 (protobuf canonical IDL; gRPC derived).
- PCDN-SOS-10-005 (per-transition idempotency override).
- PCDN-SOS-10-006 (timeout defaults — gRPC = 5000 ms).
- INV-S-ORCH-1 (one orchestrator per system).
- INV-S-ORCH-4 (wire format derived, not authored).
- INV-SOS-A (every emitted file is a build output).
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

#: Network is the only medium kind this emitter inspects.
_NETWORK_KIND: str = "network"

#: gRPC is the only transport this emitter emits for.
_GRPC_TRANSPORT: str = "gRPC"

#: Per PCDN-SOS-10-006 (ratified 2026-05-23): default gRPC request timeout
#: is 5000 ms when neither the transport nor the medium declares one.
_GRPC_DEFAULT_TIMEOUT_MS: int = 5000

#: SV-identifier shape — piece ids and event names that don't satisfy this
#: can't safely appear in Rust identifier positions. Mirrors the rule used
#: by ``protobuf_emit.py`` so a chart that passes the protobuf emitter
#: passes this emitter too.
_SV_IDENTIFIER_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

#: Crate dependencies declared on the seed Cargo.toml. Alphabetical by
#: crate name so the rendered output is deterministic. Per the SOS-10-A
#: requirement that emitter output is "wire-format derived, not authored",
#: these versions are loose upper-bound pins — chart authors integrating
#: into a real workspace pin to their workspace's resolver.
_CARGO_RUNTIME_DEPS: list[tuple[str, str, Optional[str]]] = [
    # (crate_name, version_spec, features-csv-or-None)
    ("prost", "0.13", None),
    ("serde", "1", "derive"),
    ("tokio", "1", "macros,rt-multi-thread,net"),
    ("tonic", "0.12", None),
]

_CARGO_BUILD_DEPS: list[tuple[str, str, Optional[str]]] = [
    ("tonic-build", "0.12", None),
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GrpcEmitError(ValueError):
    """Raised on malformed inputs to the gRPC emitter."""

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
class _GrpcEdge:
    """One (source -> target, event) gRPC cross-piece edge.

    ``timeout_ms`` is resolved at construction (transport > medium > default).
    ``idempotent_resolved`` is True iff EITHER the transition-level override
    OR the medium-level child element resolved to True (per
    PCDN-SOS-10-005). Otherwise False — and the client stub then carries the
    "retry policy is caller's responsibility" SAFETY block.
    """

    source_piece: str
    target_piece: str
    event: str
    timeout_ms: int
    idempotent_resolved: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _grpc_transitions(
    annotations: OrchestratorAnnotations,
) -> list[CrossPieceTransitionAnnotation]:
    """Filter to ``network`` + ``transport.name == "gRPC"`` transitions only.

    Per the filter rule: ``kind != "network"`` and ``transport.name == "AMQP"``
    are SKIPPED silently — siblings own them.
    """
    out: list[CrossPieceTransitionAnnotation] = []
    for t in annotations.transitions:
        if t.medium.kind != _NETWORK_KIND:
            continue
        if t.medium.transport is None:
            # Belt-and-braces: SOS-10-A parser enforces transport on
            # network-medium transitions, but if it ever surfaces None we
            # silently skip (defensive — sibling-emitter scope).
            continue
        if t.medium.transport.name != _GRPC_TRANSPORT:
            continue
        out.append(t)
    return out


def _validate_piece_id(piece_id: str) -> None:
    """Raise if a piece id is not a valid Rust identifier root."""
    if not _SV_IDENTIFIER_RE.match(piece_id):
        raise GrpcEmitError(
            f"piece id {piece_id!r} is not an SV identifier; cannot be "
            f"used as a Rust identifier root (struct names, mod names, "
            f"function names)",
            source=piece_id,
        )


def _extract_chart_sos_id(chart_ast: dict) -> Optional[str]:
    """Pull ``sos:id`` off the root scxml ``other_attributes`` (or None).

    Mirrors the helper in ``protobuf_emit.py`` so the chart-id-driven
    deterministic package suffix matches across emitters.
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
    """Derive the ``sos_orchestrator_<hex8>`` package suffix.

    Mirrors ``protobuf_emit._short_package_suffix`` so the gRPC stubs
    reference the same package name the protobuf emitter declared.
    """
    stripped = chart_sos_id.replace("-", "").lower()
    if len(stripped) < 8:
        raise GrpcEmitError(
            f"chart_sos_id {chart_sos_id!r} must be a UUID-shaped string "
            f"with at least 8 hex chars after hyphen-stripping; got "
            f"{stripped!r}"
        )
    hex8 = stripped[:8]
    if not re.fullmatch(r"[0-9a-f]{8}", hex8):
        raise GrpcEmitError(
            f"chart_sos_id {chart_sos_id!r} does not yield 8 hex chars at "
            f"its start; got {hex8!r}"
        )
    return hex8


def _pascal(token: str) -> str:
    """snake_case → PascalCase. Mirrors ``protobuf_emit._pascal``."""
    parts = re.split(r"[^A-Za-z0-9]+", token)
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _safe_event_token(event_name: str) -> str:
    """Map an event name to a Rust-safe identifier token. Mirrors the
    protobuf emitter so the rpc method names line up."""
    safe = re.sub(r"[^A-Za-z0-9_]", "_", event_name)
    if safe and safe[0].isdigit():
        safe = f"ev_{safe}"
    return safe or "ev_unnamed"


def _resolve_timeout_ms(t: CrossPieceTransitionAnnotation) -> int:
    """Per PCDN-SOS-10-006: transport-level > medium-level > 5000ms default."""
    if t.medium.transport is not None and t.medium.transport.timeout_ms is not None:
        return t.medium.transport.timeout_ms
    if t.medium.timeout is not None:
        return t.medium.timeout
    return _GRPC_DEFAULT_TIMEOUT_MS


def _resolve_idempotent(t: CrossPieceTransitionAnnotation) -> bool:
    """Per PCDN-SOS-10-005: True iff either the transition-level override
    or the medium-level child element resolved to True; default False (so
    the SAFETY comment fires by default — chart-author opts INTO retry
    safety, not out of it)."""
    if t.idempotent is True:
        return True
    if t.medium.idempotent is True:
        return True
    return False


def _build_edges(
    transitions: list[CrossPieceTransitionAnnotation],
) -> list[_GrpcEdge]:
    """Build sorted, deduplicated _GrpcEdge entries (alphabetical by
    ``(src, dst, event)``).

    Duplicate ``(src, dst, event)`` triples with diverging timeout or
    idempotent declarations raise — the chart-author cannot declare two
    different stub specs for the same edge at v1.
    """
    edges: dict[tuple[str, str, str], _GrpcEdge] = {}
    for t in transitions:
        key = (t.source_state_id, t.target_state_id, t.event)
        timeout_ms = _resolve_timeout_ms(t)
        idempotent = _resolve_idempotent(t)
        if key in edges:
            existing = edges[key]
            if (
                existing.timeout_ms != timeout_ms
                or existing.idempotent_resolved != idempotent
            ):
                raise GrpcEmitError(
                    f"duplicate gRPC cross-piece event with diverging "
                    f"timeout/idempotent: existing=("
                    f"{existing.timeout_ms}ms, idem={existing.idempotent_resolved}) "
                    f"new=({timeout_ms}ms, idem={idempotent})",
                    source=t.source_state_id,
                    target=t.target_state_id,
                    event=t.event,
                )
            continue
        edges[key] = _GrpcEdge(
            source_piece=t.source_state_id,
            target_piece=t.target_state_id,
            event=t.event,
            timeout_ms=timeout_ms,
            idempotent_resolved=idempotent,
        )
    return [edges[k] for k in sorted(edges.keys())]


# ---------------------------------------------------------------------------
# @spec banner
# ---------------------------------------------------------------------------


def _spec_banner(chart_sos_id: str) -> str:
    """Return the @spec citation block as leading Rust line comments."""
    return (
        "// @spec SOS-10-CONCEPTS §6.4 (network medium contract)\n"
        "// @spec PCDN-SOS-10-001 (Rust at v1)\n"
        "// @spec PCDN-SOS-10-002 (protobuf canonical IDL; gRPC derived)\n"
        "// @spec PCDN-SOS-10-005 (per-transition idempotency override)\n"
        "// @spec PCDN-SOS-10-006 (timeout defaults — gRPC = 5000ms)\n"
        "// @spec INV-S-ORCH-1 (one orchestrator per system)\n"
        "// @spec INV-S-ORCH-4 (wire format derived, not authored)\n"
        "// @spec INV-SOS-A (every emitted file is a build output)\n"
        f"// @spec chart sos:id {chart_sos_id}\n"
        "// AUTO-GENERATED by sos-codegen/grpc_emit.py — do not edit.\n"
    )


def _spec_banner_toml(chart_sos_id: str) -> str:
    """TOML-comment variant for the Cargo.toml seed."""
    return (
        "# @spec SOS-10-CONCEPTS §6.4 (network medium contract)\n"
        "# @spec PCDN-SOS-10-001 (Rust at v1)\n"
        "# @spec PCDN-SOS-10-002 (protobuf canonical IDL; gRPC derived)\n"
        "# @spec PCDN-SOS-10-005 (per-transition idempotency override)\n"
        "# @spec PCDN-SOS-10-006 (timeout defaults — gRPC = 5000ms)\n"
        "# @spec INV-S-ORCH-1 (one orchestrator per system)\n"
        "# @spec INV-S-ORCH-4 (wire format derived, not authored)\n"
        "# @spec INV-SOS-A (every emitted file is a build output)\n"
        f"# @spec chart sos:id {chart_sos_id}\n"
        "# AUTO-GENERATED by sos-codegen/grpc_emit.py — do not edit.\n"
    )


# ---------------------------------------------------------------------------
# Rendering — server stub
# ---------------------------------------------------------------------------


def _render_server_stub(
    *,
    chart_sos_id: str,
    package_name: str,
    piece_id: str,
    incoming_edges: list[_GrpcEdge],
) -> str:
    """Render ``<piece_id>_grpc_server.rs``.

    ``incoming_edges`` is already sorted alphabetically by event. We
    re-sort by event-name here for the server-trait method ordering, since
    multiple sources can target the same piece and the determinism contract
    is alphabetical by event NAME within each service trait.
    """
    piece_pascal = _pascal(piece_id)
    trait_module = f"{piece_id}_orchestrator_server"
    trait_name = f"{piece_pascal}Orchestrator"
    impl_name = f"{piece_pascal}OrchestratorImpl"

    # Sort by event name for the trait method ordering; ties broken by
    # source piece (stable across repeated event names from different
    # sources).
    server_edges = sorted(
        incoming_edges, key=lambda e: (e.event, e.source_piece)
    )

    lines: list[str] = []
    lines.append(_spec_banner(chart_sos_id))
    lines.append(f"// gRPC server stub for piece `{piece_id}`.\n")
    lines.append(
        f"// Generated from {len(server_edges)} incoming gRPC cross-piece "
        f"transition(s).\n\n"
    )
    lines.append("#![allow(dead_code)]\n")
    lines.append("#![allow(unused_imports)]\n")
    lines.append("#![allow(clippy::needless_lifetimes)]\n\n")

    lines.append("use std::net::SocketAddr;\n")
    lines.append("use tonic::{Request, Response, Status};\n")
    lines.append("use tonic::transport::Server;\n\n")

    lines.append(
        "/// Protobuf-derived types from the canonical IDL emitter "
        "(see PCDN-SOS-10-002).\n"
    )
    lines.append("pub mod proto {\n")
    lines.append(f"    tonic::include_proto!(\"{package_name}\");\n")
    lines.append("}\n\n")

    lines.append(
        f"/// User-extensible orchestrator-piece state for `{piece_id}`.\n"
    )
    lines.append(
        "/// The chart-author owns this struct's body; the emitter only "
        "guarantees the\n"
    )
    lines.append(
        "/// outer name + impl block per PCDN-SOS-10-001 (Rust v1) and "
        "INV-S-ORCH-4.\n"
    )
    lines.append("#[derive(Default)]\n")
    lines.append(f"pub struct {impl_name} {{\n")
    lines.append("    // chart-author extends with piece-local state here.\n")
    lines.append("}\n\n")

    lines.append("#[tonic::async_trait]\n")
    lines.append(
        f"impl proto::{trait_module}::{trait_name} for {impl_name} {{\n"
    )

    if not server_edges:
        lines.append(
            "    // no incoming gRPC events — empty impl block (still a "
            "valid trait impl).\n"
        )
    else:
        for edge in server_edges:
            method = f"{_pascal(edge.source_piece)}_{_safe_event_token(edge.event)}".lower()
            # Tonic's prost-derived method names are snake-cased rpc names.
            # Our rpc names are `<SrcPascal>_<event_token>` per
            # protobuf_emit.py, which protobuf-rs lower-snakes to
            # `<src_lower>_<event_token_lower>`. We compute that here.
            rpc_root = _pascal_to_snake(
                f"{_pascal(edge.source_piece)}_{_safe_event_token(edge.event)}"
            )
            # The Request/Response Rust types are PascalCase of the
            # protobuf message names. The protobuf emitter names them
            # ``<Src>To<Dst>_<event>_Request`` etc.; prost generates Rust
            # names by replacing non-alphanumerics with `_` and applying
            # PascalCase. Our names already satisfy that shape.
            req_type = (
                f"{_pascal(edge.source_piece)}To{_pascal(edge.target_piece)}"
                f"_{_safe_event_token(edge.event)}_Request"
            )
            resp_type = (
                f"{_pascal(edge.source_piece)}To{_pascal(edge.target_piece)}"
                f"_{_safe_event_token(edge.event)}_Response"
            )
            lines.append(
                f"    /// Handler for `{edge.event}` from "
                f"`{edge.source_piece}` (gRPC).\n"
            )
            lines.append(
                f"    async fn {rpc_root}(\n"
                f"        &self,\n"
                f"        _request: Request<proto::{req_type}>,\n"
                f"    ) -> Result<Response<proto::{resp_type}>, Status> {{\n"
                f"        Err(Status::unimplemented(\n"
                f"            \"{edge.event} not yet wired (piece "
                f"`{piece_id}` server stub)\".to_string(),\n"
                f"        ))\n"
                f"    }}\n\n"
            )
    lines.append("}\n\n")

    # serve() helper.
    lines.append(
        "/// Boilerplate gRPC server: bind `addr`, install the user-\n"
    )
    lines.append(
        "/// extended impl, serve until the OS signals shutdown. Chart-\n"
    )
    lines.append(
        "/// author MAY wrap this with `tokio::select!` for graceful\n"
    )
    lines.append("/// shutdown semantics.\n")
    lines.append(
        f"pub async fn serve(\n"
        f"    addr: SocketAddr,\n"
        f"    impl_: {impl_name},\n"
        f") -> Result<(), Box<dyn std::error::Error + Send + Sync>> {{\n"
    )
    lines.append("    Server::builder()\n")
    lines.append(
        f"        .add_service(proto::{trait_module}::"
        f"{trait_name}Server::new(impl_))\n"
    )
    lines.append("        .serve(addr)\n")
    lines.append("        .await?;\n")
    lines.append("    Ok(())\n")
    lines.append("}\n")
    return "".join(lines)


def _pascal_to_snake(token: str) -> str:
    """PascalCase / mixedCase → snake_case. Mirrors prost's rpc-method
    rename rule (lower-snake) so server `impl` method names line up with
    the generated trait."""
    # Insert `_` before every uppercase letter that follows a lowercase
    # letter or digit; collapse consecutive non-alphanumerics to `_`.
    step1 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", token)
    step2 = re.sub(r"[^A-Za-z0-9]+", "_", step1)
    return step2.lower().strip("_")


# ---------------------------------------------------------------------------
# Rendering — client stub
# ---------------------------------------------------------------------------


def _render_client_stub(
    *,
    chart_sos_id: str,
    package_name: str,
    piece_id: str,
    outgoing_edges: list[_GrpcEdge],
) -> str:
    """Render ``<piece_id>_grpc_client.rs``."""
    # Sort outgoing edges alphabetically by event name; ties broken by
    # target piece (different events to different pieces stay deterministic).
    client_edges = sorted(
        outgoing_edges, key=lambda e: (e.event, e.target_piece)
    )

    lines: list[str] = []
    lines.append(_spec_banner(chart_sos_id))
    lines.append(f"// gRPC client stub for piece `{piece_id}`.\n")
    lines.append(
        f"// Generated from {len(client_edges)} outgoing gRPC cross-piece "
        f"transition(s).\n\n"
    )
    lines.append("#![allow(dead_code)]\n")
    lines.append("#![allow(unused_imports)]\n\n")

    lines.append("use tonic::Status;\n")
    lines.append("use tonic::transport::Channel;\n")
    lines.append("use tonic::Request;\n\n")

    lines.append(
        "/// Protobuf-derived types from the canonical IDL emitter "
        "(see PCDN-SOS-10-002).\n"
    )
    lines.append("pub mod proto {\n")
    lines.append(f"    tonic::include_proto!(\"{package_name}\");\n")
    lines.append("}\n\n")

    if not client_edges:
        # Shouldn't happen because the caller only invokes us when there
        # are outgoing edges, but keep the file shape stable just in case.
        lines.append(
            "// No outgoing gRPC events for this piece — empty client "
            "stub.\n"
        )
        return "".join(lines)

    # Pre-resolve the per-event ClientStub type alias names, grouped by
    # target piece, so a single client struct of the right shape is named
    # exactly once. The protobuf emitter names the tonic-generated client
    # ``<Piece>OrchestratorClient`` under the
    # ``proto::<piece>_orchestrator_client`` module.
    for edge in client_edges:
        dst_pascal = _pascal(edge.target_piece)
        dst_client_mod = f"{edge.target_piece}_orchestrator_client"
        dst_client_type = f"proto::{dst_client_mod}::{dst_pascal}OrchestratorClient<Channel>"
        req_type = (
            f"proto::{_pascal(edge.source_piece)}To{_pascal(edge.target_piece)}"
            f"_{_safe_event_token(edge.event)}_Request"
        )
        resp_type = (
            f"proto::{_pascal(edge.source_piece)}To{_pascal(edge.target_piece)}"
            f"_{_safe_event_token(edge.event)}_Response"
        )
        fn_name = f"send_{_safe_event_token(edge.event)}"
        # Server-side rpc method name (prost lower-snakes its rpc names).
        rpc_method = _pascal_to_snake(
            f"{_pascal(edge.source_piece)}_{_safe_event_token(edge.event)}"
        )

        # SAFETY block for non-idempotent calls (PCDN-SOS-10-005).
        if not edge.idempotent_resolved:
            lines.append(
                "// SAFETY: this RPC is NOT marked idempotent; retry "
                "policy is\n"
            )
            lines.append(
                "// the caller's responsibility per PCDN-SOS-10-005 (chart-\n"
            )
            lines.append(
                "// author opts INTO retry safety by setting\n"
            )
            lines.append(
                "// `<transition sos:idempotent=\"true\">`).\n"
            )
        else:
            lines.append(
                "// This RPC is marked idempotent (PCDN-SOS-10-005) — "
                "callers MAY retry.\n"
            )

        lines.append(
            f"/// Send `{edge.event}` from `{edge.source_piece}` to "
            f"`{edge.target_piece}` (gRPC).\n"
        )
        lines.append(
            f"/// Per-request timeout: {edge.timeout_ms} ms "
            f"(PCDN-SOS-10-006).\n"
        )
        lines.append(
            f"pub async fn {fn_name}(\n"
            f"    client: &mut {dst_client_type},\n"
            f"    req: {req_type},\n"
            f") -> Result<{resp_type}, Status> {{\n"
        )
        lines.append(
            "    let mut request = Request::new(req);\n"
        )
        lines.append(
            f"    request.set_timeout(std::time::Duration::from_millis("
            f"{edge.timeout_ms}));\n"
        )
        lines.append(
            f"    let response = client.{rpc_method}(request).await?;\n"
        )
        lines.append("    Ok(response.into_inner())\n")
        lines.append("}\n\n")

    return "".join(lines)


# ---------------------------------------------------------------------------
# Rendering — Cargo.toml seed
# ---------------------------------------------------------------------------


def _render_cargo_toml(
    *,
    chart_sos_id: str,
    piece_id: str,
) -> str:
    """Render the ``<piece_id>_grpc_Cargo.toml`` seed."""
    lines: list[str] = []
    lines.append(_spec_banner_toml(chart_sos_id))
    lines.append("\n")
    lines.append("[package]\n")
    lines.append(f'name = "{piece_id}_grpc_stub"\n')
    lines.append('version = "0.1.0"\n')
    lines.append('edition = "2021"\n')
    lines.append('publish = false\n')
    lines.append("\n")
    lines.append("[dependencies]\n")
    for name, version, features in _CARGO_RUNTIME_DEPS:
        if features:
            feat_csv = ", ".join(f'"{f}"' for f in features.split(","))
            lines.append(
                f'{name} = {{ version = "{version}", '
                f'features = [{feat_csv}] }}\n'
            )
        else:
            lines.append(f'{name} = "{version}"\n')
    lines.append("\n")
    lines.append("[build-dependencies]\n")
    for name, version, _features in _CARGO_BUILD_DEPS:
        lines.append(f'{name} = "{version}"\n')
    lines.append("\n")
    lines.append("# Chart-author integrates this fragment into their own\n")
    lines.append("# Cargo workspace; this file is a SEED, not a complete\n")
    lines.append("# crate. See SOS-10-CONCEPTS §6.4 + INV-SOS-A.\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Rendering — build.rs seed
# ---------------------------------------------------------------------------


def _render_build_rs(
    *,
    chart_sos_id: str,
    piece_id: str,
) -> str:
    """Render the ``<piece_id>_grpc_build.rs`` seed."""
    lines: list[str] = []
    lines.append(_spec_banner(chart_sos_id))
    lines.append("\n")
    lines.append(
        "// Compiles the canonical orchestrator.proto + this piece's\n"
    )
    lines.append("// service.proto into Rust via tonic-build.\n\n")
    lines.append(
        "fn main() -> Result<(), Box<dyn std::error::Error>> {\n"
    )
    lines.append('    tonic_build::compile_protos("orchestrator.proto")?;\n')
    lines.append(
        f'    tonic_build::compile_protos("{piece_id}_service.proto")?;\n'
    )
    lines.append("    Ok(())\n")
    lines.append("}\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def emit_grpc(
    annotations: OrchestratorAnnotations,
    *,
    chart_sos_id: str,
    chart_id: Optional[str] = None,
    output_dir: Optional[Path | str] = None,
) -> dict[str, str]:
    """Emit gRPC service-stub artifacts for every gRPC-medium edge.

    Args:
        annotations: parsed SOS-10 orchestrator annotations.
        chart_sos_id: the orchestrator chart's ``sos:id`` UUID. Drives the
            deterministic protobuf package suffix
            (``sos_orchestrator_<hex8>``) referenced by every emitted
            ``tonic::include_proto!`` invocation.
        chart_id: optional chart-level identifier used as the disk sub-
            directory under ``build/network/`` when ``output_dir`` is
            provided. Defaults to the leading-8 hex of ``chart_sos_id``.
        output_dir: optional disk write target. When provided, every
            emitted file is written under
            ``{output_dir}/network/{chart_id}/<filename>``; when None, the
            function is pure (returns the file map only).

    Returns:
        Mapping ``relative_filename -> file contents`` for every emitted
        Rust artifact. Filenames carry no directory component.

    Determinism: byte-identical output for byte-identical input.

    Raises:
        GrpcEmitError: chart_sos_id is malformed; a piece id isn't an SV
            identifier; the chart carries duplicate (src, dst, event)
            triples with diverging timeout/idempotent declarations.
    """
    if not isinstance(chart_sos_id, str) or not chart_sos_id:
        raise GrpcEmitError(
            f"chart_sos_id must be a non-empty string; got {chart_sos_id!r}"
        )

    package_suffix = _short_package_suffix(chart_sos_id)
    package_name = f"sos_orchestrator_{package_suffix}"
    effective_chart_id = chart_id if chart_id else package_suffix

    transitions = _grpc_transitions(annotations)

    # Validate piece ids for pieces actually participating in gRPC edges.
    participating: set[str] = set()
    for t in transitions:
        participating.add(t.source_state_id)
        participating.add(t.target_state_id)
    for pid in sorted(participating):
        _validate_piece_id(pid)

    edges = _build_edges(transitions)

    # Bucket edges by source (outgoing → client) and target (incoming →
    # server). A piece may appear in EITHER, BOTH, or NEITHER bucket; we
    # only emit the file that matches its role.
    outgoing: dict[str, list[_GrpcEdge]] = {}
    incoming: dict[str, list[_GrpcEdge]] = {}
    for edge in edges:
        outgoing.setdefault(edge.source_piece, []).append(edge)
        incoming.setdefault(edge.target_piece, []).append(edge)

    out: dict[str, str] = {}

    # Walk pieces in document order so the filename set is stable; emit
    # role-appropriate artifacts per piece.
    for piece in annotations.pieces:
        pid = piece.state_id
        if pid not in participating:
            continue

        piece_outgoing = outgoing.get(pid, [])
        piece_incoming = incoming.get(pid, [])

        if piece_incoming:
            out[f"{pid}_grpc_server.rs"] = _render_server_stub(
                chart_sos_id=chart_sos_id,
                package_name=package_name,
                piece_id=pid,
                incoming_edges=piece_incoming,
            )
        if piece_outgoing:
            out[f"{pid}_grpc_client.rs"] = _render_client_stub(
                chart_sos_id=chart_sos_id,
                package_name=package_name,
                piece_id=pid,
                outgoing_edges=piece_outgoing,
            )

        # Cargo.toml + build.rs seeds — emitted once per participating
        # piece (the seed is per-piece because the build.rs references the
        # piece's specific _service.proto).
        out[f"{pid}_grpc_Cargo.toml"] = _render_cargo_toml(
            chart_sos_id=chart_sos_id,
            piece_id=pid,
        )
        out[f"{pid}_grpc_build.rs"] = _render_build_rs(
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


def emit_grpc_from_chart(
    chart_path: str | Path,
    *,
    chart_sos_id: Optional[str] = None,
    chart_id: Optional[str] = None,
    output_dir: Optional[Path | str] = None,
) -> dict[str, str]:
    """Convenience wrapper: loader → parser → emitter.

    ``chart_sos_id`` defaults to the root scxml's ``sos:id`` attribute
    when present; raises :class:`GrpcEmitError` when neither is supplied.
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
        raise GrpcEmitError(
            f"chart {chart_path!r} has no root sos:id and no chart_sos_id "
            f"override supplied; cannot derive deterministic protobuf "
            f"package name (INV-S-ORCH-4 + INV-SOS-G)."
        )
    return emit_grpc(
        annotations,
        chart_sos_id=sos_id,
        chart_id=chart_id,
        output_dir=output_dir,
    )


__all__ = [
    "emit_grpc",
    "emit_grpc_from_chart",
    "GrpcEmitError",
]

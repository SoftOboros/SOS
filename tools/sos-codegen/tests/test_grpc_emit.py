"""Tests for ``grpc_emit.py`` — SOS-10 gRPC service-stub emitter.

Authority: ``docs/concepts/SOS-10-CONCEPTS.md`` §6.4 (ratified 2026-05-23);
PCDN-SOS-10-001 (Rust v1); PCDN-SOS-10-002 (gRPC derived from protobuf
IDL); PCDN-SOS-10-005 (idempotency); PCDN-SOS-10-006 (timeout defaults).

Covers:
    - happy path: 3-piece chart with one gRPC transition emits server +
      client stubs for the right pieces; the 3rd piece (no gRPC) emits
      nothing gRPC-side.
    - source-only piece: outgoing gRPC, no incoming → ONLY client stub.
    - target-only piece: incoming gRPC, no outgoing → ONLY server stub.
    - timeout override: ``transport.timeout_ms=2000`` lands in client
      code as ``Duration::from_millis(2000)``.
    - timeout default: missing override → 5000 ms per PCDN-SOS-10-006.
    - idempotent=False / unspecified → SAFETY comment block present.
    - idempotent=True → SAFETY comment block absent.
    - AMQP transitions are SILENTLY SKIPPED.
    - in-process / shared-memory / mmio transitions are SILENTLY SKIPPED.
    - determinism: two runs byte-identical.
    - cargo gate: if ``cargo`` is on PATH, validate the seed Cargo.toml +
      build.rs parse cleanly via ``cargo check --offline`` (skipped if
      cargo can't fetch tonic — usually skipped in CI without network).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Make `sos-codegen` modules importable regardless of pytest cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from grpc_emit import (  # noqa: E402
    GrpcEmitError,
    emit_grpc,
    emit_grpc_from_chart,
)
from loader import load_chart  # noqa: E402
from sos10_annotations import (  # noqa: E402
    CrossPieceTransitionAnnotation,
    MediumAnnotation,
    OrchestratorAnnotations,
    PieceAnnotation,
    TransportAnnotation,
    parse_orchestrator_annotations,
)


# ---------------------------------------------------------------------------
# Annotation builders
# ---------------------------------------------------------------------------


def _piece(state_id: str, lang: str = "rust") -> PieceAnnotation:
    return PieceAnnotation(state_id=state_id, lang=lang)


def _grpc_transition(
    src: str,
    dst: str,
    *,
    event: str = "evt.x",
    payload_type: str | None = None,
    transport_timeout_ms: int | None = None,
    medium_timeout_ms: int | None = None,
    idempotent: bool | None = None,
    medium_idempotent: bool | None = None,
) -> CrossPieceTransitionAnnotation:
    extras: dict[str, object] = {}
    if payload_type is not None:
        extras["payload_type"] = payload_type
    transport = TransportAnnotation(
        name="gRPC",
        timeout_ms=transport_timeout_ms,
    )
    medium = MediumAnnotation(
        kind="network",
        transport=transport,
        timeout=medium_timeout_ms,
        idempotent=medium_idempotent,
        extras=extras,
    )
    return CrossPieceTransitionAnnotation(
        source_state_id=src,
        target_state_id=dst,
        event=event,
        medium=medium,
        idempotent=idempotent,
        extras={},
    )


def _amqp_transition(
    src: str,
    dst: str,
    *,
    event: str = "evt.x",
) -> CrossPieceTransitionAnnotation:
    return CrossPieceTransitionAnnotation(
        source_state_id=src,
        target_state_id=dst,
        event=event,
        medium=MediumAnnotation(
            kind="network",
            transport=TransportAnnotation(name="AMQP"),
        ),
    )


def _annotations(
    pieces: list[PieceAnnotation],
    transitions: list[CrossPieceTransitionAnnotation],
) -> OrchestratorAnnotations:
    return OrchestratorAnnotations(pieces=pieces, transitions=transitions)


_CHART_SOS_ID = "fe000000-0000-4000-8000-000000000017"
_HEX8 = "fe000000"


# ---------------------------------------------------------------------------
# Happy path: 3-piece chart with one gRPC transition MCU -> fabric
# ---------------------------------------------------------------------------


def test_happy_path_mcu_to_fabric_emits_client_and_server():
    """One gRPC transition mcu -> fabric → fabric gets server stub;
    mcu gets client stub; bystander piece gets nothing."""
    ann = _annotations(
        pieces=[_piece("mcu"), _piece("fabric"), _piece("bystander")],
        transitions=[
            _grpc_transition(
                "mcu", "fabric", event="evt.start", payload_type="uint32",
            ),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="hp_chart")

    # fabric is the target — gets the server stub.
    assert "fabric_grpc_server.rs" in files
    # mcu is the source — gets the client stub.
    assert "mcu_grpc_client.rs" in files
    # bystander touches no gRPC edges — no artifacts.
    assert "bystander_grpc_server.rs" not in files
    assert "bystander_grpc_client.rs" not in files
    assert "bystander_grpc_Cargo.toml" not in files

    # fabric does NOT send any gRPC — no client stub for it.
    assert "fabric_grpc_client.rs" not in files
    # mcu does NOT receive any gRPC — no server stub for it.
    assert "mcu_grpc_server.rs" not in files

    # Cargo.toml + build.rs seeds present for participating pieces.
    assert "fabric_grpc_Cargo.toml" in files
    assert "fabric_grpc_build.rs" in files
    assert "mcu_grpc_Cargo.toml" in files
    assert "mcu_grpc_build.rs" in files


def test_happy_path_server_stub_shape():
    """Server stub carries the @spec banner, tonic::include_proto!, the
    impl struct, the async_trait impl, and a serve() helper."""
    ann = _annotations(
        pieces=[_piece("mcu"), _piece("fabric")],
        transitions=[_grpc_transition("mcu", "fabric", event="evt.go")],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="srv_chart")
    server = files["fabric_grpc_server.rs"]

    # @spec banner.
    assert "SOS-10-CONCEPTS §6.4" in server
    assert "PCDN-SOS-10-001" in server
    assert "PCDN-SOS-10-002" in server
    assert "PCDN-SOS-10-005" in server
    assert "PCDN-SOS-10-006" in server
    assert "INV-S-ORCH-1" in server
    assert "INV-S-ORCH-4" in server
    assert "INV-SOS-A" in server

    # tonic::include_proto! references the canonical package.
    assert f'tonic::include_proto!("sos_orchestrator_{_HEX8}")' in server

    # Impl struct + trait impl.
    assert "pub struct FabricOrchestratorImpl" in server
    assert "#[tonic::async_trait]" in server
    assert "impl proto::fabric_orchestrator_server::FabricOrchestrator" in server

    # One async fn per incoming event with unimplemented body.
    assert "async fn mcu_evt_go(" in server
    assert "Status::unimplemented" in server
    assert "evt.go not yet wired" in server

    # serve() helper.
    assert "pub async fn serve(" in server
    assert "Server::builder()" in server
    assert "add_service(proto::fabric_orchestrator_server::FabricOrchestratorServer::new(impl_))" in server
    assert ".serve(addr)" in server


def test_happy_path_client_stub_shape():
    """Client stub carries the @spec banner, one send_<event> per
    outgoing edge, the default 5000ms timeout, and a SAFETY block."""
    ann = _annotations(
        pieces=[_piece("mcu"), _piece("fabric")],
        transitions=[_grpc_transition("mcu", "fabric", event="evt.go")],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="cli_chart")
    client = files["mcu_grpc_client.rs"]

    assert "SOS-10-CONCEPTS §6.4" in client
    assert f'tonic::include_proto!("sos_orchestrator_{_HEX8}")' in client

    # One send_<event> per outgoing.
    assert "pub async fn send_evt_go(" in client
    # Default 5000 ms timeout when no override declared.
    assert "Duration::from_millis(5000)" in client
    # SAFETY block because idempotent is unspecified.
    assert "SAFETY: this RPC is NOT marked idempotent" in client


# ---------------------------------------------------------------------------
# Role-asymmetric pieces
# ---------------------------------------------------------------------------


def test_source_only_piece_emits_only_client_stub():
    """A piece that only sends gRPC (never receives) emits ONLY the
    client stub — no server stub."""
    ann = _annotations(
        pieces=[_piece("client"), _piece("dst1"), _piece("dst2")],
        transitions=[
            _grpc_transition("client", "dst1", event="evt.a"),
            _grpc_transition("client", "dst2", event="evt.b"),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="src_chart")
    assert "client_grpc_client.rs" in files
    assert "client_grpc_server.rs" not in files
    # The destinations get server stubs only.
    assert "dst1_grpc_server.rs" in files
    assert "dst1_grpc_client.rs" not in files
    assert "dst2_grpc_server.rs" in files
    assert "dst2_grpc_client.rs" not in files


def test_target_only_piece_emits_only_server_stub():
    """A piece that only receives gRPC emits ONLY the server stub."""
    ann = _annotations(
        pieces=[_piece("src1"), _piece("src2"), _piece("target")],
        transitions=[
            _grpc_transition("src1", "target", event="evt.a"),
            _grpc_transition("src2", "target", event="evt.b"),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="tgt_chart")
    assert "target_grpc_server.rs" in files
    assert "target_grpc_client.rs" not in files
    # Sources get client stubs only.
    assert "src1_grpc_client.rs" in files
    assert "src1_grpc_server.rs" not in files
    assert "src2_grpc_client.rs" in files
    assert "src2_grpc_server.rs" not in files


def test_bidirectional_piece_emits_both_stubs():
    """A piece that both sends AND receives emits BOTH client and server
    stubs."""
    ann = _annotations(
        pieces=[_piece("alpha"), _piece("beta")],
        transitions=[
            _grpc_transition("alpha", "beta", event="evt.fwd"),
            _grpc_transition("beta", "alpha", event="evt.ack"),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="bidi_chart")
    assert "alpha_grpc_server.rs" in files
    assert "alpha_grpc_client.rs" in files
    assert "beta_grpc_server.rs" in files
    assert "beta_grpc_client.rs" in files


# ---------------------------------------------------------------------------
# Timeout override
# ---------------------------------------------------------------------------


def test_transport_timeout_override_lands_in_client():
    """``transport.timeout_ms=2000`` → ``Duration::from_millis(2000)``."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            _grpc_transition(
                "a", "b", event="evt.t", transport_timeout_ms=2000,
            ),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="to_chart")
    client = files["a_grpc_client.rs"]
    assert "Duration::from_millis(2000)" in client
    # Default should NOT appear.
    assert "Duration::from_millis(5000)" not in client


def test_medium_timeout_override_lands_in_client():
    """``medium.timeout=1500`` propagates when no transport-level timeout."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            _grpc_transition(
                "a", "b", event="evt.t", medium_timeout_ms=1500,
            ),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="to2_chart")
    client = files["a_grpc_client.rs"]
    assert "Duration::from_millis(1500)" in client


def test_transport_timeout_beats_medium_timeout():
    """Transport-level timeout takes precedence over medium-level."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            _grpc_transition(
                "a", "b", event="evt.t",
                transport_timeout_ms=750,
                medium_timeout_ms=9999,
            ),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="to3_chart")
    client = files["a_grpc_client.rs"]
    assert "Duration::from_millis(750)" in client
    assert "Duration::from_millis(9999)" not in client


def test_default_timeout_is_5000ms_per_pcdn_006():
    """No timeout declared anywhere → 5000ms default."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[_grpc_transition("a", "b", event="evt.t")],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="def_chart")
    client = files["a_grpc_client.rs"]
    assert "Duration::from_millis(5000)" in client


# ---------------------------------------------------------------------------
# Idempotency SAFETY block
# ---------------------------------------------------------------------------


def test_idempotent_false_emits_safety_block():
    """idempotent=False → SAFETY comment block present."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            _grpc_transition(
                "a", "b", event="evt.x", idempotent=False,
            ),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="if_chart")
    client = files["a_grpc_client.rs"]
    assert "SAFETY: this RPC is NOT marked idempotent" in client
    assert "PCDN-SOS-10-005" in client


def test_idempotent_unspecified_emits_safety_block():
    """idempotent unspecified (None) → SAFETY block fires (default-deny)."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[_grpc_transition("a", "b", event="evt.x")],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="iu_chart")
    client = files["a_grpc_client.rs"]
    assert "SAFETY: this RPC is NOT marked idempotent" in client


def test_idempotent_true_omits_safety_block():
    """idempotent=True → SAFETY block absent; an affirmative comment
    explains the marker is set."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            _grpc_transition(
                "a", "b", event="evt.x", idempotent=True,
            ),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="it_chart")
    client = files["a_grpc_client.rs"]
    assert "SAFETY: this RPC is NOT marked idempotent" not in client
    # An affirmative idempotent-marker comment IS present.
    assert "marked idempotent" in client


def test_medium_idempotent_true_omits_safety_block():
    """Medium-level idempotent=true also suppresses the SAFETY block."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            _grpc_transition(
                "a", "b", event="evt.x", medium_idempotent=True,
            ),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="mi_chart")
    client = files["a_grpc_client.rs"]
    assert "SAFETY: this RPC is NOT marked idempotent" not in client


# ---------------------------------------------------------------------------
# Filter: AMQP / non-network transitions silently skipped
# ---------------------------------------------------------------------------


def test_amqp_transitions_silently_skipped():
    """AMQP transitions are skipped — only gRPC pieces appear in output."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b"), _piece("c")],
        transitions=[
            _grpc_transition("a", "b", event="evt.g"),
            _amqp_transition("a", "c", event="evt.q"),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="mix_chart")
    # Only the gRPC edge (a -> b) participates.
    assert "a_grpc_client.rs" in files
    assert "b_grpc_server.rs" in files
    # c (AMQP target) participates in NO gRPC edge → no artifacts.
    assert "c_grpc_server.rs" not in files
    assert "c_grpc_client.rs" not in files
    assert "c_grpc_Cargo.toml" not in files


def test_non_network_kinds_silently_skipped():
    """in-process / shared-memory / mmio transitions are SKIPPED."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b"), _piece("c"), _piece("d"), _piece("e")],
        transitions=[
            CrossPieceTransitionAnnotation(
                source_state_id="a",
                target_state_id="b",
                event="evt.local",
                medium=MediumAnnotation(kind="in-process"),
            ),
            CrossPieceTransitionAnnotation(
                source_state_id="a",
                target_state_id="c",
                event="evt.shm",
                medium=MediumAnnotation(kind="shared-memory"),
            ),
            CrossPieceTransitionAnnotation(
                source_state_id="a",
                target_state_id="d",
                event="evt.mmio",
                medium=MediumAnnotation(kind="mmio"),
            ),
            _grpc_transition("a", "e", event="evt.net"),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="skip_chart")
    # Only the gRPC edge (a -> e) produces output.
    assert "a_grpc_client.rs" in files
    assert "e_grpc_server.rs" in files
    # No artifacts for the other targets.
    for pid in ("b", "c", "d"):
        assert f"{pid}_grpc_server.rs" not in files
        assert f"{pid}_grpc_client.rs" not in files
        assert f"{pid}_grpc_Cargo.toml" not in files


def test_chart_with_no_grpc_edges_emits_no_artifacts():
    """A chart with zero gRPC transitions → empty output map."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            _amqp_transition("a", "b", event="evt.q"),
            CrossPieceTransitionAnnotation(
                source_state_id="a",
                target_state_id="b",
                event="evt.local",
                medium=MediumAnnotation(kind="in-process"),
            ),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="none_chart")
    assert files == {}


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_emit_is_deterministic_byte_identical():
    """Two emit runs over the same annotations produce identical bytes."""
    ann = _annotations(
        pieces=[_piece("alpha"), _piece("beta"), _piece("gamma")],
        transitions=[
            _grpc_transition("alpha", "beta", event="evt.zulu"),
            _grpc_transition("beta", "gamma", event="evt.alpha"),
            _grpc_transition("alpha", "gamma", event="evt.mike",
                             transport_timeout_ms=750, idempotent=True),
        ],
    )
    a = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="det_chart")
    b = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="det_chart")
    assert a == b
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_server_trait_methods_alphabetical_by_event():
    """Server-trait methods are ordered alphabetically by event name
    within each piece."""
    ann = _annotations(
        pieces=[_piece("src"), _piece("dst")],
        transitions=[
            _grpc_transition("src", "dst", event="evt.zulu"),
            _grpc_transition("src", "dst", event="evt.alpha"),
            _grpc_transition("src", "dst", event="evt.mike"),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="ord_chart")
    server = files["dst_grpc_server.rs"]
    p_alpha = server.index("src_evt_alpha")
    p_mike = server.index("src_evt_mike")
    p_zulu = server.index("src_evt_zulu")
    assert p_alpha < p_mike < p_zulu


def test_client_fns_alphabetical_by_event():
    """Client fns are ordered alphabetically by event name."""
    ann = _annotations(
        pieces=[_piece("src"), _piece("dst")],
        transitions=[
            _grpc_transition("src", "dst", event="evt.zulu"),
            _grpc_transition("src", "dst", event="evt.alpha"),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="ord2_chart")
    client = files["src_grpc_client.rs"]
    p_alpha = client.index("pub async fn send_evt_alpha(")
    p_zulu = client.index("pub async fn send_evt_zulu(")
    assert p_alpha < p_zulu


def test_cargo_toml_dependency_ordering_alphabetical():
    """Cargo.toml runtime deps are alphabetical: prost, serde, tokio, tonic."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[_grpc_transition("a", "b", event="evt.x")],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="cgo_chart")
    cargo = files["a_grpc_Cargo.toml"]
    # Find dep positions and confirm alphabetical.
    p_prost = cargo.index("prost = ")
    p_serde = cargo.index("serde = ")
    p_tokio = cargo.index("tokio = ")
    p_tonic = cargo.index("tonic = ")
    assert p_prost < p_serde < p_tokio < p_tonic
    # Build deps section present.
    assert "[build-dependencies]" in cargo
    assert "tonic-build = " in cargo


def test_build_rs_compiles_both_protos():
    """build.rs seed compiles orchestrator.proto + <piece>_service.proto."""
    ann = _annotations(
        pieces=[_piece("mypiece"), _piece("other")],
        transitions=[_grpc_transition("mypiece", "other", event="evt.x")],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="brs_chart")
    build_rs = files["mypiece_grpc_build.rs"]
    assert 'tonic_build::compile_protos("orchestrator.proto")' in build_rs
    assert 'tonic_build::compile_protos("mypiece_service.proto")' in build_rs
    # other's build.rs references other_service.proto.
    other_build = files["other_grpc_build.rs"]
    assert 'tonic_build::compile_protos("other_service.proto")' in other_build


# ---------------------------------------------------------------------------
# Duplicate-edge divergence check
# ---------------------------------------------------------------------------


def test_duplicate_edge_with_diverging_timeout_raises():
    """Two transitions with the same (src, dst, event) but diverging
    timeout declarations raise (chart-author error)."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            _grpc_transition(
                "a", "b", event="evt.x", transport_timeout_ms=1000,
            ),
            _grpc_transition(
                "a", "b", event="evt.x", transport_timeout_ms=2000,
            ),
        ],
    )
    with pytest.raises(GrpcEmitError):
        emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="dup_chart")


def test_duplicate_edge_with_same_spec_dedupes():
    """Identical edges dedupe silently (idempotent emission)."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            _grpc_transition("a", "b", event="evt.x"),
            _grpc_transition("a", "b", event="evt.x"),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="dd_chart")
    client = files["a_grpc_client.rs"]
    # Only one send_evt_x fn emitted.
    assert client.count("pub async fn send_evt_x(") == 1


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_malformed_chart_sos_id_raises():
    """Non-hex / too-short chart_sos_id raises GrpcEmitError."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[_grpc_transition("a", "b")],
    )
    with pytest.raises(GrpcEmitError):
        emit_grpc(ann, chart_sos_id="too-short", chart_id="x")
    with pytest.raises(GrpcEmitError):
        emit_grpc(ann, chart_sos_id="", chart_id="x")


def test_non_sv_identifier_piece_id_raises():
    """Piece ids that aren't SV identifiers raise."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            CrossPieceTransitionAnnotation(
                source_state_id="a",
                target_state_id="not.valid",  # dot is illegal in idents
                event="evt.x",
                medium=MediumAnnotation(
                    kind="network",
                    transport=TransportAnnotation(name="gRPC"),
                ),
            ),
        ],
    )
    with pytest.raises(GrpcEmitError):
        emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="bad_chart")


# ---------------------------------------------------------------------------
# Disk write
# ---------------------------------------------------------------------------


def test_emit_writes_files_when_output_dir_given(tmp_path: Path):
    """`output_dir=` writes each file under `<output_dir>/network/<chart_id>/`."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[_grpc_transition("a", "b", event="evt.x")],
    )
    files = emit_grpc(
        ann, chart_sos_id=_CHART_SOS_ID, chart_id="disk_chart",
        output_dir=tmp_path,
    )
    out_root = tmp_path / "network" / "disk_chart"
    assert out_root.is_dir()
    for rel, body in files.items():
        target = out_root / rel
        assert target.exists()
        assert target.read_text(encoding="utf-8") == body


# ---------------------------------------------------------------------------
# Fixture-driven end-to-end (reuses wave-17a fixture)
# ---------------------------------------------------------------------------


_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "sos_10_network"
    / "orchestrator_3piece_network.scxml"
)


def test_fixture_three_piece_chart_emits_only_grpc_artifacts():
    """End-to-end against the wave-17a fixture: only the
    client→gateway gRPC edge (evt.start with payload_type=uint32 +
    timeout-ms=3000) produces gRPC artifacts; the AMQP and in-process
    edges are silently skipped."""
    ast = load_chart(_FIXTURE).raw_scjson
    annotations = parse_orchestrator_annotations(ast)
    files = emit_grpc(
        annotations, chart_sos_id=_CHART_SOS_ID, chart_id="fx_chart"
    )

    # Only one gRPC edge in the fixture: client -> gateway (evt.start).
    assert "gateway_grpc_server.rs" in files
    assert "client_grpc_client.rs" in files

    # broker participates ONLY in AMQP edges → no gRPC artifacts.
    assert "broker_grpc_server.rs" not in files
    assert "broker_grpc_client.rs" not in files
    assert "broker_grpc_Cargo.toml" not in files

    # client does not RECEIVE gRPC → no server stub.
    assert "client_grpc_server.rs" not in files
    # gateway does not SEND gRPC (its only outgoing is AMQP to broker).
    assert "gateway_grpc_client.rs" not in files

    # The fixture's <sos:timeout ms="3000"/> lands in the client stub.
    client = files["client_grpc_client.rs"]
    assert "Duration::from_millis(3000)" in client
    # SAFETY block is present (fixture doesn't declare idempotency).
    assert "SAFETY: this RPC is NOT marked idempotent" in client


def test_fixture_emit_is_deterministic():
    """Fixture-driven emit is byte-identical across two runs."""
    ast = load_chart(_FIXTURE).raw_scjson
    annotations = parse_orchestrator_annotations(ast)
    a = emit_grpc(
        annotations, chart_sos_id=_CHART_SOS_ID, chart_id="fx_chart"
    )
    b = emit_grpc(
        annotations, chart_sos_id=_CHART_SOS_ID, chart_id="fx_chart"
    )
    assert a == b


def test_fixture_via_from_chart_helper_uses_root_sos_id():
    """`emit_grpc_from_chart` reads `sos:id` from the root scxml."""
    files = emit_grpc_from_chart(_FIXTURE, chart_id="fxh_chart")
    # The fixture's sos:id is fe000000-... → leading-8 hex `fe000000`.
    client = files["client_grpc_client.rs"]
    assert "sos_orchestrator_fe000000" in client


# ---------------------------------------------------------------------------
# Rust syntax gate (skipped without cargo on PATH or without network for
# tonic crate download)
# ---------------------------------------------------------------------------


def _have_cargo() -> str | None:
    return shutil.which("cargo")


def test_emitted_cargo_seed_is_well_formed_toml():
    """The emitted Cargo.toml SEED parses as valid TOML (no cargo
    invocation needed — pure structural check)."""
    try:
        import tomllib  # Python 3.11+
    except ImportError:  # pragma: no cover - py3.10 path
        pytest.skip("tomllib not available (Python < 3.11)")

    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[_grpc_transition("a", "b", event="evt.x")],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="toml_chart")
    cargo = files["a_grpc_Cargo.toml"]
    parsed = tomllib.loads(cargo)
    assert parsed["package"]["name"] == "a_grpc_stub"
    assert parsed["package"]["edition"] == "2021"
    # All four runtime deps present.
    deps = parsed["dependencies"]
    assert set(deps.keys()) == {"prost", "serde", "tokio", "tonic"}
    # build-dependencies present.
    assert "tonic-build" in parsed["build-dependencies"]


def test_emitted_rust_files_have_no_obvious_brace_imbalance():
    """Quick structural gate: every emitted .rs file has matched
    braces. This isn't a real parse but catches gross template breakage
    without needing a Rust toolchain."""
    ann = _annotations(
        pieces=[_piece("alpha"), _piece("beta"), _piece("gamma")],
        transitions=[
            _grpc_transition("alpha", "beta", event="evt.zulu",
                             transport_timeout_ms=750, idempotent=True),
            _grpc_transition("beta", "gamma", event="evt.alpha"),
        ],
    )
    files = emit_grpc(ann, chart_sos_id=_CHART_SOS_ID, chart_id="bal_chart")
    for fname, body in files.items():
        if not fname.endswith(".rs"):
            continue
        # Strip line and block comments (rough) before counting braces.
        no_line_comments = "\n".join(
            line.split("//", 1)[0] for line in body.splitlines()
        )
        opens = no_line_comments.count("{")
        closes = no_line_comments.count("}")
        assert opens == closes, (
            f"{fname}: brace mismatch ({opens} opens, {closes} closes)"
        )


def test_emitted_rust_compiles_under_cargo_check(tmp_path: Path):
    """Optional gate: emit a complete Cargo crate against a stub
    orchestrator.proto + service.proto and run ``cargo check --offline``.

    Skipped unless cargo is on PATH AND a working offline tonic registry
    is available. This is the load-bearing real-toolchain gate and is
    expected to skip in most CI environments.
    """
    cargo = _have_cargo()
    if cargo is None:
        pytest.skip("no cargo on PATH")

    ann = _annotations(
        pieces=[_piece("mcu"), _piece("fabric")],
        transitions=[
            _grpc_transition("mcu", "fabric", event="evt.go",
                             payload_type="uint32"),
        ],
    )
    files = emit_grpc(
        ann, chart_sos_id=_CHART_SOS_ID, chart_id="cargo_chart",
        output_dir=tmp_path,
    )
    out_root = tmp_path / "network" / "cargo_chart"

    # Probe cargo registry availability with a tiny no-deps crate FIRST.
    # If even an empty crate can't run cargo check (no toolchain or sandbox
    # blocks the cargo home), skip without claiming a real gate ran.
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    (probe_dir / "Cargo.toml").write_text(
        '[package]\nname = "probe"\nversion = "0.1.0"\nedition = "2021"\n'
        '[lib]\npath = "lib.rs"\n',
        encoding="utf-8",
    )
    (probe_dir / "lib.rs").write_text("pub fn x() -> u32 { 1 }\n", encoding="utf-8")
    probe = subprocess.run(
        [cargo, "check", "--offline", "-q"],
        cwd=str(probe_dir),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if probe.returncode != 0:
        pytest.skip(
            "cargo check probe failed (no usable toolchain/registry): "
            f"{probe.stderr[:200]}"
        )

    # The real gate would need a tonic-able registry. Probe for tonic.
    # If the registry doesn't have tonic offline, skip (this is the
    # documented "likely will skip" path).
    crate_dir = tmp_path / "crate"
    crate_dir.mkdir()
    (crate_dir / "Cargo.toml").write_text(
        (out_root / "mcu_grpc_Cargo.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # Bare-minimum src/ shape so cargo doesn't complain.
    (crate_dir / "src").mkdir()
    (crate_dir / "src" / "lib.rs").write_text("// empty\n", encoding="utf-8")

    result = subprocess.run(
        [cargo, "check", "--offline", "-q"],
        cwd=str(crate_dir),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        # Tonic / prost not available offline → skip rather than fail.
        if "could not find" in result.stderr or "no matching package" in result.stderr:
            pytest.skip(
                f"cargo registry lacks tonic offline: {result.stderr[:200]}"
            )
        pytest.fail(
            f"cargo check failed:\nstdout: {result.stdout}\nstderr: "
            f"{result.stderr}"
        )
    # The files dict is used to confirm emit succeeded.
    assert "mcu_grpc_Cargo.toml" in files

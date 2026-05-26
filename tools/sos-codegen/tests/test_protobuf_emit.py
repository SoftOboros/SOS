"""Tests for ``protobuf_emit.py`` — SOS-10 network-medium protobuf IDL emitter.

Authority: ``docs/concepts/SOS-10-CONCEPTS.md`` §6.4 (ratified
2026-05-23) + PCDN-SOS-10-002 (protobuf canonical IDL; gRPC + AMQP both
derived).

Covers:
    - happy path: 3-piece chart with gRPC + AMQP transitions emits
      orchestrator.proto + per-piece service stubs + amqp_routing.json.
    - empty service: piece with no incoming RPCs emits an empty
      ``service`` block with the documented marker comment.
    - payload-type mapping: ``payload_type="uint32"`` propagates to
      ``uint32 payload = 1;``.
    - default `bytes` fallback when chart omits payload_type, with a
      TODO comment per INV-S-ORCH-4.
    - determinism: two emit runs produce byte-identical output.
    - protoc parse gate (skipped if `protoc` is not on PATH).
    - network-only filter: in-process / shared-memory / mmio
      transitions are SKIPPED.
    - AMQP routing JSON shape: one entry per AMQP pairing; routing
      keys are event names; queue/exchange names follow the documented
      schema.
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

from loader import load_chart  # noqa: E402
from protobuf_emit import (  # noqa: E402
    ProtobufEmitError,
    SCALAR_TYPE_MAP,
    emit_protobuf,
    emit_protobuf_from_chart,
)
from sos10_annotations import (  # noqa: E402
    CrossPieceTransitionAnnotation,
    MediumAnnotation,
    OrchestratorAnnotations,
    PieceAnnotation,
    TransportAnnotation,
    parse_orchestrator_annotations,
)


# ---------------------------------------------------------------------------
# In-process annotation builders.
# ---------------------------------------------------------------------------


def _piece(state_id: str, lang: str = "rust") -> PieceAnnotation:
    return PieceAnnotation(state_id=state_id, lang=lang)


def _network_transition(
    src: str,
    dst: str,
    *,
    event: str = "evt.x",
    transport: str = "gRPC",
    payload_type: str | None = None,
    timeout_ms: int | None = None,
) -> CrossPieceTransitionAnnotation:
    extras: dict[str, object] = {}
    if payload_type is not None:
        extras["payload_type"] = payload_type
    medium = MediumAnnotation(
        kind="network",
        transport=TransportAnnotation(name=transport),
        timeout=timeout_ms,
        idempotent=None,
        extras=extras,
    )
    return CrossPieceTransitionAnnotation(
        source_state_id=src,
        target_state_id=dst,
        event=event,
        medium=medium,
        idempotent=None,
        extras={},
    )


def _annotations(
    pieces: list[PieceAnnotation],
    transitions: list[CrossPieceTransitionAnnotation],
) -> OrchestratorAnnotations:
    return OrchestratorAnnotations(pieces=pieces, transitions=transitions)


_CHART_SOS_ID = "fe000000-0000-4000-8000-000000000017"
_HEX8 = "fe000000"  # first 8 hex chars of the UUID above (hyphen-stripped)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_three_piece_emits_full_artifact_set():
    """3-piece chart: one gRPC + one AMQP transition between distinct
    pairs → orchestrator.proto + 3 per-piece service stubs + AMQP
    routing JSON."""
    ann = _annotations(
        pieces=[_piece("client"), _piece("gateway"), _piece("broker")],
        transitions=[
            _network_transition(
                "client", "gateway", event="evt.start",
                transport="gRPC", payload_type="uint32",
            ),
            _network_transition(
                "gateway", "broker", event="evt.broadcast",
                transport="AMQP", payload_type="string",
            ),
            _network_transition(
                "client", "broker", event="evt.report",
                transport="AMQP",  # default bytes payload
            ),
        ],
    )

    files = emit_protobuf(ann, chart_sos_id=_CHART_SOS_ID, chart_id="hp_chart")

    # File set.
    assert "orchestrator.proto" in files
    assert "client_service.proto" in files
    assert "gateway_service.proto" in files
    assert "broker_service.proto" in files
    assert "amqp_routing.json" in files
    assert len(files) == 5

    # orchestrator.proto sanity.
    proto = files["orchestrator.proto"]
    assert 'syntax = "proto3";' in proto
    assert f"package sos_orchestrator_{_HEX8};" in proto
    assert 'import "google/protobuf/empty.proto";' in proto
    # @spec banner present.
    assert "SOS-10-CONCEPTS §6.4" in proto
    assert "PCDN-SOS-10-002" in proto
    assert "INV-S-ORCH-4" in proto
    assert "INV-SOS-A" in proto
    # All three events have request/response message pairs.
    assert "message ClientToGateway_evt_start_Request" in proto
    assert "message ClientToGateway_evt_start_Response" in proto
    assert "message GatewayToBroker_evt_broadcast_Request" in proto
    assert "message ClientToBroker_evt_report_Request" in proto

    # Per-piece service stubs.
    gateway_svc = files["gateway_service.proto"]
    assert "service GatewayOrchestrator {" in gateway_svc
    assert 'import "orchestrator.proto";' in gateway_svc
    # gateway is the target of evt.start from client → has one RPC.
    assert "ClientToGateway_evt_start_Request" in gateway_svc
    assert "ClientToGateway_evt_start_Response" in gateway_svc

    broker_svc = files["broker_service.proto"]
    assert "service BrokerOrchestrator {" in broker_svc
    # broker receives evt.report (from client) + evt.broadcast (from gateway).
    assert "ClientToBroker_evt_report_Request" in broker_svc
    assert "GatewayToBroker_evt_broadcast_Request" in broker_svc


# ---------------------------------------------------------------------------
# Empty-service degenerate
# ---------------------------------------------------------------------------


def test_piece_with_no_incoming_rpcs_emits_empty_service():
    """A piece that participates as a SOURCE only emits an empty
    ``service`` stub with the ``no incoming RPCs`` comment."""
    ann = _annotations(
        pieces=[_piece("alpha"), _piece("beta")],
        transitions=[
            _network_transition("alpha", "beta", event="evt.ping"),
        ],
    )
    files = emit_protobuf(ann, chart_sos_id=_CHART_SOS_ID, chart_id="empty_chart")

    # alpha is the source-only piece.
    alpha_svc = files["alpha_service.proto"]
    assert "service AlphaOrchestrator {" in alpha_svc
    assert "no incoming RPCs" in alpha_svc
    # No `rpc` declaration lines (only narrative may contain the word).
    rpc_decl_lines = [
        ln for ln in alpha_svc.splitlines()
        if ln.lstrip().startswith("rpc ")
    ]
    assert rpc_decl_lines == []

    # beta has one RPC declaration.
    beta_svc = files["beta_service.proto"]
    beta_rpc_lines = [
        ln for ln in beta_svc.splitlines()
        if ln.lstrip().startswith("rpc ")
    ]
    assert len(beta_rpc_lines) == 1


# ---------------------------------------------------------------------------
# Payload-type mapping
# ---------------------------------------------------------------------------


def test_payload_type_uint32_propagates():
    """`payload_type="uint32"` → `uint32 payload = 1;` in the Request."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            _network_transition(
                "a", "b", event="evt.tick", payload_type="uint32",
            ),
        ],
    )
    files = emit_protobuf(ann, chart_sos_id=_CHART_SOS_ID, chart_id="pl_chart")
    proto = files["orchestrator.proto"]
    # Request message has `uint32 payload = 1;` and NO TODO comment.
    assert "message AToB_evt_tick_Request {" in proto
    assert "uint32 payload = 1;" in proto
    # Default-fallback TODO is absent for explicit type.
    assert "TODO(SOS-10-payload-type)" not in proto


def test_payload_type_all_scalars_round_trip():
    """Every scalar in SCALAR_TYPE_MAP appears verbatim when declared."""
    transitions = []
    pieces = [_piece("a"), _piece("b")]
    for i, scalar in enumerate(sorted(SCALAR_TYPE_MAP)):
        transitions.append(
            _network_transition(
                "a", "b", event=f"evt.{i}", payload_type=scalar,
            )
        )
    ann = _annotations(pieces=pieces, transitions=transitions)
    files = emit_protobuf(
        ann, chart_sos_id=_CHART_SOS_ID, chart_id="all_scalars_chart"
    )
    proto = files["orchestrator.proto"]
    for scalar in SCALAR_TYPE_MAP.values():
        assert f"{scalar} payload = 1;" in proto


def test_default_bytes_when_no_payload_type():
    """No `payload_type` → `bytes payload = 1;` + TODO comment."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            _network_transition("a", "b", event="evt.raw"),  # no payload_type
        ],
    )
    files = emit_protobuf(ann, chart_sos_id=_CHART_SOS_ID, chart_id="def_chart")
    proto = files["orchestrator.proto"]
    assert "bytes payload = 1;" in proto
    assert "TODO(SOS-10-payload-type)" in proto


def test_unknown_payload_type_falls_through_to_bytes():
    """Unknown scalar name → bytes + TODO (no raise; chart-author owns
    schema per INV-S-ORCH-4)."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            _network_transition(
                "a", "b", event="evt.weird", payload_type="my_custom_type",
            ),
        ],
    )
    files = emit_protobuf(ann, chart_sos_id=_CHART_SOS_ID, chart_id="unk_chart")
    proto = files["orchestrator.proto"]
    assert "bytes payload = 1;" in proto
    assert "TODO(SOS-10-payload-type)" in proto


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_emit_is_deterministic_byte_identical():
    """Two emit runs over the same annotations produce identical bytes."""
    ann = _annotations(
        pieces=[_piece("client"), _piece("gateway"), _piece("broker")],
        transitions=[
            _network_transition(
                "client", "gateway", event="evt.start", payload_type="uint32",
            ),
            _network_transition(
                "gateway", "broker", event="evt.broadcast",
                transport="AMQP", payload_type="string",
            ),
        ],
    )
    a = emit_protobuf(ann, chart_sos_id=_CHART_SOS_ID, chart_id="det_chart")
    b = emit_protobuf(ann, chart_sos_id=_CHART_SOS_ID, chart_id="det_chart")
    assert a == b
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_emit_message_ordering_is_alphabetical():
    """Message types in orchestrator.proto are alphabetical by
    (src, dst, event)."""
    # Declare transitions in deliberately non-alphabetical order.
    ann = _annotations(
        pieces=[_piece("a"), _piece("b"), _piece("c")],
        transitions=[
            _network_transition("c", "a", event="evt.zeta"),
            _network_transition("a", "b", event="evt.alpha"),
            _network_transition("a", "b", event="evt.beta"),
        ],
    )
    files = emit_protobuf(ann, chart_sos_id=_CHART_SOS_ID, chart_id="ord_chart")
    proto = files["orchestrator.proto"]
    # AToB_evt_alpha must come before AToB_evt_beta must come before
    # CToA_evt_zeta.
    p_alpha = proto.index("AToB_evt_alpha_Request")
    p_beta = proto.index("AToB_evt_beta_Request")
    p_zeta = proto.index("CToA_evt_zeta_Request")
    assert p_alpha < p_beta < p_zeta


# ---------------------------------------------------------------------------
# Network-only filter
# ---------------------------------------------------------------------------


def test_emitter_skips_non_network_transitions():
    """Transitions with kind != network are silently skipped."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b"), _piece("c")],
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
            _network_transition("b", "c", event="evt.net"),
        ],
    )
    files = emit_protobuf(ann, chart_sos_id=_CHART_SOS_ID, chart_id="skip_chart")
    proto = files["orchestrator.proto"]
    # Only the (b -> c, evt.net) pairing produces messages.
    assert "BToC_evt_net_Request" in proto
    assert "AToB" not in proto
    assert "AToC" not in proto
    # `a` did not participate in any network transition → no service file.
    assert "a_service.proto" not in files
    assert "b_service.proto" in files
    assert "c_service.proto" in files


def test_emitter_with_no_network_transitions_still_emits_stubs():
    """A chart with zero network transitions emits a sentinel
    orchestrator.proto + amqp_routing.json with no per-piece services."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            CrossPieceTransitionAnnotation(
                source_state_id="a",
                target_state_id="b",
                event="evt.local",
                medium=MediumAnnotation(kind="in-process"),
            ),
        ],
    )
    files = emit_protobuf(ann, chart_sos_id=_CHART_SOS_ID, chart_id="zero_chart")
    assert "orchestrator.proto" in files
    assert "amqp_routing.json" in files
    # No piece participates → no per-piece services.
    assert "a_service.proto" not in files
    assert "b_service.proto" not in files
    # AMQP routing has no entries.
    parsed = json.loads(files["amqp_routing.json"])
    assert parsed["entries"] == []


# ---------------------------------------------------------------------------
# AMQP routing JSON shape
# ---------------------------------------------------------------------------


def test_amqp_routing_json_shape_one_entry_per_pairing():
    """One entry per (src, dst) AMQP pairing; routing keys alphabetical."""
    ann = _annotations(
        pieces=[_piece("client"), _piece("broker")],
        transitions=[
            _network_transition(
                "client", "broker", event="evt.zulu", transport="AMQP",
            ),
            _network_transition(
                "client", "broker", event="evt.alpha", transport="AMQP",
            ),
            _network_transition(
                "client", "broker", event="evt.mike", transport="AMQP",
            ),
        ],
    )
    files = emit_protobuf(ann, chart_sos_id=_CHART_SOS_ID, chart_id="rt_chart")
    parsed = json.loads(files["amqp_routing.json"])
    assert parsed["chart_id"] == "rt_chart"
    assert "_spec" in parsed
    entries = parsed["entries"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["source_piece"] == "client"
    assert entry["target_piece"] == "broker"
    assert entry["exchange"] == "rt_chart.client"
    assert entry["queue"] == "rt_chart.broker"
    # Routing keys alphabetical.
    assert entry["routing_keys"] == ["evt.alpha", "evt.mike", "evt.zulu"]


def test_amqp_routing_json_excludes_grpc_pairings():
    """gRPC-only pairings are absent from amqp_routing.json."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b"), _piece("c")],
        transitions=[
            _network_transition("a", "b", event="evt.grpc", transport="gRPC"),
            _network_transition("a", "c", event="evt.amqp", transport="AMQP"),
        ],
    )
    files = emit_protobuf(ann, chart_sos_id=_CHART_SOS_ID, chart_id="mix_chart")
    parsed = json.loads(files["amqp_routing.json"])
    entries = parsed["entries"]
    assert len(entries) == 1
    assert (entries[0]["source_piece"], entries[0]["target_piece"]) == ("a", "c")


def test_amqp_routing_json_multi_pairing_alphabetical():
    """Multiple (src, dst) AMQP pairings sort alphabetically."""
    ann = _annotations(
        pieces=[_piece("zeta"), _piece("alpha"), _piece("mike")],
        transitions=[
            _network_transition("zeta", "alpha", event="e1", transport="AMQP"),
            _network_transition("alpha", "mike", event="e2", transport="AMQP"),
            _network_transition("mike", "zeta", event="e3", transport="AMQP"),
        ],
    )
    files = emit_protobuf(ann, chart_sos_id=_CHART_SOS_ID, chart_id="multi_chart")
    parsed = json.loads(files["amqp_routing.json"])
    pairs = [(e["source_piece"], e["target_piece"]) for e in parsed["entries"]]
    assert pairs == sorted(pairs)


# ---------------------------------------------------------------------------
# Disk write
# ---------------------------------------------------------------------------


def test_emit_writes_files_when_output_dir_given(tmp_path: Path):
    """`output_dir=` writes each file under `<output_dir>/network/<chart_id>/`."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[_network_transition("a", "b", event="evt.x")],
    )
    files = emit_protobuf(
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
# Package suffix determinism
# ---------------------------------------------------------------------------


def test_package_suffix_derives_from_chart_sos_id():
    """Package name is `sos_orchestrator_<hex8>` from chart sos:id."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[_network_transition("a", "b", event="evt.x")],
    )
    files = emit_protobuf(
        ann, chart_sos_id="aabbccdd-0000-4000-8000-000000000001",
        chart_id="pkg_chart",
    )
    assert "package sos_orchestrator_aabbccdd;" in files["orchestrator.proto"]
    assert "package sos_orchestrator_aabbccdd;" in files["a_service.proto"]


def test_malformed_chart_sos_id_raises():
    """Non-hex / too-short chart_sos_id raises ProtobufEmitError."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[_network_transition("a", "b")],
    )
    with pytest.raises(ProtobufEmitError):
        emit_protobuf(ann, chart_sos_id="too-short", chart_id="x")
    with pytest.raises(ProtobufEmitError):
        emit_protobuf(ann, chart_sos_id="", chart_id="x")


def test_non_sv_identifier_piece_id_raises():
    """Piece ids that aren't SV identifiers raise."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            CrossPieceTransitionAnnotation(
                source_state_id="a",
                target_state_id="not.valid",  # dot is illegal in SV idents
                event="evt.x",
                medium=MediumAnnotation(
                    kind="network",
                    transport=TransportAnnotation(name="gRPC"),
                ),
            ),
        ],
    )
    with pytest.raises(ProtobufEmitError):
        emit_protobuf(ann, chart_sos_id=_CHART_SOS_ID, chart_id="bad_chart")


# ---------------------------------------------------------------------------
# Fixture-driven end-to-end
# ---------------------------------------------------------------------------


_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "sos_10_network"
    / "orchestrator_3piece_network.scxml"
)


def test_fixture_three_piece_network_emits_full_artifact_set():
    """End-to-end: scjson the fixture, parse, emit, verify expected
    artifacts and payload-type propagation."""
    ast = load_chart(_FIXTURE).raw_scjson
    annotations = parse_orchestrator_annotations(ast)
    files = emit_protobuf(
        annotations, chart_sos_id=_CHART_SOS_ID, chart_id="fx_chart"
    )
    # All five artifacts emitted.
    assert "orchestrator.proto" in files
    assert "client_service.proto" in files
    assert "gateway_service.proto" in files
    assert "broker_service.proto" in files
    assert "amqp_routing.json" in files

    proto = files["orchestrator.proto"]
    # Three network transitions → three message-pair sets.
    assert "ClientToGateway_evt_start_Request" in proto
    assert "ClientToBroker_evt_report_Request" in proto
    assert "GatewayToBroker_evt_broadcast_Request" in proto
    # In-process `evt.sync` SKIPPED.
    assert "evt_sync" not in proto
    # Explicit payload_type propagates.
    assert "uint32 payload = 1;" in proto
    assert "string payload = 1;" in proto
    # Default-bytes fallback for evt.report (no payload_type).
    assert "bytes payload = 1;" in proto
    assert "TODO(SOS-10-payload-type)" in proto

    # AMQP routing has two entries (client->broker, gateway->broker).
    parsed = json.loads(files["amqp_routing.json"])
    pairs = sorted(
        (e["source_piece"], e["target_piece"]) for e in parsed["entries"]
    )
    assert pairs == [("client", "broker"), ("gateway", "broker")]


def test_fixture_emit_is_deterministic():
    """Fixture-driven emit is byte-identical across two runs."""
    ast = load_chart(_FIXTURE).raw_scjson
    annotations = parse_orchestrator_annotations(ast)
    a = emit_protobuf(
        annotations, chart_sos_id=_CHART_SOS_ID, chart_id="fx_chart"
    )
    b = emit_protobuf(
        annotations, chart_sos_id=_CHART_SOS_ID, chart_id="fx_chart"
    )
    assert a == b


def test_fixture_via_from_chart_helper_uses_root_sos_id():
    """`emit_protobuf_from_chart` reads `sos:id` from the root scxml."""
    files = emit_protobuf_from_chart(_FIXTURE, chart_id="fxh_chart")
    # The fixture's sos:id is fe000000-... → first-8 hex `fe000000`.
    assert "package sos_orchestrator_fe000000;" in files["orchestrator.proto"]


# ---------------------------------------------------------------------------
# protoc parse gate (optional — skipped if protoc not installed)
# ---------------------------------------------------------------------------


def _have_protoc() -> str | None:
    return shutil.which("protoc")


def test_emitted_proto_parses_under_protoc(tmp_path: Path):
    """`protoc --descriptor_set_out=/dev/null` accepts every emitted
    proto file as syntactically valid proto3."""
    protoc = _have_protoc()
    if protoc is None:
        pytest.skip("no protoc on PATH")

    ann = _annotations(
        pieces=[_piece("client"), _piece("gateway"), _piece("broker")],
        transitions=[
            _network_transition(
                "client", "gateway", event="evt.start", payload_type="uint32",
            ),
            _network_transition(
                "gateway", "broker", event="evt.broadcast",
                transport="AMQP", payload_type="string",
            ),
            _network_transition(
                "client", "broker", event="evt.report", transport="AMQP",
            ),
        ],
    )
    files = emit_protobuf(
        ann, chart_sos_id=_CHART_SOS_ID, chart_id="protoc_chart",
        output_dir=tmp_path,
    )
    out_root = tmp_path / "network" / "protoc_chart"
    proto_files = sorted(out_root.glob("*.proto"))
    assert proto_files, "no .proto files emitted"

    result = subprocess.run(
        [
            protoc,
            f"--proto_path={out_root}",
            "--descriptor_set_out=/dev/null",
            *[str(p.name) for p in proto_files],
        ],
        cwd=str(out_root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"protoc parse failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # `files` dict was used to verify emit ordering; sanity-check.
    assert "orchestrator.proto" in files


# ---------------------------------------------------------------------------
# Duplicate-event divergence check
# ---------------------------------------------------------------------------


def test_duplicate_event_with_diverging_payload_raises():
    """Two transitions with the same (src, dst, event) but different
    payload types raise (chart-author error)."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            _network_transition("a", "b", event="evt.x", payload_type="uint32"),
            _network_transition("a", "b", event="evt.x", payload_type="string"),
        ],
    )
    with pytest.raises(ProtobufEmitError):
        emit_protobuf(ann, chart_sos_id=_CHART_SOS_ID, chart_id="dup_chart")


def test_duplicate_event_with_same_payload_dedupes():
    """Two identical transitions dedupe silently (idempotent emission)."""
    ann = _annotations(
        pieces=[_piece("a"), _piece("b")],
        transitions=[
            _network_transition("a", "b", event="evt.x", payload_type="uint32"),
            _network_transition("a", "b", event="evt.x", payload_type="uint32"),
        ],
    )
    files = emit_protobuf(
        ann, chart_sos_id=_CHART_SOS_ID, chart_id="dedupe_chart"
    )
    proto = files["orchestrator.proto"]
    # Only one request message emitted.
    assert proto.count("message AToB_evt_x_Request") == 1

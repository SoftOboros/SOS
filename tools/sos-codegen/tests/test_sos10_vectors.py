"""Tests for `sos10_vectors.py` — SOS-10E1 cross-piece bound-reachability
vector emitter.

Authority: ``docs/concepts/SOS-10-CONCEPTS.md`` §12(d) (acceptance gate),
§7 INV-S-ORCH-6 (vector-to-chart traceability across pieces), §5.2
(frozen 4-value medium enum), PCDN-SOS-10-005 (idempotency), -006 (per-
medium timeout defaults), -007 (strict one-orchestrator-per-system).
Cross-phase invariants exercised: INV-SOS-B (vectors-as-deliverable) and
INV-SOS-H (chart-vocabulary failure rendering).

Coverage shape:
    - one piece pair per medium kind (in-process, shared-memory, mmio,
      and network with both gRPC + AMQP transports);
    - an idempotent transition (medium-level + transition-level);
    - a contract-mismatch broken-protocol case (UNDECLARED_EVENT);
    - a multi-hop chain (A → B → C);
    - a timeout case per medium;
    - INV-SOS-H metadata presence + chart-vocabulary failure rendering
      check;
    - PCDN-SOS-10-007 strict-one-orchestrator rejection at the type
      boundary.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make `sos-codegen` modules importable from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from loader import load_chart  # noqa: E402
from sos10_annotations import (  # noqa: E402
    CrossPieceTransitionAnnotation,
    MediumAnnotation,
    OrchestratorAnnotations,
    PieceAnnotation,
    TransportAnnotation,
    parse_orchestrator_annotations,
)
from sos10_vectors import (  # noqa: E402
    PER_MEDIUM_TIMEOUT_MS,
    PER_TRANSPORT_TIMEOUT_MS,
    BrokenProtocolReason,
    CrossPieceVectorRecord,
    ExpectedOutcome,
    Sos10VectorEmissionError,
    VectorFamily,
    emit_cross_piece_vectors,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sos_10"
_CROSS_PIECE_CHART = _FIXTURE_DIR / "cross_piece_chart.scxml"


@pytest.fixture(scope="module")
def cross_piece_ast():
    """End-to-end load of the SOS-10E1 fixture (scjson roundtrip)."""
    return load_chart(_CROSS_PIECE_CHART).raw_scjson


@pytest.fixture(scope="module")
def cross_piece_inventory(cross_piece_ast):
    """Parsed orchestrator annotations for the fixture."""
    return parse_orchestrator_annotations(cross_piece_ast)


@pytest.fixture
def receiver_event_index():
    """Per-piece declared event-ins driving the broken-protocol path.

    Mirrors the per-piece chart contract (each piece declares which
    events it consumes). Two transitions in the fixture target pieces
    that DON'T declare the event → two broken_protocol vectors:

      - gamma fires dashboard_command at alpha; alpha declares only
        local_pulse → UNDECLARED_EVENT.
      - gamma fires analytics_event at beta; beta declares only
        start_dma → UNDECLARED_EVENT.
    """
    return {
        "alpha": ["local_pulse"],
        "beta": ["start_dma"],
        "gamma": ["stream_metrics"],
    }


# ---------------------------------------------------------------------------
# Frozen-enum + table-shape sanity
# ---------------------------------------------------------------------------


def test_vector_family_enum_is_frozen_at_five_values():
    """Per §12(d): five families — transition, timeout, idempotent_retry,
    broken_protocol, multi_hop. Adding a sixth is a Standards Action
    requiring §15 amendment."""
    assert {f.value for f in VectorFamily} == {
        "transition",
        "timeout",
        "idempotent_retry",
        "broken_protocol",
        "multi_hop",
    }


def test_per_transport_timeout_table_matches_pcdn_006():
    """PCDN-SOS-10-006 ratified table: gRPC = 5000ms, AMQP = 10000ms."""
    assert PER_TRANSPORT_TIMEOUT_MS == {"gRPC": 5000, "AMQP": 10000}


def test_per_medium_timeout_table_has_all_4_medium_kinds():
    """The per-medium table covers every value of the §5.2 frozen enum."""
    assert set(PER_MEDIUM_TIMEOUT_MS) == {
        "in-process",
        "shared-memory",
        "mmio",
        "network",
    }


# ---------------------------------------------------------------------------
# Per-medium transition coverage (one vector per medium kind)
# ---------------------------------------------------------------------------


def test_emits_one_transition_vector_per_medium_kind(cross_piece_inventory):
    """Fixture has 5 cross-piece transitions across 4 medium kinds (network
    twice for gRPC + AMQP). The transition family emits one vector per
    transition; medium kinds covered MUST include all four §5.2 values."""
    records = emit_cross_piece_vectors(cross_piece_inventory)
    transitions = [
        r for r in records if r.family is VectorFamily.TRANSITION
    ]
    media = {r.medium for r in transitions}
    assert media == {"in-process", "shared-memory", "mmio", "network"}
    assert len(transitions) == 5
    # Both network transports covered.
    transports = {r.transport for r in transitions if r.medium == "network"}
    assert transports == {"gRPC", "AMQP"}


def test_emits_one_timeout_vector_per_medium_or_transport(
    cross_piece_inventory,
):
    """Timeout family: one vector per (kind, transport) pair the chart
    uses. In-process / shared-memory / mmio collapse to one each; network
    splits into gRPC + AMQP → 5 timeout vectors total."""
    records = emit_cross_piece_vectors(cross_piece_inventory)
    timeouts = [r for r in records if r.family is VectorFamily.TIMEOUT]
    assert len(timeouts) == 5
    keys = {(r.medium, r.transport) for r in timeouts}
    assert keys == {
        ("in-process", None),
        ("shared-memory", None),
        ("mmio", None),
        ("network", "gRPC"),
        ("network", "AMQP"),
    }


def test_timeout_vectors_use_pcdn_006_defaults(cross_piece_inventory):
    """Per PCDN-SOS-10-006: gRPC default 5000ms (no override), AMQP override
    10000ms (matches default), shared-memory chart override 2000ms,
    in-process / mmio remain None (no timeout at v1)."""
    records = emit_cross_piece_vectors(cross_piece_inventory)
    timeouts_by_key = {
        (r.medium, r.transport): r
        for r in records
        if r.family is VectorFamily.TIMEOUT
    }
    assert timeouts_by_key[("network", "gRPC")].timeout_ms == 5000
    assert timeouts_by_key[("network", "AMQP")].timeout_ms == 10000
    assert timeouts_by_key[("shared-memory", None)].timeout_ms == 2000
    assert timeouts_by_key[("in-process", None)].timeout_ms is None
    assert timeouts_by_key[("mmio", None)].timeout_ms is None


# ---------------------------------------------------------------------------
# Idempotent retry (PCDN-SOS-10-005)
# ---------------------------------------------------------------------------


def test_idempotent_retry_vector_emitted_for_medium_level_annotation(
    cross_piece_inventory,
):
    """The AMQP transition in the fixture carries medium-level
    <sos:idempotent value="true"/> → one idempotent_retry vector."""
    records = emit_cross_piece_vectors(cross_piece_inventory)
    retries = [
        r for r in records if r.family is VectorFamily.IDEMPOTENT_RETRY
    ]
    assert len(retries) == 1
    r = retries[0]
    assert r.sender_piece == "gamma"
    assert r.receiver_piece == "beta"
    assert r.event == "analytics_event"
    assert r.medium == "network"
    assert r.transport == "AMQP"
    assert r.idempotent is True
    assert r.expected_outcome is ExpectedOutcome.RETRY_COLLAPSED


def test_transition_level_idempotent_override_wins_over_medium_level():
    """PCDN-SOS-10-005: per-transition `sos:idempotent` attribute is
    resolved as the override; medium-level value is preserved on the
    medium annotation. Build a minimal inventory by hand to exercise the
    override path without scjson roundtrip."""
    medium = MediumAnnotation(
        kind="network",
        transport=TransportAnnotation(name="gRPC"),
        idempotent=False,  # medium-level says no
    )
    tr = CrossPieceTransitionAnnotation(
        source_state_id="alpha",
        target_state_id="beta",
        event="evt.x",
        medium=medium,
        idempotent=True,  # transition-level override says yes
    )
    inv = OrchestratorAnnotations(
        pieces=[
            PieceAnnotation(state_id="alpha", lang="rust"),
            PieceAnnotation(state_id="beta", lang="rust"),
        ],
        transitions=[tr],
    )
    records = emit_cross_piece_vectors(inv)
    retries = [
        r for r in records if r.family is VectorFamily.IDEMPOTENT_RETRY
    ]
    assert len(retries) == 1
    assert retries[0].idempotent is True


# ---------------------------------------------------------------------------
# Broken protocol (INV-SOS-H chart-vocabulary failure rendering)
# ---------------------------------------------------------------------------


def test_broken_protocol_synthesised_when_receiver_event_index_provided(
    cross_piece_inventory, receiver_event_index
):
    """Per §12(d): contract-mismatch (sender fires event the receiver
    doesn't declare) emits a broken_protocol vector with INV-SOS-H
    chart-vocabulary failure message rendering."""
    records = emit_cross_piece_vectors(
        cross_piece_inventory,
        receiver_event_index=receiver_event_index,
    )
    broken = [
        r for r in records if r.family is VectorFamily.BROKEN_PROTOCOL
    ]
    assert len(broken) == 2
    broken_events = sorted(r.event for r in broken)
    assert broken_events == ["analytics_event", "dashboard_command"]
    for r in broken:
        assert r.expected_outcome is ExpectedOutcome.BROKEN_PROTOCOL
        assert (
            r.broken_protocol_reason is BrokenProtocolReason.UNDECLARED_EVENT
        )
        # INV-SOS-H rendering: chart vocabulary only, no raw medium
        # primitives (no protobuf field numbers, no ring-buffer offsets,
        # no NVIC vector numbers).
        assert r.failure_message is not None
        assert r.sender_piece in r.failure_message
        assert r.receiver_piece in r.failure_message
        assert r.event in r.failure_message
        assert r.medium in r.failure_message
        # Forbidden raw-medium tokens absent.
        forbidden = ("protobuf", "field=", "ring=", "NVIC", "0x")
        for tok in forbidden:
            assert tok not in r.failure_message, (
                f"raw-medium token {tok!r} leaked into chart-vocabulary "
                f"failure message — INV-SOS-H violation: {r.failure_message!r}"
            )


def test_broken_protocol_skipped_when_no_receiver_event_index(
    cross_piece_inventory,
):
    """Without a receiver_event_index argument, the broken-protocol
    family is skipped (the integration harness drives this path
    explicitly)."""
    records = emit_cross_piece_vectors(cross_piece_inventory)
    broken = [
        r for r in records if r.family is VectorFamily.BROKEN_PROTOCOL
    ]
    assert broken == []


# ---------------------------------------------------------------------------
# Multi-hop chain discovery
# ---------------------------------------------------------------------------


def test_multi_hop_chain_discovered_through_intermediate_piece(
    cross_piece_inventory,
):
    """A→B→C is discovered automatically: the fixture has
    (alpha→beta start_dma mmio) followed by (beta→gamma stream_metrics
    shared-memory). That chain MUST surface as a multi_hop record with
    sender=alpha, receiver=gamma, hops=2."""
    records = emit_cross_piece_vectors(cross_piece_inventory)
    multi = [r for r in records if r.family is VectorFamily.MULTI_HOP]
    # The fixture admits multiple chains (alpha→alpha→beta, alpha→beta→
    # gamma, beta→gamma→alpha, gamma→alpha→beta); assert the canonical
    # A=alpha → B=beta → C=gamma is one of them.
    chains_by_endpoints = {
        (r.sender_piece, r.receiver_piece): r for r in multi
    }
    assert ("alpha", "gamma") in chains_by_endpoints
    canonical = chains_by_endpoints[("alpha", "gamma")]
    assert len(canonical.hops) == 2
    assert canonical.hops[0]["sender_piece"] == "alpha"
    assert canonical.hops[0]["receiver_piece"] == "beta"
    assert canonical.hops[0]["medium"] == "mmio"
    assert canonical.hops[1]["sender_piece"] == "beta"
    assert canonical.hops[1]["receiver_piece"] == "gamma"
    assert canonical.hops[1]["medium"] == "shared-memory"


# ---------------------------------------------------------------------------
# INV-S-ORCH-6 metadata presence
# ---------------------------------------------------------------------------


def test_every_record_carries_inv_sos_h_metadata_block(
    cross_piece_ast, cross_piece_inventory, receiver_event_index
):
    """§12(d) mandates every record carries: orchestrator_chart,
    transition_id, sender_piece, receiver_piece, medium, expected_outcome.
    Verify across all families."""
    records = emit_cross_piece_vectors(
        cross_piece_inventory,
        chart_ast=cross_piece_ast,
        receiver_event_index=receiver_event_index,
    )
    assert records, "fixture must yield at least one vector"
    for r in records:
        d = r.to_dict()
        for key in (
            "orchestrator_chart",
            "transition_id",
            "sender_piece",
            "receiver_piece",
            "medium",
            "expected_outcome",
            "event",
            "spec_refs",
            "family",
        ):
            assert key in d, f"INV-S-ORCH-6 metadata missing key {key!r}"
        # Spec refs always cite §12(d), INV-S-ORCH-6, INV-SOS-B, INV-SOS-H.
        assert "SOS-10-CONCEPTS §12(d)" in r.spec_refs
        assert "INV-S-ORCH-6" in r.spec_refs
        assert "INV-SOS-B" in r.spec_refs
        assert "INV-SOS-H" in r.spec_refs


def test_orchestrator_chart_id_extracted_from_scjson_sos_id(
    cross_piece_ast, cross_piece_inventory
):
    """When chart_ast is provided AND the chart carries a sos:id
    other_attribute, every record's orchestrator_chart field MUST hold
    that UUID."""
    records = emit_cross_piece_vectors(
        cross_piece_inventory, chart_ast=cross_piece_ast
    )
    expected = "a1b2c3d4-1e5f-4a6b-8c7d-9e0f1a2b3c4d"
    for r in records:
        assert r.orchestrator_chart == expected


def test_orchestrator_chart_id_unidentified_when_chart_ast_absent(
    cross_piece_inventory,
):
    """When chart_ast is not provided, the field renders as
    ``"<unidentified>"`` so downstream tooling never has to handle None."""
    records = emit_cross_piece_vectors(cross_piece_inventory)
    for r in records:
        assert r.orchestrator_chart == "<unidentified>"


def test_transition_id_shape_matches_inv_s_orch_6_format(
    cross_piece_inventory,
):
    """Per INV-S-ORCH-6: trace key shape is V-<ord>-<family>-<event>.
    Each record's transition_id MUST satisfy that shape."""
    records = emit_cross_piece_vectors(cross_piece_inventory)
    import re
    pat = re.compile(r"^V-\d{4}-[a-z_]+-[A-Za-z0-9_.]+$")
    for r in records:
        assert pat.match(r.transition_id), (
            f"transition_id {r.transition_id!r} violates "
            f"V-<ord>-<family>-<event> shape"
        )


# ---------------------------------------------------------------------------
# PCDN-SOS-10-007 strict-one-orchestrator-per-system
# ---------------------------------------------------------------------------


def test_non_orchestratorannotations_input_raises_with_pcdn_007():
    """PCDN-SOS-10-007 strict at v1: the input MUST be exactly one
    OrchestratorAnnotations instance. Passing anything else (a list, a
    dict, two instances stitched together) is a violation of INV-S-ORCH-1
    rejected at the type boundary."""
    with pytest.raises(Sos10VectorEmissionError) as exc_info:
        emit_cross_piece_vectors({"pieces": [], "transitions": []})  # type: ignore[arg-type]
    assert "PCDN-SOS-10-007" in (exc_info.value.rule or "")

    with pytest.raises(Sos10VectorEmissionError):
        emit_cross_piece_vectors([
            OrchestratorAnnotations(pieces=[], transitions=[]),
            OrchestratorAnnotations(pieces=[], transitions=[]),
        ])  # type: ignore[arg-type]


def test_empty_pieces_inventory_rejected():
    """An orchestrator with zero pieces cannot host cross-piece events and
    violates INV-S-ORCH-1."""
    inv = OrchestratorAnnotations(pieces=[], transitions=[])
    with pytest.raises(Sos10VectorEmissionError) as exc_info:
        emit_cross_piece_vectors(inv)
    assert "INV-S-ORCH-1" in (exc_info.value.rule or "")


def test_transition_with_unknown_source_piece_rejected():
    """A transition whose source isn't a declared piece violates
    INV-S-ORCH-1 / INV-S-ORCH-2 even though the parser usually catches
    this. The emitter re-asserts at the type boundary for hand-built
    inventories."""
    inv = OrchestratorAnnotations(
        pieces=[PieceAnnotation(state_id="alpha", lang="rust")],
        transitions=[
            CrossPieceTransitionAnnotation(
                source_state_id="ghost",  # not in pieces
                target_state_id="alpha",
                event="evt",
                medium=MediumAnnotation(kind="in-process"),
            )
        ],
    )
    with pytest.raises(Sos10VectorEmissionError):
        emit_cross_piece_vectors(inv)


# ---------------------------------------------------------------------------
# Determinism + serialisability
# ---------------------------------------------------------------------------


def test_emission_is_deterministic_across_invocations(cross_piece_inventory):
    """Same orchestrator annotations + same arguments produce
    bit-identical record lists across replays (INV-SOS-G mirror)."""
    a = emit_cross_piece_vectors(cross_piece_inventory)
    b = emit_cross_piece_vectors(cross_piece_inventory)
    # Compare via to_dict() so dataclass __eq__ semantics don't mask
    # ordering or content drift.
    assert [r.to_dict() for r in a] == [r.to_dict() for r in b]


def test_records_round_trip_through_json(
    cross_piece_ast, cross_piece_inventory, receiver_event_index
):
    """Every emitted record MUST serialise to JSON cleanly (the cocotb-
    equivalent harness per PCDN-SOS-10-008 consumes this JSON)."""
    records = emit_cross_piece_vectors(
        cross_piece_inventory,
        chart_ast=cross_piece_ast,
        receiver_event_index=receiver_event_index,
    )
    serialised = json.dumps([r.to_dict() for r in records])
    reparsed = json.loads(serialised)
    assert isinstance(reparsed, list)
    assert len(reparsed) == len(records)


# ---------------------------------------------------------------------------
# Overall budget gate — ensures we emit a non-trivial vector set on the
# fixture, so future regressions that silently lose families surface.
# ---------------------------------------------------------------------------


def test_full_emission_yields_all_five_families_on_the_fixture(
    cross_piece_ast, cross_piece_inventory, receiver_event_index
):
    """End-to-end gate: the fixture is designed so all 5 families emit at
    least one record. If a future change drops a family silently, this
    test catches it."""
    records = emit_cross_piece_vectors(
        cross_piece_inventory,
        chart_ast=cross_piece_ast,
        receiver_event_index=receiver_event_index,
    )
    families_seen = {r.family for r in records}
    assert families_seen == set(VectorFamily)

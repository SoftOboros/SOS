"""Tests for ``tools/sos-codegen/sos12_boundary_vectors.py``.

Authority: ``docs/concepts/SOS-12-CONCEPTS.md`` §7.2 (boundary-vector
emission). Cross-phase invariants ``INV-SOS-B`` (vectors-as-deliverable-
at-every-layer) and ``INV-SOS-H`` (vector-to-chart traceability) from
``docs/concepts/SOS-07-CONCEPTS.md`` §6.

Test surface covers SOS-12 §13 acceptance gates that touch §7.2:

  (e) per-sub-chart vector emission contract in §7 specified;
      INV-S-DISP-1 (no replay across layers) frozen as Standards Action.
  (l) PCDN-SOS-12-006 (compile-time error on contract-mismatch) honoured.

Plus the metadata shape mandated by INV-SOS-H (chart_path, trigger,
expected, originating_invariant).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make ``sos-codegen`` modules importable from the tests/ directory.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos12_boundary_vectors import (  # noqa: E402
    BoundaryVectorError,
    DatamodelBoundary,
    DispatchEdge,
    SubChartContract,
    emit_boundary_vectors,
    emit_dispatch_tree_boundary_vectors,
    write_boundary_vectors_jsonl,
)


# ---------------------------------------------------------------------------
# Helper builders — keep test bodies focused on the assertion surface.
# ---------------------------------------------------------------------------


def _contract(
    chart_id: str = "child_chart",
    initial_state: str = "child_initial",
    events_in: tuple[str, ...] = (),
    events_out: tuple[str, ...] = (),
    invariants_maintained: tuple[str, ...] = (),
    invariants_assumed: tuple[str, ...] = (),
) -> SubChartContract:
    return SubChartContract(
        chart_id=chart_id,
        initial_state=initial_state,
        events_in=events_in,
        events_out=events_out,
        invariants_maintained=invariants_maintained,
        invariants_assumed=invariants_assumed,
        datamodel_boundary=DatamodelBoundary(),
    )


def _edge(
    contract: SubChartContract,
    *,
    parent_chart_id: str = "parent_chart",
    dispatch_state: str = "dispatching_child",
    parent_in: tuple[str, ...] | None = None,
    parent_out: tuple[str, ...] | None = None,
) -> DispatchEdge:
    # Default: parent advertises whatever the child declares — the
    # contract-matching success case.
    if parent_in is None:
        parent_in = contract.events_in
    if parent_out is None:
        parent_out = contract.events_out
    return DispatchEdge(
        parent_chart_id=parent_chart_id,
        dispatch_state=dispatch_state,
        child_contract=contract,
        parent_expected_events_in=parent_in,
        parent_expected_events_out=parent_out,
    )


# ---------------------------------------------------------------------------
# Category 1 — events_in only
# ---------------------------------------------------------------------------


def test_events_in_only_emits_one_vector_per_event():
    """§7.2 first clause: one boundary vector per declared events-in member."""
    contract = _contract(events_in=("tcp.bytes_received", "timer.body_timeout"))
    vectors = emit_boundary_vectors(_edge(contract))

    assert len(vectors) == 2
    assert all(v["kind"] == "events_in" for v in vectors)
    assert [v["metadata"]["trigger"] for v in vectors] == [
        "tcp.bytes_received",
        "timer.body_timeout",
    ]
    # All events-in vectors target the contract-declared initial state
    # (INV-S-DISP-1: never an internal sub-chart state).
    assert all(
        v["metadata"]["expected"] == contract.initial_state for v in vectors
    )


def test_events_in_only_vector_ids_are_zero_padded_and_sequential():
    contract = _contract(events_in=("e1", "e2", "e3"))
    vectors = emit_boundary_vectors(_edge(contract))

    ids = [v["vector_id"] for v in vectors]
    assert ids == [
        "sos12-boundary-parent_chart-child_chart-0000",
        "sos12-boundary-parent_chart-child_chart-0001",
        "sos12-boundary-parent_chart-child_chart-0002",
    ]


# ---------------------------------------------------------------------------
# Category 2 — events_out only
# ---------------------------------------------------------------------------


def test_events_out_only_emits_one_vector_per_event():
    """§7.2 second clause: one vector per events-out member; parent observes."""
    contract = _contract(events_out=("method.complete", "method.error"))
    vectors = emit_boundary_vectors(_edge(contract))

    assert len(vectors) == 2
    assert all(v["kind"] == "events_out" for v in vectors)
    # The expected value is the event itself — the parent's observable
    # surface at the dispatch edge.
    assert {v["metadata"]["expected"] for v in vectors} == {
        "method.complete",
        "method.error",
    }
    # All events-out vectors carry trigger = "child.run_to_event" — the
    # parent runs the child until it emits.
    assert all(
        v["metadata"]["trigger"] == "child.run_to_event" for v in vectors
    )


# ---------------------------------------------------------------------------
# Category 3 — mixed (events_in + events_out + invariants)
# ---------------------------------------------------------------------------


def test_mixed_contract_emits_all_three_categories_in_block_order():
    """§7.2: events-in block, then events-out block, then invariants block."""
    contract = _contract(
        events_in=("tcp.bytes_received",),
        events_out=("method.complete", "method.error"),
        invariants_maintained=("INV-GET-1-headers-bounded",),
        invariants_assumed=("INV-HTTP-1-request-line-parsed",),
    )
    vectors = emit_boundary_vectors(_edge(contract))

    # 1 + 2 + 1 + 1 = 5 vectors.
    assert len(vectors) == 5
    kinds = [v["kind"] for v in vectors]
    assert kinds == [
        "events_in",
        "events_out",
        "events_out",
        "invariant_maintained",
        "invariant_assumed",
    ]


# ---------------------------------------------------------------------------
# Category 4 — invariant-only contract
# ---------------------------------------------------------------------------


def test_invariant_only_contract_emits_invariant_vectors():
    contract = _contract(
        invariants_maintained=("INV-X", "INV-Y"),
        invariants_assumed=("INV-Z",),
    )
    vectors = emit_boundary_vectors(_edge(contract))

    assert len(vectors) == 3
    assert [v["kind"] for v in vectors] == [
        "invariant_maintained",
        "invariant_maintained",
        "invariant_assumed",
    ]
    # Each invariant vector names its originating-invariant id per
    # INV-SOS-H — this is the load-bearing traceability surface.
    assert [v["metadata"]["originating_invariant"] for v in vectors] == [
        "INV-X",
        "INV-Y",
        "INV-Z",
    ]


# ---------------------------------------------------------------------------
# Category 5 — zero-event (degenerate) contract
# ---------------------------------------------------------------------------


def test_zero_event_contract_emits_empty_vector_list():
    """The empty contract is permitted; emission returns no vectors."""
    contract = _contract()  # everything empty
    vectors = emit_boundary_vectors(_edge(contract))

    assert vectors == []


# ---------------------------------------------------------------------------
# Category 6 — all three categories present
# ---------------------------------------------------------------------------


def test_all_three_categories_present_yields_total_count():
    """§7.2 constant-size claim: count = sum of the four declared cardinalities."""
    contract = _contract(
        events_in=("a", "b", "c"),
        events_out=("x", "y"),
        invariants_maintained=("M1", "M2", "M3", "M4"),
        invariants_assumed=("A1",),
    )
    vectors = emit_boundary_vectors(_edge(contract))

    # 3 + 2 + 4 + 1 = 10.
    assert len(vectors) == 10


# ---------------------------------------------------------------------------
# Category 7 — contract-mismatch (PCDN-SOS-12-006)
# ---------------------------------------------------------------------------


def test_contract_mismatch_events_in_raises_pcdn_006_error():
    """PCDN-SOS-12-006: parent does not route a declared events-in → reject."""
    contract = _contract(events_in=("tcp.bytes_received", "timer.body_timeout"))
    bad_edge = _edge(
        contract,
        parent_in=("tcp.bytes_received",),  # missing 'timer.body_timeout'
    )

    with pytest.raises(BoundaryVectorError) as exc_info:
        emit_boundary_vectors(bad_edge)

    assert exc_info.value.pcdn == "PCDN-SOS-12-006"
    assert exc_info.value.invariant == "INV-S-DISP-2"
    assert "timer.body_timeout" in str(exc_info.value)
    # Error message references the offending dispatch edge per
    # INV-SOS-H chart-vocabulary diagnosis.
    assert "parent_chart" in str(exc_info.value)
    assert "child_chart" in str(exc_info.value)


def test_contract_mismatch_events_out_raises_pcdn_006_error():
    contract = _contract(events_out=("method.complete", "method.error"))
    bad_edge = _edge(
        contract,
        parent_out=("method.complete",),  # missing 'method.error'
    )

    with pytest.raises(BoundaryVectorError) as exc_info:
        emit_boundary_vectors(bad_edge)

    assert exc_info.value.pcdn == "PCDN-SOS-12-006"
    assert "method.error" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Category 8 — single dispatch path (smoke through tree-level emitter)
# ---------------------------------------------------------------------------


def test_single_dispatch_path_via_tree_emitter():
    contract = _contract(events_in=("e1",), events_out=("o1",))
    tree_vectors = emit_dispatch_tree_boundary_vectors([_edge(contract)])

    assert len(tree_vectors) == 2
    # The tree emitter is a sum-of-edges shape — same metadata
    # presence as the per-edge emitter (INV-SOS-F sum-not-product).
    for v in tree_vectors:
        assert v["metadata"]["chart_path"] == (
            "parent_chart.dispatching_child.child_chart"
        )


# ---------------------------------------------------------------------------
# Category 9 — multiple dispatch paths
# ---------------------------------------------------------------------------


def test_multiple_dispatch_paths_sum_not_product():
    """§6.3 sum-not-product realised at vector-emission surface."""
    c_a = _contract(
        chart_id="http_get",
        events_in=("tcp.bytes_received",),
        events_out=("method.complete",),
    )
    c_b = _contract(
        chart_id="http_post",
        events_in=("tcp.bytes_received", "timer.body_timeout"),
        events_out=("method.complete", "method.error"),
    )
    edges = [
        _edge(c_a, dispatch_state="dispatching_get"),
        _edge(c_b, dispatch_state="dispatching_post"),
    ]
    vectors = emit_dispatch_tree_boundary_vectors(edges)

    # Sum-not-product: 2 + 4 = 6 vectors (NOT 2 * 4 = 8).
    assert len(vectors) == 6
    # Each edge's vectors carry the per-edge chart_path — they are
    # local-bound per §7.3 (no replay across layers).
    paths = {v["metadata"]["chart_path"] for v in vectors}
    assert paths == {
        "parent_chart.dispatching_get.http_get",
        "parent_chart.dispatching_post.http_post",
    }


# ---------------------------------------------------------------------------
# INV-SOS-H metadata presence
# ---------------------------------------------------------------------------


def test_inv_sos_h_metadata_present_on_every_vector():
    """INV-SOS-H: every vector carries chart_path/trigger/expected/invariant keys."""
    contract = _contract(
        events_in=("e1",),
        events_out=("o1",),
        invariants_maintained=("INV-A",),
        invariants_assumed=("INV-B",),
    )
    vectors = emit_boundary_vectors(_edge(contract))

    assert vectors  # sanity
    for v in vectors:
        meta = v["metadata"]
        # All four INV-SOS-H keys MUST be present on every vector.
        for k in ("chart_path", "trigger", "expected", "originating_invariant"):
            assert k in meta
        # chart_path is the §3 dispatch-tree address.
        assert meta["chart_path"] == "parent_chart.dispatching_child.child_chart"
        # Event/invariant vectors fill originating_invariant only when
        # the kind is invariant_*; events_in / events_out leave it None.
        if v["kind"] in ("events_in", "events_out"):
            assert meta["originating_invariant"] is None
        else:
            assert meta["originating_invariant"] is not None


# ---------------------------------------------------------------------------
# Schema conformance — SOS-03 boundary-vector subtype shape
# ---------------------------------------------------------------------------


def test_vector_records_round_trip_through_json():
    """SOS-03 §6: vector wire format is JSON — round-trip must be lossless."""
    contract = _contract(
        events_in=("e1",),
        events_out=("o1",),
        invariants_maintained=("INV-A",),
    )
    vectors = emit_boundary_vectors(_edge(contract))

    for v in vectors:
        # ensure_ascii=False matches the on-disk encoding used by the
        # JSONL writer; sort_keys=False preserves insertion order.
        wire = json.dumps(v, ensure_ascii=False)
        round_tripped = json.loads(wire)
        assert round_tripped == v


def test_vector_records_carry_sos03_required_fields():
    contract = _contract(events_in=("e1",))
    vectors = emit_boundary_vectors(_edge(contract))

    for v in vectors:
        # Shape compatible with the SOS-03 vector fixture top level
        # (vector_id / category / origin / description / tags).
        for required in (
            "vector_id",
            "category",
            "origin",
            "kind",
            "description",
            "tags",
            "metadata",
        ):
            assert required in v, f"missing required field {required!r}"
        assert v["category"] == "Boundary"
        assert v["origin"] == "Authored"
        assert isinstance(v["tags"], list)
        # Tag list cross-indexes the dispatch-tree address.
        assert "sos12" in v["tags"]
        assert "boundary" in v["tags"]


# ---------------------------------------------------------------------------
# JSONL writer
# ---------------------------------------------------------------------------


def test_write_boundary_vectors_jsonl_emits_one_record_per_line(tmp_path: Path):
    contract = _contract(
        events_in=("e1", "e2"),
        events_out=("o1",),
    )
    out = tmp_path / "subdir" / "boundary.jsonl"
    written = write_boundary_vectors_jsonl(_edge(contract), out)

    assert written.exists()
    lines = written.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # 2 events_in + 1 events_out

    # Every line is exactly one JSON object — SOS-03 JSONL shape.
    parsed = [json.loads(line) for line in lines]
    assert [v["metadata"]["trigger"] for v in parsed] == [
        "e1",
        "e2",
        "child.run_to_event",
    ]


# ---------------------------------------------------------------------------
# Vector-id seq validation
# ---------------------------------------------------------------------------


def test_vector_id_seq_is_zero_padded_to_four_digits():
    """The ``sos12-boundary-<parent>-<child>-NNNN`` shape uses 4-digit padding."""
    # 12 events-in forces sequence numbers across the 0009 / 0010
    # boundary so the padding is visible.
    contract = _contract(
        events_in=tuple(f"e{i}" for i in range(12)),
    )
    vectors = emit_boundary_vectors(_edge(contract))

    ids = [v["vector_id"] for v in vectors]
    assert ids[0].endswith("-0000")
    assert ids[9].endswith("-0009")
    assert ids[10].endswith("-0010")
    assert ids[11].endswith("-0011")

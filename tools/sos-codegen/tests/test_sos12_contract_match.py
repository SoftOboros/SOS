"""Tests for ``tools/sos-codegen/sos12_contract_match.py``.

Authority: ``docs/concepts/SOS-12-CONCEPTS.md`` §5.3 (contract-matching
algebra) + §5.2 (datamodel boundary semantics) + §10.1 INV-S-DISP-2
(contract-matching is mandatory) + PCDN-SOS-12-006 (compile-time error
on mismatch). Cross-phase invariants ``INV-SOS-G`` (verified-codegen
position) and ``INV-SOS-H`` (vector-to-chart traceability) from
``docs/concepts/SOS-07-CONCEPTS.md`` §6.

Test surface covers SOS-12 §13 acceptance gates that touch the
contract-matching verifier:

  (c) Dispatch semantics + contract-matching failure mode in §5.3
      frozen per PCDN-006 resolution (compile-time error).
  (h) INV-S-DISP-2 enforcement (every dispatch boundary MUST have a
      contract-match check).

Plus the diagnostic-vocabulary shape mandated by INV-SOS-H
(``chart_path`` field on every failure).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make ``sos-codegen`` modules importable from the tests/ directory.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos12_annotations import (  # noqa: E402
    Contract,
    DispatchAnnotation,
    DispatchInventory,
)
from sos12_contract_match import (  # noqa: E402
    PERMITTED_CLAUSES,
    ContractMismatchError,
    DispatchContractEdge,
    simple_edge_provider,
    verify_contract_match,
    verify_inventory,
)


# ---------------------------------------------------------------------------
# Helper builders — keep test bodies focused on the assertion surface.
# ---------------------------------------------------------------------------


def _contract(
    events_in: tuple[str, ...] = (),
    events_out: tuple[str, ...] = (),
    invariants_maintained: tuple[str, ...] = (),
    invariants_assumed: tuple[str, ...] = (),
    reads: tuple[str, ...] = (),
    writes: tuple[str, ...] = (),
) -> Contract:
    return Contract(
        events_in=events_in,
        events_out=events_out,
        invariants_maintained=invariants_maintained,
        invariants_assumed=invariants_assumed,
        reads=reads,
        writes=writes,
    )


def _edge(
    child_contract: Contract,
    *,
    parent_chart_id: str = "parent.scxml",
    parent_state_id: str = "dispatching_child",
    child_chart_id: str = "child.scxml",
    parent_in: tuple[str, ...] | None = None,
    parent_out: tuple[str, ...] | None = None,
    parent_maintained: tuple[str, ...] = (),
    parent_assumed: tuple[str, ...] = (),
    parent_writes: tuple[str, ...] | None = None,
    parent_reads: tuple[str, ...] | None = None,
) -> DispatchContractEdge:
    """Build a DispatchContractEdge. Defaults match the child's contract
    so the matching success case is the default."""
    if parent_in is None:
        parent_in = child_contract.events_in
    if parent_out is None:
        parent_out = child_contract.events_out
    if parent_writes is None:
        parent_writes = child_contract.reads
    if parent_reads is None:
        parent_reads = child_contract.writes
    return DispatchContractEdge(
        parent_chart_id=parent_chart_id,
        parent_state_id=parent_state_id,
        child_chart_id=child_chart_id,
        child_contract=child_contract,
        parent_expected_events_in=parent_in,
        parent_expected_events_out=parent_out,
        parent_maintained_invariants=parent_maintained,
        parent_assumed_invariants=parent_assumed,
        parent_writes_before_dispatch=parent_writes,
        parent_reads_after_dispatch=parent_reads,
    )


# ---------------------------------------------------------------------------
# Sanity — frozen clause enumeration
# ---------------------------------------------------------------------------


def test_permitted_clauses_is_the_six_section_5_3_clauses():
    """The clause enum freezes exactly the six §5.3 sub-clauses."""
    assert PERMITTED_CLAUSES == frozenset(
        {
            "events_in",
            "events_out",
            "invariants_maintained",
            "invariants_assumed",
            "reads",
            "writes",
        }
    )


def test_contract_mismatch_error_rejects_unknown_clause():
    """Standards Action: adding a clause needs §15 amendment."""
    with pytest.raises(ValueError, match="not in PERMITTED_CLAUSES"):
        ContractMismatchError("bogus", clause="not_a_real_clause")


# ---------------------------------------------------------------------------
# Clause 1 — events_in
# ---------------------------------------------------------------------------


def test_events_in_match_passes_when_parent_routes_all_child_events():
    """Success case: parent_in is a superset of child events_in."""
    child = _contract(events_in=("tcp.bytes", "timer.tick"))
    edge = _edge(child, parent_in=("tcp.bytes", "timer.tick", "extra.event"))
    verify_contract_match(edge)  # MUST NOT raise


def test_events_in_mismatch_raises_with_missing_events_named():
    """Parent fires events the child does not declare? Actually inverse:
    child declares events_in the parent doesn't route — that's the §5.3
    failure mode this clause catches."""
    child = _contract(events_in=("tcp.bytes", "timer.tick"))
    edge = _edge(child, parent_in=("tcp.bytes",))  # missing timer.tick
    with pytest.raises(ContractMismatchError) as exc_info:
        verify_contract_match(edge)
    err = exc_info.value
    assert err.clause == "events_in"
    assert err.missing == frozenset({"timer.tick"})
    assert err.pcdn == "PCDN-SOS-12-006"
    assert err.invariant == "INV-S-DISP-2"
    assert err.chart_path is not None
    assert "child.scxml" in err.chart_path
    assert "dispatching_child" in err.chart_path
    assert err.child_chart == "child.scxml"


# ---------------------------------------------------------------------------
# Clause 2 — events_out
# ---------------------------------------------------------------------------


def test_events_out_match_passes_when_parent_observes_all_child_events():
    child = _contract(events_out=("method.complete", "method.error"))
    edge = _edge(child, parent_out=("method.complete", "method.error", "also.observed"))
    verify_contract_match(edge)  # MUST NOT raise


def test_events_out_mismatch_raises_when_child_emits_unobserved_event():
    """Child emits events_out the parent does not handle — §5.3 failure."""
    child = _contract(events_out=("method.complete", "method.error"))
    edge = _edge(child, parent_out=("method.complete",))  # missing method.error
    with pytest.raises(ContractMismatchError) as exc_info:
        verify_contract_match(edge)
    err = exc_info.value
    assert err.clause == "events_out"
    assert err.missing == frozenset({"method.error"})
    assert "method.error" in str(err)


# ---------------------------------------------------------------------------
# Clause 4 — invariants_assumed
# ---------------------------------------------------------------------------


def test_invariants_assumed_match_passes_when_parent_maintains_all():
    """Success case: child's assumed-of-environment ⊆ parent's maintained."""
    child = _contract(invariants_assumed=("INV-HTTP-1-request-line-parsed",))
    edge = _edge(
        child,
        parent_maintained=("INV-HTTP-1-request-line-parsed", "INV-OTHER"),
    )
    verify_contract_match(edge)  # MUST NOT raise


def test_invariants_assumed_mismatch_raises_when_parent_lacks_invariant():
    child = _contract(invariants_assumed=("INV-HTTP-1-request-line-parsed",))
    edge = _edge(child, parent_maintained=())  # parent maintains nothing
    with pytest.raises(ContractMismatchError) as exc_info:
        verify_contract_match(edge)
    err = exc_info.value
    assert err.clause == "invariants_assumed"
    assert err.missing == frozenset({"INV-HTTP-1-request-line-parsed"})


# ---------------------------------------------------------------------------
# Clause 3 — invariants_maintained (v1 no-op; clause kept for future)
# ---------------------------------------------------------------------------


def test_invariants_maintained_is_v1_no_op():
    """v1 has no semantic check for invariants_maintained; documented
    limitation. The clause stays in PERMITTED_CLAUSES so future grammar-
    aware checks can fire on this clause without enum churn."""
    child = _contract(invariants_maintained=("INV-GET-1-headers-bounded",))
    # Parent assumes nothing; child maintains an invariant. v1 must NOT raise.
    edge = _edge(child, parent_assumed=())
    verify_contract_match(edge)
    # And even with a collision — still no-op at v1.
    edge2 = _edge(child, parent_assumed=("INV-GET-1-headers-bounded",))
    verify_contract_match(edge2)


# ---------------------------------------------------------------------------
# Clause 5 — reads (write-before-read at boundary)
# ---------------------------------------------------------------------------


def test_reads_match_passes_when_parent_writes_all_child_reads():
    child = _contract(reads=("parsed_method", "parsed_uri"))
    edge = _edge(child, parent_writes=("parsed_method", "parsed_uri", "extra_field"))
    verify_contract_match(edge)  # MUST NOT raise


def test_reads_mismatch_raises_when_parent_does_not_write_field():
    """Child reads a datamodel field the parent never wrote before dispatch."""
    child = _contract(reads=("parsed_method", "parsed_uri"))
    edge = _edge(child, parent_writes=("parsed_method",))  # missing parsed_uri
    with pytest.raises(ContractMismatchError) as exc_info:
        verify_contract_match(edge)
    err = exc_info.value
    assert err.clause == "reads"
    assert err.missing == frozenset({"parsed_uri"})


# ---------------------------------------------------------------------------
# Clause 6 — writes (write-before-read on return)
# ---------------------------------------------------------------------------


def test_writes_match_passes_when_parent_reads_all_child_writes():
    child = _contract(writes=("response_status", "response_headers"))
    edge = _edge(child, parent_reads=("response_status", "response_headers"))
    verify_contract_match(edge)  # MUST NOT raise


def test_writes_mismatch_raises_when_parent_does_not_read_field():
    """Child writes a field the parent never reads — dead-code at boundary,
    most likely a chart-author typo. PCDN-006: compile-time error."""
    child = _contract(writes=("response_status", "response_headers"))
    edge = _edge(child, parent_reads=("response_status",))  # missing response_headers
    with pytest.raises(ContractMismatchError) as exc_info:
        verify_contract_match(edge)
    err = exc_info.value
    assert err.clause == "writes"
    assert err.missing == frozenset({"response_headers"})


def test_empty_writes_is_trivially_ok():
    """Child contract with no writes never raises clause-6 regardless of
    parent's read set."""
    child = _contract(reads=("x",), writes=())
    edge = _edge(child, parent_writes=("x",), parent_reads=())
    verify_contract_match(edge)


# ---------------------------------------------------------------------------
# Chart_path / metadata — INV-SOS-H traceability
# ---------------------------------------------------------------------------


def test_chart_path_shape_is_parent_state_child():
    """INV-SOS-H: chart_path = <parent_chart_id>.<parent_state_id>.<child_chart_id>."""
    child = _contract(events_in=("e",))
    edge = _edge(
        child,
        parent_chart_id="http_top.scxml",
        parent_state_id="dispatching_get",
        child_chart_id="http_get.scxml",
        parent_in=(),
    )
    with pytest.raises(ContractMismatchError) as exc_info:
        verify_contract_match(edge)
    err = exc_info.value
    assert err.chart_path == "http_top.scxml.dispatching_get.http_get.scxml"


def test_pcdn_and_invariant_always_populated():
    """Every ContractMismatchError carries PCDN-006 + INV-S-DISP-2."""
    child = _contract(events_in=("e",))
    edge = _edge(child, parent_in=())
    with pytest.raises(ContractMismatchError) as exc_info:
        verify_contract_match(edge)
    assert exc_info.value.pcdn == "PCDN-SOS-12-006"
    assert exc_info.value.invariant == "INV-S-DISP-2"


# ---------------------------------------------------------------------------
# Multi-clause edges — first-failure semantics
# ---------------------------------------------------------------------------


def test_first_failure_is_events_in_when_both_events_clauses_fail():
    """Verifier checks events_in before events_out — first-failure halts."""
    child = _contract(events_in=("a",), events_out=("b",))
    edge = _edge(child, parent_in=(), parent_out=())
    with pytest.raises(ContractMismatchError) as exc_info:
        verify_contract_match(edge)
    assert exc_info.value.clause == "events_in"


def test_fully_empty_contract_trivially_passes():
    """An edge whose child has no declared surface is trivially OK."""
    child = _contract()
    edge = _edge(child)
    verify_contract_match(edge)


# ---------------------------------------------------------------------------
# Inventory walker — verify_inventory + simple_edge_provider
# ---------------------------------------------------------------------------


def test_verify_inventory_clean_three_level_tree_passes():
    """A 3-level dispatch tree where every contract matches: no raise.

    Note on simple_edge_provider semantics: per the §5.2 four-set
    algebra each parent's chart-level contract's ``writes`` is the
    env-writes set the child reads from, and the parent's ``reads`` is
    the env-reads set the child writes to. So for a clean tree, each
    intermediate chart must declare writes ⊇ the child's reads AND
    reads ⊇ the child's writes — the env-side fields flow downward."""
    # Leaf: http_get reads parsed_method (the parent provided it) and
    # writes response_status (the parent reads it back).
    leaf_contract = Contract(
        events_in=("tcp.bytes",),
        events_out=("method.complete",),
        reads=("parsed_method",),
        writes=("response_status",),
    )
    leaf_inv = DispatchInventory(
        chart_ref="http_get.scxml",
        contract=leaf_contract,
        depth=2,
    )
    # Middle: http_method whose own contract matches what http_top dispatches
    # AND whose dispatch into http_get is also clean. For
    # simple_edge_provider, the middle's contract serves as BOTH the
    # parent expectation for http_get AND the surface its parent
    # http_top sees. Datamodel boundary: middle writes parsed_method
    # (so leaf can read it) and reads response_status (so leaf's write
    # has an observer).
    middle_contract = Contract(
        events_in=("tcp.bytes",),
        events_out=("method.complete",),
        reads=("response_status",),
        writes=("parsed_method",),
    )
    middle_dispatch = DispatchAnnotation(
        parent_state_id="dispatching_handler",
        ref="http_get.scxml",
    )
    middle_inv = DispatchInventory(
        chart_ref="http_method.scxml",
        contract=middle_contract,
        dispatches=(middle_dispatch,),
        sub_inventories=(leaf_inv,),
        depth=1,
    )
    # Root: http_top dispatches into http_method — same env-side mirror.
    # Root writes the fields middle reads, reads the fields middle writes.
    root_contract = Contract(
        events_in=("tcp.bytes",),
        events_out=("method.complete",),
        reads=("parsed_method",),
        writes=("response_status",),
    )
    root_dispatch = DispatchAnnotation(
        parent_state_id="dispatching_method",
        ref="http_method.scxml",
    )
    root_inv = DispatchInventory(
        chart_ref="http_top.scxml",
        contract=root_contract,
        dispatches=(root_dispatch,),
        sub_inventories=(middle_inv,),
        depth=0,
    )

    verify_inventory(root_inv)  # MUST NOT raise


def test_verify_inventory_three_level_with_deep_mismatch_names_path():
    """The mismatch is at the LEAF level; the walker recurses down and
    raises with the chart_path naming the failing depth-2 edge."""
    # Leaf has an events_in the middle does not route
    leaf_contract = Contract(events_in=("tcp.bytes", "unrouted.event"))
    leaf_inv = DispatchInventory(
        chart_ref="http_get.scxml",
        contract=leaf_contract,
        depth=2,
    )
    # Middle only routes tcp.bytes
    middle_contract = Contract(events_in=("tcp.bytes",))
    middle_dispatch = DispatchAnnotation(
        parent_state_id="dispatching_handler",
        ref="http_get.scxml",
    )
    middle_inv = DispatchInventory(
        chart_ref="http_method.scxml",
        contract=middle_contract,
        dispatches=(middle_dispatch,),
        sub_inventories=(leaf_inv,),
        depth=1,
    )
    # Root cleanly matches middle
    root_contract = Contract(events_in=("tcp.bytes",))
    root_dispatch = DispatchAnnotation(
        parent_state_id="dispatching_method",
        ref="http_method.scxml",
    )
    root_inv = DispatchInventory(
        chart_ref="http_top.scxml",
        contract=root_contract,
        dispatches=(root_dispatch,),
        sub_inventories=(middle_inv,),
        depth=0,
    )

    with pytest.raises(ContractMismatchError) as exc_info:
        verify_inventory(root_inv)
    err = exc_info.value
    assert err.clause == "events_in"
    assert err.missing == frozenset({"unrouted.event"})
    # chart_path names the FAILING (deep) edge:
    # http_method.scxml.dispatching_handler.http_get.scxml
    assert err.chart_path == (
        "http_method.scxml.dispatching_handler.http_get.scxml"
    )


def test_verify_inventory_no_dispatches_is_no_op():
    """A root inventory with no dispatches has nothing to verify."""
    inv = DispatchInventory(chart_ref="solo.scxml")
    verify_inventory(inv)  # MUST NOT raise


def test_verify_inventory_skips_unresolved_refs():
    """Annotations whose resolved_path / matching sub_inventory are
    missing are skipped (Wave-2 chart-id-token resolution is out of
    scope here). This is per the walker's documented v1 behaviour."""
    dispatch = DispatchAnnotation(
        parent_state_id="dispatching",
        ref="not_a_real_chart_id",
    )
    inv = DispatchInventory(
        chart_ref="parent.scxml",
        contract=Contract(),
        dispatches=(dispatch,),
        unresolved_refs=("not_a_real_chart_id",),
        # no matching sub_inventories
    )
    verify_inventory(inv)  # MUST NOT raise


def test_simple_edge_provider_uses_parent_chart_contract():
    """The reference edge_provider derives parent expectation from the
    parent inventory's own chart-level contract."""
    parent_contract = Contract(
        events_in=("a", "b"),
        events_out=("x",),
        invariants_maintained=("INV-P",),
        reads=("env_r",),
        writes=("env_w",),
    )
    child_contract = Contract(
        events_in=("a",),
        events_out=("x",),
        reads=("env_w",),
        writes=("env_r",),
    )
    parent_inv = DispatchInventory(
        chart_ref="parent.scxml",
        contract=parent_contract,
    )
    child_inv = DispatchInventory(
        chart_ref="child.scxml",
        contract=child_contract,
    )
    annotation = DispatchAnnotation(parent_state_id="s", ref="child.scxml")

    edge = simple_edge_provider(parent_inv, annotation, child_inv)
    assert edge.parent_chart_id == "parent.scxml"
    assert edge.parent_state_id == "s"
    assert edge.child_chart_id == "child.scxml"
    assert edge.parent_expected_events_in == ("a", "b")
    assert edge.parent_expected_events_out == ("x",)
    assert edge.parent_writes_before_dispatch == ("env_w",)
    assert edge.parent_reads_after_dispatch == ("env_r",)
    # And this edge should pass verification:
    verify_contract_match(edge)


def test_verify_inventory_top_level_chart_with_no_contract_fails_when_child_demands():
    """Edge case: a top-level chart whose own contract is None has empty
    parent expectations under simple_edge_provider — so any non-empty
    child contract raises. This is the documented behaviour: parent
    MUST declare what it routes."""
    child = Contract(events_in=("required.event",))
    child_inv = DispatchInventory(
        chart_ref="child.scxml",
        contract=child,
    )
    annotation = DispatchAnnotation(parent_state_id="s", ref="child.scxml")
    parent_inv = DispatchInventory(
        chart_ref="parent.scxml",
        contract=None,
        dispatches=(annotation,),
        sub_inventories=(child_inv,),
    )
    with pytest.raises(ContractMismatchError) as exc_info:
        verify_inventory(parent_inv)
    assert exc_info.value.clause == "events_in"
    assert exc_info.value.missing == frozenset({"required.event"})


def test_verify_inventory_custom_edge_provider_overrides_default():
    """Callers MAY supply a custom edge_provider to override the
    simple_edge_provider's chart-level-contract derivation."""
    # Build inventory where simple_edge_provider would FAIL but a custom
    # provider that supplies broader parent expectations succeeds.
    parent_inv = DispatchInventory(
        chart_ref="parent.scxml",
        contract=Contract(),  # empty — would fail simple
        dispatches=(DispatchAnnotation(parent_state_id="s", ref="child.scxml"),),
        sub_inventories=(
            DispatchInventory(
                chart_ref="child.scxml",
                contract=Contract(events_in=("e",)),
            ),
        ),
    )

    # simple provider raises:
    with pytest.raises(ContractMismatchError):
        verify_inventory(parent_inv)

    # Custom provider that fabricates a broader parent expectation:
    def custom(parent, ann, child):
        return DispatchContractEdge(
            parent_chart_id=parent.chart_ref,
            parent_state_id=ann.parent_state_id,
            child_chart_id=child.chart_ref,
            child_contract=child.contract or Contract(),
            parent_expected_events_in=("e",),
        )

    verify_inventory(parent_inv, edge_provider=custom)  # MUST NOT raise

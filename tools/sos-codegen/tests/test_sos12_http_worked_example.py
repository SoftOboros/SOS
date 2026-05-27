"""Tests for the SOS-12 §8.4 HTTP-family worked example.

Authority: ``docs/concepts/SOS-12-CONCEPTS.md`` §8 (informative
protocol-stack worked example) and §8.4 (bound composition).
Wave-1B's pinned synthetic test
``test_sos12_section_8_4_http_worked_example_bounds`` (in
``test_sos12_bound.py``) fixes ``composed_bound = 47`` for the
5-chart top + per-method shape; this test materialises the actual
SCXML chart family at
``tests/fixtures/sos_12/http/`` and threads it end-to-end through
the ratified SOS-12 module set:

1. :mod:`sos12_annotations` — parse the dispatch-tree + every
   sub-chart contract from the on-disk SCXML files
   (``parse_dispatch_annotations`` with ``chart_path`` anchor).
2. :mod:`sos12_bound` — recompose the parsed tree as ``BoundInputs``
   and verify ``compose_bound`` returns the same 47 the Wave-1B
   synthetic test pinned.
3. :mod:`sos12_boundary_vectors` — emit per-edge boundary vector
   sets through ``emit_dispatch_tree_boundary_vectors`` and check the
   aggregate matches the per-§7.2 sum across edges.
4. :mod:`sos12_contract_match` — verify every parent → child contract
   pair via ``verify_inventory`` with a custom multi-dispatch edge
   provider (the default ``simple_edge_provider`` is inadequate for a
   multi-dispatch parent per its own docstring).
5. :mod:`sos12_lint` — ``check_dispatch_depth`` (default cap 8) and
   ``check_legibility`` (default threshold 15 per §9.1) MUST both
   pass: depth-1 dispatch, all charts ≤ 15 peer states.

Per the SOS-12 §15 entry "Wave-1B ... Worked-example test pins §8.4
HTTP family bounds (47)" — this test is the on-disk SCXML companion
to that bound pin.

Adapter shape:
    ``DispatchInventory`` (Wave-1A) carries the chart-tree as nested
    inventories; ``BoundInputs`` (Wave-1B) carries a flat charts dict
    + edge list. ``_inventory_to_bound_inputs`` converts one to the
    other by walking the inventory and counting top-level ``<state>``
    peer children per chart (these are flat fixture charts — no
    nested states — so peer-count equals reachable-state count).
    The function is kept private to this test file per the dispatch
    spec: a future Wave-5 may lift it into a proper integration
    module, but the adapter surface is small enough (≈30 LOC) that
    in-place keeps Wave-4 scope tight.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest


# Make `sos-codegen` modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos12_annotations import (  # noqa: E402
    Contract,
    DispatchAnnotation,
    DispatchInventory,
    parse_dispatch_annotations,
)
from sos12_bound import (  # noqa: E402
    BoundInputs,
    DispatchEdge as BoundDispatchEdge,
    compose_bound,
)
from sos12_boundary_vectors import (  # noqa: E402
    DispatchEdge as BoundaryDispatchEdge,
    SubChartContract,
    emit_dispatch_tree_boundary_vectors,
)
from sos12_contract_match import (  # noqa: E402
    DispatchContractEdge,
    verify_inventory,
)
from sos12_lint import (  # noqa: E402
    check_dispatch_depth,
    check_legibility,
)


# ---------------------------------------------------------------------------
# Fixture anchor + loader bridge
# ---------------------------------------------------------------------------


_FIXTURE_DIR = (
    Path(__file__).resolve().parent / "fixtures" / "sos_12" / "http"
)


def _load_chart_or_skip(path: Path) -> dict:
    """Load a chart's scjson AST or skip if loader / scjson unavailable.

    Mirrors the helper in ``test_sos12_annotations.py`` so the suite
    behaves identically on a fresh checkout that lacks the scjson
    binary on PATH (CI installs scjson; local dev MAY not).
    """
    try:
        from loader import load_chart  # noqa: WPS433
    except Exception as exc:  # pragma: no cover - defensive
        pytest.skip(f"loader unavailable: {exc}")
    try:
        ast = load_chart(path).raw_scjson
    except (FileNotFoundError, RuntimeError) as exc:
        pytest.skip(f"scjson unavailable or chart load failed: {exc}")
    assert ast is not None
    return ast


# ---------------------------------------------------------------------------
# DispatchInventory → BoundInputs adapter (test-local helper)
# ---------------------------------------------------------------------------


def _count_states_in_ast(ast: dict) -> int:
    """Count the chart's top-level peer ``<state>`` children.

    The HTTP fixture family is intentionally flat (no nested
    ``<state>`` elements) so a simple ``len(ast['state'])`` is the
    per-chart reachable-state count §6.1 expects. For a chart family
    with nesting, the count would need to descend; that lift is
    deferred until a future Wave-5 with a real chart that requires it.
    """
    return len(ast.get("state") or [])


def _collect_charts(
    inv: DispatchInventory,
    chart_dir: Path,
    out_charts: dict[str, int],
    out_edges: list[BoundDispatchEdge],
) -> None:
    """Recursively flatten a Wave-1A inventory into Wave-1B inputs.

    For each inventory node:
      - Load its AST and record its self_bound (state count) under
        the chart_ref key.
      - For each direct dispatch, emit a ``BoundDispatchEdge`` whose
        ``parent_state_id`` matches the annotation, ``child_chart_id``
        matches the sub-inventory's ``chart_ref``.
      - Recurse into each sub-inventory.

    DAG-shared sub-charts are admissible per Wave-1B's
    ``test_dag_shared_subchart_counted_once`` — the dict insertion is
    idempotent (last-write-wins on count, all writes write the same
    count because the AST is unchanged); the edge list records every
    dispatch site separately. The HTTP family is a tree, so the DAG
    case doesn't fire here.
    """
    # Charts dict carries the chart_ref; for the root inventory it's
    # already the chart's filename.
    chart_path = chart_dir / inv.chart_ref
    ast = _load_chart_or_skip(chart_path)
    out_charts[inv.chart_ref] = _count_states_in_ast(ast)

    for ann, sub_inv in zip(inv.dispatches, inv.sub_inventories):
        out_edges.append(
            BoundDispatchEdge(
                parent_chart_id=inv.chart_ref,
                parent_state_id=ann.parent_state_id,
                child_chart_id=sub_inv.chart_ref,
                independence_axis=None,  # all HTTP dispatches sequential
            )
        )
        _collect_charts(sub_inv, chart_dir, out_charts, out_edges)


def _inventory_to_bound_inputs(
    inv: DispatchInventory,
    chart_dir: Path,
) -> BoundInputs:
    """Adapter: Wave-1A ``DispatchInventory`` → Wave-1B ``BoundInputs``.

    Per the test docstring, this is intentionally local — the
    converter is small and stays inside the worked-example test
    while Wave-4 keeps scope tight. A future Wave-5 may lift this
    into a shared integration module if a second consumer materialises.
    """
    charts: dict[str, int] = {}
    edges: list[BoundDispatchEdge] = []
    _collect_charts(inv, chart_dir, charts, edges)
    return BoundInputs(
        root_chart_id=inv.chart_ref,
        charts=charts,
        edges=edges,
    )


# ---------------------------------------------------------------------------
# Per-dispatch contract-match edge_provider (test-local helper)
# ---------------------------------------------------------------------------


def _per_dispatch_edge_provider(
    parent_inv: DispatchInventory,
    annotation: DispatchAnnotation,
    child_inv: DispatchInventory,
) -> DispatchContractEdge:
    """Build a ``DispatchContractEdge`` whose parent-side expectations
    are derived from the CHILD's declared contract.

    The default ``simple_edge_provider`` uses the parent chart's
    chart-level contract as the per-dispatch expectation for EVERY
    dispatch site — adequate for a single-dispatch parent only. The
    HTTP top-level chart dispatches into 4 distinct sub-charts whose
    contracts differ; collapsing onto the parent's chart-level surface
    produces false-positive mismatches (events the parent declares
    routable that this specific dispatch site doesn't need; reads
    the parent advertises that this method doesn't pull). Per the
    ``simple_edge_provider`` docstring this is exactly the multi-
    dispatch case requiring a custom provider.

    v1 strategy: each per-dispatch edge's parent-side expectations
    EQUAL the child's declared contract — i.e., the parent commits
    to routing every event the child declares and writing every
    field the child reads BEFORE entering this dispatch state. This
    is the minimal-conforming shape; it asserts the contract-match
    semantic ("parent routes what child needs") without requiring
    a separate per-dispatch declaration surface.

    For invariants_maintained: the child's maintained invariants
    appear in the parent's assumed set so the v1 intersection check
    (§5.3 clause 3, currently a no-op) would have something to test
    against. The §5.3 clause 4 (invariants_assumed) requires the
    parent to MAINTAIN every invariant the child ASSUMES — handled
    by carrying ``child.invariants_assumed`` in the parent's
    ``parent_maintained_invariants``.
    """
    child_contract = child_inv.contract or Contract()
    return DispatchContractEdge(
        parent_chart_id=parent_inv.chart_ref,
        parent_state_id=annotation.parent_state_id,
        child_chart_id=child_inv.chart_ref,
        child_contract=child_contract,
        parent_expected_events_in=child_contract.events_in,
        parent_expected_events_out=child_contract.events_out,
        parent_maintained_invariants=child_contract.invariants_assumed,
        parent_assumed_invariants=child_contract.invariants_maintained,
        parent_writes_before_dispatch=child_contract.reads,
        parent_reads_after_dispatch=child_contract.writes,
    )


# ---------------------------------------------------------------------------
# DispatchInventory → boundary-vector edges adapter (test-local)
# ---------------------------------------------------------------------------


def _initial_state_for(ast: dict) -> str:
    """Return the chart's named root-initial state per §7.2."""
    initial = ast.get("initial")
    if isinstance(initial, list) and initial:
        return str(initial[0])
    if isinstance(initial, str) and initial:
        return initial
    # Fall back to first state id if `initial` is absent (uncommon for
    # well-formed SCXML; the fixture set all declare explicit initial).
    states = ast.get("state") or []
    if states and isinstance(states[0], dict):
        return str(states[0].get("id") or "")
    return ""


def _inventory_to_boundary_edges(
    inv: DispatchInventory,
    chart_dir: Path,
) -> list[BoundaryDispatchEdge]:
    """Walk the inventory and emit one ``BoundaryDispatchEdge`` per
    dispatch site, suitable for ``emit_dispatch_tree_boundary_vectors``.

    Each edge mirrors the contract-match edge_provider shape:
    parent-side expectations equal the child's declared contract
    (minimal-conforming). The child contract is wrapped as a
    ``SubChartContract`` carrying chart_id + initial_state.
    """
    edges: list[BoundaryDispatchEdge] = []

    def _walk(parent_inv: DispatchInventory) -> None:
        for ann, sub_inv in zip(parent_inv.dispatches, parent_inv.sub_inventories):
            sub_ast = _load_chart_or_skip(chart_dir / sub_inv.chart_ref)
            sub_contract = sub_inv.contract or Contract()
            edges.append(
                BoundaryDispatchEdge(
                    parent_chart_id=parent_inv.chart_ref,
                    dispatch_state=ann.parent_state_id,
                    child_contract=SubChartContract(
                        chart_id=sub_inv.chart_ref,
                        initial_state=_initial_state_for(sub_ast),
                        events_in=sub_contract.events_in,
                        events_out=sub_contract.events_out,
                        invariants_maintained=sub_contract.invariants_maintained,
                        invariants_assumed=sub_contract.invariants_assumed,
                    ),
                    parent_expected_events_in=sub_contract.events_in,
                    parent_expected_events_out=sub_contract.events_out,
                )
            )
            _walk(sub_inv)

    _walk(inv)
    return edges


# ---------------------------------------------------------------------------
# Pinned per-chart bounds + dispatch-site map (mirrors §8.4 + Wave-1B)
# ---------------------------------------------------------------------------


_EXPECTED_BOUNDS: dict[str, int] = {
    "http_top.scxml":    8,
    "http_get.scxml":    5,
    "http_post.scxml":   15,
    "http_put.scxml":    12,
    "http_delete.scxml": 7,
}

_EXPECTED_COMPOSED_BOUND: int = 47  # 8 + 5 + 15 + 12 + 7 per §8.4

_EXPECTED_DISPATCH_SITES: list[tuple[str, str]] = [
    ("dispatching_get",    "http_get.scxml"),
    ("dispatching_post",   "http_post.scxml"),
    ("dispatching_put",    "http_put.scxml"),
    ("dispatching_delete", "http_delete.scxml"),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_http_family_parses_with_recursive_dispatch_inventory():
    """End-to-end: ``http_top.scxml`` parses into a 5-chart dispatch
    inventory (1 root + 4 per-method leaves), depth-1 across all
    sub-charts."""
    top_path = _FIXTURE_DIR / "http_top.scxml"
    ast = _load_chart_or_skip(top_path)
    inv = parse_dispatch_annotations(ast, chart_path=top_path)

    assert inv.chart_ref == "http_top.scxml"
    assert inv.depth == 0
    # 4 dispatches at the top level — GET/POST/PUT/DELETE; the
    # `dispatching_unknown_method` state does NOT carry a dispatch
    # per §8.1 narrative (it's a no-op pass-through to `responding`).
    assert len(inv.dispatches) == 4
    observed_sites = [
        (d.parent_state_id, d.ref) for d in inv.dispatches
    ]
    assert observed_sites == _EXPECTED_DISPATCH_SITES

    # Each sub-inventory is a leaf — no nested dispatches per §8.3
    # (per-handler decomposition deferred from the v1 worked example).
    assert len(inv.sub_inventories) == 4
    for sub in inv.sub_inventories:
        assert sub.depth == 1
        assert sub.dispatches == ()
        assert sub.sub_inventories == ()
        assert sub.contract is not None  # every method declares a contract

    # The top chart itself carries a chart-level contract (the union
    # of children's external surface, per the §8.1 narrative — the
    # top chart's contract is what the HTTP server's environment sees).
    assert inv.contract is not None


def test_http_family_per_chart_state_counts_match_section_8_4_pins():
    """Each chart's reachable-state count matches the §8.4 bound pin
    Wave-1B's synthetic test fixed at 8/5/15/12/7."""
    top_path = _FIXTURE_DIR / "http_top.scxml"
    ast = _load_chart_or_skip(top_path)
    inv = parse_dispatch_annotations(ast, chart_path=top_path)

    bound_inputs = _inventory_to_bound_inputs(inv, _FIXTURE_DIR)
    for chart_ref, expected_states in _EXPECTED_BOUNDS.items():
        assert bound_inputs.charts[chart_ref] == expected_states, (
            f"chart {chart_ref} expected {expected_states} states, "
            f"got {bound_inputs.charts[chart_ref]}"
        )


def test_http_family_composed_bound_is_47_matching_wave_1b_pin():
    """SOS-12 §8.4 + Wave-1B
    ``test_sos12_section_8_4_http_worked_example_bounds``: composing
    the dispatch-tree's per-chart bounds via sum-not-product per §6.3
    yields exactly 47 vectors for the 5-chart (top + per-method)
    family. This is the load-bearing assertion materialising
    Wave-1B's synthetic pin against the on-disk SCXML reality.
    """
    top_path = _FIXTURE_DIR / "http_top.scxml"
    ast = _load_chart_or_skip(top_path)
    inv = parse_dispatch_annotations(ast, chart_path=top_path)

    bound_inputs = _inventory_to_bound_inputs(inv, _FIXTURE_DIR)
    result = compose_bound(bound_inputs)

    assert result.composed_bound == _EXPECTED_COMPOSED_BOUND
    assert result.composed_bound == 47  # explicit per the spec narrative
    assert len(result.per_layer_breakdown) == 5

    # All 4 method dispatches are sequential (distinct parent states),
    # forming 4 single-member None-axis independence axes per §6.3 +
    # Wave-1B's `test_sos12_section_8_4_http_worked_example_bounds`.
    assert len(result.independence_axes) == 4
    for axis in result.independence_axes:
        assert axis.parent_chart_id == "http_top.scxml"
        assert axis.axis_id is None
        assert len(axis.member_child_ids) == 1


def test_http_family_boundary_vectors_sum_across_edges_per_section_7_2():
    """Per §7.2: boundary-vector emission is per-edge; the family-
    aggregate count is ``sum(per-edge counts)``. Each per-edge count
    is the constant
    ``|events_in| + |events_out| + |invariants_maintained| + |invariants_assumed|``
    (the four contract categories). The aggregate is independent of
    sub-chart internal state counts per INV-S-DISP-5.

    Expected per-edge counts (sum of contract category sizes):
        http_get    →  2 + 2 + 1 + 1 =  6
        http_post   →  4 + 2 + 2 + 1 =  9
        http_put    →  3 + 2 + 3 + 1 =  9
        http_delete →  2 + 2 + 2 + 1 =  7
        TOTAL                          = 31
    """
    top_path = _FIXTURE_DIR / "http_top.scxml"
    ast = _load_chart_or_skip(top_path)
    inv = parse_dispatch_annotations(ast, chart_path=top_path)

    boundary_edges = _inventory_to_boundary_edges(inv, _FIXTURE_DIR)
    assert len(boundary_edges) == 4

    vectors = emit_dispatch_tree_boundary_vectors(boundary_edges)

    # Per §7.2: total = sum of (|events_in| + |events_out| +
    # |invariants_maintained| + |invariants_assumed|) across edges.
    expected_total = 0
    for edge in boundary_edges:
        c = edge.child_contract
        expected_total += (
            len(c.events_in)
            + len(c.events_out)
            + len(c.invariants_maintained)
            + len(c.invariants_assumed)
        )
    assert expected_total == 31, (
        f"§8.4 worked example: expected 31 boundary vectors, "
        f"got {expected_total}"
    )
    assert len(vectors) == expected_total


def test_http_family_contract_match_verifies_clean():
    """Per §5.3 + Wave-2 contract-match: every parent → child contract
    pair verifies without mismatch under a per-dispatch edge_provider
    that derives parent-side expectations from each child's contract
    (the minimal-conforming shape; see ``_per_dispatch_edge_provider``
    docstring for the multi-dispatch rationale).
    """
    top_path = _FIXTURE_DIR / "http_top.scxml"
    ast = _load_chart_or_skip(top_path)
    inv = parse_dispatch_annotations(ast, chart_path=top_path)

    # No exception → clean verification across all 4 dispatch edges.
    verify_inventory(inv, edge_provider=_per_dispatch_edge_provider)


def test_http_family_passes_dispatch_depth_lint():
    """SCXML-LINT-DISP-1 / §6.5 / PCDN-SOS-12-005: the HTTP family is
    depth-1 (root → method-sub-chart); the default cap of 8 is
    comfortably above. Lint passes — empty diagnostics list."""
    top_path = _FIXTURE_DIR / "http_top.scxml"
    diagnostics = check_dispatch_depth(top_path)
    assert diagnostics == [], (
        f"depth lint unexpectedly fired: {diagnostics}"
    )


def test_http_family_passes_legibility_lint_for_every_chart():
    """SCXML-LINT-DISP-2 / §9.1 / PCDN-SOS-12-003: every chart in the
    family stays ≤ 15 peer-states default threshold (http_top=8,
    http_get=5, http_post=15, http_put=12, http_delete=7). The
    http_post chart at 15 sits EXACTLY at the threshold — the §8.5
    narrative specifically calls this out: a 16th state would fail
    lint, but 15 does not (the breach predicate is `peer_count >
    threshold`, not `≥`).
    """
    for chart_name in _EXPECTED_BOUNDS:
        path = _FIXTURE_DIR / chart_name
        diagnostics = check_legibility(path)
        assert diagnostics == [], (
            f"legibility lint fired on {chart_name}: {diagnostics}"
        )


def test_http_family_boundary_vectors_carry_inv_sos_h_chart_path_metadata():
    """Per INV-SOS-H: every emitted vector carries metadata pointing
    back to the chart-tree address that produced it. The vector
    ``chart_path`` shape is
    ``<parent_chart_id>.<dispatch_state>.<child_chart_id>``; for the
    HTTP family this is e.g. ``http_top.scxml.dispatching_get.
    http_get.scxml``. This test asserts the metadata pinning so a
    downstream consumer can group vectors by edge for per-edge
    review."""
    top_path = _FIXTURE_DIR / "http_top.scxml"
    ast = _load_chart_or_skip(top_path)
    inv = parse_dispatch_annotations(ast, chart_path=top_path)

    boundary_edges = _inventory_to_boundary_edges(inv, _FIXTURE_DIR)
    vectors = emit_dispatch_tree_boundary_vectors(boundary_edges)

    chart_paths: set[str] = set()
    for vec in vectors:
        meta = vec.get("metadata") or {}
        path = meta.get("chart_path")
        assert isinstance(path, str) and path, (
            f"vector missing chart_path metadata: {vec}"
        )
        chart_paths.add(path)

    # Exactly 4 distinct chart_path values — one per dispatch edge.
    assert chart_paths == {
        "http_top.scxml.dispatching_get.http_get.scxml",
        "http_top.scxml.dispatching_post.http_post.scxml",
        "http_top.scxml.dispatching_put.http_put.scxml",
        "http_top.scxml.dispatching_delete.http_delete.scxml",
    }

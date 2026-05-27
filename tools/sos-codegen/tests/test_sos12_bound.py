"""Tests for ``sos12_bound.py`` — SOS-12 bound-composition algebra.

Authority: ``docs/concepts/SOS-12-CONCEPTS.md`` (🟢 ratified 2026-05-23,
all 6 PCDNs resolved) §6.1-§6.4, §6.5, §10.1 (INV-S-DISP-1 through
INV-S-DISP-5). Cross-phase: INV-SOS-F from
``docs/concepts/SOS-07-CONCEPTS.md`` §6.

Covers:

- §6.1 — single-chart self_bound case (no dispatches).
- §6.3 — sequential composition: parent + sum of sub-chart bounds.
- §6.2 / §6.4 — independence axes: orthogonal dispatches share an axis,
  sequential dispatches occupy distinct axes; both arithmetic SUM but
  surfaced separately in the breakdown.
- §6.5 — recursion depth cap (default 8 per PCDN-SOS-12-005).
- INV-S-DISP-2 — dangling/unknown child reference rejected.
- INV-S-DISP-3 — cyclic dispatch graphs rejected (self + mutual).
- Worked example from SOS-12 §8.4 (HTTP family).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `sos-codegen` modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos12_bound import (  # noqa: E402
    DEFAULT_MAX_RECURSION_DEPTH,
    BoundInputs,
    CompositionResult,
    DispatchEdge,
    IndependenceAxis,
    LayerBound,
    Sos12BoundError,
    compose_bound,
)


# ---------------------------------------------------------------------------
# §6.1 — single chart, no dispatches
# ---------------------------------------------------------------------------


def test_single_chart_self_bound_no_dispatch() -> None:
    """A leaf chart's composed bound equals its own per-layer bound (§6.1)."""
    result = compose_bound(
        BoundInputs(root_chart_id="solo", charts={"solo": 7})
    )
    assert result.composed_bound == 7
    assert len(result.per_layer_breakdown) == 1
    layer = result.per_layer_breakdown[0]
    assert layer.chart_id == "solo"
    assert layer.depth == 0
    assert layer.self_bound == 7
    assert layer.dispatch_edge_count == 0
    assert layer.children_sum_bound == 0
    assert result.independence_axes == []
    assert result.joint_cartesian_upper_bound == 7


def test_single_chart_zero_states_admissible() -> None:
    """A zero-state stub chart is admissible (degenerate but valid §6.1)."""
    result = compose_bound(
        BoundInputs(root_chart_id="stub", charts={"stub": 0})
    )
    assert result.composed_bound == 0
    assert result.per_layer_breakdown[0].self_bound == 0


# ---------------------------------------------------------------------------
# §6.3 — sequential composition
# ---------------------------------------------------------------------------


def test_simple_sequential_composition_one_dispatch() -> None:
    """Parent + one child sub-chart: composed = parent + child (§6.3 SUM)."""
    result = compose_bound(
        BoundInputs(
            root_chart_id="parent",
            charts={"parent": 8, "child": 5},
            edges=[
                DispatchEdge(
                    parent_chart_id="parent",
                    parent_state_id="dispatching_child",
                    child_chart_id="child",
                )
            ],
        )
    )
    # Sum-not-product per §6.3.
    assert result.composed_bound == 8 + 5
    assert len(result.per_layer_breakdown) == 2
    root_layer = result.per_layer_breakdown[0]
    assert root_layer.chart_id == "parent"
    assert root_layer.depth == 0
    assert root_layer.self_bound == 8
    assert root_layer.dispatch_edge_count == 1
    assert root_layer.children_sum_bound == 5
    child_layer = result.per_layer_breakdown[1]
    assert child_layer.chart_id == "child"
    assert child_layer.depth == 1
    assert child_layer.self_bound == 5
    assert child_layer.children_sum_bound == 0


def test_multiple_sequential_children_distinct_states_sum() -> None:
    """Multiple sequentially-dispatched children all SUM into the family bound.

    Each dispatch from a DIFFERENT parent state is sequential per §6.3 —
    the parent transits through one dispatched state at a time. The sum
    is parent + sum(children), and each (parent_state, dispatch) forms
    its own single-member independence axis.
    """
    result = compose_bound(
        BoundInputs(
            root_chart_id="p",
            charts={"p": 4, "a": 3, "b": 6, "c": 2},
            edges=[
                DispatchEdge("p", "s1", "a"),
                DispatchEdge("p", "s2", "b"),
                DispatchEdge("p", "s3", "c"),
            ],
        )
    )
    assert result.composed_bound == 4 + 3 + 6 + 2
    # Three single-member axes (each from a different parent state).
    assert len(result.independence_axes) == 3
    for axis in result.independence_axes:
        assert len(axis.member_child_ids) == 1
        assert axis.axis_id is None


# ---------------------------------------------------------------------------
# §6.2 / §6.4 — independence axes (orthogonal regions)
# ---------------------------------------------------------------------------


def test_two_orthogonal_children_share_axis() -> None:
    """Two dispatches from the same parent state on the same independence
    axis collapse into a single axis with two members (§6.2 / §6.4).

    The composed_bound is parent + sum(children) — same arithmetic as
    sequential composition, but the axis breakdown distinguishes:
    one axis with two members (orthogonal-region semantics) vs. two
    single-member axes (sequential-composition semantics).
    """
    result = compose_bound(
        BoundInputs(
            root_chart_id="p",
            charts={"p": 3, "a": 4, "b": 5},
            edges=[
                DispatchEdge("p", "dispatching_orthogonal", "a", "axis-1"),
                DispatchEdge("p", "dispatching_orthogonal", "b", "axis-1"),
            ],
        )
    )
    # Per-layer SUM per §6.3; per-region SUM per §6.2 — same number.
    assert result.composed_bound == 3 + 4 + 5
    assert len(result.independence_axes) == 1
    axis = result.independence_axes[0]
    assert axis.axis_id == "axis-1"
    assert axis.parent_chart_id == "p"
    assert axis.parent_state_id == "dispatching_orthogonal"
    assert axis.member_child_ids == ("a", "b")
    assert axis.sum_bound == 4 + 5
    # Joint Cartesian DECLARED but not enumerated per §6.2; this is the
    # product, surfacing the cost an invariant-spanning-axis would pay.
    assert axis.joint_cartesian_upper_bound == 4 * 5
    # Family-wide joint upper bound at least the composed bound; here
    # the only axis carries a 20-state Cartesian product.
    assert result.joint_cartesian_upper_bound >= result.composed_bound
    assert result.joint_cartesian_upper_bound == 4 * 5  # max axis joint


def test_three_orthogonal_children_share_axis() -> None:
    """Three children on one axis: SUM for vectors, product as upper bound."""
    result = compose_bound(
        BoundInputs(
            root_chart_id="p",
            charts={"p": 2, "x": 3, "y": 4, "z": 5},
            edges=[
                DispatchEdge("p", "fork", "x", "main"),
                DispatchEdge("p", "fork", "y", "main"),
                DispatchEdge("p", "fork", "z", "main"),
            ],
        )
    )
    assert result.composed_bound == 2 + 3 + 4 + 5
    assert len(result.independence_axes) == 1
    axis = result.independence_axes[0]
    assert axis.sum_bound == 3 + 4 + 5
    assert axis.joint_cartesian_upper_bound == 3 * 4 * 5


def test_mixed_orthogonal_and_sequential_children() -> None:
    """Mix: two children on one axis (orthogonal) plus a third sequential."""
    result = compose_bound(
        BoundInputs(
            root_chart_id="p",
            charts={"p": 5, "a": 3, "b": 4, "c": 2},
            edges=[
                DispatchEdge("p", "fork", "a", "axis-1"),
                DispatchEdge("p", "fork", "b", "axis-1"),
                DispatchEdge("p", "next", "c"),  # sequential (no axis)
            ],
        )
    )
    assert result.composed_bound == 5 + 3 + 4 + 2
    # One 2-member axis ("axis-1" at "fork") + one 1-member None-axis at "next".
    assert len(result.independence_axes) == 2
    fork_axis = next(a for a in result.independence_axes if a.parent_state_id == "fork")
    assert fork_axis.member_child_ids == ("a", "b")
    assert fork_axis.axis_id == "axis-1"
    next_axis = next(a for a in result.independence_axes if a.parent_state_id == "next")
    assert next_axis.member_child_ids == ("c",)
    assert next_axis.axis_id is None


# ---------------------------------------------------------------------------
# Depth-3 chain
# ---------------------------------------------------------------------------


def test_depth_three_chain_sums_across_layers() -> None:
    """A → B → C chain: composed = A + B + C (§6.3 recursive SUM)."""
    result = compose_bound(
        BoundInputs(
            root_chart_id="A",
            charts={"A": 6, "B": 4, "C": 9},
            edges=[
                DispatchEdge("A", "to_B", "B"),
                DispatchEdge("B", "to_C", "C"),
            ],
        )
    )
    assert result.composed_bound == 6 + 4 + 9
    assert [layer.chart_id for layer in result.per_layer_breakdown] == ["A", "B", "C"]
    assert [layer.depth for layer in result.per_layer_breakdown] == [0, 1, 2]
    # A sees one outgoing edge; B sees one outgoing edge; C is a leaf.
    assert result.per_layer_breakdown[0].dispatch_edge_count == 1
    assert result.per_layer_breakdown[1].dispatch_edge_count == 1
    assert result.per_layer_breakdown[2].dispatch_edge_count == 0


# ---------------------------------------------------------------------------
# §6.5 — recursion depth cap
# ---------------------------------------------------------------------------


def test_default_max_recursion_depth_is_eight() -> None:
    """PCDN-SOS-12-005: default cap is 8 levels (§6.5 + §10.3)."""
    assert DEFAULT_MAX_RECURSION_DEPTH == 8


def test_recursion_depth_within_cap_succeeds() -> None:
    """A chain right at the depth cap passes (default 8 levels => depths 0..8)."""
    # Build a 9-chart chain (depths 0 through 8 inclusive).
    charts = {f"c{i}": 1 for i in range(9)}
    edges = [DispatchEdge(f"c{i}", f"s{i}", f"c{i + 1}") for i in range(8)]
    result = compose_bound(
        BoundInputs(root_chart_id="c0", charts=charts, edges=edges)
    )
    assert result.composed_bound == 9  # each chart contributes 1


def test_recursion_depth_exceeds_cap_rejected() -> None:
    """A chain exceeding the depth cap raises Sos12BoundError citing §6.5."""
    # 10 charts; depths 0..9; with max_depth=8, depth 9 triggers.
    charts = {f"c{i}": 1 for i in range(10)}
    edges = [DispatchEdge(f"c{i}", f"s{i}", f"c{i + 1}") for i in range(9)]
    with pytest.raises(Sos12BoundError) as excinfo:
        compose_bound(
            BoundInputs(root_chart_id="c0", charts=charts, edges=edges)
        )
    assert excinfo.value.rule == "SOS-12 §6.5"
    assert "exceeds max_depth" in str(excinfo.value)


def test_recursion_depth_override_via_max_depth() -> None:
    """Projects MAY override the depth cap per §10.3 (Specification Required)."""
    charts = {f"c{i}": 1 for i in range(5)}
    edges = [DispatchEdge(f"c{i}", f"s{i}", f"c{i + 1}") for i in range(4)]
    # With max_depth=2, the depth-3 chain should fail; with =4, pass.
    with pytest.raises(Sos12BoundError):
        compose_bound(
            BoundInputs(
                root_chart_id="c0", charts=charts, edges=edges, max_depth=2
            )
        )
    result = compose_bound(
        BoundInputs(
            root_chart_id="c0", charts=charts, edges=edges, max_depth=4
        )
    )
    assert result.composed_bound == 5


# ---------------------------------------------------------------------------
# INV-S-DISP-3 — DAG enforcement (cycle rejection)
# ---------------------------------------------------------------------------


def test_self_dispatch_rejected_inv_s_disp_3() -> None:
    """A chart cannot dispatch into itself (INV-S-DISP-3)."""
    with pytest.raises(Sos12BoundError) as excinfo:
        compose_bound(
            BoundInputs(
                root_chart_id="a",
                charts={"a": 3},
                edges=[DispatchEdge("a", "self", "a")],
            )
        )
    assert excinfo.value.rule == "INV-S-DISP-3"
    assert "self-dispatches" in str(excinfo.value)


def test_mutual_recursion_rejected_inv_s_disp_3() -> None:
    """Mutual recursion (A → B → A) is rejected (INV-S-DISP-3)."""
    with pytest.raises(Sos12BoundError) as excinfo:
        compose_bound(
            BoundInputs(
                root_chart_id="A",
                charts={"A": 2, "B": 2},
                edges=[
                    DispatchEdge("A", "to_B", "B"),
                    DispatchEdge("B", "to_A", "A"),
                ],
            )
        )
    assert excinfo.value.rule == "INV-S-DISP-3"
    assert "cycle" in str(excinfo.value).lower()


def test_three_chart_cycle_rejected_inv_s_disp_3() -> None:
    """A 3-chart cycle (A → B → C → A) is rejected (INV-S-DISP-3)."""
    with pytest.raises(Sos12BoundError) as excinfo:
        compose_bound(
            BoundInputs(
                root_chart_id="A",
                charts={"A": 1, "B": 1, "C": 1},
                edges=[
                    DispatchEdge("A", "s1", "B"),
                    DispatchEdge("B", "s2", "C"),
                    DispatchEdge("C", "s3", "A"),
                ],
            )
        )
    assert excinfo.value.rule == "INV-S-DISP-3"


# ---------------------------------------------------------------------------
# INV-S-DISP-2 — contract-matching mandatory (dangling reference rejection)
# ---------------------------------------------------------------------------


def test_dangling_child_reference_rejected_inv_s_disp_2() -> None:
    """Dispatch edge to an unknown child chart raises (INV-S-DISP-2)."""
    with pytest.raises(Sos12BoundError) as excinfo:
        compose_bound(
            BoundInputs(
                root_chart_id="A",
                charts={"A": 3},
                edges=[DispatchEdge("A", "to_ghost", "nonexistent")],
            )
        )
    assert excinfo.value.rule == "INV-S-DISP-2"


def test_dangling_parent_reference_rejected_inv_s_disp_2() -> None:
    """Dispatch edge from an unknown parent chart raises (INV-S-DISP-2)."""
    with pytest.raises(Sos12BoundError) as excinfo:
        compose_bound(
            BoundInputs(
                root_chart_id="A",
                charts={"A": 3, "B": 2},
                edges=[DispatchEdge("ghost", "s1", "B")],
            )
        )
    assert excinfo.value.rule == "INV-S-DISP-2"


# ---------------------------------------------------------------------------
# Misc input-validation surface
# ---------------------------------------------------------------------------


def test_empty_charts_mapping_rejected() -> None:
    """An empty charts mapping is rejected at validation."""
    with pytest.raises(Sos12BoundError):
        compose_bound(BoundInputs(root_chart_id="x", charts={}))


def test_missing_root_chart_rejected() -> None:
    """A root_chart_id absent from `charts` is rejected."""
    with pytest.raises(Sos12BoundError) as excinfo:
        compose_bound(BoundInputs(root_chart_id="ghost", charts={"a": 1}))
    assert "root_chart_id" in str(excinfo.value)


def test_negative_chart_bound_rejected() -> None:
    """A chart bound < 0 is rejected (§6.1)."""
    with pytest.raises(Sos12BoundError):
        compose_bound(BoundInputs(root_chart_id="a", charts={"a": -1}))


def test_zero_max_depth_rejected() -> None:
    """max_depth < 1 makes no sense (the root is at depth 0)."""
    with pytest.raises(Sos12BoundError):
        compose_bound(
            BoundInputs(root_chart_id="a", charts={"a": 1}, max_depth=0)
        )


# ---------------------------------------------------------------------------
# Pre-order traversal property — breakdown order matches dispatch declaration
# ---------------------------------------------------------------------------


def test_per_layer_breakdown_is_preorder_dispatch_declaration_order() -> None:
    """Pre-order traversal: root, then each sub-tree in edge declaration order."""
    result = compose_bound(
        BoundInputs(
            root_chart_id="root",
            charts={
                "root": 1,
                "child_a": 1,
                "child_b": 1,
                "grand_a1": 1,
                "grand_a2": 1,
                "grand_b1": 1,
            },
            edges=[
                DispatchEdge("root", "s_a", "child_a"),
                DispatchEdge("root", "s_b", "child_b"),
                DispatchEdge("child_a", "ga1_s", "grand_a1"),
                DispatchEdge("child_a", "ga2_s", "grand_a2"),
                DispatchEdge("child_b", "gb1_s", "grand_b1"),
            ],
        )
    )
    assert [layer.chart_id for layer in result.per_layer_breakdown] == [
        "root",
        "child_a",
        "grand_a1",
        "grand_a2",
        "child_b",
        "grand_b1",
    ]
    assert result.composed_bound == 6  # six charts, each contributing 1


# ---------------------------------------------------------------------------
# §8.4 HTTP worked example
# ---------------------------------------------------------------------------


def test_sos12_section_8_4_http_worked_example_bounds() -> None:
    """SOS-12 §8.4: HTTP family bound composition.

    Per §8.4:
        bound(http_top)    = 8
        bound(http_get)    = 5
        bound(http_post)   = 15
        bound(http_put)    = 12
        bound(http_delete) = 7
        bound(family) ≈ sum-across-the-tree of every chart's per-layer bound.

    Per-handler sub-charts are deferred (the §8.3 informative example
    doesn't pin specific bounds). Without them, bound(family) = 8 + 5 +
    15 + 12 + 7 = 47, which sits in the 2-3-orders-of-magnitude-below
    Cartesian regime §8.4 narratively highlights.
    """
    result = compose_bound(
        BoundInputs(
            root_chart_id="http_top",
            charts={
                "http_top": 8,
                "http_get": 5,
                "http_post": 15,
                "http_put": 12,
                "http_delete": 7,
            },
            edges=[
                DispatchEdge("http_top", "dispatching_get", "http_get"),
                DispatchEdge("http_top", "dispatching_post", "http_post"),
                DispatchEdge("http_top", "dispatching_put", "http_put"),
                DispatchEdge("http_top", "dispatching_delete", "http_delete"),
            ],
        )
    )
    assert result.composed_bound == 8 + 5 + 15 + 12 + 7
    assert result.composed_bound == 47
    # 5 charts in the family.
    assert len(result.per_layer_breakdown) == 5
    # Per-layer SUM is ~2 orders of magnitude smaller than Cartesian:
    # naive flat HTTP exceeds 200 states; full Cartesian per §8.4 is ~10^6.
    # Each per-method dispatch is sequential (distinct parent_state_id),
    # so each forms its own single-member axis.
    assert len(result.independence_axes) == 4
    for axis in result.independence_axes:
        assert axis.parent_chart_id == "http_top"
        assert axis.axis_id is None  # sequential, not orthogonal
        assert len(axis.member_child_ids) == 1


# ---------------------------------------------------------------------------
# INV-S-DISP-5 — per-layer vector count is local
# ---------------------------------------------------------------------------


def test_per_layer_bound_is_local_inv_s_disp_5() -> None:
    """INV-S-DISP-5: a chart's per-layer bound depends only on its own
    reachable-state count and outgoing-dispatch-edge count — not on the
    sub-chart's internal state count.

    Property: doubling a sub-chart's internal state count changes the
    family composed_bound by exactly the sub-chart's delta, AND leaves
    every other chart's `LayerBound.self_bound` and `dispatch_edge_count`
    unchanged.
    """
    base = compose_bound(
        BoundInputs(
            root_chart_id="parent",
            charts={"parent": 10, "child": 5},
            edges=[DispatchEdge("parent", "to_child", "child")],
        )
    )
    doubled = compose_bound(
        BoundInputs(
            root_chart_id="parent",
            charts={"parent": 10, "child": 10},  # child doubled
            edges=[DispatchEdge("parent", "to_child", "child")],
        )
    )
    # Family bound changes by exactly the child delta.
    assert doubled.composed_bound - base.composed_bound == 5
    # Parent layer is unaffected by child's internal-state growth.
    base_parent = next(l for l in base.per_layer_breakdown if l.chart_id == "parent")
    doubled_parent = next(l for l in doubled.per_layer_breakdown if l.chart_id == "parent")
    assert base_parent.self_bound == doubled_parent.self_bound
    assert base_parent.dispatch_edge_count == doubled_parent.dispatch_edge_count


# ---------------------------------------------------------------------------
# DAG (non-tree) reuse — shared sub-chart contributes its self_bound once
# ---------------------------------------------------------------------------


def test_dag_shared_subchart_counted_once() -> None:
    """A sub-chart dispatched from two parents (DAG) counts its self_bound
    exactly once in the family composed_bound — per INV-S-DISP-5 the
    per-layer count is local, and per §6.3 the SUM is per-chart not
    per-edge. Each dispatch site still contributes a boundary-vector
    surface at the parent layer (per §7.2), which surfaces as the parent
    chart's `dispatch_edge_count` field.

    Family: root → A, root → B, A → shared, B → shared
    Bounds: root=2, A=3, B=4, shared=10
    composed_bound = 2 + 3 + 4 + 10 (shared counted once) = 19
    """
    result = compose_bound(
        BoundInputs(
            root_chart_id="root",
            charts={"root": 2, "A": 3, "B": 4, "shared": 10},
            edges=[
                DispatchEdge("root", "to_A", "A"),
                DispatchEdge("root", "to_B", "B"),
                DispatchEdge("A", "to_shared_via_A", "shared"),
                DispatchEdge("B", "to_shared_via_B", "shared"),
            ],
        )
    )
    assert result.composed_bound == 2 + 3 + 4 + 10
    # `shared` appears in the breakdown exactly once (per-layer locality).
    shared_layers = [l for l in result.per_layer_breakdown if l.chart_id == "shared"]
    assert len(shared_layers) == 1
    # But A and B each register an outgoing dispatch edge to shared
    # (boundary-vector surface per §7.2 is per-dispatch-site).
    a_layer = next(l for l in result.per_layer_breakdown if l.chart_id == "A")
    b_layer = next(l for l in result.per_layer_breakdown if l.chart_id == "B")
    assert a_layer.dispatch_edge_count == 1
    assert b_layer.dispatch_edge_count == 1

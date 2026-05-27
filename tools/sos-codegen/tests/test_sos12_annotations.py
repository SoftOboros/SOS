"""Tests for `sos12_annotations.py` — SOS-12 dispatch + contract parser.

Authority: `docs/concepts/SOS-12-CONCEPTS.md` (🟢 ratified 2026-05-23; all
6 PCDNs resolved). Covers §5.1 PCDN-001 `<sos:dispatch>` element shape;
§5.1 PCDN-002 datamodel-boundary (per-sub-chart explicit reads/writes);
§5.1 PCDN-004 contract syntax detail (inline `<sos:contract>` at chart
root); §6.5 / PCDN-005 recursion depth cap (default 8); INV-S-DISP-1 /
INV-S-DISP-3 / INV-S-DISP-5 cited where load-bearing.

Tests are deliberately split between two surfaces:

- **Synthetic-AST tests** drive the parser with hand-built scjson-shape
  dicts. These exercise individual validation rules in isolation without
  needing scjson installed.
- **Fixture-driven tests** load real `.scxml` files through `loader.load_chart`
  (which shells out to scjson). These exercise the end-to-end SCXML →
  scjson → parser roundtrip and the dispatch-tree recursion across files.

The two surfaces mirror the precedent of `test_sos10_annotations.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `sos-codegen` modules importable when pytest is invoked from any cwd
# (the module dir uses a dash, so it's not a real Python package).
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos12_annotations import (  # noqa: E402
    DEFAULT_MAX_DEPTH,
    PERMITTED_CONTRACT_ATTRS,
    PERMITTED_DISPATCH_ATTRS,
    SOS_NS,
    Contract,
    DispatchAnnotation,
    DispatchInventory,
    Sos12AnnotationError,
    parse_dispatch_annotations,
)


# ---------------------------------------------------------------------------
# scjson-shape builders for synthetic in-test charts.
# ---------------------------------------------------------------------------

DISPATCH_QN = f"{{{SOS_NS}}}dispatch"
CONTRACT_QN = f"{{{SOS_NS}}}contract"
EVENTS_IN_QN = f"{{{SOS_NS}}}events-in"
EVENTS_OUT_QN = f"{{{SOS_NS}}}events-out"
INVARIANTS_QN = f"{{{SOS_NS}}}invariants"
EVENT_QN = f"{{{SOS_NS}}}event"
MAINTAINED_QN = f"{{{SOS_NS}}}maintained-by-subchart"
ASSUMED_QN = f"{{{SOS_NS}}}assumed-of-environment"


def _dispatch_element(ref: str, *, extra_attrs: dict | None = None) -> dict:
    """Build a `<sos:dispatch ref="…"/>` other_element node."""
    attrs: dict = {"ref": ref}
    if extra_attrs:
        attrs.update(extra_attrs)
    return {"qname": DISPATCH_QN, "text": "", "attributes": attrs}


def _event_node(name: str) -> dict:
    return {"qname": EVENT_QN, "text": name}


def _contract_element(
    *,
    reads: str = "",
    writes: str = "",
    events_in: list[str] | None = None,
    events_out: list[str] | None = None,
    maintained: list[str] | None = None,
    assumed: list[str] | None = None,
    extra_attrs: dict | None = None,
) -> dict:
    """Build a `<sos:contract>` other_element node with the standard sub-elements."""
    attrs: dict = {}
    if reads:
        attrs["reads"] = reads
    if writes:
        attrs["writes"] = writes
    if extra_attrs:
        attrs.update(extra_attrs)
    children: list[dict] = []
    if events_in is not None:
        children.append(
            {
                "qname": EVENTS_IN_QN,
                "text": "",
                "children": [_event_node(n) for n in events_in],
            }
        )
    if events_out is not None:
        children.append(
            {
                "qname": EVENTS_OUT_QN,
                "text": "",
                "children": [_event_node(n) for n in events_out],
            }
        )
    if maintained is not None or assumed is not None:
        inv_children: list[dict] = []
        for n in maintained or []:
            inv_children.append({"qname": MAINTAINED_QN, "text": n})
        for n in assumed or []:
            inv_children.append({"qname": ASSUMED_QN, "text": n})
        children.append(
            {"qname": INVARIANTS_QN, "text": "", "children": inv_children}
        )
    node: dict = {"qname": CONTRACT_QN, "text": "", "attributes": attrs}
    if children:
        node["children"] = children
    return node


def _state(state_id: str, *, dispatches: list[dict] | None = None) -> dict:
    """Build a `<state>` node carrying zero-or-more `<sos:dispatch>` children."""
    node: dict = {"id": state_id}
    if dispatches:
        node["other_element"] = dispatches
    return node


def _chart(
    states: list[dict],
    *,
    contract: dict | None = None,
) -> dict:
    """Build a root-level scjson chart dict."""
    root: dict = {"state": states, "version": 1.0, "datamodel_attribute": "ecmascript"}
    if contract is not None:
        root["other_element"] = [contract]
    return root


# ---------------------------------------------------------------------------
# Frozen-enum exports
# ---------------------------------------------------------------------------


def test_frozen_enum_exports_match_spec():
    """Per §10: DEFAULT_MAX_DEPTH=8 (PCDN-005); PERMITTED_DISPATCH_ATTRS={'ref'}
    (PCDN-001); PERMITTED_CONTRACT_ATTRS={'reads','writes'} (PCDN-002)."""
    assert DEFAULT_MAX_DEPTH == 8
    assert PERMITTED_DISPATCH_ATTRS == frozenset({"ref"})
    assert PERMITTED_CONTRACT_ATTRS == frozenset({"reads", "writes"})


# ---------------------------------------------------------------------------
# Synthetic single-level dispatch
# ---------------------------------------------------------------------------


def test_single_level_dispatch_in_isolated_ast():
    """A chart with one `<sos:dispatch ref="…"/>` produces one
    DispatchAnnotation; without chart_path the ref stays unresolved."""
    chart = _chart(
        [
            _state("s1", dispatches=[_dispatch_element("child.scxml")]),
            _state("s2"),
        ]
    )
    inv = parse_dispatch_annotations(chart)
    assert isinstance(inv, DispatchInventory)
    assert inv.chart_ref == "<root>"
    assert inv.depth == 0
    assert len(inv.dispatches) == 1
    d = inv.dispatches[0]
    assert isinstance(d, DispatchAnnotation)
    assert d.parent_state_id == "s1"
    assert d.ref == "child.scxml"
    assert d.resolved_path is None
    # No chart_path anchor → ref records as unresolved.
    assert inv.unresolved_refs == ("child.scxml",)
    assert inv.sub_inventories == ()
    assert inv.contract is None


def test_no_dispatches_or_contract_yields_empty_inventory():
    """A chart with neither annotation produces an empty inventory cleanly."""
    chart = _chart([_state("alone")])
    inv = parse_dispatch_annotations(chart)
    assert inv.dispatches == ()
    assert inv.contract is None
    assert inv.sub_inventories == ()
    assert inv.unresolved_refs == ()


# ---------------------------------------------------------------------------
# Contract parsing
# ---------------------------------------------------------------------------


def test_contract_with_all_four_fields_populated():
    """`<sos:contract>` with reads/writes attrs + all three sub-elements
    parses into a fully-populated Contract."""
    chart = _chart(
        [_state("s")],
        contract=_contract_element(
            reads="x y",
            writes="z",
            events_in=["e.in1", "e.in2"],
            events_out=["e.out1"],
            maintained=["INV-1"],
            assumed=["INV-ENV-1", "INV-ENV-2"],
        ),
    )
    inv = parse_dispatch_annotations(chart)
    assert isinstance(inv.contract, Contract)
    c = inv.contract
    assert c.reads == ("x", "y")
    assert c.writes == ("z",)
    assert c.events_in == ("e.in1", "e.in2")
    assert c.events_out == ("e.out1",)
    assert c.invariants_maintained == ("INV-1",)
    assert c.invariants_assumed == ("INV-ENV-1", "INV-ENV-2")


def test_contract_unknown_attribute_rejected():
    """Per PCDN-SOS-12-002 / -004 attribute set is frozen; unknown attr → error."""
    chart = _chart(
        [_state("s")],
        contract=_contract_element(reads="x", extra_attrs={"bogus": "1"}),
    )
    with pytest.raises(Sos12AnnotationError) as excinfo:
        parse_dispatch_annotations(chart)
    assert "PCDN-SOS-12-002" in (excinfo.value.rule or "")
    assert "bogus" in str(excinfo.value)


def test_contract_duplicate_field_in_reads_rejected():
    """A duplicated token in `reads` is a chart-author typo → reject."""
    chart = _chart(
        [_state("s")], contract=_contract_element(reads="x y x"),
    )
    with pytest.raises(Sos12AnnotationError) as excinfo:
        parse_dispatch_annotations(chart)
    assert "duplicate" in str(excinfo.value).lower()


def test_contract_empty_attributes_yields_empty_tuples():
    """`<sos:contract/>` with no attrs and no children is admissible (empty
    contract surface)."""
    chart = _chart([_state("s")], contract=_contract_element())
    inv = parse_dispatch_annotations(chart)
    assert inv.contract is not None
    assert inv.contract.reads == ()
    assert inv.contract.writes == ()
    assert inv.contract.events_in == ()
    assert inv.contract.events_out == ()


def test_multiple_chart_root_contracts_rejected():
    """Per PCDN-004: at most one `<sos:contract>` at chart root."""
    chart = _chart([_state("s")])
    chart["other_element"] = [
        _contract_element(reads="x"),
        _contract_element(reads="y"),
    ]
    with pytest.raises(Sos12AnnotationError) as excinfo:
        parse_dispatch_annotations(chart)
    assert "PCDN-SOS-12-004" in (excinfo.value.rule or "")


def test_contract_unknown_child_element_rejected():
    """Per PCDN-004: only events-in / events-out / invariants are valid
    contract children. Unknown qnames raise."""
    bogus_child = {"qname": f"{{{SOS_NS}}}mystery", "text": ""}
    chart = _chart([_state("s")])
    chart["other_element"] = [
        {
            "qname": CONTRACT_QN,
            "text": "",
            "attributes": {},
            "children": [bogus_child],
        }
    ]
    with pytest.raises(Sos12AnnotationError) as excinfo:
        parse_dispatch_annotations(chart)
    assert "PCDN-SOS-12-004" in (excinfo.value.rule or "")


def test_events_in_with_non_event_child_rejected():
    """A `<sos:events-in>` carrying anything other than `<sos:event>` raises."""
    chart = _chart([_state("s")])
    bogus = {"qname": f"{{{SOS_NS}}}bogus", "text": "x"}
    chart["other_element"] = [
        {
            "qname": CONTRACT_QN,
            "text": "",
            "attributes": {},
            "children": [
                {"qname": EVENTS_IN_QN, "text": "", "children": [bogus]}
            ],
        }
    ]
    with pytest.raises(Sos12AnnotationError):
        parse_dispatch_annotations(chart)


def test_events_in_empty_text_rejected():
    """Empty event-name text raises (chart-author error: events are named)."""
    chart = _chart(
        [_state("s")],
        contract=_contract_element(events_in=[""]),
    )
    with pytest.raises(Sos12AnnotationError) as excinfo:
        parse_dispatch_annotations(chart)
    assert "non-empty" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Dispatch element validation
# ---------------------------------------------------------------------------


def test_dispatch_unknown_attribute_rejected():
    """Per PCDN-001: `<sos:dispatch>` frozen attribute set is {"ref"}."""
    chart = _chart(
        [_state("s", dispatches=[_dispatch_element("c.scxml", extra_attrs={"depth": "3"})])]
    )
    with pytest.raises(Sos12AnnotationError) as excinfo:
        parse_dispatch_annotations(chart)
    assert "PCDN-SOS-12-001" in (excinfo.value.rule or "")
    assert "depth" in str(excinfo.value)


def test_dispatch_missing_ref_rejected():
    """Per PCDN-001: `ref` is required and non-empty."""
    chart = _chart(
        [_state("s", dispatches=[{"qname": DISPATCH_QN, "text": "", "attributes": {}}])]
    )
    with pytest.raises(Sos12AnnotationError) as excinfo:
        parse_dispatch_annotations(chart)
    assert "PCDN-SOS-12-001" in (excinfo.value.rule or "")
    assert "ref" in str(excinfo.value)


def test_dispatch_inside_parallel_rejected():
    """Per §5.1: dispatched states are sequential composition;
    `<sos:dispatch>` on a `<parallel>` is rejected."""
    chart = {
        "state": [],
        "parallel": [
            {
                "id": "regions",
                "other_element": [_dispatch_element("c.scxml")],
            }
        ],
    }
    with pytest.raises(Sos12AnnotationError) as excinfo:
        parse_dispatch_annotations(chart)
    assert "PCDN-SOS-12-001" in (excinfo.value.rule or "")


def test_multiple_dispatches_on_one_state_all_surface():
    """A `<state>` MAY carry multiple `<sos:dispatch>` references; each
    appears as its own DispatchAnnotation entry in document order."""
    chart = _chart(
        [
            _state(
                "router",
                dispatches=[
                    _dispatch_element("a.scxml"),
                    _dispatch_element("b.scxml"),
                ],
            )
        ]
    )
    inv = parse_dispatch_annotations(chart)
    assert [d.ref for d in inv.dispatches] == ["a.scxml", "b.scxml"]
    assert all(d.parent_state_id == "router" for d in inv.dispatches)


def test_dispatch_inside_nested_state_carries_dotted_path():
    """A `<sos:dispatch>` inside a nested `<state>` records the dotted
    parent-state path in `parent_state_id` for error messages."""
    chart = _chart(
        [
            {
                "id": "outer",
                "state": [
                    _state("inner", dispatches=[_dispatch_element("c.scxml")])
                ],
            }
        ]
    )
    inv = parse_dispatch_annotations(chart)
    assert inv.dispatches[0].parent_state_id == "outer.inner"


# ---------------------------------------------------------------------------
# Depth-cap (PCDN-005 / §6.5)
# ---------------------------------------------------------------------------


def test_synthetic_recursive_chain_at_default_cap_admissible():
    """Build an 8-deep synthetic chain via a recursion-counting fake loader;
    walking to depth 8 succeeds (cap is inclusive at 8)."""
    # We model each level as a chart that dispatches into "level_{i+1}.fake".
    # The "loader" returns the appropriate level dict by parsing the ref.
    DEPTH = 8

    def fake_loader(path: Path) -> dict:
        stem = path.stem  # e.g. "level_3"
        idx = int(stem.split("_")[1])
        if idx >= DEPTH:
            return _chart([_state("leaf")])
        return _chart(
            [_state("s", dispatches=[_dispatch_element(f"level_{idx + 1}.fake")])]
        )

    root = _chart(
        [_state("s", dispatches=[_dispatch_element("level_1.fake")])]
    )
    inv = parse_dispatch_annotations(
        root,
        chart_path=Path("/tmp/sos12_fake_root/level_0.scxml"),
        loader=fake_loader,
    )
    # Walk down the chain — last node should be at depth 8 (the cap).
    cur = inv
    depths_visited: list[int] = []
    while cur is not None:
        depths_visited.append(cur.depth)
        cur = cur.sub_inventories[0] if cur.sub_inventories else None
    assert depths_visited == list(range(0, DEPTH + 1))


def test_synthetic_recursive_chain_one_level_past_cap_rejects():
    """One-extra-level chain exceeds the default 8-cap and raises with
    a message citing PCDN-005 / §6.5 / INV-S-DISP-5."""
    DEPTH_OVERFLOW = 9

    def fake_loader(path: Path) -> dict:
        stem = path.stem
        idx = int(stem.split("_")[1])
        if idx >= DEPTH_OVERFLOW:
            return _chart([_state("leaf")])
        return _chart(
            [_state("s", dispatches=[_dispatch_element(f"level_{idx + 1}.fake")])]
        )

    root = _chart(
        [_state("s", dispatches=[_dispatch_element("level_1.fake")])]
    )
    with pytest.raises(Sos12AnnotationError) as excinfo:
        parse_dispatch_annotations(
            root,
            chart_path=Path("/tmp/sos12_fake_root_overflow/level_0.scxml"),
            loader=fake_loader,
        )
    msg = str(excinfo.value)
    assert "max_depth" in msg or "depth" in msg
    assert "PCDN-SOS-12-005" in msg or "6.5" in (excinfo.value.rule or "")


def test_max_depth_zero_rejects_any_dispatch():
    """`max_depth=0` means the root chart may have no dispatches at all."""
    chart = _chart(
        [_state("s", dispatches=[_dispatch_element("anything.scxml")])]
    )
    with pytest.raises(Sos12AnnotationError):
        parse_dispatch_annotations(chart, max_depth=0)


def test_max_depth_one_allows_root_but_rejects_recursion():
    """`max_depth=1` allows the root to dispatch but rejects the sub-chart
    from dispatching further. Drives via a fake loader."""

    def fake_loader(path: Path) -> dict:
        return _chart(
            [_state("s", dispatches=[_dispatch_element("grand.scxml")])]
        )

    root = _chart(
        [_state("s", dispatches=[_dispatch_element("child.scxml")])]
    )
    with pytest.raises(Sos12AnnotationError):
        parse_dispatch_annotations(
            root,
            chart_path=Path("/tmp/sos12_fake_md1/root.scxml"),
            max_depth=1,
            loader=fake_loader,
        )


# ---------------------------------------------------------------------------
# Acyclicity (INV-S-DISP-3)
# ---------------------------------------------------------------------------


def test_self_dispatch_cycle_rejected():
    """A chart whose `<sos:dispatch ref="self.scxml">` resolves back to
    itself is INV-S-DISP-3 acyclic-violating and rejects."""

    def fake_loader(path: Path) -> dict:
        # Returns the same dispatch-self shape regardless of path.
        return _chart(
            [_state("s", dispatches=[_dispatch_element("self.scxml")])]
        )

    root_path = Path("/tmp/sos12_fake_cycle/self.scxml").resolve()
    root = _chart(
        [_state("s", dispatches=[_dispatch_element("self.scxml")])]
    )
    with pytest.raises(Sos12AnnotationError) as excinfo:
        parse_dispatch_annotations(
            root, chart_path=root_path, loader=fake_loader
        )
    assert "INV-S-DISP-3" in (excinfo.value.rule or "")


# ---------------------------------------------------------------------------
# Fixture-driven integration tests (require scjson on PATH).
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sos_12"


def _load_chart_or_skip(path: Path) -> dict:
    """Best-effort loader.load_chart that skips the test if scjson is absent."""
    try:
        from loader import load_chart  # noqa: WPS433 (local import is intentional)
    except Exception as exc:  # pragma: no cover - defensive
        pytest.skip(f"loader unavailable: {exc}")
    try:
        ast = load_chart(path).raw_scjson
    except (FileNotFoundError, RuntimeError) as exc:
        pytest.skip(f"scjson unavailable or chart load failed: {exc}")
    assert ast is not None
    return ast


def test_fixture_single_level_dispatch_roundtrip():
    """Real `.scxml` parent dispatches into `child_leaf.scxml`; recursion
    surfaces the leaf's contract under sub_inventories."""
    parent = _FIXTURE_DIR / "parent_single_level.scxml"
    ast = _load_chart_or_skip(parent)
    inv = parse_dispatch_annotations(ast, chart_path=parent)
    assert inv.chart_ref == "parent_single_level.scxml"
    assert inv.depth == 0
    assert len(inv.dispatches) == 1
    assert inv.dispatches[0].parent_state_id == "handle_get"
    assert inv.dispatches[0].ref == "child_leaf.scxml"
    assert inv.dispatches[0].resolved_path is not None
    assert inv.dispatches[0].resolved_path.name == "child_leaf.scxml"
    assert inv.unresolved_refs == ()
    # Sub-inventory carries the leaf's contract.
    assert len(inv.sub_inventories) == 1
    sub = inv.sub_inventories[0]
    assert sub.chart_ref == "child_leaf.scxml"
    assert sub.depth == 1
    assert sub.contract is not None
    assert sub.contract.reads == ("parsed_uri", "parsed_method")
    assert sub.contract.writes == ("response_status",)
    assert sub.contract.events_in == ("tcp.bytes_received", "timer.body_timeout")
    assert sub.contract.events_out == ("method.complete", "method.error")
    assert sub.contract.invariants_maintained == (
        "INV-GET-1-headers-bounded",
        "INV-GET-2-body-absent",
    )
    assert sub.contract.invariants_assumed == ("INV-HTTP-1-request-line-parsed",)


def test_fixture_two_level_nested_dispatch_roundtrip():
    """Real `.scxml` chain: parent → middle → child. Recursion goes 2 deep."""
    parent = _FIXTURE_DIR / "parent_two_level.scxml"
    ast = _load_chart_or_skip(parent)
    inv = parse_dispatch_annotations(ast, chart_path=parent)
    assert inv.depth == 0
    assert len(inv.sub_inventories) == 1
    mid = inv.sub_inventories[0]
    assert mid.chart_ref == "middle_layer.scxml"
    assert mid.depth == 1
    assert mid.contract is not None
    assert mid.contract.reads == ("ctx",)
    assert mid.contract.writes == ("ctx_out",)
    assert len(mid.sub_inventories) == 1
    leaf = mid.sub_inventories[0]
    assert leaf.chart_ref == "child_leaf.scxml"
    assert leaf.depth == 2
    assert leaf.sub_inventories == ()  # terminal


def test_fixture_unknown_attribute_chart_rejects():
    """A real `.scxml` with `<sos:dispatch bogus="oops"/>` raises."""
    parent = _FIXTURE_DIR / "unknown_attr_parent.scxml"
    ast = _load_chart_or_skip(parent)
    with pytest.raises(Sos12AnnotationError) as excinfo:
        parse_dispatch_annotations(ast, chart_path=parent)
    assert "PCDN-SOS-12-001" in (excinfo.value.rule or "")
    assert "bogus" in str(excinfo.value)


def test_fixture_contract_only_full_population():
    """Real `.scxml` with a richly-populated contract and no dispatch
    parses every contract field."""
    chart = _FIXTURE_DIR / "contract_only.scxml"
    ast = _load_chart_or_skip(chart)
    inv = parse_dispatch_annotations(ast, chart_path=chart)
    assert inv.dispatches == ()
    assert inv.contract is not None
    c = inv.contract
    assert c.reads == ("input_buf", "header_count")
    assert c.writes == ("output_buf", "status")
    assert c.events_in == ("ingest.bytes", "ingest.eof")
    assert c.events_out == ("frame.emitted", "parse.error")
    assert c.invariants_maintained == ("INV-CO-1", "INV-CO-2")
    assert c.invariants_assumed == ("INV-ENV-1", "INV-ENV-2")


def test_fixture_deep_chain_at_boundary_admits_under_default_cap():
    """8-deep file-backed chain walks cleanly under the default cap."""
    root = _FIXTURE_DIR / "deep_chain" / "level_0.scxml"
    ast = _load_chart_or_skip(root)
    inv = parse_dispatch_annotations(ast, chart_path=root)
    # Walk to the deepest sub_inventory.
    cur = inv
    depths: list[int] = []
    while cur is not None:
        depths.append(cur.depth)
        cur = cur.sub_inventories[0] if cur.sub_inventories else None
    assert depths == list(range(0, 9))  # depths 0..8, inclusive


def test_fixture_deep_chain_overflow_rejects():
    """9-deep file-backed chain rejects with a depth-cap diagnostic."""
    root = _FIXTURE_DIR / "deep_chain_overflow" / "level_0.scxml"
    ast = _load_chart_or_skip(root)
    with pytest.raises(Sos12AnnotationError) as excinfo:
        parse_dispatch_annotations(ast, chart_path=root)
    msg = str(excinfo.value)
    assert "PCDN-SOS-12-005" in msg or "6.5" in (excinfo.value.rule or "")

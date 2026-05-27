"""SOS-11 four-axis validation composer.

Authority:
    - ``docs/concepts/SOS-11-CONCEPTS.md`` §6 — the four-axis result-contract
      surface: ``scjson_round_trip`` (a), ``lint`` (b), ``bound_converges`` (c),
      ``invariants_hold`` (d). All four MUST pass for a chart edit to commit
      (§6 read together with §7 atomicity).
    - ``docs/concepts/SOS-11-CONCEPTS.md`` §15 Wave-1 "Still open" item #2
      (``validation.py`` composer) — this module closes that line item.
    - ``docs/concepts/SOS-11-CONCEPTS.md`` §7 — the failure model: the
      composer NEVER raises; failures surface as ``passed=False`` axis
      reports so the caller (extract / inline handlers, future MCP
      transport) decides whether to roll back.
    - Wave-3 J / Wave-3 K precedent — :mod:`sos11_mcp.extract` and
      :mod:`sos11_mcp.inline` populate the four-axis ``ValidationReport``
      ad-hoc; once Wave-4 lands, both handlers will delegate to this
      composer (out-of-scope follow-up PR per the Wave-4 dispatch
      contract).

Substrate map
-------------

Each axis consumes a single-purpose substrate that already exists in tree:

================  =====================================================
Axis              Substrate
================  =====================================================
scjson_round_trip ``scjson.SCXMLDocumentHandler.xml_to_json`` /
                  ``json_to_xml`` driven through the loader convention
                  established by :mod:`sos11_mcp.inline`; structured
                  diff via :func:`sos11_mcp.diffs.structured_scxml_diff`
                  asserts the round-trip is lossless.
lint              :func:`sos12_lint.check_dispatch_depth` (SCXML-LINT-
                  DISP-1) and :func:`sos12_lint.check_legibility`
                  (SCXML-LINT-DISP-2). The broader SOS-01 lint runner
                  (SCXML-LINT-CH-{1,2,3}) is reserved at SOS-01 §15 but
                  no runner module exists yet — the composer reports
                  the CH rules as ``"deferred: SOS-01-CH-runner not
                  yet wired"`` and does NOT pretend to evaluate them.
bound_converges   :func:`sos12_annotations.parse_dispatch_annotations`
                  drives the per-chart inventory; the composer then
                  builds a :class:`sos12_bound.BoundInputs` keyed off
                  the inventory and invokes
                  :func:`sos12_bound.compose_bound`. The bound
                  converges when the call returns without raising
                  :class:`sos12_bound.Sos12BoundError`.
invariants_hold   :func:`sos12_contract_match.verify_inventory` walks
                  the parsed inventory; a passing walk means every
                  dispatch boundary satisfies SOS-12 §5.3.
================  =====================================================

Charts with **no** dispatch annotations (single-chart families) trivially
pass ``bound_converges`` (the singleton chart's per-layer bound IS the
composed bound — convergence is vacuous) and ``invariants_hold`` (with no
edges there are no contracts to mismatch).

Public surface
--------------

::

    validate_chart(
        chart_path: str | Path,
        *,
        axes: tuple[ValidationAxis, ...] = ALL_AXES,
        max_depth: int = 8,
        legibility_threshold: int = 15,
    ) -> ValidationReport

The composer is **pure** modulo a single file read (``chart_path``) and
the substrates' own I/O (e.g. the dispatch parser may load resolved sub-
charts from disk). No state escapes the call. Errors in any individual
axis become ``passed=False`` reports — the composer NEVER raises so a
chart with one bad axis does not abort the whole validation call.

Honest-partial reporting
------------------------

Following the Wave-3 J / Wave-3 K precedent: when a substrate isn't yet
wired (the SOS-01 CH-rule runner, today), the composer marks the axis as
``passed=True`` with a ``diagnosis="deferred: <reason>"`` string. The
distinction from a substantive pass: a deferred axis carries a non-None
diagnosis whose text starts with ``"deferred"``; a substantive pass
carries either ``None`` or a substrate-specific success diagnosis.
Refusing to populate the axis would block the composer's adoption; a
silent stub would mask real failures — naming the deferral is the
in-between stance.

The ``axes`` keyword lets callers opt-in only to a subset (e.g. an
extraction handler may want round-trip + invariants only, deferring lint
+ bound to the post-commit sweep). Unselected axes return
``passed=True`` with diagnosis ``"not requested"``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Union

# The sos-codegen tree is not a package (dash in its directory name); mirror
# the bootstrap pattern used by sibling SOS-11 handlers so this composer is
# importable regardless of how callers wire up ``sys.path``.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos11_mcp.contracts import (  # noqa: E402
    AxisStatus,
    ValidationAxis,
    ValidationAxisReport,
    ValidationReport,
)
from sos11_mcp.diffs import structured_scxml_diff  # noqa: E402


# ---------------------------------------------------------------------------
# Frozen defaults — Specification Required policy mirrors the substrates' own
# defaults so calling the composer with no overrides exercises the SOS-12
# §6.5 / §9.1 / PCDN-005 / PCDN-003 ratified values.
# ---------------------------------------------------------------------------

DEFAULT_MAX_DEPTH: int = 8
DEFAULT_LEGIBILITY_THRESHOLD: int = 15

#: Convenience: every axis in field order.
ALL_AXES: tuple[ValidationAxis, ...] = (
    ValidationAxis.SCJSON_ROUND_TRIP,
    ValidationAxis.LINT,
    ValidationAxis.BOUND_CONVERGES,
    ValidationAxis.INVARIANTS_HOLD,
)


# ---------------------------------------------------------------------------
# Internal helpers — chart loading shared across axes.
# ---------------------------------------------------------------------------


def _load_chart_ast(chart_path: Path) -> dict[str, Any]:
    """Load the chart through :class:`scjson.SCXMLDocumentHandler.xml_to_json`.

    Mirrors :mod:`sos11_mcp.inline`'s convention rather than
    :mod:`loader`'s shell-out so the AST preserves the SOS foreign
    elements (``<sos:dispatch>``, ``<sos:contract>``) the bound /
    invariants axes need. The composer never invokes the codegen loader
    directly.
    """
    from scjson.SCXMLDocumentHandler import SCXMLDocumentHandler

    xml = chart_path.read_text(encoding="utf-8")
    handler = SCXMLDocumentHandler(omit_empty=False)
    return json.loads(handler.xml_to_json(xml))


def _serialise_ast(ast: Mapping[str, Any]) -> str:
    """Serialise an scjson AST back to SCXML XML text."""
    from scjson.SCXMLDocumentHandler import SCXMLDocumentHandler

    handler = SCXMLDocumentHandler(omit_empty=False)
    return handler.json_to_xml(json.dumps(ast))


# ---------------------------------------------------------------------------
# Axis (a): scjson_round_trip
# ---------------------------------------------------------------------------


def _check_scjson_round_trip(chart_path: Path) -> ValidationAxisReport:
    """Round-trip the chart's SCXML through scjson and assert no drift.

    Procedure:
      1. ``xml_to_json`` the SCXML text into an AST.
      2. ``json_to_xml`` the AST back to SCXML.
      3. ``xml_to_json`` the result and assert :func:`structured_scxml_diff`
         against the first AST is empty (states / transitions / datamodel
         all match).

    A non-empty diff means the round-trip lost information; a raised
    exception (parser failure, malformed input, ...) is captured as
    ``passed=False`` with the exception text as the diagnosis. Per §7
    the composer never re-raises.
    """
    axis = ValidationAxis.SCJSON_ROUND_TRIP
    try:
        first_ast = _load_chart_ast(chart_path)
    except FileNotFoundError as exc:
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=f"chart not found: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"scjson failed to parse {chart_path.name!r}: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    try:
        serialised = _serialise_ast(first_ast)
        second_ast = json.loads(_xml_to_json_again(serialised))
    except Exception as exc:  # noqa: BLE001
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"round-trip serialise/re-parse failed: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    diff = structured_scxml_diff(first_ast, second_ast)
    if _diff_is_empty(diff):
        return ValidationAxisReport(
            axis=axis,
            passed=True,
            diagnosis=None,
        )
    return ValidationAxisReport(
        axis=axis,
        passed=False,
        diagnosis=(
            f"scjson round-trip is lossy for {chart_path.name!r}: "
            f"structured diff names states={_diff_keys(diff, 'states')}, "
            f"transitions={_diff_keys(diff, 'transitions')}, "
            f"datamodel={_diff_keys(diff, 'datamodel')}"
        ),
    )


def _xml_to_json_again(xml: str) -> str:
    """Single-shot ``xml_to_json`` helper used by the round-trip path."""
    from scjson.SCXMLDocumentHandler import SCXMLDocumentHandler

    handler = SCXMLDocumentHandler(omit_empty=False)
    return handler.xml_to_json(xml)


def _diff_is_empty(diff: Mapping[str, Any]) -> bool:
    """Return ``True`` if a :func:`structured_scxml_diff` payload is empty."""
    states = diff.get("states", {})
    transitions = diff.get("transitions", {})
    datamodel = diff.get("datamodel", {})
    return (
        not states.get("added")
        and not states.get("removed")
        and not transitions.get("added")
        and not transitions.get("removed")
        and not datamodel.get("added")
        and not datamodel.get("removed")
        and not datamodel.get("changed")
    )


def _diff_keys(diff: Mapping[str, Any], category: str) -> list[str]:
    """Surface a flat list of added/removed/changed ids for one diff section."""
    section = diff.get(category, {})
    keys: list[str] = []
    for bucket in ("added", "removed", "changed"):
        for entry in section.get(bucket, ()) or ():
            if isinstance(entry, Mapping):
                if "id" in entry:
                    keys.append(f"{bucket}:{entry['id']}")
                elif "source" in entry and "target" in entry:
                    keys.append(
                        f"{bucket}:{entry['source']}->{entry['target']}"
                    )
                else:
                    keys.append(bucket)
            else:
                keys.append(f"{bucket}:{entry}")
    return keys


# ---------------------------------------------------------------------------
# Axis (b): lint
# ---------------------------------------------------------------------------


def _check_lint(
    chart_path: Path,
    *,
    max_depth: int,
    legibility_threshold: int,
) -> ValidationAxisReport:
    """Run SOS-12 chart-decomposition lint over the chart.

    Wired rules:
      - SCXML-LINT-DISP-1 (dispatch-tree depth cap, SOS-12 §6.5 /
        PCDN-005, default 8).
      - SCXML-LINT-DISP-2 (peer-state legibility threshold, SOS-12 §9.1 /
        PCDN-003, default 15).

    Deferred rules:
      - SCXML-LINT-CH-{1,2,3} are reserved at SOS-01 §15 but no general
        runner module exists yet. The composer surfaces this as part of
        a successful lint pass diagnosis — the wired rules ARE evaluated;
        the unwired ones are named explicitly so callers know they were
        not consulted.

    A single diagnostic from either wired rule fails the axis; the
    diagnosis carries the rule id + the location it pinned. The composer
    surfaces the FIRST diagnostic encountered (DISP-1 walked before
    DISP-2) — this matches the "diagnose one bug at a time" precedent
    set by the SOS-09 / SOS-10 annotation parsers.
    """
    axis = ValidationAxis.LINT
    from sos12_lint import check_dispatch_depth, check_legibility

    try:
        depth_diags = check_dispatch_depth(chart_path, max_depth=max_depth)
    except FileNotFoundError as exc:
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=f"chart not found: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"SCXML-LINT-DISP-1 runner crashed: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    if depth_diags:
        first = depth_diags[0]
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"[{first.rule_id}] {first.location}: {first.message}"
            ),
        )

    try:
        leg_diags = check_legibility(
            chart_path,
            legibility_threshold=legibility_threshold,
        )
    except Exception as exc:  # noqa: BLE001
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"SCXML-LINT-DISP-2 runner crashed: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    if leg_diags:
        first = leg_diags[0]
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"[{first.rule_id}] {first.location}: {first.message}"
            ),
        )

    return ValidationAxisReport(
        axis=axis,
        passed=True,
        diagnosis=(
            "SCXML-LINT-DISP-{1,2} passed; SCXML-LINT-CH-{1,2,3} "
            "deferred: SOS-01-CH-runner not yet wired"
        ),
    )


# ---------------------------------------------------------------------------
# Axis (c): bound_converges
# ---------------------------------------------------------------------------


def _check_bound_converges(
    chart_path: Path,
    *,
    max_depth: int,
) -> ValidationAxisReport:
    """Verify the chart's dispatch-tree bound converges within ``max_depth``.

    Procedure:
      1. Parse the chart's dispatch annotations into a
         :class:`sos12_annotations.DispatchInventory`.
      2. Walk the inventory to enumerate (parent, child) chart-ref pairs
         and assign each chart a per-layer reachability bound. v1 uses
         the chart's reachable-state count as a proxy (a state-counting
         walk over the scjson AST); SOS-03's bound computation is the
         eventual canonical source and remains deferred.
      3. Hand the inputs to :func:`sos12_bound.compose_bound`. Convergence
         IS the return-without-raising property; an
         :class:`sos12_bound.Sos12BoundError` (depth cap, DAG violation,
         missing child) becomes a ``passed=False`` diagnosis citing the
         offending location.

    Single-chart families (no ``<sos:dispatch>`` annotations) pass
    trivially — the per-layer bound IS the composed bound, no
    composition recursion happens, convergence is vacuous.
    """
    axis = ValidationAxis.BOUND_CONVERGES
    from sos12_annotations import (
        Sos12AnnotationError,
        parse_dispatch_annotations,
    )
    from sos12_bound import (
        BoundInputs,
        DispatchEdge,
        Sos12BoundError,
        compose_bound,
    )

    try:
        ast = _load_chart_ast(chart_path)
    except FileNotFoundError as exc:
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=f"chart not found: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"scjson failed to parse {chart_path.name!r}: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    try:
        inventory = parse_dispatch_annotations(
            ast, chart_path=chart_path, max_depth=max_depth,
        )
    except Sos12AnnotationError as exc:
        # The §6.5 depth-cap is the most-likely-fire path; the lint axis
        # also catches this. Surface it here too so a caller running only
        # the bound axis still gets the failure.
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"dispatch-annotation parse failed at {exc.element_path or chart_path.name}: "
                f"{exc}"
            ),
        )
    except FileNotFoundError as exc:
        # A sub-chart reference resolved to a missing file. INV-S-DISP-2:
        # contract-matching is mandatory; a missing sub-chart is a
        # convergence failure (the bound cannot be composed across a
        # phantom edge).
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=f"dispatched sub-chart missing: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"dispatch-annotation parse failed for {chart_path.name!r}: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    # Build BoundInputs from the inventory by walking the dispatch tree.
    charts: dict[str, int] = {}
    edges: list[DispatchEdge] = []

    def _collect(inv: Any) -> None:
        chart_id = inv.chart_ref
        if chart_id not in charts:
            # Per-layer bound proxy: count reachable states. SOS-03's
            # full bound computation is the eventual source; the proxy
            # suffices for convergence checking because compose_bound's
            # raises are driven by structural properties (depth, DAG,
            # missing child), not by the magnitude of the bound.
            if chart_id == inv.chart_ref and inv is _root_inventory[0]:
                # Use the loaded AST for the root chart's state count.
                charts[chart_id] = max(_count_states(ast), 1)
            else:
                # Sub-charts: estimate from sub_inventories alone — we
                # don't carry the sub-chart's AST through this surface.
                # v1 uses 1 (a chart that resolved is at least one
                # reachable state); a future SOS-03 wire will replace
                # the estimate with the canonical bound.
                charts[chart_id] = max(charts.get(chart_id, 0), 1)
        for annotation in inv.dispatches:
            # Resolve the child ref to a child chart_id. Prefer the
            # sub_inventory match by file name; fall back to the raw ref
            # otherwise.
            child_id = annotation.ref
            for sub in inv.sub_inventories:
                if sub.chart_ref == annotation.ref or (
                    annotation.resolved_path
                    and sub.chart_ref == annotation.resolved_path.name
                ):
                    child_id = sub.chart_ref
                    break
            if child_id not in charts:
                charts[child_id] = 1
            edges.append(
                DispatchEdge(
                    parent_chart_id=chart_id,
                    parent_state_id=annotation.parent_state_id,
                    child_chart_id=child_id,
                )
            )
        for sub in inv.sub_inventories:
            _collect(sub)

    _root_inventory: list[Any] = [inventory]
    _collect(inventory)

    inputs = BoundInputs(
        root_chart_id=inventory.chart_ref,
        charts=charts,
        edges=edges,
        max_depth=max_depth,
    )

    try:
        result = compose_bound(inputs)
    except Sos12BoundError as exc:
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"bound composition failed for chart family rooted at "
                f"{chart_path.name!r}: {exc}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"bound composition crashed: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    layer_count = len(result.per_layer_breakdown)
    return ValidationAxisReport(
        axis=axis,
        passed=True,
        diagnosis=(
            f"bound converges: composed_bound={result.composed_bound}, "
            f"layers={layer_count}, edges={len(edges)}"
        ),
    )


def _count_states(node: Mapping[str, Any]) -> int:
    """Walk a scjson AST and count ``<state>`` + ``<parallel>`` elements."""
    total = 0
    for kind in ("state", "parallel"):
        children = node.get(kind) or []
        if isinstance(children, list):
            iterable: Iterable[Any] = children
        else:
            iterable = [children]
        for child in iterable:
            if isinstance(child, Mapping):
                total += 1
                total += _count_states(child)
    return total


# ---------------------------------------------------------------------------
# Axis (d): invariants_hold
# ---------------------------------------------------------------------------


def _check_invariants_hold(
    chart_path: Path,
    *,
    max_depth: int,
) -> ValidationAxisReport:
    """Verify every dispatch boundary satisfies SOS-12 §5.3 contract-match.

    Procedure:
      1. Parse the chart's dispatch annotations into a
         :class:`sos12_annotations.DispatchInventory`.
      2. Walk the inventory via
         :func:`sos12_contract_match.verify_inventory` using the default
         ``simple_edge_provider`` — adequate for single-dispatch parent
         charts and for any inventory where the parent's chart-level
         contract equals its dispatch site's boundary surface.

    A passing walk means every dispatch boundary satisfies the §5.3
    six-clause algebra (events_in / events_out / invariants_maintained /
    invariants_assumed / reads / writes). A
    :class:`sos12_contract_match.ContractMismatchError` becomes a
    ``passed=False`` diagnosis citing the failing clause + chart_path +
    missing/extra sets.

    Single-chart families (no dispatches, no contracts to mismatch) pass
    trivially.
    """
    axis = ValidationAxis.INVARIANTS_HOLD
    from sos12_annotations import (
        Sos12AnnotationError,
        parse_dispatch_annotations,
    )
    from sos12_contract_match import (
        ContractMismatchError,
        verify_inventory,
    )

    try:
        ast = _load_chart_ast(chart_path)
    except FileNotFoundError as exc:
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=f"chart not found: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"scjson failed to parse {chart_path.name!r}: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    try:
        inventory = parse_dispatch_annotations(
            ast, chart_path=chart_path, max_depth=max_depth,
        )
    except Sos12AnnotationError as exc:
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"dispatch-annotation parse failed at "
                f"{exc.element_path or chart_path.name}: {exc}"
            ),
        )
    except FileNotFoundError as exc:
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=f"dispatched sub-chart missing: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"dispatch-annotation parse failed for {chart_path.name!r}: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    try:
        verify_inventory(inventory)
    except ContractMismatchError as exc:
        chart_loc = exc.chart_path or chart_path.name
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"[PCDN-SOS-12-006] [INV-S-DISP-2] clause={exc.clause} at "
                f"{chart_loc!r}: missing={sorted(exc.missing)!r}, "
                f"extra={sorted(exc.extra)!r}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return ValidationAxisReport(
            axis=axis,
            passed=False,
            diagnosis=(
                f"invariants_hold check crashed: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    return ValidationAxisReport(
        axis=axis,
        passed=True,
        diagnosis=(
            "all dispatch boundaries pass SOS-12 §5.3 contract-match"
        ),
    )


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


def validate_chart(
    chart_path: Union[str, Path],
    *,
    axes: tuple[ValidationAxis, ...] = ALL_AXES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    legibility_threshold: int = DEFAULT_LEGIBILITY_THRESHOLD,
) -> ValidationReport:
    """Run the four-axis SOS-11 §6 validation pipeline over a chart.

    Args:
        chart_path: filesystem path to the chart's SCXML file. The
            composer reads the file once and feeds the parsed AST into
            each requested axis.
        axes: tuple of :class:`ValidationAxis` values to evaluate.
            Defaults to all four. Axes NOT in this tuple return
            ``passed=True`` with ``diagnosis="not requested"`` so the
            :class:`ValidationReport` shape stays the same regardless of
            selection (callers can always iterate axis_reports and trust
            the four fields are populated).
        max_depth: SOS-12 §6.5 / PCDN-005 dispatch-tree depth cap.
            Propagates to both the lint and bound axes. Default 8.
        legibility_threshold: SOS-12 §9.1 / PCDN-003 peer-state
            legibility threshold. Propagates to the lint axis only.
            Default 15.

    Returns:
        :class:`ValidationReport` whose four fields each carry an
        :class:`ValidationAxisReport`. The overall
        :attr:`ValidationReport.passed` property returns ``True`` iff
        every axis reported ``passed=True`` (selected or not).

    Never raises. Substrate failures (missing file, malformed SCXML,
    crashed substrate) become ``passed=False`` reports with the
    exception text as the diagnosis. The composer's caller (extract /
    inline handlers, future MCP transport) inspects the report and
    decides whether to roll back the chart edit per §7 atomicity.
    """
    path = Path(chart_path)

    selected = set(axes)

    def _resolve(axis: ValidationAxis, runner: Callable[[], ValidationAxisReport]) -> ValidationAxisReport:
        if axis not in selected:
            return ValidationAxisReport(
                axis=axis,
                passed=True,
                diagnosis="not requested",
                status=AxisStatus.NOT_REQUESTED,
            )
        return runner()

    round_trip_report = _resolve(
        ValidationAxis.SCJSON_ROUND_TRIP,
        lambda: _check_scjson_round_trip(path),
    )
    lint_report = _resolve(
        ValidationAxis.LINT,
        lambda: _check_lint(
            path,
            max_depth=max_depth,
            legibility_threshold=legibility_threshold,
        ),
    )
    bound_report = _resolve(
        ValidationAxis.BOUND_CONVERGES,
        lambda: _check_bound_converges(path, max_depth=max_depth),
    )
    invariants_report = _resolve(
        ValidationAxis.INVARIANTS_HOLD,
        lambda: _check_invariants_hold(path, max_depth=max_depth),
    )

    return ValidationReport(
        scjson_round_trip=round_trip_report,
        lint=lint_report,
        bound_converges=bound_report,
        invariants_hold=invariants_report,
    )


__all__ = [
    "ALL_AXES",
    "DEFAULT_LEGIBILITY_THRESHOLD",
    "DEFAULT_MAX_DEPTH",
    "validate_chart",
]

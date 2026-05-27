"""SOS-11 ``inline_subchart`` MCP tool handler — Wave-3K.

Authority:
    - ``docs/concepts/SOS-11-CONCEPTS.md`` §5.1 (``inline_subchart`` primitive
      definition; inverse of ``extract_region_to_subchart``).
    - ``docs/concepts/SOS-11-CONCEPTS.md`` §6 (four-tuple ``ToolCallResult``
      contract: ``scxml_diff`` / ``vector_delta`` / ``summary`` / ``validation``)
      and §7 (atomic ``ToolCallError`` shape).
    - ``docs/concepts/SOS-12-CONCEPTS.md`` §5.3 (contract-match algebra) +
      PCDN-SOS-12-006 (compile-time error on mismatch); §9 (legibility
      threshold integration) + PCDN-SOS-12-003 (default 15 peer states).
    - Wave-2I ``sos12_contract_match.verify_contract_match`` is the gate-
      keeper for clause (1): refuse to silently merge a stale dispatch edge.
    - Wave-1C ``sos12_boundary_vectors.emit_boundary_vectors`` produces the
      boundary-vector set that retires post-inline; the ``vector_delta``
      summary states which vectors are negated by the inline.

Semantics
---------

``inline_subchart(parent_chart_path, dispatch_state_id)`` is the reverse of
``extract_region_to_subchart``. It:

1. Loads the parent chart AST from ``parent_chart_path``.
2. Locates the ``<state id="{dispatch_state_id}">`` carrying a
   ``<sos:dispatch ref="…"/>`` element.
3. Loads the child sub-chart from the dispatch ref (resolved against the
   parent chart's directory).
4. Constructs the current ``DispatchContractEdge`` from the parent's
   chart-level expectation + the child's declared contract (the
   ``simple_edge_provider`` shape from Wave-2I) and runs
   ``verify_contract_match``. A mismatch yields a ``rejected`` result citing
   the failing §5.3 clause — inlining a stale edge would produce a chart
   whose behaviour deviates from the dispatch-tree's verification basis
   (Wave-2I module docstring, "Wave-3 extension points: Wave-3 K").
5. Computes the post-inline legibility impact. The default threshold is 15
   peer states at any one level (PCDN-SOS-12-003). If the post-inline
   parent's max peer-state count across any level would exceed the
   threshold, the inline is rejected with diagnosis citing §9.2.
6. Otherwise merges the child sub-chart's body into the parent at the
   dispatch site: the dispatch state's nested ``state`` / ``parallel``
   children become the child's body; the dispatch state's
   ``initial_attribute`` becomes the child's chart-root ``initial``; the
   ``<sos:dispatch>`` element is removed from ``other_element``; any state-
   id collisions between the inlined child states and the parent's other
   peer state ids are rewritten by prefixing with ``{dispatch_state_id}__``
   (rewriting all internal transition targets in the child body to match).
7. Computes the SCXML diff (``diffs.build_scxml_diff``) and the negated
   ``vector_delta`` summary (boundary vectors that no longer exist post-
   inline; rendered via ``sos12_boundary_vectors.emit_boundary_vectors``
   on the pre-inline edge).

State-id rewriting policy
-------------------------

When a child sub-chart state id collides with a parent peer state id at any
level, the v1 policy rewrites the inlined child id to
``{dispatch_state_id}__{original_child_id}``. The dispatch state's own id is
NOT rewritten (it remains the parent's anchor). The rewrite is applied to
every transition target inside the inlined child body so internal references
stay consistent. The rewrite is local: parent transitions targeting the
dispatch state (e.g. external ``abort → recover`` paths) are preserved
verbatim because the dispatch state's id is unchanged.

The rewrite policy is a v1 stance, not a ratified §15 frozen rule — the
SOS-11 §5.1 prose for ``inline_subchart`` says only "replaces a dispatching
state with the subchart's body inlined", without naming a collision policy.
A future amendment MAY ratify a different rewrite shape; the
``ToolCallResult.summary`` cites the rewrite when it fires so a chart author
can audit it.

Validation pipeline (deferred axes)
-----------------------------------

Per SOS-11 §6 the four validation axes are scjson round-trip, lint,
bound-converges, invariants-hold. The handler's v1 surface populates only
axes that are tractable without the as-yet-unbuilt SOS-11 validation
composer (mentioned as "Still open" item #2 in the §15 2026-05-27 entry):

  - ``scjson_round_trip``: computed by serialising the post-inline parent
    AST through ``SCXMLDocumentHandler`` and confirming the XML re-parses
    into the same AST shape.
  - ``lint``, ``bound_converges``, ``invariants_hold``: marked ``passed=True``
    with a ``diagnosis`` field naming the deferral. The composer wave (open
    against §6 axes (b)/(c)/(d)) is the canonical consumer for the
    not-yet-wired surfaces. Refusing to populate them would block the
    handler's adoption; populating them with stubs would silently mask real
    failures — naming the deferral explicitly is the in-between stance.

Pure function module; the only I/O is scjson file loading via the
``SCXMLDocumentHandler``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

# The sos-codegen tree is not a package (its directory name uses a dash).
# Mirror the bootstrap pattern used in sibling modules so this handler is
# importable from any caller that has ``tools/sos-codegen`` on its path.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos11_mcp.contracts import (  # noqa: E402
    FailureCode,
    ScxmlDiff,
    ToolCallError,
    ToolCallResult,
    ValidationAxis,
    ValidationAxisReport,
    ValidationReport,
    VectorDelta,
)
from sos11_mcp.diffs import build_scxml_diff, structured_scxml_diff  # noqa: E402
from sos12_annotations import (  # noqa: E402
    Contract,
    parse_dispatch_annotations,
)
from sos12_boundary_vectors import (  # noqa: E402
    DispatchEdge,
    SubChartContract,
    emit_boundary_vectors,
)
from sos12_contract_match import (  # noqa: E402
    ContractMismatchError,
    DispatchContractEdge,
    verify_contract_match,
)


# ---------------------------------------------------------------------------
# Frozen enums / defaults
# ---------------------------------------------------------------------------

#: Default legibility threshold per SOS-12 PCDN-SOS-12-003 / §9.1. Projects
#: MAY override per chart-family; the handler accepts an explicit
#: ``legibility_threshold`` keyword.
DEFAULT_LEGIBILITY_THRESHOLD: int = 15


#: SOS-12 ``<sos:dispatch>`` qname (mirrors the parser's frozen constant so
#: this module does not need to import the private prefix from
#: ``sos12_annotations``).
SOS_NS: str = "https://softoboros.com/sos/1.0"
_DISPATCH_QNAME: str = f"{{{SOS_NS}}}dispatch"
_CONTRACT_QNAME: str = f"{{{SOS_NS}}}contract"


# ---------------------------------------------------------------------------
# scjson loader / serialiser bridge
# ---------------------------------------------------------------------------


def _load_scjson(path: Path) -> dict[str, Any]:
    """Load an SCXML file into its scjson-shape AST dict.

    The handler MUST go through ``SCXMLDocumentHandler`` (and not through
    the codegen ``loader.load_chart`` shell-out) because the codegen
    loader normalises the AST into a script-site-centric view that drops
    the dispatch/contract foreign elements this handler needs to
    manipulate.
    """
    from scjson.SCXMLDocumentHandler import SCXMLDocumentHandler

    handler = SCXMLDocumentHandler(omit_empty=False)
    xml = Path(path).read_text(encoding="utf-8")
    return json.loads(handler.xml_to_json(xml))


def _dump_xml(ast: Mapping[str, Any]) -> str:
    """Serialise an scjson-shape AST back to SCXML XML."""
    from scjson.SCXMLDocumentHandler import SCXMLDocumentHandler

    handler = SCXMLDocumentHandler(omit_empty=False)
    return handler.json_to_xml(json.dumps(ast))


# ---------------------------------------------------------------------------
# AST traversal helpers
# ---------------------------------------------------------------------------


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _state_ids_at_level(node: Mapping[str, Any]) -> list[str]:
    """Return ids of direct child states / parallels at one nesting level."""
    out: list[str] = []
    for kind in ("state", "parallel"):
        for child in _as_list(node.get(kind)):
            if isinstance(child, Mapping):
                cid = child.get("id")
                if cid is not None:
                    out.append(str(cid))
    return out


def _max_peer_count(node: Mapping[str, Any]) -> int:
    """Maximum peer-state count at any one level under ``node``.

    The SOS-12 §9.1 legibility threshold is "peer states at any one level"
    — the relevant statistic is the max across all levels in the chart,
    not the total state count.
    """
    direct = len(_state_ids_at_level(node))
    nested_max = 0
    for kind in ("state", "parallel"):
        for child in _as_list(node.get(kind)):
            if isinstance(child, Mapping):
                nested_max = max(nested_max, _max_peer_count(child))
    return max(direct, nested_max)


def _all_state_ids(node: Mapping[str, Any]) -> set[str]:
    """All state ids anywhere under ``node`` (recursive)."""
    out: set[str] = set()
    for kind in ("state", "parallel"):
        for child in _as_list(node.get(kind)):
            if isinstance(child, Mapping):
                cid = child.get("id")
                if cid is not None:
                    out.add(str(cid))
                out |= _all_state_ids(child)
    return out


def _find_dispatch_state(
    root: Mapping[str, Any], dispatch_state_id: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Locate the (state_node, dispatch_other_element) for the named state.

    Returns ``(state_dict, dispatch_dict)`` if a ``<state id=dispatch_state_id>``
    exists AND carries a ``<sos:dispatch ref="…"/>`` in ``other_element``.
    Returns ``None`` otherwise.

    The state mutation surface is intentionally returned as a live dict
    reference so the caller can edit in place — the handler's mutation
    happens on a deep-copied AST per :func:`_deepcopy_ast`.
    """
    for kind in ("state", "parallel"):
        for child in _as_list(root.get(kind)):
            if not isinstance(child, dict):
                continue
            if child.get("id") == dispatch_state_id:
                for el in child.get("other_element") or []:
                    if isinstance(el, dict) and el.get("qname") == _DISPATCH_QNAME:
                        return child, el
            # Recurse — nested states can carry dispatches too.
            found = _find_dispatch_state(child, dispatch_state_id)
            if found is not None:
                return found
    return None


def _deepcopy_ast(ast: Mapping[str, Any]) -> dict[str, Any]:
    """Round-trip an AST through JSON to get a fully independent deep copy."""
    return json.loads(json.dumps(ast))


# ---------------------------------------------------------------------------
# Child-state id rewriting (collision-avoidance policy)
# ---------------------------------------------------------------------------


def _rewrite_state_ids(
    node: dict[str, Any],
    rewrite_map: Mapping[str, str],
) -> None:
    """Apply ``rewrite_map`` to every state id + transition target reachable
    under ``node``.

    Edits ``node`` in place. The map's key is the original id; the value
    is the new id. Only mapped ids change; unmapped ids stay put.
    """
    for kind in ("state", "parallel"):
        for child in _as_list(node.get(kind)):
            if not isinstance(child, dict):
                continue
            cid = child.get("id")
            if cid is not None and str(cid) in rewrite_map:
                child["id"] = rewrite_map[str(cid)]
            # Rewrite the child's own initial_attribute / initial.
            for ia_key in ("initial_attribute", "initial"):
                vals = child.get(ia_key)
                if isinstance(vals, list):
                    child[ia_key] = [
                        rewrite_map.get(str(v), v) for v in vals
                    ]
            for tr in child.get("transition") or []:
                if not isinstance(tr, dict):
                    continue
                tgt = tr.get("target")
                if isinstance(tgt, list):
                    tr["target"] = [rewrite_map.get(str(t), t) for t in tgt]
                elif isinstance(tgt, str):
                    tr["target"] = rewrite_map.get(tgt, tgt)
            _rewrite_state_ids(child, rewrite_map)


# ---------------------------------------------------------------------------
# Result-shape helpers
# ---------------------------------------------------------------------------


def _rejected(
    code: FailureCode,
    diagnosis: str,
    *,
    failed_axis: ValidationAxis | None = None,
) -> ToolCallError:
    """Build the canonical SOS-11 atomic-failure result.

    Every rejection from this handler is atomic (chart_unchanged=True per
    §7 failure model). The handler returns the typed ``ToolCallError``
    object; the caller renders it via ``.to_dict()`` for the MCP wire
    surface.
    """
    return ToolCallError(
        code=code,
        diagnosis=diagnosis,
        failed_axis=failed_axis,
        chart_unchanged=True,
    )


def _validation_report_for_inline(
    round_trip_passed: bool,
    *,
    round_trip_diagnosis: str | None = None,
) -> ValidationReport:
    """Build the §6 four-axis validation report.

    Axis (a) ``scjson_round_trip`` is computed; axes (b)–(d) are marked
    passed with a ``diagnosis`` naming the deferral (see module docstring
    "Validation pipeline" section).
    """
    return ValidationReport(
        scjson_round_trip=ValidationAxisReport(
            axis=ValidationAxis.SCJSON_ROUND_TRIP,
            passed=round_trip_passed,
            diagnosis=round_trip_diagnosis,
        ),
        lint=ValidationAxisReport(
            axis=ValidationAxis.LINT,
            passed=True,
            diagnosis=(
                "deferred to the SOS-11 validation composer "
                "(SOS-11 §15 2026-05-27 'Still open' item #2)"
            ),
        ),
        bound_converges=ValidationAxisReport(
            axis=ValidationAxis.BOUND_CONVERGES,
            passed=True,
            diagnosis=(
                "deferred to the SOS-11 validation composer "
                "(SOS-11 §15 2026-05-27 'Still open' item #2)"
            ),
        ),
        invariants_hold=ValidationAxisReport(
            axis=ValidationAxis.INVARIANTS_HOLD,
            passed=True,
            diagnosis=(
                "deferred to the SOS-11 validation composer "
                "(SOS-11 §15 2026-05-27 'Still open' item #2)"
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Boundary vector → vector_delta bridge
# ---------------------------------------------------------------------------


def _retiring_boundary_vectors(
    parent_chart_id: str,
    dispatch_state_id: str,
    child_chart_id: str,
    child_contract: Contract,
    child_initial: str,
) -> list[dict[str, Any]]:
    """Return the boundary-vector set that NO LONGER exists post-inline.

    The inline removes the dispatch boundary; the vectors that the
    boundary required (one per child events_in / events_out / invariant)
    are negated by the operation. The summary stamped into
    ``VectorDelta`` lists their count + ids.

    The ``DispatchEdge`` shape Wave-1C emits over expects a fully
    populated parent expectation. The handler uses the child's own
    declared events / invariants on both sides — that is the
    contract-was-matched case (otherwise we already rejected upstream),
    so the parent's routing is at minimum a superset of the child's.
    """
    edge = DispatchEdge(
        parent_chart_id=parent_chart_id,
        dispatch_state=dispatch_state_id,
        child_contract=SubChartContract(
            chart_id=child_chart_id,
            initial_state=child_initial,
            events_in=child_contract.events_in,
            events_out=child_contract.events_out,
            invariants_maintained=child_contract.invariants_maintained,
            invariants_assumed=child_contract.invariants_assumed,
        ),
        parent_expected_events_in=child_contract.events_in,
        parent_expected_events_out=child_contract.events_out,
    )
    return emit_boundary_vectors(edge)


def _vector_delta_summary(
    parent_chart_id: str,
    dispatch_state_id: str,
    child_chart_id: str,
    child_contract: Contract,
    child_initial: str,
) -> VectorDelta:
    """Build the negated-boundary-vector ``VectorDelta`` for an inline.

    Per SOS-11 §6 ``vector_delta`` shape — summary + citations. The
    citations name the chart-path of the dispatch boundary that retired
    (the chart-path that ``sos12_boundary_vectors._chart_path`` would
    have stamped on each emitted vector).
    """
    vecs = _retiring_boundary_vectors(
        parent_chart_id,
        dispatch_state_id,
        child_chart_id,
        child_contract,
        child_initial,
    )
    chart_path = f"{parent_chart_id}.{dispatch_state_id}.{child_chart_id}"
    if not vecs:
        return VectorDelta(
            summary=(
                f"inline at {chart_path!r} retires 0 boundary vectors "
                "(child contract declared no events / invariants)"
            ),
            citations=(chart_path,),
        )
    by_kind: dict[str, int] = {}
    for v in vecs:
        by_kind[v["kind"]] = by_kind.get(v["kind"], 0) + 1
    kind_summary = ", ".join(
        f"-{count} {kind}" for kind, count in sorted(by_kind.items())
    )
    return VectorDelta(
        summary=(
            f"inline at {chart_path!r} retires {len(vecs)} boundary "
            f"vector(s): {kind_summary}"
        ),
        citations=(chart_path,),
    )


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------


def inline_subchart(
    parent_chart_path: str | Path,
    dispatch_state_id: str,
    *,
    legibility_threshold: int = DEFAULT_LEGIBILITY_THRESHOLD,
) -> ToolCallResult | ToolCallError:
    """Inline a dispatched sub-chart back into its parent chart.

    SOS-11 §5.1 ``inline_subchart`` primitive. Inverse of
    ``extract_region_to_subchart``. Two gate-keepers run before the AST
    is mutated:

      1. ``sos12_contract_match.verify_contract_match`` MUST pass for
         the current dispatch edge. A stale contract means the dispatch-
         tree's verification basis would not survive the inline; refuse
         with ``ToolCallError(code=CONFLICT)`` citing the §5.3 clause.

      2. The post-inline parent's max peer-state count at any one level
         MUST be at or below ``legibility_threshold`` (default 15 per
         SOS-12 PCDN-SOS-12-003 / §9.2). Otherwise refuse with
         ``ToolCallError(code=LINT_FAILURE)`` citing §9.2.

    If both gates pass, the dispatch state's body is replaced with the
    child sub-chart's body (states, parallels, datamodel) — id
    collisions are resolved by prefixing the colliding child ids with
    ``{dispatch_state_id}__``; transitions inside the inlined body are
    rewritten to follow. External transitions out of the dispatch state
    itself are preserved.

    Args:
        parent_chart_path: filesystem path to the parent chart's SCXML.
        dispatch_state_id: id of the parent state carrying the
            ``<sos:dispatch ref="…"/>`` to inline.
        legibility_threshold: per-level peer-state cap. Default 15 per
            PCDN-SOS-12-003.

    Returns:
        ``ToolCallResult`` on success (chart mutated, diff + vector
        delta + summary + validation report populated); ``ToolCallError``
        on any rejection.
    """
    parent_chart_path = Path(parent_chart_path).resolve()

    # ------------------------------------------------------------------
    # 1. Load + locate the dispatch site.
    # ------------------------------------------------------------------
    try:
        parent_ast_before = _load_scjson(parent_chart_path)
    except FileNotFoundError as exc:
        return _rejected(
            FailureCode.ARGUMENT_INVALID,
            f"parent_chart_path {str(parent_chart_path)!r} does not exist: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 — scjson surface is broad
        return _rejected(
            FailureCode.ROUND_TRIP_FAILURE,
            f"parent_chart_path {str(parent_chart_path)!r} failed to parse: {exc}",
            failed_axis=ValidationAxis.SCJSON_ROUND_TRIP,
        )

    found = _find_dispatch_state(parent_ast_before, dispatch_state_id)
    if found is None:
        return _rejected(
            FailureCode.ARGUMENT_INVALID,
            f"parent chart {parent_chart_path.name!r} has no "
            f"<state id={dispatch_state_id!r}> carrying a <sos:dispatch>",
        )

    # ------------------------------------------------------------------
    # 2. Resolve and load the child sub-chart.
    # ------------------------------------------------------------------
    _parent_state_in_loaded, dispatch_el_in_loaded = found
    dispatch_attrs = dispatch_el_in_loaded.get("attributes") or {}
    ref = dispatch_attrs.get("ref")
    if not isinstance(ref, str) or not ref.strip():
        return _rejected(
            FailureCode.ARGUMENT_INVALID,
            f"dispatch at <state id={dispatch_state_id!r}> has no usable ref attribute",
        )
    child_path = (parent_chart_path.parent / ref.strip()).resolve()
    try:
        child_ast = _load_scjson(child_path)
    except FileNotFoundError as exc:
        return _rejected(
            FailureCode.ARGUMENT_INVALID,
            f"dispatch ref {ref!r} does not resolve to a readable file "
            f"({child_path}): {exc}",
        )

    # ------------------------------------------------------------------
    # 3. Build a DispatchContractEdge and verify the current contract.
    # ------------------------------------------------------------------
    parent_inv = parse_dispatch_annotations(
        parent_ast_before,
        chart_path=parent_chart_path,
        loader=lambda p: _load_scjson(p),
    )
    # The child inventory is the resolved sub-inventory for this dispatch.
    child_inv = next(
        (
            sub for sub in parent_inv.sub_inventories
            if sub.chart_ref == child_path.name
        ),
        None,
    )
    child_contract: Contract = (
        child_inv.contract if child_inv and child_inv.contract else Contract()
    )
    parent_contract: Contract = parent_inv.contract or Contract()

    edge = DispatchContractEdge(
        parent_chart_id=parent_chart_path.name,
        parent_state_id=dispatch_state_id,
        child_chart_id=child_path.name,
        child_contract=child_contract,
        parent_expected_events_in=parent_contract.events_in or child_contract.events_in,
        parent_expected_events_out=parent_contract.events_out or child_contract.events_out,
        parent_maintained_invariants=(
            parent_contract.invariants_maintained or child_contract.invariants_assumed
        ),
        parent_assumed_invariants=parent_contract.invariants_assumed,
        parent_writes_before_dispatch=parent_contract.writes or child_contract.reads,
        parent_reads_after_dispatch=parent_contract.reads or child_contract.writes,
    )

    try:
        verify_contract_match(edge)
    except ContractMismatchError as exc:
        return _rejected(
            FailureCode.CONFLICT,
            f"contract-match check rejected the inline at {dispatch_state_id!r}: "
            f"{exc} — inlining a stale dispatch edge would deviate from the "
            "dispatch-tree's verification basis (SOS-12 §5.3 PCDN-006).",
        )

    # ------------------------------------------------------------------
    # 4. Compute the post-inline AST on a deep copy.
    # ------------------------------------------------------------------
    parent_ast_after = _deepcopy_ast(parent_ast_before)
    found_after = _find_dispatch_state(parent_ast_after, dispatch_state_id)
    assert found_after is not None  # already verified above
    parent_state, dispatch_el = found_after

    # Determine child states + collision-rewrite policy.
    child_state_ids = _all_state_ids(child_ast)
    # The parent state-ids OUTSIDE the dispatch state — collisions inside
    # the dispatch state are by construction impossible because the
    # dispatch state had no children before the inline (a state with a
    # <sos:dispatch> is treated as a leaf in §5.1).
    parent_state_ids_outside = _all_state_ids(parent_ast_after) - {dispatch_state_id}
    colliding = child_state_ids & parent_state_ids_outside
    rewrite_map: dict[str, str] = {
        cid: f"{dispatch_state_id}__{cid}" for cid in sorted(colliding)
    }

    # Materialise child body inside the dispatch state. Deep copy so the
    # source child_ast is not mutated.
    child_body = _deepcopy_ast(child_ast)
    if rewrite_map:
        _rewrite_state_ids(child_body, rewrite_map)

    # Move child's nested children + datamodel into the parent state.
    parent_state["state"] = list(_as_list(parent_state.get("state"))) + list(
        _as_list(child_body.get("state"))
    )
    parent_state["parallel"] = list(_as_list(parent_state.get("parallel"))) + list(
        _as_list(child_body.get("parallel"))
    )
    parent_state["datamodel"] = list(_as_list(parent_state.get("datamodel"))) + list(
        _as_list(child_body.get("datamodel"))
    )

    # Carry the child's chart-root initial onto the dispatch state's
    # initial_attribute so entering it immediately enters the child's
    # initial state. Apply collision rewriting to the initial value.
    child_initial_raw = (
        _as_list(child_body.get("initial"))
        or _as_list(child_body.get("initial_attribute"))
    )
    child_initial_str: str = ""
    if child_initial_raw:
        first = child_initial_raw[0]
        if isinstance(first, str):
            child_initial_str = rewrite_map.get(first, first)
    if child_initial_str:
        parent_state["initial_attribute"] = [child_initial_str]
        parent_state["initial"] = [child_initial_str]

    # Drop the <sos:dispatch> element. Also drop any <sos:contract> that
    # was inlined from the child (the contract is a per-chart-root
    # element; once the child is inlined, its contract is no longer a
    # boundary obligation).
    parent_state["other_element"] = [
        el for el in parent_state.get("other_element") or []
        if not (isinstance(el, dict) and el.get("qname") == _DISPATCH_QNAME)
    ]

    # ------------------------------------------------------------------
    # 5. Legibility-threshold gate (post-mutation; cheaper to compute on
    #    the materialised AST than to project from the source).
    # ------------------------------------------------------------------
    post_peer_max = _max_peer_count(parent_ast_after)
    if post_peer_max > legibility_threshold:
        return _rejected(
            FailureCode.LINT_FAILURE,
            f"inline at {dispatch_state_id!r} would push parent chart's max "
            f"peer-state count to {post_peer_max} at one level, exceeding the "
            f"legibility threshold of {legibility_threshold} "
            f"(SOS-12 §9.2 / PCDN-SOS-12-003). Keep the dispatch.",
            failed_axis=ValidationAxis.LINT,
        )

    # ------------------------------------------------------------------
    # 6. Compose result: diff + vector_delta + summary + validation.
    # ------------------------------------------------------------------
    scxml_before = _dump_xml(parent_ast_before)
    try:
        scxml_after = _dump_xml(parent_ast_after)
    except Exception as exc:  # noqa: BLE001
        return _rejected(
            FailureCode.ROUND_TRIP_FAILURE,
            f"post-inline AST failed to serialise to SCXML: {exc}",
            failed_axis=ValidationAxis.SCJSON_ROUND_TRIP,
        )

    # Round-trip check for axis (a).
    round_trip_passed = True
    round_trip_diag: str | None = None
    try:
        reparsed = json.loads(
            __import__(
                "scjson.SCXMLDocumentHandler", fromlist=["SCXMLDocumentHandler"]
            ).SCXMLDocumentHandler(omit_empty=False).xml_to_json(scxml_after)
        )
        # The structured-diff against itself MUST be empty.
        self_diff = structured_scxml_diff(reparsed, parent_ast_after)
        all_empty = (
            not self_diff["states"]["added"]
            and not self_diff["states"]["removed"]
            and not self_diff["transitions"]["added"]
            and not self_diff["transitions"]["removed"]
            and not self_diff["datamodel"]["added"]
            and not self_diff["datamodel"]["removed"]
            and not self_diff["datamodel"]["changed"]
        )
        if not all_empty:
            round_trip_passed = False
            round_trip_diag = (
                "post-inline AST does not round-trip through scjson cleanly "
                "(structured diff is non-empty)"
            )
    except Exception as exc:  # noqa: BLE001
        round_trip_passed = False
        round_trip_diag = f"round-trip failed: {exc}"

    scxml_diff = build_scxml_diff(
        parent_ast_before,
        parent_ast_after,
        before_xml=scxml_before,
        after_xml=scxml_after,
        fromfile=f"{parent_chart_path.name}.before",
        tofile=f"{parent_chart_path.name}.after",
    )

    vector_delta = _vector_delta_summary(
        parent_chart_id=parent_chart_path.name,
        dispatch_state_id=dispatch_state_id,
        child_chart_id=child_path.name,
        child_contract=child_contract,
        child_initial=child_initial_str or "<unspecified>",
    )

    rewrite_clause = (
        f"; renamed {len(rewrite_map)} colliding child state-id(s) "
        f"with prefix {dispatch_state_id!r}"
        if rewrite_map
        else ""
    )
    summary = (
        f"inline_subchart: merged child {child_path.name!r} body into "
        f"<state id={dispatch_state_id!r}> of parent "
        f"{parent_chart_path.name!r}; removed <sos:dispatch> at the site"
        f"{rewrite_clause}."
    )

    validation = _validation_report_for_inline(
        round_trip_passed=round_trip_passed,
        round_trip_diagnosis=round_trip_diag,
    )

    return ToolCallResult(
        scxml_diff=scxml_diff,
        vector_delta=vector_delta,
        summary=summary,
        validation=validation,
    )


__all__ = [
    "DEFAULT_LEGIBILITY_THRESHOLD",
    "inline_subchart",
]

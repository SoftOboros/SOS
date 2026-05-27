"""Tests for ``tools/sos-codegen/sos11_mcp/extract.py`` (Wave-3 J).

Authority: ``docs/concepts/SOS-11-CONCEPTS.md`` §5.1 (primitive
``extract_region_to_subchart``) + §6 (four-tuple result contract) + §7
(failure model, atomicity). Cross-phase peer ratification:
``docs/concepts/SOS-12-CONCEPTS.md`` §5.3 (contract-matching algebra,
PCDN-SOS-12-006 compile-time error) + §7.2 (boundary-vector emission).

Test surface closes SOS-11 §15 Wave-1 "Still open" line item
``extract_region_to_subchart`` (the handler that was registered in
``tool_catalog.py`` but had no executable implementation). Each test
documents which §13 acceptance gate it touches.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# Make ``sos-codegen`` modules importable from the tests/ directory.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import loader  # noqa: E402
from sos11_mcp.contracts import (  # noqa: E402
    FailureCode,
    ToolCallError,
    ToolCallResult,
    ValidationAxis,
)
from sos11_mcp.extract import (  # noqa: E402
    ExtractRegionResult,
    extract_region_to_subchart,
)
from sos11_mcp.tool_catalog import (  # noqa: E402
    TOOL_HANDLERS,
    get_handler,
)
from sos12_annotations import parse_dispatch_annotations  # noqa: E402
from sos12_contract_match import (  # noqa: E402
    ContractMismatchError,
    DispatchContractEdge,
    verify_contract_match,
)


FIXTURE = (
    _TOOLS_DIR / "tests" / "fixtures" / "sos_11" / "parent_for_extract.scxml"
)


# ---------------------------------------------------------------------------
# Helpers — argument templates the tests mutate per-case.
# ---------------------------------------------------------------------------


def _good_args(**overrides) -> dict:
    """Return a kwarg dict that PASSES the contract-match for the fixture.

    The fixture's `handle_request` state has:
      - one transition INTO it (event `request.received` from `idle`)
      - one transition OUT of it (event `request.completed` to `idle`)
      - parent chart datamodel fields {request_body, response_status}
    """
    base = {
        "chart_path": str(FIXTURE),
        "region_state_id": "handle_request",
        "new_subchart_id": "request_handler",
        "events_in": ["request.received"],
        "events_out": ["request.completed"],
        "invariants_maintained": ["INV-RH-1"],
        "invariants_assumed": [],
        "reads": ["request_body"],
        "writes": ["response_status"],
    }
    base.update(overrides)
    return base


def _run_extract(**overrides):
    return extract_region_to_subchart(**_good_args(**overrides))


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_successful_extraction_returns_extract_region_result() -> None:
    """Touches §6 four-tuple result contract + §5.1 primitive semantics."""
    result = _run_extract()

    assert isinstance(result, ExtractRegionResult)
    assert isinstance(result.tool_result, ToolCallResult)
    assert result.tool_result.summary.startswith(
        "extracted region 'handle_request' into sub-chart"
    )


def test_successful_extraction_emits_parent_diff_with_dispatch_state() -> None:
    """The parent's post-extraction chart MUST contain a <sos:dispatch>
    element at the extracted region's id; the region's internal substates
    are gone. Touches §6 ``scxml_diff`` + SOS-12 §5.1 PCDN-001 dispatch shape.
    """
    result = _run_extract()
    assert isinstance(result, ExtractRegionResult)

    assert "<sos:dispatch" in result.parent_xml_after
    assert 'ref="request_handler.scxml"' in result.parent_xml_after
    # The region's internal substates (parsing / responding) are gone.
    assert "parsing" not in result.parent_xml_after
    assert "responding" not in result.parent_xml_after


def test_successful_extraction_produces_subchart_with_contract() -> None:
    """The new sub-chart's SCXML carries a <sos:contract> at root.
    Touches SOS-12 §5.1 PCDN-002/004 contract shape."""
    result = _run_extract()
    assert isinstance(result, ExtractRegionResult)

    sub = result.new_subchart_xml
    assert "<sos:contract" in sub
    assert 'reads="request_body"' in sub
    assert 'writes="response_status"' in sub
    assert "<sos:event>request.received</sos:event>" in sub
    assert "<sos:event>request.completed</sos:event>" in sub
    assert "INV-RH-1" in sub


def test_successful_extraction_emits_three_boundary_vectors() -> None:
    """events_in (1) + events_out (1) + invariants_maintained (1) = 3 boundary
    vectors per SOS-12 §7.2. Touches §6 ``vector_delta`` + INV-S-DISP-5."""
    result = _run_extract()
    assert isinstance(result, ExtractRegionResult)

    assert len(result.boundary_vectors) == 3
    kinds = {v["kind"] for v in result.boundary_vectors}
    assert kinds == {"events_in", "events_out", "invariant_maintained"}
    # vector_delta summary names the per-edge count.
    assert "+3 boundary vectors" in result.tool_result.vector_delta.summary
    # Citations name SOS-12 §7.2 + INV-SOS-B.
    citations = result.tool_result.vector_delta.citations
    assert any("§7.2" in c for c in citations)
    assert any("INV-SOS-B" in c for c in citations)


def test_validation_report_marks_contract_match_passed_others_deferred() -> None:
    """Per the §15 Wave-1 'Still open' framing: the contract-match axis
    (invariants_hold) is the only fully-wired axis at Wave-3 J; the other
    three report ``passed=False`` with a 'deferred' diagnosis."""
    result = _run_extract()
    assert isinstance(result, ExtractRegionResult)

    validation = result.tool_result.validation
    assert validation.invariants_hold.passed is True
    assert "PCDN-SOS-12-006" in (validation.invariants_hold.diagnosis or "")
    for axis in (
        validation.scjson_round_trip,
        validation.lint,
        validation.bound_converges,
    ):
        assert axis.passed is False
        assert "deferred" in (axis.diagnosis or "")


# ---------------------------------------------------------------------------
# Failure paths — contract-mismatch rejections (PCDN-SOS-12-006)
# ---------------------------------------------------------------------------


def test_rejects_extra_event_in_not_routed_by_parent() -> None:
    """The child declares `bogus.event` as events_in but the parent has
    no transition with that event targeting `handle_request`. Touches
    SOS-12 §5.3 clause 1 + PCDN-006."""
    result = _run_extract(events_in=["bogus.event"])

    assert isinstance(result, ToolCallError)
    assert result.code is FailureCode.INVARIANT_VIOLATION
    assert "PCDN-SOS-12-006" in result.diagnosis
    assert "INV-S-DISP-2" in result.diagnosis
    assert "clause=events_in" in result.diagnosis
    assert "bogus.event" in result.diagnosis
    assert result.failed_axis is ValidationAxis.INVARIANTS_HOLD
    assert result.chart_unchanged is True


def test_rejects_extra_event_out_not_observed_by_parent() -> None:
    """The child declares `internal.signal` as events_out but no transition
    inside the region targets a state outside the region with that event.
    Touches SOS-12 §5.3 clause 2 + PCDN-006."""
    result = _run_extract(events_out=["internal.signal"])

    assert isinstance(result, ToolCallError)
    assert result.code is FailureCode.INVARIANT_VIOLATION
    assert "clause=events_out" in result.diagnosis
    assert "internal.signal" in result.diagnosis


def test_rejects_reads_field_not_in_parent_datamodel() -> None:
    """Touches SOS-12 §5.3 clause 5 (reads) + §5.2 four-set algebra."""
    result = _run_extract(reads=["nonexistent_field"])

    assert isinstance(result, ToolCallError)
    assert result.code is FailureCode.INVARIANT_VIOLATION
    assert "clause=reads" in result.diagnosis
    assert "nonexistent_field" in result.diagnosis


def test_rejects_writes_field_not_in_parent_datamodel() -> None:
    """Touches SOS-12 §5.3 clause 6 (writes) — the outbound-data
    counterpart of the reads check."""
    result = _run_extract(writes=["nonexistent_field"])

    assert isinstance(result, ToolCallError)
    assert result.code is FailureCode.INVARIANT_VIOLATION
    assert "clause=writes" in result.diagnosis


# ---------------------------------------------------------------------------
# Argument-validation failures (not contract-mismatch — §7 ArgumentInvalid)
# ---------------------------------------------------------------------------


def test_rejects_missing_chart_path() -> None:
    """Touches §7 ArgumentInvalid failure code."""
    result = extract_region_to_subchart(
        chart_path="/does/not/exist.scxml",
        region_state_id="handle_request",
        new_subchart_id="x",
        events_in=[],
        events_out=[],
        invariants_maintained=[],
        invariants_assumed=[],
        reads=[],
        writes=[],
    )
    assert isinstance(result, ToolCallError)
    assert result.code is FailureCode.ARGUMENT_INVALID
    assert "chart_path not found" in result.diagnosis


def test_rejects_unknown_region_state_id() -> None:
    """Touches §7 ArgumentInvalid + INV-SOS-H chart-vocabulary."""
    result = _run_extract(region_state_id="no_such_state")
    assert isinstance(result, ToolCallError)
    assert result.code is FailureCode.ARGUMENT_INVALID
    assert "no_such_state" in result.diagnosis


# ---------------------------------------------------------------------------
# Round-trip + SOS-12 annotation parser interop
# ---------------------------------------------------------------------------


def test_outputs_round_trip_through_scjson() -> None:
    """Both the new sub-chart SCXML and the post-extraction parent SCXML
    MUST round-trip through scjson cleanly. Touches §6 axis
    ``scjson_round_trip`` (not yet auto-asserted by the validation
    composer, but exercised end-to-end here)."""
    result = _run_extract()
    assert isinstance(result, ExtractRegionResult)

    with tempfile.TemporaryDirectory() as td:
        sub_path = Path(td) / "request_handler.scxml"
        par_path = Path(td) / "parent.scxml"
        sub_path.write_text(result.new_subchart_xml, encoding="utf-8")
        par_path.write_text(result.parent_xml_after, encoding="utf-8")

        sub_ast = loader.load_chart(sub_path)
        par_ast = loader.load_chart(par_path)

        assert sub_ast.raw_scjson is not None
        assert par_ast.raw_scjson is not None


def test_post_extraction_dispatch_passes_sos12_contract_match() -> None:
    """The dispatch edge produced by extraction MUST itself pass the
    contract-match check — this is the round-trip property the
    extraction handler promises. Touches SOS-12 §5.3 INV-S-DISP-2."""
    result = _run_extract()
    assert isinstance(result, ExtractRegionResult)

    with tempfile.TemporaryDirectory() as td:
        sub_path = Path(td) / "request_handler.scxml"
        par_path = Path(td) / "parent.scxml"
        sub_path.write_text(result.new_subchart_xml, encoding="utf-8")
        par_path.write_text(result.parent_xml_after, encoding="utf-8")

        sub_ast = loader.load_chart(sub_path)
        par_ast = loader.load_chart(par_path)
        par_inv = parse_dispatch_annotations(
            par_ast.raw_scjson,
            chart_path=par_path,
            loader=lambda p: loader.load_chart(p).raw_scjson,
        )
        # The parser MUST find exactly one dispatch (the one we inserted).
        assert len(par_inv.dispatches) == 1
        assert par_inv.dispatches[0].ref == "request_handler.scxml"

        # And the sub-chart's contract MUST parse cleanly.
        sub_inv = parse_dispatch_annotations(sub_ast.raw_scjson, chart_path=sub_path)
        assert sub_inv.contract is not None
        assert sub_inv.contract.events_in == ("request.received",)
        assert sub_inv.contract.events_out == ("request.completed",)
        assert sub_inv.contract.reads == ("request_body",)
        assert sub_inv.contract.writes == ("response_status",)
        assert sub_inv.contract.invariants_maintained == ("INV-RH-1",)


def test_extracted_state_becomes_leaf_dispatching_state_no_orphan_transitions() -> None:
    """Per the §5.1 primitive semantics: the extracted region collapses
    into a SINGLE state that dispatches to the sub-chart. The state MUST
    have no child <state> elements and no orphan transitions; its
    boundary transitions (the parent-side surface) MUST remain."""
    result = _run_extract()
    assert isinstance(result, ExtractRegionResult)

    with tempfile.TemporaryDirectory() as td:
        par_path = Path(td) / "parent.scxml"
        par_path.write_text(result.parent_xml_after, encoding="utf-8")
        par_ast = loader.load_chart(par_path)

        # Locate the dispatching state in the AST.
        handle = None
        for st in par_ast.raw_scjson.get("state", []) or []:
            if st.get("id") == "handle_request":
                handle = st
                break
        assert handle is not None

        # No child states (the region body is gone).
        assert not handle.get("state")
        assert not handle.get("parallel")
        assert not handle.get("datamodel")

        # Outbound transition to `idle` preserved (parent's boundary surface).
        transitions = handle.get("transition") or []
        events = [t.get("event") for t in transitions]
        assert "request.completed" in events


# ---------------------------------------------------------------------------
# Tool-catalog wiring (Wave-3 J registration)
# ---------------------------------------------------------------------------


def test_tool_catalog_resolves_extract_region_to_subchart_handler() -> None:
    """The Wave-3 J registration MUST make the handler resolvable via the
    catalog's ``get_handler`` lookup. Touches §10 (the registry IS the
    permission-gated dispatch surface) + the SOS-11 §15 Wave-3 J entry."""
    handler = get_handler("extract_region_to_subchart")
    assert callable(handler)
    # And the handler IS our implementation.
    assert handler is extract_region_to_subchart
    # The registry now carries the entry (lazy-loaded on first lookup).
    assert "extract_region_to_subchart" in TOOL_HANDLERS


def test_tool_catalog_raises_for_still_unimplemented_tool() -> None:
    """A higher-intent tool (`factor_dispatch`) is registered in the catalog
    (SOS-11 §5.2) but has no handler binding; lookup MUST raise a clearly-
    cited KeyError. Retargeted from `inline_subchart` post-Wave-4U1 since
    inline now resolves through HANDLER_BINDINGS."""
    with pytest.raises(KeyError) as exc:
        get_handler("factor_dispatch")
    assert "Still open" in str(exc.value) or "no executable handler" in str(exc.value)


# ---------------------------------------------------------------------------
# Defensive: contract-match success implies emit_boundary_vectors works
# ---------------------------------------------------------------------------


def test_extraction_with_no_invariants_emits_two_boundary_vectors() -> None:
    """events_in (1) + events_out (1) = 2 boundary vectors. Touches the
    constant-size property of SOS-12 §7.2 / INV-SOS-F at the extraction
    surface."""
    result = _run_extract(invariants_maintained=[], invariants_assumed=[])
    assert isinstance(result, ExtractRegionResult)
    assert len(result.boundary_vectors) == 2
    assert "+2 boundary vectors" in result.tool_result.vector_delta.summary


def test_failure_does_not_mutate_parent_chart_on_disk() -> None:
    """§7 atomicity: a contract-match failure MUST leave the parent
    chart on disk unchanged. The handler does NOT write to disk in any
    code path (file IO is the caller's responsibility), but we assert
    the fixture's bytes are still identical after a rejected call.
    """
    before = FIXTURE.read_bytes()
    result = _run_extract(events_in=["bogus.event"])
    assert isinstance(result, ToolCallError)
    after = FIXTURE.read_bytes()
    assert before == after

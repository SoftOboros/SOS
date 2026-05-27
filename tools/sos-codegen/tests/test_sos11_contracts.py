"""Tests for SOS-11 MCP result and error contracts."""

from __future__ import annotations

import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

# Make `sos-codegen` modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos11_mcp.contracts import (  # noqa: E402
    AxisStatus,
    FailureCode,
    ScxmlDiff,
    ToolCallError,
    ToolCallResult,
    ValidationAxis,
    ValidationAxisReport,
    ValidationReport,
    VectorDelta,
)


def test_failure_code_values_match_sos11_section_7() -> None:
    assert [code.value for code in FailureCode] == [
        "InvariantViolation",
        "LintFailure",
        "BoundExceeded",
        "RoundTripFailure",
        "ArgumentInvalid",
        "AmbiguousReference",
        "Conflict",
        "PermissionDenied",
    ]

    with pytest.raises(AttributeError):
        FailureCode.CONFLICT.value = "Other"  # type: ignore[misc]


def test_validation_axis_values_match_sos11_section_6() -> None:
    assert [axis.value for axis in ValidationAxis] == [
        "scjson_round_trip",
        "lint",
        "bound_converges",
        "invariants_hold",
    ]


def test_tool_call_result_serializes_exact_top_level_fields() -> None:
    result = ToolCallResult(
        scxml_diff=ScxmlDiff(
            ast_diff={"ops": [{"op": "add_state", "id": "retrying"}]},
            rendered_unified_diff="--- before.scxml\n+++ after.scxml\n",
        ),
        vector_delta=VectorDelta(
            summary="+4 traces enter `retrying`",
            citations=("state:retrying", "transition:connecting->retrying"),
            full_delta_call_id="call-123",
        ),
        summary="added state `retrying` to subchart `auth.connecting`",
        validation=ValidationReport.all_passed(),
    )

    payload = result.to_dict()

    assert list(payload) == ["scxml_diff", "vector_delta", "summary", "validation"]
    assert payload["scxml_diff"] == {
        "ast_diff": {"ops": [{"op": "add_state", "id": "retrying"}]},
        "rendered_unified_diff": "--- before.scxml\n+++ after.scxml\n",
    }
    assert payload["vector_delta"] == {
        "summary": "+4 traces enter `retrying`",
        "citations": ["state:retrying", "transition:connecting->retrying"],
        "full_delta_call_id": "call-123",
    }


def test_all_validation_pass_behavior() -> None:
    validation = ValidationReport.all_passed()

    assert validation.passed is True
    assert validation.failed_axes() == ()
    # PCDN-SOS-11-010 (ratified 2026-05-27) adds a ``status`` field to
    # every axis-report dict; the default value is ``"evaluated"`` so
    # legacy ``ValidationReport.all_passed()`` construction sites keep
    # claiming substantive evaluation (which IS what the helper means).
    assert validation.to_dict() == {
        "scjson_round_trip": {
            "axis": "scjson_round_trip",
            "passed": True,
            "status": "evaluated",
        },
        "lint": {"axis": "lint", "passed": True, "status": "evaluated"},
        "bound_converges": {
            "axis": "bound_converges",
            "passed": True,
            "status": "evaluated",
        },
        "invariants_hold": {
            "axis": "invariants_hold",
            "passed": True,
            "status": "evaluated",
        },
    }


def test_failing_axis_reporting_and_error_serialization() -> None:
    validation = ValidationReport(
        scjson_round_trip=ValidationAxisReport(
            axis=ValidationAxis.SCJSON_ROUND_TRIP,
            passed=True,
        ),
        lint=ValidationAxisReport(
            axis=ValidationAxis.LINT,
            passed=False,
            diagnosis="Transition `T42` fails lint rule `event-known`.",
        ),
        bound_converges=ValidationAxisReport(
            axis=ValidationAxis.BOUND_CONVERGES,
            passed=True,
        ),
        invariants_hold=ValidationAxisReport(
            axis=ValidationAxis.INVARIANTS_HOLD,
            passed=True,
        ),
    )

    error = ToolCallError(
        code=FailureCode.LINT_FAILURE,
        diagnosis="Transition `T42` fails lint rule `event-known`.",
        failed_axis=validation.failed_axes()[0],
    )

    assert validation.passed is False
    assert validation.failed_axes() == (ValidationAxis.LINT,)
    assert error.to_dict() == {
        "code": "LintFailure",
        "diagnosis": "Transition `T42` fails lint rule `event-known`.",
        "failed_axis": "lint",
        "chart_unchanged": True,
    }


def test_axis_status_values_match_pcdn_sos_11_010() -> None:
    """PCDN-SOS-11-010 (ratified 2026-05-27) freezes a three-value
    enum: ``EVALUATED`` / ``DEFERRED`` / ``NOT_REQUESTED``. Standards-
    Action registration policy — a fourth value requires a §15
    amendment to SOS-11."""
    assert [s.value for s in AxisStatus] == [
        "evaluated",
        "deferred",
        "not_requested",
    ]


def test_validation_axis_report_default_status_is_evaluated() -> None:
    """Backwards-compat: construction sites that do NOT name ``status``
    default to ``AxisStatus.EVALUATED`` so legacy callers stay
    substantive."""
    rep = ValidationAxisReport(
        axis=ValidationAxis.SCJSON_ROUND_TRIP,
        passed=True,
    )
    assert rep.status == AxisStatus.EVALUATED


def test_validation_axis_report_to_dict_carries_status() -> None:
    """PCDN-SOS-11-010 result-contract amendment: ``to_dict()`` MUST
    include the ``status`` field for every axis report."""
    deferred = ValidationAxisReport(
        axis=ValidationAxis.LINT,
        passed=True,
        diagnosis="deferred: SOS-01 lint runner not yet wired",
        status=AxisStatus.DEFERRED,
    )
    not_req = ValidationAxisReport(
        axis=ValidationAxis.BOUND_CONVERGES,
        passed=True,
        diagnosis="not requested",
        status=AxisStatus.NOT_REQUESTED,
    )

    assert deferred.to_dict() == {
        "axis": "lint",
        "passed": True,
        "status": "deferred",
        "diagnosis": "deferred: SOS-01 lint runner not yet wired",
    }
    assert not_req.to_dict() == {
        "axis": "bound_converges",
        "passed": True,
        "status": "not_requested",
        "diagnosis": "not requested",
    }


def test_tool_call_error_enforces_chart_unchanged() -> None:
    with pytest.raises(ValueError, match="chart_unchanged must be true"):
        ToolCallError(
            code=FailureCode.CONFLICT,
            diagnosis="Chart HEAD moved between read and write.",
            chart_unchanged=False,
        )

    error = ToolCallError(
        code=FailureCode.CONFLICT,
        diagnosis="Chart HEAD moved between read and write.",
    )

    with pytest.raises(FrozenInstanceError):
        error.chart_unchanged = False  # type: ignore[misc]

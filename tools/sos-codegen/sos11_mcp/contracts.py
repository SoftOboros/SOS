"""SOS-11 MCP tool-call result and error contracts.

The chart-edit handlers are intentionally outside this module. These types
only model the frozen SOS-11 result tuple and atomic failure shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


JsonObject = Mapping[str, Any]


class FailureCode(str, Enum):
    """Frozen SOS-11 failure-code vocabulary."""

    INVARIANT_VIOLATION = "InvariantViolation"
    LINT_FAILURE = "LintFailure"
    BOUND_EXCEEDED = "BoundExceeded"
    ROUND_TRIP_FAILURE = "RoundTripFailure"
    ARGUMENT_INVALID = "ArgumentInvalid"
    AMBIGUOUS_REFERENCE = "AmbiguousReference"
    CONFLICT = "Conflict"
    PERMISSION_DENIED = "PermissionDenied"


class ValidationAxis(str, Enum):
    """Frozen SOS-11 validation axes."""

    SCJSON_ROUND_TRIP = "scjson_round_trip"
    LINT = "lint"
    BOUND_CONVERGES = "bound_converges"
    INVARIANTS_HOLD = "invariants_hold"


class AxisStatus(str, Enum):
    """Frozen SOS-11 §6 axis-evaluation tristate.

    Disambiguates the meaning of ``ValidationAxisReport.passed``:

    - ``EVALUATED`` — the axis's substrate ran end-to-end; ``passed`` is
      substantive (True means the substrate concluded the axis holds;
      False means the substrate concluded it does not).
    - ``DEFERRED`` — the substrate for this axis is not yet wired into
      the composer / handler. ``passed`` is by convention True so the
      report shape doesn't force atomic-rollback on unwired substrates,
      but the value is **non-substantive**; the ``diagnosis`` field
      cites the not-yet-wired module.
    - ``NOT_REQUESTED`` — the caller's ``axes=`` argument excluded this
      axis. ``passed`` is by convention True for the same reason as
      DEFERRED, but again non-substantive; ``diagnosis`` reads
      ``"not requested"``.

    Callers that want "axes that actually failed substantively" filter
    with ``[r for r in report.axis_reports() if r.status ==
    AxisStatus.EVALUATED and not r.passed]``. The default value at
    construction is :attr:`EVALUATED` so existing call sites
    constructing ``ValidationAxisReport(axis=..., passed=...)`` without
    naming ``status`` continue to model substantive evaluation, which
    matches the historical behaviour before this enum landed.

    Registration policy: **Standards Action** — adding a fourth status
    value requires a §15 amendment to SOS-11 + a walkthrough. The three
    values mirror SOS-11 §6's three honest-partial reporting modes
    (substantive evaluation, deferred substrate, caller opt-out).
    """

    EVALUATED = "evaluated"
    DEFERRED = "deferred"
    NOT_REQUESTED = "not_requested"


@dataclass(frozen=True)
class ScxmlDiff:
    """Canonical SCXML diff shape for SOS-11 tool-call results."""

    ast_diff: JsonObject
    rendered_unified_diff: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ast_diff": dict(self.ast_diff)}
        if self.rendered_unified_diff is not None:
            payload["rendered_unified_diff"] = self.rendered_unified_diff
        return payload


@dataclass(frozen=True)
class VectorDelta:
    """Embedded bounded-vector delta summary plus optional full-delta handle."""

    summary: str
    citations: tuple[str, ...] = ()
    full_delta_call_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "summary": self.summary,
            "citations": list(self.citations),
        }
        if self.full_delta_call_id is not None:
            payload["full_delta_call_id"] = self.full_delta_call_id
        return payload


@dataclass(frozen=True)
class ValidationAxisReport:
    """Pass/fail status for one SOS-11 validation axis.

    ``status`` (:class:`AxisStatus`, default :attr:`AxisStatus.EVALUATED`)
    disambiguates whether ``passed`` is substantive. The field defaults
    to ``EVALUATED`` so legacy construction sites that pre-date the
    PCDN-SOS-11-010 ratification keep their existing semantics — a
    construction site that says ``passed=True`` without naming
    ``status`` is still claiming the substrate ran. New construction
    sites that wrap a deferred substrate or a caller-skipped axis MUST
    name :attr:`AxisStatus.DEFERRED` or
    :attr:`AxisStatus.NOT_REQUESTED` respectively so downstream filters
    can tell substantive failures from non-substantive ones.
    """

    axis: ValidationAxis
    passed: bool
    diagnosis: str | None = None
    status: AxisStatus = AxisStatus.EVALUATED

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "axis": self.axis.value,
            "passed": self.passed,
            "status": self.status.value,
        }
        if self.diagnosis is not None:
            payload["diagnosis"] = self.diagnosis
        return payload


@dataclass(frozen=True)
class ValidationReport:
    """Four-axis SOS-11 validation report."""

    scjson_round_trip: ValidationAxisReport
    lint: ValidationAxisReport
    bound_converges: ValidationAxisReport
    invariants_hold: ValidationAxisReport

    def __post_init__(self) -> None:
        expected_axes = {
            "scjson_round_trip": ValidationAxis.SCJSON_ROUND_TRIP,
            "lint": ValidationAxis.LINT,
            "bound_converges": ValidationAxis.BOUND_CONVERGES,
            "invariants_hold": ValidationAxis.INVARIANTS_HOLD,
        }
        for field_name, expected_axis in expected_axes.items():
            actual_axis = getattr(self, field_name).axis
            if actual_axis != expected_axis:
                raise ValueError(
                    f"{field_name} report must use axis {expected_axis.value}"
                )

    @classmethod
    def all_passed(cls) -> "ValidationReport":
        return cls(
            scjson_round_trip=ValidationAxisReport(
                axis=ValidationAxis.SCJSON_ROUND_TRIP,
                passed=True,
            ),
            lint=ValidationAxisReport(axis=ValidationAxis.LINT, passed=True),
            bound_converges=ValidationAxisReport(
                axis=ValidationAxis.BOUND_CONVERGES,
                passed=True,
            ),
            invariants_hold=ValidationAxisReport(
                axis=ValidationAxis.INVARIANTS_HOLD,
                passed=True,
            ),
        )

    @property
    def passed(self) -> bool:
        return all(axis_report.passed for axis_report in self.axis_reports())

    def axis_reports(self) -> tuple[ValidationAxisReport, ...]:
        return (
            self.scjson_round_trip,
            self.lint,
            self.bound_converges,
            self.invariants_hold,
        )

    def failed_axes(self) -> tuple[ValidationAxis, ...]:
        return tuple(
            axis_report.axis
            for axis_report in self.axis_reports()
            if not axis_report.passed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scjson_round_trip": self.scjson_round_trip.to_dict(),
            "lint": self.lint.to_dict(),
            "bound_converges": self.bound_converges.to_dict(),
            "invariants_hold": self.invariants_hold.to_dict(),
        }


@dataclass(frozen=True)
class ToolCallResult:
    """Successful SOS-11 MCP tool-call result."""

    scxml_diff: ScxmlDiff
    vector_delta: VectorDelta
    summary: str
    validation: ValidationReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "scxml_diff": self.scxml_diff.to_dict(),
            "vector_delta": self.vector_delta.to_dict(),
            "summary": self.summary,
            "validation": self.validation.to_dict(),
        }


@dataclass(frozen=True)
class ToolCallError:
    """Atomic SOS-11 MCP tool-call failure result."""

    code: FailureCode
    diagnosis: str
    failed_axis: ValidationAxis | None = None
    chart_unchanged: bool = True

    def __post_init__(self) -> None:
        if self.chart_unchanged is not True:
            raise ValueError("SOS-11 failures are atomic; chart_unchanged must be true")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "diagnosis": self.diagnosis,
            "failed_axis": self.failed_axis.value if self.failed_axis else None,
            "chart_unchanged": True,
        }


__all__ = [
    "AxisStatus",
    "FailureCode",
    "JsonObject",
    "ScxmlDiff",
    "ToolCallError",
    "ToolCallResult",
    "ValidationAxis",
    "ValidationAxisReport",
    "ValidationReport",
    "VectorDelta",
]

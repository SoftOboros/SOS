"""Tests for ``tools/sos-codegen/sos11_mcp/validation.py`` (Wave-4 U2).

Authority: ``docs/concepts/SOS-11-CONCEPTS.md`` §6 (four-axis result-
contract surface) + §7 (failure model — composer never raises) + §15
Wave-1 "Still open" item #2 (this composer's reason for existing).

The composer is the gate-keeper for SOS-11 handler results. These tests
exercise each of the four axes in isolation, the composer's
honest-partial reporting for the deferred SCXML-LINT-CH-{1,2,3} family,
the axis-selection keyword, and the per-axis failure-to-diagnosis
mapping. The fixtures are reused from ``sos_11/`` (extract/inline
parent and child) and ``sos_12/`` (deep_chain_overflow, parent_two_level,
parent_for_extract is single-chart family).
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

from sos11_mcp.contracts import (  # noqa: E402
    ValidationAxis,
    ValidationReport,
)
from sos11_mcp.validation import (  # noqa: E402
    ALL_AXES,
    DEFAULT_LEGIBILITY_THRESHOLD,
    DEFAULT_MAX_DEPTH,
    validate_chart,
)


# ---------------------------------------------------------------------------
# Fixture locations — reused from sibling SOS-11 / SOS-12 phases.
# ---------------------------------------------------------------------------

FIXTURES = _TOOLS_DIR / "tests" / "fixtures"
CLEAN_CHART = FIXTURES / "sos_11" / "parent_for_extract.scxml"
CONTRACT_MISMATCH_CHART = FIXTURES / "sos_11" / "parent_for_inline.scxml"
DEPTH_OVERFLOW_CHART = FIXTURES / "sos_12" / "deep_chain_overflow" / "level_0.scxml"
TWO_LEVEL_CLEAN_CHART = FIXTURES / "sos_12" / "parent_two_level.scxml"


# ---------------------------------------------------------------------------
# §6 axis (a) — scjson_round_trip
# ---------------------------------------------------------------------------


def test_clean_chart_all_four_axes_pass() -> None:
    """Touches §6 four-axis contract; the canonical happy path.

    parent_for_extract has no <sos:dispatch> annotations, so axes (c) and
    (d) pass trivially (singleton chart family). Round-trip and lint
    both pass against the well-formed fixture.
    """
    report = validate_chart(CLEAN_CHART)

    assert isinstance(report, ValidationReport)
    assert report.passed, f"failed axes: {report.failed_axes()}"
    for axis_report in report.axis_reports():
        assert axis_report.passed, (
            f"{axis_report.axis.value} unexpectedly failed: "
            f"{axis_report.diagnosis}"
        )


def test_round_trip_axis_fails_on_unparseable_scxml() -> None:
    """Touches §6 axis (a). A payload that scjson cannot parse as SCXML
    cannot round-trip; the composer surfaces the parser failure as
    passed=False without raising. The handler tolerates many shapes of
    'odd' XML (treating them as foreign elements), but a payload that
    cannot bind to the SCXML root class raises ParserError — which is
    what the composer must catch and convert to an axis report."""
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.scxml"
        bad.write_text("not xml at all, just some text", encoding="utf-8")
        report = validate_chart(bad, axes=(ValidationAxis.SCJSON_ROUND_TRIP,))

    assert not report.scjson_round_trip.passed
    assert report.scjson_round_trip.diagnosis is not None
    # The diagnosis names the chart so the caller knows which file faulted.
    assert "bad.scxml" in report.scjson_round_trip.diagnosis


# ---------------------------------------------------------------------------
# §6 axis (b) — lint (SCXML-LINT-DISP-{1,2}; CH-{1,2,3} deferred)
# ---------------------------------------------------------------------------


def test_lint_axis_succeeds_with_disp_rules_and_names_deferred_ch_rules() -> None:
    """Touches §6 axis (b) + the honest-partial reporting precedent.

    A clean chart passes both DISP rules; the composer marks the axis as
    ``passed=True`` and names the deferred CH-{1,2,3} runner explicitly
    in the diagnosis so a downstream caller knows that not every
    SOS-01-reserved rule was actually evaluated.
    """
    report = validate_chart(CLEAN_CHART, axes=(ValidationAxis.LINT,))

    assert report.lint.passed
    assert report.lint.diagnosis is not None
    # The honest-partial framing names BOTH the wired and the deferred
    # rule families so callers can read off the coverage from the diagnosis.
    assert "SCXML-LINT-DISP" in report.lint.diagnosis
    assert "deferred" in report.lint.diagnosis
    assert "SOS-01-CH-runner" in report.lint.diagnosis


def test_lint_axis_fails_on_legibility_threshold_breach() -> None:
    """Touches §6 axis (b) + SOS-12 §9.1 / PCDN-003.

    A synthetic chart with 17 peer states at one level breaches the
    default legibility threshold (15). The lint axis surfaces the
    SCXML-LINT-DISP-2 diagnostic; the composer reports passed=False
    with the rule id + location cited.
    """
    peers = "\n".join(
        f'  <state id="s{i}"/>' for i in range(17)
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<scxml xmlns="http://www.w3.org/2005/07/scxml"\n'
        '       version="1.0" datamodel="ecmascript" initial="s0">\n'
        f'{peers}\n'
        '</scxml>\n'
    )
    with tempfile.TemporaryDirectory() as tmp:
        chart = Path(tmp) / "many_peers.scxml"
        chart.write_text(body, encoding="utf-8")
        report = validate_chart(chart, axes=(ValidationAxis.LINT,))

    assert not report.lint.passed
    assert report.lint.diagnosis is not None
    assert "SCXML-LINT-DISP-2" in report.lint.diagnosis


def test_lint_axis_legibility_threshold_overridable_per_call() -> None:
    """Touches §6 axis (b) override surface.

    Setting ``legibility_threshold=20`` lets the same 17-peer chart pass
    — projects MAY tighten or loosen per chart-family (SOS-12 §9.1 /
    PCDN-003 ratification mirrors this in the lint substrate).
    """
    peers = "\n".join(
        f'  <state id="s{i}"/>' for i in range(17)
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<scxml xmlns="http://www.w3.org/2005/07/scxml"\n'
        '       version="1.0" datamodel="ecmascript" initial="s0">\n'
        f'{peers}\n'
        '</scxml>\n'
    )
    with tempfile.TemporaryDirectory() as tmp:
        chart = Path(tmp) / "many_peers.scxml"
        chart.write_text(body, encoding="utf-8")
        report = validate_chart(
            chart,
            axes=(ValidationAxis.LINT,),
            legibility_threshold=20,
        )

    assert report.lint.passed, (
        f"lint axis should pass with legibility_threshold=20; got "
        f"{report.lint.diagnosis}"
    )


# ---------------------------------------------------------------------------
# §6 axis (c) — bound_converges
# ---------------------------------------------------------------------------


def test_bound_converges_passes_on_single_chart_family() -> None:
    """Touches §6 axis (c). A chart with no <sos:dispatch> trivially
    converges — the per-layer bound IS the composed bound."""
    report = validate_chart(
        CLEAN_CHART, axes=(ValidationAxis.BOUND_CONVERGES,),
    )

    assert report.bound_converges.passed
    assert report.bound_converges.diagnosis is not None
    assert "composed_bound=" in report.bound_converges.diagnosis


def test_bound_converges_passes_on_two_level_dispatch_tree() -> None:
    """Touches §6 axis (c) + SOS-12 §6.3 sequential composition.

    parent_two_level dispatches into middle_layer which dispatches into
    child_leaf. The composer walks the inventory, builds BoundInputs
    keyed off the three chart_refs, and confirms compose_bound returns
    without raising.
    """
    report = validate_chart(
        TWO_LEVEL_CLEAN_CHART, axes=(ValidationAxis.BOUND_CONVERGES,),
    )

    assert report.bound_converges.passed
    assert report.bound_converges.diagnosis is not None
    assert "edges=" in report.bound_converges.diagnosis


def test_bound_converges_fails_on_depth_overflow() -> None:
    """Touches §6 axis (c) + SOS-12 §6.5 / PCDN-005 depth cap.

    deep_chain_overflow is a 10-level dispatch chain (level_0 →
    level_9). Default max_depth=8 means the parser refuses past the
    level_8 → level_9 boundary; the composer surfaces that as a bound-
    convergence failure with the offending parent_state cited.
    """
    report = validate_chart(
        DEPTH_OVERFLOW_CHART, axes=(ValidationAxis.BOUND_CONVERGES,),
    )

    assert not report.bound_converges.passed
    assert report.bound_converges.diagnosis is not None
    # §6.5 is the cited cap; the parent_state at which the cap fires is
    # 's' (the dispatching state at every level of the chain).
    assert (
        "§6.5" in report.bound_converges.diagnosis
        or "depth" in report.bound_converges.diagnosis
    )


# ---------------------------------------------------------------------------
# §6 axis (d) — invariants_hold
# ---------------------------------------------------------------------------


def test_invariants_hold_passes_on_chart_with_no_dispatches() -> None:
    """Touches §6 axis (d). No dispatches means no contracts to mismatch."""
    report = validate_chart(
        CLEAN_CHART, axes=(ValidationAxis.INVARIANTS_HOLD,),
    )

    assert report.invariants_hold.passed
    assert report.invariants_hold.diagnosis is not None
    assert "contract-match" in report.invariants_hold.diagnosis


def test_invariants_hold_fails_on_contract_mismatch() -> None:
    """Touches §6 axis (d) + SOS-12 §5.3 contract-match algebra.

    parent_for_inline has a <sos:dispatch> into child_for_inline.scxml.
    The parent has no chart-level <sos:contract>, so the simple_edge_
    provider derives empty parent expectations; the child declares
    events_in=(tcp.bytes_received,) which the parent does NOT route.
    Result: the events_in clause fires; the composer reports
    passed=False with PCDN-006 + INV-S-DISP-2 cited.
    """
    report = validate_chart(
        CONTRACT_MISMATCH_CHART,
        axes=(ValidationAxis.INVARIANTS_HOLD,),
    )

    assert not report.invariants_hold.passed
    assert report.invariants_hold.diagnosis is not None
    assert "PCDN-SOS-12-006" in report.invariants_hold.diagnosis
    assert "INV-S-DISP-2" in report.invariants_hold.diagnosis
    assert "clause=" in report.invariants_hold.diagnosis


# ---------------------------------------------------------------------------
# Composer-level behaviour
# ---------------------------------------------------------------------------


def test_unrequested_axes_pass_with_not_requested_diagnosis() -> None:
    """Touches the axis-selection keyword.

    When the caller asks for only a subset, the other axes return
    passed=True with diagnosis='not requested' — so the
    :class:`ValidationReport` shape always has all four fields populated
    and a caller iterating axis_reports never sees a missing axis.
    """
    report = validate_chart(
        CLEAN_CHART, axes=(ValidationAxis.SCJSON_ROUND_TRIP,),
    )

    assert report.scjson_round_trip.passed
    # The round-trip diagnosis is None for a substantive pass.
    assert report.scjson_round_trip.diagnosis is None
    # The other three are all marked not requested.
    for unselected in (
        report.lint,
        report.bound_converges,
        report.invariants_hold,
    ):
        assert unselected.passed
        assert unselected.diagnosis == "not requested"


def test_composer_never_raises_on_missing_chart() -> None:
    """Touches §7 atomicity. The composer NEVER raises — even for a
    missing chart file. Every axis reports passed=False with a 'chart
    not found' diagnosis (or substrate-specific equivalent).
    """
    missing = Path("/tmp/sos-w4u2-this-file-does-not-exist.scxml")
    if missing.exists():
        missing.unlink()  # safety; should never exist in CI

    report = validate_chart(missing)

    # Composer must not raise; the report's four axes all fail because
    # each axis tries to open the file.
    assert not report.passed
    failed = report.failed_axes()
    assert ValidationAxis.SCJSON_ROUND_TRIP in failed
    assert ValidationAxis.LINT in failed
    assert ValidationAxis.BOUND_CONVERGES in failed
    assert ValidationAxis.INVARIANTS_HOLD in failed


def test_composer_returns_validation_report_with_all_four_fields() -> None:
    """Touches §6 four-tuple shape. The composer ALWAYS returns a
    :class:`ValidationReport` whose four named fields each carry an
    :class:`ValidationAxisReport` for the matching axis — never a None,
    never a substitute type.
    """
    report = validate_chart(CLEAN_CHART)

    assert report.scjson_round_trip.axis == ValidationAxis.SCJSON_ROUND_TRIP
    assert report.lint.axis == ValidationAxis.LINT
    assert report.bound_converges.axis == ValidationAxis.BOUND_CONVERGES
    assert report.invariants_hold.axis == ValidationAxis.INVARIANTS_HOLD
    assert len(report.axis_reports()) == 4


def test_all_axes_constant_covers_every_validation_axis() -> None:
    """The ``ALL_AXES`` convenience tuple MUST enumerate every value of
    :class:`ValidationAxis`. Catches drift if SOS-11 §6 grows a fifth axis
    via a §15 amendment without the composer being updated."""
    assert set(ALL_AXES) == set(ValidationAxis)


def test_failed_axes_helper_lists_only_failing_axes() -> None:
    """Touches the :meth:`ValidationReport.failed_axes` helper. The
    composer's output composes cleanly with the contracts module's
    pre-existing accessors."""
    report = validate_chart(CONTRACT_MISMATCH_CHART)

    failed = set(report.failed_axes())
    assert ValidationAxis.INVARIANTS_HOLD in failed
    # The other axes should pass for parent_for_inline (well-formed XML,
    # under threshold, bound composes — only invariants fail).
    assert ValidationAxis.SCJSON_ROUND_TRIP not in failed
    assert ValidationAxis.LINT not in failed
    assert ValidationAxis.BOUND_CONVERGES not in failed


def test_default_constants_match_sos12_ratified_values() -> None:
    """Touches §6.5 (PCDN-005 depth cap default 8) + §9.1 (PCDN-003
    legibility threshold default 15) — both ratified in SOS-12. The
    composer's defaults MUST mirror them so a calling site that does
    not pass overrides exercises the ratified values."""
    assert DEFAULT_MAX_DEPTH == 8
    assert DEFAULT_LEGIBILITY_THRESHOLD == 15


def test_lint_axis_fails_on_depth_overflow_with_disp1_cite() -> None:
    """Touches §6 axis (b) + SOS-12 §6.5 / PCDN-005.

    deep_chain_overflow exceeds the dispatch-tree depth cap, which is
    enforced by SCXML-LINT-DISP-1 at chart-validation time. The lint
    axis surfaces the DISP-1 diagnostic; the composer reports
    passed=False with the rule id cited.
    """
    report = validate_chart(
        DEPTH_OVERFLOW_CHART, axes=(ValidationAxis.LINT,),
    )

    assert not report.lint.passed
    assert report.lint.diagnosis is not None
    assert "SCXML-LINT-DISP-1" in report.lint.diagnosis

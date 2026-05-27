"""Tests for SOS-13 `BoundsAnalysisInput` producer interface.

Per [SOS-13-CONCEPTS.md §15 SOS13W6D]
(../../../docs/concepts/SOS-13-CONCEPTS.md) — the producer Protocol +
in-memory stub landing wave. These tests pin:

  - `BoundsProducer` is `@runtime_checkable`; the `InMemoryBoundsProducer`
    stub satisfies it via `isinstance(...)`.
  - The stub returns the constructed `BoundsAnalysisInput` verbatim,
    ignoring the `chart_path` argument.
  - The stub rejects malformed constructor input (non-`BoundsAnalysisInput`)
    with `TypeError`.
  - A `BoundsAnalysisInput` constructed via the stub flows correctly
    into `sos13_eligibility.check_eligibility(...)` — eligible verdict
    on a well-formed input, ineligible on a stub returning empty bounds.
  - The Protocol's `produce()` accepts a `pathlib.Path` (the chosen
    signature; see SOS13W6D §15 entry for the rationale).

INV-SOS-G is upheld by construction: the producer binds discharges to
invariants; the consumer (eligibility oracle) refuses strips that lack
a citable discharge. These tests defend the seam between the two.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Mirror the sos-codegen flat-package layout used by sibling tests.
TESTS_DIR = Path(__file__).resolve().parent
TOOL_DIR = TESTS_DIR.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from sos13_bounds_producer import (  # noqa: E402
    BoundsProducer,
    InMemoryBoundsProducer,
)
from sos13_eligibility import (  # noqa: E402
    check_eligibility,
)
from sos13_invariants import (  # noqa: E402
    BoundsAnalysisInput,
    DischargeAnnotation,
    InvariantSpec,
)


# -----------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------


@pytest.fixture
def bounds_with_bounds_discharge() -> BoundsAnalysisInput:
    """A minimal well-formed BoundsAnalysisInput: one chart-derived
    invariant on `sched` plus a `bounds` discharge on the same state.

    Designed to flow through `check_eligibility(..., vs_op="VS-OP-1",
    region_id="sched")` as an eligible verdict, so the producer/
    consumer chain can be exercised end-to-end."""
    return BoundsAnalysisInput.from_lists(
        chart_id="producer-test-chart",
        invariants=[
            InvariantSpec(
                text="tid is bounded by ready-queue scan, i in [0, MAX_TASKS)",
                chart_site="sched.onentry",
                status="derived",
                bound_evidence="ready-queue scan; len <= MAX_TASKS",
            ),
        ],
        discharges=[
            DischargeAnnotation(
                chart_state="sched",
                check="bounds",
            ),
        ],
    )


# -----------------------------------------------------------------
# Protocol-shape tests
# -----------------------------------------------------------------


def test_bounds_producer_is_runtime_checkable_protocol(
    bounds_with_bounds_discharge: BoundsAnalysisInput,
) -> None:
    """The `BoundsProducer` Protocol is decorated `@runtime_checkable`
    per SOS13W6D §15; the in-memory stub satisfies it via the structural
    `isinstance` check."""
    producer = InMemoryBoundsProducer(bounds_with_bounds_discharge)
    assert isinstance(producer, BoundsProducer), (
        "InMemoryBoundsProducer must satisfy the BoundsProducer Protocol "
        "(structural isinstance check via @runtime_checkable)."
    )


def test_non_producer_object_fails_protocol_check() -> None:
    """An object with no `produce()` method MUST NOT pass the
    Protocol's structural check; this guards against future producer
    stubs accidentally being declared without the required method."""

    class NotAProducer:
        def something_else(self) -> None:
            pass

    assert not isinstance(NotAProducer(), BoundsProducer)


# -----------------------------------------------------------------
# Stub-behaviour tests
# -----------------------------------------------------------------


def test_in_memory_producer_returns_bounds_verbatim(
    bounds_with_bounds_discharge: BoundsAnalysisInput,
) -> None:
    """The stub returns the constructed BoundsAnalysisInput as the same
    object (identity-equal), regardless of the chart_path argument."""
    producer = InMemoryBoundsProducer(bounds_with_bounds_discharge)
    out = producer.produce(Path("/dev/null"))
    assert out is bounds_with_bounds_discharge


def test_in_memory_producer_ignores_chart_path(
    bounds_with_bounds_discharge: BoundsAnalysisInput,
) -> None:
    """Different chart_path values MUST yield the same output (the
    stub is path-agnostic). Real producers do care about the path; the
    stub does not."""
    producer = InMemoryBoundsProducer(bounds_with_bounds_discharge)
    out1 = producer.produce(Path("/tmp/chart-a.scxml"))
    out2 = producer.produce(Path("/var/tmp/chart-b.scjson"))
    assert out1 is out2
    assert out1 is bounds_with_bounds_discharge


def test_in_memory_producer_rejects_non_bounds_input() -> None:
    """Constructing the stub with a non-`BoundsAnalysisInput` argument
    raises `TypeError` so the producer-chain failure mode surfaces at
    construction time, not at first `produce()` call."""
    with pytest.raises(TypeError, match="BoundsAnalysisInput"):
        InMemoryBoundsProducer({"chart_id": "wrong-shape"})  # type: ignore[arg-type]


def test_in_memory_producer_accepts_empty_bounds() -> None:
    """An empty BoundsAnalysisInput is valid (no invariants, no
    discharges). The stub MUST accept it — this matches the
    `sos13_invariants.generate_invariants` empty-input case."""
    empty = BoundsAnalysisInput()
    producer = InMemoryBoundsProducer(empty)
    out = producer.produce(Path("ignored"))
    assert out is empty
    assert out.invariants == ()
    assert out.discharges == ()


# -----------------------------------------------------------------
# End-to-end producer → eligibility chain tests
# -----------------------------------------------------------------


def test_producer_output_flows_into_eligibility_as_eligible(
    bounds_with_bounds_discharge: BoundsAnalysisInput,
) -> None:
    """The wire from producer to consumer: a stub returning
    well-formed bounds with a `<sos:discharged check="bounds"/>` site
    yields an eligible VS-OP-1 verdict with a citable INV-S-CHART-N
    discharge per INV-SOS-G."""
    producer = InMemoryBoundsProducer(bounds_with_bounds_discharge)
    bounds = producer.produce(Path("ignored.scxml"))
    verdict = check_eligibility(bounds, vs_op="VS-OP-1", region_id="sched")
    assert verdict.eligible is True
    assert verdict.discharging_invariant == "INV-S-CHART-1"
    assert verdict.vs_op == "VS-OP-1"


def test_producer_output_flows_into_eligibility_as_ineligible() -> None:
    """A stub returning empty bounds correctly drives the eligibility
    oracle to the ineligible verdict — the conservative default per
    SOS-13 §7.3."""
    producer = InMemoryBoundsProducer(BoundsAnalysisInput())
    bounds = producer.produce(Path("ignored.scxml"))
    verdict = check_eligibility(bounds, vs_op="VS-OP-1", region_id="sched")
    assert verdict.eligible is False
    assert verdict.discharging_invariant is None
    assert "VS-OP-1" in verdict.reason


def test_producer_protocol_signature_accepts_path() -> None:
    """The Protocol's `produce()` signature accepts `pathlib.Path`
    per the SOS13W6D §15 entry's chosen signature. The stub's
    parameter MUST accept a Path without conversion."""
    bounds = BoundsAnalysisInput.from_lists(
        chart_id="path-shape",
        invariants=[
            InvariantSpec(
                text="trivial reachability",
                chart_site="root.onentry",
            ),
        ],
    )
    producer = InMemoryBoundsProducer(bounds)
    # Pass a concrete Path subclass instance to confirm the signature
    # accepts the documented type.
    p = Path("/some/where/chart.scxml")
    assert isinstance(p, Path)
    out = producer.produce(p)
    assert out is bounds

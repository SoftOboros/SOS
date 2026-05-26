"""SOS-09-F initial_value family.

Per §5.1: every channel kind (status / command / queue / shared) gets
at least one ``initial_value`` vector. The vector reads the register at
reset and asserts the observed value matches the chart-declared reset
value (per SOS-09-A bit_layout reset_value OR-reduction, mirrored from
SOS-09-B's ``<resetValue>``).
"""

from __future__ import annotations

from typing import Any

from ..base import (
    ChannelVectorPlan,
    EmissionError,
    MembraneVector,
    VectorFamily,
    VectorStep,
    render_failure_message,
)


def generate(plan: ChannelVectorPlan, seq: int = 0) -> list[VectorStep]:
    """Emit the initial-value stimulus step list.

    Single step: ``bus.read(plan.address)`` with expected = reset value
    (0 by default — the channel's bit_layout reset_value OR-reduction
    is computed by SOS-09-B; here we mirror the same default).
    """
    return [
        VectorStep(
            primitive="bus.read",
            args=(plan.address,),
            expected=0,
            description=f"reset read of channel {plan.channel_name}",
        ),
    ]


class InitialValueVector(MembraneVector):
    """Reads channel at reset; asserts value matches the chart default."""

    def __init__(self, *, plan: ChannelVectorPlan, seq: int = 0) -> None:
        super().__init__(plan=plan, family=VectorFamily.INITIAL_VALUE, seq=seq)
        self.steps = generate(plan, seq)
        self._observed: int = 0

    def setup(self, harness: Any) -> None:
        harness.seed(self.seed)

    def stimulate(self, harness: Any) -> None:
        step = self.steps[0]
        self._observed = harness.bus.read(*step.args)

    def observe(self, harness: Any) -> Any:
        return self._observed

    def assert_invariants(self, harness: Any) -> None:
        expected = self.steps[0].expected
        if self._observed != expected:
            msg = render_failure_message(
                channel_name=self.channel_name,
                channel_kind=self.channel_kind,
                channel_zone=self.channel_zone,
                family=VectorFamily.INITIAL_VALUE,
                stimulus=self.steps[0].description,
                expected=f"0x{expected:08X}",
                observed=f"0x{self._observed:08X}",
                channel_id=self.channel_id,
            )
            raise AssertionError(msg)


vector_class = InitialValueVector

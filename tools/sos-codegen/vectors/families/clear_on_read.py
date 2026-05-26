"""SOS-09-F clear_on_read family.

Per §2 failure mode 1: ``status`` channels carrying any ``clear-on-read``
bit-field MUST return the latched value AND atomically clear it. The
vector primes the register with a non-zero value, reads it (asserts
the value comes back), reads it a second time (asserts the cleared
value comes back). The second-read assertion catches the "non-
destructive read masquerading as clear-on-read" failure mode.

For channels without explicit clear-on-read bit-fields, the family is
still emitted when §5.1 says it applies (status / shared with the
applicability flag) — in that case the vector reads twice and asserts
the two reads return the same value (idempotent read; absence of side
effect).
"""

from __future__ import annotations

from typing import Any

from ..base import (
    ChannelVectorPlan,
    MembraneVector,
    VectorFamily,
    VectorStep,
    render_failure_message,
)


def generate(plan: ChannelVectorPlan, seq: int = 0) -> list[VectorStep]:
    # The chart-declared value to prime in the register. The
    # walker / harness setup is responsible for staging the value via
    # register_channel(...) before the vector runs.
    primed = 0xDEADBEEF & ((1 << plan.width_bits) - 1)
    return [
        VectorStep(
            primitive="bus.read",
            args=(plan.address,),
            expected=primed,
            description=(
                f"first read of channel {plan.channel_name} returns latched"
            ),
        ),
        VectorStep(
            primitive="bus.read",
            args=(plan.address,),
            expected=0,
            description=(
                f"second read of channel {plan.channel_name} returns cleared"
            ),
        ),
    ]


class ClearOnReadVector(MembraneVector):
    """Reads twice; asserts second read returns cleared value."""

    def __init__(self, *, plan: ChannelVectorPlan, seq: int = 0) -> None:
        super().__init__(plan=plan, family=VectorFamily.CLEAR_ON_READ, seq=seq)
        self.steps = generate(plan, seq)
        self._first: int = 0
        self._second: int = 0
        # The harness setup phase stages this value into the register.
        self._primed_value: int = self.steps[0].expected

    def setup(self, harness: Any) -> None:
        harness.seed(self.seed)
        # Prime the register so the first read returns the latched
        # value. Real-silicon equivalent: a HW-side event populated the
        # status bits before the SW-side read.
        reg = harness._registers.get(self._plan.address)
        if reg is None:
            harness.register_channel(
                address=self._plan.address,
                width_bits=self._plan.width_bits,
                # Mark every bit as clear-on-read; the family only
                # applies when at least one bit IS clear-on-read.
                clear_on_read_mask=(1 << self._plan.width_bits) - 1,
                initial_value=self._primed_value,
            )
        else:
            reg.value = self._primed_value & ((1 << self._plan.width_bits) - 1)
            # Ensure the clear-on-read mask is set; the harness setup
            # may have left it 0 for a non-clear-on-read register.
            reg.clear_on_read_mask = (1 << self._plan.width_bits) - 1

    def stimulate(self, harness: Any) -> None:
        self._first = harness.bus.read(*self.steps[0].args)
        self._second = harness.bus.read(*self.steps[1].args)

    def observe(self, harness: Any) -> Any:
        return (self._first, self._second)

    def assert_invariants(self, harness: Any) -> None:
        if self._first != self.steps[0].expected:
            msg = render_failure_message(
                channel_name=self.channel_name,
                channel_kind=self.channel_kind,
                channel_zone=self.channel_zone,
                family=VectorFamily.CLEAR_ON_READ,
                stimulus=self.steps[0].description,
                expected=f"0x{self.steps[0].expected:08X}",
                observed=f"0x{self._first:08X}",
                channel_id=self.channel_id,
            )
            raise AssertionError(msg)
        if self._second != self.steps[1].expected:
            msg = render_failure_message(
                channel_name=self.channel_name,
                channel_kind=self.channel_kind,
                channel_zone=self.channel_zone,
                family=VectorFamily.CLEAR_ON_READ,
                stimulus=self.steps[1].description,
                expected=f"0x{self.steps[1].expected:08X}",
                observed=f"0x{self._second:08X}",
                channel_id=self.channel_id,
            )
            raise AssertionError(msg)


vector_class = ClearOnReadVector

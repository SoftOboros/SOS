"""SOS-09-F write_then_read family.

Per §5.1 applicability: ``command`` / ``queue`` / ``shared`` channels
exercise write-then-read; ``status`` channels are read-only at the
HW->SW direction so they are excluded.

The vector writes a deterministic-seed-derived value to the channel,
reads it back, and asserts the read value matches the written value
(after applying the channel's width mask). This catches the §2 failure
mode "command channel write swallowed silently" — a register that
doesn't latch the written bits.
"""

from __future__ import annotations

from typing import Any

from ..base import (
    ChannelVectorPlan,
    MembraneVector,
    VectorFamily,
    VectorStep,
    derive_seed,
    render_failure_message,
)


def _seeded_value(plan: ChannelVectorPlan, seq: int) -> int:
    """Deterministic value to write — derived from the seed.

    Uses the same hash as derive_seed so two emit runs against the same
    chart produce bit-identical written values (INV-S-MEM-F-6).
    """
    s = derive_seed(plan.channel_id, VectorFamily.WRITE_THEN_READ, seq)
    mask = (1 << plan.width_bits) - 1
    return s & mask


def generate(plan: ChannelVectorPlan, seq: int = 0) -> list[VectorStep]:
    value = _seeded_value(plan, seq)
    return [
        VectorStep(
            primitive="bus.write",
            args=(plan.address, value),
            description=(
                f"write 0x{value:0{(plan.width_bits + 3) // 4}X} "
                f"to channel {plan.channel_name}"
            ),
        ),
        VectorStep(
            primitive="bus.read",
            args=(plan.address,),
            expected=value,
            description=(
                f"read-back of channel {plan.channel_name} after write"
            ),
        ),
    ]


class WriteThenReadVector(MembraneVector):
    """Writes a seeded value; reads back; asserts round-trip."""

    def __init__(self, *, plan: ChannelVectorPlan, seq: int = 0) -> None:
        super().__init__(plan=plan, family=VectorFamily.WRITE_THEN_READ, seq=seq)
        self.steps = generate(plan, seq)
        self._observed: int = 0
        self._written: int = self.steps[0].args[1]

    def setup(self, harness: Any) -> None:
        harness.seed(self.seed)

    def stimulate(self, harness: Any) -> None:
        harness.bus.write(*self.steps[0].args)
        self._observed = harness.bus.read(*self.steps[1].args)

    def observe(self, harness: Any) -> Any:
        return self._observed

    def assert_invariants(self, harness: Any) -> None:
        expected = self.steps[1].expected
        if self._observed != expected:
            msg = render_failure_message(
                channel_name=self.channel_name,
                channel_kind=self.channel_kind,
                channel_zone=self.channel_zone,
                family=VectorFamily.WRITE_THEN_READ,
                stimulus=self.steps[1].description,
                expected=f"0x{expected:08X}",
                observed=f"0x{self._observed:08X}",
                channel_id=self.channel_id,
            )
            raise AssertionError(msg)


vector_class = WriteThenReadVector

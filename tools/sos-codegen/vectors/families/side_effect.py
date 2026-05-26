"""SOS-09-F side_effect family.

Per §5.1 applicability + §2 failure mode 2: a ``command`` channel
declares ``sos:side_effect`` (e.g. ``oneToClear``); writing to it MUST
fire the chart-declared HW-side side effect (an IRQ assertion, a queue
depth decrement, etc.) The vector writes the trigger value, then
observes the side-effect surface via ``wait_irq(...)`` (the IRQ name
the chart declares for the side effect).

When the channel does NOT declare an explicit ``sos:side_effect`` /
``sos:irq``, the family still emits a deterministic write step but
the assertion degrades to "write completed without error" — the
emitter cannot fabricate a side-effect surface from nothing. This
matches the §2 / §5.1 row for ``command`` channels lacking
``sos:side_effect`` (the family is still emitted because §5.1 says it
applies to ``command``; the assertion shape adapts).
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
    s = derive_seed(plan.channel_id, VectorFamily.SIDE_EFFECT, seq)
    mask = (1 << plan.width_bits) - 1
    # Force at least one bit set so a `oneToClear` channel sees an
    # observable transition.
    return (s & mask) | 0x1


def generate(plan: ChannelVectorPlan, seq: int = 0) -> list[VectorStep]:
    value = _seeded_value(plan, seq)
    steps: list[VectorStep] = [
        VectorStep(
            primitive="bus.write",
            args=(plan.address, value),
            description=(
                f"side-effect write 0x{value:0{(plan.width_bits + 3) // 4}X} "
                f"to channel {plan.channel_name}"
            ),
        ),
    ]
    if plan.irq is not None:
        steps.append(
            VectorStep(
                primitive="wait_irq",
                args=(plan.irq,),
                expected=plan.irq,
                description=(
                    f"observe side-effect IRQ {plan.irq!r} for channel "
                    f"{plan.channel_name}"
                ),
            )
        )
    return steps


class SideEffectVector(MembraneVector):
    """Writes a trigger value; asserts the chart-declared side effect fired."""

    def __init__(self, *, plan: ChannelVectorPlan, seq: int = 0) -> None:
        super().__init__(plan=plan, family=VectorFamily.SIDE_EFFECT, seq=seq)
        self.steps = generate(plan, seq)
        self._irq_observed: bool = False
        self._irq_name: str | None = None

    def setup(self, harness: Any) -> None:
        harness.seed(self.seed)

    def stimulate(self, harness: Any) -> None:
        # Write the trigger.
        harness.bus.write(*self.steps[0].args)
        # If the channel declares an IRQ, wait for it.
        if len(self.steps) > 1 and self.steps[1].primitive == "wait_irq":
            try:
                self._irq_name = harness.wait_irq(*self.steps[1].args)
                self._irq_observed = True
            except (TimeoutError, AssertionError):
                self._irq_observed = False

    def observe(self, harness: Any) -> Any:
        return self._irq_observed

    def assert_invariants(self, harness: Any) -> None:
        if len(self.steps) > 1 and not self._irq_observed:
            irq_name = self.steps[1].args[0]
            msg = render_failure_message(
                channel_name=self.channel_name,
                channel_kind=self.channel_kind,
                channel_zone=self.channel_zone,
                family=VectorFamily.SIDE_EFFECT,
                stimulus=self.steps[1].description,
                expected=f"IRQ {irq_name!r} asserted",
                observed="no IRQ observed",
                channel_id=self.channel_id,
            )
            raise AssertionError(msg)


vector_class = SideEffectVector

"""SOS-09-F atomicity family.

Per §5.7 (PCDN-SOS-09-F-002 option (a)): concurrent stimuli use a
cocotb coroutine pair (HW-side + SW-side). Both coroutines launch
within ±1 simulation tick of each other; the vector asserts no torn
read AND mutex serialisation.

The Python-stub form uses two OS threads under ``threading``, mirroring
the surface so the cocotb-side adapter is byte-identical at the call
site. The mutex name comes from ``plan.mutex`` (the chart-declared
``sos:mutex``); when the channel has no explicit mutex, the family
defaults the mutex name to ``f"{channel_name}_lock"`` because
``shared`` channels default to ``mutex-required`` atomicity per
umbrella §5.3.
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


def _two_values(plan: ChannelVectorPlan, seq: int) -> tuple[int, int]:
    s = derive_seed(plan.channel_id, VectorFamily.ATOMICITY, seq)
    mask = (1 << plan.width_bits) - 1
    return (s & mask, (~s) & mask)


def _mutex_name(plan: ChannelVectorPlan) -> str:
    if plan.mutex:
        return plan.mutex
    return f"{plan.channel_name}_lock"


def generate(plan: ChannelVectorPlan, seq: int = 0) -> list[VectorStep]:
    hw_val, sw_val = _two_values(plan, seq)
    return [
        VectorStep(
            primitive="concurrent_writer",
            args=(plan.address, hw_val, _mutex_name(plan)),
            description=(
                f"HW-side concurrent write of 0x{hw_val:08X} to "
                f"{plan.channel_name} under mutex {_mutex_name(plan)!r}"
            ),
        ),
        VectorStep(
            primitive="concurrent_writer",
            args=(plan.address, sw_val, _mutex_name(plan)),
            description=(
                f"SW-side concurrent write of 0x{sw_val:08X} to "
                f"{plan.channel_name} under mutex {_mutex_name(plan)!r}"
            ),
        ),
        VectorStep(
            primitive="bus.read",
            args=(plan.address,),
            description=f"post-concurrent read of {plan.channel_name}",
        ),
    ]


class AtomicityVector(MembraneVector):
    """Concurrent HW+SW stimulus; asserts no torn read + mutex serialised."""

    def __init__(self, *, plan: ChannelVectorPlan, seq: int = 0) -> None:
        super().__init__(plan=plan, family=VectorFamily.ATOMICITY, seq=seq)
        self.steps = generate(plan, seq)
        self._hw_val: int = self.steps[0].args[1]
        self._sw_val: int = self.steps[1].args[1]
        self._mutex_name: str = self.steps[0].args[2]
        self._observed: int = 0
        self._mutex_claims: int = 0
        self._mutex_accesses: int = 0

    def setup(self, harness: Any) -> None:
        harness.seed(self.seed)
        # Ensure the channel is registered in the stub bus.
        if self._plan.address not in harness._registers:
            harness.register_channel(
                address=self._plan.address,
                width_bits=self._plan.width_bits,
            )

    def stimulate(self, harness: Any) -> None:
        addr = self._plan.address
        hw_val = self._hw_val
        sw_val = self._sw_val
        mutex = self._mutex_name

        def hw_side() -> None:
            harness.claim_mutex(mutex)
            harness.bus.write(addr, hw_val)

        def sw_side() -> None:
            harness.claim_mutex(mutex)
            harness.bus.write(addr, sw_val)

        h1 = harness.concurrent_writer(hw_side)
        h2 = harness.concurrent_writer(sw_side)
        h1.join()
        h2.join()
        self._observed = harness.bus.read(addr)
        self._mutex_claims = harness.mutex_claim_count(mutex)
        self._mutex_accesses = harness.successful_access_count(mutex)

    def observe(self, harness: Any) -> Any:
        return {
            "observed": self._observed,
            "mutex_claims": self._mutex_claims,
            "mutex_accesses": self._mutex_accesses,
        }

    def assert_invariants(self, harness: Any) -> None:
        # No torn read: the observed value is one of the two complete
        # values, not a bit-interleaved mix.
        if self._observed not in (self._hw_val, self._sw_val):
            msg = render_failure_message(
                channel_name=self.channel_name,
                channel_kind=self.channel_kind,
                channel_zone=self.channel_zone,
                family=VectorFamily.ATOMICITY,
                stimulus=self.steps[2].description,
                expected=(
                    f"one of {{0x{self._hw_val:08X}, 0x{self._sw_val:08X}}}"
                ),
                observed=f"0x{self._observed:08X}",
                channel_id=self.channel_id,
            )
            raise AssertionError(msg)
        # Mutex serialisation: both sides claimed AND both succeeded.
        if self._mutex_claims != 2 or self._mutex_accesses != 2:
            msg = render_failure_message(
                channel_name=self.channel_name,
                channel_kind=self.channel_kind,
                channel_zone=self.channel_zone,
                family=VectorFamily.ATOMICITY,
                stimulus=(
                    f"mutex {self._mutex_name!r} serialisation observation"
                ),
                expected="mutex_claim_count=2, successful_access_count=2",
                observed=(
                    f"mutex_claim_count={self._mutex_claims}, "
                    f"successful_access_count={self._mutex_accesses}"
                ),
                channel_id=self.channel_id,
            )
            raise AssertionError(msg)


vector_class = AtomicityVector

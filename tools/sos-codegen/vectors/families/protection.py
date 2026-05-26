"""SOS-09-F protection family.

Per §2 failure mode 3 + INV-S-MEM-F-5 + PCDN-SOS-09-F-003 (option (a)
fatal on un-rejected access): a ``shared`` / ``status`` / ``command`` /
``queue`` channel carrying ``sos:zone="privileged"`` MUST reject writes
issued from an ``unprivileged`` context AND surface the access via the
SOS-09-E per-channel-group strobe-latch (INV-S-MEM-E-5). A "silently
rejected" outcome is the worst failure mode SOS-09 prevents.

The vector:

  1. Installs the MPU via ``harness.install_mpu()`` (SOS-09-G runtime
     hook). The harness ``setup`` phase MAY have done this already; the
     vector's own ``setup`` is idempotent.
  2. Switches zone to ``unprivileged`` via ``harness.set_zone(...)``.
  3. Issues a write via ``harness.bus.write(...)``.
  4. Catches the AccessViolation, then observes the access-violation
     IRQ via ``harness.wait_irq("access_violation", ...)``, then
     reads the strobe-latch count via
     ``harness.access_violation_count(label)``.
  5. Asserts BOTH the rejection AND the event firing per INV-S-MEM-F-5.

When SOS-09-E's HDL template is not present (sos_regfile.{vhd,sv}.j2
missing), the strobe-latch check stubs to the harness's in-process
counter — a TODO marks the path for cherry-pick.
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
    s = derive_seed(plan.channel_id, VectorFamily.PROTECTION, seq)
    mask = (1 << plan.width_bits) - 1
    return (s & mask) | 0x1


def generate(plan: ChannelVectorPlan, seq: int = 0) -> list[VectorStep]:
    value = _seeded_value(plan, seq)
    return [
        VectorStep(
            primitive="install_mpu",
            args=(),
            description=(
                f"install MPU before protection write to {plan.channel_name}"
            ),
        ),
        VectorStep(
            primitive="set_zone",
            args=("unprivileged",),
            description="switch CPU stub to unprivileged zone",
        ),
        VectorStep(
            primitive="bus.write",
            args=(plan.address, value),
            description=(
                f"unprivileged write of 0x{value:0{(plan.width_bits + 3) // 4}X} "
                f"to channel {plan.channel_name} from unprivileged context"
            ),
        ),
        VectorStep(
            primitive="wait_irq",
            args=("access_violation",),
            expected="access_violation",
            description=(
                f"observe access-violation event for channel {plan.channel_name}"
            ),
        ),
    ]


class ProtectionVector(MembraneVector):
    """Unprivileged write; asserts rejection + access-violation event."""

    def __init__(self, *, plan: ChannelVectorPlan, seq: int = 0) -> None:
        super().__init__(plan=plan, family=VectorFamily.PROTECTION, seq=seq)
        self.steps = generate(plan, seq)
        self._rejected: bool = False
        self._event_observed: bool = False
        self._strobe_count_before: int = 0
        self._strobe_count_after: int = 0
        self._observed_value: int = 0

    def setup(self, harness: Any) -> None:
        harness.seed(self.seed)
        # Register the channel as privileged-only (idempotent).
        if self._plan.address not in harness._registers:
            harness.register_channel(
                address=self._plan.address,
                width_bits=self._plan.width_bits,
                privileged_only=True,
            )
        else:
            harness._registers[self._plan.address].privileged_only = True
        # Capture the strobe-latch count before the stimulus so we can
        # assert a delta of +1.
        label = f"0x{self._plan.address:08X}"
        self._strobe_count_before = harness.access_violation_count(label)
        # Cache the privileged-side initial value so we can verify the
        # write was indeed rejected (state unchanged).
        self._observed_value = harness._registers[self._plan.address].value

    def stimulate(self, harness: Any) -> None:
        # Install MPU + flip zone.
        harness.install_mpu()
        harness.set_zone("unprivileged")
        # Attempt unprivileged write — MUST raise.
        from ..harness import AccessViolation  # noqa: PLC0415
        try:
            harness.bus.write(*self.steps[2].args)
            self._rejected = False
        except AccessViolation:
            self._rejected = True
        # Restore zone before observing the event.
        harness.set_zone("privileged")
        # Observe the access-violation event.
        try:
            harness.wait_irq("access_violation")
            self._event_observed = True
        except (TimeoutError, AssertionError):
            self._event_observed = False
        # Sample the strobe-latch count.
        label = f"0x{self._plan.address:08X}"
        self._strobe_count_after = harness.access_violation_count(label)

    def observe(self, harness: Any) -> Any:
        return {
            "rejected": self._rejected,
            "event_observed": self._event_observed,
            "strobe_delta": self._strobe_count_after - self._strobe_count_before,
        }

    def assert_invariants(self, harness: Any) -> None:
        # INV-S-MEM-F-5 + PCDN-SOS-09-F-003 (fatal): rejection MUST be
        # accompanied by the access-violation event firing.
        if not self._rejected:
            msg = render_failure_message(
                channel_name=self.channel_name,
                channel_kind=self.channel_kind,
                channel_zone=self.channel_zone,
                family=VectorFamily.PROTECTION,
                stimulus=self.steps[2].description,
                expected="access rejected (privileged-only register)",
                observed="access accepted (privilege check missing)",
                channel_id=self.channel_id,
            )
            raise AssertionError(msg)
        if not self._event_observed:
            msg = render_failure_message(
                channel_name=self.channel_name,
                channel_kind=self.channel_kind,
                channel_zone=self.channel_zone,
                family=VectorFamily.PROTECTION,
                stimulus=self.steps[3].description,
                expected="access-violation event asserted",
                observed="rejected silently (no event)",
                channel_id=self.channel_id,
            )
            raise AssertionError(msg)
        # INV-S-MEM-E-5: strobe-latch delta MUST be >=1.
        # TODO(SOS-09-E): when sos_regfile.{vhd,sv}.j2 templates land,
        # this check moves to reading the per-channel-group strobe-latch
        # via the HDL signal. The current stub satisfies the invariant
        # against the in-process counter only.
        strobe_delta = self._strobe_count_after - self._strobe_count_before
        if strobe_delta < 1:
            msg = render_failure_message(
                channel_name=self.channel_name,
                channel_kind=self.channel_kind,
                channel_zone=self.channel_zone,
                family=VectorFamily.PROTECTION,
                stimulus="access-violation strobe-latch observation",
                expected="strobe_latch delta >= 1 (INV-S-MEM-E-5)",
                observed=f"strobe_latch delta = {strobe_delta}",
                channel_id=self.channel_id,
            )
            raise AssertionError(msg)


vector_class = ProtectionVector

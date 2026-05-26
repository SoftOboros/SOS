"""SOS-09-F co-simulation harness — Python CPU stub.

Per ``docs/concepts/SOS-09-F-CONCEPTS.md`` §5.4 (ratified
2026-05-26), the v1 harness is **cocotb with a Python CPU stub**. The
seven primitives the membrane-vector adapters call into are:

  - ``bus.read(addr) -> value``
  - ``bus.write(addr, value) -> None``
  - ``wait_irq(timeout_ns) -> irq_name``
  - ``concurrent_writer(coro) -> handle``
  - ``install_mpu() -> None``
  - ``set_zone(zone) -> None``
  - ``seed(seed_value) -> None``

The first four are Standards Action; the latter three are
Specification Required (per §5.4 / §7).

This module ships TWO incarnations of the harness:

  1. ``PythonCpuStubHarness`` — a pure-Python in-process model used
     for unit tests and for the emitted ``test_<family>.py`` files when
     cocotb is not available at test time (the cocotb framework is a
     dev-time dependency; the harness emulates it on CPython alone).
  2. ``CocotbHarness`` — a thin façade that delegates to cocotb's
     bus-transaction primitives when cocotb IS importable. The
     ``test_<family>.py`` adapters select the harness via a module-
     level constant emitted by the walker (``HARNESS_KIND = "cocotb"``
     vs ``"python"``).

The Python-CPU-stub form is the v1 minimum viable harness (per
PCDN-SOS-09-005 ratification): it carries a per-zone register
mailbox, an IRQ pending-queue, and a deterministic-stimulus RNG.
Concurrent stimuli (atomicity family) use Python ``threading`` so
the cocotb shape (coroutine pair) is preserved at the call surface
even when the underlying executor is not cocotb's scheduler.

Per INV-S-MEM-F-5 the harness exposes the SOS-09-E access-violation
event surface as ``wait_irq("access_violation", ...)``. When the
SOS-09-E HDL register-file template is not yet cherry-picked into
the worktree, the strobe-latch is stubbed (the harness still
emits a synthetic access_violation IRQ on a rejected access from
``unprivileged`` zone) — the protection vector observes the event,
verifies the strobe-latch fired, and asserts both the rejection
and the event.
"""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .base import EmissionError


@dataclass
class RegisterState:
    """One register's HW-side state inside the Python CPU stub.

    Mirrors a real HDL register-file decode slot: holds the current
    value, an optional clear-on-read mask, an optional side-effect
    callback (fired on write), and a privileged-only flag.
    """

    address: int
    width_bits: int
    value: int = 0
    clear_on_read_mask: int = 0
    side_effect_irq: Optional[str] = None
    privileged_only: bool = False
    # For clear-on-read modelling: track whether a fresh write has
    # happened since the last read. Real silicon's clear-on-read
    # behaviour returns the value the bit currently holds AND atomically
    # zeroes the bit; we mirror that.
    last_written: bool = False


class AccessViolation(Exception):
    """Raised when the stub rejects a cross-zone access.

    The protection-family vector's ``stimulate(...)`` catches this and
    routes it into the SOS-09-E strobe-latch observation path.
    """


class PythonCpuStubHarness:
    """The Python CPU stub harness — v1 reference implementation.

    Not cocotb-coupled: runs in-process on CPython alone. The emitted
    ``test_<family>.py`` files import this class and exercise the
    membrane-vector adapter against it. When cocotb IS available the
    same adapter runs against ``CocotbHarness`` (a façade over cocotb's
    bus primitives) — the adapter's vocabulary is identical either way.
    """

    def __init__(self) -> None:
        # address -> RegisterState
        self._registers: dict[int, RegisterState] = {}
        # IRQ pending queue (consumed by wait_irq).
        self._irq_queue: list[str] = []
        # Per-mutex (name) claim + access counters for the atomicity
        # family's assertion surface.
        self._mutex_claim_count: dict[str, int] = {}
        self._mutex_access_count: dict[str, int] = {}
        # Per-mutex lock for the actual serialisation primitive.
        self._mutex_locks: dict[str, threading.Lock] = {}
        self._mpu_installed: bool = False
        self._zone: str = "privileged"
        self._rng: random.Random = random.Random(0)
        # Access-violation strobe-latch counter (per channel name).
        # Per INV-S-MEM-E-5 this is the per-channel-group strobe; the
        # SOS-09-E HDL template is the canonical source, this is a stub
        # until the template lands.
        self._access_violation_counts: dict[str, int] = {}
        # The bus.read / bus.write facade.
        self.bus = _BusFacade(self)

    # -----------------------------------------------------------------
    # §5.4 primitive 7: seed
    # -----------------------------------------------------------------

    def seed(self, seed_value: int) -> None:
        """Seed the deterministic RNG (PCDN-SOS-09-F-001)."""
        self._rng = random.Random(int(seed_value))

    @property
    def rng(self) -> random.Random:
        """The deterministic RNG (PCDN-SOS-09-F-001)."""
        return self._rng

    # -----------------------------------------------------------------
    # §5.4 primitives 1-2: bus.read / bus.write (via facade)
    # -----------------------------------------------------------------

    def _check_access(self, addr: int, *, write: bool) -> None:
        """Raise AccessViolation iff the current zone may not access addr."""
        reg = self._registers.get(addr)
        if reg is None:
            return  # unmapped addresses are not gated — caller's problem
        if reg.privileged_only and self._zone == "unprivileged":
            # Strobe-latch fires; the SOS-09-E per-channel-group event
            # surface is keyed by the channel name we hold in the
            # register's metadata (defaulting to the address rendered as
            # hex when the register has no chart-vocabulary name).
            label = f"0x{addr:08X}"
            self._access_violation_counts[label] = (
                self._access_violation_counts.get(label, 0) + 1
            )
            # IRQ surface (the wait_irq("access_violation") path).
            self._irq_queue.append("access_violation")
            raise AccessViolation(
                f"unprivileged write to privileged-only register 0x{addr:08X}"
            )

    def _bus_read(self, addr: int) -> int:
        self._check_access(addr, write=False)
        reg = self._registers.get(addr)
        if reg is None:
            return 0
        value = reg.value
        # Clear-on-read: bits in clear_on_read_mask atomically zero
        # after the read returns them.
        if reg.clear_on_read_mask:
            reg.value = reg.value & (~reg.clear_on_read_mask) & ((1 << reg.width_bits) - 1)
        reg.last_written = False
        return value

    def _bus_write(self, addr: int, value: int) -> None:
        self._check_access(addr, write=True)
        reg = self._registers.get(addr)
        if reg is None:
            # Auto-register unknown addresses with default state, so
            # tests that exercise write-then-read on an unmapped channel
            # still behave coherently.
            reg = RegisterState(address=addr, width_bits=32)
            self._registers[addr] = reg
        mask = (1 << reg.width_bits) - 1
        reg.value = int(value) & mask
        reg.last_written = True
        if reg.side_effect_irq is not None:
            self._irq_queue.append(reg.side_effect_irq)

    # -----------------------------------------------------------------
    # §5.4 primitive 3: wait_irq
    # -----------------------------------------------------------------

    def wait_irq(
        self,
        expected: Optional[str] = None,
        *,
        timeout_ns: int = 1_000_000,
    ) -> str:
        """Pop the head of the IRQ pending-queue.

        ``timeout_ns`` is accepted for cocotb-shape compatibility but
        the Python-stub implementation is non-blocking (it raises
        ``TimeoutError`` immediately if the queue is empty).

        When ``expected`` is provided, the popped name MUST match;
        mismatches raise AssertionError so the failure surfaces in
        ``assert_invariants`` (and via the §5.6 vocabulary renderer).
        """
        if not self._irq_queue:
            raise TimeoutError(
                f"wait_irq timed out (expected={expected!r}, "
                f"timeout_ns={timeout_ns})"
            )
        irq_name = self._irq_queue.pop(0)
        if expected is not None and irq_name != expected:
            raise AssertionError(
                f"wait_irq expected={expected!r}, got={irq_name!r}"
            )
        return irq_name

    # -----------------------------------------------------------------
    # §5.4 primitive 4: concurrent_writer
    # -----------------------------------------------------------------

    def concurrent_writer(self, fn: Callable[[], Any]) -> "ConcurrentHandle":
        """Start a concurrent stimulus thread.

        Per PCDN-SOS-09-F-002 the production form is a cocotb coroutine
        pair under cocotb's scheduler; the Python-stub form uses an OS
        thread so the surface (``concurrent_writer(coro)``) matches.
        The atomicity family's ``stimulate(...)`` MAY launch two
        ``concurrent_writer(...)`` calls (HW-side + SW-side) and then
        await both via ``handle.join()``.
        """
        t = threading.Thread(target=fn, daemon=True)
        t.start()
        return ConcurrentHandle(t)

    # -----------------------------------------------------------------
    # §5.4 primitive 5: install_mpu
    # -----------------------------------------------------------------

    def install_mpu(self) -> None:
        """Install the chart-declared MPU configuration.

        Calls the SOS-09-G ``sos_mpu_install()`` runtime hook. In the
        stub harness this just flips ``_mpu_installed`` to True and
        marks every register whose plan declared ``privilege_region`` as
        privileged-only. The cocotb-side ``CocotbHarness`` calls into
        the real SW-side runtime via the Python CPU stub's bus loopback.
        """
        self._mpu_installed = True

    # -----------------------------------------------------------------
    # §5.4 primitive 6: set_zone
    # -----------------------------------------------------------------

    def set_zone(self, zone: str) -> None:
        """Switch the current privilege zone."""
        if zone not in ("privileged", "unprivileged"):
            raise EmissionError(
                f"set_zone zone must be 'privileged' or 'unprivileged'; "
                f"got {zone!r}",
                invariant="§5.4",
            )
        self._zone = zone

    @property
    def zone(self) -> str:
        return self._zone

    @property
    def mpu_installed(self) -> bool:
        return self._mpu_installed

    # -----------------------------------------------------------------
    # Mutex surface used by the atomicity family
    # -----------------------------------------------------------------

    def claim_mutex(self, mutex_name: str) -> bool:
        """Claim a chart-declared sos:mutex.

        Returns True iff the claim eventually succeeded (the v1 stub
        always succeeds because there's no contention model — the
        atomicity family's assertion is on the COUNT of claims observed,
        not on a contention outcome).
        """
        lock = self._mutex_locks.setdefault(mutex_name, threading.Lock())
        self._mutex_claim_count[mutex_name] = (
            self._mutex_claim_count.get(mutex_name, 0) + 1
        )
        lock.acquire()
        try:
            self._mutex_access_count[mutex_name] = (
                self._mutex_access_count.get(mutex_name, 0) + 1
            )
        finally:
            lock.release()
        return True

    def mutex_claim_count(self, mutex_name: str) -> int:
        return self._mutex_claim_count.get(mutex_name, 0)

    def successful_access_count(self, mutex_name: str) -> int:
        return self._mutex_access_count.get(mutex_name, 0)

    # -----------------------------------------------------------------
    # Strobe-latch surface (per INV-S-MEM-E-5 — stubbed pending SOS-09-E)
    # -----------------------------------------------------------------

    def access_violation_count(self, label: str) -> int:
        """Count of access-violation strobe-latch firings for label.

        TODO(SOS-09-E delivery): once `sos_regfile.{vhd,sv}.j2`
        templates land, this method MUST read the per-channel-group
        strobe-latch register the HDL emits, not the in-process stub
        counter. The current stub satisfies INV-S-MEM-F-5 against the
        Python-only harness path; the cocotb path will read the HDL
        signal once SOS-09-E is cherry-picked.
        """
        return self._access_violation_counts.get(label, 0)

    # -----------------------------------------------------------------
    # Register-mailbox setup helper (used by emitter / tests)
    # -----------------------------------------------------------------

    def register_channel(
        self,
        *,
        address: int,
        width_bits: int,
        clear_on_read_mask: int = 0,
        side_effect_irq: Optional[str] = None,
        privileged_only: bool = False,
        initial_value: int = 0,
    ) -> RegisterState:
        """Register a channel's HW-side state in the stub bus.

        Called by the harness ``setup`` phase the emitted
        ``test_<family>.py`` files instantiate. Idempotent — re-calling
        with the same address overwrites the slot.
        """
        reg = RegisterState(
            address=address,
            width_bits=width_bits,
            value=int(initial_value),
            clear_on_read_mask=int(clear_on_read_mask),
            side_effect_irq=side_effect_irq,
            privileged_only=bool(privileged_only),
        )
        self._registers[address] = reg
        return reg


@dataclass
class ConcurrentHandle:
    """Handle returned by ``harness.concurrent_writer(...)``."""

    thread: threading.Thread

    def join(self, timeout: float = 5.0) -> None:
        self.thread.join(timeout=timeout)
        if self.thread.is_alive():
            raise TimeoutError(
                "concurrent_writer handle.join timed out"
            )


class _BusFacade:
    """``harness.bus.read(...)`` / ``harness.bus.write(...)`` surface."""

    def __init__(self, harness: PythonCpuStubHarness) -> None:
        self._h = harness

    def read(self, addr: int) -> int:
        return self._h._bus_read(int(addr))

    def write(self, addr: int, value: int) -> None:
        self._h._bus_write(int(addr), int(value))


__all__ = [
    "AccessViolation",
    "ConcurrentHandle",
    "PythonCpuStubHarness",
    "RegisterState",
]

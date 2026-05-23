"""test_sos_strobe_latch.py - cocotb testbench for sos_strobe_latch

@spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.10
@parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
@grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)

Invariants cited (not re-derived):
  INV-SOS-A..H       (SOS-07 §6)
  INV-S-HDL-1..5     (SOS-08 §7)
  INV-S-HDL-A-1..5   (SOS-08-A §7) — INV-S-HDL-A-5 VACUOUSLY satisfied
                                       (no user-facing parameters)

Per PCDN-A-007 resolution (§15 2026-05-23): one Python file per primitive.
Per PCDN-A-bind-form resolved 2026-05-23: module-type SVA bind attaches the
sos_strobe_latch_sva module to every elaborated instance.

Hybrid handshake pattern under test (per task brief):
  * strobe (in)  -- 1-cycle pulse from producer (PULSE variant per §5.1).
  * latched (out) -- LEVEL-HELD output (level variant per §5.1).
  * ack (in)      -- 1-cycle pulse from consumer (PULSE variant per §5.1).

Coverage (per task brief):
  * test_reset_clears_latched              -- reset clears the state
  * test_strobe_in_idle_latches            -- strobe in IDLE -> latched next cycle
  * test_ack_while_latched_clears          -- ack while LATCHED -> latched=0 next cycle
  * test_multi_cycle_latched_no_ack        -- latched holds while no ack
  * test_restrobe_while_latched_is_dropped -- strobe in LATCHED is absorbed
  * test_same_cycle_strobe_ack_from_latched-- ack wins (canonical semantic)
  * test_same_cycle_strobe_ack_from_idle   -- strobe captures; ack is no-op
  * test_repeated_strobe_ack_cycles        -- end-to-end producer/consumer cycle
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly


# ---------------------------------------------------------------------------
# Test bench parameters / helpers
# ---------------------------------------------------------------------------

CLK_PERIOD_NS = 10  # 100 MHz


def _start_clock(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


async def _reset(dut, cycles: int = 4) -> None:
    """Drive synchronous active-high reset for `cycles` edges, then release."""
    dut.rst.value = 1
    dut.strobe.value = 0
    dut.ack.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


def _latched(dut) -> int:
    return int(dut.latched.value)


def _latched_state_q(dut) -> int:
    return int(dut.latched_state_q.value)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@cocotb.test()
async def test_reset_clears_latched(dut):
    """Out of reset, latched = 0 and the observability port agrees."""
    _start_clock(dut)
    await _reset(dut)

    await ReadOnly()
    assert _latched(dut) == 0, "latched must be zero out of reset"
    assert _latched_state_q(dut) == 0, "latched_state_q must be zero out of reset"


@cocotb.test()
async def test_strobe_in_idle_latches(dut):
    """A single-cycle strobe from IDLE causes latched=1 on the next edge,
    and the latched state holds in absence of ack."""
    _start_clock(dut)
    await _reset(dut)

    # Pulse strobe for one cycle.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1

    # Sample BEFORE the next edge: still IDLE (latched=0).
    await ReadOnly()
    assert _latched(dut) == 0, "latched must remain 0 during the strobe cycle"

    await RisingEdge(dut.clk)
    dut.strobe.value = 0

    # Now we are one edge past the strobe.
    await ReadOnly()
    assert _latched(dut) == 1, "latched must rise on the cycle after strobe"
    assert _latched_state_q(dut) == 1, "observability state must mirror latched"


@cocotb.test()
async def test_ack_while_latched_clears(dut):
    """ack pulsed while latched returns latched=0 on the next edge."""
    _start_clock(dut)
    await _reset(dut)

    # Latch first.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1
    await RisingEdge(dut.clk)
    dut.strobe.value = 0
    await ReadOnly()
    assert _latched(dut) == 1, "precondition: latched must be 1 before ack"

    # Now pulse ack for one cycle.
    await RisingEdge(dut.clk)
    dut.ack.value = 1
    await RisingEdge(dut.clk)
    dut.ack.value = 0

    await ReadOnly()
    assert _latched(dut) == 0, "latched must drop on the cycle after ack"
    assert _latched_state_q(dut) == 0


@cocotb.test()
async def test_multi_cycle_latched_no_ack(dut):
    """latched stays high for many cycles while no ack arrives."""
    _start_clock(dut)
    await _reset(dut)

    # Strobe to latch.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1
    await RisingEdge(dut.clk)
    dut.strobe.value = 0

    # Hold for a stretch with no ack.
    for cyc in range(12):
        await RisingEdge(dut.clk)
        await ReadOnly()
        assert _latched(dut) == 1, f"latched dropped without ack at cycle {cyc}"
        assert _latched_state_q(dut) == 1


@cocotb.test()
async def test_restrobe_while_latched_is_dropped(dut):
    """A second strobe while latched (no ack) is absorbed; latched
    remains high (no double-latch, no counter)."""
    _start_clock(dut)
    await _reset(dut)

    # First strobe -> latched.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1
    await RisingEdge(dut.clk)
    dut.strobe.value = 0
    await ReadOnly()
    assert _latched(dut) == 1

    # Repeated re-strobe across multiple cycles, no ack in flight.
    for _ in range(5):
        await RisingEdge(dut.clk)
        dut.strobe.value = 1
        await RisingEdge(dut.clk)
        dut.strobe.value = 0
        await ReadOnly()
        # latched must stay 1 across the re-strobe; never drops.
        assert _latched(dut) == 1, "re-strobe must NOT clear latched"

    # Now ack to verify state machine still escapes after absorbed restrobes.
    await RisingEdge(dut.clk)
    dut.ack.value = 1
    await RisingEdge(dut.clk)
    dut.ack.value = 0
    await ReadOnly()
    assert _latched(dut) == 0, "ack must clear after multiple absorbed restrobes"


@cocotb.test()
async def test_same_cycle_strobe_ack_from_latched(dut):
    """Canonical semantic: from LATCHED, simultaneous strobe + ack -> ack
    wins; the strobe is dropped; next cycle latched=0."""
    _start_clock(dut)
    await _reset(dut)

    # First latch.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1
    await RisingEdge(dut.clk)
    dut.strobe.value = 0
    await ReadOnly()
    assert _latched(dut) == 1, "precondition: latched=1 before same-cycle race"

    # Drive strobe AND ack on the same cycle.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1
    dut.ack.value = 1
    await RisingEdge(dut.clk)
    dut.strobe.value = 0
    dut.ack.value = 0

    await ReadOnly()
    assert _latched(dut) == 0, \
        "same-cycle strobe+ack from LATCHED: ack must win (latched -> 0)"
    assert _latched_state_q(dut) == 0

    # And critically, the dropped strobe must NOT re-latch on the following
    # cycle (no shadow / pending-strobe register present).
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert _latched(dut) == 0, "dropped same-cycle strobe must NOT re-latch"


@cocotb.test()
async def test_same_cycle_strobe_ack_from_idle(dut):
    """From IDLE, simultaneous strobe + ack -> strobe captures the event
    (latched=1 next cycle); ack is a no-op (no latched state to clear)."""
    _start_clock(dut)
    await _reset(dut)

    # Drive strobe AND ack on the same cycle while IDLE.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1
    dut.ack.value = 1
    await RisingEdge(dut.clk)
    dut.strobe.value = 0
    dut.ack.value = 0

    await ReadOnly()
    assert _latched(dut) == 1, \
        "same-cycle strobe+ack from IDLE: strobe captures; latched must be 1"
    assert _latched_state_q(dut) == 1


@cocotb.test()
async def test_repeated_strobe_ack_cycles(dut):
    """End-to-end producer/consumer cycle repeated many times: each
    strobe-then-ack pair toggles latched 0 -> 1 -> 0 deterministically."""
    _start_clock(dut)
    await _reset(dut)

    for cyc in range(16):
        # Idle in-between to flush any prior state (we're already IDLE here).
        await ReadOnly()
        assert _latched(dut) == 0, f"latched not idle at start of cycle {cyc}"

        # Strobe.
        await RisingEdge(dut.clk)
        dut.strobe.value = 1
        await RisingEdge(dut.clk)
        dut.strobe.value = 0
        await ReadOnly()
        assert _latched(dut) == 1, f"latch failed at cycle {cyc}"

        # Hold for a few cycles (consumer "processing" the event).
        for _ in range(2):
            await RisingEdge(dut.clk)
            await ReadOnly()
            assert _latched(dut) == 1, f"latched dropped pre-ack at cycle {cyc}"

        # Ack.
        await RisingEdge(dut.clk)
        dut.ack.value = 1
        await RisingEdge(dut.clk)
        dut.ack.value = 0
        await ReadOnly()
        assert _latched(dut) == 0, f"ack failed to clear at cycle {cyc}"

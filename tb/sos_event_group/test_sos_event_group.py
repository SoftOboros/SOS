"""test_sos_event_group.py - cocotb testbench for sos_event_group (L1 service)

@spec        docs/concepts/SOS-08-B-CONCEPTS.md §6.2 (sos_event_group)
              + §5 frozen decisions, §7 cross-service invariants,
              + §15 ratification entry (PCDN-SOS-08-B-002 -> N_BITS=32).
@parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L1 set), §7 (INV-S-HDL-1..5)
@grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
@l0          docs/concepts/SOS-08-A-CONCEPTS.md §6.10 (sos_strobe_latch)
              + §15 wave-2 amendments (PCDN-A-strobe-pending-shadow).

Cited invariants (not re-derived):
  INV-SOS-A..H        (SOS-07 §6)
  INV-S-HDL-1..5      (SOS-08 §7)
  INV-S-HDL-A-1..5    (SOS-08-A §7) -- L0 invariants hold per strobe_latch.
  INV-S-HDL-B-1..5    (SOS-08-B §7) -- service-level invariants this testbench
                                       exercises.

Per PCDN-A-007 resolution (§15 of SOS-08-A 2026-05-23): one Python file per
DUT.  Per PCDN-A-bind-form (§15 wave-1 entry of SOS-08-A): module-type bind
attaches sos_event_group_sva to every elaborated instance via the bind file
at sos_event_group_bind.sv.

Operations exercised (per §6.2 behavioural contract):
  * event.set       <-> set_req + set_mask pulse
  * event.wait      <-> wait_mask + wait_mode + wait_match (level)
  * event.peek      <-> bits[] (combinational observability)
  * event.clear     <-> clear_req + clear_mask pulse

Coverage (per task brief):
  * test_reset_clears_all_bits          -- reset clears every bit.
  * test_set_single_bit                 -- set a single bit; verify bits[i].
  * test_set_multiple_bits              -- set several bits at once.
  * test_clear_single_bit               -- clear a single set bit.
  * test_clear_multiple_bits            -- clear several set bits at once.
  * test_wait_any_one_bit_satisfies     -- wait-any predicate fires with one bit.
  * test_wait_all_requires_all          -- wait-all predicate requires every bit
                                            in the mask.
  * test_peek_does_not_disturb          -- reading bits[] across multiple cycles
                                            without set/clear leaves state stable.
  * test_simultaneous_set_clear_holds   -- design-choice property: same-cycle
                                            set+clear on a set bit -> bit stays
                                            set (shadow-promote semantic).
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly


CLK_PERIOD_NS = 10  # 100 MHz

# Per PCDN-SOS-08-B-002 resolution (§15 2026-05-23) the DUT's default N_BITS
# is 32; tests parameterise via env var so the same harness covers smaller
# overrides without re-editing the file.  Mirrors the sos_fifo_sync test's
# SOS_FIFO_SYNC_DEPTH / _WIDTH pattern.
N_BITS = int(os.environ.get("SOS_EVENT_GROUP_N_BITS", "32"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _n_bits(dut) -> int:
    return N_BITS


def _bits(dut) -> int:
    return int(dut.bits.value)


def _wait_match(dut) -> int:
    return int(dut.wait_match.value)


def _start_clock(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


async def _reset(dut, cycles: int = 4) -> None:
    """Drive synchronous active-high reset, then release."""
    dut.rst.value = 1
    dut.set_req.value = 0
    dut.set_mask.value = 0
    dut.clear_req.value = 0
    dut.clear_mask.value = 0
    dut.wait_mask.value = 0
    dut.wait_mode.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def _pulse_set(dut, mask: int) -> None:
    """Pulse set_req for one cycle with the given mask."""
    await RisingEdge(dut.clk)
    dut.set_req.value = 1
    dut.set_mask.value = mask
    await RisingEdge(dut.clk)
    dut.set_req.value = 0
    dut.set_mask.value = 0


async def _pulse_clear(dut, mask: int) -> None:
    """Pulse clear_req for one cycle with the given mask."""
    await RisingEdge(dut.clk)
    dut.clear_req.value = 1
    dut.clear_mask.value = mask
    await RisingEdge(dut.clk)
    dut.clear_req.value = 0
    dut.clear_mask.value = 0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_reset_clears_all_bits(dut):
    """Out of reset, all event bits and wait_match are zero."""
    _start_clock(dut)
    await _reset(dut)

    await ReadOnly()
    assert _bits(dut) == 0, "every bit must be zero out of reset"
    assert _wait_match(dut) == 0, "wait_match must be zero out of reset"


@cocotb.test()
async def test_set_single_bit(dut):
    """Pulsing set_req with a one-hot set_mask raises exactly that bit."""
    _start_clock(dut)
    await _reset(dut)

    n = _n_bits(dut)
    target = 1 << (n // 2)   # pick a middle bit to avoid edge-only coverage

    await _pulse_set(dut, target)

    await ReadOnly()
    observed = _bits(dut)
    assert observed == target, (
        f"event.set on bit {target:#x}: expected bits=={target:#x}, "
        f"observed bits=={observed:#x}"
    )


@cocotb.test()
async def test_set_multiple_bits(dut):
    """Pulsing set_req with a multi-bit set_mask raises every bit in the mask
    atomically (a single set transaction is one chart-side event.set call)."""
    _start_clock(dut)
    await _reset(dut)

    n = _n_bits(dut)
    # Pick three disjoint bits.
    bit_a = 1 << 0
    bit_b = 1 << (n // 2)
    bit_c = 1 << (n - 1)
    mask = bit_a | bit_b | bit_c

    await _pulse_set(dut, mask)

    await ReadOnly()
    observed = _bits(dut)
    assert observed == mask, (
        f"event.set multi-bit mask {mask:#x}: expected bits=={mask:#x}, "
        f"observed bits=={observed:#x}"
    )


@cocotb.test()
async def test_clear_single_bit(dut):
    """Setting several bits then clearing one drops exactly that bit."""
    _start_clock(dut)
    await _reset(dut)

    n = _n_bits(dut)
    bit_a = 1 << 0
    bit_b = 1 << (n // 2)
    bit_c = 1 << (n - 1)
    mask = bit_a | bit_b | bit_c

    await _pulse_set(dut, mask)
    await ReadOnly()
    assert _bits(dut) == mask, "precondition: all three bits must be set"

    await _pulse_clear(dut, bit_b)

    await ReadOnly()
    expected = mask & ~bit_b
    observed = _bits(dut)
    assert observed == expected, (
        f"event.clear on bit {bit_b:#x}: expected bits=={expected:#x}, "
        f"observed bits=={observed:#x}"
    )


@cocotb.test()
async def test_clear_multiple_bits(dut):
    """Clearing several bits at once drops every targeted bit, leaving
    unmentioned bits intact."""
    _start_clock(dut)
    await _reset(dut)

    n = _n_bits(dut)
    bit_a = 1 << 0
    bit_b = 1 << 1
    bit_c = 1 << (n // 2)
    bit_d = 1 << (n - 1)
    init = bit_a | bit_b | bit_c | bit_d

    await _pulse_set(dut, init)
    await ReadOnly()
    assert _bits(dut) == init, "precondition: all four bits must be set"

    clear_mask = bit_a | bit_c
    await _pulse_clear(dut, clear_mask)

    await ReadOnly()
    expected = init & ~clear_mask
    observed = _bits(dut)
    assert observed == expected, (
        f"event.clear multi-bit mask {clear_mask:#x}: expected bits=={expected:#x}, "
        f"observed bits=={observed:#x}"
    )


@cocotb.test()
async def test_wait_any_one_bit_satisfies(dut):
    """wait_mode=0 (any-of): wait_match goes high as soon as any bit in the
    wait_mask is set; conversely it stays low while none of the masked bits
    are set."""
    _start_clock(dut)
    await _reset(dut)

    n = _n_bits(dut)
    bit_in_mask = 1 << 2
    bit_other = 1 << 5
    wait_mask = bit_in_mask | (1 << 3)   # waiting on bit_in_mask or bit 3.

    # Apply wait_mask + any-of mode.
    dut.wait_mask.value = wait_mask
    dut.wait_mode.value = 0

    # No bit set yet -> no match.
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert _wait_match(dut) == 0, "wait-any must not fire with empty bits"

    # Set a bit OUTSIDE the wait_mask -> still no match.
    await _pulse_set(dut, bit_other)
    dut.wait_mask.value = wait_mask
    dut.wait_mode.value = 0
    await ReadOnly()
    assert _wait_match(dut) == 0, "wait-any must not fire on out-of-mask bits"

    # Set a bit INSIDE the wait_mask -> wait_match should rise.
    await _pulse_set(dut, bit_in_mask)
    dut.wait_mask.value = wait_mask
    dut.wait_mode.value = 0
    await ReadOnly()
    assert _wait_match(dut) == 1, "wait-any must fire once any masked bit is set"


@cocotb.test()
async def test_wait_all_requires_all(dut):
    """wait_mode=1 (all-of): wait_match goes high only when every bit in
    wait_mask is set."""
    _start_clock(dut)
    await _reset(dut)

    n = _n_bits(dut)
    bit_a = 1 << 1
    bit_b = 1 << 4
    bit_c = 1 << 7
    wait_mask = bit_a | bit_b | bit_c

    dut.wait_mask.value = wait_mask
    dut.wait_mode.value = 1   # all-of

    # Initially: no bits set -> no match.
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert _wait_match(dut) == 0, "wait-all must not fire with no bits set"

    # Set two of the three -> still no match.
    await _pulse_set(dut, bit_a | bit_b)
    dut.wait_mask.value = wait_mask
    dut.wait_mode.value = 1
    await ReadOnly()
    assert _wait_match(dut) == 0, "wait-all must not fire with partial mask satisfied"

    # Set the third -> wait_match should now fire.
    await _pulse_set(dut, bit_c)
    dut.wait_mask.value = wait_mask
    dut.wait_mode.value = 1
    await ReadOnly()
    assert _wait_match(dut) == 1, "wait-all must fire once every masked bit is set"

    # Clear one of the bits in the mask -> wait_match drops again.
    await _pulse_clear(dut, bit_b)
    dut.wait_mask.value = wait_mask
    dut.wait_mode.value = 1
    await ReadOnly()
    assert _wait_match(dut) == 0, "wait-all must drop once any masked bit is cleared"


@cocotb.test()
async def test_peek_does_not_disturb(dut):
    """event.peek (= reading bits[]) does not change internal state.  After
    setting a couple of bits we sample bits[] across many idle cycles and
    confirm it stays exactly equal to what we set."""
    _start_clock(dut)
    await _reset(dut)

    n = _n_bits(dut)
    bit_a = 1 << 0
    bit_b = 1 << (n // 2)
    mask = bit_a | bit_b

    await _pulse_set(dut, mask)
    await ReadOnly()
    assert _bits(dut) == mask, "precondition: bits must reflect the set mask"

    # Now hold idle (no set / clear / reset pulses) and observe stability.
    for cyc in range(8):
        await RisingEdge(dut.clk)
        await ReadOnly()
        observed = _bits(dut)
        assert observed == mask, (
            f"peek cycle {cyc}: bits changed without set/clear -- "
            f"expected {mask:#x}, observed {observed:#x}"
        )


@cocotb.test()
async def test_simultaneous_set_clear_holds(dut):
    """Design-choice property (see RTL header): when a bit is already SET and
    both set_mask[i] and clear_mask[i] pulse the same cycle, the L0
    sos_strobe_latch's wave-2 shadow-promote semantic preserves the bit -- it
    stays set on the next cycle.  This is the agent-flagged "simultaneous
    set+clear on a set bit" resolution."""
    _start_clock(dut)
    await _reset(dut)

    n = _n_bits(dut)
    target = 1 << (n // 4)

    # Pre-set the bit.
    await _pulse_set(dut, target)
    await ReadOnly()
    assert _bits(dut) == target, "precondition: target bit must be set"

    # Same-cycle set + clear.
    await RisingEdge(dut.clk)
    dut.set_req.value = 1
    dut.set_mask.value = target
    dut.clear_req.value = 1
    dut.clear_mask.value = target
    await RisingEdge(dut.clk)
    dut.set_req.value = 0
    dut.set_mask.value = 0
    dut.clear_req.value = 0
    dut.clear_mask.value = 0

    await ReadOnly()
    observed = _bits(dut)
    assert observed == target, (
        "simultaneous set+clear on a set bit must preserve the bit "
        f"(shadow-promote); expected {target:#x}, observed {observed:#x}"
    )

    # One further clear (no concurrent set) must finally drop it.
    await _pulse_clear(dut, target)
    await ReadOnly()
    observed = _bits(dut)
    assert observed == 0, (
        "lone clear must drop the bit; observed bits={observed:#x}"
        .format(observed=observed)
    )

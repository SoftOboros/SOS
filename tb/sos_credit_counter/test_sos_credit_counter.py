"""
test_sos_credit_counter.py - cocotb testbench for sos_credit_counter

@spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.6
@amendments  docs/concepts/SOS-08-A-CONCEPTS.md §15 (2026-05-23 entries):
             - PCDN-A-002: bare `req`/`ack` naming on control primitives.
             - PCDN-A-mutex-ack: pulse variant of §5.1 control-handshake
               for non-ownership-tracking stateful primitives; this primitive
               uses the pulse variant — one-shot per acquire attempt.
             - PCDN-A-007: one cocotb file per primitive.
@parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
@grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)

Invariants cited (not re-derived):
  INV-SOS-A..H       (SOS-07 §6)
  INV-S-HDL-1..5     (SOS-08 §7)
  INV-S-HDL-A-1..5   (SOS-08-A §7)

Coverage (per the SOS-08-A-impl task brief):
  - test_reset_restores_init        : reset returns credits to INIT_CREDITS.
  - test_acquire_when_empty_no_ack  : acquire_req with credits=0 -> no ack.
  - test_acquire_decrements         : acquire_req with credits>0 -> ack +
                                      credits decrements.
  - test_release_increments         : release_req -> credits increments.
  - test_release_at_max_is_no_op    : release_req at MAX -> credits unchanged.
  - test_alternating_at_boundary    : acquire/release at credits=1 boundary.
  - test_simultaneous_net_neutral   : same-cycle acquire+release nets to zero.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly


# ---------------------------------------------------------------------------
# Test parameters. The example/instantiate.{vhd,sv} uses INIT_CREDITS=4,
# MAX_CREDITS=8; mirror that in the default test config.
# ---------------------------------------------------------------------------
INIT_CREDITS = int(os.environ.get("INIT_CREDITS", "4"))
MAX_CREDITS = int(os.environ.get("MAX_CREDITS", "8"))
CLK_PERIOD_NS = 10  # 100 MHz


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


async def _reset(dut, cycles: int = 4):
    """Drive sync active-high reset for `cycles` clock edges, then release."""
    dut.rst.value = 1
    dut.acquire_req.value = 0
    dut.release_req.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


def _credits(dut) -> int:
    return int(dut.credits.value)


def _ack(dut) -> int:
    return int(dut.acquire_ack.value)


async def _acquire_pulse(dut):
    """Drive a 1-cycle acquire_req pulse. Caller should sample ack on the
    cycle the pulse is high (combinational ack)."""
    dut.acquire_req.value = 1
    await RisingEdge(dut.clk)
    dut.acquire_req.value = 0


async def _release_pulse(dut):
    """Drive a 1-cycle release_req pulse."""
    dut.release_req.value = 1
    await RisingEdge(dut.clk)
    dut.release_req.value = 0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@cocotb.test()
async def test_reset_restores_init(dut):
    """After reset, credits == INIT_CREDITS and ack is low."""
    await _start_clock(dut)
    await _reset(dut)

    await ReadOnly()
    assert _credits(dut) == INIT_CREDITS, \
        f"credits={_credits(dut)} after reset, expected INIT_CREDITS={INIT_CREDITS}"
    assert _ack(dut) == 0, "acquire_ack must be low out of reset"


@cocotb.test()
async def test_acquire_when_empty_no_ack(dut):
    """With credits driven to 0, acquire_req does NOT produce an ack."""
    await _start_clock(dut)
    await _reset(dut)

    # Drain to zero via repeated acquire pulses.
    for _ in range(INIT_CREDITS):
        dut.acquire_req.value = 1
        await RisingEdge(dut.clk)
    dut.acquire_req.value = 0
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert _credits(dut) == 0, f"credits={_credits(dut)} after drain, expected 0"

    # Now fire acquire_req with credits=0; ack must stay low.
    await RisingEdge(dut.clk)
    dut.acquire_req.value = 1
    await ReadOnly()
    assert _ack(dut) == 0, \
        f"acquire_ack must stay low when credits=0; got ack={_ack(dut)}"
    assert _credits(dut) == 0, "credits must stay at 0 (no underflow)"

    # And credits must not have decremented on the next edge.
    await RisingEdge(dut.clk)
    dut.acquire_req.value = 0
    await ReadOnly()
    assert _credits(dut) == 0, "credits must remain 0 after failed acquire"


@cocotb.test()
async def test_acquire_decrements(dut):
    """acquire_req with credits > 0 produces a 1-cycle ack and decrements credits."""
    await _start_clock(dut)
    await _reset(dut)

    await ReadOnly()
    start = _credits(dut)
    assert start == INIT_CREDITS

    # Fire one acquire pulse.
    await RisingEdge(dut.clk)
    dut.acquire_req.value = 1
    await ReadOnly()
    # Combinational ack must be high on the same cycle req is high (credits>0).
    assert _ack(dut) == 1, f"expected ack pulse on cycle req fires; got ack={_ack(dut)}"

    # Next edge: credits decrement, ack deasserts.
    await RisingEdge(dut.clk)
    dut.acquire_req.value = 0
    await ReadOnly()
    assert _credits(dut) == start - 1, \
        f"credits={_credits(dut)} after one acquire, expected {start - 1}"
    assert _ack(dut) == 0, "ack must drop after the pulse"


@cocotb.test()
async def test_release_increments(dut):
    """release_req increments credits by 1 on the next cycle."""
    await _start_clock(dut)
    await _reset(dut)

    await ReadOnly()
    start = _credits(dut)

    # Fire one release pulse.
    await RisingEdge(dut.clk)
    dut.release_req.value = 1
    await RisingEdge(dut.clk)
    dut.release_req.value = 0
    await ReadOnly()
    assert _credits(dut) == start + 1, \
        f"credits={_credits(dut)} after one release, expected {start + 1}"


@cocotb.test()
async def test_release_at_max_is_no_op(dut):
    """release_req while credits == MAX_CREDITS is silently dropped."""
    await _start_clock(dut)
    await _reset(dut)

    # Fill to MAX via repeated release pulses.
    deltas = MAX_CREDITS - INIT_CREDITS
    for _ in range(deltas):
        dut.release_req.value = 1
        await RisingEdge(dut.clk)
    dut.release_req.value = 0
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert _credits(dut) == MAX_CREDITS, \
        f"credits={_credits(dut)} after fill, expected MAX_CREDITS={MAX_CREDITS}"

    # Now fire release_req at MAX; credits must stay at MAX.
    await RisingEdge(dut.clk)
    dut.release_req.value = 1
    await RisingEdge(dut.clk)
    dut.release_req.value = 0
    await ReadOnly()
    assert _credits(dut) == MAX_CREDITS, \
        f"release at MAX must be a no-op; got credits={_credits(dut)}"


@cocotb.test()
async def test_alternating_at_boundary(dut):
    """At credits == 1, alternating acquire/release cycles through 1 -> 0 -> 1.

    Verifies the one-shot semantics at the lower boundary: when credits drops
    to 0 the next acquire (sole pulse) fails to ack until a release lifts it
    back to 1.
    """
    await _start_clock(dut)
    await _reset(dut)

    # Drain to 1.
    for _ in range(INIT_CREDITS - 1):
        dut.acquire_req.value = 1
        await RisingEdge(dut.clk)
    dut.acquire_req.value = 0
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert _credits(dut) == 1, f"credits={_credits(dut)} after drain-to-1"

    # acquire(credits=1) -> ack, credits=0
    await RisingEdge(dut.clk)
    dut.acquire_req.value = 1
    await ReadOnly()
    assert _ack(dut) == 1, "acquire at credits=1 must ack"
    await RisingEdge(dut.clk)
    dut.acquire_req.value = 0
    await ReadOnly()
    assert _credits(dut) == 0
    assert _ack(dut) == 0

    # acquire(credits=0) -> no ack
    await RisingEdge(dut.clk)
    dut.acquire_req.value = 1
    await ReadOnly()
    assert _ack(dut) == 0, "acquire at credits=0 must NOT ack"
    await RisingEdge(dut.clk)
    dut.acquire_req.value = 0
    await ReadOnly()
    assert _credits(dut) == 0

    # release -> credits=1
    await RisingEdge(dut.clk)
    dut.release_req.value = 1
    await RisingEdge(dut.clk)
    dut.release_req.value = 0
    await ReadOnly()
    assert _credits(dut) == 1, f"after release credits={_credits(dut)}, expected 1"

    # acquire again -> ack, credits=0
    await RisingEdge(dut.clk)
    dut.acquire_req.value = 1
    await ReadOnly()
    assert _ack(dut) == 1, "acquire at credits=1 (post-release) must ack"


@cocotb.test()
async def test_simultaneous_net_neutral(dut):
    """Same-cycle acquire+release leaves credits unchanged (in-bound)."""
    await _start_clock(dut)
    await _reset(dut)

    await ReadOnly()
    start = _credits(dut)
    assert 0 < start < MAX_CREDITS, \
        "test setup expects INIT_CREDITS strictly inside (0, MAX_CREDITS)"

    # Fire both pulses on the same cycle.
    await RisingEdge(dut.clk)
    dut.acquire_req.value = 1
    dut.release_req.value = 1
    await ReadOnly()
    assert _ack(dut) == 1, "acquire_ack must still pulse on simultaneous cycle"

    await RisingEdge(dut.clk)
    dut.acquire_req.value = 0
    dut.release_req.value = 0
    await ReadOnly()
    assert _credits(dut) == start, \
        f"simultaneous acquire+release must be net-neutral; got credits={_credits(dut)}, expected {start}"

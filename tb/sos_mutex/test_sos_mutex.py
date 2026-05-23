"""
test_sos_mutex.py - cocotb testbench for sos_mutex

@spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.5
@parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
@grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)

Invariants cited (not re-derived):
  INV-SOS-A..H       (SOS-07 §6)
  INV-S-HDL-1..5     (SOS-08 §7)
  INV-S-HDL-A-1..5   (SOS-08-A §7)

Per PCDN-A-007 resolution (§15 2026-05-23): one Python file per primitive.

Coverage (per task brief):
  - test_single_client_acquire_release
  - test_two_client_contention
  - test_round_robin_fairness
  - test_simultaneous_request_edge_case
  - test_reset_clears_holder
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly


# ---------------------------------------------------------------------------
# Test parameters: N_CLIENTS is set by the simulator at elaboration. The cocotb
# tests assume N_CLIENTS == 4 by default, which matches the examples/ shape.
# ---------------------------------------------------------------------------
N_CLIENTS = int(os.environ.get("N_CLIENTS", "4"))
CLK_PERIOD_NS = 10  # 100 MHz


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _start_clock(dut):
    """Kick the clock."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


async def _reset(dut, cycles: int = 4):
    """Drive sync active-high reset for `cycles` clock edges, then release."""
    dut.rst.value = 1
    dut.req.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


def _set_req_bit(dut, bit_index: int, value: int) -> None:
    """Set a single bit of the req vector while preserving the others."""
    cur = int(dut.req.value)
    if value:
        cur |= (1 << bit_index)
    else:
        cur &= ~(1 << bit_index)
    dut.req.value = cur


def _get_ack(dut) -> int:
    return int(dut.ack.value)


def _holder_unheld_value() -> int:
    """The holder_id sentinel for "unheld" is N_CLIENTS."""
    return N_CLIENTS


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@cocotb.test()
async def test_single_client_acquire_release(dut):
    """One client requests; one client gets ack; deassert releases."""
    await _start_clock(dut)
    await _reset(dut)

    # Pre-condition: unheld.
    await ReadOnly()
    assert _get_ack(dut) == 0, "ack must be zero out of reset"
    assert int(dut.locked.value) == 0, "locked must be zero out of reset"
    assert int(dut.holder_id.value) == _holder_unheld_value(), \
        "holder_id must equal N_CLIENTS (unheld) out of reset"

    # Client 0 asserts req.
    await RisingEdge(dut.clk)
    _set_req_bit(dut, 0, 1)

    # One cycle later the grant resolves.
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert _get_ack(dut) == (1 << 0), f"expected ack[0]; got ack={_get_ack(dut):0{N_CLIENTS}b}"
    assert int(dut.locked.value) == 1
    assert int(dut.holder_id.value) == 0

    # Hold for a few cycles.
    for _ in range(3):
        await RisingEdge(dut.clk)
        await ReadOnly()
        assert _get_ack(dut) == (1 << 0), "ack[0] must remain while held"

    # Release: client deasserts req.
    await RisingEdge(dut.clk)
    _set_req_bit(dut, 0, 0)

    # One cycle later: ack drops, holder_id resets.
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert _get_ack(dut) == 0, "ack must clear after req drop"
    assert int(dut.locked.value) == 0
    assert int(dut.holder_id.value) == _holder_unheld_value()


@cocotb.test()
async def test_two_client_contention(dut):
    """Two clients request simultaneously while Free; exactly one wins."""
    if N_CLIENTS < 2:
        return  # not meaningful

    await _start_clock(dut)
    await _reset(dut)

    # Clients 0 and 1 assert req on the same cycle.
    await RisingEdge(dut.clk)
    dut.req.value = (1 << 0) | (1 << 1)

    await RisingEdge(dut.clk)
    await ReadOnly()
    ack = _get_ack(dut)
    assert bin(ack).count("1") == 1, f"exactly one ack must be set, got {ack:0{N_CLIENTS}b}"
    winner = ack.bit_length() - 1
    assert winner in (0, 1)
    assert int(dut.holder_id.value) == winner
    assert int(dut.locked.value) == 1

    # Winner releases; loser is still asserting -> loser gets the lock next.
    await RisingEdge(dut.clk)
    _set_req_bit(dut, winner, 0)

    # Held -> Free -> Held: takes 2 edges.
    await RisingEdge(dut.clk)  # FSM leaves HELD this edge.
    await RisingEdge(dut.clk)  # FSM grants the other client this edge.
    await ReadOnly()
    new_ack = _get_ack(dut)
    expected = (1 << (1 - winner))
    assert new_ack == expected, \
        f"after winner release the other client must hold; ack={new_ack:0{N_CLIENTS}b}"


@cocotb.test()
async def test_round_robin_fairness(dut):
    """All N_CLIENTS request continuously; each gets at least one grant
    within N_CLIENTS resolutions."""
    if N_CLIENTS < 2:
        return

    await _start_clock(dut)
    await _reset(dut)

    seen = set()
    # All clients request, every cycle.
    await RisingEdge(dut.clk)
    dut.req.value = (1 << N_CLIENTS) - 1

    # Run for enough cycles to cover the rotation. The lock is held one cycle
    # between grants (FREE->HELD->FREE) so 3 cycles per grant in the worst
    # case is safe. We also force each holder to drop req briefly so the
    # arbiter cycles.
    last_holder = None
    for _cyc in range(N_CLIENTS * 8):
        await ReadOnly()
        ack = _get_ack(dut)
        if ack:
            holder = ack.bit_length() - 1
            seen.add(holder)
            last_holder = holder
        await RisingEdge(dut.clk)
        # Briefly drop the current holder's req so it releases.
        if last_holder is not None:
            mask = ((1 << N_CLIENTS) - 1) & ~(1 << last_holder)
            dut.req.value = mask
            await RisingEdge(dut.clk)
            dut.req.value = (1 << N_CLIENTS) - 1

    assert seen == set(range(N_CLIENTS)), \
        f"every client must have been granted at least once; saw {seen}"


@cocotb.test()
async def test_simultaneous_request_edge_case(dut):
    """All clients request on the exact same cycle from idle. Exactly one
    wins (mutual exclusion); winner is deterministic per the round-robin
    pointer starting at 0 -> client 0 wins."""

    await _start_clock(dut)
    await _reset(dut)

    await RisingEdge(dut.clk)
    dut.req.value = (1 << N_CLIENTS) - 1

    await RisingEdge(dut.clk)
    await ReadOnly()
    ack = _get_ack(dut)
    assert bin(ack).count("1") == 1, \
        f"mutual exclusion: at most one ack; got {ack:0{N_CLIENTS}b}"
    # Round-robin pointer starts at 0 out of reset, so client 0 wins.
    assert ack == (1 << 0), f"expected client 0 to win first; got ack={ack:0{N_CLIENTS}b}"
    assert int(dut.holder_id.value) == 0


@cocotb.test()
async def test_reset_clears_holder(dut):
    """While a client holds the lock, asserting reset must clear the holder
    and the ack vector."""
    if N_CLIENTS < 1:
        return

    await _start_clock(dut)
    await _reset(dut)

    # Acquire on client 0.
    await RisingEdge(dut.clk)
    _set_req_bit(dut, 0, 1)
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert _get_ack(dut) == (1 << 0)
    assert int(dut.locked.value) == 1
    assert int(dut.holder_id.value) == 0

    # Assert reset.
    await RisingEdge(dut.clk)
    dut.rst.value = 1

    # One cycle later the FSM is back at Free.
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert _get_ack(dut) == 0, "reset must clear ack"
    assert int(dut.locked.value) == 0, "reset must clear locked"
    assert int(dut.holder_id.value) == _holder_unheld_value(), \
        "reset must restore holder_id to N_CLIENTS (unheld)"

    # Release reset; with req still high, client 0 must reacquire.
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert _get_ack(dut) == (1 << 0), "reacquire after reset deassert"

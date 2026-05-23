"""
test_sos_resource_pool.py - cocotb testbench for sos_resource_pool

@spec        docs/concepts/SOS-08-B-CONCEPTS.md §6.3 (sos_resource_pool
                                                       interface + service-
                                                       level SVA SVA-POOL-1..5)
             docs/concepts/SOS-08-B-CONCEPTS.md §15 (2026-05-23 ratification:
                                                       PCDN-SOS-08-B-003 →
                                                       ID_WIDTH default 16,
                                                       matching chart's task_id)
             docs/concepts/SOS-08-A-CONCEPTS.md §6.6 (sos_credit_counter L0)
             docs/concepts/SOS-08-A-CONCEPTS.md §6.7 (sos_dpram_arb L0, FWFT
                                                      read-old semantics)
@parent      docs/concepts/SOS-08-CONCEPTS.md §6, §7 (INV-S-HDL-1..5)
@grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)

Invariants cited (not re-derived):
  INV-SOS-A..H        (SOS-07 §6)
  INV-S-HDL-1..5      (SOS-08 §7)
  INV-S-HDL-B-1..5    (SOS-08-B §7)

Coverage (per the SOS-08-B-impl task brief):
  - test_reset_initialises_pool   : after reset, free_count == POOL_SIZE
                                     and alloc_ack is low.
  - test_alloc_until_empty        : POOL_SIZE successful allocs drain
                                     free_count to 0; the next alloc_req
                                     produces alloc_ack=0 (exhaustion,
                                     SVA-POOL-3).
  - test_free_returns_id_to_pool  : alloc one id, free that id, free_count
                                     returns to POOL_SIZE; the just-freed
                                     id is the next one returned by
                                     alloc (lowest-id-first encoder).
  - test_write_then_read          : write_meta + read_meta RAW round-trip
                                     across multiple slots.
  - test_alloc_free_cycle         : sequential alloc/free over many cycles
                                     keeps free_count + busy_count ==
                                     POOL_SIZE (SVA-POOL-4 conservation).
  - test_double_free_is_noop      : free of an already-free id leaves
                                     free_count unchanged (SVA-POOL-2).
  - test_lowest_id_first_order    : a fresh pool returns ids 0, 1, 2, ...
                                     in order (priority-encoder direction
                                     contract).
"""

from __future__ import annotations

import os
import random
from typing import List

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge


# ---------------------------------------------------------------------------
# Test parameters. The example/instantiate.{vhd,sv} uses POOL_SIZE=64,
# ID_WIDTH=16, META_WIDTH=128 (the chart's task pool with TCB-shaped
# metadata). The default test config keeps POOL_SIZE small so the
# alloc-until-empty test completes quickly under cocotb.
# ---------------------------------------------------------------------------
POOL_SIZE = int(os.environ.get("POOL_SIZE", "8"))
ID_WIDTH = int(os.environ.get("ID_WIDTH", "16"))
META_WIDTH = int(os.environ.get("META_WIDTH", "32"))
CLK_PERIOD_NS = 10  # 100 MHz


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


async def _reset(dut, cycles: int = 4):
    """Drive sync active-high reset for `cycles` clock edges, then release."""
    dut.rst.value = 1
    dut.alloc_req.value = 0
    dut.free_req.value = 0
    dut.free_id.value = 0
    dut.read_id.value = 0
    dut.write_req.value = 0
    dut.write_id.value = 0
    dut.write_meta.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


def _free_count(dut) -> int:
    return int(dut.free_count.value)


def _ack(dut) -> int:
    return int(dut.alloc_ack.value)


def _alloc_id(dut) -> int:
    return int(dut.alloc_id.value)


def _read_meta(dut) -> int:
    return int(dut.read_meta.value)


async def _alloc_one(dut):
    """Fire a 1-cycle alloc_req pulse, sample ack + id on the same cycle,
    and return (ack, aid) where aid is None when ack==0. Caller must check
    ack themselves if exhaustion is possible.

    Aligns to a clock edge before driving the pulse to keep the same-cycle
    combinational ack/id sample deterministic under cocotb scheduling."""
    await RisingEdge(dut.clk)
    dut.alloc_req.value = 1
    await ReadOnly()
    ack = _ack(dut)
    aid = _alloc_id(dut) if ack else None
    await RisingEdge(dut.clk)
    dut.alloc_req.value = 0
    return ack, aid


async def _free_one(dut, fid: int):
    """Fire a 1-cycle free_req pulse for the given id."""
    await RisingEdge(dut.clk)
    dut.free_req.value = 1
    dut.free_id.value = fid
    await RisingEdge(dut.clk)
    dut.free_req.value = 0
    dut.free_id.value = 0


async def _write_meta(dut, wid: int, meta: int):
    """Fire a 1-cycle write_req pulse with the given id + meta."""
    await RisingEdge(dut.clk)
    dut.write_req.value = 1
    dut.write_id.value = wid
    dut.write_meta.value = meta
    await RisingEdge(dut.clk)
    dut.write_req.value = 0
    dut.write_id.value = 0
    dut.write_meta.value = 0


async def _read_meta_at(dut, rid: int) -> int:
    """Drive read_id, settle one delta cycle, return read_meta (FWFT).

    Drives read_id at the start of a clock cycle and samples the
    combinational read on the same cycle via ReadOnly (matching the
    READ_LATENCY=0 / FWFT mode wiring in the DUT)."""
    await RisingEdge(dut.clk)
    dut.read_id.value = rid
    await ReadOnly()
    val = _read_meta(dut)
    return val


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@cocotb.test()
async def test_reset_initialises_pool(dut):
    """SVA-POOL-5: after reset, free_count == POOL_SIZE and ack is low."""
    await _start_clock(dut)
    await _reset(dut)

    await ReadOnly()
    assert _free_count(dut) == POOL_SIZE, (
        f"free_count={_free_count(dut)} after reset, expected POOL_SIZE={POOL_SIZE}"
    )
    assert _ack(dut) == 0, "alloc_ack must be low out of reset"


@cocotb.test()
async def test_alloc_until_empty(dut):
    """Alloc until free_count==0; the next alloc_req must produce no ack."""
    await _start_clock(dut)
    await _reset(dut)

    allocated: List[int] = []
    for _ in range(POOL_SIZE):
        ack, aid = await _alloc_one(dut)
        assert ack == 1, (
            f"alloc_ack must pulse while pool has credits; got ack=0 with "
            f"free_count={_free_count(dut)}"
        )
        assert aid is not None
        allocated.append(aid)

    # Pool is now empty.
    await ReadOnly()
    assert _free_count(dut) == 0, (
        f"free_count={_free_count(dut)} after {POOL_SIZE} allocs, expected 0"
    )

    # Next alloc must NOT ack (SVA-POOL-3 exhaustion).
    await RisingEdge(dut.clk)
    dut.alloc_req.value = 1
    await ReadOnly()
    assert _ack(dut) == 0, (
        f"alloc_ack must stay low with free_count=0; got ack=1 — SVA-POOL-3 "
        f"exhaustion violated"
    )
    await RisingEdge(dut.clk)
    dut.alloc_req.value = 0

    # Allocated ids must be unique (every id was emitted at most once).
    assert len(set(allocated)) == len(allocated), (
        f"allocated ids contained duplicates: {allocated}"
    )


@cocotb.test()
async def test_lowest_id_first_order(dut):
    """A fresh pool returns ids 0, 1, 2, ... in order (lowest-id-first
    priority encoder contract). This documents the chosen priority direction."""
    await _start_clock(dut)
    await _reset(dut)

    for expected in range(POOL_SIZE):
        ack, aid = await _alloc_one(dut)
        assert ack == 1
        assert aid == expected, (
            f"expected alloc to return id={expected} (lowest-id-first); "
            f"got id={aid}"
        )


@cocotb.test()
async def test_free_returns_id_to_pool(dut):
    """alloc one id, free that id, free_count returns to POOL_SIZE;
    the freed id reappears as the next alloc (because lowest-id-first
    on a fresh-after-free pool picks the just-released slot)."""
    await _start_clock(dut)
    await _reset(dut)

    # Alloc id=0 (lowest-id-first).
    ack, a0 = await _alloc_one(dut)
    assert ack == 1
    assert a0 == 0

    await ReadOnly()
    assert _free_count(dut) == POOL_SIZE - 1

    # Free id=0.
    await _free_one(dut, a0)
    await ReadOnly()
    assert _free_count(dut) == POOL_SIZE, (
        f"free_count={_free_count(dut)} after freeing id=0, expected POOL_SIZE={POOL_SIZE}"
    )

    # Re-alloc — must return id=0 again (it's the lowest-set bit).
    ack2, a1 = await _alloc_one(dut)
    assert ack2 == 1
    assert a1 == 0, f"re-alloc after free(0) returned id={a1}, expected 0"


@cocotb.test()
async def test_double_free_is_noop(dut):
    """SVA-POOL-2: free_req for an already-free id leaves free_count
    unchanged."""
    await _start_clock(dut)
    await _reset(dut)

    # Initially all slots are free.
    await ReadOnly()
    initial = _free_count(dut)
    assert initial == POOL_SIZE

    # Free id=3 (which is already free — double-free).
    await _free_one(dut, 3)
    await ReadOnly()
    assert _free_count(dut) == initial, (
        f"double-free mutated free_count: {_free_count(dut)} != {initial} "
        f"(SVA-POOL-2 silent-reject violated)"
    )


@cocotb.test()
async def test_write_then_read(dut):
    """Write META across multiple slots, read back and verify RAW
    consistency (one cycle after write lands)."""
    await _start_clock(dut)
    await _reset(dut)

    # Generate distinctive payloads. META_WIDTH may be wider than int; mask
    # to the META_WIDTH-bit value.
    mask = (1 << META_WIDTH) - 1
    payloads = {
        i: ((0xA55A0000 | (i << 8) | i) & mask)
        for i in range(POOL_SIZE)
    }

    # Write each slot.
    for slot, payload in payloads.items():
        await _write_meta(dut, slot, payload)

    # Settle one extra cycle so all writes have landed.
    await RisingEdge(dut.clk)

    # Read back and verify.
    for slot, expected in payloads.items():
        got = await _read_meta_at(dut, slot)
        assert got == expected, (
            f"slot {slot}: read_meta=0x{got:x}, expected=0x{expected:x}"
        )


@cocotb.test()
async def test_alloc_free_cycle(dut):
    """Sequential alloc/free over many cycles — conservation holds and
    no slot becomes 'lost' (eventually every alloc'd id can be freed
    back, and free_count is restored)."""
    await _start_clock(dut)
    await _reset(dut)

    rng = random.Random(0xC0DE_F00D)
    held: List[int] = []

    # Random walk of alloc/free over N iterations. Each iteration:
    #   if rng picks 'alloc' AND pool has credits, alloc one id and
    #       record it in `held`;
    #   else if `held` is non-empty, free a random held id.
    N = 64
    for _ in range(N):
        choice = rng.choice(["alloc", "free"])
        if choice == "alloc" and len(held) < POOL_SIZE:
            ack, aid = await _alloc_one(dut)
            if ack:
                assert aid not in held, (
                    f"alloc returned id={aid} which is still held in {held}"
                )
                held.append(aid)
        elif held:
            fid = rng.choice(held)
            held.remove(fid)
            await _free_one(dut, fid)

        # Conservation check at each step.
        await ReadOnly()
        fc = _free_count(dut)
        assert fc + len(held) == POOL_SIZE, (
            f"conservation broken: free_count={fc} + held={len(held)} != "
            f"POOL_SIZE={POOL_SIZE}; held={held}"
        )

    # Drain back to all-free.
    for fid in list(held):
        await _free_one(dut, fid)
    held.clear()

    await ReadOnly()
    assert _free_count(dut) == POOL_SIZE, (
        f"free_count={_free_count(dut)} after drain, expected POOL_SIZE={POOL_SIZE}"
    )

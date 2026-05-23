"""cocotb testbench for sos_arbiter_rr.

@spec docs/concepts/SOS-08-A-CONCEPTS.md §6.3 (per-primitive contract for
    `sos_arbiter_rr`), §5.4 + PCDN-A-007 (one cocotb file per primitive),
    §12 (d) (cocotb gate).

Cited invariants (the testbench exercises behaviours that these invariants
constrain; SVA bound via `sos_arbiter_rr_bind.sv` runs concurrently):

    INV-SOS-A   chart-as-source                      (SOS-07 §6)
    INV-SOS-B   vectors-as-deliverable               (SOS-07 §6)
    INV-SOS-E   explicit AuthorityRelationship       (SOS-07 §6)
    INV-SOS-G   verified-codegen position            (SOS-07 §6)
    INV-SOS-H   vector-to-chart traceability         (SOS-07 §6)
    INV-S-HDL-1 handshake-compatible ports           (SOS-08 §7)
    INV-S-HDL-2 static-allocation discipline         (SOS-08 §7)
    INV-S-HDL-4 cooperative-only at v1               (SOS-08 §7)
    INV-S-HDL-5 vector-to-chart traceability (HDL)   (SOS-08 §7)
    INV-S-HDL-A-1 sync active-high reset             (SOS-08-A §7)
    INV-S-HDL-A-2 handshake associativity            (SOS-08-A §7)
    INV-S-HDL-A-3 vendor-shim byte-identical wrap    (SOS-08-A §7)
    INV-S-HDL-A-4 one-hot internal FSM by default    (SOS-08-A §7)
    INV-S-HDL-A-5 mandatory parameters, no default   (SOS-08-A §7)

Behavioural coverage:
    * test_reset_clears_pointer    -- reset clears state, no grant pending
    * test_idle_no_grants          -- with req = 0, no grants ever fire
    * test_single_requester        -- one requester is granted on the next
                                      cycle after assertion (1-cycle reg latency)
    * test_all_requesters_round_robin -- all bits asserted, round-robin
                                      order over N_REQS cycles
    * test_rotating_request_pattern -- shifting one-hot request walks through
                                      every slot in order

Notes:
    * `grant` is the *registered* output (combinational `grant_next` is
      latched on the clock edge).  Tests time their expectations one cycle
      after a request is asserted.
    * The pointer is internal; tests do not inspect it directly.  The SVA
      bind file asserts the one-hot + advance-once-per-grant claims.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


# ---------------------------------------------------------------------------
# Test bench helpers.
# ---------------------------------------------------------------------------


CLK_PERIOD_NS = 10


def _n_reqs(dut) -> int:
    """Read the N_REQS parameter the DUT was elaborated with."""
    return int(dut.N_REQS.value)


async def _reset(dut, cycles: int = 2) -> None:
    """Drive synchronous active-high reset for `cycles` clock edges."""
    dut.rst.value = 1
    dut.req.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


def _start_clock(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


def _grant_int(dut) -> int:
    """Read `grant` as a Python int (treat X/Z as 0 for one-hot checks)."""
    try:
        return int(dut.grant.value)
    except ValueError:
        # Fallback for X/Z early in simulation.
        return 0


def _one_hot_index(value: int) -> int:
    """Return bit index of a one-hot value; -1 if value == 0."""
    if value == 0:
        return -1
    # Verify one-hot.
    assert value & (value - 1) == 0, f"grant={value:#b} not one-hot"
    return value.bit_length() - 1


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_reset_clears_pointer(dut):
    """After reset, grant is 0 and last_winner_id holds the no-winner sentinel."""
    _start_clock(dut)
    await _reset(dut)
    n = _n_reqs(dut)

    # Settle for a few cycles with req = 0; nothing should fire.
    for _ in range(4):
        await RisingEdge(dut.clk)
        assert _grant_int(dut) == 0, "spurious grant out of reset"

    # last_winner_id sentinel value = N_REQS.
    assert int(dut.last_winner_id.value) == n, (
        f"last_winner_id={int(dut.last_winner_id.value)} expected sentinel {n}"
    )


@cocotb.test()
async def test_idle_no_grants(dut):
    """With req == 0, grant stays 0 for many cycles."""
    _start_clock(dut)
    await _reset(dut)

    for _ in range(32):
        dut.req.value = 0
        await RisingEdge(dut.clk)
        assert _grant_int(dut) == 0, "grant asserted with req = 0"


@cocotb.test()
async def test_single_requester(dut):
    """A single requester is granted the cycle after assertion."""
    _start_clock(dut)
    await _reset(dut)
    n = _n_reqs(dut)

    for which in range(n):
        # Idle in between to flush the registered grant.
        dut.req.value = 0
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)

        # Assert only this requester.
        dut.req.value = 1 << which
        await RisingEdge(dut.clk)
        # 1-cycle register latency: grant fires on the cycle AFTER assertion.
        await RisingEdge(dut.clk)
        observed = _grant_int(dut)
        idx = _one_hot_index(observed)
        assert idx == which, (
            f"single-requester req[{which}] not granted; "
            f"observed grant={observed:#b} (idx={idx})"
        )

        # Drop and observe grant returns to 0.
        dut.req.value = 0
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)
        assert _grant_int(dut) == 0, "grant did not drop after req deasserted"


@cocotb.test()
async def test_all_requesters_round_robin(dut):
    """All requesters asserted -> round-robin order over N_REQS cycles."""
    _start_clock(dut)
    await _reset(dut)
    n = _n_reqs(dut)

    # Assert every bit and hold.
    dut.req.value = (1 << n) - 1

    # Walk forward and collect 2*N_REQS grants so we can verify the pattern
    # cycles cleanly.  The first edge after `req` is driven samples grant_next
    # = first-bit-set, so the first observation is the first grant.
    grants_seen: list[int] = []
    for _ in range(2 * n):
        await RisingEdge(dut.clk)
        observed = _grant_int(dut)
        idx = _one_hot_index(observed)
        assert idx >= 0, f"no grant under full contention (grant={observed:#b})"
        grants_seen.append(idx)

    # Each requester must appear at least once in any N_REQS-wide window.
    first_window = sorted(grants_seen[:n])
    second_window = sorted(grants_seen[n:])
    expected = list(range(n))
    assert first_window == expected, (
        f"round-robin first window incomplete: saw {first_window}, "
        f"want {expected}; raw sequence {grants_seen}"
    )
    assert second_window == expected, (
        f"round-robin second window incomplete: saw {second_window}, "
        f"want {expected}; raw sequence {grants_seen}"
    )

    # The two windows must follow the same rotation order: grants_seen[i+N]
    # equals grants_seen[i].
    for i in range(n):
        assert grants_seen[i] == grants_seen[i + n], (
            f"round-robin order not periodic at i={i}: "
            f"{grants_seen[i]} vs {grants_seen[i + n]} "
            f"(full sequence {grants_seen})"
        )


@cocotb.test()
async def test_rotating_request_pattern(dut):
    """Shift a single-bit request through all positions; expect each granted."""
    _start_clock(dut)
    await _reset(dut)
    n = _n_reqs(dut)

    for shift in range(n):
        # Idle to flush.
        dut.req.value = 0
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)

        dut.req.value = 1 << shift
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)  # 1-cycle register latency
        observed = _grant_int(dut)
        idx = _one_hot_index(observed)
        assert idx == shift, (
            f"rotating pattern shift={shift}: observed grant={observed:#b} "
            f"(idx={idx})"
        )


@cocotb.test()
async def test_last_winner_id_tracks_grants(dut):
    """`last_winner_id` updates to the index of the most recent winner."""
    _start_clock(dut)
    await _reset(dut)
    n = _n_reqs(dut)

    for which in range(n):
        dut.req.value = 0
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)

        dut.req.value = 1 << which
        await RisingEdge(dut.clk)
        # Grant registers on the next edge; last_winner_id updates on the
        # same edge as the grant.
        await RisingEdge(dut.clk)
        observed_grant = _grant_int(dut)
        observed_id    = int(dut.last_winner_id.value)
        # Sanity: grant matches the requested bit.
        assert observed_grant == (1 << which), (
            f"grant mismatch for which={which}: {observed_grant:#b}"
        )
        assert observed_id == which, (
            f"last_winner_id={observed_id} expected {which} "
            f"(N_REQS={n}, grant={observed_grant:#b})"
        )

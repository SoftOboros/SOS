"""cocotb testbench for sos_arbiter_priority.

@spec docs/concepts/SOS-08-A-CONCEPTS.md §6.4 (per-primitive contract for
    `sos_arbiter_priority`), §5.4 + PCDN-A-007 (one cocotb file per primitive),
    §12 (d) (cocotb gate).

Per the 2026-05-23 ratification + impl-wave-1 PCDN amendments (§15):
    - Bare req/grant naming for control primitives (PCDN-A-002).
    - Sync active-high reset (PCDN-A-003).
    - Mandatory generics N_REQS, PRIORITY_BITS, AGING_ENABLE, AGING_THRESHOLD;
      no defaults except GRANT_LATENCY_CYCLES (PCDN-A-arbiter-GRANT_LATENCY_CYCLES,
      named exception extended to this primitive per task brief).
    - GRANT_LATENCY_CYCLES selects registered-grant (=1, canonical) or
      combinational-grant (=0).  The cocotb harness reads
      `SOS_ARBITER_PRIORITY_GRANT_LATENCY` (default "1") and shifts the
      sampling window accordingly.
    - AGING_ENABLE = 1 promotes a starved requester after AGING_THRESHOLD
      cycles; = 0 lets the lowest priority lane starve under continuous
      higher-priority pressure (intentional under strict mode).

Behavioural coverage:

    * test_reset_clears_state             -- reset clears pointer + aging
                                             counters; no grant pending.
    * test_idle_no_grants                 -- req == 0 -> no grants ever fire.
    * test_single_requester_immediate     -- one requester with any priority
                                             is granted on/after assertion.
    * test_higher_priority_wins           -- two requesters at different
                                             priorities: higher wins every cycle.
    * test_same_priority_round_robin      -- two requesters at the same
                                             priority alternate via round-robin.
    * test_aging_disabled_starvation      -- under AGING_ENABLE = 0, the
                                             low-priority requester never wins
                                             while the high one is asserted.
    * test_aging_enabled_promotion        -- under AGING_ENABLE = 1, the
                                             low-priority requester eventually
                                             wins after AGING_THRESHOLD cycles.

Notes:
    * `grant` is the registered output by default (GRANT_LATENCY_CYCLES = 1);
      tests time their expectations one clock edge after a request is asserted.
    * The pointer + aging counters are internal; tests do not inspect them
      directly.  The SVA bind file enforces the structural claims.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


CLK_PERIOD_NS = 10


# ---------------------------------------------------------------------------
# Test-bench helpers.
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be an integer; got {raw!r}") from e


def _grant_latency() -> int:
    v = _env_int("SOS_ARBITER_PRIORITY_GRANT_LATENCY", 1)
    if v not in (0, 1):
        raise ValueError(
            f"SOS_ARBITER_PRIORITY_GRANT_LATENCY must be 0 or 1; got {v}"
        )
    return v


def _n_reqs(dut) -> int:
    return int(dut.N_REQS.value)


def _priority_bits(dut) -> int:
    return int(dut.PRIORITY_BITS.value)


def _aging_enable(dut) -> int:
    return int(dut.AGING_ENABLE.value)


def _aging_threshold(dut) -> int:
    return int(dut.AGING_THRESHOLD.value)


def _pack_priority(values: list[int], priority_bits: int) -> int:
    """Pack a list of per-slot priorities into a flat unsigned int."""
    out = 0
    mask = (1 << priority_bits) - 1
    for i, v in enumerate(values):
        out |= (v & mask) << (i * priority_bits)
    return out


def _start_clock(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


async def _reset(dut, cycles: int = 2) -> None:
    """Drive synchronous active-high reset for `cycles` clock edges."""
    n = _n_reqs(dut)
    pb = _priority_bits(dut)
    dut.rst.value = 1
    dut.req.value = 0
    dut.priority_in.value = _pack_priority([0] * n, pb)
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


def _grant_int(dut) -> int:
    try:
        return int(dut.grant.value)
    except ValueError:
        return 0


def _one_hot_index(value: int) -> int:
    if value == 0:
        return -1
    assert value & (value - 1) == 0, f"grant={value:#b} not one-hot"
    return value.bit_length() - 1


async def _settle_after_assert(dut, latency: int) -> None:
    """Wait the right number of edges for `grant` to be valid after asserting req."""
    await RisingEdge(dut.clk)
    if latency == 1:
        await RisingEdge(dut.clk)


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_reset_clears_state(dut):
    """After reset, grant = 0 and last_winner_id holds the no-winner sentinel."""
    _start_clock(dut)
    await _reset(dut)
    n = _n_reqs(dut)

    for _ in range(4):
        await RisingEdge(dut.clk)
        assert _grant_int(dut) == 0, "spurious grant out of reset"

    assert int(dut.last_winner_id.value) == n, (
        f"last_winner_id={int(dut.last_winner_id.value)} expected sentinel {n}"
    )


@cocotb.test()
async def test_idle_no_grants(dut):
    """With req == 0, grant stays 0 for many cycles."""
    _start_clock(dut)
    await _reset(dut)
    n = _n_reqs(dut)
    pb = _priority_bits(dut)

    # Hold a non-zero priority pattern to prove the arbiter does not grant on
    # priority alone — only req drives grant.
    dut.priority_in.value = _pack_priority(list(range(n)), pb)
    for _ in range(32):
        dut.req.value = 0
        await RisingEdge(dut.clk)
        assert _grant_int(dut) == 0, "grant asserted with req = 0"


@cocotb.test()
async def test_single_requester_immediate(dut):
    """A single requester is granted regardless of its priority value."""
    _start_clock(dut)
    await _reset(dut)
    n = _n_reqs(dut)
    pb = _priority_bits(dut)
    latency = _grant_latency()

    # Set all-zero priority (lowest possible).
    dut.priority_in.value = _pack_priority([0] * n, pb)

    for which in range(n):
        dut.req.value = 0
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)

        dut.req.value = 1 << which
        await _settle_after_assert(dut, latency)
        observed = _grant_int(dut)
        idx = _one_hot_index(observed)
        assert idx == which, (
            f"single-requester req[{which}] not granted; observed={observed:#b} "
            f"latency={latency}"
        )

        dut.req.value = 0
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)
        assert _grant_int(dut) == 0, "grant did not drop after req deasserted"


@cocotb.test()
async def test_higher_priority_wins(dut):
    """Two requesters at different priorities: the higher value wins every cycle."""
    _start_clock(dut)
    await _reset(dut)
    n = _n_reqs(dut)
    pb = _priority_bits(dut)
    latency = _grant_latency()

    if n < 2:
        return  # Spec requires N_REQS >= 2; defensive.

    # Slot 0 gets priority value 1; slot 1 gets the maximum.
    max_prio = (1 << pb) - 1
    prios = [0] * n
    prios[0] = 1
    prios[1] = max_prio
    # Other slots stay at 0 (will not assert).
    dut.priority_in.value = _pack_priority(prios, pb)

    # Assert both slot 0 and slot 1.
    dut.req.value = (1 << 0) | (1 << 1)
    await _settle_after_assert(dut, latency)

    # Sample several cycles; slot 1 must win every cycle (when aging is
    # disabled, OR for the first AGING_THRESHOLD cycles when aging is enabled).
    aging = _aging_enable(dut)
    age_thresh = _aging_threshold(dut)
    # Stay strictly under AGING_THRESHOLD so slot 0 cannot promote.  If aging
    # is disabled we just check a fixed sample window.
    window = age_thresh - 1 if aging == 1 else 16
    if window < 1:
        window = 1
    for _ in range(window):
        observed = _grant_int(dut)
        idx = _one_hot_index(observed)
        assert idx == 1, (
            f"higher-priority slot did not win (saw grant={observed:#b}, "
            f"aging={aging}, prios={prios})"
        )
        await RisingEdge(dut.clk)


@cocotb.test()
async def test_same_priority_round_robin(dut):
    """Two requesters at the same priority alternate via the shared RR pointer."""
    _start_clock(dut)
    await _reset(dut)
    n = _n_reqs(dut)
    pb = _priority_bits(dut)
    latency = _grant_latency()

    if n < 2:
        return

    # Both slots at the same (non-zero) priority.
    same = (1 << pb) - 1
    prios = [0] * n
    prios[0] = same
    prios[1] = same
    dut.priority_in.value = _pack_priority(prios, pb)

    dut.req.value = (1 << 0) | (1 << 1)
    await _settle_after_assert(dut, latency)

    # Collect 4 cycles of grants.  Under continuous-contention the shared RR
    # pointer alternates between slots 0 and 1; the exact starting slot
    # depends on the pointer reset state (bit 0).
    seen: list[int] = []
    for _ in range(4):
        observed = _grant_int(dut)
        idx = _one_hot_index(observed)
        assert idx in (0, 1), (
            f"unexpected winner in same-priority pair: grant={observed:#b}"
        )
        seen.append(idx)
        await RisingEdge(dut.clk)

    # Both slots must appear in the 4-cycle window (fairness over the lane).
    assert 0 in seen, f"slot 0 never won under same-priority contention: {seen}"
    assert 1 in seen, f"slot 1 never won under same-priority contention: {seen}"


@cocotb.test()
async def test_aging_disabled_starvation(dut):
    """AGING_ENABLE = 0: the low-priority requester never wins while high holds."""
    _start_clock(dut)
    await _reset(dut)
    n = _n_reqs(dut)
    pb = _priority_bits(dut)
    latency = _grant_latency()
    aging = _aging_enable(dut)

    if aging != 0:
        # Skip: this test exercises the strict-priority path.
        dut._log.info(
            "Skipping test_aging_disabled_starvation: AGING_ENABLE=%d", aging
        )
        return
    if n < 2:
        return

    max_prio = (1 << pb) - 1
    prios = [0] * n
    prios[0] = 1
    prios[1] = max_prio
    dut.priority_in.value = _pack_priority(prios, pb)

    dut.req.value = (1 << 0) | (1 << 1)
    await _settle_after_assert(dut, latency)

    # Run for plenty of cycles; slot 0 must NEVER win under strict priority.
    for _ in range(64):
        observed = _grant_int(dut)
        idx = _one_hot_index(observed)
        assert idx == 1, (
            f"strict mode: low-priority slot 0 promoted spuriously "
            f"(grant={observed:#b}, idx={idx})"
        )
        await RisingEdge(dut.clk)


@cocotb.test()
async def test_aging_enabled_promotion(dut):
    """AGING_ENABLE = 1: the low-priority requester eventually wins after threshold."""
    _start_clock(dut)
    await _reset(dut)
    n = _n_reqs(dut)
    pb = _priority_bits(dut)
    latency = _grant_latency()
    aging = _aging_enable(dut)
    age_thresh = _aging_threshold(dut)

    if aging != 1:
        dut._log.info(
            "Skipping test_aging_enabled_promotion: AGING_ENABLE=%d", aging
        )
        return
    if n < 2:
        return

    max_prio = (1 << pb) - 1
    prios = [0] * n
    prios[0] = 1
    prios[1] = max_prio
    dut.priority_in.value = _pack_priority(prios, pb)

    dut.req.value = (1 << 0) | (1 << 1)
    await _settle_after_assert(dut, latency)

    # Within AGING_THRESHOLD + N_REQS + GRANT_LATENCY_CYCLES cycles, slot 0
    # MUST be granted at least once.  Track whether we saw slot 0 win.
    bound = age_thresh + n + latency + 2
    saw_slot_0 = False
    for _ in range(bound):
        observed = _grant_int(dut)
        idx = _one_hot_index(observed)
        if idx == 0:
            saw_slot_0 = True
            break
        await RisingEdge(dut.clk)

    assert saw_slot_0, (
        f"aging mode: low-priority slot 0 never promoted within "
        f"AGING_THRESHOLD + N_REQS + GRANT_LATENCY_CYCLES = "
        f"{age_thresh}+{n}+{latency} cycles"
    )

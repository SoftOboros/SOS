"""cocotb testbench for sos_tick_gen.

@spec docs/concepts/SOS-08-A-CONCEPTS.md §6.8 (per-primitive contract for
    `sos_tick_gen`), §5.4 + PCDN-A-007 (one cocotb file per primitive),
    §12 (d) (cocotb gate).

The DUT is a free-running modulo-PERIOD_CYCLES counter that emits a 1-cycle
combinational `tick` pulse when `counter == PERIOD_CYCLES - 1` AND
`enable == 1`.  Reset restores `counter` to `INITIAL_PHASE`.  Dropping
`enable` mid-period FREEZES the counter (it does NOT reset to 0); reasserting
`enable` resumes from the held value.

Test runner parameter overrides:

    SOS_TICK_GEN_PERIOD_CYCLES (default "8")  -> DUT PERIOD_CYCLES generic
    SOS_TICK_GEN_INITIAL_PHASE (default "0")  -> DUT INITIAL_PHASE generic

The test reads them via os.environ to assemble its expectations; the runner
is responsible for elaborating the DUT with matching generic overrides.
Coverage matrix exercised across at least:

    * PERIOD_CYCLES=8, INITIAL_PHASE=0  (canonical reset-from-zero)
    * PERIOD_CYCLES=8, INITIAL_PHASE=3  (phase-staggered cold start)
    * PERIOD_CYCLES=5, INITIAL_PHASE=0  (odd period; tick spacing != power of 2)

Cited invariants (testbench exercises behaviours these invariants constrain;
SVA bound via `sos_tick_gen_bind.sv` runs concurrently):

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

    * test_reset_restores_phase     -- counter == INITIAL_PHASE post-reset
    * test_steady_state_cadence     -- tick fires every PERIOD_CYCLES cycles
                                       under continuous enable
    * test_tick_is_one_cycle_pulse  -- every tick is observed for exactly 1 cycle
    * test_initial_phase_offsets    -- with INITIAL_PHASE=k, first tick fires
                                       (PERIOD_CYCLES - 1 - k) cycles after
                                       reset deasserts
    * test_enable_low_pauses        -- dropping enable mid-period freezes the
                                       counter; reasserting resumes from the
                                       held value (no phase loss)
    * test_enable_low_forces_tick_low
                                    -- tick stays low across the entire
                                       disabled window, regardless of where
                                       the counter is parked
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly


CLK_PERIOD_NS = 10


# ---------------------------------------------------------------------------
# Parameter readers + helpers.
# ---------------------------------------------------------------------------


def _period_cycles() -> int:
    raw = os.environ.get("SOS_TICK_GEN_PERIOD_CYCLES", "8")
    v = int(raw)
    if v < 2:
        raise ValueError(
            f"SOS_TICK_GEN_PERIOD_CYCLES must be >= 2; got {v}"
        )
    return v


def _initial_phase() -> int:
    raw = os.environ.get("SOS_TICK_GEN_INITIAL_PHASE", "0")
    v = int(raw)
    p = _period_cycles()
    if not (0 <= v < p):
        raise ValueError(
            f"SOS_TICK_GEN_INITIAL_PHASE must satisfy 0 <= INITIAL_PHASE < "
            f"PERIOD_CYCLES={p}; got {v}"
        )
    return v


def _start_clock(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


async def _reset(dut, cycles: int = 2) -> None:
    """Drive synchronous active-high reset for `cycles` clock edges."""
    dut.rst.value = 1
    dut.enable.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    # Settle one cycle so the first post-reset edge is observed by the test.
    await RisingEdge(dut.clk)


def _tick(dut) -> int:
    try:
        return int(dut.tick.value)
    except ValueError:
        return 0


def _counter(dut) -> int:
    try:
        return int(dut.counter.value)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_reset_restores_phase(dut):
    """After reset, counter == INITIAL_PHASE and tick == 0."""
    initial = _initial_phase()
    _start_clock(dut)

    # Drive reset, then sample the first non-reset edge.
    dut.rst.value = 1
    dut.enable.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    # Settle into the first !rst cycle.
    await RisingEdge(dut.clk)

    assert _counter(dut) == initial, (
        f"counter={_counter(dut)} expected INITIAL_PHASE={initial}"
    )
    assert _tick(dut) == 0, "tick asserted immediately after reset"


@cocotb.test()
async def test_steady_state_cadence(dut):
    """Under continuous enable=1, ticks fire every PERIOD_CYCLES cycles."""
    period = _period_cycles()
    initial = _initial_phase()
    _start_clock(dut)
    await _reset(dut)

    dut.enable.value = 1

    # Observe at least three full periods.  Track every cycle the tick output
    # is high.  Stage-zero check: first tick fires at
    # (PERIOD_CYCLES - 1 - INITIAL_PHASE) cycles after the first !rst cycle.
    cycles_to_first_tick = (period - 1 - initial) % period
    # Walk forward, sampling at each rising edge.
    tick_cycles: list[int] = []
    # Observe enough cycles for 3 full periods past the first tick.
    horizon = cycles_to_first_tick + 3 * period + 1
    for i in range(horizon):
        await RisingEdge(dut.clk)
        if _tick(dut) == 1:
            tick_cycles.append(i)

    assert len(tick_cycles) >= 3, (
        f"expected >=3 ticks over {horizon} cycles; saw {len(tick_cycles)} "
        f"(period={period} initial={initial}) tick_cycles={tick_cycles}"
    )

    # Inter-tick spacing must be exactly PERIOD_CYCLES.
    for i in range(1, len(tick_cycles)):
        delta = tick_cycles[i] - tick_cycles[i - 1]
        assert delta == period, (
            f"tick spacing {delta} != PERIOD_CYCLES={period} "
            f"(tick_cycles={tick_cycles})"
        )

    # First tick offset matches the expected initial-phase math.
    assert tick_cycles[0] == cycles_to_first_tick, (
        f"first tick at cycle {tick_cycles[0]}; expected "
        f"{cycles_to_first_tick} (period={period} initial={initial})"
    )


@cocotb.test()
async def test_tick_is_one_cycle_pulse(dut):
    """No tick observation is followed by tick on the next cycle."""
    period = _period_cycles()
    _start_clock(dut)
    await _reset(dut)

    dut.enable.value = 1

    # Observe ~3 periods; sample tick on every edge.
    prev_tick = 0
    for _ in range(3 * period + 2):
        await RisingEdge(dut.clk)
        cur_tick = _tick(dut)
        if prev_tick == 1:
            assert cur_tick == 0, (
                "tick held high for two consecutive cycles"
            )
        prev_tick = cur_tick


@cocotb.test()
async def test_initial_phase_offsets(dut):
    """First tick lands (PERIOD_CYCLES - 1 - INITIAL_PHASE) cycles post-reset."""
    period = _period_cycles()
    initial = _initial_phase()
    expected_offset = (period - 1 - initial) % period

    _start_clock(dut)
    await _reset(dut)
    dut.enable.value = 1

    # Walk forward and record the first cycle index at which tick fires.
    fired_at = None
    for i in range(2 * period + 2):
        await RisingEdge(dut.clk)
        if _tick(dut) == 1:
            fired_at = i
            break

    assert fired_at is not None, (
        f"no tick observed within 2*PERIOD_CYCLES; period={period} "
        f"initial={initial}"
    )
    assert fired_at == expected_offset, (
        f"first tick at cycle {fired_at}; expected {expected_offset} "
        f"(period={period} initial={initial})"
    )


@cocotb.test()
async def test_enable_low_pauses(dut):
    """Dropping enable mid-period freezes the counter; resume preserves phase."""
    period = _period_cycles()
    _start_clock(dut)
    await _reset(dut)
    dut.enable.value = 1

    # Run a few cycles to push the counter away from INITIAL_PHASE.
    for _ in range(max(1, period // 2)):
        await RisingEdge(dut.clk)

    # Snapshot the counter, then drop enable.
    paused_at = _counter(dut)
    dut.enable.value = 0

    # Hold enable=0 for a couple of period-widths; counter MUST hold.
    for _ in range(2 * period):
        await RisingEdge(dut.clk)
        assert _counter(dut) == paused_at, (
            f"counter advanced while enable=0: paused_at={paused_at} "
            f"now={_counter(dut)}"
        )
        assert _tick(dut) == 0, "tick fired while enable=0"

    # Reassert enable; counter should resume from `paused_at` and advance.
    dut.enable.value = 1
    await RisingEdge(dut.clk)
    # On the first re-enabled edge, the counter takes the next value.
    expected_next = paused_at + 1 if paused_at != period - 1 else 0
    observed = _counter(dut)
    assert observed == expected_next, (
        f"counter did not resume from paused_at={paused_at}: "
        f"expected {expected_next}, got {observed}"
    )


@cocotb.test()
async def test_enable_low_forces_tick_low(dut):
    """Even with counter parked at PERIOD_CYCLES-1, enable=0 forces tick=0."""
    period = _period_cycles()
    _start_clock(dut)
    await _reset(dut)
    dut.enable.value = 1

    # Walk forward until the counter reaches PERIOD_CYCLES - 2; on the next
    # edge it transitions to PERIOD_CYCLES - 1 (the terminal value).  We
    # then drop enable on that edge so the counter is parked at the
    # terminal value with tick gated low.
    safety = 0
    while _counter(dut) != period - 2 and safety < 4 * period:
        await RisingEdge(dut.clk)
        safety += 1
    assert _counter(dut) == period - 2, (
        f"failed to reach counter=PERIOD_CYCLES-2={period - 2}; "
        f"got {_counter(dut)} after {safety} cycles"
    )

    # Drop enable; on the next rising edge counter holds at PERIOD_CYCLES-1
    # would normally have wrapped but since enable=0 it stays at
    # PERIOD_CYCLES-2.  Wait — re-read the spec semantics: on this edge
    # with enable=1, counter would advance from PERIOD_CYCLES-2 to
    # PERIOD_CYCLES-1, and tick would fire combinationally on the SAME
    # edge that counter becomes PERIOD_CYCLES-1.  So we must hold enable=1
    # for one more cycle to PARK the counter at the terminal value, THEN
    # drop enable.
    await RisingEdge(dut.clk)  # counter transitions PERIOD_CYCLES-2 -> PERIOD_CYCLES-1
    # The just-completed edge produced tick=1 (combinational on
    # at_terminal).  Now drop enable BEFORE the next edge so the counter
    # is held; tick goes low immediately (combinational on enable).
    dut.enable.value = 0
    # Sample at the next read-only window: tick must be 0 even though
    # counter == PERIOD_CYCLES - 1.
    await ReadOnly()
    assert _tick(dut) == 0, (
        f"tick stayed high after enable dropped; counter={_counter(dut)}"
    )

    # Run a few cycles with enable=0; tick must stay low and counter must
    # not advance past PERIOD_CYCLES - 1.
    for _ in range(2 * period):
        await RisingEdge(dut.clk)
        # The counter wrap (PERIOD_CYCLES-1 -> 0) is gated by enable too, so
        # the counter is parked at PERIOD_CYCLES-1 for the entire pause.
        assert _counter(dut) == period - 1, (
            f"counter advanced while enable=0 from terminal: now={_counter(dut)}"
        )
        assert _tick(dut) == 0, "tick fired during enable=0 hold"

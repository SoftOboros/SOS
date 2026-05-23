"""cocotb testbench for sos_rate_divider.

@spec docs/concepts/SOS-08-A-CONCEPTS.md §6.11 (per-primitive contract for
    ``sos_rate_divider``), §5.4 + PCDN-A-007 (one cocotb file per primitive),
    §12 (d) (cocotb gate).  Per the 2026-05-23 ratification and continuation-
    amendment PCDN walkthrough.

The DUT is a tick-driven divider: the internal counter advances ONLY on
cycles where ``tick_in`` is asserted, not on every clock edge.  ``tick_out``
is combinational on ``(tick_in, counter)`` -- it pulses on the same edge as
the qualifying ``tick_in`` arrives.

Generics:
    DIVISOR         -- mandatory, >= 1.  DIVISOR = 0 is forbidden.
    INITIAL_COUNTER -- mandatory, 0 <= INITIAL_COUNTER < DIVISOR.

The cocotb harness reads two env vars to align with the elaborator:
    SOS_RATE_DIVIDER_DIVISOR         (default "10")
    SOS_RATE_DIVIDER_INITIAL_COUNTER (default "0")

The test runner is responsible for setting the env vars consistently with
the DUT parameter overrides.

Cited invariants (the testbench exercises behaviours that these invariants
constrain; SVA bound via ``sos_rate_divider_bind.sv`` runs concurrently):

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
    INV-S-HDL-A-4 one-hot internal FSM by default    (SOS-08-A §7; N/A counter)
    INV-S-HDL-A-5 mandatory parameters, no default   (SOS-08-A §7)

Behavioural coverage:
    * test_reset_clears_to_initial   -- post-reset counter equals INITIAL_COUNTER
    * test_idle_no_tick_out          -- with tick_in = 0, counter holds, no
                                        tick_out fires, even for many cycles
    * test_divisor_2_alternates      -- DIVISOR=2 fires every other tick_in
                                        (special-case env override)
    * test_divisor_passthrough       -- DIVISOR=1 -> tick_out tracks tick_in
                                        (special-case env override)
    * test_default_divisor_period    -- under the parameterised DIVISOR, the
                                        Nth tick_in pulse fires tick_out and
                                        counter rolls to 0
    * test_initial_counter_offset    -- when INITIAL_COUNTER != 0, the first
                                        tick_out fires (DIVISOR - INITIAL_COUNTER)
                                        tick_in pulses later, and subsequent
                                        intervals are DIVISOR pulses each
    * test_intermittent_tick_in      -- spacing between tick_in pulses does
                                        not affect tick_out count (only the
                                        number of asserted tick_in cycles)

Notes:
    * ``tick_out`` is combinational on ``tick_in``; tests sample it on the
      same edge they drive ``tick_in`` high.  Drive ``tick_in`` before the
      RisingEdge, then sample ``tick_out`` immediately after the edge.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


# ---------------------------------------------------------------------------
# Test bench helpers.
# ---------------------------------------------------------------------------


CLK_PERIOD_NS = 10


def _divisor() -> int:
    """Return the configured DIVISOR (>= 1) from the env var."""
    raw = os.environ.get("SOS_RATE_DIVIDER_DIVISOR", "10")
    try:
        v = int(raw)
    except ValueError as e:
        raise ValueError(
            f"SOS_RATE_DIVIDER_DIVISOR must be a positive int; got {raw!r}"
        ) from e
    if v < 1:
        raise ValueError(
            f"SOS_RATE_DIVIDER_DIVISOR must be >= 1; got {v}"
        )
    return v


def _initial_counter() -> int:
    """Return the configured INITIAL_COUNTER (0 <= ic < DIVISOR) from the env var."""
    raw = os.environ.get("SOS_RATE_DIVIDER_INITIAL_COUNTER", "0")
    try:
        v = int(raw)
    except ValueError as e:
        raise ValueError(
            f"SOS_RATE_DIVIDER_INITIAL_COUNTER must be a non-negative int; got {raw!r}"
        ) from e
    d = _divisor()
    if not (0 <= v < d):
        raise ValueError(
            f"SOS_RATE_DIVIDER_INITIAL_COUNTER must satisfy 0 <= ic < DIVISOR; "
            f"got ic={v} DIVISOR={d}"
        )
    return v


async def _reset(dut, cycles: int = 2) -> None:
    """Drive synchronous active-high reset for `cycles` clock edges."""
    dut.rst.value = 1
    dut.tick_in.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


def _start_clock(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


def _tick_out_int(dut) -> int:
    """Read tick_out as Python int (X/Z -> 0)."""
    try:
        return int(dut.tick_out.value)
    except ValueError:
        return 0


def _counter_int(dut) -> int:
    """Read counter as Python int (X/Z -> 0)."""
    try:
        return int(dut.counter.value)
    except ValueError:
        return 0


async def _pulse_tick(dut) -> int:
    """Drive a single tick_in pulse aligned with the next clock edge.

    Returns the value of ``tick_out`` observed on the same cycle.
    """
    dut.tick_in.value = 1
    await RisingEdge(dut.clk)
    observed = _tick_out_int(dut)
    dut.tick_in.value = 0
    return observed


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_reset_clears_to_initial(dut):
    """After reset, counter == INITIAL_COUNTER and tick_out is 0."""
    _start_clock(dut)
    ic = _initial_counter()
    await _reset(dut)

    assert _counter_int(dut) == ic, (
        f"post-reset counter={_counter_int(dut)} expected INITIAL_COUNTER={ic}"
    )
    assert _tick_out_int(dut) == 0, "tick_out asserted out of reset"


@cocotb.test()
async def test_idle_no_tick_out(dut):
    """With tick_in == 0 for many cycles, counter holds, tick_out stays 0."""
    _start_clock(dut)
    ic = _initial_counter()
    await _reset(dut)

    for _ in range(32):
        dut.tick_in.value = 0
        await RisingEdge(dut.clk)
        assert _tick_out_int(dut) == 0, "tick_out asserted with tick_in = 0"
        assert _counter_int(dut) == ic, (
            f"counter drifted while idle: {_counter_int(dut)} != {ic}"
        )


@cocotb.test()
async def test_default_divisor_period(dut):
    """Under the parameterised DIVISOR + INITIAL_COUNTER, verify the period.

    The first ``tick_out`` should fire on the ``(DIVISOR - INITIAL_COUNTER)``-th
    ``tick_in`` pulse.  Subsequent intervals are exactly DIVISOR pulses.
    """
    _start_clock(dut)
    d = _divisor()
    ic = _initial_counter()
    await _reset(dut)

    first_window = d - ic  # number of tick_in pulses until the first tick_out

    # First window.
    for i in range(1, first_window + 1):
        observed = await _pulse_tick(dut)
        if i == first_window:
            assert observed == 1, (
                f"first tick_out expected on tick_in #{first_window}; "
                f"observed tick_out={observed} on pulse #{i} "
                f"(DIVISOR={d}, INITIAL_COUNTER={ic})"
            )
            # After firing, counter must reload to 0.
            assert _counter_int(dut) == 0, (
                f"counter did not reload to 0 after tick_out; got {_counter_int(dut)}"
            )
        else:
            assert observed == 0, (
                f"premature tick_out on pulse #{i}/{first_window} "
                f"(DIVISOR={d}, INITIAL_COUNTER={ic})"
            )

    # Two further windows of exactly DIVISOR pulses each.
    for window in range(2):
        for i in range(1, d + 1):
            observed = await _pulse_tick(dut)
            expected = 1 if i == d else 0
            assert observed == expected, (
                f"window {window} pulse {i}/{d}: tick_out expected {expected}, "
                f"observed {observed} (DIVISOR={d}, INITIAL_COUNTER={ic})"
            )
        assert _counter_int(dut) == 0, (
            f"counter not zero at end of window {window}; got {_counter_int(dut)}"
        )


@cocotb.test()
async def test_intermittent_tick_in(dut):
    """Idle cycles between tick_in pulses don't change the divide ratio."""
    _start_clock(dut)
    d = _divisor()
    ic = _initial_counter()
    await _reset(dut)

    # Mix-in: 2 idle cycles between every tick_in.  Count tick_in pulses
    # only; tick_out should fire on the (d-ic)-th tick_in.
    first_window = d - ic
    tick_in_count = 0
    saw_first_tick_out = False

    # Run long enough to see at least the first tick_out under intermittent drive.
    cycles_budget = (first_window + 1) * 4
    for _ in range(cycles_budget):
        # Two idle cycles.
        dut.tick_in.value = 0
        await RisingEdge(dut.clk)
        assert _tick_out_int(dut) == 0
        await RisingEdge(dut.clk)
        assert _tick_out_int(dut) == 0

        # One tick_in pulse.
        observed = await _pulse_tick(dut)
        tick_in_count += 1
        if observed == 1:
            saw_first_tick_out = True
            assert tick_in_count == first_window, (
                f"first tick_out expected at tick_in #{first_window}; "
                f"observed at #{tick_in_count}"
            )
            break

    assert saw_first_tick_out, (
        f"never observed tick_out within budget; tick_in_count={tick_in_count} "
        f"first_window={first_window}"
    )


# ---------------------------------------------------------------------------
# Special-cased tests: run only when the runner has set DIVISOR to a
# matching value.  This lets a single test file cover the DIVISOR=1
# passthrough and DIVISOR=2 alternates without spawning a separate harness.
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_divisor_passthrough(dut):
    """When DIVISOR=1, tick_out tracks tick_in every cycle (passthrough).

    Skipped (treated as no-op) when DIVISOR != 1.
    """
    _start_clock(dut)
    d = _divisor()
    if d != 1:
        dut._log.info("test_divisor_passthrough: skipped (DIVISOR=%d, want 1)", d)
        return

    await _reset(dut)

    # 16 cycles of a 1-0-1-0-1-1-0 pattern; expect tick_out == tick_in each cycle.
    pattern = [1, 0, 1, 0, 1, 1, 0, 1, 1, 1, 0, 0, 1, 0, 1, 1]
    for cyc, tin in enumerate(pattern):
        dut.tick_in.value = tin
        await RisingEdge(dut.clk)
        observed = _tick_out_int(dut)
        assert observed == tin, (
            f"DIVISOR=1 passthrough violated at cycle {cyc}: tick_in={tin} tick_out={observed}"
        )
    dut.tick_in.value = 0


@cocotb.test()
async def test_divisor_2_alternates(dut):
    """When DIVISOR=2 and INITIAL_COUNTER=0, tick_out fires every other tick_in.

    Skipped when DIVISOR != 2.
    """
    _start_clock(dut)
    d = _divisor()
    if d != 2:
        dut._log.info("test_divisor_2_alternates: skipped (DIVISOR=%d, want 2)", d)
        return
    ic = _initial_counter()
    if ic != 0:
        dut._log.info("test_divisor_2_alternates: skipped (INITIAL_COUNTER=%d, want 0)", ic)
        return

    await _reset(dut)

    # 8 contiguous tick_in pulses -> expect tick_out on pulses 2, 4, 6, 8.
    expected = [0, 1, 0, 1, 0, 1, 0, 1]
    for i, want in enumerate(expected, start=1):
        observed = await _pulse_tick(dut)
        assert observed == want, (
            f"DIVISOR=2 alternates: pulse {i} expected tick_out={want}, observed {observed}"
        )


@cocotb.test()
async def test_initial_counter_offset(dut):
    """When INITIAL_COUNTER != 0, the first tick_out fires earlier.

    Specifically, on the ``(DIVISOR - INITIAL_COUNTER)``-th tick_in.  Subsequent
    intervals revert to DIVISOR pulses.  Skipped when INITIAL_COUNTER == 0.
    """
    _start_clock(dut)
    d = _divisor()
    ic = _initial_counter()
    if ic == 0:
        dut._log.info("test_initial_counter_offset: skipped (INITIAL_COUNTER=0)")
        return

    await _reset(dut)

    first_window = d - ic
    # Drive first_window-1 pulses; no tick_out yet.
    for i in range(1, first_window):
        observed = await _pulse_tick(dut)
        assert observed == 0, (
            f"INITIAL_COUNTER={ic}, DIVISOR={d}: premature tick_out at pulse {i}/{first_window}"
        )
    # The (first_window)-th pulse fires tick_out.
    observed = await _pulse_tick(dut)
    assert observed == 1, (
        f"INITIAL_COUNTER={ic}, DIVISOR={d}: first tick_out expected at pulse {first_window}"
    )
    assert _counter_int(dut) == 0, (
        f"counter did not reload to 0 after first tick_out; got {_counter_int(dut)}"
    )

    # Next full window: exactly DIVISOR pulses to the next tick_out.
    for i in range(1, d + 1):
        observed = await _pulse_tick(dut)
        want = 1 if i == d else 0
        assert observed == want, (
            f"second window pulse {i}/{d}: expected tick_out={want}, observed {observed}"
        )

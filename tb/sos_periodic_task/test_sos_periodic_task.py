"""cocotb testbench for sos_periodic_task.

@spec docs/concepts/SOS-08-B-CONCEPTS.md §6.4 (per-service contract for
    ``sos_periodic_task``), §5.4 (service-level SVA binding default), §12
    (acceptance checklist; cocotb gate).  Per the 2026-05-23 ratification.

The DUT is an L1 service that wraps an inner ``sos_rate_divider`` and adds
a small one-hot FSM (ST_IDLE / ST_RUNNING / ST_OVERRUN) plus a registered
``task_enable`` pulse and a sticky ``overrun_fault`` register.

Behavioural model under verification:

    * ``base_tick`` is a 1-cycle pulse from a system-level ``sos_tick_gen``
      (NOT instantiated here -- the testbench drives ``base_tick`` directly
      per PCDN-SOS-08-B-004: the global tick generator lives outside the
      service).
    * The inner ``sos_rate_divider`` divides ``base_tick`` by ``DIVISOR``,
      phase offset ``INITIAL_COUNTER``, producing internal ``task_tick``.
    * ``task_enable`` is the registered shadow of ``task_tick`` -- it
      pulses one cycle AFTER each ``task_tick``.
    * ``task_busy`` is driven by the worker (the testbench plays this
      role).  If it remains high on the cycle of a subsequent task_tick,
      the FSM transitions to ST_OVERRUN and latches ``overrun_fault`` on
      the next cycle.  ``overrun_fault`` is sticky; only synchronous reset
      clears it.

Generics:
    DIVISOR         -- mandatory, >= 1 (forbidden = 0 per L0 sos_rate_divider).
    INITIAL_COUNTER -- mandatory, 0 <= INITIAL_COUNTER < DIVISOR.

The cocotb harness reads two env vars to align with the elaborator:

    SOS_PERIODIC_TASK_DIVISOR         (default "10")
    SOS_PERIODIC_TASK_INITIAL_COUNTER (default "0")

Behavioural coverage:

    * test_reset_clears_outputs       -- post-reset task_enable=0,
                                         overrun_fault=0, divider_counter
                                         == INITIAL_COUNTER.
    * test_normal_operation           -- worker completes before next tick:
                                         task_enable pulses fire one cycle
                                         after each DIVISOR-th base_tick,
                                         overrun_fault never asserts.
    * test_overrun_detected           -- worker holds task_busy past the
                                         next tick: overrun_fault asserts
                                         one cycle after the missed tick.
    * test_overrun_is_sticky          -- after overrun_fault asserts, it
                                         remains high even when task_busy
                                         is lowered and subsequent
                                         on-time ticks occur.
    * test_reset_clears_overrun       -- a fresh synchronous reset returns
                                         the FSM to ST_IDLE and clears
                                         overrun_fault.
    * test_task_enable_is_pulse       -- task_enable is exactly 1 cycle
                                         wide (sanity check for SVA-PT-2
                                         pulse-shape corollary).

Cited invariants (the testbench exercises behaviours that these
invariants constrain; service-level SVA bound via
``sos_periodic_task_bind.sv`` runs concurrently):

    INV-SOS-A   chart-as-source                      (SOS-07 §6)
    INV-SOS-B   vectors-as-deliverable               (SOS-07 §6)
    INV-SOS-E   explicit AuthorityRelationship       (SOS-07 §6)
    INV-SOS-G   verified-codegen position            (SOS-07 §6)
    INV-SOS-H   vector-to-chart traceability         (SOS-07 §6)
    INV-S-HDL-1 handshake-compatible ports           (SOS-08 §7; pulse form)
    INV-S-HDL-2 static-allocation discipline         (SOS-08 §7)
    INV-S-HDL-4 cooperative-only at v1               (SOS-08 §7)
    INV-S-HDL-5 vector-to-chart traceability (HDL)   (SOS-08 §7)
    INV-S-HDL-B-1 vocabulary mirror discipline       (SOS-08-B §7)
    INV-S-HDL-B-2 L0 non-modification                (SOS-08-B §7)
    INV-S-HDL-B-3 service-level SVA on every L1      (SOS-08-B §7)
    INV-S-HDL-B-5 chart-vocabulary failure rendering (SOS-08-B §7)

Per INV-S-HDL-B-5, failure messages render in chart vocabulary -- they
cite the L1 verb (``task_enable``, ``overrun_fault``) and the SVA
property ID, not raw RTL signal names alone.
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
    raw = os.environ.get("SOS_PERIODIC_TASK_DIVISOR", "10")
    try:
        v = int(raw)
    except ValueError as e:
        raise ValueError(
            f"SOS_PERIODIC_TASK_DIVISOR must be a positive int; got {raw!r}"
        ) from e
    if v < 1:
        raise ValueError(
            f"SOS_PERIODIC_TASK_DIVISOR must be >= 1; got {v}"
        )
    return v


def _initial_counter() -> int:
    """Return the configured INITIAL_COUNTER (0 <= ic < DIVISOR) from the env var."""
    raw = os.environ.get("SOS_PERIODIC_TASK_INITIAL_COUNTER", "0")
    try:
        v = int(raw)
    except ValueError as e:
        raise ValueError(
            f"SOS_PERIODIC_TASK_INITIAL_COUNTER must be a non-negative int; "
            f"got {raw!r}"
        ) from e
    d = _divisor()
    if not (0 <= v < d):
        raise ValueError(
            f"SOS_PERIODIC_TASK_INITIAL_COUNTER must satisfy 0 <= ic < DIVISOR; "
            f"got ic={v} DIVISOR={d}"
        )
    return v


def _start_clock(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


def _read_int(sig) -> int:
    """Read a signal as Python int (X/Z -> 0).

    Per INV-S-HDL-B-5, callers MUST render failures in chart vocabulary
    using the L1 verb names (``task_enable`` / ``overrun_fault``) -- this
    helper is signal-name-agnostic and is only a value-extraction tool.
    """
    try:
        return int(sig.value)
    except ValueError:
        return 0


async def _reset(dut, cycles: int = 2) -> None:
    """Drive synchronous active-high reset for `cycles` clock edges."""
    dut.rst.value = 1
    dut.base_tick.value = 0
    dut.task_busy.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def _pulse_base_tick(dut) -> None:
    """Drive a single 1-cycle base_tick pulse aligned with the next clock edge."""
    dut.base_tick.value = 1
    await RisingEdge(dut.clk)
    dut.base_tick.value = 0


async def _step_idle(dut, cycles: int = 1) -> None:
    """Step `cycles` clock cycles with base_tick = 0 (and existing task_busy)."""
    dut.base_tick.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_reset_clears_outputs(dut):
    """After reset, task_enable=0, overrun_fault=0, divider_counter=INITIAL_COUNTER."""
    _start_clock(dut)
    ic = _initial_counter()
    await _reset(dut)

    enable_v = _read_int(dut.task_enable)
    overrun_v = _read_int(dut.overrun_fault)
    counter_v = _read_int(dut.divider_counter)

    assert enable_v == 0, (
        f"L1 sos_periodic_task: task_enable={enable_v} after reset (expected 0) "
        f"-- violates SVA-PT-2 quiescence"
    )
    assert overrun_v == 0, (
        f"L1 sos_periodic_task: overrun_fault={overrun_v} after reset (expected 0) "
        f"-- violates SVA-PT-3 reset clears overrun"
    )
    assert counter_v == ic, (
        f"L1 sos_periodic_task: divider_counter={counter_v} after reset "
        f"(expected INITIAL_COUNTER={ic})"
    )


@cocotb.test()
async def test_normal_operation(dut):
    """Worker completes before next tick: task_enable fires periodically, no overrun.

    Models a well-behaved chart region whose body terminates within one
    tick interval.  task_busy is held high for a few cycles after each
    task_enable then dropped well before the next task_tick.  overrun_fault
    MUST remain 0 throughout.
    """
    _start_clock(dut)
    d = _divisor()
    ic = _initial_counter()
    await _reset(dut)

    # Number of base_tick pulses to the first task_enable.
    first_window = d - ic

    # Number of base_tick pulses, total, across three full periods.
    total_pulses = first_window + 2 * d

    enable_count = 0
    expected_enables_at = set()

    # The k-th task_enable fires one cycle after the (first_window + (k-1)*d)-th
    # base_tick.  We index base_ticks 1..total_pulses.
    expected_enables_at.add(first_window)
    expected_enables_at.add(first_window + d)
    expected_enables_at.add(first_window + 2 * d)

    pulse_idx = 0
    last_enable_pulse_idx = -1
    cycles_since_enable = -1  # not yet enabled
    worker_busy_cycles = 3   # worker holds busy for this many cycles after enable

    cycle = 0
    # Run for enough cycles to cover all the expected enables plus some slack.
    # Each base_tick pulse + one idle = 2 cycles per pulse; final enable lands
    # one cycle after the last expected base_tick.
    while pulse_idx < total_pulses or cycles_since_enable < worker_busy_cycles + 4:
        if pulse_idx < total_pulses:
            # Drive a base_tick this cycle.
            dut.base_tick.value = 1
            pulse_idx_local = pulse_idx + 1
        else:
            dut.base_tick.value = 0
            pulse_idx_local = pulse_idx  # unchanged for trailing settling cycles

        # Worker drops busy once worker_busy_cycles elapse since the last enable.
        if cycles_since_enable >= 0:
            if cycles_since_enable < worker_busy_cycles:
                dut.task_busy.value = 1
            else:
                dut.task_busy.value = 0

        await RisingEdge(dut.clk)

        # Update pulse counter AFTER the edge, then sample outputs.
        if pulse_idx < total_pulses:
            pulse_idx += 1

        enable_v = _read_int(dut.task_enable)
        overrun_v = _read_int(dut.overrun_fault)

        # SVA-PT-3 guard: no overrun_fault under cooperative worker.
        assert overrun_v == 0, (
            f"L1 sos_periodic_task: overrun_fault asserted at cycle {cycle} "
            f"(base_tick pulse #{pulse_idx_local}) under cooperative worker -- "
            f"violates SVA-PT-3 reverse direction (busy-required-for-rise)"
        )

        if enable_v == 1:
            enable_count += 1
            # task_enable should fire one cycle after the last expected base_tick.
            # The base_tick happened on the previous clock edge (pulse_idx
            # incremented above).  expected_enables_at marks the base_tick
            # index at which the corresponding task_enable cycle occurs.
            assert pulse_idx_local in expected_enables_at, (
                f"L1 sos_periodic_task: unexpected task_enable at cycle {cycle} "
                f"(base_tick pulse #{pulse_idx_local}); expected at "
                f"{sorted(expected_enables_at)} -- violates SVA-PT-1 spacing"
            )
            # Sanity: enable pulses must not be back-to-back (1-cycle wide).
            assert last_enable_pulse_idx != pulse_idx_local - 1 or last_enable_pulse_idx < 0, (
                f"L1 sos_periodic_task: task_enable asserted two cycles in a row "
                f"(at base_tick pulses {last_enable_pulse_idx} and {pulse_idx_local}) "
                f"-- violates SVA-PT-2 pulse-shape corollary"
            )
            last_enable_pulse_idx = pulse_idx_local
            cycles_since_enable = 0
        elif cycles_since_enable >= 0:
            cycles_since_enable += 1

        # Insert one idle cycle between base_tick pulses (so each pulse is
        # a clean 1-cycle event with at_limit/at_!limit transitions visible).
        if pulse_idx < total_pulses:
            dut.base_tick.value = 0
            if cycles_since_enable >= 0:
                if cycles_since_enable < worker_busy_cycles:
                    dut.task_busy.value = 1
                else:
                    dut.task_busy.value = 0
            await RisingEdge(dut.clk)
            enable_v = _read_int(dut.task_enable)
            overrun_v = _read_int(dut.overrun_fault)
            assert overrun_v == 0, (
                f"L1 sos_periodic_task: overrun_fault asserted during idle "
                f"between base_ticks at cycle {cycle} -- violates SVA-PT-3"
            )
            # task_enable can fire on this idle cycle only if the previous
            # base_tick was the divider-window-closing one; track it.
            if enable_v == 1:
                enable_count += 1
                assert pulse_idx in expected_enables_at, (
                    f"L1 sos_periodic_task: unexpected task_enable at cycle "
                    f"{cycle} (base_tick pulse #{pulse_idx}); expected at "
                    f"{sorted(expected_enables_at)} -- violates SVA-PT-1 spacing"
                )
                last_enable_pulse_idx = pulse_idx
                cycles_since_enable = 0
            elif cycles_since_enable >= 0:
                cycles_since_enable += 1

        cycle += 1

    assert enable_count == 3, (
        f"L1 sos_periodic_task: expected 3 task_enable pulses across "
        f"{total_pulses} base_ticks, observed {enable_count} -- "
        f"violates SVA-PT-1 (DIVISOR={d}, INITIAL_COUNTER={ic})"
    )


@cocotb.test()
async def test_overrun_detected(dut):
    """Worker holds task_busy past the next tick: overrun_fault asserts.

    Drives task_busy to '1' for the full inter-tick interval, so on the
    next task_tick the FSM observes task_busy and transitions to
    ST_OVERRUN, latching overrun_fault on the next cycle.
    """
    _start_clock(dut)
    d = _divisor()
    ic = _initial_counter()
    await _reset(dut)

    first_window = d - ic

    # Drive base_tick pulses until the first task_enable fires.
    for i in range(first_window):
        await _pulse_base_tick(dut)
        # Insert one idle cycle so each base_tick is a clean 1-cycle pulse.
        # task_enable fires one cycle after the divider-window-closing pulse.
        if i == first_window - 1:
            # On this idle cycle, task_enable should be high.
            await _step_idle(dut, 1)
            assert _read_int(dut.task_enable) == 1, (
                f"L1 sos_periodic_task: first task_enable did NOT fire after "
                f"base_tick pulse #{first_window} (DIVISOR={d}, "
                f"INITIAL_COUNTER={ic}) -- violates SVA-PT-1"
            )
            # Worker now claims busy and HOLDS through the next window.
            dut.task_busy.value = 1
        else:
            await _step_idle(dut, 1)

    # overrun_fault must still be 0 (only one tick has fired).
    assert _read_int(dut.overrun_fault) == 0, (
        f"L1 sos_periodic_task: overrun_fault asserted spuriously before "
        f"the second task_tick -- violates SVA-PT-3 (saw_first_tick guard)"
    )

    # Drive DIVISOR more base_tick pulses; task_busy stays high.  On the
    # task_tick that closes this window, the FSM observes task_busy=1 and
    # transitions to ST_OVERRUN; overrun_fault latches one cycle later.
    for i in range(d):
        dut.base_tick.value = 1
        dut.task_busy.value = 1
        await RisingEdge(dut.clk)
        dut.base_tick.value = 0
        await RisingEdge(dut.clk)

    # After the second-window-closing base_tick, task_enable fired one
    # cycle later AND overrun_fault latched the cycle after that.  By now
    # we are several cycles past the firing -- overrun_fault should be
    # firmly high.
    assert _read_int(dut.overrun_fault) == 1, (
        f"L1 sos_periodic_task: overrun_fault did NOT assert after worker "
        f"held task_busy past the second task_tick (DIVISOR={d}, "
        f"INITIAL_COUNTER={ic}) -- violates SVA-PT-3 forward direction"
    )


@cocotb.test()
async def test_overrun_is_sticky(dut):
    """After overrun_fault asserts, it stays high even when worker recovers.

    Drives the worker to hold task_busy past a tick to assert overrun_fault,
    then drops task_busy and drives many more on-time ticks.  overrun_fault
    MUST remain high until reset.
    """
    _start_clock(dut)
    d = _divisor()
    ic = _initial_counter()
    await _reset(dut)

    first_window = d - ic

    # First window: drive to first task_enable, then claim busy and hold.
    for i in range(first_window):
        await _pulse_base_tick(dut)
        await _step_idle(dut, 1)

    dut.task_busy.value = 1
    # Second window: hold busy.
    for i in range(d):
        await _pulse_base_tick(dut)
        await _step_idle(dut, 1)

    # By now overrun_fault is high.
    assert _read_int(dut.overrun_fault) == 1, (
        f"L1 sos_periodic_task: overrun_fault did not assert after worker "
        f"missed second-window deadline -- violates SVA-PT-3"
    )

    # Worker recovers: drop task_busy, drive several more full windows of
    # base_ticks.  overrun_fault MUST stay high.
    dut.task_busy.value = 0
    for window in range(3):
        for i in range(d):
            await _pulse_base_tick(dut)
            await _step_idle(dut, 1)
            assert _read_int(dut.overrun_fault) == 1, (
                f"L1 sos_periodic_task: overrun_fault dropped during recovery "
                f"window {window} after pulse {i} -- violates SVA-PT-3 stickiness"
            )


@cocotb.test()
async def test_reset_clears_overrun(dut):
    """Synchronous reset clears overrun_fault and returns the FSM to ST_IDLE."""
    _start_clock(dut)
    d = _divisor()
    ic = _initial_counter()
    await _reset(dut)

    first_window = d - ic

    # Drive the FSM into the overrun state.
    for i in range(first_window):
        await _pulse_base_tick(dut)
        await _step_idle(dut, 1)
    dut.task_busy.value = 1
    for i in range(d):
        await _pulse_base_tick(dut)
        await _step_idle(dut, 1)
    assert _read_int(dut.overrun_fault) == 1, (
        f"L1 sos_periodic_task: setup-failure -- overrun_fault did not assert "
        f"before reset-clears test could exercise it"
    )

    # Now reset.
    await _reset(dut)
    assert _read_int(dut.overrun_fault) == 0, (
        f"L1 sos_periodic_task: overrun_fault still asserted after "
        f"synchronous reset -- violates SVA-PT-3 reset-clears-overrun"
    )
    assert _read_int(dut.divider_counter) == ic, (
        f"L1 sos_periodic_task: divider_counter did not return to "
        f"INITIAL_COUNTER={ic} after reset; got {_read_int(dut.divider_counter)}"
    )

    # And confirm normal operation resumes from a clean slate: drive the
    # first window again and expect a fresh task_enable.
    dut.task_busy.value = 0
    for i in range(first_window):
        await _pulse_base_tick(dut)
        if i == first_window - 1:
            await _step_idle(dut, 1)
            assert _read_int(dut.task_enable) == 1, (
                f"L1 sos_periodic_task: post-reset first task_enable did NOT "
                f"fire after {first_window} base_ticks -- FSM did not return "
                f"to ST_IDLE"
            )
        else:
            await _step_idle(dut, 1)


@cocotb.test()
async def test_task_enable_is_pulse(dut):
    """task_enable is exactly 1 cycle wide.

    Walks through a few full windows of base_ticks and asserts that no
    two consecutive cycles ever both show task_enable = 1.
    """
    _start_clock(dut)
    d = _divisor()
    ic = _initial_counter()
    await _reset(dut)

    first_window = d - ic
    total_pulses = first_window + 2 * d

    prev_enable = 0
    for pulse in range(total_pulses):
        await _pulse_base_tick(dut)
        cur_enable = _read_int(dut.task_enable)
        assert not (prev_enable == 1 and cur_enable == 1), (
            f"L1 sos_periodic_task: task_enable asserted on two consecutive "
            f"cycles around base_tick pulse #{pulse + 1} -- violates "
            f"SVA-PT-2 pulse-shape corollary"
        )
        prev_enable = cur_enable

        await _step_idle(dut, 1)
        cur_enable = _read_int(dut.task_enable)
        assert not (prev_enable == 1 and cur_enable == 1), (
            f"L1 sos_periodic_task: task_enable asserted on two consecutive "
            f"cycles (idle side) around base_tick pulse #{pulse + 1} -- "
            f"violates SVA-PT-2 pulse-shape corollary"
        )
        prev_enable = cur_enable

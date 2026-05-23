"""test_sos_strobe_latch.py - cocotb testbench for sos_strobe_latch

@spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.10
@parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
@grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)

PCDN-A-strobe-pending-shadow resolved 2026-05-23 (§15): the primitive now
carries a depth-1 `pending_strobe` shadow register and a corresponding
`pending_q` observability port. The "re-strobe while LATCHED is dropped"
behaviour is REPLACED by "re-strobe while LATCHED is captured into the
shadow"; the depth-1 saturation case (re-strobe while LATCHED_PENDING)
preserves the original drop semantic. The same-cycle strobe+ack-from-LATCHED
arbitration was likewise refined: ack consumes the live event AND the shadow
captures the new strobe -- net next-state is LATCHED, not IDLE.

Invariants cited (not re-derived):
  INV-SOS-A..H       (SOS-07 §6)
  INV-S-HDL-1..5     (SOS-08 §7)
  INV-S-HDL-A-1..5   (SOS-08-A §7) — INV-S-HDL-A-4 expanded to 3-state one-hot
                                       (IDLE / LATCHED / LATCHED_PENDING);
                                       INV-S-HDL-A-5 VACUOUSLY satisfied.

Per PCDN-A-007 resolution (§15 2026-05-23): one Python file per primitive.
Per PCDN-A-bind-form resolved 2026-05-23: module-type SVA bind attaches the
sos_strobe_latch_sva module to every elaborated instance.

Hybrid handshake pattern under test (per task brief):
  * strobe (in)    -- 1-cycle pulse from producer (PULSE variant per §5.1).
  * latched (out)  -- LEVEL-HELD output (level variant per §5.1).
  * ack (in)       -- 1-cycle pulse from consumer (PULSE variant per §5.1).
  * pending_q (out)-- LEVEL-HELD observability of the depth-1 shadow.

Coverage (per task brief + PCDN-A-strobe-pending-shadow):
  * test_reset_clears_latched                  -- reset clears latched + pending_q.
  * test_strobe_in_idle_latches                -- strobe in IDLE -> latched next cycle.
  * test_ack_while_latched_clears              -- ack in LATCHED (no shadow) -> IDLE next cycle.
  * test_multi_cycle_latched_no_ack            -- latched holds while no ack.
  * test_restrobe_while_latched_shadows        -- strobe in LATCHED captures into shadow
                                                  (was test_restrobe_while_latched_is_dropped --
                                                  assertion INVERTED under the new contract).
  * test_shadow_consumed_on_first_ack          -- fill shadow, ack, verify next state
                                                  is LATCHED (not LATCHED_PENDING).
  * test_double_strobe_in_pending_dropped      -- fill shadow, send 2nd strobe in
                                                  LATCHED_PENDING, verify state unchanged.
  * test_same_cycle_strobe_ack_from_latched    -- under new semantics, ack consumes
                                                  LATCHED + shadow captures the strobe
                                                  -> state stays LATCHED (was IDLE in old
                                                  impl). The strobe SURVIVES.
  * test_same_cycle_strobe_ack_from_idle       -- strobe captures; ack is no-op.
  * test_repeated_strobe_ack_cycles            -- end-to-end producer/consumer cycle.
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


def _pending_q(dut) -> int:
    return int(dut.pending_q.value)


def _latched_state_q(dut) -> int:
    return int(dut.latched_state_q.value)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@cocotb.test()
async def test_reset_clears_latched(dut):
    """Out of reset, latched = 0, pending_q = 0, and observability agrees."""
    _start_clock(dut)
    await _reset(dut)

    await ReadOnly()
    assert _latched(dut) == 0, "latched must be zero out of reset"
    assert _pending_q(dut) == 0, "pending_q must be zero out of reset"
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

    # Sample BEFORE the next edge: still IDLE (latched=0, pending=0).
    await ReadOnly()
    assert _latched(dut) == 0, "latched must remain 0 during the strobe cycle"
    assert _pending_q(dut) == 0, "pending_q must remain 0 during the strobe cycle"

    await RisingEdge(dut.clk)
    dut.strobe.value = 0

    # Now we are one edge past the strobe.
    await ReadOnly()
    assert _latched(dut) == 1, "latched must rise on the cycle after strobe"
    assert _pending_q(dut) == 0, "pending_q must remain 0 on IDLE -> LATCHED"
    assert _latched_state_q(dut) == 1, "observability state must mirror latched"


@cocotb.test()
async def test_ack_while_latched_clears(dut):
    """ack pulsed while LATCHED (no shadow) returns latched=0 next edge."""
    _start_clock(dut)
    await _reset(dut)

    # Latch first.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1
    await RisingEdge(dut.clk)
    dut.strobe.value = 0
    await ReadOnly()
    assert _latched(dut) == 1, "precondition: latched must be 1 before ack"
    assert _pending_q(dut) == 0, "precondition: no shadow before ack"

    # Now pulse ack for one cycle.
    await RisingEdge(dut.clk)
    dut.ack.value = 1
    await RisingEdge(dut.clk)
    dut.ack.value = 0

    await ReadOnly()
    assert _latched(dut) == 0, "latched must drop on the cycle after ack"
    assert _pending_q(dut) == 0, "pending_q must stay 0"
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
        assert _pending_q(dut) == 0, f"pending_q rose without strobe at cycle {cyc}"
        assert _latched_state_q(dut) == 1


@cocotb.test()
async def test_restrobe_while_latched_shadows(dut):
    """A second strobe while LATCHED (no ack) is CAPTURED into the shadow
    under PCDN-A-strobe-pending-shadow (previously dropped). latched stays
    high; pending_q rises to 1. Subsequent strobes are dropped (depth-1
    saturation -- see test_double_strobe_in_pending_dropped for that case).
    """
    _start_clock(dut)
    await _reset(dut)

    # First strobe -> latched.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1
    await RisingEdge(dut.clk)
    dut.strobe.value = 0
    await ReadOnly()
    assert _latched(dut) == 1
    assert _pending_q(dut) == 0, "shadow must be empty after first latch"

    # Second strobe while LATCHED, no ack -> shadow captures.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1
    await RisingEdge(dut.clk)
    dut.strobe.value = 0
    await ReadOnly()
    assert _latched(dut) == 1, "latched must remain 1 across the shadow capture"
    assert _pending_q(dut) == 1, "shadow must hold the second strobe (was dropped pre-shadow)"

    # Ack to drain: first ack consumes live + promotes shadow; latched stays 1.
    await RisingEdge(dut.clk)
    dut.ack.value = 1
    await RisingEdge(dut.clk)
    dut.ack.value = 0
    await ReadOnly()
    assert _latched(dut) == 1, "first ack must promote shadow to live (latched stays 1)"
    assert _pending_q(dut) == 0, "shadow must drain on the consuming ack"

    # Second ack drains the promoted shadow back to IDLE.
    await RisingEdge(dut.clk)
    dut.ack.value = 1
    await RisingEdge(dut.clk)
    dut.ack.value = 0
    await ReadOnly()
    assert _latched(dut) == 0, "second ack must clear the promoted shadow"
    assert _pending_q(dut) == 0


@cocotb.test()
async def test_shadow_consumed_on_first_ack(dut):
    """Fill the shadow (LATCHED -> LATCHED_PENDING), then ack: next state must
    be LATCHED (live event consumed, shadow promoted), NOT LATCHED_PENDING."""
    _start_clock(dut)
    await _reset(dut)

    # Latch.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1
    await RisingEdge(dut.clk)
    dut.strobe.value = 0
    await ReadOnly()
    assert _latched(dut) == 1 and _pending_q(dut) == 0

    # Fill the shadow.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1
    await RisingEdge(dut.clk)
    dut.strobe.value = 0
    await ReadOnly()
    assert _latched(dut) == 1 and _pending_q(dut) == 1, \
        "precondition: state must be LATCHED_PENDING before ack"

    # Ack: shadow promotes to live; pending_q drops to 0; latched stays 1.
    await RisingEdge(dut.clk)
    dut.ack.value = 1
    await RisingEdge(dut.clk)
    dut.ack.value = 0
    await ReadOnly()
    assert _latched(dut) == 1, \
        "after ack from LATCHED_PENDING, state must be LATCHED (latched=1)"
    assert _pending_q(dut) == 0, \
        "after ack from LATCHED_PENDING, shadow must drain (pending_q=0)"


@cocotb.test()
async def test_double_strobe_in_pending_dropped(dut):
    """Depth-1 saturation: with the shadow already holding a pending strobe,
    additional strobes while in LATCHED_PENDING (no ack) are dropped; state
    remains LATCHED_PENDING."""
    _start_clock(dut)
    await _reset(dut)

    # Latch.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1
    await RisingEdge(dut.clk)
    dut.strobe.value = 0

    # Fill the shadow.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1
    await RisingEdge(dut.clk)
    dut.strobe.value = 0
    await ReadOnly()
    assert _latched(dut) == 1 and _pending_q(dut) == 1, \
        "precondition: LATCHED_PENDING before the extra strobes"

    # Send several additional strobes in LATCHED_PENDING with no ack.
    for _ in range(4):
        await RisingEdge(dut.clk)
        dut.strobe.value = 1
        await RisingEdge(dut.clk)
        dut.strobe.value = 0
        await ReadOnly()
        assert _latched(dut) == 1, "latched must remain 1 across saturated re-strobes"
        assert _pending_q(dut) == 1, \
            "pending_q must remain 1 (shadow already saturated; extra strobes dropped)"

    # Drain to confirm we never accidentally widened the shadow:
    # first ack -> LATCHED (live consumed, shadow promoted);
    # second ack -> IDLE. If the shadow had over-counted, we'd need >2 acks.
    await RisingEdge(dut.clk)
    dut.ack.value = 1
    await RisingEdge(dut.clk)
    dut.ack.value = 0
    await ReadOnly()
    assert _latched(dut) == 1 and _pending_q(dut) == 0, \
        "first drain ack: shadow promoted, no further shadow"

    await RisingEdge(dut.clk)
    dut.ack.value = 1
    await RisingEdge(dut.clk)
    dut.ack.value = 0
    await ReadOnly()
    assert _latched(dut) == 0 and _pending_q(dut) == 0, \
        "second drain ack: clean IDLE -- confirms depth-1 (not deeper)"


@cocotb.test()
async def test_same_cycle_strobe_ack_from_latched(dut):
    """Refined semantic under PCDN-A-strobe-pending-shadow: from LATCHED
    (no pre-existing shadow), simultaneous strobe + ack -> ack consumes the
    live event AND the shadow captures the new strobe -> the shadow
    immediately promotes to live on the same edge, so next-state is LATCHED.
    The strobe SURVIVES (previously it was dropped). Net visible: latched
    stays 1, pending_q stays 0."""
    _start_clock(dut)
    await _reset(dut)

    # First latch.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1
    await RisingEdge(dut.clk)
    dut.strobe.value = 0
    await ReadOnly()
    assert _latched(dut) == 1, "precondition: latched=1 before same-cycle race"
    assert _pending_q(dut) == 0, "precondition: shadow empty before race"

    # Drive strobe AND ack on the same cycle.
    await RisingEdge(dut.clk)
    dut.strobe.value = 1
    dut.ack.value = 1
    await RisingEdge(dut.clk)
    dut.strobe.value = 0
    dut.ack.value = 0

    await ReadOnly()
    assert _latched(dut) == 1, \
        "same-cycle strobe+ack from LATCHED: strobe must survive (shadow promotes); latched stays 1"
    assert _pending_q(dut) == 0, \
        "same-cycle strobe+ack from LATCHED: shadow must NOT remain held (promoted on same edge)"
    assert _latched_state_q(dut) == 1

    # Confirm that one further ack drains to IDLE: the survived strobe is
    # exactly one event, no over-/under-count.
    await RisingEdge(dut.clk)
    dut.ack.value = 1
    await RisingEdge(dut.clk)
    dut.ack.value = 0
    await ReadOnly()
    assert _latched(dut) == 0, \
        "second ack must drain the survived event back to IDLE"
    assert _pending_q(dut) == 0


@cocotb.test()
async def test_same_cycle_strobe_ack_from_idle(dut):
    """From IDLE, simultaneous strobe + ack -> strobe captures the event
    (latched=1 next cycle); ack is a no-op. pending_q stays 0."""
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
    assert _pending_q(dut) == 0, \
        "same-cycle strobe+ack from IDLE: shadow must stay 0"
    assert _latched_state_q(dut) == 1


@cocotb.test()
async def test_repeated_strobe_ack_cycles(dut):
    """End-to-end producer/consumer cycle repeated many times: each
    strobe-then-ack pair toggles latched 0 -> 1 -> 0 deterministically.
    No shadow is ever used in this trace (producer waits for IDLE)."""
    _start_clock(dut)
    await _reset(dut)

    for cyc in range(16):
        # Idle in-between to flush any prior state (we're already IDLE here).
        await ReadOnly()
        assert _latched(dut) == 0, f"latched not idle at start of cycle {cyc}"
        assert _pending_q(dut) == 0, f"pending_q not idle at start of cycle {cyc}"

        # Strobe.
        await RisingEdge(dut.clk)
        dut.strobe.value = 1
        await RisingEdge(dut.clk)
        dut.strobe.value = 0
        await ReadOnly()
        assert _latched(dut) == 1, f"latch failed at cycle {cyc}"
        assert _pending_q(dut) == 0, f"unexpected shadow at cycle {cyc}"

        # Hold for a few cycles (consumer "processing" the event).
        for _ in range(2):
            await RisingEdge(dut.clk)
            await ReadOnly()
            assert _latched(dut) == 1, f"latched dropped pre-ack at cycle {cyc}"
            assert _pending_q(dut) == 0

        # Ack.
        await RisingEdge(dut.clk)
        dut.ack.value = 1
        await RisingEdge(dut.clk)
        dut.ack.value = 0
        await ReadOnly()
        assert _latched(dut) == 0, f"ack failed to clear at cycle {cyc}"
        assert _pending_q(dut) == 0

"""test_sos_mailbox.py.

@spec docs/concepts/SOS-08-B-CONCEPTS.md §6.1 (sos_mailbox contract)
      docs/concepts/SOS-08-B-CONCEPTS.md §5   (frozen decisions inherited)
      docs/concepts/SOS-08-B-CONCEPTS.md §7   (INV-S-HDL-B-1..5)
      docs/concepts/SOS-08-B-CONCEPTS.md §15  (2026-05-23 ratification:
                                              NUM_PRIO default 8, level-
                                              sensitive irq_non_empty)
      docs/concepts/SOS-08-A-CONCEPTS.md §6.2 (sos_fifo_sync L0 contract)
      docs/concepts/SOS-08-A-CONCEPTS.md §6.4 (sos_arbiter_priority L0
                                              contract)
      docs/concepts/SOS-07-CONCEPTS.md   §6   (cross-phase invariants)

Cross-phase invariants (cited, not redefined):
  INV-SOS-A..H per SOS-07 §6

Cross-sub-phase invariants (SOS-08 §7, cited):
  INV-S-HDL-1  handshake-compatible ports
  INV-S-HDL-2  static-allocation discipline
  INV-S-HDL-3  cross-domain isolation (N/A -- single-clock variant)
  INV-S-HDL-4  cooperative-only at v1
  INV-S-HDL-5  vector-to-chart traceability for HDL

Service-level invariants (SOS-08-B §7, cited):
  INV-S-HDL-B-1  vocabulary mirror discipline
  INV-S-HDL-B-2  L0 non-modification
  INV-S-HDL-B-3  service-level SVA on every L1 instance
  INV-S-HDL-B-4  vendor-IP pass-through
  INV-S-HDL-B-5  chart-vocabulary failure rendering

Service-level cocotb testbench for sos_mailbox.  Per PCDN-SOS-08-A-007
resolution (one file per primitive), this test exercises the L1
composition surface; the per-lane L0 sos_fifo_sync_sva and the
sos_arbiter_priority_sva chains attach automatically via their own
bind files.

Scenarios covered (chart-vocabulary names):

  1. test_reset_clears_state          -- post-reset: irq_non_empty=0,
                                         m_axis_tvalid=0, s_axis_tready=1.
  2. test_single_lane_post_take       -- post into lane 0, take it out.
                                         FIFO ordering preserved.
  3. test_priority_dispatch           -- post into low + high priority
                                         lanes; take drains highest first.
  4. test_irq_non_empty_tracks_state  -- irq_non_empty mirrors lane
                                         non-emptiness (SVA-MBX-4).
  5. test_reset_clears_all_lanes      -- post messages into every lane,
                                         reset, verify all lanes empty.
  6. test_aging_promotes_low_lane     -- with AGING_ENABLE=1, a low lane
                                         eventually wins under continuous
                                         high-priority pressure (delegates
                                         the exact bound to L0 arbiter SVA;
                                         this test asserts eventual drain
                                         within a generous service-level
                                         window).

Parameterisation (env vars, defaulted for local runs):
  SOS_MAILBOX_NUM_PRIO              -- default 4
  SOS_MAILBOX_DEPTH                 -- default 4
  SOS_MAILBOX_WIDTH                 -- default 16
  SOS_MAILBOX_READ_LATENCY          -- default 0 (FWFT)
  SOS_MAILBOX_RESET_MEM             -- default 0
  SOS_MAILBOX_AGING_ENABLE          -- default 0
  SOS_MAILBOX_AGING_THRESHOLD       -- default 16
  SOS_MAILBOX_GRANT_LATENCY_CYCLES  -- default 1

Failure messages cite chart vocabulary (post / take / lane / irq) per
INV-S-HDL-B-5 (chart-vocabulary failure rendering).
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


# ---------------------------------------------------------------------------
# Environment / parameters.
# ---------------------------------------------------------------------------
def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be an integer; got {raw!r}") from e


NUM_PRIO = _env_int("SOS_MAILBOX_NUM_PRIO", 4)
DEPTH = _env_int("SOS_MAILBOX_DEPTH", 4)
WIDTH = _env_int("SOS_MAILBOX_WIDTH", 16)
READ_LATENCY = _env_int("SOS_MAILBOX_READ_LATENCY", 0)
RESET_MEM = _env_int("SOS_MAILBOX_RESET_MEM", 0)
AGING_ENABLE = _env_int("SOS_MAILBOX_AGING_ENABLE", 0)
AGING_THRESHOLD = _env_int("SOS_MAILBOX_AGING_THRESHOLD", 16)
GRANT_LATENCY_CYCLES = _env_int("SOS_MAILBOX_GRANT_LATENCY_CYCLES", 1)

CLK_PERIOD_NS = 10
WIDTH_MASK = (1 << WIDTH) - 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _start_clock(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


async def reset_dut(dut, cycles: int = 4) -> None:
    """Hold sync active-high reset for `cycles` clock edges, then deassert."""
    dut.rst.value = 1
    dut.s_axis_tdata.value = 0
    dut.s_axis_tprio.value = 0
    dut.s_axis_tvalid.value = 0
    dut.m_axis_tready.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def post(dut, prio: int, msg: int, timeout_cycles: int = 64) -> None:
    """Post `msg` into priority lane `prio`.

    Returns once the producer-side handshake completes (s_axis_tvalid &&
    s_axis_tready high on the same edge).  Times out per INV-S-HDL-5 so a
    stuck mailbox produces a chart-vocabulary failure message.
    """
    dut.s_axis_tprio.value = prio
    dut.s_axis_tdata.value = msg & WIDTH_MASK
    dut.s_axis_tvalid.value = 1
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if int(dut.s_axis_tready.value) == 1:
            dut.s_axis_tvalid.value = 0
            return
    dut.s_axis_tvalid.value = 0
    raise TimeoutError(
        f"sos_mailbox post(lane={prio}, msg=0x{msg:x}) stalled for "
        f"{timeout_cycles} cycles -- SVA-MBX-3 (no loss on full) or "
        "ingress lane-decode wiring suspected"
    )


async def take(dut, timeout_cycles: int = 64) -> tuple[int, int]:
    """Drain one egress message; return (prio, msg).

    Under READ_LATENCY=0 (FWFT) the data is sampled the same cycle as the
    handshake.  Under READ_LATENCY=1 the popped value appears on
    m_axis_tdata the cycle AFTER the handshake (per the L0 sos_fifo_sync
    PCDN-A-fifo-READ_LATENCY 2026-05-23 resolution -- composed through to
    the L1 surface).
    """
    dut.m_axis_tready.value = 1
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if int(dut.m_axis_tvalid.value) == 1:
            prio = int(dut.m_axis_tprio.value)
            if READ_LATENCY == 0:
                msg = int(dut.m_axis_tdata.value) & WIDTH_MASK
            else:
                dut.m_axis_tready.value = 0
                await RisingEdge(dut.clk)
                msg = int(dut.m_axis_tdata.value) & WIDTH_MASK
            dut.m_axis_tready.value = 0
            return prio, msg
    dut.m_axis_tready.value = 0
    raise TimeoutError(
        f"sos_mailbox take stalled for {timeout_cycles} cycles -- "
        "SVA-MBX-2 (priority dispatch) or egress mux wiring suspected"
    )


# ---------------------------------------------------------------------------
# Scenario 1: reset clears state.
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_reset_clears_state(dut) -> None:
    """Post-reset surface: irq_non_empty=0, m_axis_tvalid=0, s_axis_tready=1."""
    _start_clock(dut)
    await reset_dut(dut)

    assert int(dut.irq_non_empty.value) == 0, (
        "sos_mailbox post-reset: irq_non_empty asserted with no posted "
        "messages -- violates SVA-MBX-4 (level-sensitive irq, PCDN-B-006)"
    )
    assert int(dut.m_axis_tvalid.value) == 0, (
        "sos_mailbox post-reset: m_axis_tvalid asserted before any post -- "
        "violates SVA-MBX-2 (no spurious take)"
    )
    assert int(dut.s_axis_tready.value) == 1, (
        "sos_mailbox post-reset: s_axis_tready low; targeted lane 0 should "
        "accept first post immediately (SVA-MBX-3 hold)"
    )


# ---------------------------------------------------------------------------
# Scenario 2: single-lane post-take FIFO ordering.
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_single_lane_post_take(dut) -> None:
    """Post DEPTH values into lane 0, drain them, verify FIFO order."""
    _start_clock(dut)
    await reset_dut(dut)

    written: list[int] = []
    for i in range(DEPTH):
        msg = (i * 7 + 3) & WIDTH_MASK
        await post(dut, 0, msg)
        written.append(msg)

    await RisingEdge(dut.clk)
    assert int(dut.irq_non_empty.value) == 1, (
        "sos_mailbox: posted DEPTH messages into lane 0 but irq_non_empty "
        "is low -- violates SVA-MBX-4 (take-irq must wake on any-lane-"
        "non-empty)"
    )

    drained: list[int] = []
    for _ in range(DEPTH):
        prio, msg = await take(dut)
        assert prio == 0, (
            f"sos_mailbox: take returned lane={prio}, expected 0 -- "
            "violates SVA-MBX-2 (egress sideband must report dispatched lane)"
        )
        drained.append(msg)

    assert drained == written, (
        f"sos_mailbox single-lane FIFO order broken: drained {drained}, "
        f"expected {written} -- violates SVA-MBX-1 (ordering within a lane; "
        "inherited from L0 sos_fifo_sync ordering)"
    )

    await RisingEdge(dut.clk)
    assert int(dut.irq_non_empty.value) == 0, (
        "sos_mailbox: drained all posts but irq_non_empty still asserted -- "
        "violates SVA-MBX-4 (irq must clear when all lanes empty)"
    )


# ---------------------------------------------------------------------------
# Scenario 3: priority dispatch -- highest lane wins.
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_priority_dispatch(dut) -> None:
    """Post into lane 0 (low) and lane NUM_PRIO-1 (high); take drains high first.

    The L0 arbiter convention (sos_arbiter_priority §6.4) is higher value
    wins; the L1 wiring maps lane k to priority value k, so the highest-
    indexed lane is the highest-priority lane.
    """
    if NUM_PRIO < 2:
        # Degenerate single-lane case; no priority to dispatch.
        return

    _start_clock(dut)
    await reset_dut(dut)

    low_lane = 0
    high_lane = NUM_PRIO - 1

    # Post into the low lane first.
    low_msg = 0xC0FE & WIDTH_MASK
    await post(dut, low_lane, low_msg)

    # Post into the high lane second.
    high_msg = 0xBEEF & WIDTH_MASK
    await post(dut, high_lane, high_msg)

    # Drain: the high lane MUST come first (priority dispatch).
    first_prio, first_msg = await take(dut)
    assert first_prio == high_lane, (
        f"sos_mailbox: priority dispatch returned lane={first_prio} first, "
        f"expected lane={high_lane} (high-priority) -- violates SVA-MBX-2"
    )
    assert first_msg == high_msg, (
        f"sos_mailbox: priority-dispatch winner returned msg=0x{first_msg:x}, "
        f"expected 0x{high_msg:x} -- L1 egress mux wiring bug?"
    )

    # Then the low lane drains.
    second_prio, second_msg = await take(dut)
    assert second_prio == low_lane, (
        f"sos_mailbox: second drain returned lane={second_prio}, "
        f"expected lane={low_lane} -- violates SVA-MBX-2"
    )
    assert second_msg == low_msg, (
        f"sos_mailbox: low-lane drain returned msg=0x{second_msg:x}, "
        f"expected 0x{low_msg:x}"
    )


# ---------------------------------------------------------------------------
# Scenario 4: irq_non_empty tracks lane state.
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_irq_non_empty_tracks_state(dut) -> None:
    """irq_non_empty MUST be high iff at least one lane is non-empty (SVA-MBX-4)."""
    _start_clock(dut)
    await reset_dut(dut)

    # Initially: empty -> irq low.
    assert int(dut.irq_non_empty.value) == 0, (
        "sos_mailbox: irq_non_empty asserted on empty mailbox -- violates "
        "SVA-MBX-4 (no spurious post-irq)"
    )

    # Post one message into lane 0.
    await post(dut, 0, 0x42)
    await RisingEdge(dut.clk)
    assert int(dut.irq_non_empty.value) == 1, (
        "sos_mailbox: posted one message but irq_non_empty stayed low -- "
        "violates SVA-MBX-4 (level-sensitive irq must wake on any-lane-"
        "non-empty)"
    )

    # Drain it.
    prio, _msg = await take(dut)
    assert prio == 0
    await RisingEdge(dut.clk)
    assert int(dut.irq_non_empty.value) == 0, (
        "sos_mailbox: drained sole message but irq_non_empty stayed high -- "
        "violates SVA-MBX-4 (irq must clear when all lanes empty)"
    )


# ---------------------------------------------------------------------------
# Scenario 5: reset clears every lane.
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_reset_clears_all_lanes(dut) -> None:
    """Post messages into every lane, assert reset, verify all lanes empty."""
    _start_clock(dut)
    await reset_dut(dut)

    # Post one message into each lane.
    for lane in range(NUM_PRIO):
        await post(dut, lane, 0x100 + lane)

    await RisingEdge(dut.clk)
    assert int(dut.irq_non_empty.value) == 1, (
        "sos_mailbox: posted into every lane but irq_non_empty low -- "
        "violates SVA-MBX-4"
    )

    # Assert reset (sync active-high; INV-S-HDL-A-1).
    dut.rst.value = 1
    dut.s_axis_tvalid.value = 0
    dut.m_axis_tready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # Post-reset: irq low, m_axis_tvalid low.
    assert int(dut.irq_non_empty.value) == 0, (
        "sos_mailbox: irq_non_empty asserted post-reset -- violates "
        "SVA-MBX-4 (reset must drain all post-irqs)"
    )
    assert int(dut.m_axis_tvalid.value) == 0, (
        "sos_mailbox: m_axis_tvalid asserted post-reset -- violates "
        "SVA-MBX-2 (reset must clear the priority dispatcher)"
    )


# ---------------------------------------------------------------------------
# Scenario 6: aging promotes a starved low-priority lane.
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_aging_promotes_low_lane(dut) -> None:
    """Under AGING_ENABLE=1, a low-priority lane drains within a bounded window.

    Method: post one message into the low lane; then continuously post into
    the high lane.  Under strict priority (AGING_ENABLE=0) the low lane
    would starve; under aging (AGING_ENABLE=1) it must drain within
    AGING_THRESHOLD + NUM_PRIO + GRANT_LATENCY_CYCLES take cycles (the L0
    arbiter's bound).  Service-level form here: assert the low lane drains
    within a generous service-level window (the L0 SVA enforces the exact
    bound).

    When AGING_ENABLE=0, this scenario asserts the opposite: the low lane
    does NOT drain while the high lane has pending messages.
    """
    if NUM_PRIO < 2:
        # Degenerate single-lane case; no priority to age.
        return

    _start_clock(dut)
    await reset_dut(dut)

    low_lane = 0
    high_lane = NUM_PRIO - 1
    low_msg = 0xABCD & WIDTH_MASK

    # Post one low-priority message.
    await post(dut, low_lane, low_msg)

    # Bounded service-level window: the L0 bound is
    # AGING_THRESHOLD + NUM_PRIO + GRANT_LATENCY_CYCLES *take cycles*;
    # we hold the consumer's tready high and post a steady stream of
    # high-priority messages, then check whether the low lane wins
    # within the service-level window.
    dut.m_axis_tready.value = 1

    high_post_count = 0
    saw_low_win = False
    last_high_msg = 0
    # Inflate the window to cover post + take pipelining + GRANT latency.
    window_cycles = max(AGING_THRESHOLD + NUM_PRIO + GRANT_LATENCY_CYCLES + 8,
                        DEPTH * NUM_PRIO * 4)

    # Background: keep posting high-priority messages until the low lane
    # either wins (aging) or stays starved (strict).
    cycle = 0
    while cycle < window_cycles:
        # Try to post a high-priority message if the high lane is not full.
        if int(dut.s_axis_tready.value) == 1 or int(dut.s_axis_tvalid.value) == 0:
            dut.s_axis_tprio.value = high_lane
            last_high_msg = (0x1000 + high_post_count) & WIDTH_MASK
            dut.s_axis_tdata.value = last_high_msg
            dut.s_axis_tvalid.value = 1
        await RisingEdge(dut.clk)
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            high_post_count += 1

        # Check egress: who is being drained right now?
        if int(dut.m_axis_tvalid.value) == 1:
            drained_prio = int(dut.m_axis_tprio.value)
            if drained_prio == low_lane:
                saw_low_win = True
                # Stop posting; let the test conclude.
                dut.s_axis_tvalid.value = 0
                break
        cycle += 1

    dut.s_axis_tvalid.value = 0
    dut.m_axis_tready.value = 0
    await RisingEdge(dut.clk)

    if AGING_ENABLE == 1:
        assert saw_low_win, (
            f"sos_mailbox: under AGING_ENABLE=1, low-priority lane "
            f"{low_lane} did NOT drain within {window_cycles} cycles of "
            f"continuous high-priority pressure -- violates SVA-MBX-2 + "
            "aging-fairness bound (delegated to L0 arbiter SVA)"
        )
    else:
        # Strict priority: low lane MUST starve while the high lane has
        # messages.  We do NOT require a positive observation here -- the
        # condition we test is "did NOT see low_win".  Under strict
        # priority that's the expected outcome.
        assert not saw_low_win, (
            f"sos_mailbox: under AGING_ENABLE=0, low-priority lane "
            f"{low_lane} drained while high-priority lane "
            f"{high_lane} had pending messages -- violates SVA-MBX-2 "
            "(strict priority must let low lane starve)"
        )

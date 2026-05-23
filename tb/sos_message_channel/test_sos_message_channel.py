"""test_sos_message_channel.py.

@spec docs/concepts/SOS-08-B-CONCEPTS.md §6.5 (sos_message_channel contract)
      docs/concepts/SOS-08-B-CONCEPTS.md §5   (frozen decisions)
      docs/concepts/SOS-08-B-CONCEPTS.md §7   (cross-service invariants)
      docs/concepts/SOS-08-B-CONCEPTS.md §15  PCDN-SOS-08-B-005 resolved
            2026-05-23: chart-derived metadata struct. This testbench
            exercises the OPAQUE-bits layer at the L1 service module;
            per-event packed-struct variants emitted by SOS-08-C are
            tested at the SOS-08-C emission layer, NOT here. The L1
            service module is structurally uniform — the FIFO carries
            {event_id, opaque payload} and that is what this test
            verifies.
      docs/concepts/SOS-08-A-CONCEPTS.md §6.2 (inherited L0 FIFO contract)

Cross-phase invariants (cited, not redefined):
  INV-SOS-A..H per SOS-07 §6

Cross-sub-phase invariants (SOS-08 §7, cited):
  INV-S-HDL-1  handshake-compatible ports
  INV-S-HDL-2  static-allocation discipline
  INV-S-HDL-3  cross-domain isolation (N/A — single domain)
  INV-S-HDL-4  cooperative-only at v1
  INV-S-HDL-5  vector-to-chart traceability for HDL

Cross-service invariants (SOS-08-B §7, cited):
  INV-S-HDL-B-1  vocabulary mirror discipline (send / receive verbs)
  INV-S-HDL-B-2  L0 non-modification (sos_fifo_sync accepted as-is)
  INV-S-HDL-B-3  service-level SVA on every L1 instance
  INV-S-HDL-B-4  vendor-IP pass-through (inherited from sos_fifo_sync)
  INV-S-HDL-B-5  chart-vocabulary failure rendering

Cocotb service-level testbench for sos_message_channel. Per INV-S-HDL-B-3,
service-level SVA binds attach via tb/sos_message_channel/
sos_message_channel_bind.sv during simulation.

Scenarios covered:
  1. reset behaviour      — channel idle: empty=1, full=0, count=0
  2. send single message  — one {event_id, payload} sent, received intact
  3. fill the channel     — push DEPTH messages, expect full
  4. back-pressure        — producer held off when channel full
  5. send/receive order   — N messages, FIFO ordering preserved
  6. sideband-vs-packed   — producer drives sideband, consumer reads
                            sideband + packed; equality holds (§6.5 #1)

Parameterisation (env-driven; build wrapper sets these):
  SOS_MSGCH_EVENT_ID_WIDTH  — DUT EVENT_ID_WIDTH (default 10)
  SOS_MSGCH_PAYLOAD_WIDTH   — DUT PAYLOAD_WIDTH  (default 128)
  SOS_MSGCH_DEPTH           — DUT DEPTH         (default 16)
  SOS_MSGCH_READ_LATENCY    — DUT READ_LATENCY  (0 = FWFT, 1 = registered)
  SOS_MSGCH_RESET_MEM       — DUT RESET_MEM     (0 = retained, 1 = cleared)
"""

from __future__ import annotations

import os
import random
from collections import deque

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


# ---------------------------------------------------------------------------
# DUT parameters — sourced from environment; defaults match the example
# instantiation under examples/sos_message_channel/.
# ---------------------------------------------------------------------------
EVENT_ID_WIDTH = int(os.environ.get("SOS_MSGCH_EVENT_ID_WIDTH", "10"))
PAYLOAD_WIDTH = int(os.environ.get("SOS_MSGCH_PAYLOAD_WIDTH", "128"))
DEPTH = int(os.environ.get("SOS_MSGCH_DEPTH", "16"))
READ_LATENCY = int(os.environ.get("SOS_MSGCH_READ_LATENCY", "0"))
RESET_MEM = int(os.environ.get("SOS_MSGCH_RESET_MEM", "0"))
CLK_PERIOD_NS = 10  # 100 MHz nominal

EVENT_ID_MASK = (1 << EVENT_ID_WIDTH) - 1
PAYLOAD_MASK = (1 << PAYLOAD_WIDTH) - 1
TDATA_WIDTH = EVENT_ID_WIDTH + PAYLOAD_WIDTH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def reset_dut(dut, cycles: int = 4) -> None:
    """Hold sync active-high reset for `cycles` clock edges, then deassert."""
    dut.rst.value = 1
    dut.s_axis_tdata.value = 0
    dut.s_axis_tevent_id.value = 0
    dut.s_axis_tpayload.value = 0
    dut.s_axis_tvalid.value = 0
    dut.m_axis_tready.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def send_message(
    dut, event_id: int, payload: int, *, use_sideband: bool = True
) -> None:
    """Drive one accepted send transaction.

    Per PCDN-005 the producer MAY drive either the packed `s_axis_tdata` bus
    OR the decomposed sideband (`s_axis_tevent_id` + `s_axis_tpayload`).
    `use_sideband=True` exercises the chart-emitter-natural representation;
    `use_sideband=False` exercises the packed-bus representation. The L1
    service OR-combines them, so the inactive side MUST be driven to zero.
    """
    event_id &= EVENT_ID_MASK
    payload &= PAYLOAD_MASK

    if use_sideband:
        dut.s_axis_tdata.value = 0
        dut.s_axis_tevent_id.value = event_id
        dut.s_axis_tpayload.value = payload
    else:
        dut.s_axis_tdata.value = (event_id << PAYLOAD_WIDTH) | payload
        dut.s_axis_tevent_id.value = 0
        dut.s_axis_tpayload.value = 0

    dut.s_axis_tvalid.value = 1
    # Wait until the channel accepts (tready high).
    while True:
        await RisingEdge(dut.clk)
        if int(dut.s_axis_tready.value) == 1:
            break
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tevent_id.value = 0
    dut.s_axis_tpayload.value = 0


async def receive_message(dut) -> tuple[int, int, int]:
    """Receive one message; return (event_id, payload, packed_tdata).

    Under READ_LATENCY=0 (FWFT) the data is sampled the same cycle as the
    handshake. Under READ_LATENCY=1 (registered read) the popped value
    appears on the master bus the cycle AFTER the handshake — we wait one
    extra cycle before sampling, mirroring the sos_fifo_sync test
    convention.
    """
    dut.m_axis_tready.value = 1
    while True:
        await RisingEdge(dut.clk)
        if int(dut.m_axis_tvalid.value) == 1:
            if READ_LATENCY == 0:
                event_id = int(dut.m_axis_tevent_id.value)
                payload = int(dut.m_axis_tpayload.value)
                packed = int(dut.m_axis_tdata.value)
            else:
                dut.m_axis_tready.value = 0
                await RisingEdge(dut.clk)
                event_id = int(dut.m_axis_tevent_id.value)
                payload = int(dut.m_axis_tpayload.value)
                packed = int(dut.m_axis_tdata.value)
            break
    dut.m_axis_tready.value = 0
    return event_id, payload, packed


def _start_clock(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


# ---------------------------------------------------------------------------
# Scenario 1: reset behaviour
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_reset_behaviour(dut) -> None:
    """After reset: empty=1, full=0, count=0, channel idle."""
    _start_clock(dut)
    await reset_dut(dut)

    assert int(dut.empty.value) == 1, "empty should be 1 post-reset"
    assert int(dut.full.value) == 0, "full should be 0 post-reset"
    assert int(dut.count.value) == 0, "count should be 0 post-reset"
    assert int(dut.m_axis_tvalid.value) == 0, "tvalid should be 0 post-reset"
    assert int(dut.s_axis_tready.value) == 1, "tready should be 1 post-reset"


# ---------------------------------------------------------------------------
# Scenario 2: send single message, receive intact
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_send_recv_single(dut) -> None:
    """One {event_id, payload} message: sideband producer, packed+sideband consumer."""
    _start_clock(dut)
    await reset_dut(dut)

    event_id = 0x2A1 & EVENT_ID_MASK
    payload = (0xCAFEBABE_DEADBEEF & PAYLOAD_MASK)

    await send_message(dut, event_id, payload, use_sideband=True)

    got_eid, got_pl, got_packed = await receive_message(dut)
    assert got_eid == event_id, (
        f"event_id mismatch: got 0x{got_eid:x} expected 0x{event_id:x}"
    )
    assert got_pl == payload, (
        f"payload mismatch: got 0x{got_pl:x} expected 0x{payload:x}"
    )
    # §6.5 #1: master packed bus must equal {event_id, payload}.
    expected_packed = (event_id << PAYLOAD_WIDTH) | payload
    assert got_packed == expected_packed, (
        f"packed tdata mismatch: got 0x{got_packed:x} expected 0x{expected_packed:x}"
    )

    await RisingEdge(dut.clk)
    assert int(dut.empty.value) == 1, "channel should be empty after drain"
    assert int(dut.count.value) == 0


# ---------------------------------------------------------------------------
# Scenario 3: fill the channel — DEPTH messages → full
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_fill_channel(dut) -> None:
    """Send DEPTH messages, expect full=1 and the next send to be back-pressured."""
    _start_clock(dut)
    await reset_dut(dut)

    sent = []
    for i in range(DEPTH):
        eid = (i + 1) & EVENT_ID_MASK
        pl = ((i * 0x1357_9BDF_2468_ACE0) & PAYLOAD_MASK)
        await send_message(dut, eid, pl, use_sideband=True)
        sent.append((eid, pl))

    await RisingEdge(dut.clk)
    assert int(dut.full.value) == 1, f"channel should be full after {DEPTH} sends"
    assert int(dut.empty.value) == 0
    assert int(dut.count.value) == DEPTH, f"count should be {DEPTH}"
    assert int(dut.s_axis_tready.value) == 0, (
        "tready must be 0 when channel is full (no_send_when_full)"
    )

    # Drain and check FIFO ordering.
    for expected_eid, expected_pl in sent:
        got_eid, got_pl, _ = await receive_message(dut)
        assert got_eid == expected_eid, (
            f"FIFO order broken on event_id: got 0x{got_eid:x} expected 0x{expected_eid:x}"
        )
        assert got_pl == expected_pl, (
            f"FIFO order broken on payload: got 0x{got_pl:x} expected 0x{expected_pl:x}"
        )

    await RisingEdge(dut.clk)
    assert int(dut.empty.value) == 1
    assert int(dut.count.value) == 0


# ---------------------------------------------------------------------------
# Scenario 4: back-pressure — producer held off when full
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_back_pressure(dut) -> None:
    """With channel full, holding tvalid high MUST NOT cause loss; tready stays 0."""
    _start_clock(dut)
    await reset_dut(dut)

    # Fill the channel.
    for i in range(DEPTH):
        await send_message(dut, i & EVENT_ID_MASK, i & PAYLOAD_MASK)

    await RisingEdge(dut.clk)
    assert int(dut.full.value) == 1

    # Drive a fresh send with valid high while full. Hold tvalid + sideband
    # stable for several cycles; tready MUST remain 0 (no_send_when_full).
    extra_eid = 0x3FE & EVENT_ID_MASK
    extra_pl = 0xFEEDFACE_F00DCAFE & PAYLOAD_MASK
    dut.s_axis_tdata.value = 0
    dut.s_axis_tevent_id.value = extra_eid
    dut.s_axis_tpayload.value = extra_pl
    dut.s_axis_tvalid.value = 1

    for _ in range(8):
        await RisingEdge(dut.clk)
        assert int(dut.s_axis_tready.value) == 0, (
            "back-pressure: tready must be 0 while full"
        )

    # Drop tvalid, drain one slot, expect tready to rise again.
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tevent_id.value = 0
    dut.s_axis_tpayload.value = 0

    _ = await receive_message(dut)
    await RisingEdge(dut.clk)
    assert int(dut.full.value) == 0, "channel should no longer be full after one drain"
    assert int(dut.s_axis_tready.value) == 1, "tready must rise once non-full"

    # Final fresh send — the back-pressured message was NOT lost (it was
    # never accepted), so we re-send it now and confirm it arrives.
    await send_message(dut, extra_eid, extra_pl, use_sideband=True)

    # Drain the remaining DEPTH-1 pre-existing + 1 fresh message and verify
    # the fresh one shows up last (FIFO ordering).
    drained: list[tuple[int, int]] = []
    while int(dut.empty.value) == 0:
        eid, pl, _ = await receive_message(dut)
        drained.append((eid, pl))

    assert drained[-1] == (extra_eid, extra_pl), (
        f"fresh send did not land last: drained tail = {drained[-1]}, "
        f"expected ({extra_eid}, {extra_pl})"
    )


# ---------------------------------------------------------------------------
# Scenario 5: randomised send/receive — ordering preserved
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_send_recv_ordering(dut) -> None:
    """Randomised interleaved send + receive; FIFO order MUST be preserved."""
    _start_clock(dut)
    await reset_dut(dut)

    random.seed(0xBEE5_FED)
    model: deque[tuple[int, int]] = deque()
    next_eid = 1

    n_cycles = 128
    pending_send: tuple[int, int] | None = None
    pending_recv = False
    receive_holding = False
    sent_count = 0
    received_count = 0

    # Use the simple send-then-receive helper variant rather than fully
    # concurrent driving — clearer than a state machine and sufficient for
    # ordering coverage (the FIFO does the heavy lifting).
    for _ in range(n_cycles):
        want_send = random.random() < 0.5 and len(model) < DEPTH
        want_recv = random.random() < 0.5 and len(model) > 0

        if want_send:
            eid = next_eid & EVENT_ID_MASK
            pl = (next_eid * 0x9E37_79B1_7F4A_7C15) & PAYLOAD_MASK
            next_eid += 1
            await send_message(dut, eid, pl, use_sideband=(eid % 2 == 0))
            model.append((eid, pl))
            sent_count += 1

        if want_recv:
            expected_eid, expected_pl = model.popleft()
            got_eid, got_pl, got_packed = await receive_message(dut)
            assert got_eid == expected_eid, (
                f"order broken on event_id: got 0x{got_eid:x} "
                f"expected 0x{expected_eid:x}"
            )
            assert got_pl == expected_pl, (
                f"order broken on payload: got 0x{got_pl:x} "
                f"expected 0x{expected_pl:x}"
            )
            # §6.5 #1 master pack-consistency.
            assert got_packed == ((expected_eid << PAYLOAD_WIDTH) | expected_pl)
            received_count += 1

    # Drain whatever remains.
    while model:
        expected_eid, expected_pl = model.popleft()
        got_eid, got_pl, _ = await receive_message(dut)
        assert (got_eid, got_pl) == (expected_eid, expected_pl), (
            f"final-drain order broken: got (0x{got_eid:x}, 0x{got_pl:x}) "
            f"expected (0x{expected_eid:x}, 0x{expected_pl:x})"
        )

    await RisingEdge(dut.clk)
    assert int(dut.empty.value) == 1
    assert int(dut.count.value) == 0


# ---------------------------------------------------------------------------
# Scenario 6: sideband-vs-packed producer representation equivalence
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sideband_packed_equivalence(dut) -> None:
    """Producer drives EITHER sideband OR packed; consumer reads both and they agree.

    Per PCDN-005 the L1 service is structurally uniform: it OR-combines the
    two producer representations into one inner-FIFO tdata word. This test
    confirms that the choice of representation is observationally
    invariant on the master side.
    """
    _start_clock(dut)
    await reset_dut(dut)

    pairs = [
        (0x11 & EVENT_ID_MASK, 0x1111_2222_3333_4444 & PAYLOAD_MASK),
        (0x22 & EVENT_ID_MASK, 0x5555_6666_7777_8888 & PAYLOAD_MASK),
        (0x33 & EVENT_ID_MASK, 0x9999_AAAA_BBBB_CCCC & PAYLOAD_MASK),
        (0x44 & EVENT_ID_MASK, 0xDDDD_EEEE_FFFF_0000 & PAYLOAD_MASK),
    ]

    # First half: sideband producer.
    for eid, pl in pairs[: len(pairs) // 2]:
        await send_message(dut, eid, pl, use_sideband=True)
    # Second half: packed producer.
    for eid, pl in pairs[len(pairs) // 2 :]:
        await send_message(dut, eid, pl, use_sideband=False)

    for expected_eid, expected_pl in pairs:
        got_eid, got_pl, got_packed = await receive_message(dut)
        assert got_eid == expected_eid, (
            f"event_id mismatch: got 0x{got_eid:x} expected 0x{expected_eid:x}"
        )
        assert got_pl == expected_pl, (
            f"payload mismatch: got 0x{got_pl:x} expected 0x{expected_pl:x}"
        )
        # Master-side pack-consistency: packed bus MUST equal {eid, payload}.
        assert got_packed == ((expected_eid << PAYLOAD_WIDTH) | expected_pl), (
            "master packed bus does not match sideband decomposition "
            "(SVA-MSGCH master_pack_consistency)"
        )

    await RisingEdge(dut.clk)
    assert int(dut.empty.value) == 1

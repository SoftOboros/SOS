"""SIS-08B first hardware slice cocotb integration vector.

Drives one FIFO write/read cycle, one mailbox notification cycle, and one
credit-counter acquire/release cycle through the composed RTL top.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge

CLK_PERIOD_NS = 10


def _start_clock(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


async def _reset(dut, cycles: int = 4) -> None:
    dut.rst.value = 1
    dut.fifo_s_tdata.value = 0
    dut.fifo_s_tvalid.value = 0
    dut.fifo_m_tready.value = 0
    dut.mailbox_s_tdata.value = 0
    dut.mailbox_s_tprio.value = 0
    dut.mailbox_s_tvalid.value = 0
    dut.mailbox_m_tready.value = 0
    dut.credit_acquire_req.value = 0
    dut.credit_release_req.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def _fifo_push(dut, value: int) -> None:
    dut.fifo_s_tdata.value = value
    dut.fifo_s_tvalid.value = 1
    while True:
        await RisingEdge(dut.clk)
        if int(dut.fifo_s_tready.value) == 1:
            break
    dut.fifo_s_tvalid.value = 0


async def _fifo_pop(dut) -> int:
    dut.fifo_m_tready.value = 1
    while True:
        await RisingEdge(dut.clk)
        if int(dut.fifo_m_tvalid.value) == 1:
            value = int(dut.fifo_m_tdata.value)
            break
    dut.fifo_m_tready.value = 0
    return value


async def _mailbox_post(dut, prio: int, value: int) -> None:
    dut.mailbox_s_tprio.value = prio
    dut.mailbox_s_tdata.value = value
    dut.mailbox_s_tvalid.value = 1
    while True:
        await RisingEdge(dut.clk)
        if int(dut.mailbox_s_tready.value) == 1:
            break
    dut.mailbox_s_tvalid.value = 0


async def _mailbox_take(dut) -> tuple[int, int]:
    dut.mailbox_m_tready.value = 1
    while True:
        await RisingEdge(dut.clk)
        if int(dut.mailbox_m_tvalid.value) == 1:
            prio = int(dut.mailbox_m_tprio.value)
            value = int(dut.mailbox_m_tdata.value)
            break
    dut.mailbox_m_tready.value = 0
    return prio, value


@cocotb.test()
async def test_first_slice_fifo_mailbox_credit_cycle(dut) -> None:
    _start_clock(dut)
    await _reset(dut)

    await ReadOnly()
    assert int(dut.fifo_empty.value) == 1
    assert int(dut.mailbox_irq_non_empty.value) == 0
    assert int(dut.credit_credits.value) == 2

    await _fifo_push(dut, 0xA5A5_0001)
    await RisingEdge(dut.clk)
    assert int(dut.fifo_empty.value) == 0
    assert int(dut.fifo_count.value) == 1
    assert await _fifo_pop(dut) == 0xA5A5_0001
    await RisingEdge(dut.clk)
    assert int(dut.fifo_empty.value) == 1

    await _mailbox_post(dut, 1, 0xCAFE_1001)
    await RisingEdge(dut.clk)
    assert int(dut.mailbox_irq_non_empty.value) == 1
    prio, value = await _mailbox_take(dut)
    assert prio == 1
    assert value == 0xCAFE_1001
    await RisingEdge(dut.clk)
    assert int(dut.mailbox_irq_non_empty.value) == 0

    dut.credit_acquire_req.value = 1
    await ReadOnly()
    assert int(dut.credit_acquire_ack.value) == 1
    await RisingEdge(dut.clk)
    dut.credit_acquire_req.value = 0
    await ReadOnly()
    assert int(dut.credit_credits.value) == 1

    dut.credit_release_req.value = 1
    await RisingEdge(dut.clk)
    dut.credit_release_req.value = 0
    await ReadOnly()
    assert int(dut.credit_credits.value) == 2

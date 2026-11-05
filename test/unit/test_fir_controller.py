# SPDX-License-Identifier: Apache-2.0
"""Controller sequencing and the tap counter."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, Timer


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.strobe_rise.value = 0
    dut.strobe_low.value = 0
    dut.rst_n.value = 0
    await Timer(1, "ns")
    assert str(dut.ready.value) == "0"
    await ClockCycles(dut.clk, 2)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)


async def leave_init(dut):
    dut.strobe_low.value = 1
    await FallingEdge(dut.clk)
    assert str(dut.ready.value) == "1"


def snapshot(dut):
    return {
        "ready": int(dut.ready.value),
        "accept": int(dut.accept.value),
        "mac": int(dut.mac_enable.value),
        "publish": int(dut.publish.value),
        "active": int(dut.calc_active.value),
        "overrun": int(dut.overrun.value),
        "tap": dut.tap.value.to_unsigned(),
    }


@cocotb.test()
async def test_init_waits_for_strobe_low(dut):
    await start(dut)
    for _ in range(10):
        await FallingEdge(dut.clk)
        assert str(dut.ready.value) == "0"
    await leave_init(dut)


@cocotb.test()
async def test_exact_sequence(dut):
    """Accept, eight taps in order, publish, then idle: a nine-clock calculation."""
    await start(dut)
    await leave_init(dut)

    for _ in range(3):
        dut.strobe_rise.value = 1
        await Timer(1, "ns")
        state = snapshot(dut)
        assert state["accept"] == 1 and state["overrun"] == 0
        await FallingEdge(dut.clk)
        dut.strobe_rise.value = 0

        for tap in range(8):
            await Timer(1, "ns")
            state = snapshot(dut)
            assert state == {"ready": 0, "accept": 0, "mac": 1, "publish": 0, "active": 1,
                             "overrun": 0, "tap": tap}, f"tap {tap}: {state}"
            await FallingEdge(dut.clk)

        await Timer(1, "ns")
        state = snapshot(dut)
        assert state == {"ready": 0, "accept": 0, "mac": 0, "publish": 1, "active": 1,
                         "overrun": 0, "tap": 0}, f"publish: {state}"
        await FallingEdge(dut.clk)

        for _ in range(5):
            await Timer(1, "ns")
            state = snapshot(dut)
            assert state == {"ready": 1, "accept": 0, "mac": 0, "publish": 0, "active": 0,
                             "overrun": 0, "tap": 0}, f"idle: {state}"
            await FallingEdge(dut.clk)


@cocotb.test()
async def test_requests_while_busy_flag_overrun(dut):
    await start(dut)
    await leave_init(dut)
    dut.strobe_rise.value = 1
    await FallingEdge(dut.clk)

    # Pulse the request in every busy cycle: no accept, and the sequence is unchanged.
    for cycle in range(9):
        await Timer(1, "ns")
        state = snapshot(dut)
        assert state["accept"] == 0 and state["overrun"] == 1, f"cycle {cycle}: {state}"
        assert state["ready"] == 0
        await FallingEdge(dut.clk)
    dut.strobe_rise.value = 0
    await Timer(1, "ns")
    assert snapshot(dut)["ready"] == 1

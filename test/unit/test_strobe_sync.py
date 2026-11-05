# SPDX-License-Identifier: Apache-2.0
"""Strobe synchronization and edge detection."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge


async def start(dut, strobe=0):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.strobe_async.value = strobe
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    assert str(dut.strobe_rise.value) == "0"
    assert str(dut.strobe_low.value) == "0", "the chain resets as if the strobe were high"
    dut.rst_n.value = 1


async def count_pulses(dut, cycles):
    pulses = 0
    for _ in range(cycles):
        await FallingEdge(dut.clk)
        pulses += int(dut.strobe_rise.value)
    return pulses


@cocotb.test()
async def test_one_pulse_per_edge(dut):
    await start(dut)
    assert await count_pulses(dut, 5) == 0, "no pulse while flushing after reset"
    assert str(dut.strobe_low.value) == "1"

    for high_cycles in (1, 2, 3, 50):
        dut.strobe_async.value = 1
        assert await count_pulses(dut, high_cycles) in (0, 1)
        dut.strobe_async.value = 0
        await count_pulses(dut, 5)

    # Latency: a change right after an edge reaches strobe_rise two edges later.
    await RisingEdge(dut.clk)
    dut.strobe_async.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    assert str(dut.strobe_rise.value) == "0"
    await FallingEdge(dut.clk)
    assert str(dut.strobe_rise.value) == "1"
    await FallingEdge(dut.clk)
    assert str(dut.strobe_rise.value) == "0", "the pulse lasts one clock"
    assert await count_pulses(dut, 50) == 0, "holding the strobe does not repeat"
    dut.strobe_async.value = 0
    assert await count_pulses(dut, 10) == 0, "a falling edge makes no pulse"


@cocotb.test()
async def test_strobe_held_through_reset(dut):
    await start(dut, strobe=1)
    assert await count_pulses(dut, 20) == 0
    assert str(dut.strobe_low.value) == "0"
    dut.strobe_async.value = 0
    assert await count_pulses(dut, 5) == 0
    assert str(dut.strobe_low.value) == "1"

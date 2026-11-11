# SPDX-License-Identifier: Apache-2.0
"""Scaling, saturation and the output register."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, Timer

from fir_model import scale_and_saturate


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.publish.value = 0
    dut.acc_scaled.value = 0
    dut.rst_n.value = 0
    await Timer(1, "ns")
    assert dut.sample_out.value.to_signed() == 0
    assert str(dut.output_valid.value) == "0"
    assert str(dut.saturated.value) == "0"
    await ClockCycles(dut.clk, 2)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)


@cocotb.test()
async def test_every_scaled_value(dut):
    """All 2^13 values of acc[19:7] match the model."""
    await start(dut)
    for scaled in range(-(1 << 12), 1 << 12):
        dut.acc_scaled.value = scaled & 0x1FFF
        dut.publish.value = 1
        await FallingEdge(dut.clk)
        dut.publish.value = 0
        wanted_output, wanted_flag = scale_and_saturate(scaled << 7)
        assert dut.sample_out.value.to_signed() == wanted_output, f"scaled value {scaled}"
        assert int(dut.saturated.value) == int(wanted_flag), f"scaled value {scaled}"
        assert str(dut.output_valid.value) == "1"


@cocotb.test()
async def test_holds_between_results(dut):
    """Without publish the output holds, whatever the accumulator does."""
    await start(dut)
    dut.acc_scaled.value = 2000
    dut.publish.value = 1
    await FallingEdge(dut.clk)
    dut.publish.value = 0
    assert dut.sample_out.value.to_signed() == 127
    assert str(dut.saturated.value) == "1"
    for scaled in (0, 1, 100, -100, 4000, 0x1FFF):
        dut.acc_scaled.value = scaled & 0x1FFF
        await FallingEdge(dut.clk)
        assert dut.sample_out.value.to_signed() == 127
        assert str(dut.saturated.value) == "1"
        assert str(dut.output_valid.value) == "0", "valid lasts one clock"

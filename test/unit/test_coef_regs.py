# SPDX-License-Identifier: Apache-2.0
"""Coefficient registers and their two read ports."""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

from fir_model import COEF_RESET


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.write_en.value = 0
    dut.write_addr.value = 0
    dut.write_data.value = 0
    dut.tap.value = 0
    dut.read_addr.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)


async def check_all(dut, shadow):
    """Both read ports must see every word, independently of each other."""
    for tap in range(8):
        dut.tap.value = tap
        dut.read_addr.value = 7 - tap
        await FallingEdge(dut.clk)
        assert dut.coef_tap.value.to_unsigned() == shadow[tap], f"tap port {tap}"
        assert dut.read_data.value.to_unsigned() == shadow[7 - tap], f"read port {7 - tap}"


@cocotb.test()
async def test_reset_and_writes(dut):
    await start(dut)
    shadow = [COEF_RESET] * 8
    await check_all(dut, shadow)

    rng = random.Random(31)
    for _ in range(300):
        enable = rng.random() < 0.6
        addr = rng.randrange(8)
        value = rng.randrange(512)
        dut.write_en.value = int(enable)
        dut.write_addr.value = addr
        dut.write_data.value = value
        await FallingEdge(dut.clk)
        dut.write_en.value = 0
        if enable:
            shadow[addr] = value
        await check_all(dut, shadow)

    # Reset restores the default on every word at once.
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 1)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)
    await check_all(dut, [COEF_RESET] * 8)

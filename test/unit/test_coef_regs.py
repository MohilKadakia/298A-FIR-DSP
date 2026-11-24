# SPDX-License-Identifier: Apache-2.0
"""Coefficient registers and their three read ports."""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

from fir_model import COEF_RESET, NUM_TAPS

HALF = NUM_TAPS // 2


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
    """Every port must see every word, independently of the others.

    Tap slot k gives coefficients k and k + 8. The SPI read port walks all sixteen
    words in reverse while the tap ports cycle, so no two ports share an address.
    """
    for step in range(NUM_TAPS):
        tap = step % HALF
        read = NUM_TAPS - 1 - step
        dut.tap.value = tap
        dut.read_addr.value = read
        await FallingEdge(dut.clk)
        assert dut.coef_lo.value.to_unsigned() == shadow[tap], f"low tap port {tap}"
        assert dut.coef_hi.value.to_unsigned() == shadow[tap + HALF], f"high tap port {tap}"
        assert dut.read_data.value.to_unsigned() == shadow[read], f"read port {read}"


@cocotb.test()
async def test_reset_and_writes(dut):
    await start(dut)
    shadow = [COEF_RESET] * NUM_TAPS
    await check_all(dut, shadow)

    rng = random.Random(31)
    for _ in range(300):
        enable = rng.random() < 0.6
        addr = rng.randrange(NUM_TAPS)
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
    await check_all(dut, [COEF_RESET] * NUM_TAPS)

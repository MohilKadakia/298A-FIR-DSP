# SPDX-License-Identifier: Apache-2.0
"""Shared multiplier and accumulator."""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, Timer

from fir_model import COEF_MAX, COEF_MIN, SAMPLE_MAX, SAMPLE_MIN, product


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.clear.value = 0
    dut.enable.value = 0
    dut.sample.value = 0
    dut.coef.value = 0
    dut.rst_n.value = 0
    await Timer(1, "ns")
    assert dut.acc.value.to_signed() == 0, "reset should act without a clock edge"
    await ClockCycles(dut.clk, 2)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)


async def load(dut, sample, coefficient):
    dut.sample.value = sample & 0xFF
    dut.coef.value = coefficient & 0x1FF


@cocotb.test()
async def test_every_legal_product(dut):
    """All 256 x 257 sample and coefficient pairs give the exact product."""
    await start(dut)
    count = 0
    for coefficient in range(COEF_MIN, COEF_MAX + 1):
        for sample in range(SAMPLE_MIN, SAMPLE_MAX + 1):
            await load(dut, sample, coefficient)
            dut.clear.value = 1
            await FallingEdge(dut.clk)
            dut.clear.value = 0
            dut.enable.value = 1
            await FallingEdge(dut.clk)
            dut.enable.value = 0
            assert dut.acc.value.to_signed() == product(sample, coefficient), (
                f"{sample} * {coefficient} gave {dut.acc.value.to_signed()}"
            )
            count += 1
    assert count == 256 * 257


@cocotb.test()
async def test_accumulator_extremes_do_not_overflow(dut):
    """Eight products of the largest size in either direction fit in 20 bits."""
    await start(dut)
    for sample, coefficient, total in (
        (-128, -128, 131072),
        (-128, 128, -131072),
        (127, 128, 130048),
        (127, -128, -130048),
    ):
        await load(dut, sample, coefficient)
        dut.clear.value = 1
        await FallingEdge(dut.clk)
        dut.clear.value = 0
        dut.enable.value = 1
        await ClockCycles(dut.clk, 8)
        await FallingEdge(dut.clk)
        dut.enable.value = 0
        # The ClockCycles wait spans eight rising edges after the first falling edge.
        assert dut.acc.value.to_signed() == total


@cocotb.test()
async def test_control_priority(dut):
    """The accumulator holds without enable, and clear beats enable."""
    await start(dut)
    rng = random.Random(11)
    running = 0
    for _ in range(3000):
        sample = rng.randint(SAMPLE_MIN, SAMPLE_MAX)
        coefficient = rng.randint(COEF_MIN, COEF_MAX)
        clear = rng.random() < 0.1
        enable = rng.random() < 0.7
        await load(dut, sample, coefficient)
        dut.clear.value = int(clear)
        dut.enable.value = int(enable)
        await FallingEdge(dut.clk)
        if clear:
            running = 0
        elif enable:
            # Bounded here so that the expectation stays inside the legal range.
            running += product(sample, coefficient)
        if abs(running) > 400000:
            dut.clear.value = 1
            await FallingEdge(dut.clk)
            running = 0
        assert dut.acc.value.to_signed() == running

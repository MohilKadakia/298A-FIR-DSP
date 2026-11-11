import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.accept.value = 0
    dut.clear.value = 0
    dut.sample_in.value = 0
    dut.tap.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)


async def read_all(dut):
    values = []
    for tap in range(8):
        dut.tap.value = tap
        await FallingEdge(dut.clk)
        values.append(dut.sample_tap.value.to_unsigned())
    return values


@cocotb.test()
async def test_shift_hold_and_clear(dut):
    await start(dut)
    assert await read_all(dut) == [0] * 8, "history resets to zero"

    rng = random.Random(21)
    shadow = [0] * 8
    for _ in range(400):
        clear = rng.random() < 0.05
        accept = rng.random() < 0.5
        value = rng.randrange(256)
        dut.clear.value = int(clear)
        dut.accept.value = int(accept)
        dut.sample_in.value = value
        await FallingEdge(dut.clk)
        dut.clear.value = 0
        dut.accept.value = 0
        # The bus is ignored unless accepted, and a simultaneous clear keeps the sample.
        if clear:
            shadow = [value if accept else 0] + [0] * 7
        elif accept:
            shadow = [value] + shadow[:-1]
        dut.sample_in.value = rng.randrange(256)
        assert await read_all(dut) == shadow

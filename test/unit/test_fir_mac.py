"""Two multipliers feeding one accumulator"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, Timer

from fir_model import COEF_MAX, COEF_MIN, NUM_TAPS, SAMPLE_MAX, SAMPLE_MIN, product


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.clear.value = 0
    dut.enable.value = 0
    await load(dut, (0, 0), (0, 0))
    dut.rst_n.value = 0
    await Timer(1, "ns")
    assert dut.acc.value.to_signed() == 0, "reset should act without a clock edge"
    await ClockCycles(dut.clk, 2)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)


async def load(dut, low, high):
    """Drive one (sample, coefficient) pair on each multiplier."""
    dut.sample_lo.value = low[0] & 0xFF
    dut.coef_lo.value = low[1] & 0x1FF
    dut.sample_hi.value = high[0] & 0xFF
    dut.coef_hi.value = high[1] & 0x1FF


@cocotb.test()
async def test_every_legal_product(dut):
    """All 256 x 257 sample and coefficient pairs give the exact product on both multipliers.

    The low multiplier walks the pairs in order and the high one walks them in
    reverse, so each sees every pair once and the sum is checked every time.
    """
    await start(dut)
    pairs = [
        (sample, coefficient)
        for coefficient in range(COEF_MIN, COEF_MAX + 1)
        for sample in range(SAMPLE_MIN, SAMPLE_MAX + 1)
    ]
    for low, high in zip(pairs, reversed(pairs)):
        await load(dut, low, high)
        dut.clear.value = 1
        await FallingEdge(dut.clk)
        dut.clear.value = 0
        dut.enable.value = 1
        await FallingEdge(dut.clk)
        dut.enable.value = 0
        wanted = product(*low) + product(*high)
        assert dut.acc.value.to_signed() == wanted, (
            f"{low[0]} * {low[1]} + {high[0]} * {high[1]} gave {dut.acc.value.to_signed()}"
        )
    assert len(pairs) == 256 * 257

    # Each multiplier alone, with the other one held at zero.
    for sample, coefficient in ((-128, -128), (-128, 128), (127, -128), (-1, 1), (3, -7)):
        for low, high in (((sample, coefficient), (0, 0)), ((0, 0), (sample, coefficient))):
            await load(dut, low, high)
            dut.clear.value = 1
            await FallingEdge(dut.clk)
            dut.clear.value = 0
            dut.enable.value = 1
            await FallingEdge(dut.clk)
            dut.enable.value = 0
            assert dut.acc.value.to_signed() == product(sample, coefficient), f"{low} {high}"


@cocotb.test()
async def test_accumulator_extremes_do_not_overflow(dut):
    """Sixteen products of the largest size in either direction fit in 20 bits."""
    await start(dut)
    slots = NUM_TAPS // 2
    for sample, coefficient, total in (
        (-128, -128, 262144),
        (-128, 128, -262144),
        (127, 128, 260096),
        (127, -128, -260096),
    ):
        await load(dut, (sample, coefficient), (sample, coefficient))
        dut.clear.value = 1
        await FallingEdge(dut.clk)
        dut.clear.value = 0
        dut.enable.value = 1
        await ClockCycles(dut.clk, slots)
        await FallingEdge(dut.clk)
        dut.enable.value = 0
        # The ClockCycles wait spans eight rising edges after the first falling edge.
        assert dut.acc.value.to_signed() == total


@cocotb.test()
async def test_control_priority(dut):
    """The accumulator holds without enable, and clear beats enable."""
    await start(dut)
    rng = random.Random(11)

    def random_pair():
        return rng.randint(SAMPLE_MIN, SAMPLE_MAX), rng.randint(COEF_MIN, COEF_MAX)

    running = 0
    for _ in range(3000):
        low, high = random_pair(), random_pair()
        clear = rng.random() < 0.1
        enable = rng.random() < 0.7
        await load(dut, low, high)
        dut.clear.value = int(clear)
        dut.enable.value = int(enable)
        await FallingEdge(dut.clk)
        if clear:
            running = 0
        elif enable:
            running += product(*low) + product(*high)
        # Bounded here so that the expectation stays inside the 20-bit range.
        if abs(running) > 400000:
            dut.clear.value = 1
            await FallingEdge(dut.clk)
            running = 0
        assert dut.acc.value.to_signed() == running

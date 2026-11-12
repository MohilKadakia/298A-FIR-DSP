# SPDX-License-Identifier: Apache-2.0
"""SPI protocol and write validation, with stubbed registers."""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

from fir_model import COEF_MAX, COEF_MIN


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.spi_sclk.value = 0
    dut.spi_mosi.value = 0
    dut.spi_cs_n.value = 1
    dut.status.value = 0
    dut.calc_active.value = 0
    dut.coef_read_data.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 4)


async def frame(dut, bits, half=2, gap=4):
    """Drive one frame at half SCLK periods of `half` clocks and watch for pulses.

    Returns the MISO bits and what the interface did. Writes do not depend on MISO
    timing, so this may run faster than the SPI limit to allow exhaustive sweeps.
    """
    events = {"we": 0, "addr": None, "data": None, "clear_history": 0, "clear_flags": 0, "rejected": 0}

    async def watch(clocks):
        for _ in range(clocks):
            await FallingEdge(dut.clk)
            if str(dut.coef_write_en.value) == "1":
                events["we"] += 1
                events["addr"] = dut.coef_write_addr.value.to_unsigned()
                events["data"] = dut.coef_write_data.value.to_unsigned()
            events["clear_history"] += int(dut.clear_history.value)
            events["clear_flags"] += int(dut.clear_flags.value)
            events["rejected"] += int(dut.write_rejected.value)

    await FallingEdge(dut.clk)
    dut.spi_cs_n.value = 0
    received = []
    for bit in bits:
        dut.spi_mosi.value = bit
        await watch(half)
        received.append(int(dut.spi_miso.value))
        dut.spi_sclk.value = 1
        await watch(half)
        dut.spi_sclk.value = 0
    await watch(half)
    dut.spi_cs_n.value = 1
    await watch(gap)
    return received, events


def bits_of(value, width):
    return [(value >> (width - 1 - i)) & 1 for i in range(width)]


@cocotb.test()
async def test_every_16_bit_write_value(dut):
    """All 65,536 data words are classified correctly."""
    await start(dut)
    accepted = 0
    for word in range(0x10000):
        _, events = await frame(dut, bits_of(5, 8) + bits_of(word, 16), half=2, gap=4)
        signed = word - 0x10000 if word >= 0x8000 else word
        legal = COEF_MIN <= signed <= COEF_MAX
        assert events["we"] == int(legal), f"word 0x{word:04x}: {events}"
        assert events["rejected"] == int(not legal), f"word 0x{word:04x}: {events}"
        if legal:
            accepted += 1
            assert events["addr"] == 5
            assert events["data"] == signed & 0x1FF, f"word 0x{word:04x}: {events}"
    assert accepted == COEF_MAX - COEF_MIN + 1


@cocotb.test()
async def test_every_command_byte(dut):
    """All 256 command bytes decode as specified."""
    await start(dut)
    for command in range(256):
        is_read = bool(command & 0x80)
        reserved_clear = (command & 0x70) == 0
        addr = command & 0x0F
        _, events = await frame(dut, bits_of(command, 8) + bits_of(1, 16))
        if is_read:
            assert events["rejected"] == 0 and events["we"] == 0, f"read 0x{command:02x}: {events}"
            assert events["clear_history"] == 0, f"read 0x{command:02x}: {events}"
        elif reserved_clear and addr < 8:
            assert events["we"] == 1 and events["addr"] == addr, f"0x{command:02x}: {events}"
        elif reserved_clear and addr == 9:
            assert events["clear_history"] == 1 and events["rejected"] == 0, f"0x{command:02x}"
        else:
            assert events["rejected"] == 1 and events["we"] == 0, f"0x{command:02x}: {events}"


@cocotb.test()
async def test_read_data_paths(dut):
    """Coefficient and status reads return the correct word on MISO, MSB first."""
    await start(dut)
    rng = random.Random(61)
    for _ in range(200):
        raw = rng.randrange(512)
        dut.coef_read_data.value = raw
        index = rng.randrange(8)
        received, _ = await frame(
            dut, bits_of(0x80 | index, 8) + [rng.getrandbits(1) for _ in range(16)], half=5
        )
        wanted = raw - 512 if raw >= 256 else raw
        assert received[8:] == bits_of(wanted & 0xFFFF, 16), f"coefficient word {raw}"
        assert str(dut.coef_read_addr.value) != "x"

    for status in range(16):
        dut.status.value = status
        received, _ = await frame(dut, bits_of(0x88, 8) + [1] * 16, half=5)
        assert received[8:] == bits_of(status, 16)


@cocotb.test()
async def test_calculation_blocks_all_writes(dut):
    """Every kind of write is rejected at the moment a calculation is running."""
    await start(dut)
    dut.calc_active.value = 1
    for command, word in ((0x03, 16), (0x09, 1), (0x09, 2), (0x09, 3)):
        _, events = await frame(dut, bits_of(command, 8) + bits_of(word, 16))
        assert events["we"] == 0 and events["clear_history"] == 0 and events["clear_flags"] == 0
        assert events["rejected"] == 1, f"0x{command:02x} {word}: {events}"
    dut.calc_active.value = 0
    _, events = await frame(dut, bits_of(0x03, 8) + bits_of(16, 16))
    assert events["we"] == 1 and events["rejected"] == 0
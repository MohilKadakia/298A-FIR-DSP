# SPDX-FileCopyrightText: © 2026 Hamza Soofi, Gurpal Johal, Mohil Kadakia, Ayaan Tunio
# SPDX-License-Identifier: Apache-2.0
"""Pin-level model of the external host, shared by all TinyFIR tests.

Everything here goes through the chip's pins and never looks at internal state,
so the same tests run on RTL and on the gate-level netlist. The drivers follow
the host contract in docs/info.md unless a test deliberately breaks it.
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer

CLK_PERIOD_NS = 100
SPI_HALF_PERIOD_NS = 500  # SCLK at one tenth of the 10 MHz system clock

REG_COEF0 = 0x0
REG_STATUS = 0x8
REG_CONTROL = 0x9
CMD_READ = 0x80

STATUS_READY = 1 << 0
STATUS_SATURATED = 1 << 1
STATUS_REJECTED = 1 << 2
STATUS_OVERRUN = 1 << 3

CONTROL_CLEAR_HISTORY = 1 << 0
CONTROL_CLEAR_FLAGS = 1 << 1

NUM_TAPS = 8


def to_bits(value: int, width: int) -> list[int]:
    return [(value >> (width - 1 - i)) & 1 for i in range(width)]


def from_bits(bits: list[int]) -> int:
    value = 0
    for bit in bits:
        value = (value << 1) | bit
    return value


def signed16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


class TinyFirHost:
    def __init__(self, dut, seed: int = 1):
        self.dut = dut
        self.rng = random.Random(seed)
        self.results: list[tuple[int, int]] = []
        self.monitor_errors: list[str] = []
        self._monitor_task = None

    async def start(self) -> None:
        """Start the clock, reset the chip, and begin recording results."""
        cocotb.start_soon(Clock(self.dut.clk, CLK_PERIOD_NS, unit="ns").start())
        await self.reset()

    async def reset(self, cycles: int = 10) -> None:
        d = self.dut
        d.ena.value = 1
        d.ui_in.value = 0
        d.spi_sclk.value = 0
        d.spi_mosi.value = 0
        d.spi_cs_n.value = 1
        d.sample_strobe.value = 0
        d.rst_n.value = 0
        await ClockCycles(d.clk, cycles)
        d.rst_n.value = 1
        await self.wait_ready()
        await self.start_monitor()

    async def start_monitor(self) -> None:
        if self._monitor_task is not None:
            self._monitor_task.cancel()
        self.results = []
        self._monitor_task = cocotb.start_soon(self._monitor())

    async def _monitor(self) -> None:
        d = self.dut
        while True:
            await RisingEdge(d.output_valid)
            await FallingEdge(d.clk)
            self.results.append((d.uo_out.value.to_signed(), int(d.saturated.value)))
            await FallingEdge(d.clk)
            assert int(d.output_valid.value) == 0, "output_valid lasted more than one clock"

    async def wait_ready(self) -> None:
        if str(self.dut.ready.value) != "1":
            await RisingEdge(self.dut.ready)

    async def settle(self) -> None:
        """Wait until any calculation has finished and its result is recorded."""
        await self.wait_ready()
        await ClockCycles(self.dut.clk, 3)

    # ----- Sample interface -----

    async def random_phase(self) -> None:
        """Move off the clock edge by a random part of one period."""
        await Timer(self.rng.randrange(1, CLK_PERIOD_NS * 1000), "ps")

    async def send_sample(self, value: int, hold_cycles: int = 3, phase: bool = True) -> None:
        """Send one sample by the handshake in the host contract.

        The bus is changed to its inverse as soon as ready falls, because the
        contract allows that and a late capture would then read the wrong value.
        """
        d = self.dut
        await self.wait_ready()
        if phase:
            await self.random_phase()
        d.ui_in.value = value & 0xFF
        await Timer(CLK_PERIOD_NS, "ns")
        d.sample_strobe.value = 1
        await FallingEdge(d.ready)
        d.ui_in.value = ~value & 0xFF
        await Timer(hold_cycles * CLK_PERIOD_NS, "ns")
        d.sample_strobe.value = 0
        await Timer(3 * CLK_PERIOD_NS, "ns")

    async def run_samples(self, samples, phase: bool = True) -> list[tuple[int, int]]:
        """Send samples one at a time and return the (output, saturated) results."""
        first = len(self.results)
        for sample in samples:
            await self.send_sample(sample, phase=phase)
        await self.settle()
        return self.results[first:]

    async def stream_uniform_one(self, sample: int, period_ps: int, high_cycles: int = 5) -> None:
        """Send one strobe from a fixed schedule, taking exactly period_ps in total.

        The host checks ready first, so a late ready fails the test. The strobe stays
        high long enough to be acknowledged, then the bus is changed to its inverse.
        """
        d = self.dut
        setup_ps = CLK_PERIOD_NS * 1000
        high_ps = high_cycles * CLK_PERIOD_NS * 1000
        low_ps = period_ps - setup_ps - high_ps
        assert low_ps >= 3 * CLK_PERIOD_NS * 1000, "strobe low time breaks the contract"
        assert str(d.ready.value) == "1", "ready was low when the schedule needed a sample"
        d.ui_in.value = sample & 0xFF
        await Timer(setup_ps, "ps")
        d.sample_strobe.value = 1
        await Timer(high_ps, "ps")
        assert str(d.ready.value) == "0", "the sample was not acknowledged"
        d.ui_in.value = ~sample & 0xFF
        d.sample_strobe.value = 0
        await Timer(low_ps, "ps")

    async def stream_uniform(self, samples, period_ps: int) -> list[tuple[int, int]]:
        """Send samples at a fixed rate, as a converter or timer would."""
        first = len(self.results)
        for sample in samples:
            await self.stream_uniform_one(sample, period_ps)
        await self.settle()
        return self.results[first:]

    # ----- SPI -----

    async def spi_frame(
        self,
        bits: list[int],
        half_ns: float = SPI_HALF_PERIOD_NS,
        jitter_ns: float = 0.0,
        phase: bool = True,
    ) -> list[int]:
        """Run one chip-select frame in SPI mode 0; return MISO at each rising edge.

        MISO is sampled at the last moment before SCLK rises, which is the tightest
        case for a real host. A pin that is undriven or X raises an error here.
        """
        d = self.dut

        def half_ps() -> int:
            return int((half_ns + self.rng.uniform(0, jitter_ns)) * 1000)

        if phase:
            await self.random_phase()
        d.spi_cs_n.value = 0
        received = []
        for bit in bits:
            d.spi_mosi.value = bit
            await Timer(half_ps(), "ps")
            received.append(int(d.spi_miso.value))
            d.spi_sclk.value = 1
            await Timer(half_ps(), "ps")
            d.spi_sclk.value = 0
        await Timer(half_ps(), "ps")
        d.spi_cs_n.value = 1
        d.spi_mosi.value = 0
        await Timer(half_ps(), "ps")
        return received

    @staticmethod
    def write_bits(addr: int, word: int) -> list[int]:
        return to_bits(addr & 0x7F, 8) + to_bits(word & 0xFFFF, 16)

    async def reg_write(self, addr: int, word: int, **frame_args) -> None:
        received = await self.spi_frame(self.write_bits(addr, word), **frame_args)
        assert not any(received), "MISO must stay low during a write"

    async def reg_read(self, addr: int, **frame_args) -> int:
        """Read a register as an unsigned word, sending random bits while reading."""
        junk = [self.rng.getrandbits(1) for _ in range(16)]
        received = await self.spi_frame(to_bits(CMD_READ | addr, 8) + junk, **frame_args)
        assert from_bits(received[:8]) == 0, "MISO was not low during the command byte"
        return from_bits(received[8:])

    async def read_coef(self, index: int, **frame_args) -> int:
        return signed16(await self.reg_read(REG_COEF0 + index, **frame_args))

    async def read_all_coefs(self) -> list[int]:
        return [await self.read_coef(i) for i in range(NUM_TAPS)]

    async def write_coefs(self, coefficients) -> None:
        for index, value in enumerate(coefficients):
            await self.reg_write(REG_COEF0 + index, value)

    async def read_status(self) -> int:
        return await self.reg_read(REG_STATUS)

    async def control(self, word: int) -> None:
        await self.reg_write(REG_CONTROL, word)

    async def clear_flags(self) -> None:
        await self.control(CONTROL_CLEAR_FLAGS)

    async def clear_history(self) -> None:
        await self.control(CONTROL_CLEAR_HISTORY)

    async def load_filter(self, coefficients) -> None:
        """Change filters by the procedure in the proposal."""
        await self.settle()
        await self.write_coefs(coefficients)
        assert await self.read_all_coefs() == list(coefficients)
        await self.clear_history()

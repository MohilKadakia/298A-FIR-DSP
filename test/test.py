import json
import math
import random
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer
from cocotb.utils import get_sim_time

from fir_model import COEF_MAX, COEF_MIN, COEF_RESET, NUM_TAPS, FirModel, scale_and_saturate
from tinyfir_host import (
    CLK_PERIOD_NS,
    CONTROL_CLEAR_FLAGS,
    CONTROL_CLEAR_HISTORY,
    REG_COEF0,
    REG_CONTROL,
    REG_STATUS,
    STATUS_OVERRUN,
    STATUS_READY,
    STATUS_REJECTED,
    STATUS_SATURATED,
    TinyFirHost,
    to_bits,
)

MODEL_DIR = Path(__file__).resolve().parent.parent / "model"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
FILTER_DESIGNS = json.loads((MODEL_DIR / "filter_coeffs.json").read_text())

MAX_RATE_PERIOD_PS = 20 * CLK_PERIOD_NS * 1000  # 500 ksample/s at 10 MHz
MAX_INTERNAL_LATENCY_CYCLES = 16


async def start_host(dut, seed: int) -> TinyFirHost:
    host = TinyFirHost(dut, seed=seed)
    await host.start()
    return host


def expect_results(results, expected, label: str = "") -> None:
    assert len(results) == len(expected), (
        f"{label}: {len(results)} results for {len(expected)} samples"
    )
    for index, (actual, wanted) in enumerate(zip(results, expected)):
        assert actual == (wanted.output, int(wanted.saturated)), (
            f"{label}: sample {index} gave {actual}, model says "
            f"({wanted.output}, {int(wanted.saturated)}), accumulator {wanted.accumulator}"
        )


async def expect_status_flags(host: TinyFirHost, flags: int, label: str) -> None:
    status = await host.read_status()
    mask = STATUS_REJECTED | STATUS_OVERRUN
    assert status & mask == flags, f"{label}: status 0x{status:04x}"


# ----- Reset -----


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def test_reset_defaults(dut):
    """Reset gives zero history and output, moving-average taps, and defined status."""
    host = await start_host(dut, seed=101)

    # Dirty every piece of state so that reset has something to clear.
    await host.write_coefs([100, -100, 50, -50, 25, -25, 128, -128])
    await host.reg_write(REG_COEF0, 999)  # sets the rejected flag
    await host.run_samples([127, 127, -128, 90, -90, 5, 60, 127])
    assert dut.uo_out.value.to_unsigned() != 0, "the output should be non-zero before reset"
    dut.sample_strobe.value = 1
    await ClockCycles(dut.clk, 4)
    dut.sample_strobe.value = 0
    await ClockCycles(dut.clk, 1)

    # Reset acts without waiting for a clock edge.
    await Timer(13, "ns")
    dut.rst_n.value = 0
    await Timer(5, "ns")
    assert dut.uo_out.value.to_unsigned() == 0
    assert str(dut.output_valid.value) == "0"
    assert str(dut.saturated.value) == "0"
    assert str(dut.ready.value) == "0", "ready must be low during reset"
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1

    # Ready returns promptly, with no spurious result.
    await host.start_monitor()
    await ClockCycles(dut.clk, 8)
    assert str(dut.ready.value) == "1", "ready should be high within 8 clocks of reset"
    assert host.results == []

    assert await host.read_all_coefs() == [COEF_RESET] * NUM_TAPS
    assert await host.read_status() == STATUS_READY

    # The default is an eight-point moving average on empty history.
    results = await host.run_samples([80] + [0] * 9)
    assert [r[0] for r in results] == [10] * 8 + [0] * 2
    assert all(r[1] == 0 for r in results)


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def test_reset_during_calculation(dut):
    """Reset partway through a calculation abandons it at any point."""
    host = await start_host(dut, seed=102)
    for cycles_after_ack in range(0, 11):
        await host.reset()
        await host.reg_write(REG_COEF0, 128)
        await host.settle()
        dut.ui_in.value = 100
        await ClockCycles(dut.clk, 1)
        dut.sample_strobe.value = 1
        await FallingEdge(dut.ready)
        if cycles_after_ack:
            await ClockCycles(dut.clk, cycles_after_ack)
        first = len(host.results)
        dut.rst_n.value = 0
        dut.sample_strobe.value = 0
        await ClockCycles(dut.clk, 3)
        dut.rst_n.value = 1
        await host.wait_ready()
        await ClockCycles(dut.clk, 15)
        # Only a result published before the reset can have been recorded.
        assert len(host.results) - first <= 1
        assert dut.uo_out.value.to_unsigned() == 0
        assert await host.read_coef(0) == COEF_RESET


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def test_strobe_high_through_reset_is_not_a_request(dut):
    """A strobe already high when reset releases causes no capture."""
    host = await start_host(dut, seed=103)
    dut.rst_n.value = 0
    dut.sample_strobe.value = 1
    dut.ui_in.value = 100
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await host.start_monitor()
    await ClockCycles(dut.clk, 30)
    assert host.results == [], "a held strobe was treated as a new request"
    assert str(dut.ready.value) == "0", "ready should stay low until the strobe is seen low"

    # SPI configuration still works in this state.
    await host.reg_write(REG_COEF0, 77)
    assert await host.read_coef(0) == 77
    await host.reg_write(REG_COEF0, COEF_RESET)

    dut.sample_strobe.value = 0
    await ClockCycles(dut.clk, 6)
    assert str(dut.ready.value) == "1"
    assert await host.run_samples([80]) == [(10, 0)]


# ----- SPI configuration -----


@cocotb.test(timeout_time=50, timeout_unit="ms")
async def test_spi_write_and_readback(dut):
    """All eight coefficients write and read back, including -1, 0 and +1."""
    host = await start_host(dut, seed=201)
    for value in (-128, 0, 128, -1, 1, 127, -127, 64, -64, 16):
        for index in range(NUM_TAPS):
            shadow = await host.read_all_coefs()
            await host.reg_write(REG_COEF0 + index, value)
            shadow[index] = value
            assert await host.read_all_coefs() == shadow, f"write {value} to coefficient {index}"
    assert await host.read_status() == STATUS_READY

    distinct = [-128, -77, -1, 0, 1, 42, 127, 128]
    await host.write_coefs(distinct)
    assert await host.read_all_coefs() == distinct
    # A read returns the sign extension across both data bytes.
    assert await host.reg_read(REG_COEF0) == 0xFF80
    assert await host.reg_read(REG_COEF0 + 7) == 0x0080


@cocotb.test(timeout_time=100, timeout_unit="ms")
async def test_spi_value_range(dut):
    """Only sign-extended values from -128 to +128 are accepted."""
    host = await start_host(dut, seed=202)
    rng = random.Random(2021)

    illegal = [129, -129, 130, -130, 255, 256, 257, -255, -256, -257, 0x0100, 0x0180, 0x01FF,
               0x0081, 0xFF7F, 0xFE80, 0x7FFF, 0x8000, 0x4000, 0x8080, 0xFF00, 0x0200, 0x1080]
    legal = [-128, -127, -1, 0, 1, 127, 128]
    # Uniform random words are almost never legal, so also aim close to the limits.
    near_limits = [rng.randint(-140, 140) for _ in range(80)]
    words = illegal + legal + near_limits + [rng.randrange(0x10000) for _ in range(80)]

    current = COEF_RESET
    for word in words:
        word &= 0xFFFF
        signed = word - 0x10000 if word >= 0x8000 else word
        await host.reg_write(REG_COEF0 + 3, word)
        accepted = COEF_MIN <= signed <= COEF_MAX
        current = signed if accepted else current
        assert await host.read_coef(3) == current, f"after writing 0x{word:04x}"
        await expect_status_flags(host, 0 if accepted else STATUS_REJECTED, f"word {word}")
        if not accepted:
            await host.clear_flags()
            await expect_status_flags(host, 0, "after clearing")


@cocotb.test(timeout_time=100, timeout_unit="ms")
async def test_spi_invalid_commands(dut):
    """Bad addresses and reserved bits change nothing and are flagged."""
    host = await start_host(dut, seed=203)
    coefficients = list(range(1, 9))
    await host.write_coefs(coefficients)
    expected = await host.read_all_coefs()
    model = FirModel(coefficients)
    expect_results(await host.run_samples([90, -70]), model.run([90, -70]), "before bad commands")

    # Each word is one that a real register would accept: 1 clears the history through
    # CONTROL, and 5 is a legal coefficient. A bad command must not let either through.
    bad_commands = [REG_STATUS] + list(range(0xA, 0x10))  # read-only or unmapped
    bad_commands += [(reserved << 4) | addr for reserved in range(1, 8) for addr in (0, 3, 7, 9)]
    for command in bad_commands:
        for word in (CONTROL_CLEAR_HISTORY, 5):
            await host.spi_frame(to_bits(command, 8) + to_bits(word, 16))
            await expect_status_flags(host, STATUS_REJECTED, f"command 0x{command:02x}")
            await host.clear_flags()
    assert await host.read_all_coefs() == expected
    expect_results(await host.run_samples([50]), model.run([50]), "bad commands kept the history")

    # Reading anywhere is harmless. Unmapped reads and reads with reserved bits
    # return zero rather than aliasing onto a real register.
    for command in list(range(0x9, 0x10)) + [0x10, 0x27, 0x38, 0x70]:
        received = await host.spi_frame(to_bits(0x80 | command, 8) + [1] * 16)
        assert not any(received), f"read command 0x{command:02x} returned data"
    await expect_status_flags(host, 0, "after reads")
    assert await host.read_all_coefs() == expected


@cocotb.test(timeout_time=100, timeout_unit="ms")
async def test_spi_incomplete_and_overlong(dut):
    """A write must be exactly 24 clocks. Any other length changes nothing."""
    host = await start_host(dut, seed=204)
    await host.write_coefs([10] * NUM_TAPS)
    frame = host.write_bits(REG_COEF0 + 2, 99)

    for length in range(1, 24):
        await host.spi_frame(frame[:length])
        assert await host.read_coef(2) == 10, f"{length}-bit write committed"
        await expect_status_flags(host, STATUS_REJECTED, f"{length}-bit write")
        await host.clear_flags()

    # 56 and 88 bits would look like 24 if the bit counter were allowed to wrap.
    for length in (25, 26, 32, 48, 56, 88):
        await host.spi_frame(frame + [0] * (length - 24))
        assert await host.read_coef(2) == 10, f"{length}-bit write committed"
        await expect_status_flags(host, STATUS_REJECTED, f"{length}-bit write")
        await host.clear_flags()

    # Chip select with no clocks at all is not a transaction.
    await host.spi_frame([])
    await expect_status_flags(host, 0, "empty frame")

    # A short or long read has no side effects, and MISO stays low past the data.
    for length in (1, 7, 8, 9, 23):
        await host.spi_frame(to_bits(0x80 | 2, 8)[:length] + [1] * max(0, length - 8))
    received = await host.spi_frame(to_bits(0x80 | 2, 8) + [1] * 32)
    assert received[8:24] == to_bits(10, 16)
    assert not any(received[24:]), "MISO should stay low after the 16 data bits"
    await expect_status_flags(host, 0, "after partial reads")

    # An aborted frame must not disturb the next one.
    await host.spi_frame(frame[:11])
    await host.clear_flags()
    await host.reg_write(REG_COEF0 + 2, 99)
    assert await host.read_coef(2) == 99
    await expect_status_flags(host, 0, "after a good write")

    # A read cut off while driving a one must not leave MISO high for the next frame.
    await host.reg_write(REG_COEF0 + 2, -1)
    received = await host.spi_frame(to_bits(0x80 | 2, 8) + [0] * 4)
    assert received[8:] == [1, 1, 1, 1]
    assert await host.reg_read(REG_STATUS) == STATUS_READY


@cocotb.test(timeout_time=50, timeout_unit="ms")
async def test_spi_timing_margins(dut):
    """Reads and writes hold across clock phases, duty-cycle jitter and short gaps."""
    host = await start_host(dut, seed=205)
    rng = random.Random(2051)

    # The specified limit: one tenth of the system clock, at random phases, with
    # up to 30% of one half period of jitter on every edge.
    for _ in range(60):
        index = rng.randrange(NUM_TAPS)
        value = rng.randint(COEF_MIN, COEF_MAX)
        await host.reg_write(REG_COEF0 + index, value, jitter_ns=150)
        assert await host.read_coef(index, jitter_ns=150) == value

    # Margin beyond the limit: one eighth of the system clock.
    for _ in range(60):
        index = rng.randrange(NUM_TAPS)
        value = rng.randint(COEF_MIN, COEF_MAX)
        await host.reg_write(REG_COEF0 + index, value, half_ns=400)
        assert await host.read_coef(index, half_ns=400) == value

    await expect_status_flags(host, 0, "after timing margin tests")


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def test_spi_sclk_high_at_chip_select_edges(dut):
    """Only rising edges while selected count, so SCLK high at either end adds no bit."""
    host = await start_host(dut, seed=208)
    half_ns = 500

    async def frame(bits, high_at_start: bool, high_at_end: bool) -> None:
        if high_at_start:
            dut.spi_sclk.value = 1
            await Timer(half_ns, "ns")
        dut.spi_cs_n.value = 0
        await Timer(half_ns, "ns")
        dut.spi_sclk.value = 0
        for index, bit in enumerate(bits):
            dut.spi_mosi.value = bit
            await Timer(half_ns, "ns")
            dut.spi_sclk.value = 1
            await Timer(half_ns, "ns")
            if index < len(bits) - 1 or not high_at_end:
                dut.spi_sclk.value = 0
        if not high_at_end:
            await Timer(half_ns, "ns")
        dut.spi_cs_n.value = 1
        await Timer(half_ns, "ns")
        dut.spi_sclk.value = 0
        await Timer(half_ns, "ns")

    value = 20
    for high_at_start in (False, True):
        for high_at_end in (False, True):
            value += 1
            await frame(host.write_bits(REG_COEF0 + 4, value), high_at_start, high_at_end)
            assert await host.read_coef(4) == value, f"{high_at_start}, {high_at_end}"
            await expect_status_flags(host, 0, f"{high_at_start}, {high_at_end}")


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def test_uio_pin_directions(dut):
    """MISO is high-impedance unless selected. All other pin directions are fixed."""
    host = await start_host(dut, seed=206)

    def check_directions(selected: bool) -> None:
        assert dut.uio_oe.value.to_unsigned() == (0b11100100 if selected else 0b11100000)
        assert dut.uio_out.value.to_unsigned() & 0b00011011 == 0, "unused outputs must be 0"
        if not selected:
            assert str(dut.spi_miso.value).lower() == "z", "MISO must float when deselected"

    check_directions(selected=False)

    # The pin follows chip select directly, even with no clock edge in between.
    await FallingEdge(dut.clk)
    dut.spi_cs_n.value = 0
    await Timer(1, "ns")
    check_directions(selected=True)
    assert str(dut.spi_miso.value) == "0"
    dut.spi_cs_n.value = 1
    await Timer(1, "ns")
    check_directions(selected=False)

    # Directions also hold during reset.
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    check_directions(selected=False)
    dut.spi_cs_n.value = 0
    await Timer(1, "ns")
    check_directions(selected=True)
    dut.spi_cs_n.value = 1
    dut.rst_n.value = 1
    await host.wait_ready()

    # ... and throughout a calculation.
    dut.ui_in.value = 50
    await ClockCycles(dut.clk, 1)
    dut.sample_strobe.value = 1
    await FallingEdge(dut.ready)
    for _ in range(8):
        await FallingEdge(dut.clk)
        assert str(dut.ready.value) == "0", "this check should run during the calculation"
        check_directions(selected=False)
    dut.sample_strobe.value = 0
    await host.settle()
    check_directions(selected=False)


@cocotb.test(timeout_time=50, timeout_unit="ms")
async def test_status_and_control(dut):
    """Clearing history keeps coefficients, and the flags clear only on request."""
    host = await start_host(dut, seed=207)
    coefficients = [128, 64, 32, 16, -16, -32, -64, -128]
    await host.write_coefs(coefficients)
    model = FirModel(coefficients)
    samples = [100, -50, 25, 75, -125, 60, 3, 90]
    expect_results(await host.run_samples(samples), model.run(samples), "before clear")
    held_output = dut.uo_out.value.to_signed()

    # Clearing history leaves the coefficients and the held output untouched.
    await host.clear_history()
    await ClockCycles(dut.clk, 5)
    assert dut.uo_out.value.to_signed() == held_output
    assert await host.read_all_coefs() == coefficients
    await expect_status_flags(host, 0, "after clear_history")
    model.clear_history()
    samples = [40, 80]
    expect_results(await host.run_samples(samples), model.run(samples), "after clear")

    # Each sticky flag holds until cleared, and survives unrelated activity.
    await host.reg_write(REG_COEF0, 1000)
    await expect_status_flags(host, STATUS_REJECTED, "rejected flag set")
    expect_results(await host.run_samples([1]), model.run([1]), "with flag set")
    await host.write_coefs(coefficients)
    await expect_status_flags(host, STATUS_REJECTED, "rejected flag is sticky")

    # CONTROL rejects any value outside its two defined bits.
    held_coefs = await host.read_all_coefs()
    await host.clear_flags()
    for word in (0x0004, 0x0100, 0x8000, 0xFFFF):
        await host.control(word)
        await expect_status_flags(host, STATUS_REJECTED, f"control 0x{word:04x}")
        await host.clear_flags()

    # A rejected CONTROL write must not clear the history.
    await host.control(0x0005)
    await host.clear_flags()
    expect_results(await host.run_samples([9]), model.run([9]), "bad control keeps history")

    # A zero write to CONTROL is legal and does nothing.
    await host.control(0)
    await expect_status_flags(host, 0, "control zero")
    expect_results(await host.run_samples([9]), model.run([9]), "zero control keeps history")

    # Clearing flags does not clear history, and clearing both bits does both.
    await host.reg_write(REG_COEF0, 1000)
    await host.control(CONTROL_CLEAR_FLAGS)
    expect_results(await host.run_samples([8]), model.run([8]), "clear flags keeps history")
    await host.reg_write(REG_COEF0, 1000)
    await host.control(CONTROL_CLEAR_FLAGS | CONTROL_CLEAR_HISTORY)
    await expect_status_flags(host, 0, "clear both")
    model.clear_history()
    expect_results(await host.run_samples([7]), model.run([7]), "clear both clears history")
    assert await host.read_all_coefs() == held_coefs

    # The saturated status bit mirrors the pin.
    await host.write_coefs([128] * NUM_TAPS)
    model.set_coefficients([128] * NUM_TAPS)
    expect_results(await host.run_samples([127, 127]), model.run([127, 127]), "saturating")
    assert str(dut.saturated.value) == "1"
    assert await host.read_status() & STATUS_SATURATED


# ----- Arithmetic -----


@cocotb.test(timeout_time=100, timeout_unit="ms")
async def test_impulse_response(dut):
    """An impulse followed by zeros reads out the quantized coefficient set."""
    host = await start_host(dut, seed=301)
    sets = [design["coefficients"] for design in FILTER_DESIGNS.values()]
    sets += [[128, 64, 32, 16, 8, 4, 2, 1], [-128, 77, -3, 0, 5, -99, 128, -1]]
    for coefficients in sets:
        for height in (100, -100, 127, -128, 1, -1):
            await host.load_filter(coefficients)
            samples = [height] + [0] * 10
            expected = FirModel(coefficients).run(samples)
            expect_results(await host.run_samples(samples), expected, f"impulse {height}")
            # Check the model's shape directly as well, so it is not only compared
            # with itself: y[k] = floor(height * c[k] / 128), clipped to 8 bits.
            for k in range(NUM_TAPS):
                assert expected[k].output == max(-128, min(127, (height * coefficients[k]) >> 7))


@cocotb.test(timeout_time=100, timeout_unit="ms")
async def test_unity_pass_through(dut):
    """With coefficient 0 at +1 the output equals the input for every input value."""
    host = await start_host(dut, seed=302)
    await host.load_filter([128, 0, 0, 0, 0, 0, 0, 0])
    every_value = list(range(-128, 128))
    random.Random(3021).shuffle(every_value)
    results = await host.run_samples(every_value)
    assert results == [(value, 0) for value in every_value]

    # Moving the +1 to the last tap delays the stream by exactly seven samples.
    await host.load_filter([0, 0, 0, 0, 0, 0, 0, 128])
    results = await host.run_samples(every_value[:40])
    assert results == [(value, 0) for value in [0] * 7 + every_value[:33]]


@cocotb.test(timeout_time=1000, timeout_unit="ms")
async def test_random_arithmetic(dut):
    """Hardware matches the integer model over 10,240 samples and 10 coefficient sets."""
    host = await start_host(dut, seed=303)
    rng = random.Random(3031)
    samples_per_set = 1024

    def random_set(limit: int) -> list[int]:
        return [rng.randint(-limit, limit) for _ in range(NUM_TAPS)]

    coefficient_sets = [
        random_set(COEF_MAX),
        random_set(COEF_MAX),
        random_set(COEF_MAX),
        random_set(32),
        random_set(4),
        [rng.choice((COEF_MIN, COEF_MAX)) for _ in range(NUM_TAPS)],
        [rng.choice((-1, 0, 1)) for _ in range(NUM_TAPS)],
        FILTER_DESIGNS["lowpass"]["coefficients"],
        FILTER_DESIGNS["highpass"]["coefficients"],
        FILTER_DESIGNS["bandpass"]["coefficients"],
    ]

    def random_sample() -> int:
        # Mostly uniform, but with extra weight on the extremes that drive clipping.
        return rng.choice((-128, 127)) if rng.random() < 0.15 else rng.randint(-128, 127)

    total = 0
    clipped = 0
    for set_index, coefficients in enumerate(coefficient_sets):
        await host.load_filter(coefficients)
        samples = [random_sample() for _ in range(samples_per_set)]
        expected = FirModel(coefficients).run(samples)
        results = await host.run_samples(samples, phase=False)
        expect_results(results, expected, f"set {set_index} {coefficients}")
        total += len(samples)
        clipped += sum(r.saturated for r in expected)

    assert total >= 10_000
    assert clipped > 100, "the stimulus should exercise saturation"
    dut._log.info("Compared %d samples, %d of them clipped", total, clipped)
    await expect_status_flags(host, 0, "after random arithmetic")


@cocotb.test(timeout_time=100, timeout_unit="ms")
async def test_overflow_and_sign(dut):
    """Both clip limits, the exact boundaries around them, and floor rounding."""
    host = await start_host(dut, seed=304)

    # (coefficients, samples, wanted final output, wanted final saturated flag)
    cases = [
        # Full-scale extremes.
        ([128] * 8, [127] * 8, 127, 1),
        ([128] * 8, [-128] * 8, -128, 1),
        ([-128] * 8, [-128] * 8, 127, 1),
        ([-128] * 8, [127] * 8, -128, 1),
        # Largest and smallest results that fit without clipping.
        ([128] + [0] * 7, [127], 127, 0),
        ([128] + [0] * 7, [-128], -128, 0),
        ([-128] + [0] * 7, [127], -127, 0),
        # A[n] = 16383 still floors to 127, and 16384 is the first value that clips.
        ([128, 1] + [0] * 6, [127, 127], 127, 0),
        ([128, 128] + [0] * 6, [127, 1], 127, 1),
        # A[n] = -16384 floors to exactly -128. One less is the first negative clip.
        ([128, 0] + [0] * 6, [0, -128], -128, 0),
        ([128, 1] + [0] * 6, [-1, -128], -128, 1),
        # -128 * -128 is the one product that needs the top of the range.
        ([-128] + [0] * 7, [-128], 127, 1),
        ([128] + [0] * 7, [64], 64, 0),
        # Floor rounding: -1/128 gives -1, and +1/128 gives 0.
        ([1] + [0] * 7, [-1], -1, 0),
        ([1] + [0] * 7, [1], 0, 0),
        ([64] + [0] * 7, [-1], -1, 0),
        ([64] + [0] * 7, [1], 0, 0),
        ([64] + [0] * 7, [3], 1, 0),
        ([64] + [0] * 7, [-3], -2, 0),
        ([-1] + [0] * 7, [-128], 1, 0),
        ([-1] + [0] * 7, [127], -1, 0),
        ([1] + [0] * 7, [127], 0, 0),
        ([1, 1] + [0] * 6, [64, 64], 1, 0),
        ([1, 1] + [0] * 6, [-64, -64], -1, 0),
        ([1, 1] + [0] * 6, [-64, -65], -2, 0),
    ]
    for coefficients, samples, wanted_output, wanted_flag in cases:
        await host.load_filter(coefficients)
        expected = FirModel(coefficients).run(samples)
        expect_results(await host.run_samples(samples), expected, f"{coefficients} {samples}")
        assert expected[-1].output == wanted_output, f"model disagrees: {coefficients}"
        assert int(expected[-1].saturated) == wanted_flag, f"model flag: {coefficients}"

    # The saturated flag follows each result and holds between results.
    await host.load_filter([128, 128] + [0] * 6)
    results = await host.run_samples([127, 127, 0, 0, -128, -128, 0])
    assert results == [(127, 0), (127, 1), (127, 0), (0, 0), (-128, 0), (-128, 1), (-128, 0)]
    assert str(dut.saturated.value) == "0"
    await host.run_samples([127, 127])
    assert str(dut.saturated.value) == "1"
    await ClockCycles(dut.clk, 200)
    assert str(dut.saturated.value) == "1", "the flag must hold until the next result"
    assert dut.uo_out.value.to_signed() == 127

    # The model's limit logic agrees with a direct statement of the formula.
    for accumulator in (-131072, -16513, -16512, -16385, -16384, -1, 0, 127, 128, 16383, 16384, 131072):
        floor = math.floor(accumulator / 128)
        assert scale_and_saturate(accumulator) == (
            max(-128, min(127, floor)),
            floor < -128 or floor > 127,
        )


# ----- Sample interface and timing -----


async def check_output_stable(dut):
    """Fail if the output or flag changes in any cycle that has no output_valid."""
    await FallingEdge(dut.clk)
    previous = (str(dut.uo_out.value), str(dut.saturated.value))
    while True:
        await FallingEdge(dut.clk)
        current = (str(dut.uo_out.value), str(dut.saturated.value))
        if current != previous:
            assert str(dut.output_valid.value) == "1", "output changed without output_valid"
        previous = current


@cocotb.test(timeout_time=200, timeout_unit="ms")
async def test_latency_budget(dut):
    """Latency stays inside its budget for every input phase."""
    host = await start_host(dut, seed=401)
    await host.load_filter([128] + [0] * 7)
    rng = random.Random(4011)

    internal_latencies = set()
    external_latencies = []
    recovery_times = []
    for _ in range(300):
        await host.random_phase()
        dut.ui_in.value = rng.randint(-128, 127) & 0xFF
        await Timer(CLK_PERIOD_NS, "ns")
        dut.sample_strobe.value = 1
        strobe_ns = get_sim_time("ns")
        await FallingEdge(dut.ready)
        accepted_ns = get_sim_time("ns")
        await Timer(3 * CLK_PERIOD_NS, "ns")
        dut.sample_strobe.value = 0
        await RisingEdge(dut.output_valid)
        valid_ns = get_sim_time("ns")
        if str(dut.ready.value) != "1":
            await RisingEdge(dut.ready)
        ready_ns = get_sim_time("ns")
        internal_latencies.add(round((valid_ns - accepted_ns) / CLK_PERIOD_NS))
        external_latencies.append((valid_ns - strobe_ns) / CLK_PERIOD_NS)
        recovery_times.append((ready_ns - strobe_ns) / CLK_PERIOD_NS)
        assert ready_ns - valid_ns < CLK_PERIOD_NS, "ready should return with output_valid"
        await ClockCycles(dut.clk, 3)

    dut._log.info(
        "Latency in clocks: acceptance to valid %s, strobe to valid %.2f to %.2f, "
        "strobe to ready at most %.2f",
        sorted(internal_latencies),
        min(external_latencies),
        max(external_latencies),
        max(recovery_times),
    )
    assert internal_latencies == {9}, f"latency varied: {internal_latencies}"
    assert max(internal_latencies) <= MAX_INTERNAL_LATENCY_CYCLES
    assert max(external_latencies) <= 12.0 + 0.01, "worst case is 3 clocks of sync plus 9"
    assert max(recovery_times) <= 20, "ready must recover inside the 500 ksample/s budget"


@cocotb.test(timeout_time=2000, timeout_unit="ms")
async def test_variable_rate(dut):
    """No dropped or duplicated samples at any rate up to 500 ksample/s."""
    host = await start_host(dut, seed=402)
    coefficients = [90, -40, 35, 12, -7, 20, -33, 11]
    rng = random.Random(4021)
    stability = cocotb.start_soon(check_output_stable(dut))

    # (name, period in ps, sample count). The non-integer periods walk the strobe
    # through every phase of the system clock.
    rates = [
        ("500 ksps", MAX_RATE_PERIOD_PS, 300),
        ("500 ksps, new phase", MAX_RATE_PERIOD_PS, 100),
        ("490.4 ksps", 2_039_300, 300),
        ("400 ksps", 2_500_000, 200),
        ("317.5 ksps", 3_149_900, 200),
        ("250 ksps", 4_000_000, 150),
        ("100 ksps", 10_000_000, 100),
        ("33.3 ksps", 30_012_700, 40),
        ("10 ksps", 100_000_000, 20),
    ]
    for name, period_ps, count in rates:
        await host.load_filter(coefficients)
        await host.random_phase()
        samples = [rng.randint(-128, 127) for _ in range(count)]
        results = await host.stream_uniform(samples, period_ps)
        expect_results(results, FirModel(coefficients).run(samples), name)
        await expect_status_flags(host, 0, name)

    # Irregular spacing, varying from the fastest legal gap to five times that.
    await host.load_filter(coefficients)
    model = FirModel(coefficients)
    samples = [rng.randint(-128, 127) for _ in range(200)]
    first = len(host.results)
    for sample in samples:
        await host.random_phase()
        await host.stream_uniform_one(sample, rng.randrange(MAX_RATE_PERIOD_PS, 5 * MAX_RATE_PERIOD_PS))
    await host.settle()
    expect_results(host.results[first:], model.run(samples), "irregular spacing")
    await expect_status_flags(host, 0, "irregular spacing")
    stability.cancel()


@cocotb.test(timeout_time=200, timeout_unit="ms")
async def test_fastest_contract_rate(dut):
    """Measure the margin: the contract holds at 13 clocks per sample, not only 20."""
    host = await start_host(dut, seed=403)
    coefficients = [50, -20, 60, 8, -9, 33, -44, 21]
    rng = random.Random(4031)
    await host.load_filter(coefficients)
    samples = [rng.randint(-128, 127) for _ in range(400)]
    first = len(host.results)
    for sample in samples:
        await host.random_phase()
        await host.stream_uniform_one(sample, 13 * CLK_PERIOD_NS * 1000, high_cycles=4)
    await host.settle()
    expect_results(host.results[first:], FirModel(coefficients).run(samples), "13-clock period")
    await expect_status_flags(host, 0, "13-clock period")


@cocotb.test(timeout_time=100, timeout_unit="ms")
async def test_minimum_strobe_low_time(dut):
    """Exactly three clocks of strobe low re-arms the next request at any phase."""
    host = await start_host(dut, seed=409)
    coefficients = [50, -20, 60, 8, -9, 33, -44, 21]
    rng = random.Random(4091)
    await host.load_filter(coefficients)
    samples = [rng.randint(-128, 127) for _ in range(400)]
    first = len(host.results)
    await host.random_phase()
    for sample in samples:
        dut.sample_strobe.value = 0
        dut.ui_in.value = sample & 0xFF
        await Timer(3 * CLK_PERIOD_NS, "ns")
        assert str(dut.ready.value) == "1", "ready must be back after 13 clocks"
        dut.sample_strobe.value = 1
        # Random high times from 10 to 11 clocks walk the edges through every phase.
        await Timer(rng.randrange(1_000_000, 1_100_000), "ps")
    dut.sample_strobe.value = 0
    await host.settle()
    expect_results(host.results[first:], FirModel(coefficients).run(samples), "3-clock low time")
    await expect_status_flags(host, 0, "3-clock low time")


@cocotb.test(timeout_time=100, timeout_unit="ms")
async def test_host_too_slow_to_watch_ready(dut):
    """A host on fixed delays works without ever seeing the short pulses on ready and valid.

    A polling microcontroller can miss the nine clocks that ready is low and the one clock
    of output_valid. Capture always lands within three clocks of the strobe and the result
    within twelve, so holding the data for four clocks and reading at thirteen is enough.
    """
    host = await start_host(dut, seed=410)
    coefficients = [50, -20, 60, 8, -9, 33, -44, 21]
    rng = random.Random(4101)
    await host.load_filter(coefficients)
    model = FirModel(coefficients)
    for _ in range(400):
        sample = rng.randint(-128, 127)
        await host.random_phase()
        dut.ui_in.value = sample & 0xFF
        await Timer(CLK_PERIOD_NS, "ns")
        dut.sample_strobe.value = 1
        await Timer(4 * CLK_PERIOD_NS, "ns")
        dut.ui_in.value = ~sample & 0xFF
        dut.sample_strobe.value = 0
        await Timer(9 * CLK_PERIOD_NS, "ns")
        wanted = model.step(sample)
        assert dut.uo_out.value.to_signed() == wanted.output, f"sample {sample}"
        assert int(dut.saturated.value) == int(wanted.saturated), f"sample {sample}"
        await Timer(5 * CLK_PERIOD_NS, "ns")
    await expect_status_flags(host, 0, "fixed-delay host")


@cocotb.test(timeout_time=100, timeout_unit="ms")
async def test_strobe_contract(dut):
    """One rising edge makes one acceptance, and the data is taken at acceptance."""
    host = await start_host(dut, seed=404)
    await host.load_filter([128] + [0] * 7)

    # A strobe held high for a long time captures once.
    dut.ui_in.value = 33
    await ClockCycles(dut.clk, 1)
    dut.sample_strobe.value = 1
    await ClockCycles(dut.clk, 100)
    assert host.results == [(33, 0)], f"held strobe gave {host.results}"
    assert str(dut.ready.value) == "1", "ready must return even if the strobe stays high"
    dut.sample_strobe.value = 0
    await ClockCycles(dut.clk, 100)
    assert host.results == [(33, 0)], "the falling edge must not capture"

    # The input bus has no effect unless a request is made.
    for value in (1, 2, 3, 0xFF, 0x80):
        dut.ui_in.value = value
        await ClockCycles(dut.clk, 7)
    assert host.results == [(33, 0)]
    assert dut.uo_out.value.to_signed() == 33

    # Minimum legal pulse width and gap, at many phases. Three clocks high is the
    # shortest pulse a host may send. The data hold rule then applies by itself.
    host.results.clear()
    samples = [random.Random(4041).randint(-128, 127) for _ in range(100)]
    for sample in samples:
        await host.wait_ready()
        await host.random_phase()
        dut.ui_in.value = sample & 0xFF
        await Timer(CLK_PERIOD_NS, "ns")
        dut.sample_strobe.value = 1
        await Timer(3 * CLK_PERIOD_NS, "ns")
        dut.sample_strobe.value = 0
        if str(dut.ready.value) == "1":
            await FallingEdge(dut.ready)
        dut.ui_in.value = ~sample & 0xFF
        await Timer(3 * CLK_PERIOD_NS, "ns")
    await host.settle()
    assert host.results == [(s, 0) for s in samples]
    await expect_status_flags(host, 0, "contract pulses")


@cocotb.test(timeout_time=100, timeout_unit="ms")
async def test_busy_handling(dut):
    """Requests made while busy are dropped, flagged, and harm nothing."""
    host = await start_host(dut, seed=405)
    coefficients = [70, 40, 30, -20, 15, 10, -5, 2]
    await host.load_filter(coefficients)
    model = FirModel(coefficients)
    await host.run_samples([55, -66, 77])
    model.run([55, -66, 77])

    # Raise a second strobe at every clock from acceptance onward. Raised k clocks
    # after acceptance, it reaches the controller k + 3 clocks after acceptance, and
    # the controller is idle again from clock 10. So k <= 6 is dropped and k >= 7 is a
    # legal new sample. Either way the numbers must stay exact.
    dropped = accepted = 0
    for offset in range(1, 14):
        first = len(host.results)
        await host.settle()
        wanted_first = 25 + offset
        wanted_second = -40 - offset
        dut.ui_in.value = wanted_first & 0xFF
        await RisingEdge(dut.clk)
        dut.sample_strobe.value = 1
        await FallingEdge(dut.ready)
        dut.ui_in.value = wanted_second & 0xFF
        dut.sample_strobe.value = 0
        await ClockCycles(dut.clk, offset)
        dut.sample_strobe.value = 1
        await ClockCycles(dut.clk, 4)
        dut.sample_strobe.value = 0
        await ClockCycles(dut.clk, 20)
        await host.settle()

        new = host.results[first:]
        expected = [model.step(wanted_first)]
        status = await host.read_status()
        if status & STATUS_OVERRUN:
            dropped += 1
        else:
            accepted += 1
            expected.append(model.step(wanted_second))
        expect_results(new, expected, f"second strobe {offset} clocks after acceptance")
        await host.clear_flags()
        await expect_status_flags(host, 0, "after clearing overrun")
    dut._log.info("Second strobes: %d dropped as busy, %d accepted once idle", dropped, accepted)
    assert (dropped, accepted) == (6, 7), f"busy window moved: {dropped} dropped, {accepted} accepted"

    # A strobe that rises while busy and stays high must not capture when ready
    # returns, because that edge has already been used up.
    await host.settle()
    first = len(host.results)
    dut.ui_in.value = 11
    await ClockCycles(dut.clk, 1)
    dut.sample_strobe.value = 1
    await FallingEdge(dut.ready)
    await ClockCycles(dut.clk, 1)
    dut.sample_strobe.value = 0
    await ClockCycles(dut.clk, 3)
    dut.sample_strobe.value = 1
    await ClockCycles(dut.clk, 60)
    expected = model.step(11)
    assert host.results[first:] == [(expected.output, int(expected.saturated))]
    assert str(dut.ready.value) == "1"
    dut.sample_strobe.value = 0
    await ClockCycles(dut.clk, 5)
    await host.clear_flags()

    # The filter carries on correctly afterwards.
    samples = [12, -13, 14, -15]
    expect_results(await host.run_samples(samples), model.run(samples), "after busy tests")
    await expect_status_flags(host, 0, "after busy tests")


@cocotb.test(timeout_time=500, timeout_unit="ms")
async def test_coefficient_write_during_calculation(dut):
    """A write landing at any clock around a calculation is atomic or rejected."""
    host = await start_host(dut, seed=406)
    old = [20, -30, 40, -50, 60, -70, 80, -90]
    prior = [5, -6, 7, -8, 9, -10, 11]  # small enough that nothing clips
    sample = 15
    new_value = 120
    target = 2
    new = list(old)
    new[target] = new_value

    model_old = FirModel(old)
    model_old.run(prior)
    y_old = model_old.step(sample)
    model_new = FirModel(new)
    model_new.run(prior)
    y_new = model_new.step(sample)
    assert y_old.output != y_new.output and not (y_old.saturated or y_new.saturated)

    outcomes = {"rejected": 0, "used_new": 0, "used_old": 0}
    for offset in range(-16, 16):
        await host.load_filter(old)
        await host.run_samples(prior)

        first = len(host.results)
        dut.ui_in.value = sample
        await RisingEdge(dut.clk)
        frame = cocotb.start_soon(host.reg_write(REG_COEF0 + target, new_value, phase=False))
        # Chip select rises 24 full bits and one half period after it falls.
        await Timer(24_500 + offset * CLK_PERIOD_NS - CLK_PERIOD_NS, "ns")
        dut.sample_strobe.value = 1
        await ClockCycles(dut.clk, 5)
        dut.sample_strobe.value = 0
        await frame
        await host.settle()
        results = host.results[first:]
        assert len(results) == 1, f"offset {offset}: {results}"
        output = results[0][0]

        status = await host.read_status()
        readback = await host.read_coef(target)
        if status & STATUS_REJECTED:
            outcomes["rejected"] += 1
            assert readback == old[target], f"offset {offset}: rejected write changed the value"
            assert output == y_old.output, f"offset {offset}: rejected write affected the output"
        else:
            assert readback == new_value, f"offset {offset}: accepted write was lost"
            assert output in (y_old.output, y_new.output), f"offset {offset}: mixed result"
            outcomes["used_new" if output == y_new.output else "used_old"] += 1
        await host.clear_flags()

    dut._log.info("Write overlap outcomes across offsets: %s", outcomes)
    assert all(count > 0 for count in outcomes.values()), f"sweep missed a case: {outcomes}"
    # A calculation holds off writes for its 9 active cycles.
    assert outcomes["rejected"] == 9


@cocotb.test(timeout_time=500, timeout_unit="ms")
async def test_clear_history_during_calculation(dut):
    """A clear landing at any clock around a calculation never corrupts it."""
    host = await start_host(dut, seed=407)
    coefficients = [20, 30, 40, 50, 60, 70, 80, 90]
    prior = [50, 60, 70, 80, 90, 100, 110]
    sample = 55

    outcomes = {"rejected": 0, "cleared_before": 0, "cleared_after": 0}
    for offset in range(-16, 16):
        await host.load_filter(coefficients)
        await host.run_samples(prior)
        model = FirModel(coefficients)
        model.run(prior)
        kept = model.step(sample).output
        cleared_first = FirModel(coefficients).step(sample).output
        assert kept != cleared_first

        first = len(host.results)
        dut.ui_in.value = sample
        await RisingEdge(dut.clk)
        frame = cocotb.start_soon(
            host.reg_write(REG_CONTROL, CONTROL_CLEAR_HISTORY, phase=False)
        )
        await Timer(24_500 + offset * CLK_PERIOD_NS - CLK_PERIOD_NS, "ns")
        dut.sample_strobe.value = 1
        await ClockCycles(dut.clk, 5)
        dut.sample_strobe.value = 0
        await frame
        await host.settle()
        results = host.results[first:]
        assert len(results) == 1, f"offset {offset}: {results}"
        output = results[0][0]

        # Probe what the history now holds: the next result shows if it was kept.
        status = await host.read_status()
        probe = 3
        next_output = (await host.run_samples([probe]))[0][0]
        if status & STATUS_REJECTED:
            outcomes["rejected"] += 1
            assert output == kept, f"offset {offset}: rejected clear affected the output"
            assert next_output == model.step(probe).output, f"offset {offset}: history lost"
        elif output == cleared_first:
            # Cleared on or before the capture edge: the new sample must survive.
            outcomes["cleared_before"] += 1
            after = FirModel(coefficients)
            after.step(sample)
            assert next_output == after.step(probe).output, f"offset {offset}: sample lost"
        else:
            # Cleared after the calculation, so history holds nothing.
            outcomes["cleared_after"] += 1
            assert output == kept, f"offset {offset}: corrupted result {output}"
            assert next_output == FirModel(coefficients).step(probe).output, (
                f"offset {offset}: history not cleared"
            )
        await host.clear_flags()

    dut._log.info("Clear overlap outcomes across offsets: %s", outcomes)
    assert all(count > 0 for count in outcomes.values()), f"sweep missed a case: {outcomes}"
    assert outcomes["rejected"] == 9


@cocotb.test(timeout_time=50, timeout_unit="ms")
async def test_spi_read_during_calculation(dut):
    """Reading over SPI while samples run returns correct data and disturbs nothing."""
    host = await start_host(dut, seed=408)
    coefficients = [11, -22, 33, -44, 55, -66, 77, -88]
    await host.load_filter(coefficients)
    model = FirModel(coefficients)
    rng = random.Random(4081)
    samples = [rng.randint(-128, 127) for _ in range(150)]

    async def reader():
        while True:
            index = rng.randrange(NUM_TAPS)
            assert await host.read_coef(index) == coefficients[index]

    task = cocotb.start_soon(reader())
    results = await host.stream_uniform(samples, MAX_RATE_PERIOD_PS)
    task.cancel()
    dut.spi_cs_n.value = 1
    dut.spi_sclk.value = 0
    await ClockCycles(dut.clk, 10)
    expect_results(results, model.run(samples), "reads during samples")
    await expect_status_flags(host, 0, "reads during samples")


# ----- Filter demonstrations -----


def tone_amplitude(signal, frequency: float) -> float:
    """Amplitude of one tone, by correlation over a whole number of cycles."""
    n = len(signal)
    real = sum(v * math.cos(2 * math.pi * frequency * i) for i, v in enumerate(signal))
    imag = sum(v * math.sin(2 * math.pi * frequency * i) for i, v in enumerate(signal))
    return 2 * math.hypot(real, imag) / n


async def run_filter_demo(dut, name: str, tone_amplitude_lsb: int, seed: int) -> None:
    design = FILTER_DESIGNS[name]
    host = await start_host(dut, seed=seed)
    coefficients = design["coefficients"]
    await host.load_filter(coefficients)

    tones = design["tones"]
    # Startup samples are discarded so the analysis sees only the settled response.
    settle = NUM_TAPS
    count = design["analysis_samples"] + settle
    assert tone_amplitude_lsb * len(tones) < 127, "tones must stay below clipping"
    samples = [
        round(sum(tone_amplitude_lsb * math.sin(2 * math.pi * f * n) for f in tones.values()))
        for n in range(count)
    ]

    results = await host.stream_uniform(samples, MAX_RATE_PERIOD_PS)
    expect_results(results, FirModel(coefficients).run(samples), name)
    assert not any(r[1] for r in results), "the demonstration must not clip"

    analysis_in = samples[settle:]
    analysis_out = [r[0] for r in results][settle:]
    gains = {}
    for tone, frequency in tones.items():
        amplitude_in = tone_amplitude(analysis_in, frequency)
        amplitude_out = tone_amplitude(analysis_out, frequency)
        gains[tone] = 20 * math.log10(max(amplitude_out, 1e-9) / amplitude_in)
    dut._log.info(
        "%s measured gain in dB: %s, designed: %s",
        name,
        {tone: round(gain, 2) for tone, gain in gains.items()},
        design["response_db"],
    )

    for tone in design["pass_tones"]:
        assert gains[tone] >= design["min_pass_db"], f"{name}: {tone} gain {gains[tone]:.2f} dB"
        assert abs(gains[tone] - design["response_db"][tone]) <= 1.0, f"{name}: {tone} off design"
    for tone in design["stop_tones"]:
        assert gains[tone] <= design["max_stop_db"], f"{name}: {tone} gain {gains[tone]:.2f} dB"

    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / f"demo_{name}.json").write_text(
        json.dumps(
            {
                "filter": name,
                "coefficients": coefficients,
                "sample_rate_hz": 500_000,
                "input": samples,
                "output": [r[0] for r in results],
                "settle_samples": settle,
                "tones": tones,
                "measured_gain_db": gains,
                "designed_gain_db": design["response_db"],
                "min_pass_db": design["min_pass_db"],
                "max_stop_db": design["max_stop_db"],
                "pass_tones": design["pass_tones"],
                "stop_tones": design["stop_tones"],
            },
            indent=1,
        )
    )


@cocotb.test(timeout_time=100, timeout_unit="ms")
async def test_lowpass_demo(dut):
    """Low-pass: keeps the low tone and attenuates the high tone."""
    await run_filter_demo(dut, "lowpass", tone_amplitude_lsb=50, seed=501)


@cocotb.test(timeout_time=100, timeout_unit="ms")
async def test_highpass_demo(dut):
    """High-pass: attenuates the low tone and keeps the high tone."""
    await run_filter_demo(dut, "highpass", tone_amplitude_lsb=50, seed=502)


@cocotb.test(timeout_time=100, timeout_unit="ms")
async def test_bandpass_demo(dut):
    """Band-pass: keeps the middle tone and attenuates the two outer tones."""
    await run_filter_demo(dut, "bandpass", tone_amplitude_lsb=35, seed=503)

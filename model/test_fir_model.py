"""Tests of the reference model itself: run with `pytest model`.

The hardware is judged against this model, so these check it against hand-worked
values and the formula in the proposal rather than against the hardware.
"""

import json
import math
from pathlib import Path

import pytest

from fir_model import FirModel, product, scale_and_saturate


def test_reset_defaults_are_a_moving_average():
    model = FirModel()
    assert model.coefficients == [16] * 8
    assert model.history == [0] * 8
    results = model.run([80] + [0] * 8)
    assert [r.output for r in results] == [10] * 8 + [0]


@pytest.mark.parametrize(
    "stored, weight",
    [(-128, -1.0), (0, 0.0), (64, 0.5), (128, 1.0), (16, 0.125), (1, 1 / 128)],
)
def test_coefficient_interpretation(stored, weight):
    assert stored / 128 == weight


@pytest.mark.parametrize(
    "accumulator, output, saturated",
    [
        (0, 0, False),
        (127, 0, False),
        (128, 1, False),
        (-1, -1, False),  # floor, not truncation toward zero
        (-128, -1, False),
        (-129, -2, False),
        (16383, 127, False),
        (16384, 127, True),
        (-16384, -128, False),
        (-16385, -128, True),
        (131072, 127, True),
        (-131072, -128, True),
    ],
)
def test_scale_and_saturate_hand_values(accumulator, output, saturated):
    assert scale_and_saturate(accumulator) == (output, saturated)


def test_scale_and_saturate_matches_the_formula():
    for accumulator in range(-140000, 140000, 37):
        floor = math.floor(accumulator / 128)
        expected = max(-128, min(127, floor))
        assert scale_and_saturate(accumulator) == (expected, expected != floor)


def test_hand_worked_filter_step():
    model = FirModel([128, -64, 32, 0, 0, 0, 0, 1])
    model.step(10)
    model.step(-20)
    result = model.step(30)
    # 30*128 + (-20)*(-64) + 10*32 = 3840 + 1280 + 320 = 5440, and 5440 / 128 = 42.5
    assert result.accumulator == 5440
    assert result.output == 42
    assert result.saturated is False


def test_history_shifts_and_clears():
    model = FirModel([0, 0, 0, 0, 0, 0, 0, 128])
    outputs = [model.step(v).output for v in range(1, 10)]
    assert outputs == [0, 0, 0, 0, 0, 0, 0, 1, 2]
    model.clear_history()
    assert model.history == [0] * 8
    assert model.coefficients[7] == 128


def test_accumulator_range_fits_twenty_bits():
    for sample in (-128, 127):
        for coefficient in (-128, 128):
            total = FirModel([coefficient] * 8).run([sample] * 8)[-1].accumulator
            assert -(2**19) <= total < 2**19
            assert -(2**16) <= product(sample, coefficient) < 2**16


@pytest.mark.parametrize("value", [129, -129, 256])
def test_illegal_coefficients_are_refused(value):
    with pytest.raises(ValueError):
        FirModel([value] * 8)


@pytest.mark.parametrize("sample", [128, -129])
def test_illegal_samples_are_refused(sample):
    with pytest.raises(ValueError):
        FirModel().step(sample)


def test_demonstration_coefficients_are_legal_and_meet_their_limits():
    designs = json.loads(Path(__file__).with_name("filter_coeffs.json").read_text())
    assert set(designs) == {"lowpass", "highpass", "bandpass"}
    for design in designs.values():
        FirModel(design["coefficients"])
        for tone in design["pass_tones"]:
            assert design["response_db"][tone] >= design["min_pass_db"]
        for tone in design["stop_tones"]:
            assert design["response_db"][tone] <= design["max_stop_db"]

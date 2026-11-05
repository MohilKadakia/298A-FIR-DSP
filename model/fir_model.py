"""Bit-exact integer reference model of the TinyFIR datapath.

This is the arithmetic in section 4 of the project proposal:

    A[n] = sum(C[k] * X[n - k], k = 0..7)
    Y[n] = max(-128, min(127, floor(A[n] / 128)))

The model uses only the standard library so the cocotb regression can import it
without extra dependencies. Python's >> on int floors, the same rounding as the
hardware's arithmetic shift.
"""

from dataclasses import dataclass

NUM_TAPS = 8
SAMPLE_MIN, SAMPLE_MAX = -128, 127
COEF_MIN, COEF_MAX = -128, 128
OUTPUT_MIN, OUTPUT_MAX = -128, 127
COEF_RESET = 16
COEF_SCALE = 128
OUTPUT_SHIFT = 7
ACC_BITS = 20
PRODUCT_BITS = 17


@dataclass(frozen=True)
class FirResult:
    output: int
    saturated: bool
    accumulator: int


def product(sample: int, coefficient: int) -> int:
    """Return the multiplier output for a legal sample and coefficient."""
    if not SAMPLE_MIN <= sample <= SAMPLE_MAX:
        raise ValueError(f"sample {sample} is outside the signed 8-bit range")
    if not COEF_MIN <= coefficient <= COEF_MAX:
        raise ValueError(f"coefficient {coefficient} is outside {COEF_MIN}..{COEF_MAX}")
    return sample * coefficient


def scale_and_saturate(accumulator: int) -> tuple[int, bool]:
    """Convert an accumulator value to the 8-bit output and saturation flag."""
    scaled = accumulator >> OUTPUT_SHIFT
    if scaled > OUTPUT_MAX:
        return OUTPUT_MAX, True
    if scaled < OUTPUT_MIN:
        return OUTPUT_MIN, True
    return scaled, False


class FirModel:
    """Filter state as seen from the chip's pins, starting from reset defaults."""

    def __init__(self, coefficients=None):
        self.coefficients = [COEF_RESET] * NUM_TAPS
        self.history = [0] * NUM_TAPS
        if coefficients is not None:
            self.set_coefficients(coefficients)

    def set_coefficients(self, coefficients) -> None:
        coefficients = list(coefficients)
        if len(coefficients) != NUM_TAPS:
            raise ValueError(f"expected {NUM_TAPS} coefficients, got {len(coefficients)}")
        for value in coefficients:
            if not COEF_MIN <= value <= COEF_MAX:
                raise ValueError(f"coefficient {value} is outside {COEF_MIN}..{COEF_MAX}")
        self.coefficients = coefficients

    def clear_history(self) -> None:
        self.history = [0] * NUM_TAPS

    def step(self, sample: int) -> FirResult:
        """Accept one sample and return the published result."""
        if not SAMPLE_MIN <= sample <= SAMPLE_MAX:
            raise ValueError(f"sample {sample} is outside the signed 8-bit range")
        self.history = [sample] + self.history[:-1]
        accumulator = sum(
            product(x, c) for x, c in zip(self.history, self.coefficients)
        )
        output, saturated = scale_and_saturate(accumulator)
        return FirResult(output, saturated, accumulator)

    def run(self, samples) -> list[FirResult]:
        return [self.step(sample) for sample in samples]

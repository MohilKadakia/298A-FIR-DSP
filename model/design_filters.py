import json
from pathlib import Path

import numpy as np
from scipy.signal import remez

COEF_SCALE = 128
COEF_LIMIT = 128
NUM_TAPS = 16
ANALYSIS_SAMPLES = 400

# Equiripple designs place the stopband edge exactly, so each stop tone sits on
# the edge of its band. With 16 taps the transition bands are much narrower than
# eight taps allow. 9-bit coefficients put the stopband floor near -35 dB, so the
# weights favour the stopband.


def lowpass() -> list[int]:
    taps = quantize(remez(16, [0, 0.06, 0.2, 0.5], [1, 0], weight=[1, 8], fs=1.0))
    return absorb_rounding(taps, COEF_SCALE)


def highpass() -> list[int]:
    # A symmetric even-length filter is forced to zero at Nyquist, which rules out
    # a high-pass. This uses fifteen active symmetric taps and leaves the sixteenth
    # at zero. The centre tap absorbs rounding so the filter still rejects DC
    # exactly and stays symmetric.
    taps = quantize(remez(15, [0, 0.17, 0.3, 0.5], [0, 1], weight=[4, 1], fs=1.0))
    return absorb_rounding(taps, 0)


def bandpass() -> list[int]:
    # Fifteen active taps for the same reason as the high-pass. A band centred on
    # fs/4 has alternate taps at zero.
    bands = [0, 0.07, 0.19, 0.31, 0.43, 0.5]
    taps = remez(15, bands, [0, 1, 0], weight=[8, 1, 8], fs=1.0)
    return quantize(taps / gain(taps, 0.25))


def absorb_rounding(taps: list[int], total: int) -> list[int]:
    """Fix the sum (the DC gain) by adjusting the centre, keeping the taps symmetric."""
    taps = list(taps)
    error = total - sum(taps)
    left, right = (len(taps) - 1) // 2, len(taps) // 2
    if left == right:
        taps[left] += error
    else:
        if error % 2:
            raise ValueError(f"cannot split a rounding error of {error} over the centre pair")
        taps[left] += error // 2
        taps[right] += error // 2
    return taps


FILTERS = {
    "lowpass": {
        "design": lowpass,
        "tones": {"low": 20 / 400, "high": 80 / 400},
        "pass_tones": ["low"],
        "stop_tones": ["high"],
        "min_pass_db": -2.0,
        "max_stop_db": -30.0,
    },
    "highpass": {
        "design": highpass,
        "tones": {"low": 68 / 400, "high": 160 / 400},
        "pass_tones": ["high"],
        "stop_tones": ["low"],
        "min_pass_db": -2.0,
        "max_stop_db": -35.0,
    },
    "bandpass": {
        "design": bandpass,
        "tones": {"low": 28 / 400, "mid": 100 / 400, "high": 172 / 400},
        "pass_tones": ["mid"],
        "stop_tones": ["low", "high"],
        "min_pass_db": -2.0,
        "max_stop_db": -35.0,
    },
}


def gain(taps, frequency: float) -> float:
    k = np.arange(len(taps))
    return float(np.abs(np.sum(np.asarray(taps) * np.exp(-2j * np.pi * frequency * k))))


def quantize(taps) -> list[int]:
    return [int(v) for v in np.round(np.asarray(taps) * COEF_SCALE)]


def response_db(coefficients: list[int], frequency: float) -> float:
    return 20 * np.log10(max(gain(coefficients, frequency) / COEF_SCALE, 1e-12))


def build(spec: dict) -> dict:
    coefficients = spec["design"]()
    coefficients += [0] * (NUM_TAPS - len(coefficients))
    if not all(-COEF_LIMIT <= c <= COEF_LIMIT for c in coefficients):
        raise ValueError(f"illegal coefficient in {coefficients}")
    return {
        "coefficients": coefficients,
        "analysis_samples": ANALYSIS_SAMPLES,
        "tones": spec["tones"],
        "pass_tones": spec["pass_tones"],
        "stop_tones": spec["stop_tones"],
        "min_pass_db": spec["min_pass_db"],
        "max_stop_db": spec["max_stop_db"],
        "response_db": {
            tone: round(float(response_db(coefficients, f)), 2) for tone, f in spec["tones"].items()
        },
    }


def main() -> None:
    designs = {name: build(spec) for name, spec in FILTERS.items()}
    output = Path(__file__).with_name("filter_coeffs.json")
    output.write_text(json.dumps(designs, indent=2) + "\n")
    for name, result in designs.items():
        print(
            f"{name:9s} {result['coefficients']}  sum={sum(result['coefficients'])}"
            f"  {result['response_db']}"
        )


if __name__ == "__main__":
    main()

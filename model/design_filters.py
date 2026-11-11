import json
from pathlib import Path

import numpy as np
from scipy.signal import firls, firwin

COEF_SCALE = 128
COEF_LIMIT = 128
NUM_TAPS = 8
ANALYSIS_SAMPLES = 400


def lowpass() -> list[int]:
    return quantize(firwin(8, 0.15, fs=1.0))


def highpass() -> list[int]:
    # A symmetric even-length filter is forced to zero at Nyquist, which rules out
    # a high-pass. This uses seven active symmetric taps and leaves the eighth at
    # zero. The centre tap absorbs rounding so the filter still rejects DC exactly
    # and stays symmetric.
    taps = quantize(firwin(7, 0.33, pass_zero=False, fs=1.0))
    taps[3] -= sum(taps)
    return taps


def bandpass() -> list[int]:
    # Least squares handles this better than a windowed design, which leaves
    # strong leakage at both band edges with so few taps. A band centred on fs/4
    # has alternate taps at zero.
    bands = [0, 0.08, 0.17, 0.33, 0.42, 0.5]
    taps = firls(7, bands, [0, 0, 1, 1, 0, 0], fs=1.0)
    return quantize(taps / gain(taps, 0.25))


FILTERS = {
    "lowpass": {
        "design": lowpass,
        "tones": {"low": 20 / 400, "high": 160 / 400},
        "pass_tones": ["low"],
        "stop_tones": ["high"],
        "min_pass_db": -2.0,
        "max_stop_db": -35.0,
    },
    "highpass": {
        "design": highpass,
        "tones": {"low": 20 / 400, "high": 160 / 400},
        "pass_tones": ["high"],
        "stop_tones": ["low"],
        "min_pass_db": -2.0,
        "max_stop_db": -35.0,
    },
    "bandpass": {
        "design": bandpass,
        "tones": {"low": 20 / 400, "mid": 100 / 400, "high": 180 / 400},
        "pass_tones": ["mid"],
        "stop_tones": ["low", "high"],
        "min_pass_db": -2.0,
        "max_stop_db": -25.0,
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

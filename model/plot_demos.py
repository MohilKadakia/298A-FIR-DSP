#!/usr/bin/env python3
"""Plot the filter demonstrations from the regression's recorded chip output.

Run the regression first (it writes test/output/demo_*.json), then run this to
regenerate the figures in docs/figures. Needs NumPy and Matplotlib.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "test" / "output"
FIGURES = ROOT / "docs" / "figures"
FILTERS = ("lowpass", "highpass", "bandpass")
TITLES = {"lowpass": "Low-pass", "highpass": "High-pass", "bandpass": "Band-pass"}

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
AXIS = "#c3c2b7"
GRID = "#e1e0d9"
SERIES_1 = "#2a78d6"
SERIES_2 = "#eb6834"
RESPONSE_FLOOR_DB = -60

plt.rcParams.update(
    {
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "font.size": 10,
        "text.color": INK,
        "axes.labelcolor": INK_SECONDARY,
        "axes.titlecolor": INK,
        "axes.titlesize": 11,
        "axes.titleweight": "semibold",
        "axes.titlelocation": "left",
        "axes.edgecolor": AXIS,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.7,
        "xtick.color": INK_SECONDARY,
        "ytick.color": INK_SECONDARY,
        "xtick.major.size": 0,
        "ytick.major.size": 0,
        "lines.solid_capstyle": "round",
        "lines.solid_joinstyle": "round",
    }
)


def load(name: str) -> dict:
    return json.loads((RESULTS / f"demo_{name}.json").read_text())


def response_db(coefficients, frequencies) -> np.ndarray:
    k = np.arange(len(coefficients))
    phases = np.exp(-2j * np.pi * np.outer(frequencies, k))
    magnitude = np.abs(phases @ np.asarray(coefficients)) / 128
    return 20 * np.log10(np.maximum(magnitude, 1e-6))


def plot_frequency_response() -> None:
    frequencies = np.linspace(0, 0.5, 801)
    figure, axes = plt.subplots(1, 3, figsize=(10, 3.7), sharey=True, layout="constrained")
    for axis, name in zip(axes, FILTERS):
        demo = load(name)
        axis.plot(frequencies, response_db(demo["coefficients"], frequencies), color=SERIES_1,
                  linewidth=1.6, label="Designed response")
        tones = demo["tones"]
        measured = demo["measured_gain_db"]
        axis.plot(
            [tones[t] for t in tones], [measured[t] for t in tones], linestyle="none", marker="o",
            markersize=7, markerfacecolor=SERIES_2, markeredgecolor=SURFACE, markeredgewidth=1.4,
            label="Measured at chip pins", zorder=3, clip_on=False,
        )
        for tone in tones:
            # A curve this steep runs through a label placed above the point, so a stopband
            # label goes beside it, on the side the curve is not on.
            side = (1 if tones[tone] < 0.25 else -1) if measured[tone] < -10 else 0
            axis.annotate(
                f"{measured[tone]:.1f} dB", (tones[tone], measured[tone]), textcoords="offset points",
                xytext=(side * 9, 0 if side else 9), ha={1: "left", -1: "right", 0: "center"}[side],
                va="center" if side else "bottom", fontsize=9, color=INK,
            )
        axis.set_title(TITLES[name])
        axis.set_xlim(0, 0.5)
        axis.set_ylim(RESPONSE_FLOOR_DB, 10)
        axis.set_xlabel("Frequency (fraction of sample rate)")
    axes[0].set_ylabel("Gain (dB)")
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="outside upper right", ncols=2, frameon=False, fontsize=9)
    figure.savefig(FIGURES / "frequency_response.png", dpi=110)
    plt.close(figure)


def plot_waveforms() -> None:
    window = 60
    figure, axes = plt.subplots(3, 1, figsize=(10, 6.2), sharex=True, layout="constrained")
    for axis, name in zip(axes, FILTERS):
        demo = load(name)
        start = demo["settle_samples"]
        n = np.arange(window)
        axis.plot(n, demo["input"][start:start + window], color=SERIES_2, linewidth=1.3,
                  label="Input sample")
        axis.plot(n, demo["output"][start:start + window], color=SERIES_1, linewidth=1.8,
                  label="Chip output")
        coefficients = ", ".join(str(c) for c in demo["coefficients"])
        axis.set_title(f"{TITLES[name]}   coefficients [{coefficients}] / 128")
        axis.set_ylim(-128, 127)
        axis.set_yticks([-100, -50, 0, 50, 100])
        axis.set_xlim(0, window - 1)
        axis.set_ylabel("Value")
    axes[0].legend(loc="upper right", ncols=2, frameon=False, fontsize=9)
    axes[-1].set_xlabel("Sample number, after the settling samples")
    figure.savefig(FIGURES / "demo_waveforms.png", dpi=110)
    plt.close(figure)


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    plot_frequency_response()
    plot_waveforms()
    for path in sorted(FIGURES.glob("*.png")):
        print(f"{path.relative_to(ROOT)}: {path.stat().st_size // 1024} kB")


if __name__ == "__main__":
    main()

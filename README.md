![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# TinyFIR: SPI-Programmable 8-Tap FIR Filter

TinyFIR is a programmable 8-tap FIR filter for Tiny Tapeout on GF180, in a 1x2 tile. Samples enter on eight parallel pins, coefficients load over SPI, and one shared multiplier and accumulator process the eight taps in turn. Loading different coefficients makes the same hardware a low-pass, high-pass or band-pass filter.

- [Datasheet](docs/info.md): pinout, timing, SPI registers, and how to test the chip
- [Final report](docs/final_report.md): what was built, verification results, and physical status
- [Project proposal](docs/project_proposal.md): the original specification

## Repository layout

| Path | Contents |
|---|---|
| [src/](src/) | Verilog design. [project.v](src/project.v) is the Tiny Tapeout wrapper and [fir_core.v](src/fir_core.v) connects the blocks. |
| [model/](model/) | Integer reference model, filter design, and plotting |
| [test/](test/) | Pin-level cocotb regression, which runs on both RTL and gate-level netlists |
| [test/unit/](test/unit/) | Module-level tests, including exhaustive arithmetic and SPI sweeps |
| [scripts/](scripts/) | GF180 synthesis estimate and mutation testing |
| [docs/](docs/) | Datasheet, report, proposal and figures |

## Running the tests

You need Icarus Verilog and Python 3.11. Install the Python packages with `pip install -r test/requirements.txt`. See [test/README.md](test/README.md) for details.

```sh
make -C test                         # system regression, about 30 seconds
make -C test/unit                    # module tests, a few minutes
PYTHONPATH=model pytest model        # reference model tests
```

The same three steps run in the `test` workflow on every push. The `gds` workflow builds the chip layout with the official Tiny Tapeout flow, then runs the precheck and repeats the regression on the final gate-level netlist.

## Other tasks

```sh
pip install -r model/requirements.txt
python model/design_filters.py       # regenerate model/filter_coeffs.json
python model/plot_demos.py           # regenerate docs/figures after running the regression

scripts/synth_gf180.sh               # area and timing estimate, needs Yosys and the PDK
scripts/mutation_test.py             # check that the regression catches injected bugs
```

## About Tiny Tapeout

Tiny Tapeout is an educational project that makes it easier and cheaper to get digital and analog designs manufactured on a real chip. To learn more, visit https://tinytapeout.com.

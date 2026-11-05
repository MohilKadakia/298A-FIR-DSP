# TinyFIR testbench

These tests use [cocotb](https://docs.cocotb.org/en/stable/) and [Icarus Verilog](https://steveicarus.github.io/iverilog/). They need the Python packages in [requirements.txt](requirements.txt).

| File | Purpose |
|---|---|
| [test.py](test.py) | System regression, covering the verification plan in the proposal |
| [tinyfir_host.py](tinyfir_host.py) | Pin-level model of the external host: SPI, the sample handshake, and a result monitor |
| [tb.v](tb.v) | Instantiates the chip, models the `uio` pads, and names each pin |
| [unit/](unit/) | Module-level tests |

The system tests use only the chip's pins, so the same file runs on RTL and on gate-level netlists. Every test checks against the integer model in [../model/fir_model.py](../model/fir_model.py).

## How to run

RTL simulation:

```sh
make -B
```

To run a single test, set `COCOTB_TEST_FILTER`:

```sh
make -B COCOTB_TEST_FILTER=test_busy_handling
```

Module tests, all or one at a time:

```sh
make -C unit
make -C unit fir_mac
```

## Gate-level simulation

Copy the netlist from a hardened run to `gate_level_netlist.v`, set `PDK_ROOT`, and run:

```sh
make -B GATES=yes
```

The `gds` workflow does this on the final netlist. To try it before layout, [../scripts/synth_gf180.sh](../scripts/synth_gf180.sh) writes a post-synthesis `gate_level_netlist.v` in the same form.

## Waveforms

Each run writes `tb.fst`. By default it holds only the top-level pins, which keeps long regressions fast. To record the whole design, rebuild with:

```sh
make -B WAVES=all
```

View the file with GTKWave (`gtkwave tb.fst tb.gtkw`) or Surfer (`surfer tb.fst`).

## Results

The filter demonstrations write their input and output samples to `output/demo_*.json`. [../model/plot_demos.py](../model/plot_demos.py) turns these into the figures in [../docs/figures](../docs/figures).

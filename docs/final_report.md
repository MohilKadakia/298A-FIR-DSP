# TinyFIR Final Report

**Team:** Hamza Soofi, Gurpal Johal, Mohil Kadakia, and Ayaan Tunio  
**Status:** RTL and simulation are complete and passing. Place and route, the Tiny Tapeout precheck, and timing signoff have not been run, so the design is not yet ready to submit.

## 1. Summary

TinyFIR is a programmable 8-tap FIR filter for a 1x2 Tiny Tapeout tile on GF180. Coefficients load over SPI, samples enter on eight parallel pins, and one shared multiplier and accumulator process the eight taps in turn.

| Measure | Target | Result | Evidence |
|---|---|---|---|
| Processing latency | At most 16 clocks | 9 clocks | Simulation at 300 random input phases |
| Sample rate at 10 MHz | 500 ksample/s | Met, with no dropped or duplicated samples | Simulation at random phases |
| Fastest contract-legal rate at 10 MHz | Not specified | 769 ksample/s (13 clocks per sample) | Simulation at random phases |
| Random arithmetic against the model | At least 10,000 samples | 10,240 samples, 1,549 of them clipped, all exact | Simulation |
| Cell area | Fit the 112,783 µm² die | About 38,000 to 45,000 µm² (34% to 40%) | Synthesis estimate, before layout |
| Timing at 10 MHz (100 ns) | Close timing | About 25 ns of logic at the slow corner | Synthesis estimate, no wires |
| Physical checks | Pass | **Not run** | See section 6 |

The final simulation results hold on RTL and on the post-synthesis GF180 netlist. They have not yet been repeated on the final placed-and-routed netlist.

## 2. Design

![TinyFIR system architecture](figures/system_diagram.png)

For each accepted strobe, the circuit captures the sample, clears the accumulator, processes one tap per clock for eight clocks, and publishes the result on the ninth. The [datasheet](info.md) has the full pinout, timing, and register map.

| Block | Source | Cell area (µm²) | Flops |
|---|---|---:|---:|
| Multiplier and accumulator | [fir_mac.v](../src/fir_mac.v) | 12,238 | 20 |
| Coefficient registers and selection | [coef_regs.v](../src/coef_regs.v) | 9,769 | 72 |
| Sample history and selection | [sample_history.v](../src/sample_history.v) | 8,812 | 64 |
| SPI interface and synchronizers | [spi_interface.v](../src/spi_interface.v) | 4,801 | 36 |
| Scaling, saturation, output register | [output_stage.v](../src/output_stage.v) | 1,240 | 10 |
| Controller and tap counter | [fir_controller.v](../src/fir_controller.v) | 766 | 6 |
| Strobe synchronizer | [strobe_sync.v](../src/strobe_sync.v) | 263 | 3 |
| Status flags | [fir_core.v](../src/fir_core.v) | 220 | 2 |
| Reset synchronizer | [reset_sync.v](../src/reset_sync.v) | 149 | 2 |
| Wrapper | [project.v](../src/project.v) | 9 | 0 |
| **Total** | | **38,267** | **215** |

These figures are from area-oriented Yosys synthesis with the `tt_025C_3v30` library. They exclude the clock tree, repair buffers, and tap cells. Mapping for speed gives 45,236 µm².

## 3. Decisions the proposal left open

The proposal deferred these choices until implementation.

| Topic | Decision | Reason |
|---|---|---|
| SPI command byte | Bit 7 selects read, bits 6:4 must be zero, bits 3:0 are the address | Simple to decode, and it leaves room for later commands |
| Registers | `COEF0`-`COEF7` at 0x0-0x7, `STATUS` at 0x8, `CONTROL` at 0x9 | Covers everything the proposal asked for |
| Write during a calculation | Rejected and flagged, not deferred | Needs no pending-write state, and tells the host it broke the rule |
| SPI readback | Separate read mux | Reads never disturb a calculation, at a measured cost of about 1,100 µm² |
| Reset | Asserts asynchronously, releases on a clock edge | All flops leave reset in the same cycle, and gate-level simulation has no X problems |
| Strobe high through reset | `ready` stays low until the strobe is seen low | A strobe left high never captures a stray sample |
| Clock constraint | `CLOCK_PERIOD` raised from 20 ns to 100 ns | Matches the 10 MHz target. The estimated slow-corner path of about 25 ns would probably fail the template's 20 ns |

Two small additions go beyond the proposal: a sticky `STATUS` flag for requests dropped while busy, and a `CONTROL` bit that clears the status flags. Both make host errors visible through the pins.

The accumulator's top bit is redundant, because the largest magnitude, 131,072, fits in 19 bits. It stays at the 20 bits the proposal specified.

## 4. Verification

There are three levels of test.

- **System tests:** 28 cocotb tests that use only the chip's pins, so the same file runs on RTL and gate-level netlists. All 28 pass on both.
- **Module tests:** 16 tests across 7 blocks, including exhaustive sweeps. All pass.
- **Reference model tests:** 29 tests that check the integer model against hand-worked values and the proposal's formula. All pass.

| Proposal test | Test name | Result |
|---|---|---|
| Reset | `test_reset_defaults`, `test_reset_during_calculation`, `test_strobe_high_through_reset_is_not_a_request` | Pass |
| SPI writes and readback | `test_spi_write_and_readback`, `test_spi_value_range`, `test_spi_invalid_commands`, `test_spi_incomplete_and_overlong`, `test_spi_timing_margins`, `test_spi_sclk_high_at_chip_select_edges`, `test_status_and_control`, `test_uio_pin_directions` | Pass |
| Impulse response | `test_impulse_response` | Pass |
| Unity pass-through | `test_unity_pass_through`, all 256 input values | Pass |
| Random arithmetic | `test_random_arithmetic`, 10,240 samples across 10 coefficient sets | Pass |
| Overflow and sign handling | `test_overflow_and_sign` | Pass |
| Variable-rate input | `test_variable_rate`, `test_fastest_contract_rate`, `test_minimum_strobe_low_time`, `test_latency_budget`, `test_strobe_contract`, `test_host_too_slow_to_watch_ready` | Pass |
| Busy handling | `test_busy_handling`, `test_coefficient_write_during_calculation`, `test_clear_history_during_calculation`, `test_spi_read_during_calculation` | Pass |
| Low-pass, high-pass, and band-pass demonstrations | `test_lowpass_demo`, `test_highpass_demo`, `test_bandpass_demo` | Pass |
| Physical implementation | Not a simulation test | **Not run** |

The module tests cover every legal sample and coefficient product (65,792 pairs), every value of the scaled accumulator (8,192), all 65,536 SPI data words, and all 256 command bytes.

### Do the tests catch bugs?

Passing tests only help if they would fail on a broken design. [mutation_test.py](../scripts/mutation_test.py) injects one realistic bug at a time into a copy of the RTL and runs the system tests against it.

Of 82 injected bugs, the system tests caught 78. One of those, swapping the `ready` and `output_valid` pins, was caught only by the script's time limit, because the tests stalled rather than failing quickly. The remaining 4 have no effect that the system tests can see:

- Releasing reset directly from the pin behaves the same in simulation. The synchronizer guards against metastability, which simulation cannot show.
- Bit 19 of the accumulator can never differ from the bits below it, as noted in section 3.
- Two variants let the accumulator run freely outside a calculation. It is cleared on acceptance and read before it can change, so the pins cannot show the difference. The module tests catch one of these.

An earlier run found three real gaps: nothing checked that MISO stays low during writes, that MISO is low after an aborted read, or that a legal `CONTROL` value sent to a wrong address is rejected. A separate review of the RTL against the proposal, done by an AI agent reading the code without running it, then found a few more weak or missing checks and a Makefile path error that would have broken the CI workflow. All of these are fixed. That review found no RTL violations of the proposal, but it does not replace a human design review.

## 5. Filter demonstrations

Each filter ran through the chip's pins at 500 ksample/s, on 400 samples after discarding the settling samples. Every output sample matched the reference model exactly, with no clipping.

| Filter | Coefficients (/128) | Tone (fraction of sample rate) | Designed (dB) | Measured (dB) | Limit (dB) |
|---|---|---|---:|---:|---|
| Low-pass | 0, 3, 20, 41, 41, 20, 3, 0 | 0.05, pass | -0.50 | -0.51 | At least -2 |
| | | 0.40, stop | -41.96 | -52.58 | At most -35 |
| High-pass | 0, 6, -32, 52, -32, 6, 0, 0 | 0.40, pass | -1.52 | -1.53 | At least -2 |
| | | 0.05, stop | -43.65 | -42.40 | At most -35 |
| Band-pass | 0, -34, 0, 59, 0, -34, 0, 0 | 0.25, pass | -0.07 | -0.12 | At least -2 |
| | | 0.05, stop | -30.13 | -29.55 | At most -25 |
| | | 0.45, stop | -30.13 | -29.55 | At most -25 |

![Measured gain compared with the designed response](figures/frequency_response.png)

![Input and output for each demonstration filter](figures/demo_waveforms.png)

The low-pass stopband measures 10 dB better than designed because its output is smaller than one output step, which the 8-bit output cannot represent. That number reflects quantization, so it should not be read as better filter performance.

The limits were set after evaluating the quantized coefficients and before final verification, as the proposal required. That evaluation changed the band-pass design. The first attempt, a windowed filter with its DC gain corrected by one tap, lost its symmetry and reached only about -15 dB at the high tone. The final seven-tap least-squares design reaches -30 dB at both outer tones. Its DC gain is -9/128, about -23 dB, which is acceptable here because the demonstration tones have no DC component.

## 6. Physical implementation status

**The official flow has not been run.** It needs LibreLane with OpenROAD, Magic, and Netgen, which are not installed on the development machine. The prebuilt OpenROAD versions available are older than the LibreLane 3.0.14 that the Tiny Tapeout action uses, so a local run could not stand in for signoff.

What has been checked:

- A local copy of Tiny Tapeout's project tooling accepts `info.yaml`, the source list, and the datasheet. It resolves the die to 346.64 x 325.36 µm.
- Synthesis with the GF180 7-track library at the flow's 3.3 V corners gives these estimates, with no wires or clock tree:

| Corner | Estimated critical path | Slack against 100 ns |
|---|---:|---:|
| `tt_025C_3v30` | 12.2 ns | 87.8 ns |
| `ss_125C_3v00` | 24.6 ns | 75.4 ns |
| `ff_n40C_3v60` | 6.9 ns | 93.1 ns |

- In the synthesized netlist, every data and status output comes directly from a flop, there are no latches, and the only input-to-output path is chip select to the MISO enable, as intended.

What remains is to push the repository so the `gds` workflow can run. That job builds the layout and runs the precheck. It then repeats the system tests on the final gate-level netlist. Density, routing congestion, and hold timing are unknown until then, though the low utilization estimate suggests that fitting should not be a problem.

## 7. Known limits

- **Short `ready` and `output_valid` pulses.** `ready` is low for 9 clocks and `output_valid` lasts 1. A slow polling host can miss both, so the datasheet gives a fixed-delay procedure, which `test_host_too_slow_to_watch_ready` covers.
- **Reset with SPI active.** If reset releases while chip select is low and SCLK is high, the first SCLK level counts as a clock. A write in that frame is rejected and flagged, so it fails safely. This state is outside SPI mode 0 idle.
- **Simulation cannot show metastability.** The synchronizers follow standard practice, but only silicon can test them. Simulation also uses zero or unit delays, so real timing depends on the signoff run.
- **No silicon testing.** Testing the chip depends on fabrication and delivery dates.

## 8. How to reproduce

```sh
pip install -r test/requirements.txt
make -C test                         # system tests
make -C test/unit                    # module tests
PYTHONPATH=model pytest model        # reference model tests
scripts/mutation_test.py             # injected-bug check, needs several minutes
```

See the [README](../README.md) and [test instructions](../test/README.md) for gate-level simulation, regenerating coefficients, and regenerating these figures.

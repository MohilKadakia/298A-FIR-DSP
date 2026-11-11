# TinyFIR Final Report

**Team:** Hamza Soofi, Gurpal Johal, Mohil Kadakia, and Ayaan Tunio  
**Status:** RTL, simulation and the official Tiny Tapeout flow all pass for commit `c3968f1` (branch `heh`, CI run 42127859566). The layout meets 10 MHz at every signoff corner. Its slow-corner margin is thinner than it needs to be because of a flow buffering choice, described in section 6.

## 1. Summary

TinyFIR is a programmable 8-tap FIR filter for a 1x2 Tiny Tapeout tile on GF180. Coefficients load over SPI, samples enter on eight parallel pins, and one shared multiplier and accumulator process the eight taps in turn.

| Measure | Target | Result | Evidence |
|---|---|---|---|
| Processing latency | At most 16 clocks | 9 clocks | Simulation at 300 random input phases |
| Sample rate at 10 MHz | 500 ksample/s | Met, with no dropped or duplicated samples | Simulation at random phases |
| Fastest contract-legal rate at 10 MHz | Not specified | 769 ksample/s (13 clocks per sample) | Simulation at random phases |
| Random arithmetic against the model | At least 10,000 samples | 10,240 samples, 1,549 of them clipped, all exact | Simulation |
| Cell area | Fit the 112,783 µm² die | 60,267 µm² of standard cells, 55.8% of the core | Final layout |
| Timing at 10 MHz (100 ns) | Met at every corner | Met at all 9 corners. Worst setup slack 13.4 ns, worst hold slack 0.19 ns | Post-route static timing |
| Physical checks | Pass | Precheck 12 of 12, Magic and KLayout DRC clean, LVS match, no antenna violations | Tiny Tapeout CI |

All 28 system tests pass on RTL, on the post-synthesis netlist, and in CI on the final placed-and-routed netlist.

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

These figures are from area-oriented Yosys synthesis with the `tt_025C_3v30` library, before layout. They exclude the clock tree, repair buffers, and tap cells. The flow's own synthesis came to 40,829 µm², and the final layout to 60,267 µm² (section 6).

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
| Clock constraint | `CLOCK_PERIOD` raised from 20 ns to 100 ns | Matches the 10 MHz target. The signed-off layout needs 86.6 ns at its slowest corner (section 6) |

Two small additions go beyond the proposal: a sticky `STATUS` flag for requests dropped while busy, and a `CONTROL` bit that clears the status flags. Both make host errors visible through the pins.

The accumulator's top bit is redundant, because the largest magnitude, 131,072, fits in 19 bits. It stays at the 20 bits the proposal specified.

## 4. Verification

There are three levels of test.

- **System tests:** 28 cocotb tests that use only the chip's pins, so the same file runs on RTL and gate-level netlists. All 28 pass on RTL, on the post-synthesis netlist, and in CI on the final placed-and-routed netlist with power pins.
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
| Physical implementation | Tiny Tapeout `gds`, `precheck` and `gl_test` jobs | Pass, see section 6 |

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

## 6. Physical implementation

The official Tiny Tapeout flow (tt-gds-action `ttgf26c`, LibreLane 3.0.14) hardened commit `c3968f1` in GitHub Actions run 42127859566. Every job passed: `gds`, `precheck`, `gl_test` and `viewer`.

![Final layout of the 1x2 tile](figures/layout.png)

| Check | Result |
|---|---|
| Tiny Tapeout precheck | 12 of 12 checks pass, including a full KLayout GF180MCU DRC (0 violations across 739 rule categories) and an antenna check |
| Magic DRC | 0 errors |
| LVS | Circuits match uniquely: 1,960 devices, 1,971 nets and all 45 pins |
| Antenna | 0 violations, no diodes needed |
| Detailed routing | 0 violations after four iterations |
| IR drop | 0.09 mV at worst |
| Power | 4.60 mW at the typical corner, a vectorless estimate |
| Gate-level test | All 28 system tests pass on the final netlist with power pins |

The gate-level simulation is zero-delay, because the cell models' timing is switched off. It shows that the routed netlist behaves exactly like the RTL, but says nothing about timing, which comes from static timing analysis alone.

### Timing

Setup and hold are met at all nine signoff corners, with no violations. The slow corners limit setup and the fast corners limit hold. Every critical path starts at the tap counter, runs through the sample and coefficient selection and the multiplier, and ends in the accumulator.

| Corner | Setup slack, register to register | Minimum clock period | Worst hold slack |
|---|---:|---:|---:|
| Typical: `nom_tt_025C_3v30` | 58.0 ns | 42.0 ns (23.8 MHz) | 0.54 ns |
| Slow: `nom_ss_125C_3v00` | 14.8 ns | 85.2 ns (11.7 MHz) | 1.38 ns |
| Fast: `nom_ff_n40C_3v60` | 76.2 ns | 23.8 ns (42.0 MHz) | 0.19 ns |
| Slowest of all nine: `max_ss_125C_3v00` | 13.4 ns | 86.6 ns (11.5 MHz) | 1.38 ns |

The worst hold slack over all corners, 0.19 ns at `min_ff_n40C_3v60`, is between the reset synchronizer's two back-to-back flops, which is expected. Paths to and from the pins have at least 54 ns of slack even at the slowest corner.

### Why the slow-corner margin is thin

To fix fanout and slew, the layout tool inserted 146 buffers of type `dlyb_1`, a delay cell. The GF180 library describes it as an ordinary buffer, and in the slow-corner library it ranks as the weakest buffer by 0.06%, so OpenROAD picks it. Ten of these cells sit on the worst path and add 43.6 ns of its 88.3 ns at the slowest corner.

Adding the twelve delay cells (`gf180mcu_fd_sc_mcu7t5v0__dlya_1` through `__dlyd_4`) to `EXTRA_EXCLUDED_CELLS` in `src/config.json` would stop this. Estimated from the library's tables, it should give about 25 ns more slow-corner setup slack and save about 3,200 µm². That estimate needs another CI run to confirm. The change is optional, since the layout already meets 10 MHz.

### Electrical rule warnings

The flow reports max-slew, max-capacitance and max-fanout violations, which Tiny Tapeout's configuration does not treat as failures.

- **Max slew:** 440 pins exceed the flow's 3 ns limit at the slowest corner, 88 at the typical corner, and none at the fast corners. 98% are on nets driven by the delay-cell buffers, which have only x1 drive. Every slew stays inside the library's characterized range, so the timing above is interpolated, not extrapolated. Excluding the delay cells is not expected to clear these on its own, because the replacement `buf_1` has the same output drive.
- **Max capacitance:** 2 nets, at 0.208 pF and 0.202 pF against a 0.2 pF limit, and only at the max-RC corners.
- **Max fanout:** 14 clock-tree leaf buffers each drive 12 to 17 flops against a limit of 10, which is normal for a clock tree.

None of these causes a functional problem at 10 MHz. No clock net is affected, and every setup, hold, recovery and removal check passes.

### Area

The flow's synthesis came to 40,829 µm², inside the estimate in section 2. The final 60,267 µm² of standard cells (55.8% of the core) adds 8,535 µm² of repair buffers, 5,591 µm² from upsized cells, 3,806 µm² of tap and endcap cells, and 1,506 µm² of clock tree. Fill takes most of the remaining space.

### Pre-layout estimates against signoff

Before CI ran, a quick synthesis estimate put the critical path at 12.2, 24.6 and 6.9 ns at the typical, slow and fast corners. The signed-off register-to-register paths are 42.0, 85.2 and 23.8 ns, about 3.45 times longer. At the typical corner the gap breaks down roughly as follows:

- 9 ns from the flow's area-oriented synthesis
- 6 ns of timing terms the estimate left out
- 4 ns of wire load
- 14 ns from the delay cells
- 3 ns saved by buffering

The estimate was good enough to choose the 100 ns constraint, but too optimistic to quote as margin.

## 7. Known limits

- **Short `ready` and `output_valid` pulses.** `ready` is low for 9 clocks and `output_valid` lasts 1. A slow polling host can miss both, so the datasheet gives a fixed-delay procedure, which `test_host_too_slow_to_watch_ready` covers.
- **Reset with SPI active.** If reset releases while chip select is low and SCLK is high, the first SCLK level counts as a clock. A write in that frame is rejected and flagged, so it fails safely. This state is outside SPI mode 0 idle.
- **Simulation cannot show metastability.** The synchronizers follow standard practice, but only silicon can test them. Gate-level simulation is zero-delay, so timing evidence comes only from static timing analysis.
- **Slow-corner headroom.** At the slowest corner the layout supports about 11.5 MHz, roughly 15% above the 10 MHz target, until the delay-cell change in section 6 is made.
- **Electrical warnings.** The max-slew, max-capacitance and max-fanout warnings in section 6 were reviewed and accepted, and they remain in the layout.
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

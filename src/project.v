/*
 * Copyright (c) 2026 Hamza Soofi, Gurpal Johal, Mohil Kadakia, Ayaan Tunio
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Tiny Tapeout wrapper: maps the pinout in info.yaml onto fir_core.
//
//   ui_in[7:0]   sample_in[7:0]    signed 8-bit input sample
//   uo_out[7:0]  sample_out[7:0]   signed 8-bit filtered result
//   uio[0]  in   spi_sclk
//   uio[1]  in   spi_mosi
//   uio[2]  out  spi_miso          driven only while spi_cs_n is low
//   uio[3]  in   spi_cs_n
//   uio[4]  in   sample_strobe
//   uio[5]  out  ready
//   uio[6]  out  output_valid
//   uio[7]  out  saturated
module tt_um_gurpalhamzamohilayaan_tinyfir (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  wire spi_sclk      = uio_in[0];
  wire spi_mosi      = uio_in[1];
  wire spi_cs_n      = uio_in[3];
  wire sample_strobe = uio_in[4];

  wire spi_miso;
  wire ready;
  wire output_valid;
  wire saturated;

  // Reset asserts immediately and releases on a clock edge, so every flop in
  // the design leaves reset in the same cycle.
  wire core_rst_n;
  reset_sync u_reset_sync (
      .clk      (clk),
      .rst_n_in (rst_n),
      .rst_n_out(core_rst_n)
  );

  fir_core u_core (
      .clk          (clk),
      .rst_n        (core_rst_n),
      .sample_in    (ui_in),
      .sample_strobe(sample_strobe),
      .spi_sclk     (spi_sclk),
      .spi_mosi     (spi_mosi),
      .spi_cs_n     (spi_cs_n),
      .spi_miso     (spi_miso),
      .sample_out   (uo_out),
      .ready        (ready),
      .output_valid (output_valid),
      .saturated    (saturated)
  );

  assign uio_out = {saturated, output_valid, ready, 2'b00, spi_miso, 2'b00};

  // MISO follows chip select directly so the pin releases the bus as soon as
  // the host deselects, with no synchronizer delay. Pins 5-7 are always
  // outputs, and pins 0, 1, 3 and 4 are always inputs.
  assign uio_oe = {3'b111, 2'b00, ~spi_cs_n, 2'b00};

  // uio_in[7:5] and uio_in[2] only ever reflect this design's own outputs.
  wire _unused = &{ena, uio_in[7:5], uio_in[2], 1'b0};

endmodule

/*
 * Copyright (c) 2026 Hamza Soofi, Gurpal Johal, Mohil Kadakia, Ayaan Tunio
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Eight signed 9-bit coefficients, stored as weight * 128. There is one read
// port for the FIR tap and one for SPI readback, so a read over SPI never
// disturbs a calculation in progress.
module coef_regs (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       write_en,
    input  wire [2:0] write_addr,
    input  wire [8:0] write_data,
    input  wire [2:0] tap,
    output wire [8:0] coef_tap,
    input  wire [2:0] read_addr,
    output wire [8:0] read_data
);

  // 16 / 128 = 1/8 on all taps: an eight-point moving average.
  localparam [8:0] COEF_RESET = 9'd16;

  wire [8:0] coef[0:7];

  genvar i;
  generate
    for (i = 0; i < 8; i = i + 1) begin : g_coef
      reg [8:0] coef_q;

      always @(posedge clk or negedge rst_n) begin
        if (!rst_n) coef_q <= COEF_RESET;
        else if (write_en && write_addr == i[2:0]) coef_q <= write_data;
      end

      assign coef[i] = coef_q;
    end
  endgenerate

  assign coef_tap  = coef[tap];
  assign read_data = coef[read_addr];

endmodule

/*
 * Copyright (c) 2026 Hamza Soofi, Gurpal Johal, Mohil Kadakia, Ayaan Tunio
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Scaling, saturation and the output register.
//
// acc_scaled is acc[19:7]: dropping the low seven bits is an arithmetic shift
// by seven, which rounds toward negative infinity. The result fits in 8 bits
// only when bits [12:7] of acc_scaled are all copies of its sign.
module output_stage (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        publish,
    input  wire [12:0] acc_scaled,
    output reg  [ 7:0] sample_out,
    output reg         output_valid,
    output reg         saturated
);

  wire overflow = acc_scaled[12:7] != {6{acc_scaled[7]}};
  wire [7:0] clamped = acc_scaled[12] ? 8'h80 : 8'h7F;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      sample_out   <= 8'd0;
      output_valid <= 1'b0;
      saturated    <= 1'b0;
    end else begin
      output_valid <= publish;
      if (publish) begin
        sample_out <= overflow ? clamped : acc_scaled[7:0];
        saturated  <= overflow;
      end
    end
  end

endmodule

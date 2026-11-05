/*
 * Copyright (c) 2026 Hamza Soofi, Gurpal Johal, Mohil Kadakia, Ayaan Tunio
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Asynchronous-assert, synchronous-release reset generator.
module reset_sync (
    input  wire clk,
    input  wire rst_n_in,
    output wire rst_n_out
);

  // This register is the source of the design's asynchronous reset by intent.
  /* verilator lint_off SYNCASYNCNET */
  reg [1:0] chain_q;
  /* verilator lint_on SYNCASYNCNET */

  always @(posedge clk or negedge rst_n_in) begin
    if (!rst_n_in) chain_q <= 2'b00;
    else chain_q <= {chain_q[0], 1'b1};
  end

  assign rst_n_out = chain_q[1];

endmodule

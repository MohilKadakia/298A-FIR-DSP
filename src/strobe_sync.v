/*
 * Copyright (c) 2026 Hamza Soofi, Gurpal Johal, Mohil Kadakia, Ayaan Tunio
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Transfers the external sample request into the system-clock domain and
// produces a one-cycle pulse for each synchronized rising edge.
//
// The chain resets to all ones. A strobe that is already high when reset
// releases therefore never looks like a new request: it must be seen low first.
module strobe_sync (
    input  wire clk,
    input  wire rst_n,
    input  wire strobe_async,
    output wire strobe_rise,
    output wire strobe_low
);

  wire strobe_s;
  reg  strobe_prev_q;

  sync_2ff #(
      .RESET_VALUE(1'b1)
  ) u_sync (
      .clk  (clk),
      .rst_n(rst_n),
      .d    (strobe_async),
      .q    (strobe_s)
  );

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) strobe_prev_q <= 1'b1;
    else strobe_prev_q <= strobe_s;
  end

  assign strobe_rise = strobe_s & ~strobe_prev_q;
  assign strobe_low  = ~strobe_prev_q;

endmodule

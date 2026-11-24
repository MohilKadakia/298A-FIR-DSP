`default_nettype none

// Current sample and fifteen previous samples, with two tap selection muxes.
// For tap slot k the low mux gives x[n-k] and the high mux gives x[n-k-8], so
// the two multipliers together cover all sixteen taps in eight clocks.
//
// A clear that lands on the same edge as an accepted sample keeps the new
// sample, because the history is cleared first and the sample then arrives.
module sample_history (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       accept,
    input  wire       clear,
    input  wire [7:0] sample_in,
    input  wire [2:0] tap,
    output wire [7:0] sample_lo,
    output wire [7:0] sample_hi
);

  // [7:0] is x[n], the newest sample, and [127:120] is x[n-15].
  reg [127:0] hist_q;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) hist_q <= 128'd0;
    else if (clear) hist_q <= {120'd0, accept ? sample_in : 8'd0};
    else if (accept) hist_q <= {hist_q[119:0], sample_in};
  end

  assign sample_lo = hist_q[{1'b0, tap, 3'b000}+:8];
  assign sample_hi = hist_q[{1'b1, tap, 3'b000}+:8];

endmodule

`default_nettype none

// Current sample and seven previous samples, with the tap selection mux.
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
    output wire [7:0] sample_tap
);

  reg [63:0] hist_q;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) hist_q <= 64'd0;
    else if (clear) hist_q <= {56'd0, accept ? sample_in : 8'd0};
    else if (accept) hist_q <= {hist_q[55:0], sample_in};
  end

  assign sample_tap = hist_q[{tap, 3'b000}+:8];

endmodule

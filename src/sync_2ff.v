`default_nettype none

// Two-flop synchronizer for a single asynchronous input bit.
module sync_2ff #(
    parameter [0:0] RESET_VALUE = 1'b0
) (
    input  wire clk,
    input  wire rst_n,
    input  wire d,
    output wire q
);

  reg [1:0] chain_q;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) chain_q <= {2{RESET_VALUE}};
    else chain_q <= {chain_q[0], d};
  end

  assign q = chain_q[1];

endmodule

`default_nettype none

// Shared signed multiplier and accumulator
//
// |product| <= 128 * 128 = 16384
// eight products sum to at most 131072 in magnitude (20 bit accumulator holds without overflow)
module fir_mac (
    input  wire clk,
    input  wire rst_n,
    input  wire clear,
    input  wire enable,
    input  wire [7:0] sample,
    input  wire [8:0] coef,
    output reg [19:0] acc
);

  wire signed [ 7:0] sample_s = sample;
  wire signed [ 8:0] coef_s = coef;
  /* verilator lint_off WIDTHEXPAND */
  wire signed [16:0] product = sample_s * coef_s;
  /* verilator lint_on WIDTHEXPAND */

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) acc <= 20'd0;
    else if (clear) acc <= 20'd0;
    else if (enable) acc <= acc + {{3{product[16]}}, product};
  end

endmodule

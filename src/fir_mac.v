`default_nettype none

// Two signed multipliers feeding one accumulator
//
// Each enabled clock adds sample_lo * coef_lo + sample_hi * coef_hi, which the
// controller and muxes arrange to be taps k and k + 8, so sixteen taps take
// eight clocks.
//
// |product| <= 128 * 128 = 16384
// sixteen products sum to at most 262144 = 2^18 in magnitude. +2^18 needs the
// full 20-bit signed accumulator, which holds it without overflow.
module fir_mac (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        clear,
    input  wire        enable,
    input  wire [ 7:0] sample_lo,
    input  wire [ 8:0] coef_lo,
    input  wire [ 7:0] sample_hi,
    input  wire [ 8:0] coef_hi,
    output reg  [19:0] acc
);

  wire signed [7:0] sample_lo_s = sample_lo;
  wire signed [8:0] coef_lo_s = coef_lo;
  wire signed [7:0] sample_hi_s = sample_hi;
  wire signed [8:0] coef_hi_s = coef_hi;
  /* verilator lint_off WIDTHEXPAND */
  wire signed [16:0] product_lo = sample_lo_s * coef_lo_s;
  wire signed [16:0] product_hi = sample_hi_s * coef_hi_s;
  // 18 bits hold the sum of any two 8 x 9 products, legal range or not.
  wire signed [17:0] pair = product_lo + product_hi;
  /* verilator lint_on WIDTHEXPAND */

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) acc <= 20'd0;
    else if (clear) acc <= 20'd0;
    else if (enable) acc <= acc + {{2{pair[17]}}, pair};
  end

endmodule

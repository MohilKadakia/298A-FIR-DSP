`default_nettype none

// Sixteen signed 9-bit coefficients, stored as weight * 128. The FIR reads two
// at once (taps k and k + 8), and SPI readback has its own port, so a read over
// SPI never disturbs a calculation in progress.
module coef_regs (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       write_en,
    input  wire [3:0] write_addr,
    input  wire [8:0] write_data,
    input  wire [2:0] tap,
    output wire [8:0] coef_lo,
    output wire [8:0] coef_hi,
    input  wire [3:0] read_addr,
    output wire [8:0] read_data
);

  // 8 / 128 = 1/16 on all taps: a sixteen-point moving average.
  localparam [8:0] COEF_RESET = 9'd8;

  wire [8:0] coef[0:15];

  genvar i;
  generate
    for (i = 0; i < 16; i = i + 1) begin : g_coef
      reg [8:0] coef_q;

      always @(posedge clk or negedge rst_n) begin
        if (!rst_n) coef_q <= COEF_RESET;
        else if (write_en && write_addr == i[3:0]) coef_q <= write_data;
      end

      assign coef[i] = coef_q;
    end
  endgenerate

  assign coef_lo   = coef[{1'b0, tap}];
  assign coef_hi   = coef[{1'b1, tap}];
  assign read_data = coef[read_addr];

endmodule

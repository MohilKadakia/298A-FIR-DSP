
`default_nettype none

// SPI mode 0 slave, MSB first, oversampled by the system clock.
//
// A transaction is exactly 24 clocks: one command byte and two data bytes.
//
//   command[7]    1 = read, 0 = write
//   command[6:4]  must be zero
//   command[3:0]  register address
//
//   0x0-0x7  COEF0-COEF7  R/W  sign-extended coefficient, -128 to +128
//   0x8      STATUS       R    [3] overrun, [2] write rejected,
//                              [1] saturated, [0] ready
//   0x9      CONTROL      W    [1] clear status flags, [0] clear history
//
// A write commits when chip select rises, and only if it had exactly 24 clocks,
// a legal address, a legal value, and no calculation is running. Any other
// write changes nothing and sets the rejected flag.
module spi_interface (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       spi_sclk,
    input  wire       spi_mosi,
    input  wire       spi_cs_n,
    output reg        spi_miso,
    input  wire [3:0] status,
    input  wire       calc_active,
    output wire [2:0] coef_read_addr,
    input  wire [8:0] coef_read_data,
    output wire       coef_write_en,
    output wire [2:0] coef_write_addr,
    output wire [8:0] coef_write_data,
    output wire       clear_history,
    output wire       clear_flags,
    output wire       write_rejected
);

  localparam [3:0] ADDR_STATUS = 4'd8;
  localparam [3:0] ADDR_CONTROL = 4'd9;
  localparam [4:0] BITS_COMMAND = 5'd8;
  localparam [4:0] BITS_TOTAL = 5'd24;
  // The counter sticks here, so an overlong transaction cannot wrap back to 24.
  localparam [4:0] BITS_OVERLONG = 5'd25;

  wire sclk_s;
  wire mosi_s;
  wire cs_n_s;
  reg  sclk_prev_q;
  reg  cs_n_prev_q;

  sync_2ff #(.RESET_VALUE(1'b0)) u_sync_sclk (.clk(clk), .rst_n(rst_n), .d(spi_sclk), .q(sclk_s));
  sync_2ff #(.RESET_VALUE(1'b0)) u_sync_mosi (.clk(clk), .rst_n(rst_n), .d(spi_mosi), .q(mosi_s));
  sync_2ff #(.RESET_VALUE(1'b1)) u_sync_cs_n (.clk(clk), .rst_n(rst_n), .d(spi_cs_n), .q(cs_n_s));

  wire sclk_rise = sclk_s & ~sclk_prev_q;
  wire sclk_fall = ~sclk_s & sclk_prev_q;
  wire cs_end = cs_n_s & ~cs_n_prev_q;

  reg [15:0] shift_q;
  reg [ 4:0] bit_count_q;
  reg        is_read_q;
  reg [ 3:0] addr_q;
  reg        reserved_ok_q;

  // On the eighth rising edge the command is shift_q[6:0] plus the incoming bit.
  wire        last_command_bit = bit_count_q == BITS_COMMAND - 5'd1;
  wire [ 3:0] incoming_addr = {shift_q[2:0], mosi_s};

  assign coef_read_addr = incoming_addr[2:0];

  reg [15:0] read_word;
  always @(*) begin
    if (shift_q[5:3] != 3'b000) read_word = 16'd0;
    else if (!incoming_addr[3]) read_word = {{7{coef_read_data[8]}}, coef_read_data};
    else if (incoming_addr == ADDR_STATUS) read_word = {12'd0, status};
    else read_word = 16'd0;
  end

  wire in_data_phase = (bit_count_q >= BITS_COMMAND) && (bit_count_q < BITS_TOTAL);

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      sclk_prev_q   <= 1'b0;
      cs_n_prev_q   <= 1'b1;
      spi_miso      <= 1'b0;
      shift_q       <= 16'd0;
      bit_count_q   <= 5'd0;
      is_read_q     <= 1'b0;
      addr_q        <= 4'd0;
      reserved_ok_q <= 1'b0;
    end else begin
      sclk_prev_q <= sclk_s;
      cs_n_prev_q <= cs_n_s;

      if (cs_n_s) begin
        spi_miso    <= 1'b0;
        bit_count_q <= 5'd0;
      end else begin
        if (sclk_fall) spi_miso <= is_read_q & in_data_phase & shift_q[15];

        if (sclk_rise) begin
          shift_q <= {shift_q[14:0], mosi_s};
          if (bit_count_q != BITS_OVERLONG) bit_count_q <= bit_count_q + 5'd1;
          if (bit_count_q == 5'd0) is_read_q <= mosi_s;
          if (last_command_bit) begin
            addr_q        <= incoming_addr;
            reserved_ok_q <= shift_q[5:3] == 3'b000;
            if (shift_q[6]) shift_q <= read_word;
          end
        end
      end
    end
  end

  // Legal coefficients are -128 to +128: the top nine bits all match, or the
  // word is exactly +128.
  wire coef_in_range = (&shift_q[15:7]) | (~|shift_q[15:7]) | (shift_q == 16'h0080);
  wire control_legal = shift_q[15:2] == 14'd0;

  wire addr_is_coef = ~addr_q[3];
  wire addr_is_control = addr_q == ADDR_CONTROL;

  wire write_legal = (bit_count_q == BITS_TOTAL) & reserved_ok_q & ~calc_active
       & ((addr_is_coef & coef_in_range) | (addr_is_control & control_legal));

  // A chip-select pulse with no clocks is not a transaction. The read/write bit
  // is known from the first clock, so a truncated write is still a write.
  wire write_ended = cs_end & (bit_count_q != 5'd0) & ~is_read_q;
  wire write_commit = write_ended & write_legal;

  assign write_rejected  = write_ended & ~write_legal;
  assign coef_write_en   = write_commit & addr_is_coef;
  assign coef_write_addr = addr_q[2:0];
  assign coef_write_data = shift_q[8:0];
  assign clear_history   = write_commit & addr_is_control & shift_q[0];
  assign clear_flags     = write_commit & addr_is_control & shift_q[1];

endmodule
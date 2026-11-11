`default_nettype none

module fir_core (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] sample_in,
    input  wire       sample_strobe,
    input  wire       spi_sclk,
    input  wire       spi_mosi,
    input  wire       spi_cs_n,
    output wire       spi_miso,
    output wire [7:0] sample_out,
    output wire       ready,
    output wire       output_valid,
    output wire       saturated
);

  wire strobe_rise;
  wire strobe_low;
  wire accept;
  wire mac_enable;
  wire publish;
  wire calc_active;
  wire overrun;
  wire [2:0] tap;

  wire [2:0] coef_read_addr;
  wire [8:0] coef_read_data;
  wire coef_write_en;
  wire [2:0] coef_write_addr;
  wire [8:0] coef_write_data;
  wire clear_history;
  wire clear_flags;
  wire write_rejected;

  wire [7:0] sample_tap;
  wire [8:0] coef_tap;
  wire [19:0] acc;

  reg rejected_flag_q;
  reg overrun_flag_q;

  strobe_sync u_strobe_sync (
      .clk         (clk),
      .rst_n       (rst_n),
      .strobe_async(sample_strobe),
      .strobe_rise (strobe_rise),
      .strobe_low  (strobe_low)
  );

  fir_controller u_controller (
      .clk        (clk),
      .rst_n      (rst_n),
      .strobe_rise(strobe_rise),
      .strobe_low (strobe_low),
      .ready      (ready),
      .accept     (accept),
      .mac_enable (mac_enable),
      .publish    (publish),
      .calc_active(calc_active),
      .overrun    (overrun),
      .tap        (tap)
  );

  sample_history u_history (
      .clk       (clk),
      .rst_n     (rst_n),
      .accept    (accept),
      .clear     (clear_history),
      .sample_in (sample_in),
      .tap       (tap),
      .sample_tap(sample_tap)
  );

  coef_regs u_coefs (
      .clk       (clk),
      .rst_n     (rst_n),
      .write_en  (coef_write_en),
      .write_addr(coef_write_addr),
      .write_data(coef_write_data),
      .tap       (tap),
      .coef_tap  (coef_tap),
      .read_addr (coef_read_addr),
      .read_data (coef_read_data)
  );

  fir_mac u_mac (
      .clk   (clk),
      .rst_n (rst_n),
      .clear (accept),
      .enable(mac_enable),
      .sample(sample_tap),
      .coef  (coef_tap),
      .acc   (acc)
  );

  output_stage u_output (
      .clk         (clk),
      .rst_n       (rst_n),
      .publish     (publish),
      .acc_scaled  (acc[19:7]),
      .sample_out  (sample_out),
      .output_valid(output_valid),
      .saturated   (saturated)
  );

  spi_interface u_spi (
      .clk            (clk),
      .rst_n          (rst_n),
      .spi_sclk       (spi_sclk),
      .spi_mosi       (spi_mosi),
      .spi_cs_n       (spi_cs_n),
      .spi_miso       (spi_miso),
      .status         ({overrun_flag_q, rejected_flag_q, saturated, ready}),
      .calc_active    (calc_active),
      .coef_read_addr (coef_read_addr),
      .coef_read_data (coef_read_data),
      .coef_write_en  (coef_write_en),
      .coef_write_addr(coef_write_addr),
      .coef_write_data(coef_write_data),
      .clear_history  (clear_history),
      .clear_flags    (clear_flags),
      .write_rejected (write_rejected)
  );

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rejected_flag_q <= 1'b0;
      overrun_flag_q  <= 1'b0;
    end else begin
      rejected_flag_q <= write_rejected | (rejected_flag_q & ~clear_flags);
      overrun_flag_q  <= overrun | (overrun_flag_q & ~clear_flags);
    end
  end

  wire _unused = &{acc[6:0], 1'b0};

endmodule

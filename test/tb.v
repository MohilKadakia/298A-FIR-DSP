`default_nettype none
`timescale 1ns / 1ps

/* Instantiates the design with a model of its bidirectional pads and names each
   pin, so the cocotb tests can drive and trigger on individual signals at both
   RTL and gate level.

   By default only this top level is dumped to tb.fst, which keeps the file small
   during long regressions. Build with -DDUMP_ALL for the whole hierarchy.
*/
module tb ();

  initial begin
    $dumpfile("tb.fst");
`ifdef DUMP_ALL
    $dumpvars(0, tb);
`else
    $dumpvars(1, tb);
`endif
    #1;
  end

  reg clk;
  reg rst_n;
  reg ena;
  reg [7:0] ui_in;

  // Signals driven by the external host:
  reg spi_sclk;
  reg spi_mosi;
  reg spi_cs_n;
  reg sample_strobe;

  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;
`ifdef GL_TEST
  wire VPWR = 1'b1;
  wire VGND = 1'b0;
`endif

  // On the chip, each uio input path reads the pad, which reflects the design's
  // own output when its output enable is high.
  wire [7:0] uio_host = {3'b000, sample_strobe, spi_cs_n, 1'b0, spi_mosi, spi_sclk};
  wire [7:0] uio_in = (uio_oe & uio_out) | (~uio_oe & uio_host);

  // Pins as an external device sees them:
  wire spi_miso = uio_oe[2] ? uio_out[2] : 1'bz;
  wire ready = uio_out[5];
  wire output_valid = uio_out[6];
  wire saturated = uio_out[7];

  tt_um_gurpalhamzamohilayaan_tinyfir user_project (

      // Include power ports for the Gate Level test:
`ifdef GL_TEST
      .VPWR(VPWR),
      .VGND(VGND),
`endif

      .ui_in  (ui_in),    // Dedicated inputs
      .uo_out (uo_out),   // Dedicated outputs
      .uio_in (uio_in),   // IOs: Input path
      .uio_out(uio_out),  // IOs: Output path
      .uio_oe (uio_oe),   // IOs: Enable path (active high: 0=input, 1=output)
      .ena    (ena),      // enable - goes high when design is selected
      .clk    (clk),      // clock
      .rst_n  (rst_n)     // not reset
  );

endmodule

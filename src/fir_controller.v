`default_nettype none

// Sequences one sample through the shared multiplier-accumulator
//
//   edge 0     accept: history shifts, accumulator clears, ready falls
//   edge 1-8   one tap accumulated per clock
//   edge 9     publish: output register loads, output_valid and ready rise
//
// INIT holds ready low after reset until the strobe synchronizer has flushed
// Requests that arrive while ready is low are dropped, not queued
module fir_controller (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       strobe_rise,
    input  wire       strobe_low,
    output wire       ready,
    output wire       accept,
    output wire       mac_enable,
    output wire       publish,
    output wire       calc_active,
    output wire       overrun,
    output wire [2:0] tap
);

  localparam [2:0] ST_INIT = 3'b000;
  localparam [2:0] ST_IDLE = 3'b001;
  localparam [2:0] ST_MAC = 3'b010;
  localparam [2:0] ST_PUBLISH = 3'b100;

  (* fsm_encoding = "none" *) reg [2:0] state_q;
  reg [2:0] tap_q;

  assign ready       = state_q[0];
  assign mac_enable  = state_q[1];
  assign publish     = state_q[2];
  assign calc_active = state_q[1] | state_q[2];
  assign accept      = ready & strobe_rise;
  assign overrun     = ~ready & strobe_rise;
  assign tap         = tap_q;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state_q <= ST_INIT;
      tap_q   <= 3'd0;
    end else begin
      case (state_q)
        ST_INIT: if (strobe_low) state_q <= ST_IDLE;
        ST_IDLE: if (strobe_rise) state_q <= ST_MAC;
        ST_MAC: begin
          // Eight increments wrap the 3-bit counter back to 0
          tap_q <= tap_q + 3'd1;
          if (tap_q == 3'd7) state_q <= ST_PUBLISH;
        end
        ST_PUBLISH: state_q <= ST_IDLE;
        default: state_q <= ST_INIT;
      endcase
    end
  end

endmodule

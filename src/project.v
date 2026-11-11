/*
 * Copyright (c) 2024 Your Name
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_example (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

// uio_in[0] tells us when a new sample should be accepted 
wire sample_strobe; 

assign sample_strobe = uio_in[0];

// Store one signed 8-bit sample 
reg signed [7:0] sample; 


    always @(posedge clk) begin

        // Reset the sample to 0
        if (!rst_n) begin
            sample <= 8'sd0;
        end

        // If a new sample is ready, store ui_in
        else if (sample_strobe) begin
            sample <= $signed(ui_in);
        end

    end

// Send the stored sample to the output pins 
assign uo_out = sample;

// Default output uio output pin yet 
assign uio_out = 8'b00000000;

// Output enable set to 0's dont know what pins we want for output 
assign uio_oe = 8'b00000000;


// Ignore the other 7 input pins for now 
wire _unused = &{ena, uio_in[7:1], 1'b0};

endmodule

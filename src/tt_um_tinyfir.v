// SPDX-License-Identifier: Apache-2.0
// Top-level module for the TinyFIR filter
// Connects the SPI interface, coefficient registers, and FIR core

module tt_um_tinyfir (
    input  wire [7:0] ui_in,      // 8-bit input sample
    output wire [7:0] uo_out,     // 8-bit filtered output
    input  wire [7:0] uio_in,     // Input pins
    output wire [7:0] uio_out,    // Output pins
    output wire [7:0] uio_oe,     // Controls input/output direction
    input  wire       ena,        // Enable signal
    input  wire       clk,        // System clock
    input  wire       rst_n       // Active-low reset
);

    // Assign the SPI and sample control pins
    wire spi_sclk      = uio_in[0];
    wire spi_mosi      = uio_in[1];
    wire spi_cs_n      = uio_in[3];
    wire sample_strobe = uio_in[4];

    // SPI signals
    wire spi_miso;
    wire spi_active;
    wire frame_valid;
    wire [7:0] frame_command;
    wire [15:0] frame_data;
    wire [7:0] spi_command;
    wire [15:0] spi_read_data;

    // Signals used by the coefficient registers and FIR core
    wire [2:0] tap_index;
    wire signed [8:0] tap_coefficient;
    wire clear_history;
    wire rejected_write;
    wire ready;
    wire output_valid;
    wire saturated;
    wire busy;
    wire [7:0] sample_out;


    // SPI module
    // Receives commands and data from the external controller
    // Also handles sending data back through MISO
    tinyfir_spi u_spi (
        .clk(clk),
        .rst_n(rst_n),
        .sclk_in(spi_sclk),
        .mosi_in(spi_mosi),
        .cs_n_in(spi_cs_n),
        .miso_out(spi_miso),
        .active(spi_active),
        .current_command(spi_command),
        .read_data(spi_read_data),
        .frame_valid(frame_valid),
        .frame_command(frame_command),
        .frame_data(frame_data)
    );


    // Coefficient register module
    // Stores the 8 filter coefficients
    // Allows coefficients to be updated and read using SPI
    tinyfir_coeffs u_coeffs (
        .clk(clk),
        .rst_n(rst_n),
        .frame_valid(frame_valid),
        .frame_command(frame_command),
        .frame_data(frame_data),
        .spi_command(spi_command),
        .spi_read_data(spi_read_data),
        .fir_busy(busy),
        .saturated(saturated),
        .tap_index(tap_index),
        .tap_coefficient(tap_coefficient),
        .clear_history(clear_history),
        .rejected_write(rejected_write)
    );


    // FIR filter module
    // Stores previous input samples and performs the filtering
    // Uses one multiplier and accumulator for all 8 taps
    tinyfir_core u_core (
        .clk(clk),
        .rst_n(rst_n),
        .ena(ena),
        .sample_in(ui_in),
        .sample_strobe(sample_strobe),
        .configuration_active(spi_active | frame_valid),
        .clear_history(clear_history),
        .tap_coefficient(tap_coefficient),
        .tap_index(tap_index),
        .sample_out(sample_out),
        .ready(ready),
        .busy(busy),
        .output_valid(output_valid),
        .saturated(saturated)
    );


    // Send the filtered sample to the output pins
    assign uo_out = sample_out;


    // Assign SPI and status signals to the output pins
    assign uio_out = {
        saturated,
        output_valid,
        ready,
        2'b00,
        spi_miso,
        2'b00
    };

    // Set pins 5, 6, and 7 as outputs
    // MISO is only enabled when SPI is selected
    assign uio_oe = {
        3'b111,
        2'b00,
        ~spi_cs_n,
        2'b00
    };

endmodule

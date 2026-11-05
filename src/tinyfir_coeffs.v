
// SPDX-License-Identifier: Apache-2.0
// Coefficient storage module for TinyFIR
// Stores the 8 filter coefficients and allows them to be changed using SPI
// The FIR core reads these coefficients when calculating each output sample

module tinyfir_coeffs (
    input  wire              clk,              // Main system clock
    input  wire              rst_n,            // Active-low reset
    input  wire              frame_valid,      // High when a full SPI message arrives
    input  wire [7:0]        frame_command,    // Command received through SPI
    input  wire [15:0]       frame_data,       // Data received through SPI
    input  wire [7:0]        spi_command,      // Current SPI command
    output reg  [15:0]       spi_read_data,    // Data being sent back through SPI
    input  wire              fir_busy,         // Indicates if FIR is processing a sample
    input  wire              saturated,        // Indicates if output was limited
    input  wire [2:0]        tap_index,        // Selects which coefficient to use
    output wire signed [8:0] tap_coefficient,  // Coefficient sent to FIR core
    output reg               clear_history,   // Clears previous input samples
    output reg               rejected_write   // Indicates an invalid write
);

    // Store 8 signed coefficients, each 9 bits wide
    // Signed values allow positive and negative filter weights
    // This lets us create different filters using the same hardware
    reg signed [8:0] coefficients [0:7];
    integer k;

    // The FIR core processes one tap at a time
    // tap_index chooses which coefficient gets sent to the multiplier
    assign tap_coefficient = coefficients[tap_index];


    // SPI readback logic
    // Allows the external controller to check stored coefficients
    // or read the current status of the filter
    always @(*) begin
        spi_read_data = 16'h0000;

        if (spi_command[7] &&
            spi_command[6:3] == 4'b0000) begin

            // Commands 0x80 to 0x87 read coefficients 0 to 7
            // Extend the 9-bit signed coefficient to 16 bits
            // This keeps negative coefficients negative when read back
            spi_read_data = {
                {7{coefficients[spi_command[2:0]][8]}},
                coefficients[spi_command[2:0]]
            };

        end else if (spi_command == 8'h8F) begin

            // Return basic information about the filter
            // Bit 0: whether a write was rejected
            // Bit 1: whether the FIR core is busy
            // Bit 2: whether the last output was saturated
            spi_read_data = {
                13'd0,
                saturated,
                fir_busy,
                rejected_write
            };
        end
    end


    // Main coefficient control logic
    // Handles reset, coefficient updates, and control commands
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin

            // Initialize all coefficients to 16
            // Since coefficients are divided by 128,
            // each one represents a weight of 1/8
            // This gives us an 8-point moving-average filter at reset
            for (k = 0; k < 8; k = k + 1)
                coefficients[k] <= 9'sd16;

            // Clear control and error signals
            clear_history  <= 1'b0;
            rejected_write <= 1'b0;

        end else begin

            // Keep clear_history low unless a clear command arrives
            // This makes it a one-clock pulse
            clear_history <= 1'b0;

            if (frame_valid) begin

                // A complete SPI message has been received
                // Decode the command to determine what to do

                if (frame_command[7:3] == 5'b00000) begin

                    // Commands 0x00 to 0x07 update coefficients 0 to 7
                    // First check whether the new value is allowed

                    if (fir_busy ||
                        $signed(frame_data) < -16'sd128 ||
                        $signed(frame_data) >  16'sd128) begin

                        // Reject the update if the FIR is busy
                        // or the coefficient is outside -128 to +128
                        // Keep the previous coefficient unchanged
                        rejected_write <= 1'b1;

                    end else begin

                        // Store the new coefficient
                        // The lower 3 command bits choose the register
                        // The lower 9 data bits contain the coefficient
                        coefficients[frame_command[2:0]]
                            <= frame_data[8:0];

                    end

                end else if (frame_command == 8'h10) begin

                    // Clear the previous input samples
                    // Useful when starting a new filtering operation
                    // The programmed coefficients remain unchanged
                    if (!fir_busy)
                        clear_history <= 1'b1;
                    else
                        rejected_write <= 1'b1;

                end else if (frame_command == 8'h11) begin

                    // Clear the rejected-write error flag
                    // Allows us to reset the error status
                    rejected_write <= 1'b0;

                end

                // Read commands do not change stored coefficients
            end
        end
    end

endmodule


// SPDX-License-Identifier: Apache-2.0
// SPI module for TinyFIR
// Receives commands and coefficient data from an external controller
// Also sends stored data back to the controller when requested

module tinyfir_spi (
    input  wire        clk,              // Main system clock
    input  wire        rst_n,            // Reset signal
    input  wire        sclk_in,          // Clock sent by SPI controller
    input  wire        mosi_in,          // Data coming into the chip
    input  wire        cs_n_in,          // Selects the SPI device
    output wire        miso_out,         // Data going back to controller
    output wire        active,           // High when SPI is selected
    output wire [7:0]  current_command,  // Command received from SPI
    input  wire [15:0] read_data,        // Data we want to send back
    output reg         frame_valid,     // High when a full message is received
    output reg  [7:0]  frame_command,   // Command from completed message
    output reg  [15:0] frame_data       // Data from completed message
);

    // SPI signals come from an external controller
    // We pass them through two registers to safely bring
    // them into our main system clock domain
    reg sclk_meta, sclk_sync, sclk_prev;
    reg mosi_meta, mosi_sync;
    reg cs_meta, cs_sync, cs_prev;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // Set SPI signals to their starting values
            sclk_meta <= 1'b0;
            sclk_sync <= 1'b0;
            sclk_prev <= 1'b0;
            mosi_meta <= 1'b0;
            mosi_sync <= 1'b0;
            cs_meta   <= 1'b1;
            cs_sync   <= 1'b1;
            cs_prev   <= 1'b1;
        end else begin
            // Update synchronized SPI signals each clock cycle
            // Keep the previous values so we can detect edges
            sclk_meta <= sclk_in;
            sclk_sync <= sclk_meta;
            sclk_prev <= sclk_sync;

            mosi_meta <= mosi_in;
            mosi_sync <= mosi_meta;

            cs_meta   <= cs_n_in;
            cs_sync   <= cs_meta;
            cs_prev   <= cs_sync;
        end
    end

    // Compare current and previous signal values
    // This tells us when the SPI clock or chip select changes
    wire sclk_rise =  sclk_sync & ~sclk_prev;
    wire sclk_fall = ~sclk_sync &  sclk_prev;
    wire cs_rise   =  cs_sync & ~cs_prev;
    wire cs_fall   = ~cs_sync &  cs_prev;


    // Each SPI message contains 24 bits:
    // First 8 bits = command
    // Next 16 bits = coefficient data or readback
    reg [4:0]  bit_count;
    reg [7:0]  command_shift;
    reg [7:0]  command_reg;
    reg [15:0] data_shift;
    reg [15:0] transmit_shift;

    // SPI is active when chip select is LOW
    assign active = ~cs_sync;

    // Give the coefficient module access to the received command
    assign current_command = command_reg;

    // Send the most significant bit of our response through MISO
    assign miso_out = transmit_shift[15];


    // Main SPI control logic
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // Clear all stored SPI data during reset
            bit_count      <= 5'd0;
            command_shift  <= 8'd0;
            command_reg    <= 8'd0;
            data_shift     <= 16'd0;
            transmit_shift <= 16'd0;
            frame_valid    <= 1'b0;
            frame_command  <= 8'd0;
            frame_data     <= 16'd0;

        end else begin

            // Normally keep frame_valid LOW
            // It only goes HIGH for one clock when a message finishes
            frame_valid <= 1'b0;

            if (cs_fall) begin

                // Chip select went LOW
                // This means the controller is starting a new message
                // Clear old data and begin counting bits from zero
                bit_count      <= 5'd0;
                command_shift  <= 8'd0;
                command_reg    <= 8'd0;
                data_shift     <= 16'd0;
                transmit_shift <= 16'd0;

            end else if (cs_rise) begin

                // Chip select went HIGH
                // The controller has finished sending its message
                // Only accept it if all 24 bits were received
                if (bit_count == 5'd24) begin
                    frame_valid   <= 1'b1;
                    frame_command <= command_reg;
                    frame_data    <= data_shift;
                end

            end else if (!cs_sync) begin

                // While SPI is selected, listen for clock edges

                if (sclk_rise && bit_count < 5'd24) begin

                    // Every rising SPI clock means one new bit arrived
                    bit_count <= bit_count + 5'd1;

                    if (bit_count < 5'd8) begin

                        // The first 8 bits represent our command
                        // Shift each new bit into the command register
                        command_shift <= {
                            command_shift[6:0],
                            mosi_sync
                        };

                        // Once the eighth bit arrives,
                        // we have received the complete command
                        if (bit_count == 5'd7)
                            command_reg <= {
                                command_shift[6:0],
                                mosi_sync
                            };

                    end else begin

                        // After the command, receive the 16 data bits
                        // These bits may contain a new coefficient
                        data_shift <= {
                            data_shift[14:0],
                            mosi_sync
                        };

                    end
                end


                // SPI mode 0 sends data on falling clock edges
                // This prepares the next bit before the controller reads it
                if (sclk_fall) begin

                    if (bit_count == 5'd8) begin

                        // Command has been received
                        // Load the data we want to send back
                        transmit_shift <= read_data;

                    end else if (
                        bit_count > 5'd8 &&
                        bit_count < 5'd24
                    ) begin

                        // Shift the next output bit toward MISO
                        // Each falling edge prepares another bit
                        transmit_shift <= {
                            transmit_shift[14:0],
                            1'b0
                        };

                    end
                end

            end
        end
    end

endmodule

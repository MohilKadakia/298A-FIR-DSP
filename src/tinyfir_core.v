
// SPDX-License-Identifier: Apache-2.0
// Main FIR filter module
// Stores the last 8 samples and calculates one filtered output at a time

module tinyfir_core (
    input  wire              clk,                  // Main clock
    input  wire              rst_n,                // Active-low reset
    input  wire              ena,                  // Enable the filter
    input  wire [7:0]        sample_in,            // New 8-bit input sample
    input  wire              sample_strobe,        // Tells us a new sample is ready
    input  wire              configuration_active, // SPI is currently being used
    input  wire              clear_history,        // Clear previous samples
    input  wire signed [8:0] tap_coefficient,      // Coefficient selected by the register module
    output reg  [2:0]        tap_index,            // Chooses one of the 8 coefficients
    output reg  [7:0]        sample_out,           // Final filtered sample
    output wire              ready,                // Ready for a new sample
    output wire              busy,                 // Currently processing
    output reg               output_valid,         // Pulses when a result is ready
    output reg               saturated             // Output was limited to 8-bit range
);

    // Three steps: wait for input, calculate, then send out the result
    localparam [1:0] IDLE    = 2'd0;
    localparam [1:0] MAC     = 2'd1;
    localparam [1:0] PUBLISH = 2'd2;
    reg [1:0] state;

    // Synchronize the external sample strobe with our main clock
    // This also lets us detect a new rising edge instead of repeatedly
    // accepting a strobe that stays high
    reg strobe_meta, strobe_sync, strobe_prev;
    wire strobe_rise = strobe_sync & ~strobe_prev;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            strobe_meta <= 1'b0;
            strobe_sync <= 1'b0;
            strobe_prev <= 1'b0;
        end else begin
            strobe_meta <= sample_strobe;
            strobe_sync <= strobe_meta;
            strobe_prev <= strobe_sync;
        end
    end

    // The filter is busy whenever it is calculating or publishing a result
    // New samples can only be accepted when idle and not using SPI
    assign busy  = (state != IDLE);
    assign ready = ena && (state == IDLE) &&
                   !configuration_active && !clear_history;

    // Keep the newest 8 input samples
    // history[0] is the newest and history[7] is the oldest
    reg signed [7:0] history [0:7];
    wire signed [7:0] selected_sample = history[tap_index];

    // Multiply one sample by one coefficient each clock cycle
    // We reuse the same multiplier for all 8 taps to save hardware
    wire signed [16:0] product = selected_sample * tap_coefficient;

    // Extend the signed product to match the accumulator size
    wire signed [19:0] extended_product = {{3{product[16]}}, product};
    reg signed [19:0] accumulator;

    // Our coefficients are scaled by 128, so shift right by 7
    // An arithmetic shift keeps the correct sign for negative numbers
    wire signed [19:0] scaled_result = accumulator >>> 7;

    // Make sure the result fits in a signed 8-bit output (-128 to 127)
    // If it is too large or too small, clamp it instead of wrapping around
    wire clipped_hi = (scaled_result >  20'sd127);
    wire clipped_lo = (scaled_result < -20'sd128);
    wire [7:0] result_8bit = clipped_hi ? 8'h7F :
                             clipped_lo ? 8'h80 : scaled_result[7:0];

    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // Clear samples, accumulator, and output on reset
            state        <= IDLE;
            tap_index    <= 3'd0;
            accumulator  <= 20'sd0;
            sample_out   <= 8'd0;
            output_valid <= 1'b0;
            saturated    <= 1'b0;
            for (i = 0; i < 8; i = i + 1)
                history[i] <= 8'sd0;
        end else begin
            // output_valid is normally low and only pulses for one clock
            output_valid <= 1'b0;

            // Clear old samples if a clear-history command was received
            // Coefficients are stored in another module, so they are unchanged
            if (clear_history && state == IDLE) begin
                for (i = 0; i < 8; i = i + 1)
                    history[i] <= 8'sd0;
            end

            case (state)
                IDLE: begin
                    // Wait until a new sample arrives and the filter is ready
                    if (ready && strobe_rise) begin
                        // Shift old samples back and store the newest sample
                        for (i = 7; i > 0; i = i - 1)
                            history[i] <= history[i-1];
                        history[0] <= sample_in;

                        // Start a fresh calculation from tap 0
                        accumulator <= 20'sd0;
                        tap_index   <= 3'd0;
                        state       <= MAC;
                    end
                end

                MAC: begin
                    // Add the current multiplication result to the total
                    // Move to the next tap each clock cycle
                    accumulator <= accumulator + extended_product;

                    if (tap_index == 3'd7) begin
                        // All 8 multiplications have finished
                        state <= PUBLISH;
                    end else begin
                        tap_index <= tap_index + 3'd1;
                    end
                end

                PUBLISH: begin
                    // Scale the total, clamp it if necessary, and save output
                    // Tell the external controller a new result is available
                    sample_out   <= result_8bit;
                    saturated    <= clipped_hi || clipped_lo;
                    output_valid <= 1'b1;
                    state        <= IDLE;
                end

                default: state <= IDLE;
            endcase
        end
    end

endmodule

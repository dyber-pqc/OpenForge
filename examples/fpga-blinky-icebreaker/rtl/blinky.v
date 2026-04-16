`timescale 1ns / 1ps
//-----------------------------------------------------------------------------
// blinky.v - LED blinky pattern for iCEBreaker FPGA (Lattice iCE40 UP5K)
//
// Divides the 12 MHz on-board oscillator to create visible LED patterns.
// A 24-bit counter produces four LED outputs at different blink rates.
//-----------------------------------------------------------------------------

module blinky (
    input  wire clk,    // 12 MHz oscillator on iCEBreaker
    output wire led1,   // User LED 1 (accent green)
    output wire led2,   // User LED 2 (accent green)
    output wire led3,   // User LED 3 (accent red)
    output wire led4,   // User LED 4 (accent red)
    output wire led5    // On-board LED (active-low accent green)
);

    // 24-bit free-running counter
    // At 12 MHz: bit 23 toggles at ~0.7 Hz, bit 20 at ~5.7 Hz
    reg [23:0] counter;

    always @(posedge clk) begin
        counter <= counter + 24'd1;
    end

    // LED outputs driven by different counter bits for a cascading pattern
    assign led1 = counter[23];   // ~0.7 Hz - slowest blink
    assign led2 = counter[22];   // ~1.4 Hz
    assign led3 = counter[21];   // ~2.9 Hz
    assign led4 = counter[20];   // ~5.7 Hz - fastest blink
    assign led5 = ~counter[23];  // On-board LED is active-low, mirrors LED1

endmodule

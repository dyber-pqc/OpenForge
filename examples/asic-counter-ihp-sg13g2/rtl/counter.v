`timescale 1ns / 1ps
//-----------------------------------------------------------------------------
// counter.v - 8-bit synchronous up-counter with enable and overflow
//
// Target: SkyWater sky130 (sky130_fd_sc_hd standard cells)
// Clock:  100 MHz (10 ns period)
//
// Features:
//   - Synchronous active-high reset
//   - Count enable
//   - 8-bit count output
//   - Overflow flag (pulses high for one cycle when count wraps from 255 to 0)
//-----------------------------------------------------------------------------

module counter (
    input  wire       clk,       // System clock
    input  wire       rst,       // Synchronous reset (active-high)
    input  wire       en,        // Count enable
    output reg  [7:0] count,     // 8-bit count value
    output reg        overflow   // Overflow flag (one-cycle pulse)
);

    always @(posedge clk) begin
        if (rst) begin
            count    <= 8'd0;
            overflow <= 1'b0;
        end else if (en) begin
            if (count == 8'd255) begin
                count    <= 8'd0;
                overflow <= 1'b1;
            end else begin
                count    <= count + 8'd1;
                overflow <= 1'b0;
            end
        end else begin
            overflow <= 1'b0;
        end
    end

endmodule

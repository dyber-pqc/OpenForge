// Simple testbench for counter module
`timescale 1ns / 1ps

module counter_tb;
    reg clk = 0;
    reg rst_n = 0;
    reg enable = 0;
    wire [7:0] count;
    wire overflow;

    // Clock generation: 10ns period
    always #5 clk = ~clk;

    // DUT instantiation
    counter dut (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .count(count),
        .overflow(overflow)
    );

    // Dump waveforms
    initial begin
        $dumpfile("dump.vcd");
        $dumpvars(0, counter_tb);
    end

    // Test sequence
    initial begin
        $display("=== Counter Testbench Start ===");

        // Reset
        rst_n = 0;
        enable = 0;
        #20;

        // Release reset
        rst_n = 1;
        #10;

        // Enable counting
        enable = 1;
        $display("Counting enabled at time %0t", $time);

        // Count for 20 cycles
        repeat (20) @(posedge clk);
        $display("Count = %0d at time %0t", count, $time);

        // Check count is incrementing (exact value depends on clock edge)
        if (count > 15 && count < 25) begin
            $display("PASS: count = %0d (in expected range)", count);
        end else begin
            $display("FAIL: count = %0d (out of range)", count);
        end

        // Disable and re-enable
        enable = 0;
        repeat (5) @(posedge clk);
        $display("Count after disable = %0d (should be unchanged)", count);

        enable = 1;
        repeat (10) @(posedge clk);
        $display("Count after re-enable = %0d", count);

        // Test reset during counting
        rst_n = 0;
        #20;
        rst_n = 1;
        $display("Count after reset = %0d (expected 0)", count);

        if (count == 0) begin
            $display("PASS: reset works");
        end else begin
            $display("FAIL: reset failed, count = %0d", count);
        end

        #50;
        $display("=== Counter Testbench End ===");
        $finish;
    end

endmodule

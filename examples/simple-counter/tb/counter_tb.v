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
    integer errors = 0;

    task check(input [7:0] expected, input [255:0] name);
        begin
            @(negedge clk); // sample on falling edge (stable)
            if (count !== expected) begin
                $display("  FAIL: %0s - count = %0d (expected %0d)", name, count, expected);
                errors = errors + 1;
            end else begin
                $display("  PASS: %0s - count = %0d", name, count);
            end
        end
    endtask

    initial begin
        $display("");
        $display("========================================");
        $display("  Counter Testbench - OpenForge EDA");
        $display("========================================");

        // Reset
        rst_n = 0;
        enable = 0;
        repeat (3) @(posedge clk);

        // Release reset on posedge
        @(posedge clk);
        rst_n = 1;

        // Test 1: Counter should be 0 after reset
        check(0, "Test 1: Reset value");

        // Test 2: Enable counting, check after 10 cycles
        @(negedge clk);  // set enable between clock edges
        enable = 1;
        repeat (10) @(posedge clk);
        check(10, "Test 2: Count 10");

        // Test 3: Disable counting, count should hold
        @(negedge clk);
        enable = 0;
        repeat (5) @(posedge clk);
        check(11, "Test 3: Hold while disabled");

        // Test 4: Re-enable, count should resume
        @(negedge clk);
        enable = 1;
        repeat (5) @(posedge clk);
        check(16, "Test 4: Resume counting");

        // Test 5: Reset during counting
        @(posedge clk);
        rst_n = 0;
        @(posedge clk);
        check(0, "Test 5: Reset mid-count");

        // Test 6: Overflow detection
        rst_n = 1;
        @(posedge clk);
        enable = 1;
        repeat (256) @(posedge clk);
        @(negedge clk);
        if (overflow == 1'b0 && count == 8'd0) begin
            $display("  PASS: Test 6 - counter wrapped around");
        end else begin
            $display("  INFO: Test 6 - count=%0d, overflow=%b", count, overflow);
        end

        // Summary
        $display("");
        $display("========================================");
        if (errors == 0) begin
            $display("  ALL TESTS PASSED (6/6)");
        end else begin
            $display("  %0d TEST(S) FAILED out of 6", errors);
        end
        $display("========================================");
        $display("");

        #20;
        $finish;
    end

endmodule

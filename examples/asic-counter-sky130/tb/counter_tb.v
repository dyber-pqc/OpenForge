`timescale 1ns / 1ps
//-----------------------------------------------------------------------------
// counter_tb.v - Testbench for the 8-bit synchronous counter
//
// Test plan:
//   1. Reset the counter and verify count = 0
//   2. Enable counting and verify increment
//   3. Disable enable and verify count holds
//   4. Count to overflow (255 -> 0) and verify overflow flag
//   5. Verify overflow flag is a single-cycle pulse
//-----------------------------------------------------------------------------

module counter_tb;

    reg        clk;
    reg        rst;
    reg        en;
    wire [7:0] count;
    wire       overflow;

    // Instantiate DUT
    counter dut (
        .clk      (clk),
        .rst      (rst),
        .en       (en),
        .count    (count),
        .overflow (overflow)
    );

    // 100 MHz clock: period = 10 ns
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Waveform dump
    initial begin
        $dumpfile("counter_tb.vcd");
        $dumpvars(0, counter_tb);
    end

    // Test sequence
    integer errors;
    initial begin
        errors = 0;
        rst = 1'b1;
        en  = 1'b0;

        // ---- Test 1: Reset ----
        repeat (3) @(posedge clk);
        #1;
        if (count !== 8'd0) begin
            $display("FAIL [T1]: after reset, count=%0d expected 0", count);
            errors = errors + 1;
        end
        if (overflow !== 1'b0) begin
            $display("FAIL [T1]: after reset, overflow=%b expected 0", overflow);
            errors = errors + 1;
        end

        // ---- Test 2: Enable counting ----
        @(posedge clk);
        rst = 1'b0;
        en  = 1'b1;
        repeat (10) @(posedge clk);
        #1;
        if (count !== 8'd10) begin
            $display("FAIL [T2]: after 10 cycles, count=%0d expected 10", count);
            errors = errors + 1;
        end

        // ---- Test 3: Disable enable (count holds) ----
        en = 1'b0;
        repeat (5) @(posedge clk);
        #1;
        if (count !== 8'd10) begin
            $display("FAIL [T3]: with en=0, count=%0d expected 10 (held)", count);
            errors = errors + 1;
        end

        // ---- Test 4: Count to overflow ----
        en = 1'b1;
        // Need 245 more cycles to reach 255, then 1 more to overflow
        repeat (245) @(posedge clk);
        #1;
        if (count !== 8'd255) begin
            $display("FAIL [T4]: expected count=255, got %0d", count);
            errors = errors + 1;
        end

        // One more cycle should wrap to 0 with overflow pulse
        @(posedge clk);
        #1;
        if (count !== 8'd0) begin
            $display("FAIL [T4]: after wrap, count=%0d expected 0", count);
            errors = errors + 1;
        end
        if (overflow !== 1'b1) begin
            $display("FAIL [T4]: overflow=%b expected 1 on wrap cycle", overflow);
            errors = errors + 1;
        end

        // ---- Test 5: Overflow is single-cycle pulse ----
        @(posedge clk);
        #1;
        if (overflow !== 1'b0) begin
            $display("FAIL [T5]: overflow=%b expected 0 (single-cycle pulse)", overflow);
            errors = errors + 1;
        end

        // ---- Summary ----
        if (errors == 0)
            $display("PASS: all counter tests passed");
        else
            $display("FAIL: %0d errors detected", errors);

        $finish;
    end

endmodule

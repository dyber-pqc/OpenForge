`timescale 1ns / 1ps
//-----------------------------------------------------------------------------
// counter_tb.v - Testbench for the 8-bit synchronous counter (gf180mcuC).
//
// Identical stimulus to the sky130 variant; only the clock period is
// relaxed (20 ns / 50 MHz) to match the slower 180 nm target.
//-----------------------------------------------------------------------------

module counter_tb;

    reg        clk;
    reg        rst;
    reg        en;
    wire [7:0] count;
    wire       overflow;

    counter dut (
        .clk      (clk),
        .rst      (rst),
        .en       (en),
        .count    (count),
        .overflow (overflow)
    );

    // 50 MHz clock: period = 20 ns
    initial clk = 1'b0;
    always #10 clk = ~clk;

    initial begin
        $dumpfile("counter_tb.vcd");
        $dumpvars(0, counter_tb);
    end

    integer errors;
    initial begin
        errors = 0;
        rst = 1'b1;
        en  = 1'b0;

        repeat (3) @(posedge clk);
        #1;
        if (count !== 8'd0) begin
            $display("FAIL [T1]: after reset, count=%0d expected 0", count);
            errors = errors + 1;
        end

        @(posedge clk);
        rst = 1'b0;
        en  = 1'b1;
        repeat (10) @(posedge clk);
        #1;
        if (count !== 8'd10) begin
            $display("FAIL [T2]: after 10 cycles, count=%0d expected 10", count);
            errors = errors + 1;
        end

        en = 1'b0;
        repeat (5) @(posedge clk);
        #1;
        if (count !== 8'd10) begin
            $display("FAIL [T3]: with en=0, count=%0d expected 10 (held)", count);
            errors = errors + 1;
        end

        en = 1'b1;
        repeat (245) @(posedge clk);
        #1;
        if (count !== 8'd255) begin
            $display("FAIL [T4]: expected count=255, got %0d", count);
            errors = errors + 1;
        end

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

        @(posedge clk);
        #1;
        if (overflow !== 1'b0) begin
            $display("FAIL [T5]: overflow=%b expected 0 (single-cycle pulse)", overflow);
            errors = errors + 1;
        end

        if (errors == 0)
            $display("PASS: all counter tests passed");
        else
            $display("FAIL: %0d errors detected", errors);

        $finish;
    end

endmodule

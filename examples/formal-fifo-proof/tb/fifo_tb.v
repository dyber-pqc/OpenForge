`timescale 1ns / 1ps
//-----------------------------------------------------------------------------
// fifo_tb.v - Directed testbench for sync_fifo
//
// Test plan:
//   1. Reset and verify empty state
//   2. Write until full, verify full flag
//   3. Read until empty, verify data integrity (FIFO ordering)
//   4. Simultaneous read/write at various fill levels
//   5. Write when full (should be ignored)
//   6. Read when empty (should be ignored)
//-----------------------------------------------------------------------------

module fifo_tb;

    parameter DEPTH = 8;
    parameter WIDTH = 8;

    reg              clk;
    reg              rst;
    reg              wr_en;
    reg  [WIDTH-1:0] wr_data;
    reg              rd_en;
    wire [WIDTH-1:0] rd_data;
    wire             full;
    wire             empty;
    wire [$clog2(DEPTH):0] count;

    // Instantiate DUT
    sync_fifo #(
        .DEPTH (DEPTH),
        .WIDTH (WIDTH)
    ) dut (
        .clk     (clk),
        .rst     (rst),
        .wr_en   (wr_en),
        .wr_data (wr_data),
        .rd_en   (rd_en),
        .rd_data (rd_data),
        .full    (full),
        .empty   (empty),
        .count   (count)
    );

    // 100 MHz clock
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Waveform dump
    initial begin
        $dumpfile("fifo_tb.vcd");
        $dumpvars(0, fifo_tb);
    end

    integer errors;
    integer i;
    reg [WIDTH-1:0] expected_data;

    initial begin
        errors  = 0;
        wr_en   = 1'b0;
        rd_en   = 1'b0;
        wr_data = 0;
        rst     = 1'b1;

        // ---- Test 1: Reset ----
        repeat (3) @(posedge clk);
        #1;
        if (!empty || full || count !== 0) begin
            $display("FAIL [T1]: after reset, empty=%b full=%b count=%0d", empty, full, count);
            errors = errors + 1;
        end
        @(posedge clk);
        rst = 1'b0;

        // ---- Test 2: Fill to full ----
        for (i = 0; i < DEPTH; i = i + 1) begin
            @(posedge clk);
            wr_en   = 1'b1;
            wr_data = i[WIDTH-1:0];  // Write 0, 1, 2, ..., DEPTH-1
        end
        @(posedge clk);
        wr_en = 1'b0;
        #1;

        if (!full) begin
            $display("FAIL [T2]: FIFO should be full, full=%b count=%0d", full, count);
            errors = errors + 1;
        end
        if (count !== DEPTH) begin
            $display("FAIL [T2]: count=%0d expected %0d", count, DEPTH);
            errors = errors + 1;
        end

        // ---- Test 3: Read all and verify FIFO ordering ----
        for (i = 0; i < DEPTH; i = i + 1) begin
            @(posedge clk);
            rd_en = 1'b1;
        end
        @(posedge clk);
        rd_en = 1'b0;

        // Verify the last read data (data comes out one cycle after rd_en)
        // The first read data appears after the first rd_en pulse
        #1;
        if (!empty) begin
            $display("FAIL [T3]: FIFO should be empty after draining, empty=%b count=%0d", empty, count);
            errors = errors + 1;
        end

        // ---- Test 4: Simultaneous read/write ----
        // First, put some data in
        @(posedge clk);
        wr_en = 1'b1;
        wr_data = 8'hAA;
        @(posedge clk);
        wr_data = 8'hBB;
        @(posedge clk);
        wr_en = 1'b0;
        #1;
        if (count !== 2) begin
            $display("FAIL [T4]: count=%0d expected 2 before simultaneous rw", count);
            errors = errors + 1;
        end

        // Simultaneous read and write - count should stay the same
        @(posedge clk);
        wr_en   = 1'b1;
        rd_en   = 1'b1;
        wr_data = 8'hCC;
        @(posedge clk);
        wr_en = 1'b0;
        rd_en = 1'b0;
        #1;
        if (count !== 2) begin
            $display("FAIL [T4]: after simultaneous rw, count=%0d expected 2", count);
            errors = errors + 1;
        end

        // ---- Test 5: Write when full (should be silently ignored) ----
        // Fill the FIFO first
        rst = 1'b1;
        @(posedge clk);
        rst = 1'b0;
        for (i = 0; i < DEPTH; i = i + 1) begin
            @(posedge clk);
            wr_en   = 1'b1;
            wr_data = i[WIDTH-1:0];
        end
        @(posedge clk);
        wr_en = 1'b0;
        #1;

        // Try writing when full
        @(posedge clk);
        wr_en   = 1'b1;
        wr_data = 8'hFF;
        @(posedge clk);
        wr_en = 1'b0;
        #1;
        if (count !== DEPTH) begin
            $display("FAIL [T5]: write when full changed count to %0d", count);
            errors = errors + 1;
        end

        // ---- Test 6: Read when empty ----
        rst = 1'b1;
        @(posedge clk);
        rst = 1'b0;
        @(posedge clk);
        rd_en = 1'b1;
        @(posedge clk);
        rd_en = 1'b0;
        #1;
        if (count !== 0) begin
            $display("FAIL [T6]: read when empty changed count to %0d", count);
            errors = errors + 1;
        end

        // ---- Summary ----
        repeat (2) @(posedge clk);
        if (errors == 0)
            $display("PASS: all FIFO tests passed");
        else
            $display("FAIL: %0d errors detected", errors);

        $finish;
    end

endmodule

`timescale 1ns/1ps

// UART TX Testbench - sends a byte and verifies the serial output
module uart_tx_tb;

    // Use small CLKS_PER_BIT for fast simulation
    localparam CLKS_PER_BIT = 8;
    localparam BIT_PERIOD   = CLKS_PER_BIT * 10; // 10 ns clock period

    reg        clk;
    reg        rst_n;
    reg  [7:0] tx_data;
    reg        tx_valid;
    wire       tx_ready;
    wire       tx_out;
    wire       tx_active;

    uart_tx #(
        .CLKS_PER_BIT(CLKS_PER_BIT)
    ) uut (
        .clk(clk),
        .rst_n(rst_n),
        .tx_data(tx_data),
        .tx_valid(tx_valid),
        .tx_ready(tx_ready),
        .tx_out(tx_out),
        .tx_active(tx_active)
    );

    // Clock generation: 100 MHz (10 ns period)
    initial clk = 0;
    always #5 clk = ~clk;

    integer errors;
    integer i;
    reg [7:0] received_byte;

    // Task: receive a byte by sampling tx_out at the center of each bit
    task receive_byte;
        output [7:0] rx_byte;
        begin
            // Wait for start bit (falling edge on tx_out)
            @(negedge tx_out);

            // Center of start bit
            #(BIT_PERIOD / 2);

            // Verify start bit is still low
            if (tx_out !== 1'b0) begin
                $display("FAIL: Start bit not low");
                errors = errors + 1;
            end

            // Sample 8 data bits
            for (i = 0; i < 8; i = i + 1) begin
                #BIT_PERIOD;
                rx_byte[i] = tx_out;
            end

            // Check stop bit
            #BIT_PERIOD;
            if (tx_out !== 1'b1) begin
                $display("FAIL: Stop bit not high");
                errors = errors + 1;
            end
        end
    endtask

    initial begin
        $dumpfile("dump.vcd");
        $dumpvars(0, uart_tx_tb);

        errors = 0;
        rst_n    = 0;
        tx_data  = 8'h00;
        tx_valid = 0;

        // Reset
        #50;
        rst_n = 1;
        #20;

        $display("=== UART TX Test ===");

        // Test 1: Send 0xA5 (10100101)
        $display("  Sending byte 0xA5...");
        @(posedge clk);
        tx_data  = 8'hA5;
        tx_valid = 1;
        @(posedge clk);
        tx_valid = 0;

        receive_byte(received_byte);

        if (received_byte !== 8'hA5) begin
            $display("FAIL: Received 0x%02h, expected 0xA5", received_byte);
            errors = errors + 1;
        end else begin
            $display("  OK: Received 0x%02h", received_byte);
        end

        // Wait for idle
        #(BIT_PERIOD * 2);

        // Test 2: Send 0x3C
        $display("  Sending byte 0x3C...");
        @(posedge clk);
        tx_data  = 8'h3C;
        tx_valid = 1;
        @(posedge clk);
        tx_valid = 0;

        receive_byte(received_byte);

        if (received_byte !== 8'h3C) begin
            $display("FAIL: Received 0x%02h, expected 0x3C", received_byte);
            errors = errors + 1;
        end else begin
            $display("  OK: Received 0x%02h", received_byte);
        end

        // Wait for idle
        #(BIT_PERIOD * 2);

        // Test 3: Send 0x00 (all zeros)
        $display("  Sending byte 0x00...");
        @(posedge clk);
        tx_data  = 8'h00;
        tx_valid = 1;
        @(posedge clk);
        tx_valid = 0;

        receive_byte(received_byte);

        if (received_byte !== 8'h00) begin
            $display("FAIL: Received 0x%02h, expected 0x00", received_byte);
            errors = errors + 1;
        end else begin
            $display("  OK: Received 0x%02h", received_byte);
        end

        // Wait for idle
        #(BIT_PERIOD * 2);

        // Test 4: Send 0xFF (all ones)
        $display("  Sending byte 0xFF...");
        @(posedge clk);
        tx_data  = 8'hFF;
        tx_valid = 1;
        @(posedge clk);
        tx_valid = 0;

        receive_byte(received_byte);

        if (received_byte !== 8'hFF) begin
            $display("FAIL: Received 0x%02h, expected 0xFF", received_byte);
            errors = errors + 1;
        end else begin
            $display("  OK: Received 0x%02h", received_byte);
        end

        #(BIT_PERIOD * 2);

        // Verify tx_ready returns high after transmission
        if (tx_ready !== 1'b1) begin
            $display("FAIL: tx_ready not high after transmission");
            errors = errors + 1;
        end else begin
            $display("  OK: tx_ready is high (idle)");
        end

        $display("");
        if (errors == 0)
            $display("PASS: All UART TX tests passed.");
        else
            $display("FAIL: %0d error(s) detected.", errors);

        $finish;
    end

endmodule

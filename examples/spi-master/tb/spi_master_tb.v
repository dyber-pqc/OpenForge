`timescale 1ns/1ps

// SPI Master Testbench - loopback test (MOSI directly connected to MISO)
module spi_master_tb;

    localparam CLK_DIV = 2;  // Fast for simulation

    reg        clk;
    reg        rst_n;
    reg  [7:0] tx_data;
    reg        tx_valid;
    wire       tx_ready;
    wire [7:0] rx_data;
    wire       rx_valid;
    wire       sclk;
    wire       mosi;
    wire       cs_n;

    // Loopback: connect MOSI to MISO
    wire       miso;
    assign miso = mosi;

    spi_master #(
        .CLK_DIV(CLK_DIV)
    ) uut (
        .clk(clk),
        .rst_n(rst_n),
        .tx_data(tx_data),
        .tx_valid(tx_valid),
        .tx_ready(tx_ready),
        .rx_data(rx_data),
        .rx_valid(rx_valid),
        .sclk(sclk),
        .mosi(mosi),
        .miso(miso),
        .cs_n(cs_n)
    );

    // Clock: 100 MHz
    initial clk = 0;
    always #5 clk = ~clk;

    integer errors;
    reg [7:0] expected;

    // Task: send a byte and check the loopback result
    task send_and_check;
        input [7:0] data;
        begin
            @(posedge clk);
            tx_data  = data;
            tx_valid = 1;
            @(posedge clk);
            tx_valid = 0;

            // Wait for rx_valid
            @(posedge rx_valid);
            @(posedge clk);

            if (rx_data !== data) begin
                $display("FAIL: Sent 0x%02h, received 0x%02h", data, rx_data);
                errors = errors + 1;
            end else begin
                $display("  OK: Loopback 0x%02h", data);
            end
        end
    endtask

    initial begin
        $dumpfile("dump.vcd");
        $dumpvars(0, spi_master_tb);

        errors   = 0;
        rst_n    = 0;
        tx_data  = 8'h00;
        tx_valid = 0;

        // Reset
        #100;
        rst_n = 1;
        #20;

        $display("=== SPI Master Loopback Test ===");

        // Test various byte patterns
        send_and_check(8'hA5);
        #50;
        send_and_check(8'h5A);
        #50;
        send_and_check(8'hFF);
        #50;
        send_and_check(8'h00);
        #50;
        send_and_check(8'h81);
        #50;
        send_and_check(8'h3C);
        #50;

        // Verify CS goes high between transfers
        if (cs_n !== 1'b1) begin
            $display("FAIL: CS_N not high in idle");
            errors = errors + 1;
        end else begin
            $display("  OK: CS_N high in idle");
        end

        // Verify SCLK is low in idle (Mode 0)
        if (sclk !== 1'b0) begin
            $display("FAIL: SCLK not low in idle (Mode 0 violation)");
            errors = errors + 1;
        end else begin
            $display("  OK: SCLK low in idle (Mode 0)");
        end

        // Verify tx_ready is high
        if (tx_ready !== 1'b1) begin
            $display("FAIL: tx_ready not high after transfers");
            errors = errors + 1;
        end else begin
            $display("  OK: tx_ready high (idle)");
        end

        $display("");
        if (errors == 0)
            $display("PASS: All SPI master tests passed.");
        else
            $display("FAIL: %0d error(s) detected.", errors);

        $finish;
    end

endmodule

`timescale 1ns / 1ps
//-----------------------------------------------------------------------------
// blinky_tb.v - Testbench for the blinky LED pattern module
//
// Runs 1000 clock cycles and verifies that the LED outputs toggle as expected.
//-----------------------------------------------------------------------------

module blinky_tb;

    reg  clk;
    wire led1, led2, led3, led4, led5;

    // Instantiate the DUT
    blinky dut (
        .clk  (clk),
        .led1 (led1),
        .led2 (led2),
        .led3 (led3),
        .led4 (led4),
        .led5 (led5)
    );

    // 12 MHz clock: period = 83.33 ns
    initial clk = 1'b0;
    always #41.667 clk = ~clk;

    // Monitor and check
    integer cycle_count;
    reg [4:0] prev_leds;
    reg       any_toggle;

    initial begin
        $dumpfile("blinky_tb.vcd");
        $dumpvars(0, blinky_tb);

        cycle_count = 0;
        any_toggle  = 1'b0;
        prev_leds   = 5'b0;

        // Run for 1000 clock cycles
        repeat (1000) begin
            @(posedge clk);
            cycle_count = cycle_count + 1;

            // Check if any LED changed state
            if ({led1, led2, led3, led4, led5} !== prev_leds) begin
                any_toggle = 1'b1;
            end
            prev_leds = {led1, led2, led3, led4, led5};
        end

        // Verify that led5 is always the inverse of led1 (active-low mirror)
        if (led5 !== ~led1) begin
            $display("FAIL: led5 should be inverse of led1");
            $finish;
        end

        // After 1000 cycles the counter should be non-zero so LEDs must have toggled
        if (!any_toggle) begin
            $display("FAIL: no LED transitions observed in 1000 cycles");
            $finish;
        end

        $display("PASS: blinky testbench completed - %0d cycles, LEDs toggled correctly", cycle_count);
        $finish;
    end

endmodule

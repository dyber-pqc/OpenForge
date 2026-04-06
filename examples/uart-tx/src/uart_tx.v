`timescale 1ns/1ps

// UART Transmitter - 8N1 format with configurable baud rate
// Transmits one byte at a time: START(0), D0..D7 (LSB first), STOP(1).
// The baud rate is derived from the system clock using CLKS_PER_BIT.

module uart_tx #(
    parameter CLKS_PER_BIT = 87  // 100 MHz / 115200 baud ~ 868, use 87 for sim
)(
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] tx_data,
    input  wire       tx_valid,
    output reg        tx_ready,
    output reg        tx_out,
    output reg        tx_active
);

    // State encoding
    localparam S_IDLE  = 3'd0;
    localparam S_START = 3'd1;
    localparam S_DATA  = 3'd2;
    localparam S_STOP  = 3'd3;

    reg [2:0]  state;
    reg [15:0] clk_count;
    reg [2:0]  bit_index;
    reg [7:0]  tx_shift;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= S_IDLE;
            clk_count <= 16'd0;
            bit_index <= 3'd0;
            tx_shift  <= 8'd0;
            tx_out    <= 1'b1;   // Idle high
            tx_ready  <= 1'b1;
            tx_active <= 1'b0;
        end else begin
            case (state)
                S_IDLE: begin
                    tx_out    <= 1'b1;
                    tx_ready  <= 1'b1;
                    tx_active <= 1'b0;
                    clk_count <= 16'd0;
                    bit_index <= 3'd0;

                    if (tx_valid) begin
                        tx_shift  <= tx_data;
                        tx_ready  <= 1'b0;
                        tx_active <= 1'b1;
                        state     <= S_START;
                    end
                end

                S_START: begin
                    // Send start bit (low)
                    tx_out <= 1'b0;

                    if (clk_count < CLKS_PER_BIT - 1) begin
                        clk_count <= clk_count + 16'd1;
                    end else begin
                        clk_count <= 16'd0;
                        state     <= S_DATA;
                    end
                end

                S_DATA: begin
                    // Send data bits LSB first
                    tx_out <= tx_shift[bit_index];

                    if (clk_count < CLKS_PER_BIT - 1) begin
                        clk_count <= clk_count + 16'd1;
                    end else begin
                        clk_count <= 16'd0;
                        if (bit_index < 3'd7) begin
                            bit_index <= bit_index + 3'd1;
                        end else begin
                            bit_index <= 3'd0;
                            state     <= S_STOP;
                        end
                    end
                end

                S_STOP: begin
                    // Send stop bit (high)
                    tx_out <= 1'b1;

                    if (clk_count < CLKS_PER_BIT - 1) begin
                        clk_count <= clk_count + 16'd1;
                    end else begin
                        clk_count <= 16'd0;
                        tx_active <= 1'b0;
                        tx_ready  <= 1'b1;
                        state     <= S_IDLE;
                    end
                end

                default: begin
                    state <= S_IDLE;
                end
            endcase
        end
    end

endmodule

`timescale 1ns/1ps

// SPI Master Controller - Mode 0 (CPOL=0, CPHA=0)
// Configurable clock divider, 8-bit transfers.
// SCLK idles low, data sampled on rising edge, shifted out on falling edge.

module spi_master #(
    parameter CLK_DIV = 4  // SCLK = clk / (2 * CLK_DIV)
)(
    input  wire       clk,
    input  wire       rst_n,

    // Control interface
    input  wire [7:0] tx_data,
    input  wire       tx_valid,
    output reg        tx_ready,
    output reg  [7:0] rx_data,
    output reg        rx_valid,

    // SPI bus
    output reg        sclk,
    output reg        mosi,
    input  wire       miso,
    output reg        cs_n
);

    localparam S_IDLE    = 3'd0;
    localparam S_CS_LOW  = 3'd1;
    localparam S_SHIFT   = 3'd2;
    localparam S_SAMPLE  = 3'd3;
    localparam S_DONE    = 3'd4;

    reg [2:0]  state;
    reg [15:0] clk_cnt;
    reg [2:0]  bit_cnt;
    reg [7:0]  shift_out;
    reg [7:0]  shift_in;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= S_IDLE;
            clk_cnt   <= 16'd0;
            bit_cnt   <= 3'd0;
            shift_out <= 8'd0;
            shift_in  <= 8'd0;
            tx_ready  <= 1'b1;
            rx_data   <= 8'd0;
            rx_valid  <= 1'b0;
            sclk      <= 1'b0;
            mosi      <= 1'b0;
            cs_n      <= 1'b1;
        end else begin
            rx_valid <= 1'b0;  // Default: pulse for one cycle

            case (state)
                S_IDLE: begin
                    sclk     <= 1'b0;
                    cs_n     <= 1'b1;
                    tx_ready <= 1'b1;
                    bit_cnt  <= 3'd0;
                    clk_cnt  <= 16'd0;

                    if (tx_valid) begin
                        shift_out <= tx_data;
                        shift_in  <= 8'd0;
                        tx_ready  <= 1'b0;
                        cs_n      <= 1'b0;
                        mosi      <= tx_data[7]; // MSB first
                        state     <= S_CS_LOW;
                    end
                end

                S_CS_LOW: begin
                    // Brief CS setup time
                    if (clk_cnt < CLK_DIV - 1) begin
                        clk_cnt <= clk_cnt + 16'd1;
                    end else begin
                        clk_cnt <= 16'd0;
                        sclk    <= 1'b1;    // Rising edge: slave samples MOSI
                        state   <= S_SAMPLE;
                    end
                end

                S_SAMPLE: begin
                    // SCLK is high - sample MISO on this edge
                    if (clk_cnt == 16'd0) begin
                        shift_in <= {shift_in[6:0], miso};
                    end

                    if (clk_cnt < CLK_DIV - 1) begin
                        clk_cnt <= clk_cnt + 16'd1;
                    end else begin
                        clk_cnt <= 16'd0;
                        sclk    <= 1'b0;    // Falling edge: shift out next bit

                        if (bit_cnt < 3'd7) begin
                            bit_cnt   <= bit_cnt + 3'd1;
                            mosi      <= shift_out[6 - bit_cnt]; // Next bit MSB first
                            state     <= S_SHIFT;
                        end else begin
                            state <= S_DONE;
                        end
                    end
                end

                S_SHIFT: begin
                    // SCLK is low - hold data, wait half period
                    if (clk_cnt < CLK_DIV - 1) begin
                        clk_cnt <= clk_cnt + 16'd1;
                    end else begin
                        clk_cnt <= 16'd0;
                        sclk    <= 1'b1;    // Rising edge again
                        state   <= S_SAMPLE;
                    end
                end

                S_DONE: begin
                    // Transfer complete
                    cs_n     <= 1'b1;
                    rx_data  <= shift_in;
                    rx_valid <= 1'b1;
                    tx_ready <= 1'b1;
                    mosi     <= 1'b0;
                    state    <= S_IDLE;
                end

                default: begin
                    state <= S_IDLE;
                end
            endcase
        end
    end

endmodule

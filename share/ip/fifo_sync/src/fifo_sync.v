`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////
// OpenForge EDA - Synchronous FIFO (Register-Based)
//
// Features:
//   - Parameterized width and depth
//   - Simple register array storage (no BRAM inference)
//   - Full, empty, and count status outputs
//   - Overflow/underflow protection (writes ignored when full, reads ignored
//     when empty)
//   - Single clock domain, active-low synchronous reset
//   - Zero read latency (combinational read from head)
//
// Ports:
//   clk       - System clock
//   rst_n     - Active-low synchronous reset
//   wr_en     - Write enable
//   wr_data   - Write data input
//   rd_en     - Read enable
//   rd_data   - Read data output (valid when !empty)
//   full      - FIFO is full
//   empty     - FIFO is empty
//   count     - Number of entries currently stored
//
// Copyright (c) 2024-2026 OpenForge Contributors
// SPDX-License-Identifier: Apache-2.0
//////////////////////////////////////////////////////////////////////////////

module fifo_sync #(
    parameter WIDTH = 8,            // Data width in bits
    parameter DEPTH = 16,           // FIFO depth (number of entries)
    parameter ADDR_W = $clog2(DEPTH) // Address width (auto-calculated)
) (
    input  wire              clk,
    input  wire              rst_n,

    // Write port
    input  wire              wr_en,
    input  wire [WIDTH-1:0]  wr_data,

    // Read port
    input  wire              rd_en,
    output wire [WIDTH-1:0]  rd_data,

    // Status
    output wire              full,
    output wire              empty,
    output reg [ADDR_W:0]    count     // Extra bit for full count (0..DEPTH)
);

    // =========================================================================
    // Storage and pointers
    // =========================================================================
    (* ram_style = "registers" *)
    reg [WIDTH-1:0] mem [0:DEPTH-1];

    reg [ADDR_W-1:0] wr_ptr;  // Write pointer
    reg [ADDR_W-1:0] rd_ptr;  // Read pointer

    // =========================================================================
    // Status flags
    // =========================================================================
    assign full  = (count == DEPTH);
    assign empty = (count == 0);

    // =========================================================================
    // Combinational read output (zero latency)
    // =========================================================================
    assign rd_data = mem[rd_ptr];

    // =========================================================================
    // Write/read pointer and count management
    // =========================================================================
    wire do_write = wr_en && !full;
    wire do_read  = rd_en && !empty;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr <= {ADDR_W{1'b0}};
            rd_ptr <= {ADDR_W{1'b0}};
            count  <= {(ADDR_W+1){1'b0}};
        end else begin
            case ({do_write, do_read})
                2'b10: begin
                    // Write only
                    mem[wr_ptr] <= wr_data;
                    wr_ptr      <= (wr_ptr == DEPTH - 1) ? {ADDR_W{1'b0}} : wr_ptr + 1;
                    count       <= count + 1;
                end
                2'b01: begin
                    // Read only
                    rd_ptr <= (rd_ptr == DEPTH - 1) ? {ADDR_W{1'b0}} : rd_ptr + 1;
                    count  <= count - 1;
                end
                2'b11: begin
                    // Simultaneous read and write
                    mem[wr_ptr] <= wr_data;
                    wr_ptr      <= (wr_ptr == DEPTH - 1) ? {ADDR_W{1'b0}} : wr_ptr + 1;
                    rd_ptr      <= (rd_ptr == DEPTH - 1) ? {ADDR_W{1'b0}} : rd_ptr + 1;
                    // Count stays the same
                end
                default: ;  // No operation
            endcase
        end
    end

    // =========================================================================
    // Assertions (simulation only, ignored by synthesis)
    // =========================================================================
    // synthesis translate_off
    always @(posedge clk) begin
        if (rst_n) begin
            if (wr_en && full && !rd_en)
                $display("WARNING: %m FIFO write while full at time %0t", $time);
            if (rd_en && empty)
                $display("WARNING: %m FIFO read while empty at time %0t", $time);
        end
    end
    // synthesis translate_on

endmodule

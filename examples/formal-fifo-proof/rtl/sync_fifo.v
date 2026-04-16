`timescale 1ns / 1ps
//-----------------------------------------------------------------------------
// sync_fifo.v - Parameterized synchronous FIFO
//
// A single-clock FIFO with binary read/write pointers, full/empty flags,
// and a count output. Designed for formal verification of safety properties.
//
// Parameters:
//   DEPTH - Number of entries (must be a power of 2)
//   WIDTH - Data width in bits
//-----------------------------------------------------------------------------

module sync_fifo #(
    parameter DEPTH = 8,
    parameter WIDTH = 8
) (
    input  wire             clk,
    input  wire             rst,       // Synchronous reset (active-high)

    // Write interface
    input  wire             wr_en,     // Write enable
    input  wire [WIDTH-1:0] wr_data,   // Write data

    // Read interface
    input  wire             rd_en,     // Read enable
    output reg  [WIDTH-1:0] rd_data,   // Read data

    // Status flags
    output wire             full,
    output wire             empty,
    output reg  [$clog2(DEPTH):0] count  // Number of entries currently stored
);

    // Local parameters
    localparam ADDR_W = $clog2(DEPTH);

    // Internal storage
    reg [WIDTH-1:0] mem [0:DEPTH-1];

    // Pointers
    reg [ADDR_W:0] wr_ptr;  // Extra bit for full/empty disambiguation
    reg [ADDR_W:0] rd_ptr;

    // Derived signals
    wire [ADDR_W-1:0] wr_addr = wr_ptr[ADDR_W-1:0];
    wire [ADDR_W-1:0] rd_addr = rd_ptr[ADDR_W-1:0];

    // Full when pointers match in lower bits but differ in MSB
    assign full  = (wr_ptr[ADDR_W] != rd_ptr[ADDR_W]) &&
                   (wr_ptr[ADDR_W-1:0] == rd_ptr[ADDR_W-1:0]);

    // Empty when pointers are identical
    assign empty = (wr_ptr == rd_ptr);

    // Internal write/read enable (gated by full/empty)
    wire do_write = wr_en && !full;
    wire do_read  = rd_en && !empty;

    // Write logic
    always @(posedge clk) begin
        if (rst) begin
            wr_ptr <= {(ADDR_W+1){1'b0}};
        end else if (do_write) begin
            mem[wr_addr] <= wr_data;
            wr_ptr <= wr_ptr + 1'b1;
        end
    end

    // Read logic
    always @(posedge clk) begin
        if (rst) begin
            rd_ptr  <= {(ADDR_W+1){1'b0}};
            rd_data <= {WIDTH{1'b0}};
        end else if (do_read) begin
            rd_data <= mem[rd_addr];
            rd_ptr  <= rd_ptr + 1'b1;
        end
    end

    // Count logic
    always @(posedge clk) begin
        if (rst) begin
            count <= 0;
        end else begin
            case ({do_write, do_read})
                2'b10:   count <= count + 1'b1;  // Write only
                2'b01:   count <= count - 1'b1;  // Read only
                default: count <= count;          // Both or neither
            endcase
        end
    end

endmodule

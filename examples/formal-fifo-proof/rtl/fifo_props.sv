`timescale 1ns / 1ps
//-----------------------------------------------------------------------------
// fifo_props.sv - Formal properties (assertions + covers) for sync_fifo
//
// These properties are bound to the sync_fifo module during formal
// verification via SymbiYosys. They prove critical safety invariants
// and verify that important behaviors are reachable.
//-----------------------------------------------------------------------------

module fifo_props #(
    parameter DEPTH = 8,
    parameter WIDTH = 8
) (
    input wire                      clk,
    input wire                      rst,
    input wire                      wr_en,
    input wire                      rd_en,
    input wire                      full,
    input wire                      empty,
    input wire [$clog2(DEPTH):0]    count
);

    // ---- Safety assertions ------------------------------------------------

    // A1: Never write when full - the FIFO silently drops writes when full,
    //     but the count must never exceed DEPTH.
    assert property (@(posedge clk) disable iff (rst)
        count <= DEPTH
    );

    // A2: Count is never negative (unsigned, but check it never wraps)
    assert property (@(posedge clk) disable iff (rst)
        count <= DEPTH
    );

    // A3: Full flag is consistent with count
    assert property (@(posedge clk) disable iff (rst)
        full == (count == DEPTH)
    );

    // A4: Empty flag is consistent with count
    assert property (@(posedge clk) disable iff (rst)
        empty == (count == 0)
    );

    // A5: Full and empty are mutually exclusive (for DEPTH > 0)
    assert property (@(posedge clk) disable iff (rst)
        !(full && empty)
    );

    // A6: After reset, FIFO is empty
    assert property (@(posedge clk)
        $past(rst) |-> empty && (count == 0)
    );

    // ---- Cover properties (reachability) ----------------------------------

    // C1: Can reach full state
    cover property (@(posedge clk) disable iff (rst)
        full
    );

    // C2: Can recover from full
    cover property (@(posedge clk) disable iff (rst)
        full ##1 !full
    );

    // C3: Can reach empty state (after being non-empty)
    cover property (@(posedge clk) disable iff (rst)
        !empty ##1 empty
    );

    // C4: Can recover from empty
    cover property (@(posedge clk) disable iff (rst)
        empty ##1 !empty
    );

    // C5: Simultaneous read and write at any count
    cover property (@(posedge clk) disable iff (rst)
        wr_en && rd_en && !full && !empty
    );

    // C6: Can fill to half capacity
    cover property (@(posedge clk) disable iff (rst)
        count == DEPTH / 2
    );

endmodule

// Bind the properties to the DUT
bind sync_fifo fifo_props #(
    .DEPTH(DEPTH),
    .WIDTH(WIDTH)
) props_inst (
    .clk   (clk),
    .rst   (rst),
    .wr_en (wr_en),
    .rd_en (rd_en),
    .full  (full),
    .empty (empty),
    .count (count)
);

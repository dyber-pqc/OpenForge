`timescale 1ns/1ps

// Keccak-f[1600] round testbench
// Tests the round function with the all-zero state (round 0).
// For the all-zero state, after theta/rho/pi/chi the state is all-ones
// in certain positions, then iota XORs in the round constant.
// Round 0 constant: 0x0000000000000001

module keccak_round_tb;

    reg  [1599:0] state_in;
    wire [1599:0] state_out;
    reg  [63:0]   round_constant;

    keccak_round uut (
        .state_in(state_in),
        .round_constant(round_constant),
        .state_out(state_out)
    );

    // 24 round constants for Keccak-f[1600]
    reg [63:0] RC [0:23];

    integer errors;
    integer i;

    // Extract lane [x][y] from a 1600-bit state
    function [63:0] get_lane;
        input [1599:0] st;
        input integer x;
        input integer y;
        begin
            get_lane = st[64*(5*y+x) +: 64];
        end
    endfunction

    initial begin
        $dumpfile("dump.vcd");
        $dumpvars(0, keccak_round_tb);

        errors = 0;

        // Initialize round constants (FIPS 202)
        RC[0]  = 64'h0000000000000001; RC[1]  = 64'h0000000000008082;
        RC[2]  = 64'h800000000000808A; RC[3]  = 64'h8000000080008000;
        RC[4]  = 64'h000000000000808B; RC[5]  = 64'h0000000080000001;
        RC[6]  = 64'h8000000080008081; RC[7]  = 64'h8000000000008009;
        RC[8]  = 64'h000000000000008A; RC[9]  = 64'h0000000000000088;
        RC[10] = 64'h0000000080008009; RC[11] = 64'h000000008000000A;
        RC[12] = 64'h000000008000808B; RC[13] = 64'h800000000000008B;
        RC[14] = 64'h8000000000008089; RC[15] = 64'h8000000000008003;
        RC[16] = 64'h8000000000008002; RC[17] = 64'h8000000000000080;
        RC[18] = 64'h000000000000800A; RC[19] = 64'h800000008000000A;
        RC[20] = 64'h8000000080008081; RC[21] = 64'h8000000000008080;
        RC[22] = 64'h0000000080000001; RC[23] = 64'h8000000080008008;

        $display("=== Keccak Round Test ===");

        // Test 1: All-zero state, round 0
        // For the all-zero input:
        //   theta: C[x] = 0, D[x] = 0, so state unchanged after theta
        //   rho/pi: all zeros stay zero
        //   chi: A[x,y] = 0 ^ (~0 & 0) = 0 (since ~0=all-ones, &0=0)
        //   Actually: chi(0,0,0,0,0) for each row:
        //     each bit: b ^ (~b1 & b2) where all are 0
        //     = 0 ^ (1 & 0) = 0
        //   So all-zero state stays all-zero except for iota: lane[0][0] ^= RC
        state_in = 1600'b0;
        round_constant = RC[0];
        #10;

        // After round 0 on all-zero state, only lane[0][0] should be RC[0]
        if (get_lane(state_out, 0, 0) !== RC[0]) begin
            $display("FAIL: Lane[0][0] = %016h, expected %016h",
                     get_lane(state_out, 0, 0), RC[0]);
            errors = errors + 1;
        end else begin
            $display("  OK: Round 0 on zero state, lane[0][0] = %016h", RC[0]);
        end

        // All other lanes should be zero
        for (i = 1; i < 25; i = i + 1) begin
            if (get_lane(state_out, i % 5, i / 5) !== 64'h0) begin
                $display("FAIL: Lane[%0d][%0d] = %016h, expected 0",
                         i % 5, i / 5,
                         get_lane(state_out, i % 5, i / 5));
                errors = errors + 1;
            end
        end
        if (errors == 0)
            $display("  OK: All other lanes are zero");

        // Test 2: Apply round 0 result as input to round 1
        state_in = state_out;
        round_constant = RC[1];
        #10;

        // The output should be non-trivial now
        $display("  Round 1 output lane[0][0] = %016h", get_lane(state_out, 0, 0));
        $display("  Round 1 output lane[1][0] = %016h", get_lane(state_out, 1, 0));

        // Basic sanity: output should not be all zeros after two rounds
        if (state_out === 1600'b0) begin
            $display("FAIL: State is all zeros after round 1 (should not be)");
            errors = errors + 1;
        end else begin
            $display("  OK: State is non-zero after round 1");
        end

        // Test 3: Verify that round function changes the state
        state_in = state_out;
        round_constant = RC[2];
        #10;

        if (state_out === state_in) begin
            $display("FAIL: Round 2 did not change the state");
            errors = errors + 1;
        end else begin
            $display("  OK: Round 2 produced different output");
        end

        $display("");
        if (errors == 0)
            $display("PASS: All Keccak round tests passed.");
        else
            $display("FAIL: %0d error(s) detected.", errors);

        $finish;
    end

endmodule

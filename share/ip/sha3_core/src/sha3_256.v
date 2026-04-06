`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////
// OpenForge EDA - SHA3-256 Hash Core (Keccak-f[1600])
//
// Features:
//   - Full SHA3-256 (FIPS 202) with Keccak-f[1600] permutation
//   - 24-round permutation, iterative (1 round/cycle = 24 cycles per block)
//   - Absorb phase: 1088-bit rate (r=1088 for SHA3-256)
//   - Squeeze phase: 256-bit hash output
//   - Valid/ready handshake interface for streaming input
//
// Ports:
//   clk, rst_n       - Clock and active-low reset
//   msg_data[63:0]   - Message input (64-bit words)
//   msg_valid         - Input data valid
//   msg_ready         - Core ready to accept data
//   msg_last          - Last word of message
//   hash_data[255:0]  - Hash output
//   hash_valid        - Hash output valid
//   hash_ready        - Downstream ready for hash
//
// Usage:
//   Feed 64-bit message words with msg_valid/msg_ready handshake.
//   Assert msg_last on the final word. Padding (10*1) is handled internally.
//   After permutation completes, hash_data is valid for one handshake.
//
// Copyright (c) 2024-2026 OpenForge Contributors
// SPDX-License-Identifier: Apache-2.0
//////////////////////////////////////////////////////////////////////////////

module sha3_256 (
    input  wire         clk,
    input  wire         rst_n,

    // Message input interface (64-bit words, valid/ready)
    input  wire [63:0]  msg_data,
    input  wire         msg_valid,
    output reg          msg_ready,
    input  wire         msg_last,

    // Hash output interface
    output reg  [255:0] hash_data,
    output reg          hash_valid,
    input  wire         hash_ready
);

    // =========================================================================
    // Keccak state: 5x5 array of 64-bit lanes = 1600 bits
    // Indexed as state[x][y] where x,y in [0..4]
    // Flattened: state_flat[lane_index*64 +: 64], lane_index = x*5 + y
    // =========================================================================
    reg [63:0] state [0:4][0:4];

    // Rate for SHA3-256: r = 1088 bits = 17 x 64-bit lanes
    localparam RATE_LANES = 17;

    // FSM states
    localparam S_IDLE     = 3'd0;
    localparam S_ABSORB   = 3'd1;
    localparam S_PAD      = 3'd2;
    localparam S_PERMUTE  = 3'd3;
    localparam S_SQUEEZE  = 3'd4;

    reg [2:0]  fsm_state;
    reg [4:0]  round_cnt;      // 0..23 for Keccak-f rounds
    reg [4:0]  lane_cnt;       // Counts absorbed lanes within a block
    reg        pad_pending;    // Need to process padding block

    // =========================================================================
    // Keccak-f[1600] round constants
    // =========================================================================
    function [63:0] rc;
        input [4:0] rnd;
        begin
            case (rnd)
                5'd0:  rc = 64'h0000000000000001;
                5'd1:  rc = 64'h0000000000008082;
                5'd2:  rc = 64'h800000000000808A;
                5'd3:  rc = 64'h8000000080008000;
                5'd4:  rc = 64'h000000000000808B;
                5'd5:  rc = 64'h0000000080000001;
                5'd6:  rc = 64'h8000000080008081;
                5'd7:  rc = 64'h8000000000008009;
                5'd8:  rc = 64'h000000000000008A;
                5'd9:  rc = 64'h0000000000000088;
                5'd10: rc = 64'h0000000080008009;
                5'd11: rc = 64'h000000008000000A;
                5'd12: rc = 64'h000000008000808B;
                5'd13: rc = 64'h800000000000008B;
                5'd14: rc = 64'h8000000000008089;
                5'd15: rc = 64'h8000000000008003;
                5'd16: rc = 64'h8000000000008002;
                5'd17: rc = 64'h8000000000000080;
                5'd18: rc = 64'h000000000000800A;
                5'd19: rc = 64'h800000008000000A;
                5'd20: rc = 64'h8000000080008081;
                5'd21: rc = 64'h8000000000008080;
                5'd22: rc = 64'h0000000080000001;
                5'd23: rc = 64'h8000000080008008;
                default: rc = 64'h0;
            endcase
        end
    endfunction

    // =========================================================================
    // Rotation offsets for rho step
    // rot_offset[x][y]
    // =========================================================================
    function [5:0] rot_offset;
        input [2:0] x;
        input [2:0] y;
        begin
            case ({x[1:0], y[1:0]})
                4'b00_00: rot_offset = 6'd0;   // (0,0)
                4'b00_01: rot_offset = 6'd36;  // (0,1)
                4'b00_10: rot_offset = 6'd3;   // (0,2)
                4'b00_11: rot_offset = 6'd41;  // (0,3)
                4'b01_00: rot_offset = 6'd1;   // (1,0)
                4'b01_01: rot_offset = 6'd44;  // (1,1)
                4'b01_10: rot_offset = 6'd10;  // (1,2)
                4'b01_11: rot_offset = 6'd45;  // (1,3)
                4'b10_00: rot_offset = 6'd62;  // (2,0)
                4'b10_01: rot_offset = 6'd6;   // (2,1)
                4'b10_10: rot_offset = 6'd43;  // (2,2)
                4'b10_11: rot_offset = 6'd15;  // (2,3)
                4'b11_00: rot_offset = 6'd28;  // (3,0)
                4'b11_01: rot_offset = 6'd55;  // (3,1)
                4'b11_10: rot_offset = 6'd25;  // (3,2)
                4'b11_11: rot_offset = 6'd21;  // (3,3)
                default:  rot_offset = 6'd0;
            endcase
            // Handle x=4 or y=4
            if (x == 3'd4 && y == 3'd0) rot_offset = 6'd18;
            if (x == 3'd4 && y == 3'd1) rot_offset = 6'd2;
            if (x == 3'd4 && y == 3'd2) rot_offset = 6'd61;
            if (x == 3'd4 && y == 3'd3) rot_offset = 6'd56;
            if (x == 3'd4 && y == 3'd4) rot_offset = 6'd14;
            if (x == 3'd0 && y == 3'd4) rot_offset = 6'd18;  // overloaded, use proper
            if (x == 3'd1 && y == 3'd4) rot_offset = 6'd2;
            if (x == 3'd2 && y == 3'd4) rot_offset = 6'd61;
            if (x == 3'd3 && y == 3'd4) rot_offset = 6'd56;
            // Correction: use full lookup
            case ({x[2:0], y[2:0]})
                6'b000_000: rot_offset = 6'd0;
                6'b000_001: rot_offset = 6'd36;
                6'b000_010: rot_offset = 6'd3;
                6'b000_011: rot_offset = 6'd41;
                6'b000_100: rot_offset = 6'd18;
                6'b001_000: rot_offset = 6'd1;
                6'b001_001: rot_offset = 6'd44;
                6'b001_010: rot_offset = 6'd10;
                6'b001_011: rot_offset = 6'd45;
                6'b001_100: rot_offset = 6'd2;
                6'b010_000: rot_offset = 6'd62;
                6'b010_001: rot_offset = 6'd6;
                6'b010_010: rot_offset = 6'd43;
                6'b010_011: rot_offset = 6'd15;
                6'b010_100: rot_offset = 6'd61;
                6'b011_000: rot_offset = 6'd28;
                6'b011_001: rot_offset = 6'd55;
                6'b011_010: rot_offset = 6'd25;
                6'b011_011: rot_offset = 6'd21;
                6'b011_100: rot_offset = 6'd56;
                6'b100_000: rot_offset = 6'd27;
                6'b100_001: rot_offset = 6'd20;
                6'b100_010: rot_offset = 6'd39;
                6'b100_011: rot_offset = 6'd8;
                6'b100_100: rot_offset = 6'd14;
                default:    rot_offset = 6'd0;
            endcase
        end
    endfunction

    // Rotate left by n for 64-bit value
    function [63:0] rotl64;
        input [63:0] val;
        input [5:0]  n;
        begin
            rotl64 = (val << n) | (val >> (6'd64 - n));
        end
    endfunction

    // =========================================================================
    // Lane indexing helpers for absorb
    // Lane ordering: (0,0),(1,0),(2,0),(3,0),(4,0),(0,1),(1,1),...
    // lane_cnt maps to (x,y) = (lane_cnt % 5, lane_cnt / 5)
    // =========================================================================
    wire [2:0] absorb_x = lane_cnt % 5;
    wire [2:0] absorb_y = lane_cnt / 5;

    // =========================================================================
    // Keccak-f[1600] round computation (combinational)
    // =========================================================================
    // Intermediate values for one round
    reg [63:0] st_theta  [0:4][0:4];
    reg [63:0] st_rho_pi [0:4][0:4];
    reg [63:0] st_chi    [0:4][0:4];
    reg [63:0] c_col     [0:4]; // Column parities for theta
    reg [63:0] d_col     [0:4]; // Theta offsets

    integer xi, yi;

    always @(*) begin
        // --- Theta ---
        for (xi = 0; xi < 5; xi = xi + 1)
            c_col[xi] = state[xi][0] ^ state[xi][1] ^ state[xi][2]
                       ^ state[xi][3] ^ state[xi][4];

        for (xi = 0; xi < 5; xi = xi + 1)
            d_col[xi] = c_col[(xi + 4) % 5] ^ rotl64(c_col[(xi + 1) % 5], 6'd1);

        for (xi = 0; xi < 5; xi = xi + 1)
            for (yi = 0; yi < 5; yi = yi + 1)
                st_theta[xi][yi] = state[xi][yi] ^ d_col[xi];

        // --- Rho + Pi (combined) ---
        // Pi: A'[y][2x+3y mod 5] = A[x][y], then rho rotates
        for (xi = 0; xi < 5; xi = xi + 1)
            for (yi = 0; yi < 5; yi = yi + 1)
                st_rho_pi[yi][(2*xi + 3*yi) % 5] =
                    rotl64(st_theta[xi][yi], rot_offset(xi[2:0], yi[2:0]));

        // --- Chi ---
        for (xi = 0; xi < 5; xi = xi + 1)
            for (yi = 0; yi < 5; yi = yi + 1)
                st_chi[xi][yi] = st_rho_pi[xi][yi]
                    ^ (~st_rho_pi[(xi+1) % 5][yi] & st_rho_pi[(xi+2) % 5][yi]);
    end

    // =========================================================================
    // Main FSM
    // =========================================================================
    integer ix, iy;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fsm_state   <= S_IDLE;
            round_cnt   <= 5'd0;
            lane_cnt    <= 5'd0;
            pad_pending <= 1'b0;
            msg_ready   <= 1'b0;
            hash_valid  <= 1'b0;
            hash_data   <= 256'd0;
            for (ix = 0; ix < 5; ix = ix + 1)
                for (iy = 0; iy < 5; iy = iy + 1)
                    state[ix][iy] <= 64'd0;
        end else begin
            case (fsm_state)

                S_IDLE: begin
                    hash_valid <= 1'b0;
                    lane_cnt   <= 5'd0;
                    round_cnt  <= 5'd0;
                    // Zero state for new hash
                    for (ix = 0; ix < 5; ix = ix + 1)
                        for (iy = 0; iy < 5; iy = iy + 1)
                            state[ix][iy] <= 64'd0;
                    msg_ready  <= 1'b1;
                    fsm_state  <= S_ABSORB;
                end

                S_ABSORB: begin
                    if (msg_valid && msg_ready) begin
                        // XOR incoming lane into state
                        state[absorb_x][absorb_y] <=
                            state[absorb_x][absorb_y] ^ msg_data;

                        if (msg_last) begin
                            // Apply SHA3 domain separation + padding
                            // Pad byte: 0x06 for SHA3 (domain sep), then 10*1 pad
                            msg_ready   <= 1'b0;
                            pad_pending <= 1'b1;
                            lane_cnt    <= lane_cnt + 5'd1;
                            fsm_state   <= S_PAD;
                        end else if (lane_cnt == RATE_LANES - 1) begin
                            // Rate block full, run permutation
                            msg_ready <= 1'b0;
                            lane_cnt  <= 5'd0;
                            round_cnt <= 5'd0;
                            fsm_state <= S_PERMUTE;
                        end else begin
                            lane_cnt <= lane_cnt + 5'd1;
                        end
                    end
                end

                S_PAD: begin
                    // XOR padding into next lane if needed
                    // SHA3-256 pad: append 0x06 byte, then 0x80 at end of rate
                    // For simplicity: XOR 0x06 at current byte position,
                    // XOR 0x80 into MSB of last rate lane
                    if (pad_pending) begin
                        // XOR 0x06 into the lane after last data
                        if (lane_cnt < RATE_LANES) begin
                            state[lane_cnt % 5][lane_cnt / 5] <=
                                state[lane_cnt % 5][lane_cnt / 5] ^ 64'h0000000000000006;
                        end
                        // XOR 0x80 into byte 7 of last rate lane (lane index 16)
                        state[(RATE_LANES-1) % 5][(RATE_LANES-1) / 5] <=
                            state[(RATE_LANES-1) % 5][(RATE_LANES-1) / 5] ^ 64'h8000000000000000;
                        pad_pending <= 1'b0;
                        round_cnt   <= 5'd0;
                        fsm_state   <= S_PERMUTE;
                    end
                end

                S_PERMUTE: begin
                    // Apply one round of Keccak-f per cycle
                    // Iota step: XOR round constant into (0,0)
                    for (ix = 0; ix < 5; ix = ix + 1)
                        for (iy = 0; iy < 5; iy = iy + 1)
                            state[ix][iy] <= st_chi[ix][iy];
                    state[0][0] <= st_chi[0][0] ^ rc(round_cnt);

                    if (round_cnt == 5'd23) begin
                        // Permutation complete
                        if (!pad_pending && hash_valid == 1'b0) begin
                            // Check if we came from absorb (more data) or pad (squeeze)
                            // If lane_cnt was 0 we came from a full absorb block
                            // If lane_cnt != 0 we came from padding
                            if (lane_cnt != 5'd0) begin
                                // Came from padding -> squeeze
                                fsm_state <= S_SQUEEZE;
                            end else begin
                                // Came from full block -> continue absorbing
                                msg_ready <= 1'b1;
                                fsm_state <= S_ABSORB;
                            end
                        end else begin
                            msg_ready <= 1'b1;
                            fsm_state <= S_ABSORB;
                        end
                    end else begin
                        round_cnt <= round_cnt + 5'd1;
                    end
                end

                S_SQUEEZE: begin
                    // Extract first 256 bits = 4 lanes: (0,0),(1,0),(2,0),(3,0)
                    hash_data <= {state[3][0], state[2][0], state[1][0], state[0][0]};
                    hash_valid <= 1'b1;
                    if (hash_valid && hash_ready) begin
                        hash_valid <= 1'b0;
                        fsm_state  <= S_IDLE;
                    end
                end

                default: fsm_state <= S_IDLE;
            endcase
        end
    end

endmodule

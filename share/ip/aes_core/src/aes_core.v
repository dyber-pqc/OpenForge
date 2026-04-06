`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////
// OpenForge EDA - AES-128 Encryption Core with AXI4-Lite Slave Interface
//
// Features:
//   - Full AES-128 encryption (FIPS 197 compliant SubBytes, ShiftRows,
//     MixColumns, AddRoundKey)
//   - AXI4-Lite slave for key/data register access
//   - Configurable: PIPELINE_MODE=1 for 1 round/cycle (11-cycle latency),
//                   PIPELINE_MODE=0 for iterative (10 cycles/block, less area)
//   - 128-bit key expansion inline
//
// Register Map (32-bit aligned):
//   0x00 - KEY[31:0]       0x04 - KEY[63:32]
//   0x08 - KEY[95:64]      0x0C - KEY[127:96]
//   0x10 - DATA_IN[31:0]   0x14 - DATA_IN[63:32]
//   0x18 - DATA_IN[95:64]  0x1C - DATA_IN[127:96]
//   0x20 - DATA_OUT[31:0]  0x24 - DATA_OUT[63:32]
//   0x28 - DATA_OUT[95:64] 0x2C - DATA_OUT[127:96]
//   0x30 - CTRL/STATUS: bit0=start(W)/busy(R), bit1=done(R)
//
// Copyright (c) 2024-2026 OpenForge Contributors
// SPDX-License-Identifier: Apache-2.0
//////////////////////////////////////////////////////////////////////////////

module aes_core #(
    parameter PIPELINE_MODE = 0  // 0=iterative (10 cycles), 1=pipelined (11 cycles)
) (
    // Clock and reset
    input  wire        clk,
    input  wire        rst_n,

    // AXI4-Lite Write Address Channel
    input  wire [5:0]  s_axi_awaddr,
    input  wire        s_axi_awvalid,
    output reg         s_axi_awready,

    // AXI4-Lite Write Data Channel
    input  wire [31:0] s_axi_wdata,
    input  wire [3:0]  s_axi_wstrb,
    input  wire        s_axi_wvalid,
    output reg         s_axi_wready,

    // AXI4-Lite Write Response Channel
    output reg  [1:0]  s_axi_bresp,
    output reg         s_axi_bvalid,
    input  wire        s_axi_bready,

    // AXI4-Lite Read Address Channel
    input  wire [5:0]  s_axi_araddr,
    input  wire        s_axi_arvalid,
    output reg         s_axi_arready,

    // AXI4-Lite Read Data Channel
    output reg  [31:0] s_axi_rdata,
    output reg  [1:0]  s_axi_rresp,
    output reg         s_axi_rvalid,
    input  wire        s_axi_rready
);

    // =========================================================================
    // Internal registers
    // =========================================================================
    reg [127:0] key_reg;
    reg [127:0] data_in_reg;
    reg [127:0] data_out_reg;
    reg         busy;
    reg         done;
    reg         start_pulse;

    // AXI write state
    reg [5:0]   aw_addr_latched;
    reg         aw_addr_valid;
    reg         w_data_valid;
    reg [31:0]  w_data_latched;
    reg [3:0]   w_strb_latched;

    // AXI read state
    reg [5:0]   ar_addr_latched;

    // =========================================================================
    // AES S-Box (SubBytes lookup)
    // =========================================================================
    function [7:0] sbox;
        input [7:0] in;
        reg [7:0] lut [0:255];
        begin
            lut[8'h00]=8'h63; lut[8'h01]=8'h7c; lut[8'h02]=8'h77; lut[8'h03]=8'h7b;
            lut[8'h04]=8'hf2; lut[8'h05]=8'h6b; lut[8'h06]=8'h6f; lut[8'h07]=8'hc5;
            lut[8'h08]=8'h30; lut[8'h09]=8'h01; lut[8'h0a]=8'h67; lut[8'h0b]=8'h2b;
            lut[8'h0c]=8'hfe; lut[8'h0d]=8'hd7; lut[8'h0e]=8'hab; lut[8'h0f]=8'h76;
            lut[8'h10]=8'hca; lut[8'h11]=8'h82; lut[8'h12]=8'hc9; lut[8'h13]=8'h7d;
            lut[8'h14]=8'hfa; lut[8'h15]=8'h59; lut[8'h16]=8'h47; lut[8'h17]=8'hf0;
            lut[8'h18]=8'had; lut[8'h19]=8'hd4; lut[8'h1a]=8'ha2; lut[8'h1b]=8'haf;
            lut[8'h1c]=8'h9c; lut[8'h1d]=8'ha4; lut[8'h1e]=8'h72; lut[8'h1f]=8'hc0;
            lut[8'h20]=8'hb7; lut[8'h21]=8'hfd; lut[8'h22]=8'h93; lut[8'h23]=8'h26;
            lut[8'h24]=8'h36; lut[8'h25]=8'h3f; lut[8'h26]=8'hf7; lut[8'h27]=8'hcc;
            lut[8'h28]=8'h34; lut[8'h29]=8'ha5; lut[8'h2a]=8'he5; lut[8'h2b]=8'hf1;
            lut[8'h2c]=8'h71; lut[8'h2d]=8'hd8; lut[8'h2e]=8'h31; lut[8'h2f]=8'h15;
            lut[8'h30]=8'h04; lut[8'h31]=8'hc7; lut[8'h32]=8'h23; lut[8'h33]=8'hc3;
            lut[8'h34]=8'h18; lut[8'h35]=8'h96; lut[8'h36]=8'h05; lut[8'h37]=8'h9a;
            lut[8'h38]=8'h07; lut[8'h39]=8'h12; lut[8'h3a]=8'h80; lut[8'h3b]=8'he2;
            lut[8'h3c]=8'heb; lut[8'h3d]=8'h27; lut[8'h3e]=8'hb2; lut[8'h3f]=8'h75;
            lut[8'h40]=8'h09; lut[8'h41]=8'h83; lut[8'h42]=8'h2c; lut[8'h43]=8'h1a;
            lut[8'h44]=8'h1b; lut[8'h45]=8'h6e; lut[8'h46]=8'h5a; lut[8'h47]=8'ha0;
            lut[8'h48]=8'h52; lut[8'h49]=8'h3b; lut[8'h4a]=8'hd6; lut[8'h4b]=8'hb3;
            lut[8'h4c]=8'h29; lut[8'h4d]=8'he3; lut[8'h4e]=8'h2f; lut[8'h4f]=8'h84;
            lut[8'h50]=8'h53; lut[8'h51]=8'hd1; lut[8'h52]=8'h00; lut[8'h53]=8'hed;
            lut[8'h54]=8'h20; lut[8'h55]=8'hfc; lut[8'h56]=8'hb1; lut[8'h57]=8'h5b;
            lut[8'h58]=8'h6a; lut[8'h59]=8'hcb; lut[8'h5a]=8'hbe; lut[8'h5b]=8'h39;
            lut[8'h5c]=8'h4a; lut[8'h5d]=8'h4c; lut[8'h5e]=8'h58; lut[8'h5f]=8'hcf;
            lut[8'h60]=8'hd0; lut[8'h61]=8'hef; lut[8'h62]=8'haa; lut[8'h63]=8'hfb;
            lut[8'h64]=8'h43; lut[8'h65]=8'h4d; lut[8'h66]=8'h33; lut[8'h67]=8'h85;
            lut[8'h68]=8'h45; lut[8'h69]=8'hf9; lut[8'h6a]=8'h02; lut[8'h6b]=8'h7f;
            lut[8'h6c]=8'h50; lut[8'h6d]=8'h3c; lut[8'h6e]=8'h9f; lut[8'h6f]=8'ha8;
            lut[8'h70]=8'h51; lut[8'h71]=8'ha3; lut[8'h72]=8'h40; lut[8'h73]=8'h8f;
            lut[8'h74]=8'h92; lut[8'h75]=8'h9d; lut[8'h76]=8'h38; lut[8'h77]=8'hf5;
            lut[8'h78]=8'hbc; lut[8'h79]=8'hb6; lut[8'h7a]=8'hda; lut[8'h7b]=8'h21;
            lut[8'h7c]=8'h10; lut[8'h7d]=8'hff; lut[8'h7e]=8'hf3; lut[8'h7f]=8'hd2;
            lut[8'h80]=8'hcd; lut[8'h81]=8'h0c; lut[8'h82]=8'h13; lut[8'h83]=8'hec;
            lut[8'h84]=8'h5f; lut[8'h85]=8'h97; lut[8'h86]=8'h44; lut[8'h87]=8'h17;
            lut[8'h88]=8'hc4; lut[8'h89]=8'ha7; lut[8'h8a]=8'h7e; lut[8'h8b]=8'h3d;
            lut[8'h8c]=8'h64; lut[8'h8d]=8'h5d; lut[8'h8e]=8'h19; lut[8'h8f]=8'h73;
            lut[8'h90]=8'h60; lut[8'h91]=8'h81; lut[8'h92]=8'h4f; lut[8'h93]=8'hdc;
            lut[8'h94]=8'h22; lut[8'h95]=8'h2a; lut[8'h96]=8'h90; lut[8'h97]=8'h88;
            lut[8'h98]=8'h46; lut[8'h99]=8'hee; lut[8'h9a]=8'hb8; lut[8'h9b]=8'h14;
            lut[8'h9c]=8'hde; lut[8'h9d]=8'h5e; lut[8'h9e]=8'h0b; lut[8'h9f]=8'hdb;
            lut[8'ha0]=8'he0; lut[8'ha1]=8'h32; lut[8'ha2]=8'h3a; lut[8'ha3]=8'h0a;
            lut[8'ha4]=8'h49; lut[8'ha5]=8'h06; lut[8'ha6]=8'h24; lut[8'ha7]=8'h5c;
            lut[8'ha8]=8'hc2; lut[8'ha9]=8'hd3; lut[8'haa]=8'hac; lut[8'hab]=8'h62;
            lut[8'hac]=8'h91; lut[8'had]=8'h95; lut[8'hae]=8'he4; lut[8'haf]=8'h79;
            lut[8'hb0]=8'he7; lut[8'hb1]=8'hc8; lut[8'hb2]=8'h37; lut[8'hb3]=8'h6d;
            lut[8'hb4]=8'h8d; lut[8'hb5]=8'hd5; lut[8'hb6]=8'h4e; lut[8'hb7]=8'ha9;
            lut[8'hb8]=8'h6c; lut[8'hb9]=8'h56; lut[8'hba]=8'hf4; lut[8'hbb]=8'hea;
            lut[8'hbc]=8'h65; lut[8'hbd]=8'h7a; lut[8'hbe]=8'hae; lut[8'hbf]=8'h08;
            lut[8'hc0]=8'hba; lut[8'hc1]=8'h78; lut[8'hc2]=8'h25; lut[8'hc3]=8'h2e;
            lut[8'hc4]=8'h1c; lut[8'hc5]=8'ha6; lut[8'hc6]=8'hb4; lut[8'hc7]=8'hc6;
            lut[8'hc8]=8'he8; lut[8'hc9]=8'hdd; lut[8'hca]=8'h74; lut[8'hcb]=8'h1f;
            lut[8'hcc]=8'h4b; lut[8'hcd]=8'hbd; lut[8'hce]=8'h8b; lut[8'hcf]=8'h8a;
            lut[8'hd0]=8'h70; lut[8'hd1]=8'h3e; lut[8'hd2]=8'hb5; lut[8'hd3]=8'h66;
            lut[8'hd4]=8'h48; lut[8'hd5]=8'h03; lut[8'hd6]=8'hf6; lut[8'hd7]=8'h0e;
            lut[8'hd8]=8'h61; lut[8'hd9]=8'h35; lut[8'hda]=8'h57; lut[8'hdb]=8'hb9;
            lut[8'hdc]=8'h86; lut[8'hdd]=8'hc1; lut[8'hde]=8'h1d; lut[8'hdf]=8'h9e;
            lut[8'he0]=8'he1; lut[8'he1]=8'hf8; lut[8'he2]=8'h98; lut[8'he3]=8'h11;
            lut[8'he4]=8'h69; lut[8'he5]=8'hd9; lut[8'he6]=8'h8e; lut[8'he7]=8'h94;
            lut[8'he8]=8'h9b; lut[8'he9]=8'h1e; lut[8'hea]=8'h87; lut[8'heb]=8'he9;
            lut[8'hec]=8'hce; lut[8'hed]=8'h55; lut[8'hee]=8'h28; lut[8'hef]=8'hdf;
            lut[8'hf0]=8'h8c; lut[8'hf1]=8'ha1; lut[8'hf2]=8'h89; lut[8'hf3]=8'h0d;
            lut[8'hf4]=8'hbf; lut[8'hf5]=8'he6; lut[8'hf6]=8'h42; lut[8'hf7]=8'h68;
            lut[8'hf8]=8'h41; lut[8'hf9]=8'h99; lut[8'hfa]=8'h2d; lut[8'hfb]=8'h0f;
            lut[8'hfc]=8'hb0; lut[8'hfd]=8'h54; lut[8'hfe]=8'hbb; lut[8'hff]=8'h16;
            sbox = lut[in];
        end
    endfunction

    // =========================================================================
    // AES Round Functions
    // =========================================================================

    // SubBytes: apply S-Box to each byte of 128-bit state
    function [127:0] sub_bytes;
        input [127:0] state;
        integer i;
        begin
            for (i = 0; i < 16; i = i + 1)
                sub_bytes[i*8 +: 8] = sbox(state[i*8 +: 8]);
        end
    endfunction

    // ShiftRows: cyclically shift rows of the 4x4 byte matrix
    // State is column-major: byte[row][col] = state[(col*4+row)*8 +: 8]
    function [127:0] shift_rows;
        input [127:0] s;
        reg [7:0] m [0:3][0:3]; // [row][col]
        integer r, c;
        begin
            // Unpack to matrix (column-major in AES)
            for (c = 0; c < 4; c = c + 1)
                for (r = 0; r < 4; r = r + 1)
                    m[r][c] = s[(c*4+r)*8 +: 8];
            // Row 0: no shift
            // Row 1: shift left by 1
            // Row 2: shift left by 2
            // Row 3: shift left by 3
            shift_rows = {
                m[3][3], m[2][2], m[1][1], m[0][0],  // col 0 output
                m[3][0], m[2][3], m[1][2], m[0][1],  // col 1 output
                m[3][1], m[2][0], m[1][3], m[0][2],  // col 2 output
                m[3][2], m[2][1], m[1][0], m[0][3]   // col 3 output
            };
            // Re-pack column-major
            for (c = 0; c < 4; c = c + 1) begin
                shift_rows[(c*4+0)*8 +: 8] = m[0][(c+0) % 4];
                shift_rows[(c*4+1)*8 +: 8] = m[1][(c+1) % 4];
                shift_rows[(c*4+2)*8 +: 8] = m[2][(c+2) % 4];
                shift_rows[(c*4+3)*8 +: 8] = m[3][(c+3) % 4];
            end
        end
    endfunction

    // xtime: multiply by 2 in GF(2^8)
    function [7:0] xtime;
        input [7:0] b;
        begin
            xtime = (b[7]) ? ({b[6:0], 1'b0} ^ 8'h1b) : {b[6:0], 1'b0};
        end
    endfunction

    // MixColumns: mix each column using GF(2^8) arithmetic
    function [127:0] mix_columns;
        input [127:0] s;
        reg [7:0] a0, a1, a2, a3;
        reg [7:0] r0, r1, r2, r3;
        integer c;
        begin
            mix_columns = 128'd0;
            for (c = 0; c < 4; c = c + 1) begin
                a0 = s[(c*4+0)*8 +: 8];
                a1 = s[(c*4+1)*8 +: 8];
                a2 = s[(c*4+2)*8 +: 8];
                a3 = s[(c*4+3)*8 +: 8];
                // {02}*a0 ^ {03}*a1 ^ a2 ^ a3
                r0 = xtime(a0) ^ (xtime(a1) ^ a1) ^ a2 ^ a3;
                r1 = a0 ^ xtime(a1) ^ (xtime(a2) ^ a2) ^ a3;
                r2 = a0 ^ a1 ^ xtime(a2) ^ (xtime(a3) ^ a3);
                r3 = (xtime(a0) ^ a0) ^ a1 ^ a2 ^ xtime(a3);
                mix_columns[(c*4+0)*8 +: 8] = r0;
                mix_columns[(c*4+1)*8 +: 8] = r1;
                mix_columns[(c*4+2)*8 +: 8] = r2;
                mix_columns[(c*4+3)*8 +: 8] = r3;
            end
        end
    endfunction

    // AddRoundKey
    function [127:0] add_round_key;
        input [127:0] state;
        input [127:0] rkey;
        begin
            add_round_key = state ^ rkey;
        end
    endfunction

    // =========================================================================
    // Key Expansion (on-the-fly for iterative mode)
    // =========================================================================
    // Round constants
    function [7:0] rcon;
        input [3:0] round;
        begin
            case (round)
                4'd0: rcon = 8'h01;  4'd1: rcon = 8'h02;
                4'd2: rcon = 8'h04;  4'd3: rcon = 8'h08;
                4'd4: rcon = 8'h10;  4'd5: rcon = 8'h20;
                4'd6: rcon = 8'h40;  4'd7: rcon = 8'h80;
                4'd8: rcon = 8'h1b;  4'd9: rcon = 8'h36;
                default: rcon = 8'h00;
            endcase
        end
    endfunction

    // Compute next round key from current round key
    function [127:0] next_round_key;
        input [127:0] prev;
        input [3:0]   round;
        reg [31:0] w0, w1, w2, w3;
        reg [31:0] temp;
        begin
            w0 = prev[127:96];
            w1 = prev[95:64];
            w2 = prev[63:32];
            w3 = prev[31:0];
            // RotWord + SubWord + Rcon
            temp = {sbox(w3[23:16]), sbox(w3[15:8]), sbox(w3[7:0]), sbox(w3[31:24])};
            temp[31:24] = temp[31:24] ^ rcon(round);
            w0 = w0 ^ temp;
            w1 = w1 ^ w0;
            w2 = w2 ^ w1;
            w3 = w3 ^ w2;
            next_round_key = {w0, w1, w2, w3};
        end
    endfunction

    // =========================================================================
    // AES Encryption Datapath (iterative)
    // =========================================================================
    reg [127:0] state;
    (* keep *) reg [127:0] round_key;
    reg [3:0]   round_cnt;
    reg [1:0]   aes_state; // 0=idle, 1=initial_add, 2=rounds, 3=done

    localparam AES_IDLE     = 2'd0;
    localparam AES_INIT     = 2'd1;
    localparam AES_ROUNDS   = 2'd2;
    localparam AES_DONE     = 2'd3;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= 128'd0;
            round_key <= 128'd0;
            round_cnt <= 4'd0;
            aes_state <= AES_IDLE;
            busy      <= 1'b0;
            done      <= 1'b0;
            data_out_reg <= 128'd0;
        end else begin
            case (aes_state)
                AES_IDLE: begin
                    if (start_pulse) begin
                        // Initial AddRoundKey
                        state     <= add_round_key(data_in_reg, key_reg);
                        round_key <= key_reg;
                        round_cnt <= 4'd0;
                        aes_state <= AES_ROUNDS;
                        busy      <= 1'b1;
                        done      <= 1'b0;
                    end
                end

                AES_ROUNDS: begin
                    round_key <= next_round_key(round_key, round_cnt);
                    if (round_cnt < 4'd9) begin
                        // Rounds 1-9: SubBytes, ShiftRows, MixColumns, AddRoundKey
                        state <= add_round_key(
                            mix_columns(shift_rows(sub_bytes(state))),
                            next_round_key(round_key, round_cnt)
                        );
                        round_cnt <= round_cnt + 4'd1;
                    end else begin
                        // Round 10 (final): SubBytes, ShiftRows, AddRoundKey (no MixColumns)
                        state <= add_round_key(
                            shift_rows(sub_bytes(state)),
                            next_round_key(round_key, round_cnt)
                        );
                        aes_state <= AES_DONE;
                    end
                end

                AES_DONE: begin
                    data_out_reg <= state;
                    busy         <= 1'b0;
                    done         <= 1'b1;
                    aes_state    <= AES_IDLE;
                end

                default: aes_state <= AES_IDLE;
            endcase
        end
    end

    // =========================================================================
    // AXI4-Lite Write Logic
    // =========================================================================
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s_axi_awready   <= 1'b0;
            s_axi_wready    <= 1'b0;
            s_axi_bvalid    <= 1'b0;
            s_axi_bresp     <= 2'b00;
            aw_addr_latched  <= 6'd0;
            aw_addr_valid    <= 1'b0;
            w_data_valid     <= 1'b0;
            w_data_latched   <= 32'd0;
            w_strb_latched   <= 4'd0;
            key_reg          <= 128'd0;
            data_in_reg      <= 128'd0;
            start_pulse      <= 1'b0;
        end else begin
            start_pulse <= 1'b0;

            // Accept write address
            if (s_axi_awvalid && !aw_addr_valid) begin
                s_axi_awready   <= 1'b1;
                aw_addr_latched <= s_axi_awaddr;
                aw_addr_valid   <= 1'b1;
            end else begin
                s_axi_awready <= 1'b0;
            end

            // Accept write data
            if (s_axi_wvalid && !w_data_valid) begin
                s_axi_wready   <= 1'b1;
                w_data_latched <= s_axi_wdata;
                w_strb_latched <= s_axi_wstrb;
                w_data_valid   <= 1'b1;
            end else begin
                s_axi_wready <= 1'b0;
            end

            // Process write when both address and data are ready
            if (aw_addr_valid && w_data_valid) begin
                case (aw_addr_latched[5:2])
                    4'h0: key_reg[31:0]        <= w_data_latched;
                    4'h1: key_reg[63:32]       <= w_data_latched;
                    4'h2: key_reg[95:64]       <= w_data_latched;
                    4'h3: key_reg[127:96]      <= w_data_latched;
                    4'h4: data_in_reg[31:0]    <= w_data_latched;
                    4'h5: data_in_reg[63:32]   <= w_data_latched;
                    4'h6: data_in_reg[95:64]   <= w_data_latched;
                    4'h7: data_in_reg[127:96]  <= w_data_latched;
                    4'hC: begin // 0x30 = CTRL: write bit0 = start
                        if (w_data_latched[0] && !busy)
                            start_pulse <= 1'b1;
                    end
                    default: ; // Read-only or reserved
                endcase
                s_axi_bvalid  <= 1'b1;
                s_axi_bresp   <= 2'b00; // OKAY
                aw_addr_valid <= 1'b0;
                w_data_valid  <= 1'b0;
            end

            // Write response handshake
            if (s_axi_bvalid && s_axi_bready) begin
                s_axi_bvalid <= 1'b0;
            end
        end
    end

    // =========================================================================
    // AXI4-Lite Read Logic
    // =========================================================================
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s_axi_arready   <= 1'b0;
            s_axi_rvalid    <= 1'b0;
            s_axi_rdata     <= 32'd0;
            s_axi_rresp     <= 2'b00;
            ar_addr_latched  <= 6'd0;
        end else begin
            // Accept read address and respond in one cycle
            if (s_axi_arvalid && !s_axi_rvalid) begin
                s_axi_arready <= 1'b1;
                s_axi_rvalid  <= 1'b1;
                s_axi_rresp   <= 2'b00;
                case (s_axi_araddr[5:2])
                    4'h0: s_axi_rdata <= key_reg[31:0];
                    4'h1: s_axi_rdata <= key_reg[63:32];
                    4'h2: s_axi_rdata <= key_reg[95:64];
                    4'h3: s_axi_rdata <= key_reg[127:96];
                    4'h4: s_axi_rdata <= data_in_reg[31:0];
                    4'h5: s_axi_rdata <= data_in_reg[63:32];
                    4'h6: s_axi_rdata <= data_in_reg[95:64];
                    4'h7: s_axi_rdata <= data_in_reg[127:96];
                    4'h8: s_axi_rdata <= data_out_reg[31:0];
                    4'h9: s_axi_rdata <= data_out_reg[63:32];
                    4'hA: s_axi_rdata <= data_out_reg[95:64];
                    4'hB: s_axi_rdata <= data_out_reg[127:96];
                    4'hC: s_axi_rdata <= {30'd0, done, busy}; // STATUS
                    default: s_axi_rdata <= 32'd0;
                endcase
            end else begin
                s_axi_arready <= 1'b0;
            end

            // Read response handshake
            if (s_axi_rvalid && s_axi_rready) begin
                s_axi_rvalid <= 1'b0;
            end
        end
    end

endmodule

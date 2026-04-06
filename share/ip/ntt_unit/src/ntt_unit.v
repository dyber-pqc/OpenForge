`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////
// OpenForge EDA - Number Theoretic Transform (NTT) Unit for ML-KEM/Kyber
//
// Features:
//   - Parameterized for any NTT-friendly prime modulus
//   - Default configuration: Q=3329 (Kyber/ML-KEM), N=256, WIDTH=12
//   - Cooley-Tukey butterfly with modular arithmetic
//   - Twiddle factor ROM (precomputed)
//   - Forward and inverse NTT via mode select
//   - Iterative in-place computation with coefficient RAM
//
// Ports:
//   clk, rst_n       - Clock and active-low reset
//   start             - Pulse to begin NTT computation
//   busy              - Asserted during computation
//   done              - Pulses when computation is complete
//   mode              - 0=forward NTT, 1=inverse NTT
//   coeff_in          - Input coefficient data
//   coeff_in_valid    - Input coefficient valid
//   coeff_in_ready    - Ready to accept input coefficient
//   coeff_out         - Output coefficient data
//   coeff_out_valid   - Output coefficient valid
//   coeff_out_ready   - Downstream ready for output
//
// Copyright (c) 2024-2026 OpenForge Contributors
// SPDX-License-Identifier: Apache-2.0
//////////////////////////////////////////////////////////////////////////////

module ntt_unit #(
    parameter Q     = 3329,    // Prime modulus (Kyber)
    parameter N     = 256,     // Polynomial degree
    parameter WIDTH = 12,      // Coefficient bit width (ceil(log2(Q))+1)
    parameter LOG_N = 8        // log2(N)
) (
    input  wire              clk,
    input  wire              rst_n,

    // Control
    input  wire              start,
    output reg               busy,
    output reg               done,
    input  wire              mode,      // 0=forward NTT, 1=inverse NTT

    // Coefficient input (sequential, N coefficients)
    input  wire [WIDTH-1:0]  coeff_in,
    input  wire              coeff_in_valid,
    output reg               coeff_in_ready,

    // Coefficient output (sequential, N coefficients)
    output reg  [WIDTH-1:0]  coeff_out,
    output reg               coeff_out_valid,
    input  wire              coeff_out_ready
);

    // =========================================================================
    // Coefficient RAM (dual-port, in-place butterfly)
    // =========================================================================
    (* ram_style = "registers" *)
    reg [WIDTH-1:0] coeff_ram [0:N-1];

    // =========================================================================
    // Twiddle Factor ROM
    // For Kyber Q=3329, primitive 256th root of unity zeta=17
    // We store zeta^(bit_rev(i)) for i=0..127 (forward NTT)
    // Inverse uses zeta^(-bit_rev(i))
    // =========================================================================
    // Pre-computed twiddle factors for Q=3329, zeta=17
    // Using bit-reversed order as per NTT-friendly Kyber spec
    reg [WIDTH-1:0] twiddle_fwd [0:127];
    reg [WIDTH-1:0] twiddle_inv [0:127];

    // Initialize twiddle factors (synthesizable initial block)
    // These are powers of zeta=17 mod 3329 in bit-reversed order
    // For Kyber: zeta^{br(k)} mod Q for k=0..127
    initial begin
        // Forward twiddle factors: powers of 17 mod 3329 in bit-reversed order
        // zeta = 17, zeta^128 = -1 mod 3329
        twiddle_fwd[  0] = 12'd1;    twiddle_fwd[  1] = 12'd1729;
        twiddle_fwd[  2] = 12'd2580; twiddle_fwd[  3] = 12'd3289;
        twiddle_fwd[  4] = 12'd2642; twiddle_fwd[  5] = 12'd630;
        twiddle_fwd[  6] = 12'd1897; twiddle_fwd[  7] = 12'd848;
        twiddle_fwd[  8] = 12'd1062; twiddle_fwd[  9] = 12'd1919;
        twiddle_fwd[ 10] = 12'd193;  twiddle_fwd[ 11] = 12'd797;
        twiddle_fwd[ 12] = 12'd2786; twiddle_fwd[ 13] = 12'd3260;
        twiddle_fwd[ 14] = 12'd569;  twiddle_fwd[ 15] = 12'd1746;
        twiddle_fwd[ 16] = 12'd296;  twiddle_fwd[ 17] = 12'd2447;
        twiddle_fwd[ 18] = 12'd1339; twiddle_fwd[ 19] = 12'd1476;
        twiddle_fwd[ 20] = 12'd3046; twiddle_fwd[ 21] = 12'd56;
        twiddle_fwd[ 22] = 12'd2240; twiddle_fwd[ 23] = 12'd1333;
        twiddle_fwd[ 24] = 12'd1426; twiddle_fwd[ 25] = 12'd2094;
        twiddle_fwd[ 26] = 12'd535;  twiddle_fwd[ 27] = 12'd2882;
        twiddle_fwd[ 28] = 12'd2393; twiddle_fwd[ 29] = 12'd2879;
        twiddle_fwd[ 30] = 12'd1974; twiddle_fwd[ 31] = 12'd821;
        twiddle_fwd[ 32] = 12'd289;  twiddle_fwd[ 33] = 12'd331;
        twiddle_fwd[ 34] = 12'd3253; twiddle_fwd[ 35] = 12'd1756;
        twiddle_fwd[ 36] = 12'd1197; twiddle_fwd[ 37] = 12'd2304;
        twiddle_fwd[ 38] = 12'd2277; twiddle_fwd[ 39] = 12'd2055;
        twiddle_fwd[ 40] = 12'd650;  twiddle_fwd[ 41] = 12'd1977;
        twiddle_fwd[ 42] = 12'd2513; twiddle_fwd[ 43] = 12'd632;
        twiddle_fwd[ 44] = 12'd2865; twiddle_fwd[ 45] = 12'd33;
        twiddle_fwd[ 46] = 12'd1320; twiddle_fwd[ 47] = 12'd1915;
        twiddle_fwd[ 48] = 12'd2319; twiddle_fwd[ 49] = 12'd1435;
        twiddle_fwd[ 50] = 12'd807;  twiddle_fwd[ 51] = 12'd452;
        twiddle_fwd[ 52] = 12'd1438; twiddle_fwd[ 53] = 12'd2868;
        twiddle_fwd[ 54] = 12'd1534; twiddle_fwd[ 55] = 12'd2402;
        twiddle_fwd[ 56] = 12'd2647; twiddle_fwd[ 57] = 12'd2617;
        twiddle_fwd[ 58] = 12'd1481; twiddle_fwd[ 59] = 12'd648;
        twiddle_fwd[ 60] = 12'd2474; twiddle_fwd[ 61] = 12'd3110;
        twiddle_fwd[ 62] = 12'd1227; twiddle_fwd[ 63] = 12'd910;
        // Remaining twiddles (higher-layer butterflies)
        twiddle_fwd[ 64] = 12'd17;   twiddle_fwd[ 65] = 12'd2761;
        twiddle_fwd[ 66] = 12'd583;  twiddle_fwd[ 67] = 12'd2649;
        twiddle_fwd[ 68] = 12'd1637; twiddle_fwd[ 69] = 12'd723;
        twiddle_fwd[ 70] = 12'd2288; twiddle_fwd[ 71] = 12'd1100;
        twiddle_fwd[ 72] = 12'd1409; twiddle_fwd[ 73] = 12'd2662;
        twiddle_fwd[ 74] = 12'd3281; twiddle_fwd[ 75] = 12'd233;
        twiddle_fwd[ 76] = 12'd756;  twiddle_fwd[ 77] = 12'd2156;
        twiddle_fwd[ 78] = 12'd3015; twiddle_fwd[ 79] = 12'd3050;
        twiddle_fwd[ 80] = 12'd1455; twiddle_fwd[ 81] = 12'd1987;
        twiddle_fwd[ 82] = 12'd2604; twiddle_fwd[ 83] = 12'd2136;
        twiddle_fwd[ 84] = 12'd1571; twiddle_fwd[ 85] = 12'd205;
        twiddle_fwd[ 86] = 12'd2918; twiddle_fwd[ 87] = 12'd1542;
        twiddle_fwd[ 88] = 12'd2721; twiddle_fwd[ 89] = 12'd2597;
        twiddle_fwd[ 90] = 12'd2312; twiddle_fwd[ 91] = 12'd681;
        twiddle_fwd[ 92] = 12'd130;  twiddle_fwd[ 93] = 12'd1602;
        twiddle_fwd[ 94] = 12'd1871; twiddle_fwd[ 95] = 12'd829;
        twiddle_fwd[ 96] = 12'd2946; twiddle_fwd[ 97] = 12'd3065;
        twiddle_fwd[ 98] = 12'd1325; twiddle_fwd[ 99] = 12'd2756;
        twiddle_fwd[100] = 12'd1861; twiddle_fwd[101] = 12'd1474;
        twiddle_fwd[102] = 12'd1202; twiddle_fwd[103] = 12'd2367;
        twiddle_fwd[104] = 12'd3147; twiddle_fwd[105] = 12'd1752;
        twiddle_fwd[106] = 12'd2707; twiddle_fwd[107] = 12'd171;
        twiddle_fwd[108] = 12'd3127; twiddle_fwd[109] = 12'd3042;
        twiddle_fwd[110] = 12'd1907; twiddle_fwd[111] = 12'd1836;
        twiddle_fwd[112] = 12'd1517; twiddle_fwd[113] = 12'd359;
        twiddle_fwd[114] = 12'd758;  twiddle_fwd[115] = 12'd1441;
        twiddle_fwd[116] = 12'd2952; twiddle_fwd[117] = 12'd2438;
        twiddle_fwd[118] = 12'd2471; twiddle_fwd[119] = 12'd1616;
        twiddle_fwd[120] = 12'd2624; twiddle_fwd[121] = 12'd1736;
        twiddle_fwd[122] = 12'd2811; twiddle_fwd[123] = 12'd2998;
        twiddle_fwd[124] = 12'd2064; twiddle_fwd[125] = 12'd233;
        twiddle_fwd[126] = 12'd2014; twiddle_fwd[127] = 12'd2006;

        // Inverse twiddle factors: Q - twiddle_fwd[i] for all (negation mod Q)
        twiddle_inv[  0] = 12'd1;    twiddle_inv[  1] = 12'd1600;
        twiddle_inv[  2] = 12'd749;  twiddle_inv[  3] = 12'd40;
        twiddle_inv[  4] = 12'd687;  twiddle_inv[  5] = 12'd2699;
        twiddle_inv[  6] = 12'd1432; twiddle_inv[  7] = 12'd2481;
        twiddle_inv[  8] = 12'd2267; twiddle_inv[  9] = 12'd1410;
        twiddle_inv[ 10] = 12'd3136; twiddle_inv[ 11] = 12'd2532;
        twiddle_inv[ 12] = 12'd543;  twiddle_inv[ 13] = 12'd69;
        twiddle_inv[ 14] = 12'd2760; twiddle_inv[ 15] = 12'd1583;
        twiddle_inv[ 16] = 12'd3033; twiddle_inv[ 17] = 12'd882;
        twiddle_inv[ 18] = 12'd1990; twiddle_inv[ 19] = 12'd1853;
        twiddle_inv[ 20] = 12'd283;  twiddle_inv[ 21] = 12'd3273;
        twiddle_inv[ 22] = 12'd1089; twiddle_inv[ 23] = 12'd1996;
        twiddle_inv[ 24] = 12'd1903; twiddle_inv[ 25] = 12'd1235;
        twiddle_inv[ 26] = 12'd2794; twiddle_inv[ 27] = 12'd447;
        twiddle_inv[ 28] = 12'd936;  twiddle_inv[ 29] = 12'd450;
        twiddle_inv[ 30] = 12'd1355; twiddle_inv[ 31] = 12'd2508;
        twiddle_inv[ 32] = 12'd3040; twiddle_inv[ 33] = 12'd2998;
        twiddle_inv[ 34] = 12'd76;   twiddle_inv[ 35] = 12'd1573;
        twiddle_inv[ 36] = 12'd2132; twiddle_inv[ 37] = 12'd1025;
        twiddle_inv[ 38] = 12'd1052; twiddle_inv[ 39] = 12'd1274;
        twiddle_inv[ 40] = 12'd2679; twiddle_inv[ 41] = 12'd1352;
        twiddle_inv[ 42] = 12'd816;  twiddle_inv[ 43] = 12'd2697;
        twiddle_inv[ 44] = 12'd464;  twiddle_inv[ 45] = 12'd3296;
        twiddle_inv[ 46] = 12'd2009; twiddle_inv[ 47] = 12'd1414;
        twiddle_inv[ 48] = 12'd1010; twiddle_inv[ 49] = 12'd1894;
        twiddle_inv[ 50] = 12'd2522; twiddle_inv[ 51] = 12'd2877;
        twiddle_inv[ 52] = 12'd1891; twiddle_inv[ 53] = 12'd461;
        twiddle_inv[ 54] = 12'd1795; twiddle_inv[ 55] = 12'd927;
        twiddle_inv[ 56] = 12'd682;  twiddle_inv[ 57] = 12'd712;
        twiddle_inv[ 58] = 12'd1848; twiddle_inv[ 59] = 12'd2681;
        twiddle_inv[ 60] = 12'd855;  twiddle_inv[ 61] = 12'd219;
        twiddle_inv[ 62] = 12'd2102; twiddle_inv[ 63] = 12'd2419;
        twiddle_inv[ 64] = 12'd3312; twiddle_inv[ 65] = 12'd568;
        twiddle_inv[ 66] = 12'd2746; twiddle_inv[ 67] = 12'd680;
        twiddle_inv[ 68] = 12'd1692; twiddle_inv[ 69] = 12'd2606;
        twiddle_inv[ 70] = 12'd1041; twiddle_inv[ 71] = 12'd2229;
        twiddle_inv[ 72] = 12'd1920; twiddle_inv[ 73] = 12'd667;
        twiddle_inv[ 74] = 12'd48;   twiddle_inv[ 75] = 12'd3096;
        twiddle_inv[ 76] = 12'd2573; twiddle_inv[ 77] = 12'd1173;
        twiddle_inv[ 78] = 12'd314;  twiddle_inv[ 79] = 12'd279;
        twiddle_inv[ 80] = 12'd1874; twiddle_inv[ 81] = 12'd1342;
        twiddle_inv[ 82] = 12'd725;  twiddle_inv[ 83] = 12'd1193;
        twiddle_inv[ 84] = 12'd1758; twiddle_inv[ 85] = 12'd3124;
        twiddle_inv[ 86] = 12'd411;  twiddle_inv[ 87] = 12'd1787;
        twiddle_inv[ 88] = 12'd608;  twiddle_inv[ 89] = 12'd732;
        twiddle_inv[ 90] = 12'd1017; twiddle_inv[ 91] = 12'd2648;
        twiddle_inv[ 92] = 12'd3199; twiddle_inv[ 93] = 12'd1727;
        twiddle_inv[ 94] = 12'd1458; twiddle_inv[ 95] = 12'd2500;
        twiddle_inv[ 96] = 12'd383;  twiddle_inv[ 97] = 12'd264;
        twiddle_inv[ 98] = 12'd2004; twiddle_inv[ 99] = 12'd573;
        twiddle_inv[100] = 12'd1468; twiddle_inv[101] = 12'd1855;
        twiddle_inv[102] = 12'd2127; twiddle_inv[103] = 12'd962;
        twiddle_inv[104] = 12'd182;  twiddle_inv[105] = 12'd1577;
        twiddle_inv[106] = 12'd622;  twiddle_inv[107] = 12'd3158;
        twiddle_inv[108] = 12'd202;  twiddle_inv[109] = 12'd287;
        twiddle_inv[110] = 12'd1422; twiddle_inv[111] = 12'd1493;
        twiddle_inv[112] = 12'd1812; twiddle_inv[113] = 12'd2970;
        twiddle_inv[114] = 12'd2571; twiddle_inv[115] = 12'd1888;
        twiddle_inv[116] = 12'd377;  twiddle_inv[117] = 12'd891;
        twiddle_inv[118] = 12'd858;  twiddle_inv[119] = 12'd1713;
        twiddle_inv[120] = 12'd705;  twiddle_inv[121] = 12'd1593;
        twiddle_inv[122] = 12'd518;  twiddle_inv[123] = 12'd331;
        twiddle_inv[124] = 12'd1265; twiddle_inv[125] = 12'd3096;
        twiddle_inv[126] = 12'd1315; twiddle_inv[127] = 12'd1323;
    end

    // =========================================================================
    // Modular arithmetic helpers
    // =========================================================================
    // Barrett reduction: a mod Q where a < Q^2
    // For Q=3329: multiplier approximation for Barrett
    function [WIDTH-1:0] mod_reduce;
        input [2*WIDTH-1:0] val;
        reg [2*WIDTH-1:0] tmp;
        begin
            // Simple modular reduction via conditional subtraction
            // Works for val < 2*Q*Q range from butterfly
            tmp = val;
            while (tmp >= Q)
                tmp = tmp - Q;
            mod_reduce = tmp[WIDTH-1:0];
        end
    endfunction

    // Modular subtraction: (a - b) mod Q
    function [WIDTH-1:0] mod_sub;
        input [WIDTH-1:0] a;
        input [WIDTH-1:0] b;
        begin
            if (a >= b)
                mod_sub = a - b;
            else
                mod_sub = Q[WIDTH-1:0] + a - b;
        end
    endfunction

    // Modular addition: (a + b) mod Q
    function [WIDTH-1:0] mod_add;
        input [WIDTH-1:0] a;
        input [WIDTH-1:0] b;
        reg [WIDTH:0] sum;
        begin
            sum = a + b;
            if (sum >= Q)
                mod_add = sum - Q;
            else
                mod_add = sum[WIDTH-1:0];
        end
    endfunction

    // =========================================================================
    // NTT FSM
    // =========================================================================
    localparam FSM_IDLE     = 3'd0;
    localparam FSM_LOAD     = 3'd1;
    localparam FSM_COMPUTE  = 3'd2;
    localparam FSM_OUTPUT   = 3'd3;
    localparam FSM_DONE     = 3'd4;

    reg [2:0]          fsm;
    reg [LOG_N-1:0]    load_cnt;
    reg [LOG_N-1:0]    out_cnt;
    reg [LOG_N-1:0]    stage;        // Current butterfly stage (0..LOG_N-1)
    reg [LOG_N-1:0]    group;        // Current butterfly index within stage
    reg                mode_reg;     // Latched mode

    // Butterfly computation wires
    reg [LOG_N-1:0]    bf_idx_a;    // Index of first butterfly operand
    reg [LOG_N-1:0]    bf_idx_b;    // Index of second butterfly operand
    reg [6:0]          tw_idx;      // Twiddle factor index
    reg [WIDTH-1:0]    tw;          // Current twiddle factor
    reg [WIDTH-1:0]    a_val, b_val;
    reg [2*WIDTH-1:0]  tw_mult;     // Twiddle * b product
    reg [WIDTH-1:0]    bf_out_a;    // Butterfly output upper
    reg [WIDTH-1:0]    bf_out_b;    // Butterfly output lower

    // Butterfly index calculation
    reg [LOG_N-1:0] half_size;
    reg [LOG_N-1:0] bf_group_idx;
    reg [LOG_N-1:0] bf_pair_idx;

    integer i;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fsm            <= FSM_IDLE;
            busy           <= 1'b0;
            done           <= 1'b0;
            coeff_in_ready <= 1'b0;
            coeff_out_valid <= 1'b0;
            coeff_out      <= {WIDTH{1'b0}};
            load_cnt       <= {LOG_N{1'b0}};
            out_cnt        <= {LOG_N{1'b0}};
            stage          <= {LOG_N{1'b0}};
            group          <= {LOG_N{1'b0}};
            mode_reg       <= 1'b0;
            for (i = 0; i < N; i = i + 1)
                coeff_ram[i] <= {WIDTH{1'b0}};
        end else begin
            done <= 1'b0;

            case (fsm)
                FSM_IDLE: begin
                    coeff_in_ready <= 1'b1;
                    if (start) begin
                        busy           <= 1'b1;
                        mode_reg       <= mode;
                        load_cnt       <= {LOG_N{1'b0}};
                        fsm            <= FSM_LOAD;
                    end
                end

                FSM_LOAD: begin
                    // Load N coefficients into RAM
                    if (coeff_in_valid && coeff_in_ready) begin
                        coeff_ram[load_cnt] <= coeff_in;
                        if (load_cnt == N - 1) begin
                            coeff_in_ready <= 1'b0;
                            stage          <= {LOG_N{1'b0}};
                            group          <= {LOG_N{1'b0}};
                            fsm            <= FSM_COMPUTE;
                        end else begin
                            load_cnt <= load_cnt + 1;
                        end
                    end
                end

                FSM_COMPUTE: begin
                    // Cooley-Tukey butterfly: LOG_N stages, N/2 butterflies each
                    // For forward NTT: decimation-in-time
                    half_size    = (1 << stage);
                    bf_group_idx = group >> stage;      // Which group
                    bf_pair_idx  = group & (half_size - 1); // Position in group

                    bf_idx_a = (bf_group_idx << (stage + 1)) | bf_pair_idx;
                    bf_idx_b = bf_idx_a | half_size;
                    tw_idx   = bf_group_idx + (N >> (stage + 1));

                    a_val = coeff_ram[bf_idx_a];
                    b_val = coeff_ram[bf_idx_b];

                    // Select twiddle factor based on mode
                    tw = mode_reg ? twiddle_inv[tw_idx[6:0]] : twiddle_fwd[tw_idx[6:0]];

                    // Butterfly: a' = a + tw*b mod Q, b' = a - tw*b mod Q
                    tw_mult = tw * b_val;
                    bf_out_a = mod_add(a_val, mod_reduce(tw_mult));
                    bf_out_b = mod_sub(a_val, mod_reduce(tw_mult));

                    coeff_ram[bf_idx_a] <= bf_out_a;
                    coeff_ram[bf_idx_b] <= bf_out_b;

                    if (group == (N / 2) - 1) begin
                        group <= {LOG_N{1'b0}};
                        if (stage == LOG_N - 1) begin
                            out_cnt <= {LOG_N{1'b0}};
                            fsm     <= FSM_OUTPUT;
                        end else begin
                            stage <= stage + 1;
                        end
                    end else begin
                        group <= group + 1;
                    end
                end

                FSM_OUTPUT: begin
                    // Stream out coefficients
                    coeff_out_valid <= 1'b1;
                    coeff_out       <= coeff_ram[out_cnt];
                    if (coeff_out_valid && coeff_out_ready) begin
                        if (out_cnt == N - 1) begin
                            coeff_out_valid <= 1'b0;
                            fsm             <= FSM_DONE;
                        end else begin
                            out_cnt <= out_cnt + 1;
                        end
                    end
                end

                FSM_DONE: begin
                    busy <= 1'b0;
                    done <= 1'b1;
                    fsm  <= FSM_IDLE;
                end

                default: fsm <= FSM_IDLE;
            endcase
        end
    end

endmodule

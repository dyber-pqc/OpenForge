`timescale 1ns/1ps

// Keccak-f[1600] single round permutation
// Implements one round of the SHA-3 permutation: theta, rho, pi, chi, iota.
// The state is a 5x5 array of 64-bit lanes = 1600 bits total.

module keccak_round (
    input  wire [1599:0] state_in,
    input  wire [63:0]   round_constant,
    output wire [1599:0] state_out
);

    // Unpack the 1600-bit state into a 5x5 array of 64-bit lanes.
    // Lane[x][y] = state_in[64*(5*y+x) +: 64]
    wire [63:0] A [0:4][0:4];
    wire [63:0] A_theta [0:4][0:4];
    wire [63:0] A_rho_pi [0:4][0:4];
    wire [63:0] A_chi [0:4][0:4];
    wire [63:0] A_iota [0:4][0:4];

    genvar gx, gy;

    // --- Unpack ---
    generate
        for (gy = 0; gy < 5; gy = gy + 1) begin : unpack_y
            for (gx = 0; gx < 5; gx = gx + 1) begin : unpack_x
                assign A[gx][gy] = state_in[64*(5*gy+gx) +: 64];
            end
        end
    endgenerate

    // --- Theta step ---
    // C[x] = A[x,0] ^ A[x,1] ^ A[x,2] ^ A[x,3] ^ A[x,4]
    // D[x] = C[x-1] ^ rot(C[x+1], 1)
    // A'[x,y] = A[x,y] ^ D[x]
    wire [63:0] C [0:4];
    wire [63:0] D [0:4];

    generate
        for (gx = 0; gx < 5; gx = gx + 1) begin : theta_c
            assign C[gx] = A[gx][0] ^ A[gx][1] ^ A[gx][2]
                          ^ A[gx][3] ^ A[gx][4];
        end
        for (gx = 0; gx < 5; gx = gx + 1) begin : theta_d
            assign D[gx] = C[(gx + 4) % 5]
                         ^ {C[(gx + 1) % 5][62:0], C[(gx + 1) % 5][63]};
        end
        for (gy = 0; gy < 5; gy = gy + 1) begin : theta_y
            for (gx = 0; gx < 5; gx = gx + 1) begin : theta_x
                assign A_theta[gx][gy] = A[gx][gy] ^ D[gx];
            end
        end
    endgenerate

    // --- Rho and Pi steps (combined) ---
    // B[y, 2*x+3*y] = rot(A'[x,y], rho_offset[x][y])
    // Rho rotation offsets (NIST FIPS 202, Table 2)
    function [63:0] rotl64;
        input [63:0] val;
        input integer amount;
        begin
            if (amount == 0)
                rotl64 = val;
            else
                rotl64 = {val[63-amount:0], val[63:64-amount]};
        end
    endfunction

    // We use a generate block to compute rho+pi in one step.
    // The offset table for rho:
    //   [x][y] offsets (mod 64):
    //   [0][0]=0  [1][0]=1  [2][0]=62  [3][0]=28  [4][0]=27
    //   [0][1]=36 [1][1]=44 [2][1]=6   [3][1]=55  [4][1]=20
    //   [0][2]=3  [1][2]=10 [2][2]=43  [3][2]=25  [4][2]=39
    //   [0][3]=41 [1][3]=45 [2][3]=15  [3][3]=21  [4][3]=8
    //   [0][4]=18 [1][4]=2  [2][4]=61  [3][4]=56  [4][4]=14

    // After pi: B[y][2x+3y mod 5] = rot(A_theta[x][y], offset)
    // We precompute the destination and rotation for each (x,y).

    // Rho offsets stored as a flat lookup
    wire [63:0] B [0:4][0:4];

    // Manually assign rho+pi for each of the 25 lanes
    // pi: (x,y) -> (y, 2x+3y mod 5)
    assign B[0][0] = A_theta[0][0];                                                              // rot 0
    assign B[0][2] = {A_theta[1][0][62:0], A_theta[1][0][63]};                                   // rot 1
    assign B[0][4] = {A_theta[2][0][1:0],  A_theta[2][0][63:2]};                                 // rot 62
    assign B[0][1] = {A_theta[3][0][35:0], A_theta[3][0][63:36]};                                // rot 28
    assign B[0][3] = {A_theta[4][0][36:0], A_theta[4][0][63:37]};                                // rot 27

    assign B[1][3] = {A_theta[0][1][27:0], A_theta[0][1][63:28]};                                // rot 36
    assign B[1][0] = {A_theta[1][1][19:0], A_theta[1][1][63:20]};                                // rot 44
    assign B[1][2] = {A_theta[2][1][57:0], A_theta[2][1][63:58]};                                // rot 6
    assign B[1][4] = {A_theta[3][1][8:0],  A_theta[3][1][63:9]};                                 // rot 55
    assign B[1][1] = {A_theta[4][1][43:0], A_theta[4][1][63:44]};                                // rot 20

    assign B[2][1] = {A_theta[0][2][60:0], A_theta[0][2][63:61]};                                // rot 3
    assign B[2][3] = {A_theta[1][2][53:0], A_theta[1][2][63:54]};                                // rot 10
    assign B[2][0] = {A_theta[2][2][20:0], A_theta[2][2][63:21]};                                // rot 43
    assign B[2][2] = {A_theta[3][2][38:0], A_theta[3][2][63:39]};                                // rot 25
    assign B[2][4] = {A_theta[4][2][24:0], A_theta[4][2][63:25]};                                // rot 39

    assign B[3][4] = {A_theta[0][3][22:0], A_theta[0][3][63:23]};                                // rot 41
    assign B[3][1] = {A_theta[1][3][18:0], A_theta[1][3][63:19]};                                // rot 45
    assign B[3][3] = {A_theta[2][3][48:0], A_theta[2][3][63:49]};                                // rot 15
    assign B[3][0] = {A_theta[3][3][42:0], A_theta[3][3][63:43]};                                // rot 21
    assign B[3][2] = {A_theta[4][3][55:0], A_theta[4][3][63:56]};                                // rot 8

    assign B[4][2] = {A_theta[0][4][45:0], A_theta[0][4][63:46]};                                // rot 18
    assign B[4][4] = {A_theta[1][4][61:0], A_theta[1][4][63:62]};                                // rot 2
    assign B[4][1] = {A_theta[2][4][2:0],  A_theta[2][4][63:3]};                                 // rot 61
    assign B[4][3] = {A_theta[3][4][7:0],  A_theta[3][4][63:8]};                                 // rot 56
    assign B[4][0] = {A_theta[4][4][49:0], A_theta[4][4][63:50]};                                // rot 14

    // --- Chi step ---
    // A''[x,y] = B[x,y] ^ (~B[x+1,y] & B[x+2,y])
    generate
        for (gy = 0; gy < 5; gy = gy + 1) begin : chi_y
            for (gx = 0; gx < 5; gx = gx + 1) begin : chi_x
                assign A_chi[gx][gy] = B[gx][gy]
                    ^ (~B[(gx+1)%5][gy] & B[(gx+2)%5][gy]);
            end
        end
    endgenerate

    // --- Iota step ---
    // A'''[0,0] = A''[0,0] ^ RC
    generate
        for (gy = 0; gy < 5; gy = gy + 1) begin : iota_y
            for (gx = 0; gx < 5; gx = gx + 1) begin : iota_x
                if (gx == 0 && gy == 0) begin : iota_apply
                    assign A_iota[0][0] = A_chi[0][0] ^ round_constant;
                end else begin : iota_pass
                    assign A_iota[gx][gy] = A_chi[gx][gy];
                end
            end
        end
    endgenerate

    // --- Pack output ---
    generate
        for (gy = 0; gy < 5; gy = gy + 1) begin : pack_y
            for (gx = 0; gx < 5; gx = gx + 1) begin : pack_x
                assign state_out[64*(5*gy+gx) +: 64] = A_iota[gx][gy];
            end
        end
    endgenerate

endmodule

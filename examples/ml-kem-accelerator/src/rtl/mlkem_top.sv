// ML-KEM (FIPS 203) Top-Level Accelerator Module
// Post-quantum key encapsulation mechanism hardware implementation
// Copyright 2026 Dyber Inc. -- OpenForge EDA Example Project

module mlkem_top #(
    parameter K       = 3,         // Security level: 2=ML-KEM-512, 3=ML-KEM-768, 4=ML-KEM-1024
    parameter Q       = 3329,      // Kyber prime modulus
    parameter N       = 256,       // Polynomial degree
    parameter ETA1    = 2,         // CBD parameter for secret key
    parameter ETA2    = 2,         // CBD parameter for encryption noise
    parameter DU      = 10,        // Compressed ciphertext bits (u)
    parameter DV      = 4          // Compressed ciphertext bits (v)
) (
    input  wire             clk,
    input  wire             rst_n,

    // Control interface
    input  wire [2:0]       cmd,            // 0=idle, 1=keygen, 2=encaps, 3=decaps, 4=self_test
    input  wire             cmd_valid,
    output wire             cmd_ready,
    output wire             done,
    output wire             error,

    // Key I/O (AXI-Stream style)
    input  wire [63:0]      data_in,
    input  wire             data_in_valid,
    output wire             data_in_ready,

    output wire [63:0]      data_out,
    output wire             data_out_valid,
    input  wire             data_out_ready,

    // RNG interface (for key generation)
    input  wire [63:0]      rng_data,
    input  wire             rng_valid,
    output wire             rng_ready,

    // FIPS 140-3 interface
    input  wire             zeroize,         // Key zeroization command
    output wire             self_test_pass,
    output wire             health_test_fail
);

    // ── FSM ─────────────────────────────────────────────────────────
    typedef enum logic [3:0] {
        ST_IDLE       = 4'd0,
        ST_KEYGEN     = 4'd1,
        ST_ENCAPS     = 4'd2,
        ST_DECAPS     = 4'd3,
        ST_SELF_TEST  = 4'd4,
        ST_NTT        = 4'd5,
        ST_INTT       = 4'd6,
        ST_MULTIPLY   = 4'd7,
        ST_COMPRESS   = 4'd8,
        ST_DECOMPRESS = 4'd9,
        ST_ERROR      = 4'd15
    } state_t;

    state_t state, next_state;

    // ── Key storage (CSP - Critical Security Parameter) ─────────────
    reg [11:0] secret_key [0:K*N-1];    // sk: K polynomials of N coefficients
    reg [11:0] public_key [0:K*N-1];    // pk: K polynomials
    reg [255:0] seed_d;                   // d seed for keygen
    reg [255:0] seed_z;                   // z seed for implicit rejection

    // ── NTT butterfly instantiation ─────────────────────────────────
    wire        ntt_valid_in, ntt_valid_out;
    wire [11:0] ntt_a_in, ntt_b_in, ntt_twiddle;
    wire [11:0] ntt_a_out, ntt_b_out;

    ntt_butterfly #(
        .Q     (Q),
        .WIDTH (12)
    ) u_ntt_butterfly (
        .clk       (clk),
        .rst_n     (rst_n),
        .valid_in  (ntt_valid_in),
        .a_in      (ntt_a_in),
        .b_in      (ntt_b_in),
        .twiddle   (ntt_twiddle),
        .valid_out (ntt_valid_out),
        .a_out     (ntt_a_out),
        .b_out     (ntt_b_out)
    );

    // ── Key zeroization (FIPS 140-3 requirement) ────────────────────
    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n || zeroize) begin
            for (i = 0; i < K*N; i = i + 1) begin
                secret_key[i] <= 12'd0;
            end
            seed_d <= 256'd0;
            seed_z <= 256'd0;
        end
    end

    // ── FSM logic ───────────────────────────────────────────────────
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            state <= ST_IDLE;
        else
            state <= next_state;
    end

    always @(*) begin
        next_state = state;
        case (state)
            ST_IDLE: begin
                if (cmd_valid) begin
                    case (cmd)
                        3'd1: next_state = ST_KEYGEN;
                        3'd2: next_state = ST_ENCAPS;
                        3'd3: next_state = ST_DECAPS;
                        3'd4: next_state = ST_SELF_TEST;
                        default: next_state = ST_IDLE;
                    endcase
                end
            end
            ST_KEYGEN:    next_state = done ? ST_IDLE : ST_NTT;
            ST_ENCAPS:    next_state = done ? ST_IDLE : ST_NTT;
            ST_DECAPS:    next_state = done ? ST_IDLE : ST_NTT;
            ST_SELF_TEST: next_state = done ? ST_IDLE : ST_SELF_TEST;
            ST_NTT:       next_state = ntt_valid_out ? ST_MULTIPLY : ST_NTT;
            ST_MULTIPLY:  next_state = ST_INTT;
            ST_INTT:      next_state = ST_COMPRESS;
            ST_COMPRESS:  next_state = ST_IDLE;
            ST_ERROR:     next_state = ST_ERROR;  // Sticky error state
            default:      next_state = ST_ERROR;
        endcase
    end

    // ── Error state is sticky (FIPS requirement) ────────────────────
    // Error state can only be exited by reset

    // ── Self-test gating (FIPS requirement) ─────────────────────────
    reg self_test_done;
    assign self_test_pass = self_test_done;

    // Crypto operations blocked until self-test passes
    wire crypto_enable = self_test_done && !health_test_fail;

    // ── Placeholder assignments ─────────────────────────────────────
    assign cmd_ready     = (state == ST_IDLE) && crypto_enable;
    assign done          = 1'b0;  // TODO: implement completion logic
    assign error         = (state == ST_ERROR);
    assign data_in_ready = 1'b0;  // TODO
    assign data_out       = 64'd0;  // TODO
    assign data_out_valid = 1'b0;   // TODO
    assign rng_ready      = 1'b0;   // TODO
    assign health_test_fail = 1'b0; // TODO: connect to RNG health monitor

    assign ntt_valid_in = 1'b0;     // TODO
    assign ntt_a_in     = 12'd0;    // TODO
    assign ntt_b_in     = 12'd0;    // TODO
    assign ntt_twiddle  = 12'd0;    // TODO

endmodule

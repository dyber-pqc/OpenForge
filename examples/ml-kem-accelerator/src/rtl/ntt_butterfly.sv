// NTT Butterfly Unit for ML-KEM (FIPS 203)
// Cooley-Tukey butterfly: a' = a + w*b mod q, b' = a - w*b mod q
// q = 3329 (Kyber prime)

module ntt_butterfly #(
    parameter Q     = 3329,
    parameter WIDTH = 12   // ceil(log2(Q))
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             valid_in,
    input  wire [WIDTH-1:0] a_in,
    input  wire [WIDTH-1:0] b_in,
    input  wire [WIDTH-1:0] twiddle,  // w (twiddle factor)
    output reg              valid_out,
    output reg  [WIDTH-1:0] a_out,
    output reg  [WIDTH-1:0] b_out
);

    // Pipeline stage 1: multiply
    reg [2*WIDTH-1:0] wb_product;
    reg [WIDTH-1:0]   a_pipe1;
    reg               valid_pipe1;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wb_product <= '0;
            a_pipe1    <= '0;
            valid_pipe1 <= 1'b0;
        end else begin
            wb_product  <= twiddle * b_in;
            a_pipe1     <= a_in;
            valid_pipe1 <= valid_in;
        end
    end

    // Pipeline stage 2: modular reduction + add/sub
    wire [2*WIDTH-1:0] wb_mod = wb_product % Q;  // Barrett reduction in real impl
    wire [WIDTH:0]     sum    = a_pipe1 + wb_mod[WIDTH-1:0];
    wire [WIDTH:0]     diff   = a_pipe1 - wb_mod[WIDTH-1:0] + Q;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_out     <= '0;
            b_out     <= '0;
            valid_out <= 1'b0;
        end else begin
            a_out     <= (sum >= Q) ? sum - Q : sum[WIDTH-1:0];
            b_out     <= (diff >= Q) ? diff - Q : diff[WIDTH-1:0];
            valid_out <= valid_pipe1;
        end
    end

endmodule

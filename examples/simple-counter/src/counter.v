// Simple 8-bit counter - OpenForge example design
module counter #(
    parameter WIDTH = 8
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             enable,
    output reg  [WIDTH-1:0] count,
    output wire             overflow
);

    assign overflow = (count == {WIDTH{1'b1}}) & enable;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            count <= {WIDTH{1'b0}};
        end else if (enable) begin
            count <= count + 1'b1;
        end
    end

endmodule
// Minimal serial-parallel multiplier stub used as a fixture.
module spm (
    input  wire        clk,
    input  wire        rst,
    input  wire        x,
    input  wire [31:0] y,
    output wire        p
);
    reg [31:0] acc;
    always @(posedge clk) begin
        if (rst) acc <= 0;
        else     acc <= acc + (x ? y : 32'd0);
    end
    assign p = acc[0];
endmodule

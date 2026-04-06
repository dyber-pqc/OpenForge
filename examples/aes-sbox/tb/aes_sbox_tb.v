`timescale 1ns/1ps

// AES S-Box Testbench - verifies known input/output vectors from FIPS 197
module aes_sbox_tb;

    reg  [7:0] data_in;
    wire [7:0] data_out;

    aes_sbox uut (
        .data_in(data_in),
        .data_out(data_out)
    );

    integer errors;
    integer i;

    // Known AES S-Box test vectors (input -> expected output)
    reg [7:0] test_inputs  [0:15];
    reg [7:0] test_expects [0:15];

    initial begin
        $dumpfile("dump.vcd");
        $dumpvars(0, aes_sbox_tb);

        errors = 0;

        // Standard AES S-Box test vectors
        test_inputs[0]  = 8'h00; test_expects[0]  = 8'h63;
        test_inputs[1]  = 8'h01; test_expects[1]  = 8'h7c;
        test_inputs[2]  = 8'h10; test_expects[2]  = 8'hca;
        test_inputs[3]  = 8'h53; test_expects[3]  = 8'hed;
        test_inputs[4]  = 8'hff; test_expects[4]  = 8'h16;
        test_inputs[5]  = 8'h7f; test_expects[5]  = 8'hd2;
        test_inputs[6]  = 8'h80; test_expects[6]  = 8'hcd;
        test_inputs[7]  = 8'hab; test_expects[7]  = 8'h62;
        test_inputs[8]  = 8'hfe; test_expects[8]  = 8'hbb;
        test_inputs[9]  = 8'h19; test_expects[9]  = 8'hd4;
        test_inputs[10] = 8'ha7; test_expects[10] = 8'h5c;
        test_inputs[11] = 8'h3c; test_expects[11] = 8'heb;
        test_inputs[12] = 8'hd4; test_expects[12] = 8'h48;
        test_inputs[13] = 8'he0; test_expects[13] = 8'he1;
        test_inputs[14] = 8'h6a; test_expects[14] = 8'h02;
        test_inputs[15] = 8'h52; test_expects[15] = 8'h00;

        $display("=== AES S-Box Test ===");

        for (i = 0; i < 16; i = i + 1) begin
            data_in = test_inputs[i];
            #10;
            if (data_out !== test_expects[i]) begin
                $display("FAIL: S-Box[%02h] = %02h, expected %02h",
                         data_in, data_out, test_expects[i]);
                errors = errors + 1;
            end else begin
                $display("  OK: S-Box[%02h] = %02h", data_in, data_out);
            end
        end

        // Exhaustive check: verify S-Box is a permutation (all 256 outputs unique)
        begin : exhaustive_check
            reg [255:0] seen;
            seen = 256'b0;
            for (i = 0; i < 256; i = i + 1) begin
                data_in = i[7:0];
                #1;
                if (seen[data_out]) begin
                    $display("FAIL: Duplicate output %02h for input %02h",
                             data_out, data_in);
                    errors = errors + 1;
                end
                seen[data_out] = 1'b1;
            end
            // Check all 256 values appeared
            if (seen !== {256{1'b1}}) begin
                $display("FAIL: S-Box is not a permutation");
                errors = errors + 1;
            end else begin
                $display("  OK: S-Box is a valid permutation (256 unique outputs)");
            end
        end

        $display("");
        if (errors == 0)
            $display("PASS: All AES S-Box tests passed.");
        else
            $display("FAIL: %0d error(s) detected.", errors);

        $finish;
    end

endmodule

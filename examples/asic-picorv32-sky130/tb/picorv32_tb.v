`timescale 1ns / 1ps
//-----------------------------------------------------------------------------
// picorv32_tb.v - Minimal smoke testbench for PicoRV32
//
// Drives clk + reset and runs 100 cycles. PicoRV32 will issue an instruction
// fetch on the memory bus; we tie mem_ready high after a 1-cycle delay and
// always return NOP (0x00000013 = addi x0, x0, 0). This is the smallest
// possible "does the core start" smoke test - no program, no checks.
//-----------------------------------------------------------------------------

module picorv32_tb;

    reg         clk;
    reg         resetn;
    wire        trap;

    // Native memory interface
    wire        mem_valid;
    wire        mem_instr;
    reg         mem_ready;
    wire [31:0] mem_addr;
    wire [31:0] mem_wdata;
    wire [ 3:0] mem_wstrb;
    reg  [31:0] mem_rdata;

    // Look-ahead memory interface (unused, but DUT drives them)
    wire        mem_la_read;
    wire        mem_la_write;
    wire [31:0] mem_la_addr;
    wire [31:0] mem_la_wdata;
    wire [ 3:0] mem_la_wstrb;

    // Coprocessor / IRQ (unused)
    wire        pcpi_valid;
    wire [31:0] pcpi_insn;
    wire [31:0] pcpi_rs1;
    wire [31:0] pcpi_rs2;
    reg         pcpi_wr;
    reg  [31:0] pcpi_rd;
    reg         pcpi_wait;
    reg         pcpi_ready;

    reg  [31:0] irq;
    wire [31:0] eoi;

    // Trace port (unused)
    wire        trace_valid;
    wire [35:0] trace_data;

    picorv32 dut (
        .clk         (clk),
        .resetn      (resetn),
        .trap        (trap),
        .mem_valid   (mem_valid),
        .mem_instr   (mem_instr),
        .mem_ready   (mem_ready),
        .mem_addr    (mem_addr),
        .mem_wdata   (mem_wdata),
        .mem_wstrb   (mem_wstrb),
        .mem_rdata   (mem_rdata),
        .mem_la_read (mem_la_read),
        .mem_la_write(mem_la_write),
        .mem_la_addr (mem_la_addr),
        .mem_la_wdata(mem_la_wdata),
        .mem_la_wstrb(mem_la_wstrb),
        .pcpi_valid  (pcpi_valid),
        .pcpi_insn   (pcpi_insn),
        .pcpi_rs1    (pcpi_rs1),
        .pcpi_rs2    (pcpi_rs2),
        .pcpi_wr     (pcpi_wr),
        .pcpi_rd     (pcpi_rd),
        .pcpi_wait   (pcpi_wait),
        .pcpi_ready  (pcpi_ready),
        .irq         (irq),
        .eoi         (eoi),
        .trace_valid (trace_valid),
        .trace_data  (trace_data)
    );

    // 50 MHz clock (period = 20 ns)
    initial clk = 1'b0;
    always #10 clk = ~clk;

    initial begin
        $dumpfile("picorv32_tb.vcd");
        $dumpvars(0, picorv32_tb);
    end

    // Always answer the bus 1 cycle after a request, with a NOP.
    initial begin
        mem_ready  = 1'b0;
        mem_rdata  = 32'h0000_0013;  // addi x0, x0, 0  (RISC-V NOP)
        pcpi_wr    = 1'b0;
        pcpi_rd    = 32'h0;
        pcpi_wait  = 1'b0;
        pcpi_ready = 1'b0;
        irq        = 32'h0;
    end

    always @(posedge clk) begin
        mem_ready <= mem_valid && !mem_ready;
    end

    // Reset and run 100 cycles
    initial begin
        resetn = 1'b0;
        repeat (4) @(posedge clk);
        resetn = 1'b1;
        repeat (100) @(posedge clk);
        if (trap)
            $display("FAIL: core trapped during smoke run");
        else
            $display("PASS: picorv32 ran 100 cycles without trap");
        $finish;
    end

endmodule

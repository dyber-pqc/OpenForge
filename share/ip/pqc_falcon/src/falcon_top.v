// =====================================================================
// Falcon-512 - AXI4-Lite wrapper
// ---------------------------------------------------------------------
// SKELETON module for OpenForge. Replace inner logic with real impl.
//
// Standard:    NIST Round 3 alternate (informal)
// Algorithm:   Falcon-512
// Security:    NIST Level 1
// Public key:  897 bytes
// Secret key:  1281 bytes
// Signature:   666 bytes (typical)
// Note:        Falcon uses floating-point sampling - real implementation
//              requires constant-time Gaussian sampler.
// =====================================================================

`timescale 1ns / 1ps

module falcon_top #(
    parameter AXI_ADDR_WIDTH = 13,
    parameter AXI_DATA_WIDTH = 32
) (
    input  wire                       axi_aclk,
    input  wire                       axi_aresetn,

    input  wire [AXI_ADDR_WIDTH-1:0]  awaddr,
    input  wire [2:0]                 awprot,
    input  wire                       awvalid,
    output reg                        awready,
    input  wire [AXI_DATA_WIDTH-1:0]  wdata,
    input  wire [(AXI_DATA_WIDTH/8)-1:0] wstrb,
    input  wire                       wvalid,
    output reg                        wready,
    output reg  [1:0]                 bresp,
    output reg                        bvalid,
    input  wire                       bready,

    input  wire [AXI_ADDR_WIDTH-1:0]  araddr,
    input  wire [2:0]                 arprot,
    input  wire                       arvalid,
    output reg                        arready,
    output reg  [AXI_DATA_WIDTH-1:0]  rdata,
    output reg  [1:0]                 rresp,
    output reg                        rvalid,
    input  wire                       rready,

    output wire                       irq,
    output wire                       busy,
    output wire                       done,
    output wire                       error
);

    // -----------------------------------------------------------------
    // Register map (byte offsets)
    // -----------------------------------------------------------------
    // 0x0000: CTRL    - [0]=keygen, [1]=sign, [2]=verify, [3]=clear,
    //                   [4]=irq_en, [5]=det_mode (deterministic sign)
    // 0x0004: STATUS  - [0]=busy, [1]=done, [2]=error, [3]=verify_ok,
    //                   [4]=sampler_ready
    // 0x0008: VERSION - 32'h0FA1_0512 (Falcon-512)
    // 0x000C: IRQ_EN
    // 0x0010: MSG_LEN
    // 0x0014: SIG_LEN (output - actual signature length)
    // 0x0020-0x03A1: PUBLIC_KEY (897 bytes)
    // 0x03B0-0x08B1: SECRET_KEY (1281 bytes)
    // 0x08C0-0x18BF: MESSAGE (4096 bytes max)
    // 0x18C0-0x1B59: SIGNATURE (666 bytes)
    // -----------------------------------------------------------------

    localparam ADDR_CTRL       = 13'h0000;
    localparam ADDR_STATUS     = 13'h0004;
    localparam ADDR_VERSION    = 13'h0008;
    localparam ADDR_IRQ_EN     = 13'h000C;
    localparam ADDR_MSG_LEN    = 13'h0010;
    localparam ADDR_SIG_LEN    = 13'h0014;
    localparam ADDR_PUBLIC_KEY = 13'h0020;
    localparam ADDR_SECRET_KEY = 13'h03B0;
    localparam ADDR_MESSAGE    = 13'h08C0;
    localparam ADDR_SIGNATURE  = 13'h18C0;

    reg [31:0] ctrl_reg;
    reg [31:0] status_reg;
    reg [31:0] irq_en_reg;
    reg [31:0] version_reg;
    reg [31:0] msg_len_reg;
    reg [31:0] sig_len_reg;

    initial begin
        version_reg = 32'h0FA1_0512;
        ctrl_reg    = 32'h0;
        status_reg  = 32'h0;
        irq_en_reg  = 32'h0;
        msg_len_reg = 32'h0;
        sig_len_reg = 32'h0;
    end

    // Memory windows (stub)
    reg [31:0] pk_mem  [0:31];
    reg [31:0] sk_mem  [0:31];
    reg [31:0] msg_mem [0:31];
    reg [31:0] sig_mem [0:31];

    integer i;
    initial begin
        for (i = 0; i < 32; i = i + 1) begin
            pk_mem[i]  = 32'h0;
            sk_mem[i]  = 32'h0;
            msg_mem[i] = 32'h0;
            sig_mem[i] = 32'h0;
        end
    end

    // -----------------------------------------------------------------
    // FSM
    // -----------------------------------------------------------------
    // Falcon-512 has dominant FFT/NTRU and Gaussian sampler stages.
    localparam STATE_IDLE        = 4'd0;
    localparam STATE_KEYGEN_FFT  = 4'd1;
    localparam STATE_KEYGEN_NTRU = 4'd2;
    localparam STATE_SIGN_HASH   = 4'd3;
    localparam STATE_SIGN_SAMPLE = 4'd4;
    localparam STATE_SIGN_FINAL  = 4'd5;
    localparam STATE_VERIFY      = 4'd6;
    localparam STATE_DONE        = 4'd7;
    localparam STATE_ERROR       = 4'd8;

    reg [3:0]  state;
    reg [31:0] cycle_counter;

    // Estimated cycle counts
    localparam CYCLES_KEYGEN_FFT  = 32'd5_000_000;
    localparam CYCLES_KEYGEN_NTRU = 32'd5_000_000;
    localparam CYCLES_SIGN_HASH   = 32'd5_000;
    localparam CYCLES_SIGN_SAMPLE = 32'd1_000_000;
    localparam CYCLES_SIGN_FINAL  = 32'd200_000;
    localparam CYCLES_VERIFY      = 32'd80_000;

    always @(posedge axi_aclk or negedge axi_aresetn) begin
        if (!axi_aresetn) begin
            state         <= STATE_IDLE;
            cycle_counter <= 32'h0;
            status_reg    <= 32'h0;
        end else begin
            case (state)
                STATE_IDLE: begin
                    cycle_counter <= 32'h0;
                    status_reg[0] <= 1'b0;
                    status_reg[1] <= 1'b0;
                    status_reg[2] <= 1'b0;
                    status_reg[4] <= 1'b1;  // sampler always ready in stub
                    if (ctrl_reg[0]) state <= STATE_KEYGEN_FFT;
                    else if (ctrl_reg[1]) state <= STATE_SIGN_HASH;
                    else if (ctrl_reg[2]) state <= STATE_VERIFY;
                end
                STATE_KEYGEN_FFT: begin
                    status_reg[0] <= 1'b1;
                    cycle_counter <= cycle_counter + 1;
                    if (cycle_counter >= CYCLES_KEYGEN_FFT) begin
                        cycle_counter <= 32'h0;
                        state         <= STATE_KEYGEN_NTRU;
                    end
                end
                STATE_KEYGEN_NTRU: begin
                    cycle_counter <= cycle_counter + 1;
                    if (cycle_counter >= CYCLES_KEYGEN_NTRU) state <= STATE_DONE;
                end
                STATE_SIGN_HASH: begin
                    status_reg[0] <= 1'b1;
                    cycle_counter <= cycle_counter + 1;
                    if (cycle_counter >= CYCLES_SIGN_HASH) begin
                        cycle_counter <= 32'h0;
                        state         <= STATE_SIGN_SAMPLE;
                    end
                end
                STATE_SIGN_SAMPLE: begin
                    cycle_counter <= cycle_counter + 1;
                    if (cycle_counter >= CYCLES_SIGN_SAMPLE) begin
                        cycle_counter <= 32'h0;
                        state         <= STATE_SIGN_FINAL;
                    end
                end
                STATE_SIGN_FINAL: begin
                    cycle_counter <= cycle_counter + 1;
                    if (cycle_counter >= CYCLES_SIGN_FINAL) begin
                        sig_len_reg <= 32'd666;
                        state       <= STATE_DONE;
                    end
                end
                STATE_VERIFY: begin
                    status_reg[0] <= 1'b1;
                    cycle_counter <= cycle_counter + 1;
                    if (cycle_counter >= CYCLES_VERIFY) begin
                        status_reg[3] <= 1'b1;
                        state         <= STATE_DONE;
                    end
                end
                STATE_DONE: begin
                    status_reg[0] <= 1'b0;
                    status_reg[1] <= 1'b1;
                    if (ctrl_reg[3]) state <= STATE_IDLE;
                end
                STATE_ERROR: begin
                    status_reg[2] <= 1'b1;
                    if (ctrl_reg[3]) state <= STATE_IDLE;
                end
                default: state <= STATE_IDLE;
            endcase
        end
    end

    // -----------------------------------------------------------------
    // AXI4-Lite write channel
    // -----------------------------------------------------------------
    reg [AXI_ADDR_WIDTH-1:0] aw_addr_reg;
    reg                      aw_addr_valid;

    always @(posedge axi_aclk or negedge axi_aresetn) begin
        if (!axi_aresetn) begin
            awready       <= 1'b0;
            wready        <= 1'b0;
            bresp         <= 2'b00;
            bvalid        <= 1'b0;
            aw_addr_reg   <= {AXI_ADDR_WIDTH{1'b0}};
            aw_addr_valid <= 1'b0;
            ctrl_reg      <= 32'h0;
            irq_en_reg    <= 32'h0;
            msg_len_reg   <= 32'h0;
        end else begin
            if (!aw_addr_valid && awvalid) begin
                awready       <= 1'b1;
                aw_addr_reg   <= awaddr;
                aw_addr_valid <= 1'b1;
            end else begin
                awready <= 1'b0;
            end

            if (aw_addr_valid && wvalid && !bvalid) begin
                wready <= 1'b1;
                case (aw_addr_reg)
                    ADDR_CTRL:    ctrl_reg    <= wdata;
                    ADDR_IRQ_EN:  irq_en_reg  <= wdata;
                    ADDR_MSG_LEN: msg_len_reg <= wdata;
                    default: begin
                        if (aw_addr_reg >= ADDR_PUBLIC_KEY && aw_addr_reg < ADDR_SECRET_KEY)
                            pk_mem[((aw_addr_reg - ADDR_PUBLIC_KEY) >> 2) & 5'h1F] <= wdata;
                        else if (aw_addr_reg >= ADDR_SECRET_KEY && aw_addr_reg < ADDR_MESSAGE)
                            sk_mem[((aw_addr_reg - ADDR_SECRET_KEY) >> 2) & 5'h1F] <= wdata;
                        else if (aw_addr_reg >= ADDR_MESSAGE && aw_addr_reg < ADDR_SIGNATURE)
                            msg_mem[((aw_addr_reg - ADDR_MESSAGE) >> 2) & 5'h1F] <= wdata;
                        else
                            sig_mem[((aw_addr_reg - ADDR_SIGNATURE) >> 2) & 5'h1F] <= wdata;
                    end
                endcase
                bvalid        <= 1'b1;
                bresp         <= 2'b00;
                aw_addr_valid <= 1'b0;
            end else begin
                wready <= 1'b0;
            end

            if (bvalid && bready) bvalid <= 1'b0;
        end
    end

    // -----------------------------------------------------------------
    // AXI4-Lite read channel
    // -----------------------------------------------------------------
    reg [AXI_ADDR_WIDTH-1:0] ar_addr_reg;

    always @(posedge axi_aclk or negedge axi_aresetn) begin
        if (!axi_aresetn) begin
            arready     <= 1'b0;
            rdata       <= {AXI_DATA_WIDTH{1'b0}};
            rresp       <= 2'b00;
            rvalid      <= 1'b0;
            ar_addr_reg <= {AXI_ADDR_WIDTH{1'b0}};
        end else begin
            if (arvalid && !arready && !rvalid) begin
                arready     <= 1'b1;
                ar_addr_reg <= araddr;
            end else begin
                arready <= 1'b0;
            end

            if (arready) begin
                rvalid <= 1'b1;
                rresp  <= 2'b00;
                case (ar_addr_reg)
                    ADDR_CTRL:    rdata <= ctrl_reg;
                    ADDR_STATUS:  rdata <= status_reg;
                    ADDR_VERSION: rdata <= version_reg;
                    ADDR_IRQ_EN:  rdata <= irq_en_reg;
                    ADDR_MSG_LEN: rdata <= msg_len_reg;
                    ADDR_SIG_LEN: rdata <= sig_len_reg;
                    default: begin
                        if (ar_addr_reg >= ADDR_PUBLIC_KEY && ar_addr_reg < ADDR_SECRET_KEY)
                            rdata <= pk_mem[((ar_addr_reg - ADDR_PUBLIC_KEY) >> 2) & 5'h1F];
                        else if (ar_addr_reg >= ADDR_SECRET_KEY && ar_addr_reg < ADDR_MESSAGE)
                            rdata <= sk_mem[((ar_addr_reg - ADDR_SECRET_KEY) >> 2) & 5'h1F];
                        else if (ar_addr_reg >= ADDR_MESSAGE && ar_addr_reg < ADDR_SIGNATURE)
                            rdata <= msg_mem[((ar_addr_reg - ADDR_MESSAGE) >> 2) & 5'h1F];
                        else
                            rdata <= sig_mem[((ar_addr_reg - ADDR_SIGNATURE) >> 2) & 5'h1F];
                    end
                endcase
            end

            if (rvalid && rready) rvalid <= 1'b0;
        end
    end

    assign busy  = (state != STATE_IDLE) && (state != STATE_DONE);
    assign done  = (state == STATE_DONE);
    assign error = (state == STATE_ERROR);
    assign irq   = done & irq_en_reg[0];

endmodule

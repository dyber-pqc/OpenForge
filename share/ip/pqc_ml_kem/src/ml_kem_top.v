// =====================================================================
// ML-KEM-768 (NIST FIPS 203 / Kyber768) - AXI4-Lite wrapper
// ---------------------------------------------------------------------
// This is a SKELETON module for OpenForge. Replace inner cryptographic
// logic with a real implementation when integrating into a product.
//
// Standard:    NIST FIPS 203 (August 2024)
// Algorithm:   ML-KEM-768
// Security:    NIST Level 3 (192-bit equivalent)
// Public key:  1184 bytes
// Secret key:  2400 bytes
// Ciphertext:  1088 bytes
// Shared sec:  32 bytes
// =====================================================================

`timescale 1ns / 1ps

module ml_kem_top #(
    parameter AXI_ADDR_WIDTH = 12,
    parameter AXI_DATA_WIDTH = 32
) (
    // Clock & reset
    input  wire                       axi_aclk,
    input  wire                       axi_aresetn,

    // AXI4-Lite Write Address
    input  wire [AXI_ADDR_WIDTH-1:0]  awaddr,
    input  wire [2:0]                 awprot,
    input  wire                       awvalid,
    output reg                        awready,

    // AXI4-Lite Write Data
    input  wire [AXI_DATA_WIDTH-1:0]  wdata,
    input  wire [(AXI_DATA_WIDTH/8)-1:0] wstrb,
    input  wire                       wvalid,
    output reg                        wready,

    // AXI4-Lite Write Response
    output reg  [1:0]                 bresp,
    output reg                        bvalid,
    input  wire                       bready,

    // AXI4-Lite Read Address
    input  wire [AXI_ADDR_WIDTH-1:0]  araddr,
    input  wire [2:0]                 arprot,
    input  wire                       arvalid,
    output reg                        arready,

    // AXI4-Lite Read Data
    output reg  [AXI_DATA_WIDTH-1:0]  rdata,
    output reg  [1:0]                 rresp,
    output reg                        rvalid,
    input  wire                       rready,

    // Status outputs
    output wire                       irq,
    output wire                       busy,
    output wire                       done,
    output wire                       error
);

    // -----------------------------------------------------------------
    // Register map (byte offsets)
    // -----------------------------------------------------------------
    // 0x000: CTRL    - [0]=start_keygen, [1]=start_encaps,
    //                  [2]=start_decaps, [3]=clear, [4]=irq_enable
    // 0x004: STATUS  - [0]=busy, [1]=done, [2]=error, [3]=zeroized
    // 0x008: VERSION - 32'h0203_0768 (FIPS 203, ML-KEM-768)
    // 0x00C: IRQ_EN
    // 0x010-0x4AF: PUBLIC_KEY (1184 bytes)
    // 0x4B0-0xE0F: SECRET_KEY (2400 bytes)
    // 0xE10-0x124F: CIPHERTEXT (1088 bytes)
    // 0x1250-0x126F: SHARED_SECRET (32 bytes)
    // 0x1270-0x128F: SEED (32 bytes)
    // -----------------------------------------------------------------

    localparam ADDR_CTRL          = 12'h000;
    localparam ADDR_STATUS        = 12'h004;
    localparam ADDR_VERSION       = 12'h008;
    localparam ADDR_IRQ_EN        = 12'h00C;
    localparam ADDR_PUBLIC_KEY    = 12'h010;
    localparam ADDR_SECRET_KEY    = 12'h4B0;
    localparam ADDR_CIPHERTEXT    = 12'hE10;

    // -----------------------------------------------------------------
    // Control / status registers
    // -----------------------------------------------------------------
    reg  [31:0] ctrl_reg;
    reg  [31:0] status_reg;
    reg  [31:0] irq_en_reg;
    reg  [31:0] version_reg;

    initial begin
        version_reg = 32'h0203_0768;
        ctrl_reg    = 32'h0;
        status_reg  = 32'h0;
        irq_en_reg  = 32'h0;
    end

    // -----------------------------------------------------------------
    // Memory-mapped buffers (modeled as small register banks for stub)
    // -----------------------------------------------------------------
    // Real implementation would use BRAM. Stub uses small windows.
    reg  [31:0] pubkey_mem  [0:15];
    reg  [31:0] seckey_mem  [0:15];
    reg  [31:0] ct_mem      [0:15];
    reg  [31:0] ss_mem      [0:7];
    reg  [31:0] seed_mem    [0:7];

    integer i;
    initial begin
        for (i = 0; i < 16; i = i + 1) begin
            pubkey_mem[i] = 32'h0;
            seckey_mem[i] = 32'h0;
            ct_mem[i]     = 32'h0;
        end
        for (i = 0; i < 8; i = i + 1) begin
            ss_mem[i]   = 32'h0;
            seed_mem[i] = 32'h0;
        end
    end

    // -----------------------------------------------------------------
    // Main FSM
    // -----------------------------------------------------------------
    localparam STATE_IDLE   = 3'd0;
    localparam STATE_KEYGEN = 3'd1;
    localparam STATE_ENCAPS = 3'd2;
    localparam STATE_DECAPS = 3'd3;
    localparam STATE_DONE   = 3'd4;
    localparam STATE_ERROR  = 3'd5;

    reg [2:0]  state;
    reg [31:0] cycle_counter;

    // Estimated cycle counts (rough hardware reference)
    localparam CYCLES_KEYGEN = 32'd50_000;
    localparam CYCLES_ENCAPS = 32'd60_000;
    localparam CYCLES_DECAPS = 32'd65_000;

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
                    if (ctrl_reg[0]) state <= STATE_KEYGEN;
                    else if (ctrl_reg[1]) state <= STATE_ENCAPS;
                    else if (ctrl_reg[2]) state <= STATE_DECAPS;
                end
                STATE_KEYGEN: begin
                    status_reg[0] <= 1'b1;
                    cycle_counter <= cycle_counter + 1;
                    if (cycle_counter >= CYCLES_KEYGEN) state <= STATE_DONE;
                end
                STATE_ENCAPS: begin
                    status_reg[0] <= 1'b1;
                    cycle_counter <= cycle_counter + 1;
                    if (cycle_counter >= CYCLES_ENCAPS) state <= STATE_DONE;
                end
                STATE_DECAPS: begin
                    status_reg[0] <= 1'b1;
                    cycle_counter <= cycle_counter + 1;
                    if (cycle_counter >= CYCLES_DECAPS) state <= STATE_DONE;
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
        end else begin
            // Address phase
            if (!aw_addr_valid && awvalid) begin
                awready       <= 1'b1;
                aw_addr_reg   <= awaddr;
                aw_addr_valid <= 1'b1;
            end else begin
                awready <= 1'b0;
            end

            // Data phase
            if (aw_addr_valid && wvalid && !bvalid) begin
                wready <= 1'b1;
                case (aw_addr_reg)
                    ADDR_CTRL:   ctrl_reg   <= wdata;
                    ADDR_IRQ_EN: irq_en_reg <= wdata;
                    default: begin
                        // Write into one of the memories based on address range
                        if (aw_addr_reg >= ADDR_PUBLIC_KEY && aw_addr_reg < ADDR_SECRET_KEY)
                            pubkey_mem[(aw_addr_reg - ADDR_PUBLIC_KEY) >> 2] <= wdata;
                        else if (aw_addr_reg >= ADDR_SECRET_KEY && aw_addr_reg < ADDR_CIPHERTEXT)
                            seckey_mem[(aw_addr_reg - ADDR_SECRET_KEY) >> 2] <= wdata;
                        else
                            ct_mem[(aw_addr_reg - ADDR_CIPHERTEXT) >> 2] <= wdata;
                    end
                endcase
                bvalid        <= 1'b1;
                bresp         <= 2'b00;
                aw_addr_valid <= 1'b0;
            end else begin
                wready <= 1'b0;
            end

            // Response acknowledged
            if (bvalid && bready) begin
                bvalid <= 1'b0;
            end
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
                    default: begin
                        if (ar_addr_reg >= ADDR_PUBLIC_KEY && ar_addr_reg < ADDR_SECRET_KEY)
                            rdata <= pubkey_mem[(ar_addr_reg - ADDR_PUBLIC_KEY) >> 2];
                        else if (ar_addr_reg >= ADDR_SECRET_KEY && ar_addr_reg < ADDR_CIPHERTEXT)
                            rdata <= seckey_mem[(ar_addr_reg - ADDR_SECRET_KEY) >> 2];
                        else
                            rdata <= ct_mem[(ar_addr_reg - ADDR_CIPHERTEXT) >> 2];
                    end
                endcase
            end

            if (rvalid && rready) begin
                rvalid <= 1'b0;
            end
        end
    end

    // -----------------------------------------------------------------
    // Status outputs
    // -----------------------------------------------------------------
    assign busy  = (state != STATE_IDLE) && (state != STATE_DONE);
    assign done  = (state == STATE_DONE);
    assign error = (state == STATE_ERROR);
    assign irq   = done & irq_en_reg[0];

endmodule

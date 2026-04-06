`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////
// OpenForge EDA - AXI4-Lite Crossbar (1 Master, N Slaves)
//
// Features:
//   - Single master to N slave address-based routing
//   - Configurable base addresses and address masks per slave
//   - Supports concurrent read and write channels
//   - Default slave response (DECERR) for unmapped addresses
//   - Fully synthesizable, no latches
//
// Parameters:
//   NUM_SLAVES     - Number of slave ports (2-8)
//   ADDR_WIDTH     - Address bus width
//   DATA_WIDTH     - Data bus width (32)
//   BASE_ADDR      - Packed array of base addresses per slave
//   ADDR_MASK      - Packed array of address masks per slave
//
// Routing:
//   For each slave i, address matches if:
//     (addr & ADDR_MASK[i]) == BASE_ADDR[i]
//   First matching slave wins (priority encoder).
//
// Copyright (c) 2024-2026 OpenForge Contributors
// SPDX-License-Identifier: Apache-2.0
//////////////////////////////////////////////////////////////////////////////

module axi_lite_xbar #(
    parameter NUM_SLAVES  = 4,
    parameter ADDR_WIDTH  = 32,
    parameter DATA_WIDTH  = 32,
    // Packed base addresses: {slave[N-1], ..., slave[1], slave[0]}
    parameter [NUM_SLAVES*ADDR_WIDTH-1:0] BASE_ADDR = {
        32'h0000_3000,   // Slave 3
        32'h0000_2000,   // Slave 2
        32'h0000_1000,   // Slave 1
        32'h0000_0000    // Slave 0
    },
    // Packed address masks
    parameter [NUM_SLAVES*ADDR_WIDTH-1:0] ADDR_MASK = {
        32'hFFFF_F000,
        32'hFFFF_F000,
        32'hFFFF_F000,
        32'hFFFF_F000
    }
) (
    input  wire                             clk,
    input  wire                             rst_n,

    // =====================================================================
    // Master port (upstream)
    // =====================================================================
    // Write Address
    input  wire [ADDR_WIDTH-1:0]            m_axi_awaddr,
    input  wire                             m_axi_awvalid,
    output reg                              m_axi_awready,

    // Write Data
    input  wire [DATA_WIDTH-1:0]            m_axi_wdata,
    input  wire [(DATA_WIDTH/8)-1:0]        m_axi_wstrb,
    input  wire                             m_axi_wvalid,
    output reg                              m_axi_wready,

    // Write Response
    output reg  [1:0]                       m_axi_bresp,
    output reg                              m_axi_bvalid,
    input  wire                             m_axi_bready,

    // Read Address
    input  wire [ADDR_WIDTH-1:0]            m_axi_araddr,
    input  wire                             m_axi_arvalid,
    output reg                              m_axi_arready,

    // Read Data
    output reg  [DATA_WIDTH-1:0]            m_axi_rdata,
    output reg  [1:0]                       m_axi_rresp,
    output reg                              m_axi_rvalid,
    input  wire                             m_axi_rready,

    // =====================================================================
    // Slave ports (downstream, active-low active signals active only
    // for the selected slave)
    // =====================================================================
    // Write Address
    output reg  [NUM_SLAVES*ADDR_WIDTH-1:0] s_axi_awaddr,
    output reg  [NUM_SLAVES-1:0]            s_axi_awvalid,
    input  wire [NUM_SLAVES-1:0]            s_axi_awready,

    // Write Data
    output reg  [NUM_SLAVES*DATA_WIDTH-1:0] s_axi_wdata,
    output reg  [NUM_SLAVES*(DATA_WIDTH/8)-1:0] s_axi_wstrb,
    output reg  [NUM_SLAVES-1:0]            s_axi_wvalid,
    input  wire [NUM_SLAVES-1:0]            s_axi_wready,

    // Write Response
    input  wire [NUM_SLAVES*2-1:0]          s_axi_bresp,
    input  wire [NUM_SLAVES-1:0]            s_axi_bvalid,
    output reg  [NUM_SLAVES-1:0]            s_axi_bready,

    // Read Address
    output reg  [NUM_SLAVES*ADDR_WIDTH-1:0] s_axi_araddr,
    output reg  [NUM_SLAVES-1:0]            s_axi_arvalid,
    input  wire [NUM_SLAVES-1:0]            s_axi_arready,

    // Read Data
    input  wire [NUM_SLAVES*DATA_WIDTH-1:0] s_axi_rdata,
    input  wire [NUM_SLAVES*2-1:0]          s_axi_rresp,
    input  wire [NUM_SLAVES-1:0]            s_axi_rvalid,
    output reg  [NUM_SLAVES-1:0]            s_axi_rready
);

    localparam STRB_WIDTH = DATA_WIDTH / 8;

    // =========================================================================
    // Address decode - find matching slave for a given address
    // =========================================================================
    function integer addr_decode;
        input [ADDR_WIDTH-1:0] addr;
        integer s;
        begin
            addr_decode = -1; // No match (default slave / DECERR)
            for (s = 0; s < NUM_SLAVES; s = s + 1) begin
                if ((addr & ADDR_MASK[s*ADDR_WIDTH +: ADDR_WIDTH]) ==
                    BASE_ADDR[s*ADDR_WIDTH +: ADDR_WIDTH]) begin
                    addr_decode = s;
                end
            end
        end
    endfunction

    // =========================================================================
    // Write channel FSM
    // =========================================================================
    localparam W_IDLE    = 2'd0;
    localparam W_ADDR    = 2'd1;
    localparam W_DATA    = 2'd2;
    localparam W_RESP    = 2'd3;

    reg [1:0]               wr_state;
    reg [$clog2(NUM_SLAVES):0] wr_slave;  // Selected slave (-1 = none, use extra bit)
    reg                     wr_decode_err;
    reg [ADDR_WIDTH-1:0]    wr_addr_latched;

    integer wr_sel;
    integer wi;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_state       <= W_IDLE;
            wr_slave       <= 0;
            wr_decode_err  <= 1'b0;
            wr_addr_latched <= {ADDR_WIDTH{1'b0}};
            m_axi_awready  <= 1'b0;
            m_axi_wready   <= 1'b0;
            m_axi_bvalid   <= 1'b0;
            m_axi_bresp    <= 2'b00;
            for (wi = 0; wi < NUM_SLAVES; wi = wi + 1) begin
                s_axi_awvalid[wi]                       <= 1'b0;
                s_axi_awaddr[wi*ADDR_WIDTH +: ADDR_WIDTH] <= {ADDR_WIDTH{1'b0}};
                s_axi_wvalid[wi]                        <= 1'b0;
                s_axi_wdata[wi*DATA_WIDTH +: DATA_WIDTH]  <= {DATA_WIDTH{1'b0}};
                s_axi_wstrb[wi*STRB_WIDTH +: STRB_WIDTH]  <= {STRB_WIDTH{1'b0}};
                s_axi_bready[wi]                        <= 1'b0;
            end
        end else begin
            case (wr_state)
                W_IDLE: begin
                    m_axi_bvalid <= 1'b0;
                    if (m_axi_awvalid) begin
                        wr_sel = addr_decode(m_axi_awaddr);
                        wr_addr_latched <= m_axi_awaddr;
                        if (wr_sel < 0) begin
                            // Decode error: accept and return DECERR
                            m_axi_awready <= 1'b1;
                            wr_decode_err <= 1'b1;
                            wr_state      <= W_DATA;
                        end else begin
                            wr_slave      <= wr_sel[($clog2(NUM_SLAVES)):0];
                            wr_decode_err <= 1'b0;
                            // Forward address to selected slave
                            s_axi_awaddr[wr_sel*ADDR_WIDTH +: ADDR_WIDTH] <= m_axi_awaddr;
                            s_axi_awvalid[wr_sel] <= 1'b1;
                            wr_state <= W_ADDR;
                        end
                    end
                end

                W_ADDR: begin
                    // Wait for slave to accept write address
                    if (s_axi_awready[wr_slave]) begin
                        s_axi_awvalid[wr_slave] <= 1'b0;
                        m_axi_awready <= 1'b1;
                        wr_state      <= W_DATA;
                    end
                end

                W_DATA: begin
                    m_axi_awready <= 1'b0;
                    if (m_axi_wvalid) begin
                        if (wr_decode_err) begin
                            // Consume write data, respond with DECERR
                            m_axi_wready <= 1'b1;
                            m_axi_bresp  <= 2'b11; // DECERR
                            m_axi_bvalid <= 1'b1;
                            wr_state     <= W_RESP;
                        end else begin
                            // Forward write data to slave
                            s_axi_wdata[wr_slave*DATA_WIDTH +: DATA_WIDTH] <= m_axi_wdata;
                            s_axi_wstrb[wr_slave*STRB_WIDTH +: STRB_WIDTH] <= m_axi_wstrb;
                            s_axi_wvalid[wr_slave] <= 1'b1;
                            if (s_axi_wready[wr_slave]) begin
                                s_axi_wvalid[wr_slave] <= 1'b0;
                                m_axi_wready <= 1'b1;
                                // Wait for slave response
                                s_axi_bready[wr_slave] <= 1'b1;
                                wr_state <= W_RESP;
                            end
                        end
                    end
                end

                W_RESP: begin
                    m_axi_wready <= 1'b0;
                    if (wr_decode_err) begin
                        if (m_axi_bready) begin
                            m_axi_bvalid  <= 1'b0;
                            wr_decode_err <= 1'b0;
                            wr_state      <= W_IDLE;
                        end
                    end else begin
                        // Wait for slave write response
                        if (s_axi_bvalid[wr_slave]) begin
                            s_axi_bready[wr_slave] <= 1'b0;
                            m_axi_bresp  <= s_axi_bresp[wr_slave*2 +: 2];
                            m_axi_bvalid <= 1'b1;
                            if (m_axi_bready) begin
                                m_axi_bvalid <= 1'b0;
                                wr_state     <= W_IDLE;
                            end
                        end
                    end
                end

                default: wr_state <= W_IDLE;
            endcase
        end
    end

    // =========================================================================
    // Read channel FSM
    // =========================================================================
    localparam R_IDLE    = 2'd0;
    localparam R_ADDR    = 2'd1;
    localparam R_DATA    = 2'd2;
    localparam R_RESP    = 2'd3;

    reg [1:0]               rd_state;
    reg [$clog2(NUM_SLAVES):0] rd_slave;
    reg                     rd_decode_err;

    integer rd_sel;
    integer ri;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rd_state      <= R_IDLE;
            rd_slave      <= 0;
            rd_decode_err <= 1'b0;
            m_axi_arready <= 1'b0;
            m_axi_rvalid  <= 1'b0;
            m_axi_rdata   <= {DATA_WIDTH{1'b0}};
            m_axi_rresp   <= 2'b00;
            for (ri = 0; ri < NUM_SLAVES; ri = ri + 1) begin
                s_axi_arvalid[ri]                       <= 1'b0;
                s_axi_araddr[ri*ADDR_WIDTH +: ADDR_WIDTH] <= {ADDR_WIDTH{1'b0}};
                s_axi_rready[ri]                        <= 1'b0;
            end
        end else begin
            case (rd_state)
                R_IDLE: begin
                    m_axi_rvalid <= 1'b0;
                    if (m_axi_arvalid) begin
                        rd_sel = addr_decode(m_axi_araddr);
                        if (rd_sel < 0) begin
                            m_axi_arready <= 1'b1;
                            rd_decode_err <= 1'b1;
                            rd_state      <= R_DATA;
                        end else begin
                            rd_slave      <= rd_sel[($clog2(NUM_SLAVES)):0];
                            rd_decode_err <= 1'b0;
                            s_axi_araddr[rd_sel*ADDR_WIDTH +: ADDR_WIDTH] <= m_axi_araddr;
                            s_axi_arvalid[rd_sel] <= 1'b1;
                            rd_state <= R_ADDR;
                        end
                    end
                end

                R_ADDR: begin
                    if (s_axi_arready[rd_slave]) begin
                        s_axi_arvalid[rd_slave] <= 1'b0;
                        m_axi_arready <= 1'b1;
                        s_axi_rready[rd_slave] <= 1'b1;
                        rd_state <= R_DATA;
                    end
                end

                R_DATA: begin
                    m_axi_arready <= 1'b0;
                    if (rd_decode_err) begin
                        // Return DECERR with zero data
                        m_axi_rdata   <= {DATA_WIDTH{1'b0}};
                        m_axi_rresp   <= 2'b11; // DECERR
                        m_axi_rvalid  <= 1'b1;
                        rd_decode_err <= 1'b0;
                        rd_state      <= R_RESP;
                    end else if (s_axi_rvalid[rd_slave]) begin
                        s_axi_rready[rd_slave] <= 1'b0;
                        m_axi_rdata  <= s_axi_rdata[rd_slave*DATA_WIDTH +: DATA_WIDTH];
                        m_axi_rresp  <= s_axi_rresp[rd_slave*2 +: 2];
                        m_axi_rvalid <= 1'b1;
                        rd_state     <= R_RESP;
                    end
                end

                R_RESP: begin
                    if (m_axi_rvalid && m_axi_rready) begin
                        m_axi_rvalid <= 1'b0;
                        rd_state     <= R_IDLE;
                    end
                end

                default: rd_state <= R_IDLE;
            endcase
        end
    end

endmodule

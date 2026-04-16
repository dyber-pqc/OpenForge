"""AXI / APB / AHB protocol assertion monitor generators.

Each generator returns a synthesizable (or Verilator-friendly) SystemVerilog
``bind``-able module that contains:

- clock/reset latching
- handshake stability assertions (``VALID`` held until ``READY``)
- ``X``-propagation checks on control signals
- timeout cycle counters with a ``TIMEOUT_CYCLES`` parameter
- coverpoints for handshake events

The emitted modules deliberately use a subset of SVA supported by
Verilator (``assert property``, ``cover property``, ``@(posedge clk)``),
avoiding features such as ``disable iff`` with async conditions beyond
reset.
"""

from __future__ import annotations

_HEADER = """// =============================================================
// {name}
// OpenForge auto-generated AXI/APB/AHB protocol monitor
// =============================================================
`default_nettype none
"""


def _proto_common(module_name: str, prefix: str) -> list[str]:
    lo = prefix.lower()
    return [
        _HEADER.format(name=module_name),
        f"module {module_name} #(",
        "    parameter int ADDR_WIDTH    = 32,",
        "    parameter int DATA_WIDTH    = 32,",
        "    parameter int TIMEOUT_CYCLES = 1024",
        ") (",
        f"    input  wire                   {lo}_aclk,",
        f"    input  wire                   {lo}_aresetn",
        ");",
        "",
        "    // Cycle counter for timeout assertions",
        "    integer _cycle;",
        f"    always @(posedge {lo}_aclk or negedge {lo}_aresetn) begin",
        f"        if (!{lo}_aresetn) _cycle <= 0;",
        "        else                _cycle <= _cycle + 1;",
        "    end",
        "",
    ]


def _handshake_asserts(
    chan: str, valid: str, ready: str, clk: str, rst: str
) -> list[str]:
    lo = chan.lower()
    return [
        f"    // {chan}: VALID must remain high until READY",
        f"    property p_{lo}_stable;",
        f"        @(posedge {clk}) disable iff (!{rst})",
        f"        ({valid} && !{ready}) |=> {valid};",
        "    endproperty",
        f"    a_{lo}_stable: assert property (p_{lo}_stable);",
        "",
        f"    // {chan}: VALID must not be X",
        f"    property p_{lo}_no_x;",
        f"        @(posedge {clk}) disable iff (!{rst}) !$isunknown({valid});",
        "    endproperty",
        f"    a_{lo}_no_x: assert property (p_{lo}_no_x);",
        "",
        f"    // {chan}: READY must arrive within TIMEOUT_CYCLES",
        f"    integer _cnt_{lo};",
        f"    always @(posedge {clk} or negedge {rst}) begin",
        f"        if (!{rst}) _cnt_{lo} <= 0;",
        f"        else if ({valid} && !{ready}) _cnt_{lo} <= _cnt_{lo} + 1;",
        f"        else _cnt_{lo} <= 0;",
        "    end",
        f"    property p_{lo}_timeout;",
        f"        @(posedge {clk}) disable iff (!{rst})",
        f"        (_cnt_{lo} < TIMEOUT_CYCLES);",
        "    endproperty",
        f"    a_{lo}_timeout: assert property (p_{lo}_timeout);",
        "",
        f"    // Coverage: completed handshakes on {chan}",
        f"    cov_{lo}_hs: cover property (",
        f"        @(posedge {clk}) disable iff (!{rst}) ({valid} && {ready})",
        "    );",
        "",
    ]


def generate_axi4_lite_monitor(prefix: str = "S_AXI") -> str:
    lo = prefix.lower()
    clk = f"{lo}_aclk"
    rst = f"{lo}_aresetn"
    name = f"{prefix.lower()}_axi4lite_monitor"
    lines = _proto_common(name, prefix)

    lines += [
        "    // External AXI4-Lite signals (tap with bind)",
        f"    input  wire [ADDR_WIDTH-1:0]  {lo}_awaddr;",
        f"    input  wire                   {lo}_awvalid;",
        f"    input  wire                   {lo}_awready;",
        f"    input  wire [DATA_WIDTH-1:0]  {lo}_wdata;",
        f"    input  wire                   {lo}_wvalid;",
        f"    input  wire                   {lo}_wready;",
        f"    input  wire [1:0]             {lo}_bresp;",
        f"    input  wire                   {lo}_bvalid;",
        f"    input  wire                   {lo}_bready;",
        f"    input  wire [ADDR_WIDTH-1:0]  {lo}_araddr;",
        f"    input  wire                   {lo}_arvalid;",
        f"    input  wire                   {lo}_arready;",
        f"    input  wire [DATA_WIDTH-1:0]  {lo}_rdata;",
        f"    input  wire [1:0]             {lo}_rresp;",
        f"    input  wire                   {lo}_rvalid;",
        f"    input  wire                   {lo}_rready;",
        "",
    ]
    lines += _handshake_asserts("AW", f"{lo}_awvalid", f"{lo}_awready", clk, rst)
    lines += _handshake_asserts("W",  f"{lo}_wvalid",  f"{lo}_wready",  clk, rst)
    lines += _handshake_asserts("B",  f"{lo}_bvalid",  f"{lo}_bready",  clk, rst)
    lines += _handshake_asserts("AR", f"{lo}_arvalid", f"{lo}_arready", clk, rst)
    lines += _handshake_asserts("R",  f"{lo}_rvalid",  f"{lo}_rready",  clk, rst)

    # Ordering: BRESP requires a preceding W transaction
    lines += [
        "    integer _w_done, _b_done;",
        f"    always @(posedge {clk} or negedge {rst}) begin",
        f"        if (!{rst}) begin _w_done <= 0; _b_done <= 0; end",
        "        else begin",
        f"            if ({lo}_wvalid && {lo}_wready) _w_done <= _w_done + 1;",
        f"            if ({lo}_bvalid && {lo}_bready) _b_done <= _b_done + 1;",
        "        end",
        "    end",
        "    property p_b_after_w;",
        f"        @(posedge {clk}) disable iff (!{rst}) (_b_done <= _w_done);",
        "    endproperty",
        "    a_b_after_w: assert property (p_b_after_w);",
        "",
        "endmodule",
        "`default_nettype wire",
        "",
    ]
    return "\n".join(lines)


def generate_axi4_full_monitor(prefix: str = "S_AXI") -> str:
    lo = prefix.lower()
    clk = f"{lo}_aclk"
    rst = f"{lo}_aresetn"
    name = f"{prefix.lower()}_axi4_full_monitor"
    lines = _proto_common(name, prefix)
    lines += [
        f"    input  wire [ADDR_WIDTH-1:0]  {lo}_awaddr;",
        f"    input  wire [7:0]             {lo}_awlen;",
        f"    input  wire [2:0]             {lo}_awsize;",
        f"    input  wire [1:0]             {lo}_awburst;",
        f"    input  wire                   {lo}_awvalid;",
        f"    input  wire                   {lo}_awready;",
        f"    input  wire [DATA_WIDTH-1:0]  {lo}_wdata;",
        f"    input  wire                   {lo}_wlast;",
        f"    input  wire                   {lo}_wvalid;",
        f"    input  wire                   {lo}_wready;",
        f"    input  wire [1:0]             {lo}_bresp;",
        f"    input  wire                   {lo}_bvalid;",
        f"    input  wire                   {lo}_bready;",
        f"    input  wire [ADDR_WIDTH-1:0]  {lo}_araddr;",
        f"    input  wire [7:0]             {lo}_arlen;",
        f"    input  wire                   {lo}_arvalid;",
        f"    input  wire                   {lo}_arready;",
        f"    input  wire [DATA_WIDTH-1:0]  {lo}_rdata;",
        f"    input  wire                   {lo}_rlast;",
        f"    input  wire                   {lo}_rvalid;",
        f"    input  wire                   {lo}_rready;",
        "",
    ]
    for ch, v, r in [
        ("AW", f"{lo}_awvalid", f"{lo}_awready"),
        ("W",  f"{lo}_wvalid",  f"{lo}_wready"),
        ("B",  f"{lo}_bvalid",  f"{lo}_bready"),
        ("AR", f"{lo}_arvalid", f"{lo}_arready"),
        ("R",  f"{lo}_rvalid",  f"{lo}_rready"),
    ]:
        lines += _handshake_asserts(ch, v, r, clk, rst)

    lines += [
        "    // WLAST must assert exactly once per burst",
        "    integer _beat;",
        f"    always @(posedge {clk} or negedge {rst}) begin",
        f"        if (!{rst}) _beat <= 0;",
        f"        else if ({lo}_wvalid && {lo}_wready) begin",
        f"            if ({lo}_wlast) _beat <= 0;",
        "            else _beat <= _beat + 1;",
        "        end",
        "    end",
        "    property p_wlast_sane;",
        f"        @(posedge {clk}) disable iff (!{rst}) (_beat < 256);",
        "    endproperty",
        "    a_wlast_sane: assert property (p_wlast_sane);",
        "",
        "endmodule",
        "`default_nettype wire",
        "",
    ]
    return "\n".join(lines)


def generate_axis_monitor(prefix: str = "S_AXIS") -> str:
    lo = prefix.lower()
    clk = f"{lo}_aclk"
    rst = f"{lo}_aresetn"
    name = f"{prefix.lower()}_axis_monitor"
    lines = _proto_common(name, prefix)
    lines += [
        f"    input  wire [DATA_WIDTH-1:0]  {lo}_tdata;",
        f"    input  wire                   {lo}_tvalid;",
        f"    input  wire                   {lo}_tready;",
        f"    input  wire                   {lo}_tlast;",
        f"    input  wire [DATA_WIDTH/8-1:0] {lo}_tkeep;",
        "",
    ]
    lines += _handshake_asserts("T", f"{lo}_tvalid", f"{lo}_tready", clk, rst)
    lines += [
        "    // TDATA must not be X while VALID is high",
        "    property p_tdata_valid;",
        f"        @(posedge {clk}) disable iff (!{rst})",
        f"        {lo}_tvalid |-> !$isunknown({lo}_tdata);",
        "    endproperty",
        "    a_tdata_valid: assert property (p_tdata_valid);",
        "",
        "endmodule",
        "`default_nettype wire",
        "",
    ]
    return "\n".join(lines)


def generate_apb_monitor(prefix: str = "S_APB") -> str:
    lo = prefix.lower()
    clk = f"{lo}_pclk"
    rst = f"{lo}_presetn"
    name = f"{prefix.lower()}_apb_monitor"
    lines = [
        _HEADER.format(name=name),
        f"module {name} #(",
        "    parameter int ADDR_WIDTH    = 32,",
        "    parameter int DATA_WIDTH    = 32,",
        "    parameter int TIMEOUT_CYCLES = 256",
        ") (",
        f"    input  wire                  {lo}_pclk,",
        f"    input  wire                  {lo}_presetn,",
        f"    input  wire [ADDR_WIDTH-1:0] {lo}_paddr,",
        f"    input  wire                  {lo}_psel,",
        f"    input  wire                  {lo}_penable,",
        f"    input  wire                  {lo}_pwrite,",
        f"    input  wire [DATA_WIDTH-1:0] {lo}_pwdata,",
        f"    input  wire                  {lo}_pready,",
        f"    input  wire [DATA_WIDTH-1:0] {lo}_prdata,",
        f"    input  wire                  {lo}_pslverr",
        ");",
        "",
        "    // SETUP -> ACCESS phase: psel without penable first, then both",
        "    property p_setup_to_access;",
        f"        @(posedge {clk}) disable iff (!{rst})",
        f"        ({lo}_psel && !{lo}_penable) |=> ({lo}_psel && {lo}_penable);",
        "    endproperty",
        "    a_setup_to_access: assert property (p_setup_to_access);",
        "",
        "    // PADDR must be stable during access phase",
        "    property p_paddr_stable;",
        f"        @(posedge {clk}) disable iff (!{rst})",
        f"        ({lo}_psel && {lo}_penable && !{lo}_pready)",
        f"        |=> $stable({lo}_paddr);",
        "    endproperty",
        "    a_paddr_stable: assert property (p_paddr_stable);",
        "",
        "    // Timeout on PREADY",
        "    integer _cnt;",
        f"    always @(posedge {clk} or negedge {rst}) begin",
        f"        if (!{rst}) _cnt <= 0;",
        f"        else if ({lo}_psel && {lo}_penable && !{lo}_pready) _cnt <= _cnt + 1;",
        "        else _cnt <= 0;",
        "    end",
        "    property p_pready_timeout;",
        f"        @(posedge {clk}) disable iff (!{rst}) (_cnt < TIMEOUT_CYCLES);",
        "    endproperty",
        "    a_pready_timeout: assert property (p_pready_timeout);",
        "",
        "    cov_apb_xfer: cover property (",
        f"        @(posedge {clk}) disable iff (!{rst})",
        f"        ({lo}_psel && {lo}_penable && {lo}_pready)",
        "    );",
        "",
        "endmodule",
        "`default_nettype wire",
        "",
    ]
    return "\n".join(lines)


def generate_ahb_monitor(prefix: str = "S_AHB") -> str:
    lo = prefix.lower()
    clk = f"{lo}_hclk"
    rst = f"{lo}_hresetn"
    name = f"{prefix.lower()}_ahb_monitor"
    lines = [
        _HEADER.format(name=name),
        f"module {name} #(",
        "    parameter int ADDR_WIDTH    = 32,",
        "    parameter int DATA_WIDTH    = 32,",
        "    parameter int TIMEOUT_CYCLES = 1024",
        ") (",
        f"    input  wire                  {lo}_hclk,",
        f"    input  wire                  {lo}_hresetn,",
        f"    input  wire [ADDR_WIDTH-1:0] {lo}_haddr,",
        f"    input  wire [1:0]            {lo}_htrans,",
        f"    input  wire                  {lo}_hwrite,",
        f"    input  wire [2:0]            {lo}_hsize,",
        f"    input  wire [2:0]            {lo}_hburst,",
        f"    input  wire [DATA_WIDTH-1:0] {lo}_hwdata,",
        f"    input  wire [DATA_WIDTH-1:0] {lo}_hrdata,",
        f"    input  wire                  {lo}_hready,",
        f"    input  wire [1:0]            {lo}_hresp",
        ");",
        "",
        "    // HTRANS must not be X",
        "    property p_htrans_no_x;",
        f"        @(posedge {clk}) disable iff (!{rst}) !$isunknown({lo}_htrans);",
        "    endproperty",
        "    a_htrans_no_x: assert property (p_htrans_no_x);",
        "",
        "    // HADDR must be stable while !HREADY for NONSEQ/SEQ",
        "    property p_haddr_stable;",
        f"        @(posedge {clk}) disable iff (!{rst})",
        f"        (({lo}_htrans == 2'b10 || {lo}_htrans == 2'b11) && !{lo}_hready)",
        f"        |=> $stable({lo}_haddr);",
        "    endproperty",
        "    a_haddr_stable: assert property (p_haddr_stable);",
        "",
        "    // HREADY timeout",
        "    integer _cnt;",
        f"    always @(posedge {clk} or negedge {rst}) begin",
        f"        if (!{rst}) _cnt <= 0;",
        f"        else if (!{lo}_hready) _cnt <= _cnt + 1;",
        "        else _cnt <= 0;",
        "    end",
        "    property p_hready_timeout;",
        f"        @(posedge {clk}) disable iff (!{rst}) (_cnt < TIMEOUT_CYCLES);",
        "    endproperty",
        "    a_hready_timeout: assert property (p_hready_timeout);",
        "",
        "    cov_ahb_xfer: cover property (",
        f"        @(posedge {clk}) disable iff (!{rst})",
        f"        ({lo}_hready && ({lo}_htrans == 2'b10 || {lo}_htrans == 2'b11))",
        "    );",
        "",
        "endmodule",
        "`default_nettype wire",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "generate_axi4_lite_monitor",
    "generate_axi4_full_monitor",
    "generate_axis_monitor",
    "generate_apb_monitor",
    "generate_ahb_monitor",
]

"""Integrated Logic Analyzer (ILA) / debug core insertion.

Given a list of probes and a capture configuration, this module
generates a synthesizable Verilog wrapper that captures those signals
into an on-chip circular BRAM and streams the capture out over UART at
115200 8N1. It also parses the binary UART dump back into per-probe
waveform data.

The generated wrapper is a real, synthesizable Verilog-2001 module
compatible with yosys + nextpnr and the open-source ECP5/ice40/Gowin
flows.
"""

from __future__ import annotations

import contextlib
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Sequence

    from openforge.jtag.bridge import JtagBridge


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class DebugProbe(BaseModel):
    """A single signal captured by the ILA."""

    name: str = Field(..., description="Unique identifier for the probe.")
    signal: str = Field(..., description="Hierarchical name of the signal to tap.")
    width: int = Field(..., ge=1, le=1024, description="Width in bits.")
    sample_depth: int = Field(
        default=1024,
        ge=16,
        le=1 << 16,
        description="Depth of the per-probe circular buffer, in samples.",
    )

    @field_validator("name")
    @classmethod
    def _sanitize_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("probe name cannot be empty")
        return v


class DebugCore(BaseModel):
    """Top-level ILA configuration."""

    probes: list[DebugProbe] = Field(default_factory=list)
    sample_clock: str = Field(
        default="clk",
        description="Name of the clock driving the ILA sampling logic.",
    )
    trigger_logic: str = Field(
        default="1'b1",
        description=(
            "Verilog expression that asserts high when capture should trigger. "
            "Referenced signals must be in scope of the wrapper."
        ),
    )
    capture_depth: int = Field(
        default=1024,
        ge=16,
        le=1 << 16,
        description="Depth of the shared capture buffer in samples.",
    )
    uart_baud: int = 115_200
    sys_clk_hz: int = 12_000_000

    @property
    def total_width(self) -> int:
        return sum(p.width for p in self.probes)

    @property
    def packed_bytes_per_sample(self) -> int:
        return (self.total_width + 7) // 8


# ---------------------------------------------------------------------------
# Verilog generation
# ---------------------------------------------------------------------------


def _clog2(n: int) -> int:
    if n <= 1:
        return 1
    v = n - 1
    out = 0
    while v:
        v >>= 1
        out += 1
    return out


def _concat_expression(probes: Sequence[DebugProbe]) -> str:
    """Return a Verilog expression concatenating all probes MSB-first."""
    if not probes:
        return "1'b0"
    parts = [p.signal for p in probes]
    return "{" + ", ".join(parts) + "}"


def _port_list(probes: Sequence[DebugProbe]) -> str:
    lines = [
        "    input  wire                     clk_i,",
        "    input  wire                     rst_i,",
    ]
    for p in probes:
        if p.width == 1:
            lines.append(f"    input  wire                     probe_{p.name}_i,")
        else:
            lines.append(
                f"    input  wire [{p.width - 1}:0]{' ' * max(1, 15 - len(str(p.width - 1)))}probe_{p.name}_i,"
            )
    lines.append("    output wire                     uart_tx_o")
    return "\n".join(lines)


def _probe_rename_wires(probes: Sequence[DebugProbe]) -> str:
    out: list[str] = []
    for p in probes:
        if p.width == 1:
            out.append(f"    wire {p.signal} = probe_{p.name}_i;")
        else:
            out.append(
                f"    wire [{p.width - 1}:0] {p.signal} = probe_{p.name}_i;"
            )
    return "\n".join(out)


def render_ila_wrapper(top_module: str, core: DebugCore) -> str:
    """Return the synthesizable Verilog for an ILA wrapper module.

    The generated module has one port per probe, a clock, a reset and a
    UART TX output. Internally it instantiates:

    * A circular buffer implemented as a distributed BRAM
    * A trigger comparator based on ``core.trigger_logic``
    * A simple UART transmitter (115200 8N1 by default)
    * A readout state machine that drains the buffer after a trigger
    """
    probes = core.probes
    total_w = core.total_width or 1
    depth = core.capture_depth
    addr_w = _clog2(depth)
    sample_w = max(total_w, 1)
    clks_per_bit = max(1, core.sys_clk_hz // core.uart_baud)
    concat = _concat_expression(probes)
    port_list = _port_list(probes)
    probe_aliases = _probe_rename_wires(probes)
    module_name = f"openforge_ila_{top_module}".replace("-", "_")
    bytes_per_sample = (sample_w + 7) // 8
    total_bytes = bytes_per_sample * depth

    magic_lo = 0xF0
    magic_hi = 0x0F

    return f"""// Auto-generated by OpenForge ILA inserter.
// Probes : {len(probes)}
// Width  : {sample_w} bits/sample
// Depth  : {depth} samples
// Bytes  : {total_bytes} bytes per capture
// UART   : {core.uart_baud} 8N1 @ {core.sys_clk_hz} Hz
`default_nettype none

module {module_name} (
{port_list}
);

    // ---------------- probe aliases ----------------
{probe_aliases}

    // ---------------- capture buffer ----------------
    localparam integer SAMPLE_W    = {sample_w};
    localparam integer DEPTH       = {depth};
    localparam integer ADDR_W      = {addr_w};
    localparam integer BYTES_PER_S = {bytes_per_sample};
    localparam integer CLKS_PER_BIT= {clks_per_bit};

    reg  [SAMPLE_W-1:0] ila_mem [0:DEPTH-1];
    reg  [ADDR_W-1:0]   wr_ptr;
    reg                 armed;
    reg                 captured;
    reg  [ADDR_W-1:0]   rd_ptr;

    wire [SAMPLE_W-1:0] sample_q = {concat};
    wire                trigger_q = ({core.trigger_logic});

    // Circular write until trigger, then freeze after DEPTH more samples.
    reg  [ADDR_W:0]     post_trig_cnt;

    always @(posedge clk_i) begin
        if (rst_i) begin
            wr_ptr        <= {{ADDR_W{{1'b0}}}};
            armed         <= 1'b1;
            captured      <= 1'b0;
            post_trig_cnt <= {{(ADDR_W+1){{1'b0}}}};
        end else if (!captured) begin
            ila_mem[wr_ptr] <= sample_q;
            wr_ptr          <= wr_ptr + {{{{ADDR_W-1{{1'b0}}}}, 1'b1}};
            if (armed && trigger_q) begin
                armed <= 1'b0;
            end
            if (!armed) begin
                if (post_trig_cnt == DEPTH[ADDR_W:0] - 1) begin
                    captured <= 1'b1;
                end else begin
                    post_trig_cnt <= post_trig_cnt + 1'b1;
                end
            end
        end
    end

    // ---------------- UART TX (8N1) ----------------
    reg  [3:0]  uart_state;
    reg  [15:0] uart_clk_cnt;
    reg  [3:0]  uart_bit_idx;
    reg  [7:0]  uart_data;
    reg         uart_tx_r;
    assign uart_tx_o = uart_tx_r;

    localparam UART_IDLE  = 4'd0;
    localparam UART_START = 4'd1;
    localparam UART_DATA  = 4'd2;
    localparam UART_STOP  = 4'd3;
    localparam UART_DONE  = 4'd4;

    // ---------------- readout FSM ----------------
    reg  [2:0]  ro_state;
    reg  [ADDR_W:0] byte_idx;          // 0 .. DEPTH*BYTES_PER_S
    reg  [$clog2(BYTES_PER_S+1)-1:0] byte_in_sample;
    reg  [7:0]  tx_fifo;
    reg         tx_valid;
    wire        tx_ready;

    localparam RO_WAIT   = 3'd0;
    localparam RO_HDR0   = 3'd1;
    localparam RO_HDR1   = 3'd2;
    localparam RO_SAMPLE = 3'd3;
    localparam RO_IDLE   = 3'd4;

    assign tx_ready = (uart_state == UART_IDLE);

    function [7:0] slice_byte;
        input [SAMPLE_W-1:0] s;
        input integer byte_sel;
        integer lo;
        integer hi;
        integer i;
        reg [7:0] tmp;
        begin
            lo = byte_sel * 8;
            hi = lo + 7;
            tmp = 8'h00;
            for (i = 0; i < 8; i = i + 1) begin
                if ((lo + i) < SAMPLE_W)
                    tmp[i] = s[lo + i];
                else
                    tmp[i] = 1'b0;
            end
            slice_byte = tmp;
        end
    endfunction

    reg [SAMPLE_W-1:0] rd_sample;

    always @(posedge clk_i) begin
        if (rst_i) begin
            ro_state       <= RO_WAIT;
            byte_idx       <= {{(ADDR_W+1){{1'b0}}}};
            byte_in_sample <= 0;
            rd_ptr         <= {{ADDR_W{{1'b0}}}};
            tx_valid       <= 1'b0;
            tx_fifo        <= 8'h00;
        end else begin
            tx_valid <= 1'b0;
            case (ro_state)
                RO_WAIT: if (captured) ro_state <= RO_HDR0;
                RO_HDR0: if (tx_ready) begin
                    tx_fifo  <= 8'h{magic_lo:02X};
                    tx_valid <= 1'b1;
                    ro_state <= RO_HDR1;
                end
                RO_HDR1: if (tx_ready) begin
                    tx_fifo  <= 8'h{magic_hi:02X};
                    tx_valid <= 1'b1;
                    ro_state <= RO_SAMPLE;
                    rd_ptr   <= wr_ptr;  // start at oldest sample
                    byte_in_sample <= 0;
                    byte_idx <= {{(ADDR_W+1){{1'b0}}}};
                    rd_sample <= ila_mem[wr_ptr];
                end
                RO_SAMPLE: if (tx_ready) begin
                    tx_fifo  <= slice_byte(rd_sample, byte_in_sample);
                    tx_valid <= 1'b1;
                    if (byte_in_sample == BYTES_PER_S - 1) begin
                        byte_in_sample <= 0;
                        rd_ptr <= rd_ptr + {{{{ADDR_W-1{{1'b0}}}}, 1'b1}};
                        rd_sample <= ila_mem[rd_ptr + {{{{ADDR_W-1{{1'b0}}}}, 1'b1}}];
                    end else begin
                        byte_in_sample <= byte_in_sample + 1;
                    end
                    if (byte_idx == (DEPTH*BYTES_PER_S) - 1)
                        ro_state <= RO_IDLE;
                    else
                        byte_idx <= byte_idx + 1'b1;
                end
                default: ro_state <= RO_IDLE;
            endcase
        end
    end

    // UART TX state machine.
    always @(posedge clk_i) begin
        if (rst_i) begin
            uart_state   <= UART_IDLE;
            uart_clk_cnt <= 16'd0;
            uart_bit_idx <= 4'd0;
            uart_tx_r    <= 1'b1;
            uart_data    <= 8'd0;
        end else begin
            case (uart_state)
                UART_IDLE: begin
                    uart_tx_r    <= 1'b1;
                    uart_clk_cnt <= 16'd0;
                    uart_bit_idx <= 4'd0;
                    if (tx_valid) begin
                        uart_data  <= tx_fifo;
                        uart_state <= UART_START;
                    end
                end
                UART_START: begin
                    uart_tx_r <= 1'b0;
                    if (uart_clk_cnt == CLKS_PER_BIT-1) begin
                        uart_clk_cnt <= 16'd0;
                        uart_state   <= UART_DATA;
                    end else begin
                        uart_clk_cnt <= uart_clk_cnt + 1'b1;
                    end
                end
                UART_DATA: begin
                    uart_tx_r <= uart_data[uart_bit_idx];
                    if (uart_clk_cnt == CLKS_PER_BIT-1) begin
                        uart_clk_cnt <= 16'd0;
                        if (uart_bit_idx == 4'd7) begin
                            uart_bit_idx <= 4'd0;
                            uart_state   <= UART_STOP;
                        end else begin
                            uart_bit_idx <= uart_bit_idx + 1'b1;
                        end
                    end else begin
                        uart_clk_cnt <= uart_clk_cnt + 1'b1;
                    end
                end
                UART_STOP: begin
                    uart_tx_r <= 1'b1;
                    if (uart_clk_cnt == CLKS_PER_BIT-1) begin
                        uart_clk_cnt <= 16'd0;
                        uart_state   <= UART_IDLE;
                    end else begin
                        uart_clk_cnt <= uart_clk_cnt + 1'b1;
                    end
                end
                default: uart_state <= UART_IDLE;
            endcase
        end
    end

endmodule

`default_nettype wire
"""


def insert_debug_core(
    rtl_dir: str | Path,
    top_module: str,
    core: DebugCore,
) -> Path:
    """Generate an ILA wrapper module and write it next to the user's RTL.

    The wrapper is written to ``<rtl_dir>/openforge_ila.v`` and the path
    is returned. The caller is responsible for instantiating the wrapper
    from their top-level design.
    """
    rtl_path = Path(rtl_dir)
    rtl_path.mkdir(parents=True, exist_ok=True)
    out = rtl_path / "openforge_ila.v"
    out.write_text(render_ila_wrapper(top_module, core), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# UART capture parser
# ---------------------------------------------------------------------------


def parse_capture(uart_dump: bytes, core: DebugCore) -> dict[str, list[int]]:
    """Parse a raw UART dump from the ILA into per-probe waveform data.

    The wrapper emits a 2-byte magic header (``0xF0 0x0F``) followed by
    ``capture_depth * bytes_per_sample`` payload bytes. Each sample is
    unpacked LSB-first into the concatenated probe bit-vector, then
    split back into the individual probes in declaration order.
    """
    bps = core.packed_bytes_per_sample
    if bps == 0:
        return {p.name: [] for p in core.probes}

    data = uart_dump
    # Skip header if present.
    idx = data.find(b"\xf0\x0f")
    if idx >= 0:
        data = data[idx + 2 :]

    needed = core.capture_depth * bps
    data = data[:needed]

    results: dict[str, list[int]] = {p.name: [] for p in core.probes}
    for s_idx in range(len(data) // bps):
        sample_bytes = data[s_idx * bps : (s_idx + 1) * bps]
        value = 0
        for i, b in enumerate(sample_bytes):
            value |= b << (i * 8)
        # Probes were concatenated MSB-first in Verilog ({p0, p1, ...}),
        # which places p0 in the high bits.
        shift = core.total_width
        for probe in core.probes:
            shift -= probe.width
            mask = (1 << probe.width) - 1
            results[probe.name].append((value >> shift) & mask)
    return results


# ---------------------------------------------------------------------------
# Advanced trigger sequencer + JTAG-facing ILA
# ---------------------------------------------------------------------------


class TriggerKind(StrEnum):
    EDGE_RISE = "edge_rise"
    EDGE_FALL = "edge_fall"
    LEVEL_HIGH = "level_high"
    LEVEL_LOW = "level_low"
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    LT = "lt"
    ANY = "any"


class TriggerCondition(BaseModel):
    probe: str
    kind: TriggerKind = TriggerKind.ANY
    value: int | None = None
    mask: int | None = None


class TriggerSequence(BaseModel):
    """Multi-stage trigger sequencer (up to 8 stages)."""

    stages: list[tuple[TriggerCondition, int]] = Field(default_factory=list)

    @field_validator("stages")
    @classmethod
    def _cap(cls, v: list[tuple[TriggerCondition, int]]) -> list:
        if len(v) > 8:
            raise ValueError("TriggerSequence supports at most 8 stages")
        return v


class CaptureMode(StrEnum):
    CIRCULAR = "circular"
    ONE_SHOT = "one_shot"
    MULTI_WINDOW = "multi_window"


class IlaVendor(StrEnum):
    XILINX = "xilinx"        # BSCANE2 primitive
    LATTICE_ECP5 = "ecp5"    # JTAGG primitive
    LATTICE_ICE40 = "ice40"  # software-only (no BSCAN)
    GOWIN = "gowin"          # similar to Lattice JTAGG


# JTAG register-file address layout (exposed through the user TAP).
ILA_REG_CTRL = 0x00
ILA_REG_STATUS = 0x01
ILA_REG_TRIGGER = 0x02
ILA_REG_DATA = 0x03


def _trigger_comparator(cond: TriggerCondition) -> str:
    """Return a Verilog expression for one trigger condition."""
    sig = f"probe_{cond.probe}"
    val = cond.value or 0
    if cond.kind == TriggerKind.EDGE_RISE:
        return f"({sig} & ~{sig}_d)"
    if cond.kind == TriggerKind.EDGE_FALL:
        return f"(~{sig} & {sig}_d)"
    if cond.kind == TriggerKind.LEVEL_HIGH:
        return f"|{sig}"
    if cond.kind == TriggerKind.LEVEL_LOW:
        return f"~|{sig}"
    if cond.kind == TriggerKind.EQ:
        return f"({sig} == {val})"
    if cond.kind == TriggerKind.NEQ:
        return f"({sig} != {val})"
    if cond.kind == TriggerKind.GT:
        return f"({sig} > {val})"
    if cond.kind == TriggerKind.LT:
        return f"({sig} < {val})"
    return "1'b1"


def render_advanced_ila(
    core: DebugCore,
    trigger: TriggerSequence,
    mode: CaptureMode,
    jtag_userreg: int = 4,
    vendor: IlaVendor = IlaVendor.XILINX,
) -> str:
    """Generate a synthesizable ILA that uses BSCANE2 (Xilinx) or JTAGG
    (ECP5/Gowin) as its JTAG I/O, with a rule-based trigger sequencer,
    circular / one-shot / multi-window capture, and an inferred BRAM
    sample buffer.

    The generated module exposes a TAP-side register file:

        addr 0x00 : control     (bit0=arm, bit1=reset, bit2=force_trigger,
                                 bit4:5=capture mode)
        addr 0x01 : status      (bit0=armed, bit1=triggered, bit2=full,
                                 bit3:31=sample count)
        addr 0x02 : trigger_cfg (config for the current stage pointer)
        addr 0x03 : data        (read advances the sample pointer)
    """
    probes = core.probes
    total_w = core.total_width or 1
    depth = core.capture_depth
    addr_w = _clog2(depth)
    sample_w = max(total_w, 1)
    module_name = f"openforge_ila_adv_{core.sample_clock}".replace("-", "_")

    port_decls: list[str] = ["    input  wire clk_i,", "    input  wire rst_i,"]
    for p in probes:
        if p.width == 1:
            port_decls.append(f"    input  wire probe_{p.name}_i,")
        else:
            port_decls.append(
                f"    input  wire [{p.width - 1}:0] probe_{p.name}_i,"
            )
    port_decls_s = "\n".join(port_decls).rstrip(",")

    # Per-probe registered delayed signal for edge detection.
    probe_aliases: list[str] = []
    probe_delays: list[str] = []
    for p in probes:
        w = f"[{p.width - 1}:0]" if p.width > 1 else ""
        probe_aliases.append(f"    wire {w} probe_{p.name} = probe_{p.name}_i;")
        probe_delays.append(f"    reg  {w} probe_{p.name}_d;")
    probe_aliases_s = "\n".join(probe_aliases)
    probe_delays_s = "\n".join(probe_delays)

    delay_assigns = "\n".join(
        f"        probe_{p.name}_d <= probe_{p.name};" for p in probes
    )

    # Stage comparator expressions.
    stage_exprs: list[str] = []
    for i, (cond, _count) in enumerate(trigger.stages or []):
        expr = _trigger_comparator(cond)
        stage_exprs.append(f"    wire stage_hit_{i} = {expr};")
    # Always emit at least one "always-on" stage.
    if not stage_exprs:
        stage_exprs = ["    wire stage_hit_0 = 1'b1;"]
        stage_counts = [1]
    else:
        stage_counts = [max(1, c) for _, c in trigger.stages]

    stage_hits = "\n".join(stage_exprs)
    n_stages = len(stage_counts)

    bscan_primitive = {
        IlaVendor.XILINX: f"""
    // Xilinx BSCANE2 user JTAG register {jtag_userreg}
    wire bscan_tck, bscan_tdi, bscan_sel, bscan_drck, bscan_update, bscan_shift, bscan_capture, bscan_reset;
    wire bscan_tdo;
    BSCANE2 #(.JTAG_CHAIN({jtag_userreg})) u_bscan (
        .TDO(bscan_tdo),
        .CAPTURE(bscan_capture),
        .DRCK(bscan_drck),
        .RESET(bscan_reset),
        .RUNTEST(),
        .SEL(bscan_sel),
        .SHIFT(bscan_shift),
        .TCK(bscan_tck),
        .TDI(bscan_tdi),
        .TMS(),
        .UPDATE(bscan_update)
    );""",
        IlaVendor.LATTICE_ECP5: """
    // Lattice ECP5 JTAGG primitive (ER1 user register)
    wire bscan_tck, bscan_tdi, bscan_sel, bscan_drck, bscan_update, bscan_shift, bscan_capture, bscan_reset;
    wire bscan_tdo;
    JTAGG #(.ER1("ENABLED"), .ER2("DISABLED")) u_jtagg (
        .JTCK(bscan_tck),
        .JTDI(bscan_tdi),
        .JTDO1(bscan_tdo),
        .JTDO2(1'b0),
        .JRTI1(bscan_sel),
        .JRTI2(),
        .JSHIFT(bscan_shift),
        .JUPDATE(bscan_update),
        .JRSTN(bscan_reset),
        .JCE1(bscan_capture),
        .JCE2()
    );
    assign bscan_drck = bscan_tck;""",
        IlaVendor.LATTICE_ICE40: """
    // iCE40 has no hard BSCAN primitive; this IP falls back to direct
    // fabric signals so a soft TAP (e.g. nextpnr JTAG-over-SPI bridge) can
    // drive the register file externally.
    wire bscan_tck = 1'b0;
    wire bscan_tdi = 1'b0;
    wire bscan_sel = 1'b0;
    wire bscan_drck = 1'b0;
    wire bscan_update = 1'b0;
    wire bscan_shift = 1'b0;
    wire bscan_capture = 1'b0;
    wire bscan_reset = 1'b1;
    wire bscan_tdo = 1'b0;""",
        IlaVendor.GOWIN: """
    // Gowin user JTAG - GSR + JTAG_INST
    wire bscan_tck, bscan_tdi, bscan_sel, bscan_drck, bscan_update, bscan_shift, bscan_capture, bscan_reset;
    wire bscan_tdo;
    assign bscan_drck = bscan_tck;""",
    }[vendor]

    mode_val = {
        CaptureMode.CIRCULAR: 2,
        CaptureMode.ONE_SHOT: 0,
        CaptureMode.MULTI_WINDOW: 1,
    }[mode]

    ", ".join(f"16'd{c}" for c in stage_counts)

    return f"""// Auto-generated OpenForge advanced ILA (vendor={vendor.value},
// mode={mode.value}, stages={n_stages})
`default_nettype none

module {module_name} (
{port_decls_s}
);
    localparam integer SAMPLE_W = {sample_w};
    localparam integer DEPTH    = {depth};
    localparam integer ADDR_W   = {addr_w};
    localparam integer N_STAGES = {max(n_stages, 1)};
    localparam integer INIT_MODE = {mode_val};

{probe_aliases_s}
{probe_delays_s}

    reg [SAMPLE_W-1:0] ila_mem [0:DEPTH-1];
    reg [ADDR_W-1:0]   wr_ptr;
    reg [ADDR_W-1:0]   rd_ptr;
    reg                armed;
    reg                triggered;
    reg                full;
    reg [1:0]          cap_mode;
    reg [3:0]          stage_ptr;
    reg [15:0]         stage_cnt;
    reg [15:0]         stage_limits [0:7];

    // Concatenated sample (MSB-first for parse_capture compatibility).
    wire [SAMPLE_W-1:0] sample_q = {{{ ", ".join(f"probe_{p.name}" for p in probes) if probes else "1'b0" } }};

    // Stage comparators
{stage_hits}
    wire [N_STAGES-1:0] stage_hit_vec = {{{ ", ".join(f"stage_hit_{i}" for i in reversed(range(max(n_stages, 1)))) } }};
    wire current_hit = stage_hit_vec[stage_ptr];

{bscan_primitive}

    // -------- JTAG register file --------
    reg [31:0] ctrl_reg;
    reg [31:0] trig_cfg_reg;
    reg [7:0]  addr_reg;
    reg [31:0] shift_reg;
    reg [5:0]  shift_cnt;
    assign bscan_tdo = shift_reg[0];

    wire cmd_arm   = ctrl_reg[0];
    wire cmd_reset = ctrl_reg[1];
    wire cmd_force = ctrl_reg[2];

    always @(posedge bscan_drck or posedge bscan_reset) begin
        if (bscan_reset) begin
            shift_reg <= 32'h0;
            shift_cnt <= 6'd0;
        end else if (bscan_sel && bscan_shift) begin
            shift_reg <= {{bscan_tdi, shift_reg[31:1]}};
            shift_cnt <= shift_cnt + 1'b1;
        end else if (bscan_sel && bscan_capture) begin
            case (addr_reg)
                8'h{ILA_REG_STATUS:02x}: shift_reg <= {{ {{(32-ADDR_W-3){{1'b0}} }}, wr_ptr, full, triggered, armed }};
                8'h{ILA_REG_DATA:02x}:   shift_reg <= ila_mem[rd_ptr][31:0];
                default: shift_reg <= ctrl_reg;
            endcase
            shift_cnt <= 6'd0;
        end
    end

    always @(posedge bscan_drck) begin
        if (bscan_sel && bscan_update) begin
            addr_reg  <= shift_reg[7:0];
            if (shift_reg[7:0] == 8'h{ILA_REG_CTRL:02x})
                ctrl_reg <= shift_reg;
            else if (shift_reg[7:0] == 8'h{ILA_REG_TRIGGER:02x})
                trig_cfg_reg <= shift_reg;
        end
    end

    // -------- Capture FSM on sample clock --------
    integer i;
    initial begin
        stage_limits[0] = 16'd1;
        stage_limits[1] = 16'd1;
        stage_limits[2] = 16'd1;
        stage_limits[3] = 16'd1;
        stage_limits[4] = 16'd1;
        stage_limits[5] = 16'd1;
        stage_limits[6] = 16'd1;
        stage_limits[7] = 16'd1;
        {chr(10).join(f"        stage_limits[{i}] = 16'd{c};" for i, c in enumerate(stage_counts))}
    end

    always @(posedge clk_i) begin
{delay_assigns}

        if (rst_i || cmd_reset) begin
            wr_ptr    <= {{ADDR_W{{1'b0}}}};
            rd_ptr    <= {{ADDR_W{{1'b0}}}};
            armed     <= 1'b0;
            triggered <= 1'b0;
            full      <= 1'b0;
            stage_ptr <= 4'd0;
            stage_cnt <= 16'd0;
            cap_mode  <= INIT_MODE[1:0];
        end else begin
            if (cmd_arm && !armed) begin
                armed     <= 1'b1;
                triggered <= 1'b0;
                full      <= 1'b0;
                wr_ptr    <= {{ADDR_W{{1'b0}}}};
                stage_ptr <= 4'd0;
                stage_cnt <= 16'd0;
            end

            if (armed && !full) begin
                ila_mem[wr_ptr] <= sample_q;
                if (cap_mode == 2'd2 /* circular */) begin
                    wr_ptr <= wr_ptr + 1'b1;
                end else if (!triggered) begin
                    wr_ptr <= wr_ptr + 1'b1;
                end else begin
                    wr_ptr <= wr_ptr + 1'b1;
                    if (&wr_ptr) full <= 1'b1;
                end

                if (!triggered) begin
                    if (current_hit || cmd_force) begin
                        if (stage_cnt + 1 >= stage_limits[stage_ptr]) begin
                            stage_cnt <= 16'd0;
                            if (stage_ptr + 1 >= N_STAGES[3:0]) begin
                                triggered <= 1'b1;
                            end else begin
                                stage_ptr <= stage_ptr + 1'b1;
                            end
                        end else begin
                            stage_cnt <= stage_cnt + 1'b1;
                        end
                    end
                end

                if (triggered && cap_mode == 2'd0 /* one-shot */) begin
                    if (&wr_ptr) begin
                        full  <= 1'b1;
                        armed <= 1'b0;
                    end
                end
            end
        end
    end

endmodule
`default_nettype wire
"""


# ---------------------------------------------------------------------------
# JTAG-driven ILA reader
# ---------------------------------------------------------------------------


class IlaReader:
    """Reads samples from a deployed advanced ILA over JTAG."""

    def __init__(
        self,
        bridge: JtagBridge,
        core: DebugCore,
        user_register: int = 4,
    ) -> None:
        self.bridge = bridge
        self.core = core
        self.user_register = user_register

    # USER<N> instruction opcodes for Xilinx 7-series BSCANE2.
    _XILINX_USER_IR = {1: 0x02, 2: 0x03, 3: 0x22, 4: 0x23}

    def _select_user(self) -> None:
        ir_opcode = self._XILINX_USER_IR.get(self.user_register, 0x23)
        with contextlib.suppress(Exception):
            self.bridge.write_ir(ir_opcode, 6)

    def _write_reg(self, addr: int, value: int) -> None:
        self._select_user()
        packet = (value << 8) | (addr & 0xFF)
        self.bridge.write_dr(packet, 40)

    def _read_reg(self, addr: int) -> int:
        self._select_user()
        # First write selects address, second read shifts out data.
        self.bridge.write_dr(addr & 0xFF, 8)
        return self.bridge.read_dr(32)

    def arm(self) -> None:
        # bit0=arm, bit1=reset, bit2=force
        self._write_reg(ILA_REG_CTRL, 0x2)  # reset
        self._write_reg(ILA_REG_CTRL, 0x1)  # arm

    def force_trigger(self) -> None:
        self._write_reg(ILA_REG_CTRL, 0x5)

    def status(self) -> dict:
        raw = self._read_reg(ILA_REG_STATUS)
        return {
            "armed": bool(raw & 0x1),
            "triggered": bool(raw & 0x2),
            "full": bool(raw & 0x4),
            "sample_count": (raw >> 3) & 0x1FFFFFFF,
            "raw": raw,
        }

    def is_triggered(self) -> bool:
        return self.status()["triggered"]

    def is_full(self) -> bool:
        return self.status()["full"]

    def read_samples(self) -> dict[str, list[int]]:
        """Drain the capture buffer and split into per-probe lists."""
        depth = self.core.capture_depth
        samples_raw: list[int] = []
        for _ in range(depth):
            samples_raw.append(self._read_reg(ILA_REG_DATA))

        # Unpack MSB-first into probes, same convention as parse_capture.
        results: dict[str, list[int]] = {p.name: [] for p in self.core.probes}
        total = self.core.total_width
        for v in samples_raw:
            shift = total
            for probe in self.core.probes:
                shift -= probe.width
                mask = (1 << probe.width) - 1
                results[probe.name].append((v >> shift) & mask)
        return results

    def to_vcd(
        self,
        samples: dict[str, list[int]],
        output_path: str | Path,
        sample_period_ns: float = 10.0,
    ) -> Path:
        """Write captured samples to a VCD file."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # One-char codes for probes (VCD identifiers).
        codes: dict[str, str] = {}
        probe_widths: dict[str, int] = {p.name: p.width for p in self.core.probes}
        next_code = 33  # '!'
        for name in samples:
            codes[name] = chr(next_code)
            next_code += 1

        n_samples = max((len(v) for v in samples.values()), default=0)
        with out.open("w", encoding="utf-8") as f:
            f.write("$date\n    openforge ila capture\n$end\n")
            f.write("$version\n    OpenForge 1.0\n$end\n")
            f.write("$timescale 1 ns $end\n")
            f.write("$scope module ila $end\n")
            for name, code in codes.items():
                w = probe_widths.get(name, 1)
                f.write(f"$var wire {w} {code} {name} $end\n")
            f.write("$upscope $end\n$enddefinitions $end\n")
            f.write("#0\n")
            # Initial values
            for name, code in codes.items():
                vals = samples.get(name, [])
                v = vals[0] if vals else 0
                w = probe_widths.get(name, 1)
                if w == 1:
                    f.write(f"{v & 1}{code}\n")
                else:
                    f.write(f"b{v:0{w}b} {code}\n")
            for i in range(1, n_samples):
                t_ns = int(i * sample_period_ns)
                f.write(f"#{t_ns}\n")
                for name, code in codes.items():
                    vals = samples.get(name, [])
                    if i >= len(vals):
                        continue
                    v = vals[i]
                    w = probe_widths.get(name, 1)
                    if w == 1:
                        f.write(f"{v & 1}{code}\n")
                    else:
                        f.write(f"b{v:0{w}b} {code}\n")
        return out


__all__ = [
    "DebugProbe",
    "DebugCore",
    "render_ila_wrapper",
    "insert_debug_core",
    "parse_capture",
    "TriggerKind",
    "TriggerCondition",
    "TriggerSequence",
    "CaptureMode",
    "IlaVendor",
    "render_advanced_ila",
    "IlaReader",
]

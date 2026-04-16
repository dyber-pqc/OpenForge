"""Block design Verilog generator.

Produces synthesizable Verilog-2001 from a declarative
:class:`BlockDesign` description, plus a matching testbench and a
lightweight linter.  Also ships a library of built-in IP factory
functions for common peripherals (AXI, SPI, I2C, UART, ...).

The module is intentionally free of any Qt or UI dependency so it can be
used from the CLI, the API, or unit tests.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class BlockPort:
    """A single port on an IP block or on the top-level module.

    ``width`` is expressed in bits; a width of 1 produces a scalar
    declaration (no ``[x:0]`` prefix).  ``direction`` must be one of
    ``input``, ``output`` or ``inout``.
    """

    name: str
    direction: str  # "input" | "output" | "inout"
    width: int = 1
    description: str = ""

    def __post_init__(self) -> None:
        if self.direction not in ("input", "output", "inout"):
            raise ValueError(f"invalid direction {self.direction!r} for port {self.name!r}")
        if self.width < 1:
            raise ValueError(f"width must be >= 1 (port {self.name!r})")

    @property
    def range_spec(self) -> str:
        """Return the Verilog ``[N-1:0]`` prefix, or empty for scalar."""
        if self.width <= 1:
            return ""
        return f"[{self.width - 1}:0]"


@dataclass
class BlockInstance:
    """A concrete instance of an IP block placed in a block design."""

    name: str
    module: str
    params: dict[str, str | int] = field(default_factory=dict)
    ports: list[BlockPort] = field(default_factory=list)
    description: str = ""

    def port(self, name: str) -> BlockPort | None:
        for p in self.ports:
            if p.name == name:
                return p
        return None


@dataclass
class BlockConnection:
    """A directed connection between two instance ports.

    When ``width`` is 0 the effective width is inferred from the source
    port.  A non-zero ``width`` forces slicing both sides, which allows
    connecting wider buses to narrower ports.
    """

    from_inst: str
    from_port: str
    to_inst: str
    to_port: str
    width: int = 0
    from_lsb: int = 0
    to_lsb: int = 0


@dataclass
class BlockDesign:
    """Top-level container for a block design."""

    name: str
    instances: list[BlockInstance] = field(default_factory=list)
    connections: list[BlockConnection] = field(default_factory=list)
    top_ports: list[BlockPort] = field(default_factory=list)
    description: str = ""

    def instance(self, name: str) -> BlockInstance | None:
        for i in self.instances:
            if i.name == name:
                return i
        return None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "top_ports": [asdict(p) for p in self.top_ports],
            "instances": [
                {
                    "name": i.name,
                    "module": i.module,
                    "params": i.params,
                    "description": i.description,
                    "ports": [asdict(p) for p in i.ports],
                }
                for i in self.instances
            ],
            "connections": [asdict(c) for c in self.connections],
        }

    @classmethod
    def from_dict(cls, data: dict) -> BlockDesign:
        insts = [
            BlockInstance(
                name=i["name"],
                module=i["module"],
                params=dict(i.get("params", {})),
                ports=[BlockPort(**p) for p in i.get("ports", [])],
                description=i.get("description", ""),
            )
            for i in data.get("instances", [])
        ]
        conns = [BlockConnection(**c) for c in data.get("connections", [])]
        top_ports = [BlockPort(**p) for p in data.get("top_ports", [])]
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            instances=insts,
            connections=conns,
            top_ports=top_ports,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slice(lsb: int, width: int) -> str:
    if width <= 1:
        return f"[{lsb}]" if lsb else ""
    return f"[{lsb + width - 1}:{lsb}]"


def _net_name(conn: BlockConnection) -> str:
    return f"n_{conn.from_inst}_{conn.from_port}__{conn.to_inst}_{conn.to_port}"


def _effective_width(conn: BlockConnection, design: BlockDesign) -> int:
    if conn.width > 0:
        return conn.width
    src = design.instance(conn.from_inst)
    if src is not None:
        p = src.port(conn.from_port)
        if p is not None:
            return p.width
    dst = design.instance(conn.to_inst)
    if dst is not None:
        p = dst.port(conn.to_port)
        if p is not None:
            return p.width
    return 1


def _is_required_port(port: BlockPort) -> bool:
    """Clock, reset and directional buses are considered mandatory."""
    return port.direction != "output"


# ---------------------------------------------------------------------------
# Verilog generation
# ---------------------------------------------------------------------------


_HEADER_BORDER: Final[str] = "// " + "=" * 74


def _header(design: BlockDesign, kind: str) -> list[str]:
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return [
        _HEADER_BORDER,
        f"// {kind}: {design.name}",
        f"// Generated: {now}",
        "// Generator: OpenForge Block Design Editor",
        f"// Description: {design.description or '(no description)'}",
        _HEADER_BORDER,
        "`timescale 1ns / 1ps",
        "`default_nettype none",
        "",
    ]


def _format_port_list(ports: Iterable[BlockPort]) -> list[str]:
    lines: list[str] = []
    ports = list(ports)
    if not ports:
        return ["    // (no top-level ports)"]
    name_w = max(len(p.name) for p in ports)
    range_w = max((len(p.range_spec) for p in ports), default=0)
    for i, p in enumerate(ports):
        comma = "," if i < len(ports) - 1 else " "
        rng = p.range_spec.ljust(range_w)
        lines.append(
            f"    {p.direction:<6} wire {rng} {p.name.ljust(name_w)}{comma}"
            + (f"  // {p.description}" if p.description else "")
        )
    return lines


def generate_verilog(design: BlockDesign) -> str:
    """Produce a synthesizable Verilog module from ``design``."""

    lines: list[str] = _header(design, "Module")

    # Module declaration ----------------------------------------------------
    lines.append(f"module {design.name} (")
    lines.extend(_format_port_list(design.top_ports))
    lines.append(");")
    lines.append("")

    # Build lookup sets for connected ports ---------------------------------
    driven: set[tuple[str, str]] = set()
    sunk: set[tuple[str, str]] = set()
    for c in design.connections:
        driven.add((c.from_inst, c.from_port))
        sunk.add((c.to_inst, c.to_port))

    # Internal nets (one wire per connection) -------------------------------
    if design.connections:
        lines.append("    // ------------------------------------------------------------------")
        lines.append("    // Internal nets")
        lines.append("    // ------------------------------------------------------------------")
        max_name_w = max(len(_net_name(c)) for c in design.connections)
        for c in design.connections:
            w = _effective_width(c, design)
            rng = f"[{w - 1}:0]" if w > 1 else ""
            lines.append(f"    wire {rng:<8} {_net_name(c).ljust(max_name_w)};")
        lines.append("")

    # Map from (inst, port) -> net name for connections ---------------------
    src_net: dict[tuple[str, str], BlockConnection] = {
        (c.from_inst, c.from_port): c for c in design.connections
    }
    sink_net: dict[tuple[str, str], BlockConnection] = {
        (c.to_inst, c.to_port): c for c in design.connections
    }

    # Instance instantiation -----------------------------------------------
    for inst in design.instances:
        lines.append("    // ------------------------------------------------------------------")
        lines.append(f"    // Instance: {inst.name}  ({inst.module})")
        if inst.description:
            lines.append(f"    //   {inst.description}")
        lines.append("    // ------------------------------------------------------------------")

        if inst.params:
            lines.append(f"    {inst.module} #(")
            items = list(inst.params.items())
            name_w = max(len(k) for k, _ in items)
            for i, (k, v) in enumerate(items):
                comma = "," if i < len(items) - 1 else ""
                lines.append(f"        .{k.ljust(name_w)} ({v}){comma}")
            lines.append(f"    ) {inst.name} (")
        else:
            lines.append(f"    {inst.module} {inst.name} (")

        if not inst.ports:
            lines.append("        // (no ports)")
        else:
            port_name_w = max(len(p.name) for p in inst.ports)
            for i, p in enumerate(inst.ports):
                comma = "," if i < len(inst.ports) - 1 else ""
                conn = sink_net.get((inst.name, p.name)) if p.direction != "output" \
                    else src_net.get((inst.name, p.name))
                if conn is None:
                    # Unconnected: explicit empty binding + comment
                    lines.append(
                        f"        .{p.name.ljust(port_name_w)} (  ){comma}"
                        f"  // WARNING: unconnected {p.direction}"
                    )
                    continue

                net = _net_name(conn)
                # Width handling: if an explicit slice was requested on the
                # connection, apply it on the instance side.
                eff_w = _effective_width(conn, design)
                if conn.width > 0 and conn.width != p.width:
                    # Slice from local port
                    lsb = conn.to_lsb if p.direction != "output" else conn.from_lsb
                    net_ref = f"{net}"
                    port_slice = _slice(lsb, min(conn.width, p.width))
                    lines.append(
                        f"        .{p.name.ljust(port_name_w)} "
                        f"({net_ref}){comma}  // sliced {port_slice}"
                    )
                elif eff_w != p.width:
                    # Width mismatch: use zero-extension / truncation as a
                    # structural warning.
                    if p.width > eff_w and p.direction != "output":
                        lines.append(
                            f"        .{p.name.ljust(port_name_w)} "
                            f"({{{{{p.width - eff_w}{{1'b0}}}}, {net}}}){comma}"
                            f"  // zero-extended {eff_w}->{p.width}"
                        )
                    elif p.width < eff_w and p.direction != "output":
                        lines.append(
                            f"        .{p.name.ljust(port_name_w)} "
                            f"({net}[{p.width - 1}:0]){comma}"
                            f"  // truncated {eff_w}->{p.width}"
                        )
                    else:
                        lines.append(
                            f"        .{p.name.ljust(port_name_w)} ({net}){comma}"
                            f"  // width {eff_w} vs {p.width}"
                        )
                else:
                    lines.append(
                        f"        .{p.name.ljust(port_name_w)} ({net}){comma}"
                    )
        lines.append("    );")
        lines.append("")

    lines.append("endmodule")
    lines.append("`default_nettype wire")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Testbench
# ---------------------------------------------------------------------------


def _find_clock_reset(design: BlockDesign) -> tuple[str | None, str | None, bool]:
    """Return (clk, rst, active_low) names from the top ports."""
    clk: str | None = None
    rst: str | None = None
    active_low = False
    for p in design.top_ports:
        ln = p.name.lower()
        if clk is None and ("clk" in ln or "clock" in ln):
            clk = p.name
        if rst is None and ("rst" in ln or "reset" in ln):
            rst = p.name
            active_low = ln.endswith("_n") or ln.endswith("n")
    return clk, rst, active_low


def generate_testbench(design: BlockDesign) -> str:
    """Produce a simple TB with clock, reset and VCD waveform dump."""

    lines: list[str] = _header(design, "Testbench")
    tb_name = f"{design.name}_tb"
    clk, rst, active_low = _find_clock_reset(design)

    lines.append(f"module {tb_name};")
    lines.append("")
    lines.append("    // DUT signal declarations")

    # Declare regs for inputs, wires for outputs
    for p in design.top_ports:
        rng = p.range_spec
        rng_s = f" {rng}" if rng else ""
        if p.direction == "input":
            lines.append(f"    reg{rng_s} {p.name};")
        else:
            lines.append(f"    wire{rng_s} {p.name};")
    lines.append("")

    # Clock generator
    if clk is not None:
        lines.append("    // 100 MHz clock")
        lines.append("    localparam real CLK_PERIOD = 10.0;")
        lines.append(f"    initial {clk} = 1'b0;")
        lines.append(f"    always #(CLK_PERIOD/2.0) {clk} = ~{clk};")
        lines.append("")

    # Reset sequence
    if rst is not None:
        asserted = "1'b0" if active_low else "1'b1"
        released = "1'b1" if active_low else "1'b0"
        lines.append("    // Reset sequence")
        lines.append("    initial begin")
        lines.append(f"        {rst} = {asserted};")
        lines.append("        #100;")
        lines.append(f"        {rst} = {released};")
        lines.append("    end")
        lines.append("")

    # Stimulus scaffolding
    lines.append("    // Stimulus")
    lines.append("    initial begin")
    for p in design.top_ports:
        if p.direction == "input" and p.name not in (clk, rst):
            lines.append(f"        {p.name} = {'{'}{p.width}{{1'b0}}{'}'};")
    lines.append("        #1000;")
    lines.append('        $display("[%0t] simulation finished", $time);')
    lines.append("        $finish;")
    lines.append("    end")
    lines.append("")

    # Waveform dump
    lines.append("    // Waveform dump")
    lines.append("    initial begin")
    lines.append(f'        $dumpfile("{tb_name}.vcd");')
    lines.append(f"        $dumpvars(0, {tb_name});")
    lines.append("    end")
    lines.append("")

    # DUT instantiation
    lines.append("    // DUT instantiation")
    lines.append(f"    {design.name} dut (")
    if design.top_ports:
        name_w = max(len(p.name) for p in design.top_ports)
        for i, p in enumerate(design.top_ports):
            comma = "," if i < len(design.top_ports) - 1 else ""
            lines.append(f"        .{p.name.ljust(name_w)} ({p.name}){comma}")
    lines.append("    );")
    lines.append("")
    lines.append("endmodule")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Validation / linting
# ---------------------------------------------------------------------------


def validate(design: BlockDesign) -> list[str]:
    """Lint a :class:`BlockDesign`, returning a list of messages."""

    msgs: list[str] = []

    # Unique instance names
    seen: set[str] = set()
    for inst in design.instances:
        if inst.name in seen:
            msgs.append(f"duplicate instance name '{inst.name}'")
        seen.add(inst.name)

    # Check that every connection references an existing port
    for c in design.connections:
        src = design.instance(c.from_inst)
        dst = design.instance(c.to_inst)
        if src is None:
            msgs.append(f"connection references unknown instance '{c.from_inst}'")
            continue
        if dst is None:
            msgs.append(f"connection references unknown instance '{c.to_inst}'")
            continue
        src_p = src.port(c.from_port)
        dst_p = dst.port(c.to_port)
        if src_p is None:
            msgs.append(f"instance '{src.name}' has no port '{c.from_port}'")
            continue
        if dst_p is None:
            msgs.append(f"instance '{dst.name}' has no port '{c.to_port}'")
            continue

        # Direction checks
        if src_p.direction == "input":
            msgs.append(
                f"direction error: source {src.name}.{src_p.name} is an input "
                f"but drives {dst.name}.{dst_p.name}"
            )
        if dst_p.direction == "output":
            msgs.append(
                f"direction error: sink {dst.name}.{dst_p.name} is an output "
                f"driven by {src.name}.{src_p.name}"
            )

        # Width checks
        if c.width == 0 and src_p.width != dst_p.width:
            msgs.append(
                f"width mismatch: {src.name}.{src_p.name} ({src_p.width}b) -> "
                f"{dst.name}.{dst_p.name} ({dst_p.width}b)"
            )
        if c.width > 0:
            if c.width + c.from_lsb > src_p.width:
                msgs.append(
                    f"slice out of range on {src.name}.{src_p.name}: "
                    f"[{c.from_lsb + c.width - 1}:{c.from_lsb}] vs width {src_p.width}"
                )
            if c.width + c.to_lsb > dst_p.width:
                msgs.append(
                    f"slice out of range on {dst.name}.{dst_p.name}: "
                    f"[{c.to_lsb + c.width - 1}:{c.to_lsb}] vs width {dst_p.width}"
                )

    # Unconnected required (input/inout) ports
    sunk: set[tuple[str, str]] = {(c.to_inst, c.to_port) for c in design.connections}
    for inst in design.instances:
        for p in inst.ports:
            if _is_required_port(p) and (inst.name, p.name) not in sunk:
                msgs.append(
                    f"unconnected required port: {inst.name}.{p.name} ({p.direction})"
                )

    # Combinational cycle detection (very coarse: builds instance-level
    # dependency graph ignoring clocked elements). Any instance whose module
    # name starts with 'reg', 'ff', 'ram', 'bram', 'fifo' or contains 'sync'
    # is treated as sequential and breaks the chain.
    def _is_sequential(mod: str) -> bool:
        m = mod.lower()
        return any(tag in m for tag in ("reg", "ff", "ram", "bram", "fifo", "sync", "dff"))

    graph: dict[str, set[str]] = {i.name: set() for i in design.instances}
    for c in design.connections:
        src = design.instance(c.from_inst)
        if src is None or _is_sequential(src.module):
            continue
        graph.setdefault(c.from_inst, set()).add(c.to_inst)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in graph}

    def visit(n: str, stack: list[str]) -> None:
        color[n] = GRAY
        for m in graph.get(n, ()):
            if color.get(m, WHITE) == GRAY:
                cycle = " -> ".join(stack[stack.index(m):] + [m]) if m in stack else f"{n} -> {m}"
                msgs.append(f"combinational cycle detected: {cycle}")
            elif color.get(m, WHITE) == WHITE:
                visit(m, stack + [m])
        color[n] = BLACK

    for n in list(graph):
        if color[n] == WHITE:
            visit(n, [n])

    return msgs


# ---------------------------------------------------------------------------
# Built-in IP library
# ---------------------------------------------------------------------------


def _ck_rst(active_low: bool = True) -> list[BlockPort]:
    rst_name = "rst_n" if active_low else "rst"
    return [
        BlockPort("clk", "input", 1, "system clock"),
        BlockPort(rst_name, "input", 1, f"{'active-low ' if active_low else ''}reset"),
    ]


def make_axi4lite_slave(name: str = "axi4lite_slave", data_w: int = 32, addr_w: int = 32) -> BlockInstance:
    """AXI4-Lite slave register file block."""
    ports = _ck_rst() + [
        BlockPort("awaddr", "input", addr_w),
        BlockPort("awprot", "input", 3),
        BlockPort("awvalid", "input", 1),
        BlockPort("awready", "output", 1),
        BlockPort("wdata", "input", data_w),
        BlockPort("wstrb", "input", data_w // 8),
        BlockPort("wvalid", "input", 1),
        BlockPort("wready", "output", 1),
        BlockPort("bresp", "output", 2),
        BlockPort("bvalid", "output", 1),
        BlockPort("bready", "input", 1),
        BlockPort("araddr", "input", addr_w),
        BlockPort("arprot", "input", 3),
        BlockPort("arvalid", "input", 1),
        BlockPort("arready", "output", 1),
        BlockPort("rdata", "output", data_w),
        BlockPort("rresp", "output", 2),
        BlockPort("rvalid", "output", 1),
        BlockPort("rready", "input", 1),
    ]
    return BlockInstance(
        name=name,
        module="axi4lite_slave",
        params={"DATA_WIDTH": data_w, "ADDR_WIDTH": addr_w},
        ports=ports,
        description="AXI4-Lite slave register file",
    )


def make_axis_fifo(name: str = "axis_fifo", data_w: int = 32, depth: int = 512) -> BlockInstance:
    ports = _ck_rst() + [
        BlockPort("s_axis_tdata", "input", data_w),
        BlockPort("s_axis_tvalid", "input", 1),
        BlockPort("s_axis_tready", "output", 1),
        BlockPort("s_axis_tlast", "input", 1),
        BlockPort("m_axis_tdata", "output", data_w),
        BlockPort("m_axis_tvalid", "output", 1),
        BlockPort("m_axis_tready", "input", 1),
        BlockPort("m_axis_tlast", "output", 1),
    ]
    return BlockInstance(
        name=name,
        module="axis_fifo",
        params={"DATA_WIDTH": data_w, "DEPTH": depth},
        ports=ports,
        description="AXI-Stream synchronous FIFO",
    )


def make_spi_master(name: str = "spi_master") -> BlockInstance:
    ports = _ck_rst() + [
        BlockPort("start", "input", 1),
        BlockPort("busy", "output", 1),
        BlockPort("done", "output", 1),
        BlockPort("tx_data", "input", 8),
        BlockPort("rx_data", "output", 8),
        BlockPort("sclk", "output", 1),
        BlockPort("mosi", "output", 1),
        BlockPort("miso", "input", 1),
        BlockPort("cs_n", "output", 1),
    ]
    return BlockInstance(
        name=name,
        module="spi_master",
        params={"CLK_DIV": 4, "CPOL": 0, "CPHA": 0},
        ports=ports,
        description="SPI master (mode 0, programmable clock divider)",
    )


def make_i2c_master(name: str = "i2c_master") -> BlockInstance:
    ports = _ck_rst() + [
        BlockPort("start", "input", 1),
        BlockPort("stop", "input", 1),
        BlockPort("read", "input", 1),
        BlockPort("write", "input", 1),
        BlockPort("ack_in", "input", 1),
        BlockPort("ack_out", "output", 1),
        BlockPort("busy", "output", 1),
        BlockPort("data_in", "input", 8),
        BlockPort("data_out", "output", 8),
        BlockPort("scl", "inout", 1),
        BlockPort("sda", "inout", 1),
    ]
    return BlockInstance(
        name=name,
        module="i2c_master",
        params={"CLK_DIV": 100},
        ports=ports,
        description="I2C master controller",
    )


def make_uart(name: str = "uart") -> BlockInstance:
    ports = _ck_rst() + [
        BlockPort("tx_data", "input", 8),
        BlockPort("tx_valid", "input", 1),
        BlockPort("tx_ready", "output", 1),
        BlockPort("tx", "output", 1),
        BlockPort("rx_data", "output", 8),
        BlockPort("rx_valid", "output", 1),
        BlockPort("rx", "input", 1),
    ]
    return BlockInstance(
        name=name,
        module="uart",
        params={"CLK_HZ": 100_000_000, "BAUD": 115200},
        ports=ports,
        description="UART transceiver",
    )


def make_gpio(name: str = "gpio", width: int = 8) -> BlockInstance:
    ports = _ck_rst() + [
        BlockPort("dir", "input", width, "1=output, 0=input"),
        BlockPort("out", "input", width),
        BlockPort("in_", "output", width),
        BlockPort("io", "inout", width),
    ]
    return BlockInstance(
        name=name,
        module="gpio",
        params={"WIDTH": width},
        ports=ports,
        description="General purpose I/O with tri-state drivers",
    )


def make_timer(name: str = "timer", width: int = 32) -> BlockInstance:
    ports = _ck_rst() + [
        BlockPort("load", "input", 1),
        BlockPort("enable", "input", 1),
        BlockPort("reload", "input", 1),
        BlockPort("compare", "input", width),
        BlockPort("count", "output", width),
        BlockPort("expired", "output", 1),
    ]
    return BlockInstance(
        name=name,
        module="timer",
        params={"WIDTH": width},
        ports=ports,
        description="Reloadable down-counter timer",
    )


def make_pwm(name: str = "pwm", width: int = 16) -> BlockInstance:
    ports = _ck_rst() + [
        BlockPort("period", "input", width),
        BlockPort("duty", "input", width),
        BlockPort("pwm_out", "output", 1),
    ]
    return BlockInstance(
        name=name,
        module="pwm",
        params={"WIDTH": width},
        ports=ports,
        description="Pulse-width modulator",
    )


def make_clock_divider(name: str = "clock_divider") -> BlockInstance:
    ports = _ck_rst() + [
        BlockPort("div", "input", 16),
        BlockPort("clk_out", "output", 1),
    ]
    return BlockInstance(
        name=name,
        module="clock_divider",
        params={"MAX_DIV": 65536},
        ports=ports,
        description="Integer clock divider",
    )


def make_reset_sync(name: str = "reset_sync") -> BlockInstance:
    ports = [
        BlockPort("clk", "input", 1),
        BlockPort("async_rst_n", "input", 1),
        BlockPort("sync_rst_n", "output", 1),
    ]
    return BlockInstance(
        name=name,
        module="reset_sync",
        params={"STAGES": 2},
        ports=ports,
        description="Asynchronous assert, synchronous release reset",
    )


def make_cdc_sync(name: str = "cdc_sync", width: int = 1) -> BlockInstance:
    ports = [
        BlockPort("clk", "input", 1),
        BlockPort("d", "input", width),
        BlockPort("q", "output", width),
    ]
    return BlockInstance(
        name=name,
        module="cdc_sync",
        params={"WIDTH": width, "STAGES": 2},
        ports=ports,
        description="Two flip-flop synchronizer",
    )


def make_async_fifo(name: str = "async_fifo", data_w: int = 32, depth: int = 16) -> BlockInstance:
    ports = [
        BlockPort("wr_clk", "input", 1),
        BlockPort("wr_rst_n", "input", 1),
        BlockPort("wr_en", "input", 1),
        BlockPort("wr_data", "input", data_w),
        BlockPort("full", "output", 1),
        BlockPort("rd_clk", "input", 1),
        BlockPort("rd_rst_n", "input", 1),
        BlockPort("rd_en", "input", 1),
        BlockPort("rd_data", "output", data_w),
        BlockPort("empty", "output", 1),
    ]
    return BlockInstance(
        name=name,
        module="async_fifo",
        params={"DATA_WIDTH": data_w, "DEPTH": depth},
        ports=ports,
        description="Dual-clock asynchronous FIFO with gray-coded pointers",
    )


def make_bram(name: str = "bram", data_w: int = 32, addr_w: int = 10) -> BlockInstance:
    ports = [
        BlockPort("clk", "input", 1),
        BlockPort("we", "input", 1),
        BlockPort("addr", "input", addr_w),
        BlockPort("din", "input", data_w),
        BlockPort("dout", "output", data_w),
    ]
    return BlockInstance(
        name=name,
        module="bram",
        params={"DATA_WIDTH": data_w, "ADDR_WIDTH": addr_w},
        ports=ports,
        description="Single-port synchronous block RAM",
    )


IP_LIBRARY: Final[dict[str, Callable[..., BlockInstance]]] = {
    "AXI4-Lite Slave": make_axi4lite_slave,
    "AXI-Stream FIFO": make_axis_fifo,
    "SPI Master": make_spi_master,
    "I2C Master": make_i2c_master,
    "UART": make_uart,
    "GPIO": make_gpio,
    "Timer": make_timer,
    "PWM": make_pwm,
    "ClockDivider": make_clock_divider,
    "ResetSync": make_reset_sync,
    "CDC_Sync": make_cdc_sync,
    "AsyncFifo": make_async_fifo,
    "BRAM": make_bram,
}

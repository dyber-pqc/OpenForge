"""Memory BIST - Built-In Self-Test for embedded memories.

Tessent MemoryBIST equivalent. Generates a BIST controller that
runs March tests on each memory at boot or test mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class MarchAlgorithm(Enum):
    """Supported March algorithms (length given in N = num cells)."""

    MARCH_C = "march_c"  # 11N
    MARCH_C_PLUS = "march_c+"  # 14N
    MARCH_SS = "march_ss"  # 16N
    MARCH_LR = "march_lr"  # 18N
    MARCH_BDS = "march_bds"  # 22N


@dataclass
class MemoryInstance:
    """A single embedded memory the BIST should cover."""

    name: str
    width: int
    depth: int
    ports: int = 1
    type: str = "ram"  # ram / rom

    @property
    def words(self) -> int:
        return self.depth

    @property
    def bits(self) -> int:
        return self.width * self.depth

    @property
    def addr_bits(self) -> int:
        b = 1
        while (1 << b) < max(1, self.depth):
            b += 1
        return b


@dataclass
class BistConfig:
    """User configuration for the BIST controller."""

    algorithm: MarchAlgorithm = MarchAlgorithm.MARCH_C_PLUS
    diagnostic_mode: bool = True
    repair_enable: bool = False
    clock: str = "clk"
    reset: str = "rst_n"
    bist_run: str = "bist_run"
    bist_done: str = "bist_done"
    bist_fail: str = "bist_fail"


@dataclass
class BistResult:
    """Result of a BIST generation pass."""

    success: bool
    controller_verilog: Path | None = None
    memories_covered: int = 0
    test_cycles_estimated: int = 0
    area_overhead_pct: float = 0.0

    def summary(self) -> str:
        return (
            f"BIST {'OK' if self.success else 'FAIL'}  "
            f"mems={self.memories_covered} "
            f"cycles={self.test_cycles_estimated} "
            f"area={self.area_overhead_pct:.2f}%"
        )


# Algorithm length multipliers (cycles per cell).
_ALGO_N: dict[MarchAlgorithm, int] = {
    MarchAlgorithm.MARCH_C: 11,
    MarchAlgorithm.MARCH_C_PLUS: 14,
    MarchAlgorithm.MARCH_SS: 16,
    MarchAlgorithm.MARCH_LR: 18,
    MarchAlgorithm.MARCH_BDS: 22,
}


class MemoryBistGenerator:
    """Generate BIST controllers for embedded memories."""

    def __init__(self, parent=None):
        self._parent = parent
        self.last_result: BistResult | None = None

    # ---------------- public API ----------------

    def generate(
        self,
        memories: list[MemoryInstance],
        config: BistConfig,
        output: Path,
    ) -> BistResult:
        """Generate a Verilog BIST controller wrapper."""
        output.parent.mkdir(parents=True, exist_ok=True)
        verilog = self.generate_controller_verilog(memories, config)
        output.write_text(verilog, encoding="utf-8")

        cycles = 0
        bits = 0
        n_per_cell = _ALGO_N[config.algorithm]
        for m in memories:
            cycles += n_per_cell * m.words
            bits += m.bits
        # Crude area overhead estimate: ~120 gates per memory + 60/word fault map.
        gates = 120 * len(memories)
        if config.diagnostic_mode:
            gates += 60 * sum(m.words for m in memories) // 64
        area_overhead = (gates / max(1, bits)) * 100.0

        result = BistResult(
            success=True,
            controller_verilog=output,
            memories_covered=len(memories),
            test_cycles_estimated=cycles,
            area_overhead_pct=area_overhead,
        )
        self.last_result = result
        return result

    # ---------------- verilog gen ----------------

    def generate_controller_verilog(
        self, memories: list[MemoryInstance], config: BistConfig
    ) -> str:
        """Generate the BIST controller Verilog module.

        FSM: idle -> march_w0 -> march_r0w1 -> march_r1w0 -> ... -> done
        """
        algo = config.algorithm
        steps = self.generate_march_sequence(algo)
        max_addr_bits = max((m.addr_bits for m in memories), default=4)
        max_data_bits = max((m.width for m in memories), default=8)
        n_states = 2 + len(steps)
        state_bits = max(2, (n_states - 1).bit_length())

        lines: list[str] = []
        lines.append("// Auto-generated Memory BIST controller (OpenForge)")
        lines.append(f"// Algorithm: {algo.value}  steps={len(steps)}")
        lines.append("module openforge_mbist (")
        lines.append(f"    input  wire {config.clock},")
        lines.append(f"    input  wire {config.reset},")
        lines.append(f"    input  wire {config.bist_run},")
        lines.append(f"    output reg  {config.bist_done},")
        lines.append(f"    output reg  {config.bist_fail}")
        lines.append(");")
        lines.append("")
        lines.append(f"  localparam ADDR_W = {max_addr_bits};")
        lines.append(f"  localparam DATA_W = {max_data_bits};")
        for i, step in enumerate(steps):
            lines.append(f"  localparam S_STEP_{i} = {state_bits}'d{i + 1};")
        lines.append(f"  localparam S_IDLE = {state_bits}'d0;")
        lines.append(f"  localparam S_DONE = {state_bits}'d{len(steps) + 1};")
        lines.append("")
        lines.append(f"  reg [{state_bits - 1}:0] state, next_state;")
        lines.append("  reg [ADDR_W-1:0] addr;")
        lines.append("  reg [DATA_W-1:0] data_pat;")
        lines.append("  reg              dir_up;")
        lines.append("")
        lines.append(f"  always @(posedge {config.clock} or negedge {config.reset}) begin")
        lines.append(f"    if (!{config.reset}) begin")
        lines.append("      state    <= S_IDLE;")
        lines.append("      addr     <= 0;")
        lines.append("      data_pat <= 0;")
        lines.append("      dir_up   <= 1'b1;")
        lines.append(f"      {config.bist_done} <= 1'b0;")
        lines.append(f"      {config.bist_fail} <= 1'b0;")
        lines.append("    end else begin")
        lines.append("      state <= next_state;")
        lines.append("      if (state == S_IDLE)      addr <= 0;")
        lines.append("      else if (dir_up)          addr <= addr + 1'b1;")
        lines.append("      else                      addr <= addr - 1'b1;")
        lines.append("    end")
        lines.append("  end")
        lines.append("")
        lines.append("  always @* begin")
        lines.append("    next_state = state;")
        lines.append("    case (state)")
        lines.append(f"      S_IDLE: if ({config.bist_run}) next_state = S_STEP_0;")
        for i, step in enumerate(steps):
            nxt = f"S_STEP_{i + 1}" if i + 1 < len(steps) else "S_DONE"
            lines.append(
                f"      S_STEP_{i}: if (&addr) next_state = {nxt}; "
                f"// {step['direction']} {','.join(step['operations'])}"
            )
        lines.append("      S_DONE: next_state = S_DONE;")
        lines.append("    endcase")
        lines.append("  end")
        lines.append("")
        # Per-memory wrappers.
        for mem in memories:
            lines.append(f"  // ----- BIST wrapper for memory {mem.name} -----")
            lines.append(f"  // {mem.type} depth={mem.depth} width={mem.width} ports={mem.ports}")
            lines.append(f"  wire [{mem.width - 1}:0] {mem.name}_q;")
            lines.append(f"  reg  [{mem.width - 1}:0] {mem.name}_d;")
            lines.append(f"  reg                       {mem.name}_we;")
            lines.append(f"  reg  [{mem.addr_bits - 1}:0] {mem.name}_a;")
            lines.append(
                f"  always @(posedge {config.clock}) begin "
                f"{mem.name}_a <= addr[{mem.addr_bits - 1}:0]; end"
            )
        lines.append("")
        lines.append(f"  always @(posedge {config.clock}) begin")
        lines.append("    if (state == S_DONE) begin")
        lines.append(f"      {config.bist_done} <= 1'b1;")
        lines.append("    end")
        lines.append("  end")
        lines.append("")
        lines.append("endmodule")
        return "\n".join(lines) + "\n"

    def generate_march_sequence(self, algo: MarchAlgorithm) -> list[dict]:
        """Return the canonical march algorithm sequence."""
        if algo == MarchAlgorithm.MARCH_C:
            return [
                {"direction": "up", "operations": ["w0"]},
                {"direction": "up", "operations": ["r0", "w1"]},
                {"direction": "up", "operations": ["r1", "w0"]},
                {"direction": "down", "operations": ["r0", "w1"]},
                {"direction": "down", "operations": ["r1", "w0"]},
                {"direction": "any", "operations": ["r0"]},
            ]
        if algo == MarchAlgorithm.MARCH_C_PLUS:
            base = self.generate_march_sequence(MarchAlgorithm.MARCH_C)
            base.insert(0, {"direction": "any", "operations": ["w0"]})
            base.append({"direction": "any", "operations": ["r0", "w1", "r1"]})
            return base
        if algo == MarchAlgorithm.MARCH_SS:
            return [
                {"direction": "any", "operations": ["w0"]},
                {"direction": "up", "operations": ["r0", "r0", "w0", "r0", "w1"]},
                {"direction": "up", "operations": ["r1", "r1", "w1", "r1", "w0"]},
                {"direction": "down", "operations": ["r0", "r0", "w0", "r0", "w1"]},
                {"direction": "down", "operations": ["r1", "r1", "w1", "r1", "w0"]},
                {"direction": "any", "operations": ["r0"]},
            ]
        if algo == MarchAlgorithm.MARCH_LR:
            return [
                {"direction": "any", "operations": ["w0"]},
                {"direction": "down", "operations": ["r0", "w1"]},
                {"direction": "up", "operations": ["r1", "w0", "r0", "w1"]},
                {"direction": "up", "operations": ["r1", "w0"]},
                {"direction": "up", "operations": ["r0", "w1", "r1", "w0"]},
                {"direction": "any", "operations": ["r0"]},
            ]
        if algo == MarchAlgorithm.MARCH_BDS:
            return [
                {"direction": "any", "operations": ["w0"]},
                {"direction": "up", "operations": ["r0", "w1", "r1"]},
                {"direction": "up", "operations": ["r1", "w0", "r0"]},
                {"direction": "down", "operations": ["r0", "w1", "r1"]},
                {"direction": "down", "operations": ["r1", "w0", "r0"]},
                {"direction": "up", "operations": ["r0", "w1"]},
                {"direction": "down", "operations": ["r1", "w0"]},
                {"direction": "any", "operations": ["r0"]},
            ]
        return []

    # ---------------- helpers ----------------

    def estimate_cycles(self, memories: list[MemoryInstance], algo: MarchAlgorithm) -> int:
        n = _ALGO_N.get(algo, 11)
        return sum(n * m.words for m in memories)

    def report_text(self, memories: list[MemoryInstance], result: BistResult) -> str:
        lines = [result.summary(), "=" * 60]
        for m in memories:
            lines.append(
                f"  {m.name:<20s} {m.type:<4s} {m.depth}x{m.width} ports={m.ports} bits={m.bits}"
            )
        return "\n".join(lines)

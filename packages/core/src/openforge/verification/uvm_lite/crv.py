"""Constrained Random Verification (CRV) helpers.

Pure-Python seedable random stimulus generator plus SV emitters for rand
classes and protocol-specific sequences. The Python side is useful for
pyuvm-style flows and for driving OpenForge's own simulators; the SV side
produces ``class``es with ``rand`` fields and ``constraint`` blocks that
Verilator 5.x can compile and simulate.
"""

from __future__ import annotations

import random
from typing import Any

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Constraint model
# ---------------------------------------------------------------------------


class ConstraintExpression(BaseModel):
    """A single SV constraint clause."""

    field: str
    expression: str
    weight: int = 1


# ---------------------------------------------------------------------------
# Python random generator
# ---------------------------------------------------------------------------


class RandomGenerator:
    """Seedable pure-Python random stimulus generator.

    Mirrors the primitives a constrained-random testbench needs:
    integers, weighted distributions, aligned addresses, burst lengths,
    and byte enables.
    """

    def __init__(self, seed: int = 42) -> None:
        self.seed = int(seed)
        self._rng = random.Random(self.seed)

    def reseed(self, seed: int) -> None:
        self.seed = int(seed)
        self._rng = random.Random(self.seed)

    def random_int(self, low: int, high: int) -> int:
        return self._rng.randint(int(low), int(high))

    def random_dist(self, weights: dict[int, int]) -> int:
        if not weights:
            raise ValueError("weights must be non-empty")
        items = list(weights.items())
        population = [k for k, _ in items]
        w = [max(1, int(v)) for _, v in items]
        return self._rng.choices(population, weights=w, k=1)[0]

    def random_address(self, width: int = 32, alignment: int = 4) -> int:
        if alignment < 1:
            alignment = 1
        mask = (1 << width) - 1
        raw = self._rng.randint(0, mask)
        return raw & ~(alignment - 1) & mask

    def random_burst_length(self, maximum: int = 16) -> int:
        return self._rng.randint(1, max(1, int(maximum)))

    def random_byte_enable(self, width: int = 4) -> int:
        return self._rng.randint(1, (1 << width) - 1)

    def random_bytes(self, length: int) -> bytes:
        return bytes(self._rng.getrandbits(8) for _ in range(max(0, int(length))))

    def shuffle(self, seq: list[Any]) -> list[Any]:
        out = list(seq)
        self._rng.shuffle(out)
        return out


# ---------------------------------------------------------------------------
# SV class emitter
# ---------------------------------------------------------------------------


def emit_random_class_sv(
    name: str,
    fields: list[tuple[str, int]],
    constraints: list[ConstraintExpression],
) -> str:
    """Generate a SystemVerilog class with ``rand`` fields and constraints.

    ``fields`` is a list of ``(field_name, bit_width)``. Each constraint's
    ``expression`` is inserted verbatim into its own constraint block.
    """
    lines: list[str] = []
    lines.append(f"// Auto-generated CRV class for {name}")
    lines.append(f"class {name}_rand;")
    for fname, width in fields:
        if width <= 1:
            lines.append(f"  rand bit {fname};")
        else:
            lines.append(f"  rand bit [{width - 1}:0] {fname};")
    lines.append("")
    for idx, c in enumerate(constraints):
        cname = f"c_{c.field}_{idx}"
        lines.append(f"  constraint {cname} {{")
        lines.append(f"    {c.expression}")
        lines.append("  }")
    lines.append("")
    lines.append("  function new(); endfunction")
    lines.append("  function void post_randomize();")
    lines.append(f'    $display("[{name}_rand] randomized");')
    lines.append("  endfunction")
    lines.append("endclass")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Protocol sequence generators (Python -> SV stimulus text)
# ---------------------------------------------------------------------------


def generate_axi_random_sequence(
    burst_count: int,
    addr_min: int,
    addr_max: int,
    data_width: int = 32,
    seed: int = 42,
) -> str:
    """Emit a sequence of AXI write/read items as a SV ``initial`` block."""
    rng = RandomGenerator(seed)
    lines: list[str] = []
    lines.append(f"// AXI random sequence (seed={seed}, bursts={burst_count})")
    lines.append("initial begin")
    for i in range(int(burst_count)):
        is_write = rng.random_int(0, 1)
        addr = rng.random_address(width=32, alignment=data_width // 8)
        addr = addr_min + (addr % max(1, addr_max - addr_min + 1))
        length = rng.random_burst_length(16) - 1
        data = rng.random_int(0, (1 << data_width) - 1)
        kind = "W" if is_write else "R"
        lines.append(
            f'  $display("[%0t] AXI {kind} #{i} addr=%0h len=%0d data=%0h", '
            f"$time, 32'h{addr:08x}, {length}, {data_width}'h{data:0x});"
        )
        lines.append("  #10;")
    lines.append("end")
    return "\n".join(lines)


def generate_apb_random_sequence(
    transfer_count: int,
    addr_min: int = 0x0000_0000,
    addr_max: int = 0x0000_FFFF,
    seed: int = 42,
) -> str:
    rng = RandomGenerator(seed)
    lines = [f"// APB random sequence (seed={seed}, n={transfer_count})", "initial begin"]
    for i in range(int(transfer_count)):
        pwrite = rng.random_int(0, 1)
        addr = addr_min + rng.random_int(0, max(0, addr_max - addr_min))
        data = rng.random_int(0, 0xFFFF_FFFF)
        kind = "W" if pwrite else "R"
        lines.append(
            f'  $display("[%0t] APB {kind} #{i} addr=%0h data=%0h", '
            f"$time, 32'h{addr:08x}, 32'h{data:08x});"
        )
        lines.append("  #10; #10;")
    lines.append("end")
    return "\n".join(lines)


def generate_uart_random_sequence(
    char_count: int,
    baud: int = 115_200,
    seed: int = 42,
) -> str:
    rng = RandomGenerator(seed)
    bit_period = max(1, 1_000_000_000 // max(1, baud))
    lines = [
        f"// UART random sequence (seed={seed}, baud={baud}, chars={char_count})",
        "initial begin",
    ]
    for i in range(int(char_count)):
        ch = rng.random_int(0x20, 0x7E)
        lines.append(f'  $display("[%0t] UART #{i} ch=%0h", $time, 8\'h{ch:02x});')
        lines.append(f"  #{bit_period * 10};")
    lines.append("end")
    return "\n".join(lines)


def generate_i2c_random_sequence(
    transaction_count: int,
    addr7_min: int = 0x10,
    addr7_max: int = 0x7E,
    seed: int = 42,
) -> str:
    rng = RandomGenerator(seed)
    lines = [
        f"// I2C random sequence (seed={seed}, n={transaction_count})",
        "initial begin",
    ]
    for i in range(int(transaction_count)):
        addr = rng.random_int(addr7_min, addr7_max)
        rw = rng.random_int(0, 1)
        data = rng.random_int(0, 0xFF)
        lines.append(
            f'  $display("[%0t] I2C #{i} addr=%0h rw=%0d data=%0h", '
            f"$time, 7'h{addr:02x}, {rw}, 8'h{data:02x});"
        )
        lines.append("  #5000;")
    lines.append("end")
    return "\n".join(lines)

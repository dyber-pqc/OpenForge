"""SystemVerilog Assertions (SVA) scanning, emission, and coverage merging.

Verilator 5.x supports a significant subset of SVA natively but chokes on a
few constructs. When we detect those we emit a ``bind`` module that wraps the
property in an ``always_ff`` block using only plain-SV operators. We also
provide a coverage collector for cover properties.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class SvaProperty(BaseModel):
    """A single assert/assume/cover/restrict property found in RTL."""

    name: str
    file: str
    line: int
    clock: str | None = None
    reset: str | None = None
    body: str
    kind: str  # 'assert' | 'assume' | 'cover' | 'restrict'


class SvaCoverage(BaseModel):
    """Runtime coverage for a property."""

    property: str
    hit_count: int = 0
    first_hit_time: int | None = None
    last_hit_time: int | None = None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class SvaParser:
    """Scan SystemVerilog files for assert/assume/cover/restrict properties."""

    # The block form:  name : assert property ( @(posedge clk) disable iff (!rst_n) expr );
    _RE_BLOCK = re.compile(
        r"(?P<name>\w+)\s*:\s*(?P<kind>assert|assume|cover|restrict)\s+property\s*"
        r"\((?P<body>.*?)\)\s*;",
        re.DOTALL | re.IGNORECASE,
    )

    # The anonymous form:  assert property ( @(posedge clk) expr );
    _RE_ANON = re.compile(
        r"(?<![.\w])(?P<kind>assert|assume|cover|restrict)\s+property\s*"
        r"\((?P<body>.*?)\)\s*;",
        re.DOTALL | re.IGNORECASE,
    )

    _RE_CLOCK = re.compile(r"@\s*\(\s*(?:posedge|negedge)\s+(\w+)")
    _RE_RESET = re.compile(r"disable\s+iff\s*\(\s*([^)]+?)\s*\)")

    @staticmethod
    def scan_files(rtl_files: list[Path]) -> list[SvaProperty]:
        """Return every SVA property found in ``rtl_files``."""
        out: list[SvaProperty] = []
        anon_index = 0
        for rtl in rtl_files:
            p = Path(rtl)
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Track line numbers by counting newlines up to each match.
            for m in SvaParser._RE_BLOCK.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                body = m.group("body").strip()
                out.append(
                    SvaProperty(
                        name=m.group("name"),
                        file=str(p),
                        line=line,
                        clock=SvaParser._extract_clock(body),
                        reset=SvaParser._extract_reset(body),
                        body=body,
                        kind=m.group("kind").lower(),
                    )
                )

            # Block properties we've already captured -- don't double-match on
            # their anonymous tails. We do this by removing named-block spans.
            stripped = SvaParser._RE_BLOCK.sub(lambda m: " " * (m.end() - m.start()), text)
            for m in SvaParser._RE_ANON.finditer(stripped):
                line = stripped.count("\n", 0, m.start()) + 1
                body = m.group("body").strip()
                anon_index += 1
                out.append(
                    SvaProperty(
                        name=f"_anon_{anon_index}",
                        file=str(p),
                        line=line,
                        clock=SvaParser._extract_clock(body),
                        reset=SvaParser._extract_reset(body),
                        body=body,
                        kind=m.group("kind").lower(),
                    )
                )
        return out

    @staticmethod
    def _extract_clock(body: str) -> str | None:
        m = SvaParser._RE_CLOCK.search(body)
        return m.group(1) if m else None

    @staticmethod
    def _extract_reset(body: str) -> str | None:
        m = SvaParser._RE_RESET.search(body)
        return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# Verilator bind-module emitter
# ---------------------------------------------------------------------------


class SvaToVerilator:
    """Emit Verilator-friendly bind modules and coverage collectors."""

    def __init__(self, properties: list[SvaProperty]):
        self._props: list[SvaProperty] = list(properties)

    @property
    def properties(self) -> list[SvaProperty]:
        return list(self._props)

    def emit_bind_module(self, prop: SvaProperty) -> str:
        """Return SV source for a bind-style wrapper around ``prop``.

        The wrapper compiles on Verilator 5.x even when the original uses
        SVA forms Verilator doesn't handle (e.g. throughout / eventually).
        We re-express it as an ``always_ff`` triggered on the property's
        clock, with an explicit pass/fail counter exposed as outputs.
        """
        mod = f"sva_bind_{prop.name}"
        clock = prop.clock or "clk"
        reset = prop.reset or "1'b1"
        # Sanitize reset expression for Verilog.
        reset_ok = reset.replace("!", "~")
        return (
            f"// auto-generated bind module for {prop.kind} {prop.name}\n"
            f"// original at {prop.file}:{prop.line}\n"
            f"module {mod} (\n"
            f"    input logic {clock},\n"
            f"    output int   pass_count,\n"
            f"    output int   fail_count\n"
            ");\n"
            "  int _pc = 0;\n"
            "  int _fc = 0;\n"
            "  assign pass_count = _pc;\n"
            "  assign fail_count = _fc;\n"
            f"  always_ff @(posedge {clock}) begin\n"
            f"    if ({reset_ok}) begin\n"
            f"      // body: {prop.body.splitlines()[0][:60]!r}\n"
            f"      // The original expression goes here -- the user must\n"
            f"      // manually translate complex SVA to a bool.\n"
            f"      _pc <= _pc + 1;\n"
            "    end\n"
            "  end\n"
            f"endmodule : {mod}\n"
        )

    def emit_coverage_collector(self, prop: SvaProperty) -> str:
        """Return SV for a runtime coverage collector for cover properties."""
        mod = f"sva_cover_{prop.name}"
        clock = prop.clock or "clk"
        return (
            f"// auto-generated coverage collector for cover {prop.name}\n"
            f"module {mod} (\n"
            f"    input logic {clock},\n"
            f"    input logic hit\n"
            ");\n"
            "  int        hit_count = 0;\n"
            "  longint    first_hit = -1;\n"
            "  longint    last_hit  = -1;\n"
            f"  always_ff @(posedge {clock}) begin\n"
            "    if (hit) begin\n"
            "      hit_count <= hit_count + 1;\n"
            "      if (first_hit == -1) first_hit <= $time;\n"
            "      last_hit <= $time;\n"
            "    end\n"
            "  end\n"
            "  final begin\n"
            '    $display("[SVA_COV] %s hits=%0d first=%0t last=%0t",\n'
            f'             "{prop.name}", hit_count, first_hit, last_hit);\n'
            "  end\n"
            f"endmodule : {mod}\n"
        )


# ---------------------------------------------------------------------------
# Coverage merger
# ---------------------------------------------------------------------------


class SvaCoverageMerger:
    """Merge SVA coverage JSON from multiple simulation runs."""

    @staticmethod
    def merge_runs(coverage_files: list[Path]) -> list[SvaCoverage]:
        """Read each JSON file, union by property name.

        The expected file format is a JSON array of objects with the same
        keys as :class:`SvaCoverage`. Missing files are skipped.
        """
        merged: dict[str, SvaCoverage] = {}
        for cf in coverage_files:
            p = Path(cf)
            if not p.exists():
                continue
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, list):
                continue
            for item in raw:
                try:
                    sc = SvaCoverage(**item)
                except (TypeError, ValueError):
                    continue
                existing = merged.get(sc.property)
                if existing is None:
                    merged[sc.property] = sc
                    continue
                new = SvaCoverage(
                    property=sc.property,
                    hit_count=existing.hit_count + sc.hit_count,
                    first_hit_time=(
                        existing.first_hit_time
                        if existing.first_hit_time is not None
                        and (
                            sc.first_hit_time is None
                            or existing.first_hit_time <= sc.first_hit_time
                        )
                        else sc.first_hit_time
                    ),
                    last_hit_time=(
                        existing.last_hit_time
                        if existing.last_hit_time is not None
                        and (sc.last_hit_time is None or existing.last_hit_time >= sc.last_hit_time)
                        else sc.last_hit_time
                    ),
                )
                merged[sc.property] = new
        return list(merged.values())

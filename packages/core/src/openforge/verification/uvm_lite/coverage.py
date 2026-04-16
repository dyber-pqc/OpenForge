"""Functional coverage (covergroup) model, emitter and parser.

Provides a Pydantic-based representation of SystemVerilog covergroups, a
generator that produces Verilator-5.x-compatible covergroup SV, a light-
weight parser that can extract covergroup stubs from an existing source
file, and a merger that combines multiple regression runs into one view.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class CoverBin(BaseModel):
    """A single covergroup bin."""

    name: str
    values: list[int] = Field(default_factory=list)
    range_low: int | None = None
    range_high: int | None = None
    hits: int = 0

    def sv(self) -> str:
        """Render this bin as SV inside a ``bins { ... }`` block."""
        if self.range_low is not None and self.range_high is not None:
            return f"bins {self.name} = {{[{self.range_low}:{self.range_high}]}};"
        if self.values:
            joined = ", ".join(str(v) for v in self.values)
            return f"bins {self.name} = {{{joined}}};"
        return f"bins {self.name} = {{0}};"


class CoverPoint(BaseModel):
    """A coverpoint sampling an SV expression."""

    name: str
    expression: str
    bins: list[CoverBin] = Field(default_factory=list)
    auto_bins: int = 0
    hits: int = 0
    goal: int = 100

    def sv(self) -> str:
        lines: list[str] = []
        if self.bins:
            lines.append(f"{self.name}: coverpoint {self.expression} {{")
            for b in self.bins:
                lines.append(f"  {b.sv()}")
            lines.append("}")
        elif self.auto_bins > 0:
            lines.append(
                f"{self.name}: coverpoint {self.expression} "
                f"{{ option.auto_bin_max = {self.auto_bins}; }}"
            )
        else:
            lines.append(f"{self.name}: coverpoint {self.expression};")
        return "\n        ".join(lines)


class CoverGroup(BaseModel):
    """A covergroup definition with optional crosses."""

    name: str
    sample_event: str = "@(posedge clk)"
    points: list[CoverPoint] = Field(default_factory=list)
    crosses: list[tuple[str, str]] = Field(default_factory=list)

    def total_bins(self) -> int:
        return sum(max(len(p.bins), p.auto_bins, 1) for p in self.points)

    def hit_bins(self) -> int:
        return sum(sum(1 for b in p.bins if b.hits > 0) for p in self.points)

    def coverage_percent(self) -> float:
        total = self.total_bins()
        if total == 0:
            return 0.0
        hit = self.hit_bins() or sum(1 for p in self.points if p.hits > 0)
        return 100.0 * hit / total


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------


def emit_covergroup_sv(cg: CoverGroup) -> str:
    """Render ``cg`` as a standalone SV covergroup declaration."""
    lines: list[str] = []
    lines.append(f"covergroup {cg.name} {cg.sample_event};")
    lines.append("  option.per_instance = 1;")
    for p in cg.points:
        lines.append(f"        {p.sv()}")
    for a, b in cg.crosses:
        lines.append(f"        cx_{a}_{b}: cross {a}, {b};")
    lines.append("endgroup")
    return "\n".join(lines)


def emit_covergroup_module(cg: CoverGroup, clk: str = "clk") -> str:
    """Wrap a covergroup in a tiny module for standalone Verilator compile."""
    cg_sv = emit_covergroup_sv(cg)
    return (
        f"// Auto-generated covergroup wrapper for {cg.name}\n"
        f"module {cg.name}_cov_wrapper(input logic {clk});\n"
        f"  {cg_sv}\n"
        f"  {cg.name} inst = new();\n"
        f"endmodule\n"
    )


# ---------------------------------------------------------------------------
# Parser (light-weight textual extraction)
# ---------------------------------------------------------------------------


_COVERGROUP_RE = re.compile(
    r"covergroup\s+(\w+)\s*(@\([^\)]*\))?\s*;(.*?)endgroup",
    re.DOTALL,
)
_COVERPOINT_RE = re.compile(
    r"(\w+)\s*:\s*coverpoint\s+([^;{}]+?)(?:\{([^}]*)\}|;)",
    re.DOTALL,
)
_BIN_RE = re.compile(
    r"bins\s+(\w+)\s*=\s*\{([^}]+)\}\s*;",
)


def parse_covergroups_from_sv(file: Path) -> list[CoverGroup]:
    """Extract covergroup definitions from an SV file.

    This is a deliberately shallow parser -- it pulls names, sample events,
    coverpoint expressions and explicit bins. It does not fully parse
    constraints or transition bins.
    """
    text = Path(file).read_text(encoding="utf-8", errors="ignore")
    groups: list[CoverGroup] = []
    for m in _COVERGROUP_RE.finditer(text):
        name = m.group(1)
        event = (m.group(2) or "@(posedge clk)").strip()
        body = m.group(3)
        points: list[CoverPoint] = []
        for pm in _COVERPOINT_RE.finditer(body):
            pname = pm.group(1)
            expr = pm.group(2).strip()
            bin_body = pm.group(3) or ""
            bins: list[CoverBin] = []
            for bm in _BIN_RE.finditer(bin_body):
                bins.append(
                    CoverBin(name=bm.group(1), values=[0])  # values unused here
                )
            points.append(
                CoverPoint(name=pname, expression=expr, bins=bins)
            )
        groups.append(CoverGroup(name=name, sample_event=event, points=points))
    return groups


# ---------------------------------------------------------------------------
# Merger
# ---------------------------------------------------------------------------


class FunctionalCoverageMerger:
    """Merge functional coverage results from multiple regression runs."""

    def __init__(self) -> None:
        self.groups: dict[str, CoverGroup] = {}

    def merge_runs(self, coverage_files: list[Path]) -> dict:
        """Merge JSON coverage exports.

        Each file is expected to contain a JSON dict of the form::

            {"groups": [<CoverGroup.model_dump()>, ...]}

        Files that fail to parse are silently skipped.
        """
        for f in coverage_files:
            try:
                raw = json.loads(Path(f).read_text(encoding="utf-8"))
            except Exception:
                continue
            for g_dict in raw.get("groups", []):
                try:
                    cg = CoverGroup.model_validate(g_dict)
                except Exception:
                    continue
                if cg.name not in self.groups:
                    self.groups[cg.name] = cg
                else:
                    self._merge_into(self.groups[cg.name], cg)
        return {
            "groups": [g.model_dump() for g in self.groups.values()],
            "summary": self.summary(),
        }

    @staticmethod
    def _merge_into(dst: CoverGroup, src: CoverGroup) -> None:
        for p_src in src.points:
            p_dst = next((p for p in dst.points if p.name == p_src.name), None)
            if p_dst is None:
                dst.points.append(p_src)
                continue
            p_dst.hits += p_src.hits
            for b_src in p_src.bins:
                b_dst = next((b for b in p_dst.bins if b.name == b_src.name), None)
                if b_dst is None:
                    p_dst.bins.append(b_src)
                else:
                    b_dst.hits += b_src.hits

    def summary(self) -> dict:
        total = sum(g.total_bins() for g in self.groups.values())
        hit = sum(g.hit_bins() for g in self.groups.values())
        return {
            "groups": len(self.groups),
            "total_bins": total,
            "hit_bins": hit,
            "percent": (100.0 * hit / total) if total else 0.0,
        }

    def gap_finder(self) -> list[CoverPoint]:
        """Return coverpoints with at least one uncovered bin."""
        gaps: list[CoverPoint] = []
        for g in self.groups.values():
            for p in g.points:
                if not p.bins and p.hits == 0:
                    gaps.append(p)
                    continue
                if any(b.hits == 0 for b in p.bins):
                    gaps.append(p)
        return gaps


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def hash_covergroup(cg: CoverGroup) -> str:
    """Return a short stable hash of a covergroup definition."""
    blob = json.dumps(cg.model_dump(), sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:12]

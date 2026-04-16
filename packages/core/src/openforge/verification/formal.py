"""Formal verification flow using SymbiYosys (sby).

Generates a real ``.sby`` file, drives ``sby --yosys yosys`` as a
subprocess, parses its status report, and collects counter-example
VCDs from the ``<task>/engine_N/`` work directory.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class FormalEngine(StrEnum):
    SMTBMC = "smtbmc"
    ABC_PDR = "abc pdr"
    AIGER = "aiger"
    BTOR = "btor"
    AVY = "avy"


class FormalProperty(BaseModel):
    kind: str  # assert | assume | cover | restrict | fair
    expr: str = ""
    file: str = ""
    line: int = 0
    name: str = ""


class FormalConfig(BaseModel):
    top_module: str
    rtl_files: list[str] = Field(default_factory=list)
    engine: FormalEngine = FormalEngine.SMTBMC
    depth: int = 50
    mode: str = "bmc"  # bmc | prove | cover | live
    timeout_s: int = 600
    multiclock: bool = False


class FormalResult(BaseModel):
    property: FormalProperty
    status: str  # PASS | FAIL | UNKNOWN | TIMEOUT
    cex_vcd: str | None = None
    runtime_s: float = 0.0


# ---------------------------------------------------------------------------
# RTL property scanner
# ---------------------------------------------------------------------------


_PROP_RE = re.compile(
    r"\b(assert|assume|cover|restrict|fair)\s+(?:property\s*)?\(([^;]*?)\)\s*;",
    re.DOTALL,
)


def scan_properties(rtl_files: list[str]) -> list[FormalProperty]:
    out: list[FormalProperty] = []
    for f in rtl_files:
        p = Path(f)
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _PROP_RE.finditer(text):
            lineno = text.count("\n", 0, m.start()) + 1
            kind = m.group(1)
            expr = m.group(2).strip()
            name = f"{p.stem}_{kind}_{lineno}"
            out.append(
                FormalProperty(
                    kind=kind, expr=expr, file=str(p), line=lineno, name=name
                )
            )
    return out


# ---------------------------------------------------------------------------
# SBY runner
# ---------------------------------------------------------------------------


class SbyRunner:
    """SymbiYosys wrapper."""

    def __init__(self, config: FormalConfig, design_dir: Path) -> None:
        self.config = config
        self.design_dir = Path(design_dir)
        self.design_dir.mkdir(parents=True, exist_ok=True)
        self.sby_path = self.design_dir / f"{self.config.top_module}.sby"

    def generate_sby_file(self) -> Path:
        """Write a real SymbiYosys task file."""
        cfg = self.config
        lines: list[str] = []
        lines.append("[tasks]")
        lines.append(f"{cfg.mode}")
        lines.append("")
        lines.append("[options]")
        lines.append(f"mode {cfg.mode}")
        lines.append(f"depth {cfg.depth}")
        if cfg.multiclock:
            lines.append("multiclock on")
        lines.append(f"timeout {cfg.timeout_s}")
        lines.append("")
        lines.append("[engines]")
        lines.append(cfg.engine.value)
        lines.append("")
        lines.append("[script]")
        for rtl in cfg.rtl_files:
            lines.append(f"read -formal {rtl}")
        lines.append(f"prep -top {cfg.top_module}")
        lines.append("")
        lines.append("[files]")
        for rtl in cfg.rtl_files:
            # sby expects paths relative to the .sby file; include absolute if
            # the file sits outside design_dir.
            p = Path(rtl)
            lines.append(str(p if p.is_absolute() else p.resolve()))
        self.sby_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.sby_path

    def run(self) -> list[FormalResult]:
        """Invoke ``sby --yosys yosys <file>.sby`` and parse its report."""
        self.generate_sby_file()
        props = scan_properties(self.config.rtl_files)
        sby = shutil.which("sby")
        if not sby:
            # Produce UNKNOWN results for every discovered property.
            return [
                FormalResult(property=p, status="UNKNOWN", runtime_s=0.0)
                for p in props
            ]
        cmd = [sby, "-f", "--yosys", "yosys", str(self.sby_path.name)]
        try:
            cp = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.sby_path.parent),
                timeout=self.config.timeout_s + 60,
            )
        except subprocess.TimeoutExpired:
            return [
                FormalResult(property=p, status="TIMEOUT", runtime_s=self.config.timeout_s)
                for p in props
            ]
        except FileNotFoundError:
            return [FormalResult(property=p, status="UNKNOWN") for p in props]
        log = cp.stdout + cp.stderr
        results: list[FormalResult] = []
        task_dir = self.sby_path.parent / f"{self.config.top_module}_{self.config.mode}"
        for prop in props:
            status = "UNKNOWN"
            cex: str | None = None
            if re.search(rf"{re.escape(prop.name)}.*PASS", log):
                status = "PASS"
            elif re.search(rf"{re.escape(prop.name)}.*FAIL", log):
                status = "FAIL"
            elif "DONE (PASS" in log:
                status = "PASS"
            elif "DONE (FAIL" in log:
                status = "FAIL"
            if status == "FAIL" and task_dir.exists():
                for vcd in task_dir.rglob("*.vcd"):
                    cex = str(vcd)
                    break
            results.append(FormalResult(property=prop, status=status, cex_vcd=cex))
        if not results:
            # Whole-task summary fallback
            status = "UNKNOWN"
            if "DONE (PASS" in log:
                status = "PASS"
            elif "DONE (FAIL" in log:
                status = "FAIL"
            results.append(
                FormalResult(
                    property=FormalProperty(
                        kind="assert",
                        name=self.config.top_module,
                        file=self.config.rtl_files[0] if self.config.rtl_files else "",
                    ),
                    status=status,
                )
            )
        return results

"""Logical Equivalence Checking (LEC) - Formality replacement.

Uses Yosys equiv_* commands to verify two designs are functionally equivalent.
Common use cases:
    - RTL vs synthesized gates
    - Pre-optimization vs post-optimization netlists
    - Pre-CTS vs post-CTS netlists
    - ECO verification
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass
class LecResult:
    """Result of a Logical Equivalence Check run."""

    success: bool
    equivalent: bool  # designs match
    duration: float
    point_count: int = 0  # equivalence points checked
    matched: int = 0
    diff_points: list[dict] = field(default_factory=list)  # mismatched (signal, type)
    log: str = ""
    script: str = ""
    gold_top: str = ""
    rev_top: str = ""
    error: str = ""

    @property
    def status_text(self) -> str:
        if not self.success:
            return "ERROR"
        if self.equivalent:
            return "EQUIVALENT"
        return "NOT EQUIVALENT"

    @property
    def match_ratio(self) -> float:
        if self.point_count == 0:
            return 0.0
        return self.matched / self.point_count

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "equivalent": self.equivalent,
            "duration": self.duration,
            "point_count": self.point_count,
            "matched": self.matched,
            "diff_points": self.diff_points,
            "gold_top": self.gold_top,
            "rev_top": self.rev_top,
            "error": self.error,
        }


class LecRunner:
    """Logical Equivalence Checking via Yosys equiv_* commands.

    The flow uses Yosys's miter-based equivalence checking. Two designs
    (gold and revised) are loaded, paired up by port and register names,
    then proven equivalent through SAT plus k-induction.
    """

    YOSYS_BIN = "yosys"

    def __init__(self, native_yosys: bool = True) -> None:
        self.native_yosys = native_yosys
        self._timeout_seconds: int = 600

    # ---------- public API ----------

    def check_equivalence(
        self,
        gold_sources: list[Path],
        gold_top: str,
        rev_sources: list[Path],
        rev_top: str,
        cwd: Path | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> LecResult:
        """Compare two designs for equivalence.

        Args:
            gold_sources: Verilog/SystemVerilog files for the golden design.
            gold_top: Top module name in the golden design.
            rev_sources: Verilog/SystemVerilog files for the revised design.
            rev_top: Top module name in the revised design.
            cwd: Working directory (defaults to current directory).
            on_output: Optional callback for streaming Yosys output lines.

        Returns:
            LecResult with success/equivalent flags and a list of diff points.
        """
        cwd = Path(cwd) if cwd else Path.cwd()
        cwd.mkdir(parents=True, exist_ok=True)
        script = self._build_equiv_script(gold_sources, gold_top, rev_sources, rev_top)
        start = time.time()
        log, error = self._run_yosys(script, cwd, on_output)
        duration = time.time() - start

        equivalent, points, matched, diffs = self._parse_equiv_log(log)
        success = error == "" and not log.lower().startswith("error")
        return LecResult(
            success=success,
            equivalent=equivalent,
            duration=duration,
            point_count=points,
            matched=matched,
            diff_points=diffs,
            log=log,
            script=script,
            gold_top=gold_top,
            rev_top=rev_top,
            error=error,
        )

    def check_rtl_vs_gates(
        self,
        rtl_sources: list[Path],
        netlist_path: Path,
        top_module: str,
        liberty: Path | None = None,
        cwd: Path | None = None,
    ) -> LecResult:
        """Verify that an RTL description matches its synthesized netlist."""
        cwd = Path(cwd) if cwd else Path.cwd()
        cwd.mkdir(parents=True, exist_ok=True)
        script = self._build_rtl_vs_gates_script(rtl_sources, netlist_path, top_module, liberty)
        start = time.time()
        log, error = self._run_yosys(script, cwd, None)
        duration = time.time() - start
        equivalent, points, matched, diffs = self._parse_equiv_log(log)
        return LecResult(
            success=error == "",
            equivalent=equivalent,
            duration=duration,
            point_count=points,
            matched=matched,
            diff_points=diffs,
            log=log,
            script=script,
            gold_top=top_module,
            rev_top=top_module,
            error=error,
        )

    def check_pre_post_opt(
        self,
        netlist_pre: Path,
        netlist_post: Path,
        top_module: str,
    ) -> LecResult:
        """Verify pre-optimization vs post-optimization gates are equivalent."""
        return self.check_equivalence(
            gold_sources=[netlist_pre],
            gold_top=top_module,
            rev_sources=[netlist_post],
            rev_top=top_module,
        )

    def check_eco(
        self,
        original_netlist: Path,
        eco_netlist: Path,
        top_module: str,
        ignored_signals: list[str] | None = None,
    ) -> LecResult:
        """Check that an ECO patch did not change functional behavior outside
        of explicitly ignored signals."""
        result = self.check_equivalence(
            gold_sources=[original_netlist],
            gold_top=top_module,
            rev_sources=[eco_netlist],
            rev_top=top_module,
        )
        if ignored_signals:
            filtered = [d for d in result.diff_points if d.get("signal") not in ignored_signals]
            result.diff_points = filtered
            if len(filtered) == 0 and not result.equivalent:
                result.equivalent = True
        return result

    # ---------- script builders ----------

    def _build_equiv_script(
        self,
        gold_sources: list[Path],
        gold_top: str,
        rev_sources: list[Path],
        rev_top: str,
    ) -> str:
        """Generate the Yosys script that performs equivalence checking."""
        lines: list[str] = []
        lines.append("# OpenForge LEC - generated by LecRunner")
        lines.append("# Step 1: read gold design")
        for src in gold_sources:
            lines.append(f"read_verilog -DGOLD {self._posix(src)}")
        lines.append(f"hierarchy -top {gold_top}")
        lines.append("proc; opt; memory; opt")
        lines.append(f"rename {gold_top} gold")
        lines.append("design -stash gold")

        lines.append("")
        lines.append("# Step 2: read revised design")
        for src in rev_sources:
            lines.append(f"read_verilog -DREV {self._posix(src)}")
        lines.append(f"hierarchy -top {rev_top}")
        lines.append("proc; opt; memory; opt")
        lines.append(f"rename {rev_top} rev")
        lines.append("design -stash rev")

        lines.append("")
        lines.append("# Step 3: combine and build miter")
        lines.append("design -copy-from gold -as gold gold")
        lines.append("design -copy-from rev -as rev rev")
        lines.append("equiv_make gold rev equiv")
        lines.append("hierarchy -top equiv")
        lines.append("equiv_simple -seq 5 equiv")
        lines.append("equiv_induct -seq 10 equiv")
        lines.append("equiv_status -assert equiv")
        return "\n".join(lines) + "\n"

    def _build_rtl_vs_gates_script(
        self,
        rtl_sources: list[Path],
        netlist: Path,
        top_module: str,
        liberty: Path | None,
    ) -> str:
        lines: list[str] = []
        lines.append("# OpenForge LEC - RTL vs Gates")
        for src in rtl_sources:
            lines.append(f"read_verilog -sv {self._posix(src)}")
        lines.append(f"hierarchy -check -top {top_module}")
        lines.append("proc; opt; memory; opt")
        lines.append(f"rename {top_module} gold")
        lines.append("design -stash gold")
        if liberty:
            lines.append(f"read_liberty -lib {self._posix(liberty)}")
        lines.append(f"read_verilog {self._posix(netlist)}")
        lines.append(f"hierarchy -top {top_module}")
        lines.append(f"rename {top_module} rev")
        lines.append("design -stash rev")
        lines.append("design -copy-from gold -as gold gold")
        lines.append("design -copy-from rev -as rev rev")
        lines.append("equiv_make gold rev equiv")
        lines.append("hierarchy -top equiv")
        lines.append("equiv_simple -seq 5 equiv")
        lines.append("equiv_induct -seq 10 equiv")
        lines.append("equiv_status -assert equiv")
        return "\n".join(lines) + "\n"

    # ---------- Yosys execution ----------

    def _run_yosys(
        self,
        script: str,
        cwd: Path,
        on_output: Callable[[str], None] | None,
    ) -> tuple[str, str]:
        """Execute Yosys and return (stdout_log, error_string)."""
        script_path = cwd / "lec_script.ys"
        script_path.write_text(script, encoding="utf-8")
        try:
            proc = subprocess.Popen(
                [self.YOSYS_BIN, "-q", "-s", str(script_path)],
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            return "", "yosys binary not found in PATH"

        chunks: list[str] = []
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                chunks.append(line)
                if on_output:
                    with contextlib.suppress(Exception):
                        on_output(line.rstrip())
            proc.wait(timeout=self._timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            return "".join(chunks), f"timeout after {self._timeout_seconds}s"
        return "".join(chunks), ""

    # ---------- log parsing ----------

    _RE_POINTS = re.compile(r"Found\s+(\d+)\s+equiv\s+cells", re.IGNORECASE)
    _RE_REMAINING = re.compile(r"Found\s+(\d+)\s+unproven\s+\$equiv\s+cells", re.IGNORECASE)
    _RE_PROVEN = re.compile(r"Successfully\s+proved\s+(\d+)", re.IGNORECASE)
    _RE_NO_DIFF = re.compile(r"Equivalence successfully proven", re.IGNORECASE)

    def _parse_equiv_log(self, log: str) -> tuple[bool, int, int, list[dict]]:
        """Return (equivalent, points_total, matched, diff_points)."""
        if not log:
            return False, 0, 0, []
        equivalent = bool(self._RE_NO_DIFF.search(log))
        points = 0
        matched = 0
        for m in self._RE_POINTS.finditer(log):
            points = max(points, int(m.group(1)))
        for m in self._RE_PROVEN.finditer(log):
            matched += int(m.group(1))
        if matched == 0 and equivalent:
            matched = points

        diffs: list[dict] = []
        # Look for unproven entries
        for line in log.splitlines():
            line = line.strip()
            if "unproven" in line.lower() and "$equiv" in line:
                # heuristic extraction
                token = line.split()[-1] if line.split() else "?"
                diffs.append(
                    {
                        "type": "unproven",
                        "signal": token,
                        "reason": "equivalence not proven",
                    }
                )
            elif line.startswith("ERROR"):
                diffs.append({"type": "error", "signal": "", "reason": line})

        return equivalent, points, matched, diffs

    @staticmethod
    def _posix(p: Path) -> str:
        return Path(p).as_posix()


def quick_check(gold: Path, rev: Path, top: str, cwd: Path | None = None) -> LecResult:
    """One-shot helper used by tests and the CLI."""
    return LecRunner().check_equivalence(
        gold_sources=[Path(gold)],
        gold_top=top,
        rev_sources=[Path(rev)],
        rev_top=top,
        cwd=cwd,
    )

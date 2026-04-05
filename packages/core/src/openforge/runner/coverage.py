"""Coverage data collection, merging, and HTML report generation."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ToggleCounts:
    """Toggle coverage counters for a single signal."""

    zero_to_one: int = 0
    one_to_zero: int = 0


@dataclass(slots=True)
class FSMCoverage:
    """FSM coverage data for a single state machine."""

    states_hit: int = 0
    states_total: int = 0
    transitions_hit: int = 0
    transitions_total: int = 0


@dataclass(slots=True)
class CoverageData:
    """Aggregated coverage information from one or more simulation runs."""

    line_coverage: dict[str, int] = field(default_factory=dict)
    toggle_coverage: dict[str, ToggleCounts] = field(default_factory=dict)
    fsm_coverage: dict[str, FSMCoverage] = field(default_factory=dict)

    @property
    def line_hit_count(self) -> int:
        return sum(1 for v in self.line_coverage.values() if v > 0)

    @property
    def line_total_count(self) -> int:
        return len(self.line_coverage)

    @property
    def line_percentage(self) -> float:
        if not self.line_coverage:
            return 0.0
        return 100.0 * self.line_hit_count / self.line_total_count


# ---------------------------------------------------------------------------
# Parser helpers -- Verilator coverage .dat format
# ---------------------------------------------------------------------------

# Verilator coverage files have lines like:
#   C '<file>' <line> <column> <name> <count>
# or the annotated form from ``verilator_coverage --annotate``.

_VERILATOR_LINE_RE = re.compile(
    r"^C\s+'([^']+)'\s+(\d+)\s+\d+\s+(\S+)\s+(\d+)"
)

# Toggle entries:
#   T '<file>' <line> <column> <hier> <signal> <bit> <0->1> <1->0>
_VERILATOR_TOGGLE_RE = re.compile(
    r"^T\s+'([^']+)'\s+\d+\s+\d+\s+(\S+)\s+(\S+)\s+\d+\s+(\d+)\s+(\d+)"
)

# FSM entries (from verilator --coverage-line --coverage-toggle):
_VERILATOR_FSM_RE = re.compile(
    r"^F\s+'([^']+)'\s+\d+\s+\d+\s+(\S+)"
)


class CoverageCollector:
    """Collects and processes simulation coverage data.

    Supports Verilator ``.dat`` coverage files.  The methods parse
    different coverage categories and can merge multiple runs.
    """

    # ------------------------------------------------------------------
    # Line coverage
    # ------------------------------------------------------------------

    @staticmethod
    def collect_line_coverage(
        dat_file: str | PathLike[str],
    ) -> dict[str, int]:
        """Parse line coverage from a Verilator ``.dat`` file.

        Returns a mapping of ``"file:line"`` to hit count.
        """
        result: dict[str, int] = {}
        path = Path(dat_file)
        if not path.is_file():
            return result

        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if m := _VERILATOR_LINE_RE.match(raw_line):
                src_file = m.group(1)
                line_no = m.group(2)
                count = int(m.group(4))
                key = f"{src_file}:{line_no}"
                result[key] = result.get(key, 0) + count

        return result

    # ------------------------------------------------------------------
    # Toggle coverage
    # ------------------------------------------------------------------

    @staticmethod
    def collect_toggle_coverage(
        dat_file: str | PathLike[str],
    ) -> dict[str, ToggleCounts]:
        """Parse toggle coverage from a Verilator ``.dat`` file.

        Returns a mapping of signal name to :class:`ToggleCounts`.
        """
        result: dict[str, ToggleCounts] = {}
        path = Path(dat_file)
        if not path.is_file():
            return result

        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if m := _VERILATOR_TOGGLE_RE.match(raw_line):
                signal = f"{m.group(2)}.{m.group(3)}"
                zero_one = int(m.group(4))
                one_zero = int(m.group(5))
                if signal in result:
                    result[signal].zero_to_one += zero_one
                    result[signal].one_to_zero += one_zero
                else:
                    result[signal] = ToggleCounts(
                        zero_to_one=zero_one,
                        one_to_zero=one_zero,
                    )

        return result

    # ------------------------------------------------------------------
    # FSM coverage
    # ------------------------------------------------------------------

    @staticmethod
    def collect_fsm_coverage(
        dat_file: str | PathLike[str],
    ) -> dict[str, FSMCoverage]:
        """Parse FSM coverage from a Verilator ``.dat`` file.

        Returns a mapping of FSM name to :class:`FSMCoverage`.

        Note: Verilator FSM coverage support is limited.  This parser
        handles the common ``F`` record format when available.
        """
        result: dict[str, FSMCoverage] = {}
        path = Path(dat_file)
        if not path.is_file():
            return result

        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if m := _VERILATOR_FSM_RE.match(raw_line):
                fsm_name = m.group(2)
                if fsm_name not in result:
                    result[fsm_name] = FSMCoverage()
                result[fsm_name].states_hit += 1
                result[fsm_name].states_total += 1

        return result

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    @staticmethod
    def merge_coverage(
        files: list[str | PathLike[str]],
    ) -> CoverageData:
        """Merge multiple coverage ``.dat`` files into a single :class:`CoverageData`.

        Parameters
        ----------
        files:
            Paths to coverage data files to merge.
        """
        merged = CoverageData()

        for f in files:
            # Line coverage
            for key, count in CoverageCollector.collect_line_coverage(f).items():
                merged.line_coverage[key] = merged.line_coverage.get(key, 0) + count

            # Toggle coverage
            for sig, tc in CoverageCollector.collect_toggle_coverage(f).items():
                if sig in merged.toggle_coverage:
                    merged.toggle_coverage[sig].zero_to_one += tc.zero_to_one
                    merged.toggle_coverage[sig].one_to_zero += tc.one_to_zero
                else:
                    merged.toggle_coverage[sig] = ToggleCounts(
                        zero_to_one=tc.zero_to_one,
                        one_to_zero=tc.one_to_zero,
                    )

            # FSM coverage
            for name, fsm in CoverageCollector.collect_fsm_coverage(f).items():
                if name in merged.fsm_coverage:
                    merged.fsm_coverage[name].states_hit += fsm.states_hit
                    merged.fsm_coverage[name].transitions_hit += fsm.transitions_hit
                else:
                    merged.fsm_coverage[name] = FSMCoverage(
                        states_hit=fsm.states_hit,
                        states_total=fsm.states_total,
                        transitions_hit=fsm.transitions_hit,
                        transitions_total=fsm.transitions_total,
                    )

        return merged

    # ------------------------------------------------------------------
    # HTML report
    # ------------------------------------------------------------------

    @staticmethod
    def generate_html_report(
        coverage_data: CoverageData,
        output_path: str | PathLike[str],
        *,
        source_root: str | PathLike[str] | None = None,
    ) -> Path:
        """Generate an HTML coverage report with color-coded source lines.

        Parameters
        ----------
        coverage_data:
            Aggregated coverage data to render.
        output_path:
            Path for the generated HTML file.
        source_root:
            Root directory for resolving source file paths.  When *None*,
            source code is not inlined -- only a summary table is produced.

        Returns
        -------
        Path
            Resolved path to the generated HTML file.
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # Group line coverage by file
        files: dict[str, dict[int, int]] = {}
        for key, count in coverage_data.line_coverage.items():
            parts = key.rsplit(":", 1)
            if len(parts) != 2:
                continue
            fname, lineno_str = parts
            lineno = int(lineno_str)
            files.setdefault(fname, {})[lineno] = count

        # Build HTML
        lines: list[str] = [
            "<!DOCTYPE html>",
            "<html lang='en'>",
            "<head>",
            "<meta charset='utf-8'>",
            "<title>OpenForge Coverage Report</title>",
            "<style>",
            "body { font-family: 'Segoe UI', sans-serif; background: #1e1e2e; color: #cdd6f4; margin: 20px; }",
            "h1 { color: #89b4fa; }",
            "h2 { color: #cba6f7; margin-top: 2em; }",
            "table { border-collapse: collapse; width: 100%; margin: 1em 0; }",
            "th, td { border: 1px solid #313244; padding: 6px 12px; text-align: left; }",
            "th { background: #181825; color: #89b4fa; }",
            "tr:hover { background: #313244; }",
            ".covered { background: #1a3a1a; color: #a6e3a1; }",      # green
            ".uncovered { background: #3a1a1a; color: #f38ba8; }",    # red
            ".partial { background: #3a3a1a; color: #f9e2af; }",      # yellow
            ".line-no { color: #585b70; text-align: right; width: 50px; user-select: none; }",
            ".hit-count { text-align: right; width: 60px; }",
            "pre { margin: 0; font-family: 'JetBrains Mono', monospace; font-size: 13px; }",
            ".summary-good { color: #a6e3a1; font-weight: bold; }",
            ".summary-warn { color: #f9e2af; font-weight: bold; }",
            ".summary-bad { color: #f38ba8; font-weight: bold; }",
            ".pct-bar { height: 12px; border-radius: 6px; background: #313244; overflow: hidden; display: inline-block; width: 120px; vertical-align: middle; }",
            ".pct-fill { height: 100%; border-radius: 6px; }",
            "</style>",
            "</head>",
            "<body>",
            "<h1>OpenForge Coverage Report</h1>",
        ]

        # Summary
        pct = coverage_data.line_percentage
        pct_class = "summary-good" if pct >= 80 else ("summary-warn" if pct >= 50 else "summary-bad")
        pct_color = "#a6e3a1" if pct >= 80 else ("#f9e2af" if pct >= 50 else "#f38ba8")
        lines.append(f"<p>Line coverage: <span class='{pct_class}'>{pct:.1f}%</span> "
                      f"({coverage_data.line_hit_count}/{coverage_data.line_total_count} lines)</p>")
        lines.append(f"<div class='pct-bar'><div class='pct-fill' style='width:{pct:.0f}%; background:{pct_color};'></div></div>")

        # Per-file summary table
        lines.append("<h2>File Summary</h2>")
        lines.append("<table><tr><th>File</th><th>Lines Hit</th><th>Total</th><th>Coverage</th></tr>")
        for fname in sorted(files):
            line_data = files[fname]
            total = len(line_data)
            hit = sum(1 for c in line_data.values() if c > 0)
            fpct = 100.0 * hit / total if total else 0.0
            fc = "summary-good" if fpct >= 80 else ("summary-warn" if fpct >= 50 else "summary-bad")
            lines.append(
                f"<tr><td>{html.escape(fname)}</td><td>{hit}</td><td>{total}</td>"
                f"<td class='{fc}'>{fpct:.1f}%</td></tr>"
            )
        lines.append("</table>")

        # Toggle coverage summary
        if coverage_data.toggle_coverage:
            lines.append("<h2>Toggle Coverage</h2>")
            lines.append("<table><tr><th>Signal</th><th>0-&gt;1</th><th>1-&gt;0</th></tr>")
            for sig in sorted(coverage_data.toggle_coverage):
                tc = coverage_data.toggle_coverage[sig]
                lines.append(
                    f"<tr><td>{html.escape(sig)}</td>"
                    f"<td>{tc.zero_to_one}</td><td>{tc.one_to_zero}</td></tr>"
                )
            lines.append("</table>")

        # FSM coverage summary
        if coverage_data.fsm_coverage:
            lines.append("<h2>FSM Coverage</h2>")
            lines.append("<table><tr><th>FSM</th><th>States Hit</th><th>Transitions Hit</th></tr>")
            for name in sorted(coverage_data.fsm_coverage):
                fsm = coverage_data.fsm_coverage[name]
                lines.append(
                    f"<tr><td>{html.escape(name)}</td>"
                    f"<td>{fsm.states_hit}/{fsm.states_total}</td>"
                    f"<td>{fsm.transitions_hit}/{fsm.transitions_total}</td></tr>"
                )
            lines.append("</table>")

        # Annotated source code (if source_root provided)
        if source_root:
            root = Path(source_root)
            for fname in sorted(files):
                src_path = root / fname if not Path(fname).is_absolute() else Path(fname)
                if not src_path.is_file():
                    continue
                line_data = files[fname]
                lines.append(f"<h2>{html.escape(fname)}</h2>")
                lines.append("<table>")
                lines.append("<tr><th class='line-no'>#</th><th class='hit-count'>Hits</th><th>Source</th></tr>")
                for i, src_line in enumerate(src_path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if i in line_data:
                        count = line_data[i]
                        if count > 0:
                            cls = "covered"
                        else:
                            cls = "uncovered"
                    else:
                        cls = ""
                        count = None  # type: ignore[assignment]

                    count_str = str(count) if count is not None else ""
                    lines.append(
                        f"<tr class='{cls}'>"
                        f"<td class='line-no'>{i}</td>"
                        f"<td class='hit-count'>{count_str}</td>"
                        f"<td><pre>{html.escape(src_line)}</pre></td>"
                        f"</tr>"
                    )
                lines.append("</table>")

        lines.extend(["</body>", "</html>"])

        out.write_text("\n".join(lines), encoding="utf-8")
        return out.resolve()

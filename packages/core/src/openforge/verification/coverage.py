"""Coverage parsing, merging and reporting for OpenForge.

Legacy dataclass-based ``CoverageReport`` (used by the regression runner)
plus a Pydantic v2 model hierarchy (``CoverageReportV2``, ``FileCoverage``,
``ModuleCoverage``, ``CoverageBin``) and a ``CoverageDb`` trend database
used by the Phase 4 coverage dashboard.
"""

from __future__ import annotations

import contextlib
import html
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class LineCoverage:
    """A single source line coverage data point."""

    file: str
    line: int
    count: int = 0


@dataclass
class ToggleCoverage:
    """Toggle coverage for a single signal/bit."""

    signal: str
    rises: int = 0
    falls: int = 0

    @property
    def covered(self) -> bool:
        return self.rises > 0 and self.falls > 0


@dataclass
class FunctionalCoverage:
    """A single covergroup/coverpoint/bin record."""

    covergroup: str
    coverpoint: str
    bin: str
    hits: int = 0


@dataclass
class CoverageReport:
    """Aggregated coverage metrics from one or more runs."""

    line_total: int = 0
    line_covered: int = 0
    toggle_total: int = 0
    toggle_covered: int = 0
    branch_total: int = 0
    branch_covered: int = 0
    functional_total: int = 0
    functional_covered: int = 0

    line_details: list[LineCoverage] = field(default_factory=list)
    toggle_details: list[ToggleCoverage] = field(default_factory=list)
    functional_details: list[FunctionalCoverage] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Percent helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _pct(num: int, denom: int) -> float:
        if denom <= 0:
            return 0.0
        return (num / denom) * 100.0

    @property
    def line_pct(self) -> float:
        return self._pct(self.line_covered, self.line_total)

    @property
    def toggle_pct(self) -> float:
        return self._pct(self.toggle_covered, self.toggle_total)

    @property
    def branch_pct(self) -> float:
        return self._pct(self.branch_covered, self.branch_total)

    @property
    def functional_pct(self) -> float:
        return self._pct(self.functional_covered, self.functional_total)

    @property
    def overall_pct(self) -> float:
        total = (
            self.line_total
            + self.toggle_total
            + self.branch_total
            + self.functional_total
        )
        covered = (
            self.line_covered
            + self.toggle_covered
            + self.branch_covered
            + self.functional_covered
        )
        return self._pct(covered, total)

    def files(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for d in self.line_details:
            if d.file not in seen:
                seen.add(d.file)
                out.append(d.file)
        return out

    def lines_for_file(self, file: str) -> list[LineCoverage]:
        return [d for d in self.line_details if d.file == file]

    def file_pct(self, file: str) -> float:
        rows = self.lines_for_file(file)
        if not rows:
            return 0.0
        hit = sum(1 for r in rows if r.count > 0)
        return (hit / len(rows)) * 100.0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


_LINE_RE = re.compile(r"C\s+'([^']+)'\s+(\d+)")
_POINT_RE = re.compile(r"([\w./\\:-]+):(\d+)\s+(\d+)")


class CoverageParser:
    """Parse and merge coverage data files."""

    # ------------------------------------------------------------------
    # Verilator parser
    # ------------------------------------------------------------------
    def parse_verilator_dat(self, path: Path) -> CoverageReport:
        """Parse a Verilator ``coverage.dat`` file.

        Verilator emits a textual format where each non-comment line has the
        form ``C 'point_spec' count``. The point spec is a comma separated
        list of ``key=value`` attributes. We look at ``type``, ``filename``,
        ``lineno``, ``hier`` and ``per_instance``.
        """
        report = CoverageReport()
        path = Path(path)
        if not path.exists():
            return report

        toggle_seen: dict[str, ToggleCoverage] = {}
        line_seen: dict[tuple[str, int], LineCoverage] = {}

        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue

                m = _LINE_RE.match(line)
                if not m:
                    # Fallback simple format file:line count
                    fm = _POINT_RE.match(line)
                    if fm:
                        f, ln, cnt = fm.group(1), int(fm.group(2)), int(fm.group(3))
                        key = (f, ln)
                        existing = line_seen.get(key)
                        if existing is None:
                            line_seen[key] = LineCoverage(f, ln, cnt)
                        else:
                            existing.count += cnt
                    continue

                attrs_raw, count_raw = m.group(1), m.group(2)
                count = int(count_raw)
                attrs: dict[str, str] = {}
                for piece in attrs_raw.split(","):
                    if "\\'" in piece:
                        piece = piece.replace("\\'", "'")
                    if "=" in piece:
                        k, _, v = piece.partition("=")
                        attrs[k.strip()] = v.strip()

                ctype = attrs.get("type", "line")
                if ctype in ("line", "block", "v_line"):
                    fname = attrs.get("filename") or attrs.get("file") or "<unknown>"
                    lineno = int(attrs.get("lineno", attrs.get("line", "0")) or 0)
                    key = (fname, lineno)
                    existing = line_seen.get(key)
                    if existing is None:
                        line_seen[key] = LineCoverage(fname, lineno, count)
                    else:
                        existing.count += count
                elif ctype in ("toggle", "v_toggle"):
                    sig = attrs.get("hier") or attrs.get("signal") or "<unknown>"
                    edge = attrs.get("edge") or attrs.get("dir") or "rise"
                    tc = toggle_seen.setdefault(sig, ToggleCoverage(sig))
                    if edge.startswith("r") or edge in ("01", "0->1"):
                        tc.rises += count
                    else:
                        tc.falls += count
                elif ctype in ("branch", "v_branch"):
                    report.branch_total += 1
                    if count > 0:
                        report.branch_covered += 1
                elif ctype in ("user", "cover", "covergroup", "v_user"):
                    cg = attrs.get("group", attrs.get("hier", "user"))
                    cp = attrs.get("point", "cp")
                    bn = attrs.get("bin", "default")
                    report.functional_details.append(
                        FunctionalCoverage(cg, cp, bn, count)
                    )

        report.line_details = list(line_seen.values())
        report.line_total = len(report.line_details)
        report.line_covered = sum(1 for r in report.line_details if r.count > 0)

        report.toggle_details = list(toggle_seen.values())
        report.toggle_total = len(report.toggle_details) * 2
        report.toggle_covered = sum(
            (1 if t.rises > 0 else 0) + (1 if t.falls > 0 else 0)
            for t in report.toggle_details
        )

        report.functional_total = len(report.functional_details)
        report.functional_covered = sum(
            1 for f in report.functional_details if f.hits > 0
        )

        return report

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------
    def merge(self, reports: Iterable[CoverageReport]) -> CoverageReport:
        """Merge multiple coverage reports into a single aggregate.

        Line counts are summed per (file, line). Toggle rises/falls are
        summed per signal. Functional bins are summed per (group, point,
        bin) tuple.
        """
        merged = CoverageReport()

        line_acc: dict[tuple[str, int], LineCoverage] = {}
        tog_acc: dict[str, ToggleCoverage] = {}
        func_acc: dict[tuple[str, str, str], FunctionalCoverage] = {}

        branch_total = 0
        branch_covered = 0

        for rep in reports:
            for ln in rep.line_details:
                key = (ln.file, ln.line)
                cur = line_acc.get(key)
                if cur is None:
                    line_acc[key] = LineCoverage(ln.file, ln.line, ln.count)
                else:
                    cur.count += ln.count
            for tg in rep.toggle_details:
                cur_t = tog_acc.get(tg.signal)
                if cur_t is None:
                    tog_acc[tg.signal] = ToggleCoverage(tg.signal, tg.rises, tg.falls)
                else:
                    cur_t.rises += tg.rises
                    cur_t.falls += tg.falls
            for fc in rep.functional_details:
                key_f = (fc.covergroup, fc.coverpoint, fc.bin)
                cur_f = func_acc.get(key_f)
                if cur_f is None:
                    func_acc[key_f] = FunctionalCoverage(*key_f, fc.hits)
                else:
                    cur_f.hits += fc.hits
            branch_total = max(branch_total, rep.branch_total)
            branch_covered += rep.branch_covered

        merged.line_details = list(line_acc.values())
        merged.line_total = len(merged.line_details)
        merged.line_covered = sum(1 for r in merged.line_details if r.count > 0)

        merged.toggle_details = list(tog_acc.values())
        merged.toggle_total = len(merged.toggle_details) * 2
        merged.toggle_covered = sum(
            (1 if t.rises > 0 else 0) + (1 if t.falls > 0 else 0)
            for t in merged.toggle_details
        )

        merged.functional_details = list(func_acc.values())
        merged.functional_total = len(merged.functional_details)
        merged.functional_covered = sum(
            1 for f in merged.functional_details if f.hits > 0
        )

        merged.branch_total = branch_total
        merged.branch_covered = min(branch_covered, branch_total)

        return merged

    # ------------------------------------------------------------------
    # HTML
    # ------------------------------------------------------------------
    def to_html(self, report: CoverageReport, output_dir: Path) -> Path:
        """Render a self contained HTML coverage report.

        The output directory will contain ``index.html`` plus an
        ``files/`` directory with one HTML file per source file showing
        line by line annotation.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        files_dir = output_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        css = self._css()

        # ---------- index ----------
        bars = [
            ("Line", report.line_pct, report.line_covered, report.line_total),
            ("Toggle", report.toggle_pct, report.toggle_covered, report.toggle_total),
            ("Branch", report.branch_pct, report.branch_covered, report.branch_total),
            (
                "Functional",
                report.functional_pct,
                report.functional_covered,
                report.functional_total,
            ),
        ]

        rows: list[str] = []
        for f in report.files():
            pct = report.file_pct(f)
            rows_for_file = report.lines_for_file(f)
            hit = sum(1 for r in rows_for_file if r.count > 0)
            slug = self._slugify(f)
            rows.append(
                f'<tr><td><a href="files/{slug}.html">{html.escape(f)}</a></td>'
                f"<td class='num'>{hit}/{len(rows_for_file)}</td>"
                f"<td class='bar'>{self._bar_html(pct)}</td>"
                f"<td class='num'>{pct:.1f}%</td></tr>"
            )

        bars_html = "\n".join(
            f"<div class='metric'><div class='label'>{name}</div>"
            f"<div class='bar-wrap'>{self._bar_html(pct)}</div>"
            f"<div class='num'>{cov}/{tot} ({pct:.1f}%)</div></div>"
            for name, pct, cov, tot in bars
        )

        index = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>OpenForge Coverage Report</title>
<style>{css}</style></head>
<body>
<header>
  <h1>Coverage Report</h1>
  <div class='overall'>Overall: <strong>{report.overall_pct:.1f}%</strong></div>
</header>
<section class='metrics'>
{bars_html}
</section>
<section>
  <h2>Files</h2>
  <table class='files'>
    <thead><tr><th>File</th><th>Lines</th><th>&nbsp;</th><th>%</th></tr></thead>
    <tbody>
    {''.join(rows) or '<tr><td colspan=4 class="muted">No line coverage data</td></tr>'}
    </tbody>
  </table>
</section>
<footer>Generated by OpenForge EDA</footer>
</body></html>
"""
        index_path = output_dir / "index.html"
        index_path.write_text(index, encoding="utf-8")

        # ---------- per file ----------
        for f in report.files():
            slug = self._slugify(f)
            rows_for_file = sorted(report.lines_for_file(f), key=lambda r: r.line)
            file_rows = []
            for r in rows_for_file:
                cls = "hit" if r.count > 0 else "miss"
                file_rows.append(
                    f"<tr class='{cls}'><td class='ln'>{r.line}</td>"
                    f"<td class='cnt'>{r.count}</td>"
                    f"<td class='src'>&nbsp;</td></tr>"
                )
            html_doc = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>{html.escape(f)}</title>
<style>{css}</style></head>
<body>
<header><h1>{html.escape(f)}</h1>
<a href="../index.html">&larr; back</a></header>
<table class='source'>
<thead><tr><th>Line</th><th>Hits</th><th>Source</th></tr></thead>
<tbody>{''.join(file_rows)}</tbody></table>
</body></html>
"""
            (files_dir / f"{slug}.html").write_text(html_doc, encoding="utf-8")

        return index_path

    # ------------------------------------------------------------------
    # LCOV
    # ------------------------------------------------------------------
    def to_lcov(self, report: CoverageReport, output: Path) -> Path:
        """Export the report as LCOV info format.

        See https://github.com/linux-test-project/lcov for the spec.
        """
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

        per_file: dict[str, list[LineCoverage]] = {}
        for d in report.line_details:
            per_file.setdefault(d.file, []).append(d)

        lines: list[str] = []
        for fname, rows in per_file.items():
            lines.append("TN:")
            lines.append(f"SF:{fname}")
            for r in rows:
                lines.append(f"DA:{r.line},{r.count}")
            hit = sum(1 for r in rows if r.count > 0)
            lines.append(f"LF:{len(rows)}")
            lines.append(f"LH:{hit}")
            lines.append("end_of_record")

        output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return output

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _slugify(s: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", s)

    @staticmethod
    def _bar_color(pct: float) -> str:
        if pct >= 80:
            return "#a6e3a1"
        if pct >= 50:
            return "#f9e2af"
        return "#f38ba8"

    def _bar_html(self, pct: float) -> str:
        color = self._bar_color(pct)
        width = max(0.0, min(100.0, pct))
        return (
            f"<div class='bar-bg'><div class='bar-fill' "
            f"style='width:{width:.1f}%;background:{color};'></div></div>"
        )

    @staticmethod
    def _css() -> str:
        return """
        :root { color-scheme: dark; }
        body {
          margin: 0; padding: 0;
          font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
          background: #11111b; color: #cdd6f4;
        }
        header {
          padding: 1rem 2rem; border-bottom: 1px solid #313244;
          display: flex; align-items: center; justify-content: space-between;
          background: #181825;
        }
        h1 { margin: 0; font-size: 1.4rem; color: #cba6f7; }
        h2 { color: #89b4fa; }
        .overall { font-size: 1.1rem; }
        section { padding: 1rem 2rem; }
        .metrics {
          display: grid; gap: .75rem;
          grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        }
        .metric {
          background: #1e1e2e; padding: .75rem 1rem;
          border-radius: 6px; border: 1px solid #313244;
        }
        .metric .label { font-size: .85rem; color: #94a3b8; }
        .metric .num { font-size: .85rem; margin-top: .25rem; }
        .bar-bg {
          width: 100%; height: 10px; background: #313244;
          border-radius: 5px; overflow: hidden;
        }
        .bar-fill { height: 100%; }
        table.files, table.source {
          width: 100%; border-collapse: collapse; margin-top: 1rem;
        }
        table.files th, table.files td,
        table.source th, table.source td {
          padding: .35rem .6rem; text-align: left;
          border-bottom: 1px solid #313244;
        }
        table.files th { background: #181825; color: #94a3b8; }
        table.files td.num { text-align: right; font-variant-numeric: tabular-nums; }
        table.files td.bar { width: 30%; }
        table.files a { color: #89b4fa; text-decoration: none; }
        table.files a:hover { text-decoration: underline; }
        table.source td.ln { color: #6c7086; text-align: right; width: 4rem; }
        table.source td.cnt { color: #94a3b8; text-align: right; width: 4rem; }
        table.source tr.hit td.cnt { color: #a6e3a1; }
        table.source tr.miss { background: #2a1a1f; }
        table.source tr.miss td.cnt { color: #f38ba8; }
        footer {
          padding: 1rem 2rem; color: #6c7086;
          border-top: 1px solid #313244; margin-top: 2rem;
        }
        .muted { color: #6c7086; font-style: italic; }
        """


# ---------------------------------------------------------------------------
# Pydantic v2 models used by Phase 4 dashboard
# ---------------------------------------------------------------------------


class CoverageKind(StrEnum):
    LINE = "line"
    TOGGLE = "toggle"
    BRANCH = "branch"
    CONDITION = "condition"
    FSM = "fsm"
    FUNCTIONAL = "functional"
    ASSERTION = "assertion"


class CoverageBin(BaseModel):
    name: str
    hits: int = 0
    target: int = 1
    weight: float = 1.0

    @property
    def covered(self) -> bool:
        return self.hits >= self.target


class FileCoverage(BaseModel):
    path: str
    total_lines: int = 0
    covered_lines: int = 0
    percent: float = 0.0
    line_hits: dict[int, int] = Field(default_factory=dict)

    def recompute(self) -> None:
        self.total_lines = len(self.line_hits)
        self.covered_lines = sum(1 for h in self.line_hits.values() if h > 0)
        self.percent = (
            (self.covered_lines / self.total_lines * 100.0)
            if self.total_lines
            else 0.0
        )


class ModuleCoverage(BaseModel):
    name: str
    kind: CoverageKind = CoverageKind.LINE
    total: int = 0
    hit: int = 0
    percent: float = 0.0
    bins: list[CoverageBin] = Field(default_factory=list)

    def recompute(self) -> None:
        if self.bins:
            self.total = len(self.bins)
            self.hit = sum(1 for b in self.bins if b.covered)
        self.percent = (self.hit / self.total * 100.0) if self.total else 0.0


class CoverageReportV2(BaseModel):
    """Pydantic v2 coverage report."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    test_name: str = ""
    files: dict[str, FileCoverage] = Field(default_factory=dict)
    modules: list[ModuleCoverage] = Field(default_factory=list)
    overall: dict[CoverageKind, float] = Field(default_factory=dict)

    def recompute_overall(self) -> None:
        if self.files:
            tot = sum(f.total_lines for f in self.files.values())
            cov = sum(f.covered_lines for f in self.files.values())
            self.overall[CoverageKind.LINE] = (cov / tot * 100.0) if tot else 0.0
        by_kind: dict[CoverageKind, tuple[int, int]] = {}
        for m in self.modules:
            t, h = by_kind.get(m.kind, (0, 0))
            by_kind[m.kind] = (t + m.total, h + m.hit)
        for k, (t, h) in by_kind.items():
            self.overall[k] = (h / t * 100.0) if t else 0.0

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------
    @classmethod
    def from_verilator_lcov(cls, lcov_path: str | Path) -> CoverageReportV2:
        """Parse a Verilator/GCov LCOV ``.info`` file.

        Handles TN / SF / DA / LH / LF / BRDA / end_of_record records.
        """
        report = cls(test_name=Path(lcov_path).stem)
        path = Path(lcov_path)
        if not path.exists():
            return report
        current: FileCoverage | None = None
        br_total = 0
        br_hit = 0
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("TN:"):
                name = line[3:].strip()
                if name:
                    report.test_name = name
            elif line.startswith("SF:"):
                sf = line[3:].strip()
                current = FileCoverage(path=sf)
                report.files[sf] = current
            elif line.startswith("DA:") and current is not None:
                try:
                    parts = line[3:].split(",")
                    lineno = int(parts[0])
                    count = int(parts[1])
                    current.line_hits[lineno] = count
                except (ValueError, IndexError):
                    continue
            elif line.startswith("LF:") and current is not None:
                with contextlib.suppress(ValueError):
                    current.total_lines = int(line[3:])
            elif line.startswith("LH:") and current is not None:
                with contextlib.suppress(ValueError):
                    current.covered_lines = int(line[3:])
            elif line.startswith("BRDA:"):
                try:
                    parts = line[5:].split(",")
                    taken = parts[3]
                    br_total += 1
                    if taken not in ("-", "0"):
                        br_hit += 1
                except IndexError:
                    pass
            elif line == "end_of_record":
                if current is not None:
                    current.recompute()
                current = None
        if br_total:
            report.modules.append(
                ModuleCoverage(
                    name="<branches>",
                    kind=CoverageKind.BRANCH,
                    total=br_total,
                    hit=br_hit,
                    percent=(br_hit / br_total * 100.0),
                )
            )
        report.recompute_overall()
        return report

    @classmethod
    def from_verilator_dat(cls, dat_path: str | Path) -> CoverageReportV2:
        """Parse a native Verilator ``coverage.dat``.

        Reuses the legacy :class:`CoverageParser` then normalises into the
        Pydantic model so both views share a single parser implementation.
        """
        legacy = CoverageParser().parse_verilator_dat(Path(dat_path))
        rep = cls(test_name=Path(dat_path).stem)
        for ld in legacy.line_details:
            fc = rep.files.get(ld.file)
            if fc is None:
                fc = FileCoverage(path=ld.file)
                rep.files[ld.file] = fc
            fc.line_hits[ld.line] = fc.line_hits.get(ld.line, 0) + ld.count
        for fc in rep.files.values():
            fc.recompute()
        if legacy.toggle_total:
            rep.modules.append(
                ModuleCoverage(
                    name="<toggles>",
                    kind=CoverageKind.TOGGLE,
                    total=legacy.toggle_total,
                    hit=legacy.toggle_covered,
                    percent=legacy.toggle_pct,
                )
            )
        if legacy.branch_total:
            rep.modules.append(
                ModuleCoverage(
                    name="<branches>",
                    kind=CoverageKind.BRANCH,
                    total=legacy.branch_total,
                    hit=legacy.branch_covered,
                    percent=legacy.branch_pct,
                )
            )
        if legacy.functional_total:
            bins = [
                CoverageBin(name=f"{f.covergroup}.{f.coverpoint}.{f.bin}", hits=f.hits)
                for f in legacy.functional_details
            ]
            rep.modules.append(
                ModuleCoverage(
                    name="<functional>",
                    kind=CoverageKind.FUNCTIONAL,
                    total=legacy.functional_total,
                    hit=legacy.functional_covered,
                    percent=legacy.functional_pct,
                    bins=bins,
                )
            )
        rep.recompute_overall()
        return rep

    @classmethod
    def from_icarus(cls, path: str | Path) -> CoverageReportV2:
        """Parse an Icarus coverage dump.

        Icarus writes simple ``file:line count`` lines when the ``-gcoverage``
        option is used; anything else is treated as no coverage.
        """
        rep = cls(test_name=Path(path).stem)
        p = Path(path)
        if not p.exists():
            return rep
        for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"(.+?):(\d+)\s+(\d+)", line)
            if not m:
                continue
            fname, lineno, cnt = m.group(1), int(m.group(2)), int(m.group(3))
            fc = rep.files.get(fname)
            if fc is None:
                fc = FileCoverage(path=fname)
                rep.files[fname] = fc
            fc.line_hits[lineno] = fc.line_hits.get(lineno, 0) + cnt
        for fc in rep.files.values():
            fc.recompute()
        rep.recompute_overall()
        return rep

    # ------------------------------------------------------------------
    # Merge / export
    # ------------------------------------------------------------------
    def merge(self, other: CoverageReportV2) -> CoverageReportV2:
        merged = CoverageReportV2(
            timestamp=datetime.now(UTC).isoformat(),
            test_name=f"{self.test_name}+{other.test_name}",
        )
        # Merge files
        for src in (self, other):
            for path, fc in src.files.items():
                dst = merged.files.get(path)
                if dst is None:
                    dst = FileCoverage(path=path)
                    merged.files[path] = dst
                for ln, h in fc.line_hits.items():
                    dst.line_hits[ln] = dst.line_hits.get(ln, 0) + h
        for fc in merged.files.values():
            fc.recompute()
        # Merge modules by (name, kind)
        mod_acc: dict[tuple[str, CoverageKind], ModuleCoverage] = {}
        for src in (self, other):
            for m in src.modules:
                key = (m.name, m.kind)
                cur = mod_acc.get(key)
                if cur is None:
                    mod_acc[key] = m.model_copy(deep=True)
                else:
                    cur.total = max(cur.total, m.total)
                    cur.hit = min(cur.total, cur.hit + m.hit)
                    # Merge bins by name
                    bins_idx = {b.name: b for b in cur.bins}
                    for b in m.bins:
                        if b.name in bins_idx:
                            bins_idx[b.name].hits += b.hits
                        else:
                            cur.bins.append(b.model_copy())
                    cur.recompute()
        merged.modules = list(mod_acc.values())
        merged.recompute_overall()
        return merged

    def to_lcov(self) -> str:
        """Emit the report as LCOV info text."""
        out: list[str] = []
        for path, fc in self.files.items():
            out.append(f"TN:{self.test_name}")
            out.append(f"SF:{path}")
            for ln in sorted(fc.line_hits):
                out.append(f"DA:{ln},{fc.line_hits[ln]}")
            out.append(f"LF:{fc.total_lines}")
            out.append(f"LH:{fc.covered_lines}")
            out.append("end_of_record")
        return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Trend database
# ---------------------------------------------------------------------------


class CoverageDb:
    """SQLite-backed trend database for coverage runs."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                test_name TEXT NOT NULL,
                payload TEXT NOT NULL
            )"""
        )
        self._conn.commit()

    def add_run(self, report: CoverageReportV2) -> int:
        cur = self._conn.execute(
            "INSERT INTO runs (timestamp, test_name, payload) VALUES (?, ?, ?)",
            (report.timestamp, report.test_name, report.model_dump_json()),
        )
        self._conn.commit()
        return int(cur.lastrowid or 0)

    def runs(self) -> list[CoverageReportV2]:
        cur = self._conn.execute("SELECT payload FROM runs ORDER BY id ASC")
        out: list[CoverageReportV2] = []
        for (payload,) in cur.fetchall():
            try:
                out.append(CoverageReportV2.model_validate(json.loads(payload)))
            except Exception:
                continue
        return out

    def merged(self) -> CoverageReportV2:
        runs = self.runs()
        if not runs:
            return CoverageReportV2(test_name="empty")
        acc = runs[0]
        for r in runs[1:]:
            acc = acc.merge(r)
        return acc

    def trend(self, kind: CoverageKind, last_n: int = 20) -> list[float]:
        runs = self.runs()[-last_n:]
        return [r.overall.get(kind, 0.0) for r in runs]

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.close()

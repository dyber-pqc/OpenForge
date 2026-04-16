"""Timing analysis integration wrapping OpenSTA with rich result parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from openforge.engine.opensta import OpenSTAEngine

if TYPE_CHECKING:
    from collections.abc import Sequence
    from os import PathLike

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TimingStage:
    """One stage (cell traversal) along a timing path."""

    cell_name: str
    cell_type: str
    delay_ns: float = 0.0
    arrival_ns: float = 0.0
    transition_ns: float = 0.0
    fanout: int = 0


@dataclass(frozen=True, slots=True)
class TimingPath:
    """A complete timing path from start to end point."""

    start_point: str
    end_point: str
    path_type: str  # "setup" or "hold"
    delay_ns: float = 0.0
    required_ns: float = 0.0
    slack_ns: float = 0.0
    stages: list[TimingStage] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TimingResult:
    """Aggregate timing analysis results."""

    paths: list[TimingPath] = field(default_factory=list)
    wns: float = 0.0
    tns: float = 0.0
    clocks: dict[str, dict[str, float]] = field(default_factory=dict)
    num_endpoints: int = 0
    num_violated: int = 0


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_timing_paths(text: str) -> list[TimingPath]:
    """Parse OpenSTA ``report_checks -format full`` output into structured paths.

    The output format is a series of path blocks delimited by lines of
    dashes.  Each block contains:

    * Startpoint / Endpoint header lines
    * Path Type (max = setup, min = hold)
    * A table of stages with columns for cell, delay, arrival, transition
    * A slack summary line
    """
    paths: list[TimingPath] = []

    # Split into path report blocks -- each starts with "Startpoint:"
    blocks = re.split(r"(?=Startpoint:)", text)

    for block in blocks:
        if "Startpoint:" not in block:
            continue

        start_point = ""
        end_point = ""
        path_type = "setup"
        slack = 0.0
        required = 0.0
        arrival = 0.0
        stages: list[TimingStage] = []

        # Extract start/end points
        if m := re.search(r"Startpoint:\s*(\S+)", block):
            start_point = m.group(1)
        if m := re.search(r"Endpoint:\s*(\S+)", block):
            end_point = m.group(1)

        # Path type
        if m := re.search(r"Path Type:\s*(\S+)", block):
            ptype = m.group(1).lower()
            path_type = "hold" if ptype in ("min", "hold") else "setup"

        # Parse stage lines.  OpenSTA format:
        #   <pin>   <cell>   <delay>   <arrival>   <transition>   <fanout>
        # Lines vary by version, so we look for numeric columns
        stage_pattern = re.compile(
            r"^\s*(\S+)\s+"           # pin name
            r"(\S+)\s+"              # cell/instance
            r"([-+]?[\d.]+)\s+"     # delay
            r"([-+]?[\d.]+)"        # arrival
            r"(?:\s+([-+]?[\d.]+))?" # transition (optional)
            r"(?:\s+(\d+))?"        # fanout (optional)
            r"\s*$",
            re.MULTILINE,
        )

        for sm in stage_pattern.finditer(block):
            cell_name = sm.group(1)
            cell_type = sm.group(2)
            delay = float(sm.group(3))
            arr = float(sm.group(4))
            trans = float(sm.group(5)) if sm.group(5) else 0.0
            fo = int(sm.group(6)) if sm.group(6) else 0

            stages.append(TimingStage(
                cell_name=cell_name,
                cell_type=cell_type,
                delay_ns=delay,
                arrival_ns=arr,
                transition_ns=trans,
                fanout=fo,
            ))

        # Slack
        if (m := re.search(r"slack\s+\((?:VIOLATED|MET)\)\s+([-+]?[\d.]+)", block)) or (m := re.search(r"slack\s+([-+]?[\d.]+)", block)):
            slack = float(m.group(1))

        # Required time
        if m := re.search(r"data required time\s+([-+]?[\d.]+)", block):
            required = float(m.group(1))

        # Data arrival time
        if m := re.search(r"data arrival time\s+([-+]?[\d.]+)", block):
            arrival = float(m.group(1))

        total_delay = arrival if arrival else (
            stages[-1].arrival_ns if stages else 0.0
        )

        paths.append(TimingPath(
            start_point=start_point,
            end_point=end_point,
            path_type=path_type,
            delay_ns=total_delay,
            required_ns=required,
            slack_ns=slack,
            stages=stages,
        ))

    return paths


def _parse_wns(text: str) -> float:
    """Extract worst negative slack from report_wns output."""
    if m := re.search(r"wns\s+([-+]?[\d.]+)", text):
        return float(m.group(1))
    return 0.0


def _parse_tns(text: str) -> float:
    """Extract total negative slack from report_tns output."""
    if m := re.search(r"tns\s+([-+]?[\d.]+)", text):
        return float(m.group(1))
    return 0.0


def _parse_clock_info(text: str) -> dict[str, dict[str, float]]:
    """Extract per-clock summary from STA output.

    Returns a dict keyed by clock name with sub-keys:
    ``period``, ``frequency_achieved``, ``slack``.
    """
    clocks: dict[str, dict[str, float]] = {}

    # Look for clock definitions: create_clock -name <name> -period <period>
    for m in re.finditer(
        r"(?:create_clock|Clock)\s+(\S+)\s+.*?period\s+([\d.]+)",
        text,
        re.IGNORECASE,
    ):
        name = m.group(1)
        period = float(m.group(2))
        clocks[name] = {
            "period": period,
            "frequency_achieved": 1000.0 / period if period > 0 else 0.0,
            "slack": 0.0,
        }

    # Try to associate slack with clocks from path reports
    for m in re.finditer(
        r"Clock\s+(\S+)\s+.*?slack\s+\((?:VIOLATED|MET)\)\s+([-+]?[\d.]+)",
        text,
    ):
        name = m.group(1)
        slack = float(m.group(2))
        if name in clocks:
            clocks[name]["slack"] = slack

    return clocks


# ---------------------------------------------------------------------------
# TimingAnalyzer
# ---------------------------------------------------------------------------


class TimingAnalyzer:
    """Static timing analysis wrapper with structured result parsing.

    Uses :class:`OpenSTAEngine` to run STA and parses the full
    ``report_checks`` output into :class:`TimingPath` objects.

    Typical workflow::

        analyzer = TimingAnalyzer()
        result = analyzer.run_analysis(
            liberty="sky130.lib",
            netlist="synth.v",
            sdc="constraints.sdc",
            top_module="top",
        )
        for path in result.paths:
            print(f"{path.start_point} -> {path.end_point}: {path.slack_ns} ns")
    """

    def __init__(self) -> None:
        self._sta = OpenSTAEngine()
        self._last_output: str = ""

    # ------------------------------------------------------------------
    # Full analysis
    # ------------------------------------------------------------------

    def run_analysis(
        self,
        liberty: str | PathLike[str],
        netlist: str | PathLike[str],
        sdc: str | PathLike[str],
        *,
        top_module: str = "top",
        corners: Sequence[str | PathLike[str]] | None = None,
        num_paths: int = 50,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> TimingResult:
        """Run a full static timing analysis flow.

        Parameters
        ----------
        liberty:
            Liberty timing library (``.lib``) file.
        netlist:
            Gate-level Verilog netlist.
        sdc:
            SDC timing constraints file.
        top_module:
            Top-level module name.
        corners:
            Additional Liberty files for multi-corner analysis.
        num_paths:
            Number of worst paths to report.
        cwd:
            Working directory.
        timeout:
            Process timeout in seconds.
        """
        extra_tcl: list[str] = []

        # Read additional corner libraries
        if corners:
            for corner_lib in corners:
                extra_tcl.append(f"read_liberty {corner_lib}")

        extra_tcl.extend([
            f"report_checks -path_delay max -format full -fields {{capacitance slew input_pins nets fanout}} -digits 4 -endpoint_count {num_paths}",
            f"report_checks -path_delay min -format full -fields {{capacitance slew input_pins nets fanout}} -digits 4 -endpoint_count {num_paths}",
        ])

        result = self._sta.run_timing(
            liberty=liberty,
            verilog_netlist=netlist,
            sdc=sdc,
            top_module=top_module,
            extra_tcl=extra_tcl,
            cwd=cwd,
            timeout=timeout,
        )

        self._last_output = result.stdout + result.stderr
        return self.parse_timing_report(self._last_output)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def parse_timing_report(self, sta_output: str) -> TimingResult:
        """Parse the full OpenSTA output into a structured :class:`TimingResult`.

        Parameters
        ----------
        sta_output:
            Raw stdout+stderr from an OpenSTA run.

        Returns
        -------
        TimingResult
        """
        paths = _parse_timing_paths(sta_output)
        wns = self.parse_wns(sta_output)
        tns = self.parse_tns(sta_output)
        clocks = _parse_clock_info(sta_output)

        num_violated = sum(1 for p in paths if p.slack_ns < 0)
        num_endpoints = len(paths)

        return TimingResult(
            paths=paths,
            wns=wns,
            tns=tns,
            clocks=clocks,
            num_endpoints=num_endpoints,
            num_violated=num_violated,
        )

    @staticmethod
    def parse_tns(output: str) -> float:
        """Extract total negative slack from STA output."""
        return _parse_tns(output)

    @staticmethod
    def parse_wns(output: str) -> float:
        """Extract worst negative slack from STA output."""
        return _parse_wns(output)

    # ------------------------------------------------------------------
    # Convenience queries
    # ------------------------------------------------------------------

    def get_critical_paths(self, n: int = 10) -> list[TimingPath]:
        """Return the top *n* worst (most negative slack) paths from the last analysis.

        Parameters
        ----------
        n:
            Number of paths to return.

        Returns
        -------
        list[TimingPath]
            Paths sorted by slack (worst first).
        """
        paths = _parse_timing_paths(self._last_output)
        paths.sort(key=lambda p: p.slack_ns)
        return paths[:n]

    def get_clock_summary(self) -> dict[str, dict[str, float]]:
        """Return per-clock timing summary from the last analysis.

        Returns
        -------
        dict
            Keyed by clock name with sub-keys ``period``,
            ``frequency_achieved`` (MHz), and ``slack`` (ns).
        """
        return _parse_clock_info(self._last_output)

    def get_slack_histogram(self, bins: int = 20) -> list[tuple[tuple[float, float], int]]:
        """Build a histogram of endpoint slack values.

        Parameters
        ----------
        bins:
            Number of histogram bins.

        Returns
        -------
        list[tuple[tuple[float, float], int]]
            Each entry is ``((low, high), count)`` representing a bin
            range and the number of endpoints that fall into it.
        """
        paths = _parse_timing_paths(self._last_output)
        if not paths:
            return []

        slacks = [p.slack_ns for p in paths]
        min_slack = min(slacks)
        max_slack = max(slacks)

        if min_slack == max_slack:
            return [((min_slack, max_slack), len(slacks))]

        bin_width = (max_slack - min_slack) / bins
        histogram: list[tuple[tuple[float, float], int]] = []

        for i in range(bins):
            low = min_slack + i * bin_width
            high = low + bin_width
            count = sum(1 for s in slacks if low <= s < high)
            # Include the upper bound in the last bin
            if i == bins - 1:
                count = sum(1 for s in slacks if low <= s <= high)
            histogram.append(((round(low, 4), round(high, 4)), count))

        return histogram

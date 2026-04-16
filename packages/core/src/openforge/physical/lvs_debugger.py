"""Production-grade LVS debugger for OpenForge.

A Mentor Calibre nmLVS replacement built on top of Netgen + custom analysis.
"""
from __future__ import annotations

import html
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class LvsNet:
    name_layout: str
    name_schematic: str
    matched: bool
    devices: list[str] = field(default_factory=list)


@dataclass
class LvsDevice:
    instance: str
    type: str  # nfet, pfet, R, C, ...
    parameters: dict[str, str] = field(default_factory=dict)
    matched: bool = False


@dataclass
class LvsMismatch:
    type: str  # net_count, device_count, port_mismatch, parameter_mismatch
    layout_value: str
    schematic_value: str
    location: tuple[float, float] | None = None
    description: str = ""


@dataclass
class LvsDebugResult:
    matched: bool
    layout_nets: int = 0
    schematic_nets: int = 0
    layout_devices: int = 0
    schematic_devices: int = 0
    matched_nets: list[LvsNet] = field(default_factory=list)
    unmatched_nets: list[LvsNet] = field(default_factory=list)
    matched_devices: list[LvsDevice] = field(default_factory=list)
    unmatched_devices: list[LvsDevice] = field(default_factory=list)
    mismatches: list[LvsMismatch] = field(default_factory=list)
    duration: float = 0.0
    log: str = ""

    @property
    def net_delta(self) -> int:
        return self.layout_nets - self.schematic_nets

    @property
    def device_delta(self) -> int:
        return self.layout_devices - self.schematic_devices

    def summary(self) -> str:
        status = "MATCH" if self.matched else "MISMATCH"
        return (
            f"LVS {status}\n"
            f"  Layout    nets={self.layout_nets} devices={self.layout_devices}\n"
            f"  Schematic nets={self.schematic_nets} devices={self.schematic_devices}\n"
            f"  Mismatches: {len(self.mismatches)}\n"
            f"  Duration:   {self.duration:.2f}s"
        )


# ---------------------------------------------------------------------------
# Debugger
# ---------------------------------------------------------------------------


class LvsDebugger:
    """Production-grade LVS debugger using Netgen + custom analysis."""

    def __init__(self):
        self._last_result: Optional[LvsDebugResult] = None

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run_lvs(
        self,
        layout_netlist: Path,
        schematic_netlist: Path,
        top_module: str,
        setup_file: Optional[Path] = None,
        cwd: Optional[Path] = None,
    ) -> LvsDebugResult:
        """Run Netgen LVS and parse the output for debugging."""
        layout_netlist = Path(layout_netlist)
        schematic_netlist = Path(schematic_netlist)
        cwd = Path(cwd) if cwd else Path.cwd()
        comp_out = cwd / "comp.out"

        start = time.time()
        log = ""
        try:
            tcl = self._build_netgen_script(
                layout_netlist, schematic_netlist, top_module,
                setup_file, comp_out,
            )
            tcl_path = cwd / "_openforge_lvs.tcl"
            tcl_path.write_text(tcl, encoding="utf-8")
            proc = subprocess.run(
                ["netgen", "-batch", "source", str(tcl_path)],
                capture_output=True, text=True, timeout=600, cwd=str(cwd),
            )
            log = (proc.stdout or "") + (proc.stderr or "")
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            log = f"Netgen unavailable: {e}\n"

        if comp_out.exists():
            result = self.parse_comp_out(comp_out)
        else:
            result = self.parse_netgen_output(log)
        result.log = log
        result.duration = time.time() - start
        self._last_result = result
        return result

    @staticmethod
    def _build_netgen_script(
        layout: Path, schematic: Path, top: str,
        setup: Optional[Path], comp_out: Path,
    ) -> str:
        setup_line = f'source "{setup}"\n' if setup else ""
        return (
            f'{setup_line}'
            f'lvs {{ "{layout}" "{top}" }} {{ "{schematic}" "{top}" }} '
            f'nofile "{comp_out}"\n'
            f'quit\n'
        )

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    _RE_NET_COUNT = re.compile(
        r"Subcircuit summary:.*?Nets:\s*(\d+)\s+(\d+)", re.DOTALL,
    )
    _RE_DEV_COUNT = re.compile(
        r"Devices:\s*(\d+)\s+(\d+)", re.DOTALL,
    )
    _RE_NET_LINE = re.compile(
        r"^\s*([A-Za-z0-9_/\[\].]+)\s*\|\s*([A-Za-z0-9_/\[\].]+)\s*$",
    )

    def parse_netgen_output(self, output: str) -> LvsDebugResult:
        result = LvsDebugResult(matched=False)
        if not output:
            return result

        m = self._RE_NET_COUNT.search(output)
        if m:
            result.layout_nets = int(m.group(1))
            result.schematic_nets = int(m.group(2))
        m = self._RE_DEV_COUNT.search(output)
        if m:
            result.layout_devices = int(m.group(1))
            result.schematic_devices = int(m.group(2))

        lines = output.splitlines()
        for line in lines:
            ml = self._RE_NET_LINE.match(line)
            if ml:
                a, b = ml.group(1), ml.group(2)
                net = LvsNet(name_layout=a, name_schematic=b, matched=(a == b))
                if net.matched:
                    result.matched_nets.append(net)
                else:
                    result.unmatched_nets.append(net)

        if result.layout_nets != result.schematic_nets:
            result.mismatches.append(
                LvsMismatch(
                    type="net_count",
                    layout_value=str(result.layout_nets),
                    schematic_value=str(result.schematic_nets),
                    description="Net count differs between layout and schematic",
                )
            )
        if result.layout_devices != result.schematic_devices:
            result.mismatches.append(
                LvsMismatch(
                    type="device_count",
                    layout_value=str(result.layout_devices),
                    schematic_value=str(result.schematic_devices),
                    description="Device count differs between layout and schematic",
                )
            )

        result.matched = (
            "Circuits match uniquely." in output
            or "Networks match." in output
            or (
                not result.mismatches
                and not result.unmatched_nets
                and result.layout_nets > 0
            )
        )
        return result

    def parse_comp_out(self, comp_out_path: Path) -> LvsDebugResult:
        try:
            text = Path(comp_out_path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return LvsDebugResult(matched=False)
        result = self.parse_netgen_output(text)
        if "Circuits match uniquely" in text:
            result.matched = True
        return result

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def find_root_cause(self, result: LvsDebugResult) -> str:
        """Identify the most likely root cause of mismatches."""
        if result.matched:
            return "No mismatches; layout and schematic are equivalent."

        if result.layout_devices != result.schematic_devices:
            delta = result.device_delta
            direction = "extra" if delta > 0 else "missing"
            return (
                f"Device count mismatch ({delta:+d}). "
                f"Layout has {direction} {abs(delta)} device(s). "
                "Likely cause: a transistor was added/removed during placement, "
                "or extraction missed a device."
            )

        if result.layout_nets != result.schematic_nets:
            delta = result.net_delta
            direction = "extra" if delta > 0 else "missing"
            return (
                f"Net count mismatch ({delta:+d}). "
                f"Layout has {direction} {abs(delta)} net(s). "
                "Likely cause: a short or open in routing, or a missing tie-cell."
            )

        port_issues = [m for m in result.mismatches if m.type == "port_mismatch"]
        if port_issues:
            return (
                f"Port order mismatch on {len(port_issues)} cell(s). "
                "Check pin definitions in the LEF/LIB versus the schematic."
            )

        param_issues = [m for m in result.mismatches if m.type == "parameter_mismatch"]
        if param_issues:
            return (
                f"Parameter mismatch on {len(param_issues)} device(s). "
                "Check W/L values for FETs or R/C values for passives."
            )

        if result.unmatched_nets:
            return (
                f"{len(result.unmatched_nets)} net(s) unmatched even though "
                "counts agree. Likely a connectivity error - a wire is "
                "connected to the wrong node."
            )

        return "Unknown mismatch; inspect the netgen log for details."

    def suggest_fixes(self, result: LvsDebugResult) -> list[str]:
        suggestions: list[str] = []
        if result.matched:
            return ["LVS is clean - no fixes needed."]

        if result.device_delta > 0:
            suggestions.append(
                "Remove the extra layout device(s). Check fill cells, "
                "antenna diodes, or accidentally-placed cells."
            )
        elif result.device_delta < 0:
            suggestions.append(
                "Add missing device(s) to the layout. Confirm that all "
                "schematic instances were placed and not optimized away."
            )

        if result.net_delta > 0:
            suggestions.append(
                "Layout has extra nets. Check for routing shorts, "
                "or stray geometry creating phantom nets."
            )
        elif result.net_delta < 0:
            suggestions.append(
                "Layout is missing nets. Check for routing opens, "
                "missing vias, or unconnected pins."
            )

        if result.unmatched_nets and not result.mismatches:
            suggestions.append(
                "Run `netgen -batch lvs ... -accept` interactively to find "
                "the first connectivity divergence."
            )

        for m in result.mismatches:
            if m.type == "parameter_mismatch":
                suggestions.append(
                    f"Fix device parameters: layout={m.layout_value} vs "
                    f"schematic={m.schematic_value} ({m.description})"
                )
            elif m.type == "port_mismatch":
                suggestions.append(
                    f"Reorder ports: layout={m.layout_value} vs "
                    f"schematic={m.schematic_value}"
                )

        if not suggestions:
            suggestions.append(
                "Inspect the raw netgen log; the mismatch is unusual."
            )
        return suggestions

    # ------------------------------------------------------------------
    # Diff report
    # ------------------------------------------------------------------

    def generate_diff_report(self, result: LvsDebugResult, output: Path) -> Path:
        """Generate a side-by-side diff HTML report."""
        output = Path(output)
        status_color = "#a6e3a1" if result.matched else "#f38ba8"
        status_text = "MATCH" if result.matched else "MISMATCH"

        rows_nets = "".join(
            f"<tr><td>{html.escape(n.name_layout)}</td>"
            f"<td>{html.escape(n.name_schematic)}</td>"
            f"<td style='color:#f38ba8'>NO</td></tr>"
            for n in result.unmatched_nets[:200]
        ) or "<tr><td colspan='3'><i>No unmatched nets</i></td></tr>"

        rows_mm = "".join(
            f"<tr><td>{html.escape(m.type)}</td>"
            f"<td>{html.escape(m.layout_value)}</td>"
            f"<td>{html.escape(m.schematic_value)}</td>"
            f"<td>{html.escape(m.description)}</td></tr>"
            for m in result.mismatches
        ) or "<tr><td colspan='4'><i>No mismatches</i></td></tr>"

        suggestions = "".join(
            f"<li>{html.escape(s)}</li>" for s in self.suggest_fixes(result)
        )
        root_cause = html.escape(self.find_root_cause(result))

        doc = f"""<!doctype html>
<html><head><meta charset='utf-8'><title>LVS Diff Report</title>
<style>
  body {{ font-family: sans-serif; background: #1e1e2e; color: #cdd6f4;
          padding: 20px; }}
  h1 {{ color: {status_color}; }}
  table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
  th, td {{ border: 1px solid #45475a; padding: 6px 10px; text-align: left; }}
  th {{ background: #313244; }}
  .stats span {{ display: inline-block; margin-right: 20px; }}
  .root {{ background: #313244; padding: 10px; border-left: 4px solid #89b4fa; }}
</style></head><body>
<h1>LVS {status_text}</h1>
<div class='stats'>
  <span>Layout nets: <b>{result.layout_nets}</b></span>
  <span>Schematic nets: <b>{result.schematic_nets}</b></span>
  <span>Layout devices: <b>{result.layout_devices}</b></span>
  <span>Schematic devices: <b>{result.schematic_devices}</b></span>
  <span>Duration: <b>{result.duration:.2f}s</b></span>
</div>
<h2>Root Cause</h2>
<div class='root'>{root_cause}</div>
<h2>Suggested Fixes</h2>
<ul>{suggestions}</ul>
<h2>Mismatches</h2>
<table>
<tr><th>Type</th><th>Layout</th><th>Schematic</th><th>Description</th></tr>
{rows_mm}
</table>
<h2>Unmatched Nets</h2>
<table>
<tr><th>Layout net</th><th>Schematic net</th><th>Matched</th></tr>
{rows_nets}
</table>
</body></html>
"""
        output.write_text(doc, encoding="utf-8")
        return output


__all__ = [
    "LvsNet",
    "LvsDevice",
    "LvsMismatch",
    "LvsDebugResult",
    "LvsDebugger",
]

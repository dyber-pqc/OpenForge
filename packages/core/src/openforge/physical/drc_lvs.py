"""DRC and LVS runners wrapping Magic and Netgen engines."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from openforge.engine.magic import MagicEngine
from openforge.engine.netgen import NetgenEngine

if TYPE_CHECKING:
    from os import PathLike

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DRCViolation:
    """A single DRC rule violation."""

    rule: str
    message: str
    x: float = 0.0
    y: float = 0.0
    layer: str = ""
    severity: str = "error"  # "error" | "warning"


@dataclass(frozen=True, slots=True)
class DRCResult:
    """Aggregate DRC results."""

    passed: bool
    violations: list[DRCViolation] = field(default_factory=list)
    total_count: int = 0
    by_category: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LVSResult:
    """Aggregate LVS comparison results."""

    match: bool
    mismatches: list[str] = field(default_factory=list)
    device_count_layout: int = 0
    device_count_schematic: int = 0
    net_count: int = 0


# ---------------------------------------------------------------------------
# DRC parsing
# ---------------------------------------------------------------------------


def _parse_drc_output(text: str) -> list[DRCViolation]:
    """Parse Magic DRC output into structured violations.

    Magic outputs DRC violations in a format like::

        [INFO]: DRC: <rule_name> at (<x>, <y>) on layer <layer>
        <description text>

    or via the ``drc listall why`` TCL command which prints grouped
    rule names followed by coordinate pairs.
    """
    violations: list[DRCViolation] = []

    # Pattern 1: "[INFO]: DRC rule at (x, y) on layer ..."
    for m in re.finditer(
        r"(?:DRC|Rule)\s*[:\-]?\s*(\S+)\s+"
        r"(?:at\s+)?\(?\s*([-\d.]+)\s*,?\s*([-\d.]+)\s*\)?"
        r"(?:\s+(?:on\s+)?(?:layer\s+)?(\S+))?",
        text,
        re.IGNORECASE,
    ):
        violations.append(
            DRCViolation(
                rule=m.group(1),
                message=m.group(0).strip(),
                x=float(m.group(2)),
                y=float(m.group(3)),
                layer=m.group(4) or "",
            )
        )

    # Pattern 2: grouped "drc listall why" output
    # Format: "<rule description>\n  (<x1> <y1> <x2> <y2>)\n ..."
    rule_blocks = re.split(r"\n(?=\S)", text)
    for block in rule_blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        rule_line = lines[0].strip()
        # Skip lines that are obviously not DRC rules
        if not rule_line or rule_line.startswith(("[", "#", "DRC errors")):
            continue
        for coord_line in lines[1:]:
            coord_match = re.match(
                r"\s*\(?\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*\)?",
                coord_line,
            )
            if coord_match:
                x = (float(coord_match.group(1)) + float(coord_match.group(3))) / 2
                y = (float(coord_match.group(2)) + float(coord_match.group(4))) / 2
                violations.append(
                    DRCViolation(
                        rule=rule_line,
                        message=rule_line,
                        x=x,
                        y=y,
                    )
                )

    return violations


def _categorize_violations(violations: list[DRCViolation]) -> dict[str, int]:
    """Group violations by rule name and count occurrences."""
    cats: dict[str, int] = {}
    for v in violations:
        cats[v.rule] = cats.get(v.rule, 0) + 1
    return cats


# ---------------------------------------------------------------------------
# LVS parsing
# ---------------------------------------------------------------------------


def _parse_lvs_output(text: str) -> LVSResult:
    """Parse Netgen LVS comparison output.

    Netgen prints ``Circuits match uniquely.`` on success, or lists
    mismatches on failure.
    """
    match = "Circuits match uniquely." in text

    mismatches: list[str] = []
    for m in re.finditer(r"(?:Mismatch|MISMATCH|NET mismatch|Flattening)[^\n]*", text):
        mismatches.append(m.group(0).strip())

    # Device counts
    device_layout = 0
    device_schematic = 0
    if m := re.search(r"Circuit\s+1.*?contains\s+(\d+)\s+device", text, re.IGNORECASE):
        device_layout = int(m.group(1))
    if m := re.search(r"Circuit\s+2.*?contains\s+(\d+)\s+device", text, re.IGNORECASE):
        device_schematic = int(m.group(1))

    # Net count
    net_count = 0
    if m := re.search(r"(\d+)\s+nets?\s+", text, re.IGNORECASE):
        net_count = int(m.group(1))

    return LVSResult(
        match=match,
        mismatches=mismatches,
        device_count_layout=device_layout,
        device_count_schematic=device_schematic,
        net_count=net_count,
    )


# ---------------------------------------------------------------------------
# DRCRunner
# ---------------------------------------------------------------------------


class DRCRunner:
    """Run design-rule checks using Magic.

    Typical workflow::

        drc = DRCRunner()
        result = drc.run_drc("layout.gds", pdk="sky130", tech_file="sky130A.tech")
        if not result.passed:
            for v in result.violations:
                print(f"{v.rule} at ({v.x}, {v.y})")
    """

    def __init__(self) -> None:
        self._magic = MagicEngine()

    def run_drc(
        self,
        gds_or_mag: str | PathLike[str],
        *,
        pdk: str = "sky130",
        tech_file: str | PathLike[str] | None = None,
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> DRCResult:
        """Run DRC on a GDS or Magic layout file.

        Parameters
        ----------
        gds_or_mag:
            Layout file (``.gds``, ``.gds2``, ``.mag``).
        pdk:
            PDK name (used to locate tech file if not provided).
        tech_file:
            Magic technology file.
        cwd:
            Working directory.
        timeout:
            Process timeout in seconds.
        """
        layout_path = Path(gds_or_mag)
        extra_tcl: list[str] = []

        # For GDS files, import via Magic GDS read
        if layout_path.suffix.lower() in (".gds", ".gds2"):
            extra_tcl = [
                f"gds read {layout_path}",
                "select top cell",
                "drc check",
                "drc catchup",
                "set drc_result [drc listall why]",
                'puts "DRC_RESULT_START"',
                "puts $drc_result",
                'puts "DRC_RESULT_END"',
                "quit -noprompt",
            ]
            result = self._magic._run_magic_tcl(
                extra_tcl,
                tech_file=tech_file,
                cwd=cwd,
                timeout=timeout,
            )
        else:
            # .mag file -- use the engine's run_drc directly
            result = self._magic.run_drc(
                layout_path,
                tech_file=tech_file,
                cwd=cwd,
                timeout=timeout,
            )

        combined = result.stdout + result.stderr
        violations = self.parse_drc_results(combined)
        by_category = _categorize_violations(violations)

        return DRCResult(
            passed=result.ok and len(violations) == 0,
            violations=violations,
            total_count=len(violations),
            by_category=by_category,
        )

    @staticmethod
    def parse_drc_results(output: str) -> list[DRCViolation]:
        """Parse DRC output text into structured violations."""
        return _parse_drc_output(output)


# ---------------------------------------------------------------------------
# LVSRunner
# ---------------------------------------------------------------------------


class LVSRunner:
    """Run layout-vs-schematic checks using Netgen.

    Typical workflow::

        lvs = LVSRunner()
        result = lvs.run_lvs(
            layout_netlist="extracted.spice",
            schematic_netlist="synth.v",
            setup_file="setup.tcl",
        )
        print("LVS match:", result.match)
    """

    def __init__(self) -> None:
        self._netgen = NetgenEngine()

    def run_lvs(
        self,
        layout_netlist: str | PathLike[str],
        schematic_netlist: str | PathLike[str],
        *,
        setup_file: str | PathLike[str] | None = None,
        output: str | PathLike[str] | None = None,
        layout_type: str = "spice",
        schematic_type: str = "verilog",
        cwd: str | PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> LVSResult:
        """Run an LVS comparison between layout and schematic netlists.

        Parameters
        ----------
        layout_netlist:
            Extracted layout netlist (typically SPICE from Magic).
        schematic_netlist:
            Schematic/source netlist (gate-level Verilog or SPICE).
        setup_file:
            Netgen setup/configuration TCL file with device mappings.
        output:
            Path for the LVS comparison report.
        layout_type:
            Netlist format of the layout file (``"spice"``, ``"verilog"``).
        schematic_type:
            Netlist format of the schematic file.
        cwd:
            Working directory.
        timeout:
            Process timeout in seconds.
        """
        result = self._netgen.run_lvs(
            netlist1=layout_netlist,
            netlist2=schematic_netlist,
            setup_file=setup_file,
            output=output,
            netlist1_type=layout_type,
            netlist2_type=schematic_type,
            cwd=cwd,
            timeout=timeout,
        )

        combined = result.stdout + result.stderr
        return self.parse_lvs_results(combined)

    @staticmethod
    def parse_lvs_results(output: str) -> LVSResult:
        """Parse Netgen LVS output into a structured result."""
        return _parse_lvs_output(output)

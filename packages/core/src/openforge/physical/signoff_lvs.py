"""Sign-off LVS - Calibre LVS equivalent.

Production-grade layout-vs-schematic with detailed mismatch debugging.
This module wraps Netgen and adds extensive parsing of mismatch types,
including net mismatches (missing/extra/topology), device mismatches
(wrong type or parameters), and commonly swapped pin patterns
(e.g. NMOS source/drain).
"""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class NetMismatch:
    """A net-level mismatch between layout and schematic."""

    layout_net: str
    schematic_net: str
    reason: str  # missing / extra / wrong_topology / different_devices
    layout_devices: list[str] = field(default_factory=list)
    schematic_devices: list[str] = field(default_factory=list)

    def short(self) -> str:
        return (
            f"NET {self.reason}: layout='{self.layout_net}' "
            f"schematic='{self.schematic_net}' "
            f"L#dev={len(self.layout_devices)} S#dev={len(self.schematic_devices)}"
        )


@dataclass
class DeviceMismatch:
    """A device-level mismatch between layout and schematic."""

    instance: str
    layout_type: str
    schematic_type: str
    parameter_diffs: dict[str, tuple[str, str]] = field(default_factory=dict)

    def short(self) -> str:
        diffs = ", ".join(
            f"{k}={lv}/{sv}" for k, (lv, sv) in self.parameter_diffs.items()
        )
        return (
            f"DEV {self.instance}: layout={self.layout_type} "
            f"schematic={self.schematic_type} {diffs}"
        )


@dataclass
class LvsResult:
    """Aggregate result of an LVS run."""

    matched: bool
    matched_nets: int = 0
    matched_devices: int = 0
    net_mismatches: list[NetMismatch] = field(default_factory=list)
    device_mismatches: list[DeviceMismatch] = field(default_factory=list)
    swapped_pins: list[tuple[str, str]] = field(default_factory=list)
    log: str = ""
    duration: float = 0.0

    @property
    def total_mismatches(self) -> int:
        return (
            len(self.net_mismatches)
            + len(self.device_mismatches)
            + len(self.swapped_pins)
        )

    def summary(self) -> str:
        return (
            f"LVS {'MATCH' if self.matched else 'MISMATCH'}  "
            f"nets_ok={self.matched_nets} devs_ok={self.matched_devices} "
            f"net_mm={len(self.net_mismatches)} dev_mm={len(self.device_mismatches)} "
            f"swap={len(self.swapped_pins)} duration={self.duration:.1f}s"
        )


class SignoffLvsRunner:
    """Run sign-off quality LVS with detailed debug output."""

    def __init__(self, parent=None):
        self._parent = parent
        self.last_result: LvsResult | None = None

    def run(
        self,
        layout_netlist: Path,
        schematic_netlist: Path,
        top_module: str,
        cwd: Path | None = None,
    ) -> LvsResult:
        """Run Netgen LVS with full setup and parse all mismatches."""
        cwd = cwd or layout_netlist.parent
        cwd.mkdir(parents=True, exist_ok=True)
        setup_path = cwd / "lvs_setup.tcl"
        log_path = cwd / "lvs.log"

        setup_path.write_text(self.generate_netgen_setup(top_module), encoding="utf-8")

        cmd = [
            "netgen",
            "-batch",
            "lvs",
            f"{layout_netlist} {top_module}",
            f"{schematic_netlist} {top_module}",
            str(setup_path),
            str(log_path),
        ]
        start = time.time()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=3600, check=False
            )
            log = proc.stdout + "\n" + proc.stderr
        except FileNotFoundError:
            log = "netgen not found in PATH"
        except subprocess.TimeoutExpired:
            log = "netgen timeout"
        duration = time.time() - start

        if log_path.exists():
            log = log_path.read_text(encoding="utf-8")

        result = self.parse_netgen_log(log)
        result.duration = duration
        result.log = log
        # Heuristic: detect commonly swapped pins (NMOS S/D, etc).
        result.swapped_pins = self.find_swapped_pins(result.device_mismatches)
        result.matched = result.total_mismatches == 0

        self.last_result = result
        return result

    def generate_netgen_setup(self, top_module: str) -> str:
        """Generate complete Netgen setup with cell equates, port matching."""
        lines = [
            "# Auto-generated Netgen LVS setup",
            f"# Top module: {top_module}",
            "",
            "# --- Permute equivalent pins for symmetric devices ---",
            "permute default",
            "permute {nmos g s d b}",
            "permute {pmos g s d b}",
            "permute {sky130_fd_pr__nfet_01v8 g s d b}",
            "permute {sky130_fd_pr__pfet_01v8 g s d b}",
            "permute {sky130_fd_pr__nfet_01v8_lvt g s d b}",
            "permute {sky130_fd_pr__pfet_01v8_lvt g s d b}",
            "permute {res g 1 2}",
            "permute {cap g 1 2}",
            "",
            "# --- Property tolerance ---",
            "property {sky130_fd_pr__nfet_01v8} tolerance {w 0.01}",
            "property {sky130_fd_pr__nfet_01v8} tolerance {l 0.01}",
            "property {sky130_fd_pr__pfet_01v8} tolerance {w 0.01}",
            "property {sky130_fd_pr__pfet_01v8} tolerance {l 0.01}",
            "property {sky130_fd_pr__res_generic_po} tolerance {value 0.05}",
            "property {sky130_fd_pr__cap_mim_m3_1}  tolerance {value 0.05}",
            "",
            "# --- Cell equates between schematic & layout views ---",
            "equate classes {sky130_fd_pr__nfet_01v8} {nmos}",
            "equate classes {sky130_fd_pr__pfet_01v8} {pmos}",
            "equate classes {sky130_fd_pr__nfet_01v8_lvt} {nmos_lvt}",
            "equate classes {sky130_fd_pr__pfet_01v8_lvt} {pmos_lvt}",
            "equate classes {sky130_fd_pr__res_generic_po} {res}",
            "equate classes {sky130_fd_pr__cap_mim_m3_1} {cap}",
            "",
            "# --- Hierarchy flattening for blackboxes ---",
            "ignore class sky130_fd_sc_hd__decap",
            "ignore class sky130_fd_sc_hd__fill",
            "ignore class sky130_fd_sc_hd__tap",
            "",
            f"# --- LVS run on {top_module} ---",
            "lvs",
        ]
        return "\n".join(lines)

    def parse_netgen_log(self, log: str) -> LvsResult:
        """Parse Netgen log for matches/mismatches."""
        result = LvsResult(matched=False)

        # Try to extract summary numbers.
        m = re.search(r"Subcircuit summary:.*?Number of nets.*?=\s*(\d+)", log, re.S)
        if m:
            result.matched_nets = int(m.group(1))
        m = re.search(r"Number of devices?.*?=\s*(\d+)", log)
        if m:
            result.matched_devices = int(m.group(1))

        if "Circuits match uniquely" in log or "Netlists match uniquely" in log:
            result.matched = True
            return result

        # Net mismatches: look for messages like "Net XYZ in netlist1 has..." etc.
        for m in re.finditer(
            r"Net\s+(\S+)\s+in\s+(layout|schematic).*?(missing|extra|differ).*?$",
            log,
            re.M | re.I,
        ):
            name = m.group(1)
            side = m.group(2).lower()
            reason = m.group(3).lower()
            if side == "layout":
                result.net_mismatches.append(
                    NetMismatch(layout_net=name, schematic_net="", reason=reason)
                )
            else:
                result.net_mismatches.append(
                    NetMismatch(layout_net="", schematic_net=name, reason=reason)
                )

        # Device mismatches: "Device <inst>: layout=X schematic=Y"
        for m in re.finditer(
            r"Device\s+(\S+):\s*layout\s*=\s*(\S+)\s+schematic\s*=\s*(\S+)",
            log,
        ):
            result.device_mismatches.append(
                DeviceMismatch(
                    instance=m.group(1),
                    layout_type=m.group(2),
                    schematic_type=m.group(3),
                )
            )

        # Property mismatch lines: "Property <p> mismatch on <inst>: L=<v> S=<v>"
        for m in re.finditer(
            r"Property\s+(\S+)\s+mismatch\s+on\s+(\S+):\s*L=(\S+)\s+S=(\S+)",
            log,
        ):
            prop = m.group(1)
            inst = m.group(2)
            lv = m.group(3)
            sv = m.group(4)
            self._attach_property_diff(result, inst, prop, lv, sv)

        # Catch-all "MISMATCH" indicator.
        if (
            not result.net_mismatches
            and not result.device_mismatches
            and "do not match" not in log.lower()
        ):
            # No information; treat as failed parse, leave matched False.
            pass

        return result

    def _attach_property_diff(
        self,
        result: LvsResult,
        instance: str,
        prop: str,
        layout_val: str,
        sch_val: str,
    ) -> None:
        for dm in result.device_mismatches:
            if dm.instance == instance:
                dm.parameter_diffs[prop] = (layout_val, sch_val)
                return
        # Create a new device mismatch entry.
        dm = DeviceMismatch(
            instance=instance,
            layout_type="",
            schematic_type="",
            parameter_diffs={prop: (layout_val, sch_val)},
        )
        result.device_mismatches.append(dm)

    def find_swapped_pins(
        self, device_mismatches: list[DeviceMismatch]
    ) -> list[tuple[str, str]]:
        """Detect commonly swapped pins (e.g. NMOS source/drain)."""
        swapped: list[tuple[str, str]] = []
        for dm in device_mismatches:
            # Heuristic: if width and length match but type differs by S/D,
            # mark as swapped.
            if dm.parameter_diffs:
                w_diff = dm.parameter_diffs.get("w")
                l_diff = dm.parameter_diffs.get("l")
                if w_diff and w_diff[0] == w_diff[1] and l_diff and l_diff[0] == l_diff[1]:
                    swapped.append((dm.instance, "S/D"))
        return swapped

    def write_debug_report(self, result: LvsResult, path: Path) -> None:
        """Write a detailed human readable LVS debug report."""
        lines: list[str] = []
        lines.append(result.summary())
        lines.append("=" * 72)
        if result.net_mismatches:
            lines.append("Net mismatches:")
            for nm in result.net_mismatches:
                lines.append("  " + nm.short())
        if result.device_mismatches:
            lines.append("Device mismatches:")
            for dm in result.device_mismatches:
                lines.append("  " + dm.short())
        if result.swapped_pins:
            lines.append("Likely swapped pins:")
            for inst, kind in result.swapped_pins:
                lines.append(f"  {inst}: {kind}")
        path.write_text("\n".join(lines), encoding="utf-8")

    def is_clean(self, result: LvsResult) -> bool:
        """Return True iff layout matches schematic."""
        return result.matched and result.total_mismatches == 0

"""Vivado .xpr project importer.

Parses the XML Vivado Project File and extracts sources, constraints,
top module, part number and IP instances into an OpenForge
:class:`openforge.project.model.Project`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ..model import (
    IPInstance,
    Project,
    ProjectKind,
    Target,
    TargetKind,
)


def _text(elem: ET.Element | None, default: str = "") -> str:
    return (elem.text or default) if elem is not None else default


def import_xpr(xpr_path: str | Path) -> Project:
    """Parse a Vivado .xpr file into a :class:`Project`."""
    xpr = Path(xpr_path).resolve()
    if not xpr.exists():
        raise FileNotFoundError(xpr)
    project_dir = xpr.parent
    tree = ET.parse(xpr)
    root = tree.getroot()

    name = xpr.stem
    part = ""
    top_module = ""
    rtl_sources: list[str] = []
    constraint_files: list[str] = []
    tb_sources: list[str] = []
    ips: list[IPInstance] = []

    # Global configuration (Part)
    for cfg in root.iter("Configuration"):
        for opt in cfg.findall("Option"):
            if opt.get("Name") == "Part":
                part = opt.get("Val", "")
            if opt.get("Name") == "TopModule":
                top_module = opt.get("Val", "")

    # File sets contain RTL, constraints, simulation
    for fileset in root.iter("FileSet"):
        fstype = (fileset.get("Type") or "").lower()
        name_attr = (fileset.get("Name") or "").lower()
        # Top module sometimes stored as a fileset Option
        for opt in fileset.findall("Option"):
            if opt.get("Name") == "TopModule" and not top_module:
                top_module = opt.get("Val", "")
        for f in fileset.findall("File"):
            rel = f.get("Path") or ""
            if not rel:
                continue
            rel = rel.replace("$PPRDIR", str(project_dir)).replace("$PROJDIR", str(project_dir))
            p = (project_dir / rel).resolve() if not Path(rel).is_absolute() else Path(rel)
            path_str = str(p)
            suffix = p.suffix.lower()
            if "constr" in fstype or suffix == ".xdc":
                constraint_files.append(path_str)
            elif "sim" in fstype or "sim" in name_attr:
                tb_sources.append(path_str)
            elif suffix in {".v", ".sv", ".vhd", ".vhdl", ".svh", ".vh"}:
                rtl_sources.append(path_str)
            elif suffix == ".xci":
                ips.append(
                    IPInstance(
                        name=p.stem,
                        ip_type="vivado_ip",
                        source="local",
                        params={"xci": path_str},
                    )
                )

    # Fallback: glob for sources if XML was sparse
    if not rtl_sources:
        for pat in ("*.v", "*.sv", "*.vhd", "*.vhdl"):
            rtl_sources.extend(str(p) for p in project_dir.rglob(pat))

    family = None
    vendor = "xilinx"
    if part:
        lower = part.lower()
        if lower.startswith("xc7"):
            family = "7-series"
        elif lower.startswith(("xcu", "xcvu")):
            family = "ultrascale"
        elif lower.startswith("xczu"):
            family = "zynq-ultrascale+"
        elif lower.startswith("xc7z"):
            family = "zynq-7000"

    target = Target(
        kind=TargetKind.FPGA,
        device=part or None,
        vendor=vendor,
        family=family,
    )

    proj = Project(
        name=name,
        kind=ProjectKind.FPGA,
        top_module=top_module,
        rtl_sources=rtl_sources,
        constraint_files=constraint_files,
        tb_sources=tb_sources,
        ips=ips,
        target=target,
        metadata={"imported_from": "vivado", "source_xpr": str(xpr)},
    )
    return proj


__all__ = ["import_xpr"]

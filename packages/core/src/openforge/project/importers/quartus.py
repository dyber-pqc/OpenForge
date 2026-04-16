"""Intel Quartus project importer.

Reads a ``.qpf`` (project file) and its companion ``.qsf`` (settings
file) and extracts family, device, top-level entity, Verilog sources
and SDC files.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..model import (
    Project,
    ProjectKind,
    Target,
    TargetKind,
)

_SET_GLOBAL = re.compile(
    r"set_global_assignment\s+-name\s+(\w+)\s+(?:-section_id\s+\S+\s+)?(.+?)\s*$",
    re.M,
)


def _parse_qsf(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for m in _SET_GLOBAL.finditer(text):
        key = m.group(1).upper()
        val = m.group(2).strip().strip('"')
        out.append((key, val))
    return out


def import_quartus_qpf(qpf_path: str | Path) -> Project:
    """Parse a Quartus project file into an OpenForge FPGA project."""
    qpf = Path(qpf_path).resolve()
    if not qpf.exists():
        raise FileNotFoundError(qpf)
    proj_dir = qpf.parent
    name = qpf.stem

    qsf = proj_dir / f"{name}.qsf"
    settings: list[tuple[str, str]] = []
    if qsf.exists():
        settings = _parse_qsf(qsf.read_text(encoding="utf-8", errors="replace"))

    family = ""
    device = ""
    top_module = ""
    rtl_sources: list[str] = []
    constraint_files: list[str] = []
    tb_sources: list[str] = []

    for key, val in settings:
        if key == "FAMILY":
            family = val
        elif key == "DEVICE":
            device = val
        elif key == "TOP_LEVEL_ENTITY":
            top_module = val
        elif key in ("VERILOG_FILE", "SYSTEMVERILOG_FILE", "VHDL_FILE"):
            p = (proj_dir / val).resolve() if not Path(val).is_absolute() else Path(val)
            rtl_sources.append(str(p))
        elif key == "SDC_FILE":
            p = (proj_dir / val).resolve() if not Path(val).is_absolute() else Path(val)
            constraint_files.append(str(p))
        elif key == "EDA_TEST_BENCH_FILE":
            p = (proj_dir / val).resolve() if not Path(val).is_absolute() else Path(val)
            tb_sources.append(str(p))

    target = Target(
        kind=TargetKind.FPGA,
        device=device or None,
        family=family or None,
        vendor="intel",
    )

    return Project(
        name=name,
        kind=ProjectKind.FPGA,
        top_module=top_module or name,
        rtl_sources=rtl_sources,
        constraint_files=constraint_files,
        tb_sources=tb_sources,
        target=target,
        metadata={
            "imported_from": "quartus",
            "source_qpf": str(qpf),
            "source_qsf": str(qsf) if qsf.exists() else None,
        },
    )


__all__ = ["import_quartus_qpf"]

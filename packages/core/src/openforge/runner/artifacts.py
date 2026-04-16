"""Artifact registry and auto-detection for run outputs."""

from __future__ import annotations

import threading
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import RunArtifact


class ArtifactKind(StrEnum):
    """Known kinds of EDA artifacts."""

    NETLIST_V = "netlist_v"
    NETLIST_JSON = "netlist_json"
    DEF = "def"
    LEF = "lef"
    GDS = "gds"
    VCD = "vcd"
    FST = "fst"
    SDF = "sdf"
    SPEF = "spef"
    SDC = "sdc"
    XDC = "xdc"
    LPF = "lpf"
    CST = "cst"
    PCF = "pcf"
    BITSTREAM = "bitstream"
    REPORT = "report"
    LOG = "log"
    GERBER = "gerber"
    DRILL = "drill"
    PICK_PLACE = "pick_place"
    MAG = "mag"
    OTHER = "other"


_EXT_MAP: dict[str, ArtifactKind] = {
    ".v": ArtifactKind.NETLIST_V,
    ".sv": ArtifactKind.NETLIST_V,
    ".json": ArtifactKind.NETLIST_JSON,
    ".def": ArtifactKind.DEF,
    ".lef": ArtifactKind.LEF,
    ".gds": ArtifactKind.GDS,
    ".gds.gz": ArtifactKind.GDS,
    ".gdsii": ArtifactKind.GDS,
    ".vcd": ArtifactKind.VCD,
    ".fst": ArtifactKind.FST,
    ".sdf": ArtifactKind.SDF,
    ".spef": ArtifactKind.SPEF,
    ".sdc": ArtifactKind.SDC,
    ".xdc": ArtifactKind.XDC,
    ".lpf": ArtifactKind.LPF,
    ".cst": ArtifactKind.CST,
    ".pcf": ArtifactKind.PCF,
    ".bin": ArtifactKind.BITSTREAM,
    ".bit": ArtifactKind.BITSTREAM,
    ".asc": ArtifactKind.BITSTREAM,
    ".fs": ArtifactKind.BITSTREAM,
    ".rpt": ArtifactKind.REPORT,
    ".log": ArtifactKind.LOG,
    ".gbr": ArtifactKind.GERBER,
    ".drl": ArtifactKind.DRILL,
    ".pos": ArtifactKind.PICK_PLACE,
    ".csv": ArtifactKind.PICK_PLACE,
    ".mag": ArtifactKind.MAG,
}


def detect_kind(path: str | Path) -> ArtifactKind:
    """Detect an :class:`ArtifactKind` from a file path."""
    name = str(path).lower()
    # multi-extension matches first
    if name.endswith(".gds.gz"):
        return ArtifactKind.GDS
    suffix = Path(name).suffix
    return _EXT_MAP.get(suffix, ArtifactKind.OTHER)


class ArtifactRegistry:
    """In-memory registry of artifacts produced by runs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # run_id -> stage_id -> [RunArtifact]
        self._by_run: dict[str, dict[str, list[RunArtifact]]] = {}

    def register(self, run_id: str, stage_id: str, artifact: RunArtifact) -> None:
        with self._lock:
            self._by_run.setdefault(run_id, {}).setdefault(stage_id, []).append(artifact)

    def list_for_run(self, run_id: str) -> list[RunArtifact]:
        with self._lock:
            out: list[RunArtifact] = []
            for stage_arts in self._by_run.get(run_id, {}).values():
                out.extend(stage_arts)
            return out

    def find(self, run_id: str, kind: ArtifactKind) -> list[Path]:
        return [Path(a.path) for a in self.list_for_run(run_id) if a.kind == kind]

    def latest(self, kind: ArtifactKind) -> Path | None:
        with self._lock:
            best: RunArtifact | None = None
            for run in self._by_run.values():
                for stage_arts in run.values():
                    for a in stage_arts:
                        if a.kind != kind:
                            continue
                        if best is None or a.created_at > best.created_at:
                            best = a
            return Path(best.path) if best else None


__all__ = ["ArtifactKind", "ArtifactRegistry", "detect_kind"]

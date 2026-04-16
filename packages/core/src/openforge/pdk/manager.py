"""PDK Manager - central registry of supported PDKs with install/discover."""
from __future__ import annotations

import contextlib
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass
class PdkCorner:
    name: str
    process: str  # tt/ss/ff
    temperature: float
    voltage: float
    liberty_file: Path


@dataclass
class PdkInfo:
    name: str
    display_name: str
    foundry: str
    process_node_nm: int
    cell_libraries: list[str] = field(default_factory=list)
    corners: dict[str, list[PdkCorner]] = field(default_factory=dict)
    tech_lef: Path | None = None
    merged_lef: Path | None = None
    install_path: Path | None = None
    download_url: str = ""
    installed: bool = False


def _share_pdk_root() -> Path:
    """Locate the repo's share/pdk directory if available."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "share" / "pdk"
        if candidate.exists():
            return candidate
    return Path.cwd() / "share" / "pdk"


class PdkManager:  # noqa: N801 - camelCase alias exposed below
    """Manages installed PDKs and downloads new ones."""

    KNOWN_PDKS: dict[str, PdkInfo] = {
        "sky130": PdkInfo(
            name="sky130",
            display_name="SkyWater 130nm",
            foundry="SkyWater",
            process_node_nm=130,
            cell_libraries=["sky130_fd_sc_hd", "sky130_fd_sc_hs"],
            download_url="https://github.com/google/skywater-pdk",
        ),
        "gf180mcu": PdkInfo(
            name="gf180mcu",
            display_name="GlobalFoundries 180nm MCU",
            foundry="GlobalFoundries",
            process_node_nm=180,
            cell_libraries=["gf180mcu_fd_sc_mcu7t5v0", "gf180mcu_fd_sc_mcu9t5v0"],
            download_url="https://github.com/google/gf180mcu-pdk",
        ),
        "asap7": PdkInfo(
            name="asap7",
            display_name="ASAP7 7nm Academic",
            foundry="ASU",
            process_node_nm=7,
            cell_libraries=["asap7sc7p5t"],
            download_url="https://github.com/The-OpenROAD-Project/asap7",
        ),
        "ihp130": PdkInfo(
            name="ihp130",
            display_name="IHP SG13G2 130nm BiCMOS",
            foundry="IHP",
            process_node_nm=130,
            cell_libraries=["sg13g2_stdcell"],
            download_url="https://github.com/IHP-GmbH/IHP-Open-PDK",
        ),
    }

    def __init__(self, install_root: Path | None = None):
        self.install_root: Path = install_root or (Path.home() / ".openforge" / "pdks")
        self.install_root.mkdir(parents=True, exist_ok=True)
        self._share_root = _share_pdk_root()
        self._active: str | None = None
        self._pdks: dict[str, PdkInfo] = {
            name: PdkInfo(
                name=info.name,
                display_name=info.display_name,
                foundry=info.foundry,
                process_node_nm=info.process_node_nm,
                cell_libraries=list(info.cell_libraries),
                corners={},
                download_url=info.download_url,
            )
            for name, info in self.KNOWN_PDKS.items()
        }
        self.discover_local()

    # ------------------------------------------------------------------
    def list_pdks(self) -> list[PdkInfo]:
        return list(self._pdks.values())

    def is_installed(self, pdk_name: str) -> bool:
        info = self._pdks.get(pdk_name)
        return bool(info and info.installed)

    def get_pdk(self, pdk_name: str) -> PdkInfo | None:
        return self._pdks.get(pdk_name)

    def set_active(self, pdk_name: str) -> None:
        if pdk_name in self._pdks:
            self._active = pdk_name

    def get_active(self) -> PdkInfo | None:
        return self._pdks.get(self._active) if self._active else None

    # ------------------------------------------------------------------
    def discover_local(self) -> dict[str, PdkInfo]:
        """Scan share/pdk and ~/.openforge/pdks for installed PDKs."""
        roots = [self._share_root, self.install_root]
        for pdk_name, info in self._pdks.items():
            for root in roots:
                candidate = root / pdk_name
                if candidate.exists() and candidate.is_dir():
                    info.install_path = candidate
                    info.installed = True
                    self._populate_pdk_paths(info)
                    break
        return self._pdks

    def _populate_pdk_paths(self, info: PdkInfo) -> None:
        if not info.install_path:
            return
        root = info.install_path
        lib_root = root / "lib"
        lef_root = root / "lef"
        tech_root = root / "tech"
        for sub in (tech_root, lef_root, root):
            if sub.exists():
                for f in sub.rglob("*.tlef"):
                    info.tech_lef = f
                    break
                if info.tech_lef:
                    break
        if lef_root.exists():
            for f in lef_root.rglob("*merged*.lef"):
                info.merged_lef = f
                break
            if not info.merged_lef:
                for f in lef_root.rglob("*.lef"):
                    info.merged_lef = f
                    break
        if lib_root.exists():
            info.corners = {}
            for lib_file in lib_root.rglob("*.lib"):
                stem = lib_file.stem
                parts = stem.split("__")
                if len(parts) >= 2:
                    lib_name = parts[0]
                    corner_str = parts[1]
                else:
                    lib_name = stem
                    corner_str = "default"
                process, temp, volt = self._parse_corner_str(corner_str)
                corner = PdkCorner(
                    name=corner_str,
                    process=process,
                    temperature=temp,
                    voltage=volt,
                    liberty_file=lib_file,
                )
                info.corners.setdefault(lib_name, []).append(corner)
                if lib_name not in info.cell_libraries:
                    info.cell_libraries.append(lib_name)

    @staticmethod
    def _parse_corner_str(corner: str) -> tuple[str, float, float]:
        process = "tt"
        temp = 25.0
        volt = 1.8
        parts = corner.split("_")
        for p in parts:
            if p in ("tt", "ss", "ff", "sf", "fs"):
                process = p
            elif p.endswith("C") and p[:-1].lstrip("-").isdigit():
                with contextlib.suppress(ValueError):
                    temp = float(p[:-1])
            elif "v" in p:
                with contextlib.suppress(ValueError):
                    volt = float(p.replace("v", "."))
        return process, temp, volt

    # ------------------------------------------------------------------
    def install(
        self,
        pdk_name: str,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> bool:
        info = self._pdks.get(pdk_name)
        if not info:
            return False
        if info.installed:
            return True
        target = self.install_root / pdk_name
        if progress_callback:
            progress_callback(f"Cloning {info.download_url}", 0.0)
        git = shutil.which("git")
        if not git:
            if progress_callback:
                progress_callback("git not found", 1.0)
            return False
        try:
            subprocess.run(
                [git, "clone", "--depth", "1", info.download_url, str(target)],
                check=True,
            )
        except subprocess.CalledProcessError:
            if progress_callback:
                progress_callback("clone failed", 1.0)
            return False
        info.install_path = target
        info.installed = True
        self._populate_pdk_paths(info)
        if progress_callback:
            progress_callback("done", 1.0)
        return True

    def uninstall(self, pdk_name: str) -> bool:
        info = self._pdks.get(pdk_name)
        if not info or not info.install_path:
            return False
        try:
            if str(info.install_path).startswith(str(self.install_root)):
                shutil.rmtree(info.install_path)
        except OSError:
            return False
        info.installed = False
        info.install_path = None
        info.corners = {}
        info.tech_lef = None
        info.merged_lef = None
        return True

    # ------------------------------------------------------------------
    def get_corners(self, pdk_name: str, lib_name: str) -> list[PdkCorner]:
        info = self._pdks.get(pdk_name)
        if not info:
            return []
        return info.corners.get(lib_name, [])

    def get_default_corner(self, pdk_name: str) -> PdkCorner | None:
        info = self._pdks.get(pdk_name)
        if not info or not info.corners:
            return None
        for lib_corners in info.corners.values():
            for c in lib_corners:
                if c.process == "tt":
                    return c
        for lib_corners in info.corners.values():
            if lib_corners:
                return lib_corners[0]
        return None


# Compatibility alias for code that uses PDKManager (upper-case)
PDKManager = PdkManager

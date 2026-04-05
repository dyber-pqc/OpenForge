"""PDK (Process Design Kit) manager for OpenForge EDA."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class PDKStatus(StrEnum):
    INSTALLED = "installed"
    AVAILABLE = "available"
    LICENSED = "licensed"


@dataclass
class PDKInfo:
    """Metadata for a Process Design Kit."""

    name: str
    display_name: str
    node: str
    metal_layers: int
    features: list[str]
    license: str
    status: PDKStatus = PDKStatus.AVAILABLE
    install_path: Path | None = None
    version: str = ""
    source_url: str = ""

    @property
    def liberty_files(self) -> list[Path]:
        """Return paths to Liberty timing libraries."""
        if not self.install_path:
            return []
        return sorted(self.install_path.rglob("*.lib"))

    @property
    def lef_files(self) -> list[Path]:
        """Return paths to LEF files."""
        if not self.install_path:
            return []
        return sorted(self.install_path.rglob("*.lef"))

    @property
    def tech_file(self) -> Path | None:
        """Return path to technology file (.tech)."""
        if not self.install_path:
            return None
        techs = list(self.install_path.rglob("*.tech"))
        return techs[0] if techs else None


# Registry of known PDKs
KNOWN_PDKS: dict[str, PDKInfo] = {
    "sky130": PDKInfo(
        name="sky130",
        display_name="SkyWater SKY130",
        node="130nm",
        metal_layers=5,
        features=["Digital", "Analog", "IO cells", "SRAM"],
        license="Apache-2.0",
        source_url="https://github.com/google/skywater-pdk",
    ),
    "gf180mcu": PDKInfo(
        name="gf180mcu",
        display_name="GlobalFoundries GF180MCU",
        node="180nm",
        metal_layers=5,
        features=["Digital", "Analog", "High-voltage", "Thick oxide"],
        license="Apache-2.0",
        source_url="https://github.com/google/gf180mcu-pdk",
    ),
    "ihp_sg13g2": PDKInfo(
        name="ihp_sg13g2",
        display_name="IHP SG13G2",
        node="130nm",
        metal_layers=5,
        features=["BiCMOS", "SiGe HBT", "RF"],
        license="Apache-2.0",
        source_url="https://github.com/IHP-GmbH/IHP-Open-PDK",
    ),
    "asap7": PDKInfo(
        name="asap7",
        display_name="ASAP7 Predictive",
        node="7nm",
        metal_layers=9,
        features=["FinFET", "Academic/Predictive"],
        license="BSD-3-Clause",
        source_url="https://github.com/The-OpenROAD-Project/asap7",
    ),
}


class PDKManager:
    """Manages PDK installation, discovery, and configuration."""

    def __init__(self, pdk_root: Path | None = None) -> None:
        self.pdk_root = pdk_root or Path.home() / ".openforge" / "pdks"
        self.pdk_root.mkdir(parents=True, exist_ok=True)
        self._pdks: dict[str, PDKInfo] = dict(KNOWN_PDKS)
        self._scan_installed()

    def _scan_installed(self) -> None:
        """Scan pdk_root for installed PDKs."""
        for pdk_dir in self.pdk_root.iterdir():
            if pdk_dir.is_dir() and pdk_dir.name in self._pdks:
                self._pdks[pdk_dir.name].status = PDKStatus.INSTALLED
                self._pdks[pdk_dir.name].install_path = pdk_dir

                # Read version from metadata if present
                meta_file = pdk_dir / "pdk_info.json"
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text())
                        self._pdks[pdk_dir.name].version = meta.get("version", "")
                    except (json.JSONDecodeError, OSError):
                        pass

    def list_pdks(self) -> list[PDKInfo]:
        """List all known PDKs with their installation status."""
        return list(self._pdks.values())

    def get_pdk(self, name: str) -> PDKInfo | None:
        """Get PDK info by name."""
        return self._pdks.get(name)

    def is_installed(self, name: str) -> bool:
        """Check if a PDK is installed."""
        pdk = self._pdks.get(name)
        return pdk is not None and pdk.status == PDKStatus.INSTALLED

    def get_liberty(self, pdk_name: str, corner: str = "tt") -> Path | None:
        """Get the Liberty file for a specific corner.

        Common corners: tt (typical), ss (slow), ff (fast), sf, fs.
        """
        pdk = self._pdks.get(pdk_name)
        if not pdk or not pdk.install_path:
            return None

        for lib_file in pdk.liberty_files:
            if corner in lib_file.stem.lower():
                return lib_file

        # Fallback to first available
        libs = pdk.liberty_files
        return libs[0] if libs else None

    def get_lef(self, pdk_name: str) -> Path | None:
        """Get the primary LEF file for a PDK."""
        pdk = self._pdks.get(pdk_name)
        if not pdk or not pdk.install_path:
            return None

        lefs = pdk.lef_files
        return lefs[0] if lefs else None

    def install_pdk(self, name: str) -> bool:
        """Install a PDK (downloads from source if open-source).

        Returns True on success.
        """
        pdk = self._pdks.get(name)
        if not pdk:
            return False

        if pdk.status == PDKStatus.INSTALLED:
            return True

        if pdk.license in ("Apache-2.0", "BSD-3-Clause"):
            # Open-source PDK -- clone from git
            install_dir = self.pdk_root / name
            install_dir.mkdir(parents=True, exist_ok=True)

            import subprocess

            result = subprocess.run(
                ["git", "clone", "--depth=1", pdk.source_url, str(install_dir)],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                pdk.status = PDKStatus.INSTALLED
                pdk.install_path = install_dir
                return True

        return False

    def uninstall_pdk(self, name: str) -> bool:
        """Remove an installed PDK."""
        pdk = self._pdks.get(name)
        if not pdk or pdk.status != PDKStatus.INSTALLED or not pdk.install_path:
            return False

        shutil.rmtree(pdk.install_path, ignore_errors=True)
        pdk.status = PDKStatus.AVAILABLE
        pdk.install_path = None
        return True

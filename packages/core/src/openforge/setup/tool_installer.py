"""Tool installer: detect, download, and install open-source EDA tools.

This module knows about the major open-source EDA tools that OpenForge
drives (yosys, nextpnr, openroad, magic, netgen, ngspice, verilator,
icarus verilog, klayout, openFPGALoader, icestorm, prjtrellis). It can
detect what's already on ``PATH``, probe versions, and install missing
tools via the platform's native package manager (apt, winget, brew,
scoop) or by downloading a prebuilt archive from GitHub Releases.

Network failures are non-fatal: if a URL 404s or a package manager is
unavailable, the installer logs and returns ``False`` so the UI can move
on to the next tool.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ProgressCB = Callable[[str, float], None] | None


def _platform_key() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


class Tool(BaseModel):
    """Metadata about a single external EDA tool."""

    name: str
    binary: str
    description: str
    download_urls: dict[str, str] = Field(default_factory=dict)
    archive_kind: str = "zip"  # zip | tar.gz | exe | dmg | deb | apt | none
    install_method: str = "extract"  # extract | run | apt | winget | brew | scoop | wsl
    version_check_args: list[str] = Field(default_factory=lambda: ["--version"])
    install_size_mb: int = 0
    apt_package: str | None = None
    brew_package: str | None = None
    scoop_package: str | None = None
    winget_package: str | None = None


# Real upstream URLs / package names. Every URL is considered best-effort -
# if any of them 404 the installer will log and fall through.
KNOWN_TOOLS: dict[str, Tool] = {
    "yosys": Tool(
        name="Yosys",
        binary="yosys",
        description="RTL synthesis framework from YosysHQ",
        download_urls={
            "linux": "https://github.com/YosysHQ/oss-cad-suite-build/releases/latest/download/oss-cad-suite-linux-x64.tgz",
            "macos": "https://github.com/YosysHQ/oss-cad-suite-build/releases/latest/download/oss-cad-suite-darwin-x64.tgz",
            "windows": "https://github.com/YosysHQ/oss-cad-suite-build/releases/latest/download/oss-cad-suite-windows-x64.exe",
        },
        archive_kind="tar.gz",
        install_method="extract",
        install_size_mb=1200,
        apt_package="yosys",
        brew_package="yosys",
        scoop_package="yosys",
    ),
    "nextpnr-ice40": Tool(
        name="nextpnr-ice40",
        binary="nextpnr-ice40",
        description="iCE40 FPGA place and route (part of oss-cad-suite)",
        download_urls={
            "linux": "https://github.com/YosysHQ/oss-cad-suite-build/releases/latest/download/oss-cad-suite-linux-x64.tgz",
        },
        archive_kind="tar.gz",
        install_method="extract",
        install_size_mb=1200,
        apt_package="nextpnr-ice40",
        brew_package="nextpnr",
    ),
    "nextpnr-ecp5": Tool(
        name="nextpnr-ecp5",
        binary="nextpnr-ecp5",
        description="ECP5 FPGA place and route",
        install_method="apt",
        apt_package="nextpnr-ecp5",
        brew_package="nextpnr",
    ),
    "openroad": Tool(
        name="OpenROAD",
        binary="openroad",
        description="ASIC place and route, CTS, static timing",
        download_urls={
            "linux": "https://github.com/The-OpenROAD-Project/OpenROAD/releases/latest/download/openroad-ubuntu-24.04.tar.gz",
            "macos": "https://github.com/The-OpenROAD-Project/OpenROAD/releases/latest/download/openroad-macos.tar.gz",
        },
        archive_kind="tar.gz",
        install_method="extract",
        install_size_mb=650,
        brew_package="openroad",
    ),
    "magic": Tool(
        name="Magic VLSI",
        binary="magic",
        description="Magic layout editor (DRC, LVS helper)",
        install_method="apt",
        apt_package="magic",
        brew_package="magic",
    ),
    "netgen": Tool(
        name="Netgen",
        binary="netgen",
        description="LVS netlist comparison",
        install_method="apt",
        apt_package="netgen-lvs",
        brew_package="netgen",
    ),
    "ngspice": Tool(
        name="ngspice",
        binary="ngspice",
        description="Mixed-signal SPICE simulator",
        install_method="apt",
        apt_package="ngspice",
        brew_package="ngspice",
        winget_package="ngspice.ngspice",
    ),
    "verilator": Tool(
        name="Verilator",
        binary="verilator",
        description="Fast SystemVerilog simulator / linter",
        install_method="apt",
        apt_package="verilator",
        brew_package="verilator",
        scoop_package="verilator",
    ),
    "iverilog": Tool(
        name="Icarus Verilog",
        binary="iverilog",
        description="Reference Verilog simulator",
        install_method="apt",
        apt_package="iverilog",
        brew_package="icarus-verilog",
        scoop_package="iverilog",
    ),
    "klayout": Tool(
        name="KLayout",
        binary="klayout",
        description="GDSII / OASIS layout viewer",
        download_urls={
            "windows": "https://www.klayout.org/downloads/Windows-64/klayout-0.29.0-win64-install.exe",
            "macos": "https://www.klayout.org/downloads/MacOS/klayout-0.29.0-macOS-Sonoma-1-qt5.dmg",
        },
        archive_kind="exe",
        install_method="run",
        install_size_mb=200,
        apt_package="klayout",
        brew_package="klayout",
    ),
    "openfpgaloader": Tool(
        name="openFPGALoader",
        binary="openFPGALoader",
        description="Universal FPGA bitstream loader",
        install_method="apt",
        apt_package="openfpgaloader",
        brew_package="openfpgaloader",
    ),
    "icestorm": Tool(
        name="icestorm",
        binary="icepack",
        description="iCE40 bitstream tools (icepack/icetime/iceprog)",
        install_method="apt",
        apt_package="fpga-icestorm",
        brew_package="icestorm",
    ),
    "prjtrellis": Tool(
        name="prjtrellis",
        binary="ecppack",
        description="ECP5 bitstream tools",
        install_method="apt",
        apt_package="prjtrellis",
        brew_package="prjtrellis",
    ),
}


class ToolInstaller:
    """Detects installed tools and drives installation of missing ones."""

    def __init__(self, install_root: Path | None = None) -> None:
        self.install_root = install_root or (Path.home() / ".openforge" / "tools")
        self.install_root.mkdir(parents=True, exist_ok=True)
        self._user_paths = self._load_user_paths()

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def detect_all(self) -> dict[str, str | None]:
        return {name: self.detect(name) for name in KNOWN_TOOLS}

    def detect(self, name: str) -> str | None:
        tool = KNOWN_TOOLS.get(name)
        if tool is None:
            return None
        # User override
        if name in self._user_paths:
            p = Path(self._user_paths[name])
            if p.exists():
                return str(p)
        # PATH search
        found = shutil.which(tool.binary)
        if found:
            return found
        # Bundled install dir
        candidate = self.install_root / name / "bin" / tool.binary
        if candidate.exists():
            return str(candidate)
        if sys.platform.startswith("win"):
            candidate_exe = candidate.with_suffix(".exe")
            if candidate_exe.exists():
                return str(candidate_exe)
        return None

    def get_version(self, name: str) -> str | None:
        path = self.detect(name)
        if not path:
            return None
        tool = KNOWN_TOOLS[name]
        try:
            res = subprocess.run(
                [path, *tool.version_check_args],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            blob = (res.stdout or "") + (res.stderr or "")
            for line in blob.splitlines():
                line = line.strip()
                if line:
                    return line[:120]
        except (OSError, subprocess.TimeoutExpired) as exc:  # noqa: BLE001
            logger.debug("version probe failed for %s: %s", name, exc)
        return None

    # ------------------------------------------------------------------
    # User path overrides
    # ------------------------------------------------------------------
    @staticmethod
    def _paths_file() -> Path:
        return Path.home() / ".openforge" / "tool_paths.json"

    def _load_user_paths(self) -> dict[str, str]:
        import json
        f = self._paths_file()
        if not f.exists():
            return {}
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def set_user_path(self, name: str, path: str) -> None:
        import json
        self._user_paths[name] = path
        f = self._paths_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(self._user_paths, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Installation
    # ------------------------------------------------------------------
    def install(
        self,
        name: str,
        target_dir: Path | None = None,
        progress: ProgressCB = None,
    ) -> bool:
        tool = KNOWN_TOOLS.get(name)
        if tool is None:
            logger.error("unknown tool: %s", name)
            return False

        plat = _platform_key()
        logger.info("installing %s on %s", name, plat)
        if progress:
            progress(f"Installing {tool.name}...", 0.05)

        # Prefer native package managers when possible.
        try:
            if plat == "linux" and tool.apt_package and shutil.which("apt-get"):
                return self.install_via_apt([tool.apt_package])
            if plat == "macos" and tool.brew_package and shutil.which("brew"):
                return self.install_via_brew([tool.brew_package])
            if plat == "windows":
                if tool.winget_package and shutil.which("winget"):
                    return self.install_via_winget([tool.winget_package])
                if tool.scoop_package and shutil.which("scoop"):
                    return self.install_via_scoop([tool.scoop_package])
        except Exception as exc:  # noqa: BLE001
            logger.warning("package manager install failed for %s: %s", name, exc)

        # Fall back to downloading the platform archive.
        url = tool.download_urls.get(plat)
        if not url:
            logger.warning("no download URL for %s on %s", name, plat)
            return False

        dest = (target_dir or self.install_root) / name
        dest.mkdir(parents=True, exist_ok=True)
        archive = dest / Path(url).name
        try:
            self._download(url, archive, progress)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
            logger.warning("download failed for %s: %s", name, exc)
            return False

        try:
            if tool.archive_kind in {"tar.gz", "tgz"}:
                with tarfile.open(archive, "r:gz") as tf:
                    tf.extractall(dest)  # noqa: S202
            elif tool.archive_kind == "zip":
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(dest)
            elif tool.archive_kind in {"exe", "run", "dmg", "deb"}:
                logger.info("downloaded %s installer at %s (manual run)", name, archive)
            if progress:
                progress(f"{tool.name} installed", 1.0)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("extract failed for %s: %s", name, exc)
            return False

    # ------------------------------------------------------------------
    # Package-manager helpers
    # ------------------------------------------------------------------
    def install_via_apt(self, packages: list[str]) -> bool:
        if not shutil.which("apt-get"):
            return False
        sudo = ["sudo"] if os.geteuid() != 0 else []  # type: ignore[attr-defined]
        cmd = [*sudo, "apt-get", "install", "-y", *packages]
        logger.info("running: %s", " ".join(cmd))
        return subprocess.call(cmd) == 0

    def install_via_winget(self, packages: list[str]) -> bool:
        if not shutil.which("winget"):
            return False
        ok = True
        for pkg in packages:
            rc = subprocess.call(["winget", "install", "--id", pkg, "-e", "--silent"])
            ok = ok and rc == 0
        return ok

    def install_via_brew(self, packages: list[str]) -> bool:
        if not shutil.which("brew"):
            return False
        rc = subprocess.call(["brew", "install", *packages])
        return rc == 0

    def install_via_scoop(self, packages: list[str]) -> bool:
        if not shutil.which("scoop"):
            return False
        ok = True
        for pkg in packages:
            rc = subprocess.call(["scoop", "install", pkg])
            ok = ok and rc == 0
        return ok

    def install_via_wsl(self, packages: list[str]) -> bool:
        if not shutil.which("wsl"):
            return False
        cmd = ["wsl", "-e", "bash", "-c", f"sudo apt-get update && sudo apt-get install -y {' '.join(packages)}"]
        return subprocess.call(cmd) == 0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _download(url: str, dest: Path, progress: ProgressCB) -> None:
        logger.info("downloading %s -> %s", url, dest)

        def _hook(block_num: int, block_size: int, total_size: int) -> None:
            if progress and total_size > 0:
                downloaded = block_num * block_size
                frac = min(0.95, max(0.05, downloaded / total_size))
                progress(f"Downloading {dest.name}", frac)

        urllib.request.urlretrieve(url, dest, reporthook=_hook)  # noqa: S310

    @staticmethod
    def system_info() -> dict[str, str]:
        return {
            "platform": _platform_key(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        }

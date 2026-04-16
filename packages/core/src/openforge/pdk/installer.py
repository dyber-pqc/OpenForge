"""PDK installer backed by ``volare`` (sky130/gf180) and git (asap7/ihp).

Provides a uniform ``PdkInstaller`` API for downloading, verifying and
removing open-source PDKs used by OpenForge's ASIC flow.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

ProgressCallback = Callable[[str, float], None]


class PdkInfo(BaseModel):
    name: str
    version: str
    foundry: str
    vendor: str
    install_path: Path | None = None
    sources_url: str
    license: str
    supported_libs: list[str] = Field(default_factory=list)
    node_nm: int = 0
    installer: str = "volare"  # "volare" | "git"
    git_ref: str | None = None


class PdkInstaller:
    """Downloads and manages local installations of open PDKs."""

    KNOWN_PDKS: dict[str, PdkInfo] = {
        "sky130A": PdkInfo(
            name="sky130A",
            version="2024.05.01",
            foundry="SkyWater",
            vendor="Google / Efabless",
            sources_url="https://github.com/google/skywater-pdk",
            license="Apache-2.0",
            supported_libs=[
                "sky130_fd_sc_hd",
                "sky130_fd_sc_hs",
                "sky130_fd_sc_ms",
                "sky130_fd_sc_ls",
                "sky130_fd_sc_hdll",
                "sky130_fd_sc_lp",
                "sky130_fd_sc_hvl",
                "sky130_fd_io",
                "sky130_fd_pr",
            ],
            node_nm=130,
            installer="volare",
        ),
        "sky130B": PdkInfo(
            name="sky130B",
            version="2024.05.01",
            foundry="SkyWater",
            vendor="Google / Efabless",
            sources_url="https://github.com/google/skywater-pdk",
            license="Apache-2.0",
            supported_libs=[
                "sky130_fd_sc_hd",
                "sky130_fd_sc_hs",
                "sky130_fd_sc_ms",
                "sky130_fd_sc_ls",
                "sky130_fd_sc_hdll",
                "sky130_fd_sc_lp",
                "sky130_fd_sc_hvl",
                "sky130_fd_io",
                "sky130_fd_pr",
            ],
            node_nm=130,
            installer="volare",
        ),
        "gf180mcuC": PdkInfo(
            name="gf180mcuC",
            version="0.0.1",
            foundry="GlobalFoundries",
            vendor="Google / Efabless",
            sources_url="https://github.com/google/gf180mcu-pdk",
            license="Apache-2.0",
            supported_libs=[
                "gf180mcu_fd_sc_mcu7t5v0",
                "gf180mcu_fd_sc_mcu9t5v0",
                "gf180mcu_fd_io",
                "gf180mcu_fd_pr",
            ],
            node_nm=180,
            installer="volare",
        ),
        "asap7": PdkInfo(
            name="asap7",
            version="main",
            foundry="ASU",
            vendor="Arizona State University",
            sources_url="https://github.com/The-OpenROAD-Project/asap7.git",
            license="BSD-3-Clause",
            supported_libs=[
                "asap7sc7p5t_AO_RVT",
                "asap7sc7p5t_INVBUF_RVT",
                "asap7sc7p5t_OA_RVT",
                "asap7sc7p5t_SEQ_RVT",
                "asap7sc7p5t_SIMPLE_RVT",
            ],
            node_nm=7,
            installer="git",
            git_ref="master",
        ),
        "ihp_sg13g2": PdkInfo(
            name="ihp_sg13g2",
            version="main",
            foundry="IHP",
            vendor="IHP Microelectronics",
            sources_url="https://github.com/IHP-GmbH/IHP-Open-PDK.git",
            license="Apache-2.0",
            supported_libs=["sg13g2_stdcell", "sg13g2_io", "sg13g2_pr"],
            node_nm=130,
            installer="git",
            git_ref="main",
        ),
    }

    def __init__(self, install_root: Path | None = None) -> None:
        self.install_root = Path(
            install_root or os.environ.get("PDK_ROOT") or Path.home() / ".volare"
        )

    # ------------------------------------------------------------------
    def list_known(self) -> list[PdkInfo]:
        return list(self.KNOWN_PDKS.values())

    def list_installed(self) -> list[PdkInfo]:
        installed: list[PdkInfo] = []
        for info in self.KNOWN_PDKS.values():
            path = self._resolved_path(info)
            if path.exists():
                enriched = info.model_copy(update={"install_path": path})
                installed.append(enriched)
        return installed

    def _resolved_path(self, info: PdkInfo) -> Path:
        if info.installer == "volare":
            # volare lays out PDK_ROOT/sky130/versions/<ver>/<pdk>/...
            base = self.install_root / info.name.rstrip("AB").lower()
            candidate = base / "versions" / info.version / info.name
            if candidate.exists():
                return candidate
            # Fallback to PDK_ROOT/<name>
            return self.install_root / info.name
        else:
            return self.install_root / info.name

    # ------------------------------------------------------------------
    def install(
        self,
        pdk_name: str,
        install_dir: Path | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        info = self.KNOWN_PDKS.get(pdk_name)
        if info is None:
            raise ValueError(f"Unknown PDK: {pdk_name}")

        root = Path(install_dir) if install_dir else self.install_root
        root.mkdir(parents=True, exist_ok=True)

        def emit(msg: str, frac: float) -> None:
            if progress_callback:
                with contextlib.suppress(Exception):
                    progress_callback(msg, frac)

        emit(f"Preparing to install {pdk_name}...", 0.0)

        if info.installer == "volare":
            return self._install_volare(info, root, emit)
        return self._install_git(info, root, emit)

    def _install_volare(
        self, info: PdkInfo, root: Path, emit: Callable[[str, float], None]
    ) -> Path:
        volare = shutil.which("volare")
        if volare is None:
            emit("volare not found - install via `pip install volare`", 1.0)
            raise RuntimeError("volare is not installed. Run: pip install volare")

        # Volare invocation:  volare enable --pdk sky130 <VERSION>
        pdk_family = "sky130" if info.name.startswith("sky130") else "gf180mcu"
        cmd = [
            volare,
            "enable",
            "--pdk",
            pdk_family,
            "--pdk-root",
            str(root),
            info.version,
        ]
        emit(f"Running {' '.join(cmd)}", 0.1)
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Failed to launch volare: {exc}") from exc

        assert proc.stdout is not None
        step = 0.1
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                step = min(step + 0.01, 0.95)
                emit(line, step)
        code = proc.wait()
        if code != 0:
            emit(f"volare exited with code {code}", 1.0)
            raise RuntimeError(f"volare install failed (exit {code})")

        path = self._resolved_path(info)
        emit(f"Installed {info.name} at {path}", 1.0)
        return path

    def _install_git(self, info: PdkInfo, root: Path, emit: Callable[[str, float], None]) -> Path:
        git = shutil.which("git")
        if git is None:
            raise RuntimeError("git not found on PATH")
        target = root / info.name
        if target.exists():
            emit(f"{target} already exists; pulling", 0.2)
            cmd = [git, "-C", str(target), "pull", "--ff-only"]
        else:
            emit(f"Cloning {info.sources_url}", 0.1)
            cmd = [git, "clone", "--depth", "1"]
            if info.git_ref:
                cmd += ["--branch", info.git_ref]
            cmd += [info.sources_url, str(target)]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Failed to launch git: {exc}") from exc

        assert proc.stdout is not None
        step = 0.1
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                step = min(step + 0.02, 0.95)
                emit(line, step)
        code = proc.wait()
        if code != 0:
            raise RuntimeError(f"git clone/pull failed (exit {code})")
        emit(f"Installed {info.name} at {target}", 1.0)
        return target

    # ------------------------------------------------------------------
    def uninstall(self, pdk_name: str) -> bool:
        info = self.KNOWN_PDKS.get(pdk_name)
        if info is None:
            return False
        path = self._resolved_path(info)
        if not path.exists():
            return False
        try:
            shutil.rmtree(path)
            return True
        except OSError:
            return False

    def verify(self, pdk_name: str) -> list[str]:
        """Return a list of missing well-known files, empty if OK."""
        info = self.KNOWN_PDKS.get(pdk_name)
        if info is None:
            return [f"unknown pdk: {pdk_name}"]
        path = self._resolved_path(info)
        if not path.exists():
            return [f"install path does not exist: {path}"]

        missing: list[str] = []
        if info.name.startswith("sky130") or info.name.startswith("gf180"):
            expected_subdirs = ["libs.ref", "libs.tech"]
        elif info.name == "asap7":
            expected_subdirs = ["asap7PDK_r1p7", "asap7sc7p5t_28"]
        else:
            expected_subdirs = []

        for sub in expected_subdirs:
            if not any(path.rglob(sub)):
                missing.append(f"missing subdir: {sub}")
        return missing

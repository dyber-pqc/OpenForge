"""OpenLane2 wrapper.

Wraps the OpenLane2 Python CLI (``openlane``) for use from OpenForge.
Supports both the new Python-based OpenLane2 (``openlane``) and legacy
``openlane2`` entry points. Config is serialised to JSON or YAML matching
the OpenLane2 variable schema.

Reference: https://openlane2.readthedocs.io
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field


class ArtifactKind(str, Enum):
    NETLIST = "netlist"
    DEF = "def"
    GDS = "gds"
    LEF = "lef"
    SDF = "sdf"
    SPEF = "spef"
    SDC = "sdc"
    REPORT = "report"
    METRICS = "metrics"
    LOG = "log"


class OpenLane2Stage(str, Enum):
    SYNTHESIS = "Yosys.Synthesis"
    FLOORPLAN = "OpenROAD.Floorplan"
    IO_PLACEMENT = "OpenROAD.IOPlacement"
    GLOBAL_PLACEMENT = "OpenROAD.GlobalPlacement"
    DETAILED_PLACEMENT = "OpenROAD.DetailedPlacement"
    CTS = "OpenROAD.CTS"
    GLOBAL_ROUTING = "OpenROAD.GlobalRouting"
    DETAILED_ROUTING = "OpenROAD.DetailedRouting"
    FILL_INSERTION = "OpenROAD.FillInsertion"
    RCX = "OpenROAD.RCX"
    STA = "OpenROAD.STAPostPNR"
    GDS_STREAMOUT = "Magic.StreamOut"
    DRC = "Magic.DRC"
    LVS = "Netgen.LVS"
    ANTENNA = "OpenROAD.CheckAntennas"
    MAGIC_DRC = "Magic.DRC"
    KLAYOUT_DRC = "KLayout.DRC"


class OpenLane2Config(BaseModel):
    """OpenLane2 design configuration.

    Matches the variable schema used by OpenLane2 config.json / config.yaml.
    """

    model_config = ConfigDict(extra="allow")

    DESIGN_NAME: str
    VERILOG_FILES: list[str]
    CLOCK_PORT: str
    CLOCK_PERIOD: float
    DIE_AREA: Optional[tuple[float, float, float, float]] = None
    FP_CORE_UTIL: float = 50.0
    PL_TARGET_DENSITY: float = 0.55
    SYNTH_STRATEGY: str = "AREA 0"
    PDK: str = "sky130A"
    STD_CELL_LIBRARY: str = "sky130_fd_sc_hd"
    extra: dict[str, Any] = Field(default_factory=dict)

    def _flatten(self) -> dict[str, Any]:
        data = self.model_dump(exclude={"extra"}, exclude_none=True)
        if self.DIE_AREA is not None:
            x1, y1, x2, y2 = self.DIE_AREA
            data["DIE_AREA"] = f"{x1} {y1} {x2} {y2}"
        data.update(self.extra or {})
        return data

    def to_json(self) -> str:
        return json.dumps(self._flatten(), indent=2)

    def to_yaml(self) -> str:
        try:
            import yaml  # type: ignore
            return yaml.safe_dump(self._flatten(), sort_keys=False)
        except Exception:
            # Minimal YAML-ish fallback
            lines = []
            for k, v in self._flatten().items():
                if isinstance(v, list):
                    lines.append(f"{k}:")
                    for item in v:
                        lines.append(f"  - {item}")
                else:
                    lines.append(f"{k}: {v}")
            return "\n".join(lines) + "\n"


class OpenLane2Runner:
    """Runs OpenLane2 flows via the ``openlane`` Python CLI."""

    def __init__(
        self,
        config: OpenLane2Config,
        design_dir: Path,
        openlane_dir: Optional[Path] = None,
    ) -> None:
        self.config = config
        self.design_dir = Path(design_dir)
        self.openlane_dir = Path(openlane_dir) if openlane_dir else None
        self._cli: Optional[Path] = None

    # ------------------------------------------------------------------
    def detect_openlane(self) -> Optional[Path]:
        """Locate an OpenLane2 CLI executable."""
        if self._cli is not None:
            return self._cli
        for name in ("openlane", "openlane2"):
            found = shutil.which(name)
            if found:
                self._cli = Path(found)
                return self._cli
        # Check OPENLANE_ROOT or OPENLANE2_ROOT
        for env_key in ("OPENLANE2_ROOT", "OPENLANE_ROOT"):
            root = os.environ.get(env_key)
            if root:
                for name in ("openlane", "openlane2"):
                    p = Path(root) / "bin" / name
                    if p.exists():
                        self._cli = p
                        return self._cli
        return None

    def version(self) -> Optional[str]:
        cli = self.detect_openlane()
        if cli is None:
            return None
        try:
            out = subprocess.run(
                [str(cli), "--version"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            match = re.search(r"(\d+\.\d+(?:\.\d+)?)", out.stdout + out.stderr)
            if match:
                return match.group(1)
            return (out.stdout or out.stderr).strip().splitlines()[0] if out.stdout or out.stderr else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    def list_steps(self) -> list[str]:
        """Return canonical step IDs, falling back to ``OpenLane2Stage`` values."""
        cli = self.detect_openlane()
        if cli is not None:
            try:
                out = subprocess.run(
                    [str(cli), "--list-steps"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
                if lines:
                    return lines
            except Exception:
                pass
        return [s.value for s in OpenLane2Stage]

    # ------------------------------------------------------------------
    def _write_config(self, run_dir: Path) -> Path:
        run_dir.mkdir(parents=True, exist_ok=True)
        cfg_path = run_dir / "config.json"
        cfg_path.write_text(self.config.to_json())
        return cfg_path

    def run_step(
        self,
        step: OpenLane2Stage,
        run_dir: Path,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> dict[str, Any]:
        """Run a single OpenLane2 step via ``--from/--to``."""
        cli = self.detect_openlane()
        if cli is None:
            return {"ok": False, "error": "OpenLane2 CLI not found on PATH"}

        cfg = self._write_config(run_dir)
        tag = f"step_{step.name.lower()}"
        cmd = [
            str(cli),
            "--run-tag", tag,
            "--from", step.value,
            "--to", step.value,
            str(cfg),
        ]
        return self._spawn(cmd, run_dir, log_callback)

    def run_flow(
        self,
        steps: Optional[list[OpenLane2Stage]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        run_tag: str = "openforge",
    ) -> dict[str, Any]:
        """Run a full (or sub-)flow."""
        cli = self.detect_openlane()
        if cli is None:
            return {"ok": False, "error": "OpenLane2 CLI not found on PATH"}

        run_dir = self.design_dir / "runs"
        cfg = self._write_config(run_dir)
        cmd = [str(cli), "--run-tag", run_tag]
        if steps:
            cmd += ["--from", steps[0].value, "--to", steps[-1].value]
        cmd.append(str(cfg))
        return self._spawn(cmd, run_dir, log_callback)

    def _spawn(
        self,
        cmd: list[str],
        cwd: Path,
        log_callback: Optional[Callable[[str], None]],
    ) -> dict[str, Any]:
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            return {"ok": False, "error": f"Failed to launch openlane: {exc}"}

        assert proc.stdout is not None
        lines: list[str] = []
        for line in proc.stdout:
            lines.append(line.rstrip("\n"))
            if log_callback is not None:
                try:
                    log_callback(line.rstrip("\n"))
                except Exception:
                    pass
        code = proc.wait()
        return {
            "ok": code == 0,
            "returncode": code,
            "cmd": cmd,
            "log": "\n".join(lines),
        }

    # ------------------------------------------------------------------
    def latest_run_dir(self) -> Optional[Path]:
        runs = self.design_dir / "runs"
        if not runs.exists():
            return None
        candidates = [p for p in runs.iterdir() if p.is_dir()]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

    def collect_artifacts(self, run_dir: Path) -> dict[ArtifactKind, Path]:
        """Walk ``run_dir`` and map common OpenLane2 outputs by kind."""
        out: dict[ArtifactKind, Path] = {}
        if not run_dir.exists():
            return out
        patterns = {
            ArtifactKind.NETLIST: ("*.nl.v", "*.netlist.v", "*.synthesis.v"),
            ArtifactKind.DEF: ("*.def",),
            ArtifactKind.GDS: ("*.gds", "*.gds.gz"),
            ArtifactKind.LEF: ("*.lef",),
            ArtifactKind.SDF: ("*.sdf",),
            ArtifactKind.SPEF: ("*.spef",),
            ArtifactKind.SDC: ("*.sdc",),
            ArtifactKind.METRICS: ("metrics.json", "*metrics*.json"),
            ArtifactKind.LOG: ("*.log",),
            ArtifactKind.REPORT: ("*.rpt", "*.report"),
        }
        for kind, globs in patterns.items():
            for g in globs:
                matches = sorted(run_dir.rglob(g))
                if matches:
                    out[kind] = matches[-1]
                    break
        return out

    def parse_metrics(self, run_dir: Path) -> dict[str, Any]:
        """Load per-step metrics.json files written by OpenLane2."""
        metrics: dict[str, Any] = {}
        if not run_dir.exists():
            return metrics
        for path in run_dir.rglob("metrics.json"):
            try:
                data = json.loads(path.read_text())
            except Exception:
                continue
            step_name = path.parent.name
            metrics[step_name] = data
        # Also top-level final metrics
        final = run_dir / "final" / "metrics.json"
        if final.exists():
            try:
                metrics["final"] = json.loads(final.read_text())
            except Exception:
                pass
        return metrics

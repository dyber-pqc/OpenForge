"""OpenLane <-> OpenForge interoperability adapter.

This module lets users bring an existing OpenLane (1.x or 2.x) project into
OpenForge without rewriting their ``config.json``. It also walks the reverse
direction: copying OpenForge build outputs back into the OpenLane
``runs/<tag>/`` layout so downstream OpenLane scripts keep working.

Reference: https://openlane.readthedocs.io/en/latest/usage/configs.html
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from openforge.config.schema import (
    DesignConfig,
    OpenForgeConfig,
    ProjectConfig,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OpenLane configuration model
# ---------------------------------------------------------------------------


_PDK_MAP: dict[str, str] = {
    "sky130A": "sky130A",
    "sky130B": "sky130B",
    "gf180mcuC": "gf180mcuC",
    "gf180mcuD": "gf180mcuD",
    "asap7": "asap7",
}


class OpenLaneConfig(BaseModel):
    """Pydantic model for an OpenLane ``config.json``.

    Captures the most-used variables from the OpenLane variable schema with
    sensible defaults. Unknown keys are preserved (``extra="allow"``) so a
    round-trip does not drop user customisations.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # Identity / sources
    DESIGN_NAME: str
    VERILOG_FILES: list[str] = Field(default_factory=list)
    VERILOG_INCLUDE_DIRS: list[str] = Field(default_factory=list)
    EXTRA_LEFS: list[str] = Field(default_factory=list)
    EXTRA_GDS_FILES: list[str] = Field(default_factory=list)

    # Clocking
    CLOCK_PORT: str | None = None
    CLOCK_NET: str | None = None
    CLOCK_PERIOD: float | None = None

    # Floorplanning
    DIE_AREA: str | None = None
    FP_CORE_UTIL: float = 50.0
    FP_ASPECT_RATIO: float = 1.0
    FP_PDN_VPITCH: float | None = None
    FP_PDN_HPITCH: float | None = None
    PL_TARGET_DENSITY: float = 0.55

    # Tech
    PDK: str = "sky130A"
    STD_CELL_LIBRARY: str = "sky130_fd_sc_hd"

    # Synthesis
    SYNTH_STRATEGY: str = "AREA 0"

    @classmethod
    def from_path(cls, path: Path) -> OpenLaneConfig:
        """Load an OpenLane config from ``config.json`` (or ``config.yaml``).

        ``path`` may point either at the file itself or at the project
        directory containing it.
        """
        p = Path(path)
        if p.is_dir():
            for candidate in ("config.json", "config.yaml", "config.yml"):
                if (p / candidate).is_file():
                    p = p / candidate
                    break
            else:
                raise FileNotFoundError(f"No OpenLane config.json/yaml in {path}")

        text = p.read_text(encoding="utf-8")
        if p.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"OpenLane config must be a dict, got {type(data).__name__}")
        return cls.model_validate(data)

    def parsed_die_area(self) -> tuple[float, float, float, float] | None:
        """Parse ``DIE_AREA`` (a space-separated 4-tuple in OpenLane) to floats."""
        if not self.DIE_AREA:
            return None
        parts = self.DIE_AREA.replace(",", " ").split()
        if len(parts) != 4:
            return None
        try:
            x1, y1, x2, y2 = (float(v) for v in parts)
        except ValueError:
            return None
        return (x1, y1, x2, y2)


# ---------------------------------------------------------------------------
# Import: OpenLane project -> OpenForgeConfig
# ---------------------------------------------------------------------------


def _expand_globs(patterns: list[str], root: Path) -> list[str]:
    """Expand globs relative to ``root``. Falls back to the literal pattern.

    Returns POSIX-style relative paths so the resulting yaml is portable.
    """
    expanded: list[str] = []
    for pat in patterns:
        # OpenLane allows ``dir::pattern`` syntax to anchor at a sub-dir.
        if "::" in pat:
            sub, glob = pat.split("::", 1)
            base = (root / sub).resolve()
        else:
            base = root.resolve()
            glob = pat
        # Strip a leading "./"
        glob = glob.removeprefix("./")
        matches = sorted(base.glob(glob))
        if matches:
            for m in matches:
                try:
                    rel = m.resolve().relative_to(root.resolve())
                    expanded.append(rel.as_posix())
                except ValueError:
                    expanded.append(m.as_posix())
        else:
            expanded.append(pat)
    return expanded


def _synthesize_sdc(cfg: OpenLaneConfig, out_path: Path) -> None:
    """Write a minimal SDC file derived from the OpenLane clock variables."""
    if cfg.CLOCK_PERIOD is None or not (cfg.CLOCK_PORT or cfg.CLOCK_NET):
        return
    port = cfg.CLOCK_PORT or cfg.CLOCK_NET
    period = cfg.CLOCK_PERIOD
    lines = [
        "# Generated by openforge openlane import",
        f"create_clock -name clk -period {period} [get_ports {{{port}}}]",
        "set_clock_uncertainty 0.25 [get_clocks clk]",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def import_openlane(
    path: Path,
    *,
    write_yaml: bool = True,
    write_sdc: bool = True,
) -> OpenForgeConfig:
    """Import an OpenLane project at ``path`` and return an ``OpenForgeConfig``.

    Side effects when ``path`` is a directory and ``write_yaml`` is True:
      * writes ``openforge.yaml`` next to the OpenLane ``config.json``
      * writes ``constraints/openlane.sdc`` if a clock is defined

    The mapping is intentionally lossy on the OpenForge side -- OpenLane
    floorplan-specific knobs (utilisation, PDN pitch, density) are stashed in
    the schema's permissive ``extra`` area via ``model_extra``.
    """
    p = Path(path)
    project_dir = p if p.is_dir() else p.parent
    ol = OpenLaneConfig.from_path(p)

    sources = _expand_globs(ol.VERILOG_FILES, project_dir)
    includes = (
        _expand_globs(ol.VERILOG_INCLUDE_DIRS, project_dir) if ol.VERILOG_INCLUDE_DIRS else []
    )

    constraints: list[str] = []
    sdc_rel = "constraints/openlane.sdc"
    if write_sdc and ol.CLOCK_PERIOD is not None and (ol.CLOCK_PORT or ol.CLOCK_NET):
        sdc_abs = project_dir / sdc_rel
        sdc_abs.parent.mkdir(parents=True, exist_ok=True)
        _synthesize_sdc(ol, sdc_abs)
        constraints.append(sdc_rel)

    pdk = _PDK_MAP.get(ol.PDK, ol.PDK)

    cfg = OpenForgeConfig(
        project=ProjectConfig(
            name=ol.DESIGN_NAME,
            top_module=ol.DESIGN_NAME,
            target_pdk=pdk,
            include_dirs=[Path(i) for i in includes],
        ),
        design=DesignConfig(
            sources=sources,
            includes=includes,
            constraints=constraints,
        ),
    )

    # Stash floorplan/synth knobs that don't have a first-class home in the
    # schema, so a round-trip preserves them. ``OpenForgeConfig`` allows
    # extra keys (``model_config = {"extra": "allow"}``).
    extra: dict[str, Any] = {
        "openlane": {
            "PDK": ol.PDK,
            "STD_CELL_LIBRARY": ol.STD_CELL_LIBRARY,
            "FP_CORE_UTIL": ol.FP_CORE_UTIL,
            "FP_ASPECT_RATIO": ol.FP_ASPECT_RATIO,
            "PL_TARGET_DENSITY": ol.PL_TARGET_DENSITY,
            "SYNTH_STRATEGY": ol.SYNTH_STRATEGY,
        }
    }
    die = ol.parsed_die_area()
    if die is not None:
        extra["openlane"]["DIE_AREA"] = list(die)
    if ol.FP_PDN_VPITCH is not None:
        extra["openlane"]["FP_PDN_VPITCH"] = ol.FP_PDN_VPITCH
    if ol.FP_PDN_HPITCH is not None:
        extra["openlane"]["FP_PDN_HPITCH"] = ol.FP_PDN_HPITCH
    # Preserve any unknown keys verbatim
    if ol.model_extra:
        extra["openlane"]["extra"] = dict(ol.model_extra)

    cfg = cfg.model_copy(update=extra)

    if write_yaml and project_dir.is_dir():
        out = project_dir / "openforge.yaml"
        data = cfg.model_dump(mode="json", exclude_none=True)
        out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        logger.info("Wrote %s", out)

    return cfg


# ---------------------------------------------------------------------------
# Export: OpenForge build dir -> OpenLane runs/<tag>/ layout
# ---------------------------------------------------------------------------


def _write_drc_report(drc_json: Path, out_rpt: Path) -> int:
    """Convert an OpenForge DRC JSON (list of violations) to a TritonRoute-style
    text report. Returns the violation count.
    """
    try:
        data = json.loads(drc_json.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        out_rpt.write_text("# DRC report unavailable\n", encoding="utf-8")
        return 0

    violations = data.get("violations", data) if isinstance(data, dict) else data
    if not isinstance(violations, list):
        violations = []

    lines = ["# OpenForge -> OpenLane DRC report", f"# violations: {len(violations)}", ""]
    for i, v in enumerate(violations, start=1):
        rule = v.get("rule", "UNKNOWN") if isinstance(v, dict) else str(v)
        layer = v.get("layer", "?") if isinstance(v, dict) else "?"
        bbox = v.get("bbox", []) if isinstance(v, dict) else []
        bbox_str = " ".join(str(b) for b in bbox) if bbox else "0 0 0 0"
        lines.append(f"violation type: {rule}")
        lines.append(f"\tsrcs: {layer}")
        lines.append(f"\tbbox = ({bbox_str}) on Layer {layer}")
        lines.append("")
    out_rpt.write_text("\n".join(lines), encoding="utf-8")
    return len(violations)


def _maybe_copy(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def export_openlane_reports(build_dir: Path, openlane_run_dir: Path) -> dict[str, Any]:
    """Mirror an OpenForge build output tree into an OpenLane ``runs/<tag>``.

    ``build_dir`` is the OpenForge build directory (typically
    ``<project>/build/``). ``openlane_run_dir`` is the OpenLane run directory
    to populate -- it will be created if it does not exist.

    Returns a dict describing what was copied; useful for tests.
    """
    build = Path(build_dir)
    run = Path(openlane_run_dir)
    (run / "results" / "final").mkdir(parents=True, exist_ok=True)
    (run / "reports" / "synthesis").mkdir(parents=True, exist_ok=True)
    (run / "reports" / "routing").mkdir(parents=True, exist_ok=True)
    (run / "reports" / "signoff").mkdir(parents=True, exist_ok=True)
    (run / "logs").mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {"copied": [], "synthesized": []}

    # Final layout artifacts
    candidates: list[tuple[str, Path]] = [
        ("results/final/def/" + "final.def", _first_match(build, ("*.final.def", "*.def"))),
        ("results/final/gds/" + "final.gds", _first_match(build, ("*.final.gds", "*.gds"))),
        (
            "results/final/verilog/gl/final.v",
            _first_match(build, ("*.nl.v", "*.netlist.v", "*.gl.v")),
        ),
        ("results/final/sdf/final.sdf", _first_match(build, ("*.sdf",))),
        ("results/final/spef/final.spef", _first_match(build, ("*.spef",))),
        ("results/final/sdc/final.sdc", _first_match(build, ("*.sdc",))),
    ]
    for rel_dst, src in candidates:
        if src is None:
            continue
        dst = run / rel_dst
        if _maybe_copy(src, dst):
            summary["copied"].append(rel_dst)

    # Synthesis stat report (synthesized from yosys log if present)
    yosys_log = _first_match(build, ("yosys*.log", "synth*.log"))
    synth_rpt = run / "reports" / "synthesis" / "synthesis.stat.rpt"
    if yosys_log is not None:
        shutil.copy2(yosys_log, synth_rpt)
        summary["copied"].append("reports/synthesis/synthesis.stat.rpt")
    else:
        synth_rpt.write_text("# OpenForge: no yosys log available\n", encoding="utf-8")
        summary["synthesized"].append("reports/synthesis/synthesis.stat.rpt")

    # DRC: synthesise a tritonRoute-style report from our DRC JSON
    drc_json = _first_match(build, ("drc.json", "*drc*.json"))
    drc_rpt = run / "reports" / "signoff" / "tritonRoute.drc"
    if drc_json is not None:
        count = _write_drc_report(drc_json, drc_rpt)
        summary["synthesized"].append(f"reports/signoff/tritonRoute.drc ({count} violations)")
    else:
        drc_rpt.write_text("# OpenForge: no DRC results found\n", encoding="utf-8")
        summary["synthesized"].append("reports/signoff/tritonRoute.drc")

    # Metrics passthrough
    metrics_src = _first_match(build, ("metrics.json", "*metrics*.json"))
    if metrics_src is not None and _maybe_copy(metrics_src, run / "metrics.json"):
        summary["copied"].append("metrics.json")

    return summary


def _first_match(root: Path, patterns: tuple[str, ...]) -> Path | None:
    if not root.exists():
        return None
    for pat in patterns:
        matches = sorted(root.rglob(pat))
        if matches:
            return matches[-1]
    return None

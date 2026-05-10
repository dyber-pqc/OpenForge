"""Tests for the OpenLane <-> OpenForge interop adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from openforge.integrations.openlane import (
    OpenLaneConfig,
    export_openlane_reports,
    import_openlane,
)

FIXTURE = Path(__file__).parent / "fixtures" / "openlane_minimal"


def test_openlane_config_loads_from_json() -> None:
    cfg = OpenLaneConfig.from_path(FIXTURE)
    assert cfg.DESIGN_NAME == "spm"
    assert cfg.CLOCK_PORT == "clk"
    assert cfg.CLOCK_PERIOD == 10.0
    assert cfg.PDK == "sky130A"
    assert cfg.parsed_die_area() == (0.0, 0.0, 100.0, 100.0)
    # Unknown keys preserved via extra="allow"
    assert (cfg.model_extra or {}).get("RUN_HEURISTIC_DIODE_INSERTION") == 1


def test_import_openlane_maps_core_fields(tmp_path: Path) -> None:
    # Copy fixture into tmp so we can write side-effect files
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "src").mkdir()
    (proj / "config.json").write_text((FIXTURE / "config.json").read_text())
    (proj / "src" / "spm.v").write_text((FIXTURE / "src" / "spm.v").read_text())

    cfg = import_openlane(proj)

    # Top-level project
    assert cfg.project.name == "spm"
    assert cfg.project.top_module == "spm"
    assert cfg.project.target_pdk == "sky130A"

    # VERILOG_FILES glob expanded relative to the project
    assert "src/spm.v" in cfg.design.sources

    # Clock -> SDC synthesised, referenced from constraints
    assert any("openlane.sdc" in c for c in cfg.design.constraints)
    sdc = (proj / "constraints" / "openlane.sdc").read_text()
    assert "create_clock" in sdc
    assert "clk" in sdc
    assert "10.0" in sdc

    # openforge.yaml written next to config.json
    written = proj / "openforge.yaml"
    assert written.exists()
    parsed = yaml.safe_load(written.read_text())
    assert parsed["project"]["top_module"] == "spm"

    # Floorplan knobs preserved in the openlane: extra block
    extras = cfg.model_extra or {}
    assert "openlane" in extras
    ol_extra = extras["openlane"]
    assert ol_extra["FP_CORE_UTIL"] == 45.0
    assert ol_extra["DIE_AREA"] == [0.0, 0.0, 100.0, 100.0]
    assert ol_extra["extra"]["RUN_HEURISTIC_DIODE_INSERTION"] == 1


def test_import_openlane_no_writes(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "config.json").write_text((FIXTURE / "config.json").read_text())
    cfg = import_openlane(proj, write_yaml=False, write_sdc=False)
    assert not (proj / "openforge.yaml").exists()
    assert not (proj / "constraints" / "openlane.sdc").exists()
    assert cfg.project.name == "spm"


def test_export_openlane_reports(tmp_path: Path) -> None:
    build = tmp_path / "build"
    build.mkdir()
    # Fake OpenForge build outputs
    (build / "spm.def").write_text("VERSION 5.8 ;\n")
    (build / "spm.gds").write_text("fake-gds")
    (build / "spm.nl.v").write_text("module spm(); endmodule\n")
    (build / "yosys.log").write_text("Number of cells: 42\n")
    (build / "drc.json").write_text(
        json.dumps(
            {
                "violations": [
                    {"rule": "M1.SPACING", "layer": "met1", "bbox": [10, 20, 30, 40]},
                    {"rule": "M2.WIDTH", "layer": "met2", "bbox": [0, 0, 5, 5]},
                ]
            }
        )
    )
    (build / "metrics.json").write_text(json.dumps({"area": 1234, "wns": -0.1}))

    run_dir = tmp_path / "runs" / "openforge"
    summary = export_openlane_reports(build, run_dir)

    # Layout artefacts copied to the OpenLane directory layout
    assert (run_dir / "results" / "final" / "def" / "final.def").exists()
    assert (run_dir / "results" / "final" / "gds" / "final.gds").exists()
    assert (run_dir / "results" / "final" / "verilog" / "gl" / "final.v").exists()

    # DRC report synthesised
    drc = (run_dir / "reports" / "signoff" / "tritonRoute.drc").read_text()
    assert "violations: 2" in drc
    assert "M1.SPACING" in drc

    # Synthesis stat report copied from yosys log
    stat = (run_dir / "reports" / "synthesis" / "synthesis.stat.rpt").read_text()
    assert "Number of cells: 42" in stat

    # Metrics passthrough
    assert (run_dir / "metrics.json").exists()
    assert summary["copied"], "expected at least one copied artefact"


def test_openlane_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        OpenLaneConfig.from_path(tmp_path)

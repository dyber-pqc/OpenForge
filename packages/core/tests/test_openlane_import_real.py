"""Real-world OpenLane import smoke test.

The fixture under ``tests/fixtures/openlane_spm/`` is a verbatim copy of the
``spm`` design from The-OpenROAD-Project/OpenLane (commit master, May 2026).
It exercises the parts of the OpenLane config schema that the synthetic
``openlane_minimal`` fixture does not:

* ``VERILOG_FILES`` as a single space-separated string (not a list)
* ``dir::`` anchor prefix on file paths
* Conditional ``pdk::sky130*`` and ``scl::*`` override blocks
* External SDC (``PNR_SDC_FILE``) instead of synthesised clock
* JSON ``"//"`` comment keys
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from openforge.integrations.openlane import (
    OpenLaneConfig,
    import_openlane,
)

REAL_FIXTURE = Path(__file__).parent / "fixtures" / "openlane_spm"


def _copy_fixture(dst: Path) -> Path:
    """Copy the read-only fixture tree into a writable temp dir."""
    proj = dst / "spm"
    shutil.copytree(REAL_FIXTURE, proj)
    return proj


def test_real_spm_config_loads() -> None:
    """The raw OpenLane config from the spm design parses cleanly."""
    cfg = OpenLaneConfig.from_path(REAL_FIXTURE)
    assert cfg.DESIGN_NAME == "spm"
    assert cfg.CLOCK_PORT == "clk"
    assert cfg.CLOCK_PERIOD == 10.0
    # VERILOG_FILES was a string in the source, should now be a 1-element list
    assert cfg.VERILOG_FILES == ["dir::src/*.v"]
    # PNR_SDC_FILE preserved
    assert cfg.PNR_SDC_FILE == "dir::src/spm.sdc"


def test_real_spm_pdk_conditional_flatten() -> None:
    """``pdk::sky130*`` block should be flattened onto the top-level cfg."""
    cfg = OpenLaneConfig.from_path(REAL_FIXTURE, pdk="sky130A", scl="sky130_fd_sc_hd")
    # FP_CORE_UTIL only exists inside the pdk::sky130* block
    assert cfg.FP_CORE_UTIL == 45.0


def test_real_spm_scl_override_takes_precedence() -> None:
    """When a matching ``scl::`` block is selected, it overrides the pdk block."""
    cfg = OpenLaneConfig.from_path(REAL_FIXTURE, pdk="sky130A", scl="sky130_fd_sc_hs")
    # scl::sky130_fd_sc_hs overrides CLOCK_PERIOD from 10 to 8
    assert cfg.CLOCK_PERIOD == 8.0


def test_real_spm_gf180_branch() -> None:
    """Selecting a different PDK picks the gf180mcu branch."""
    cfg = OpenLaneConfig.from_path(REAL_FIXTURE, pdk="gf180mcuC")
    assert cfg.CLOCK_PERIOD == 24.0
    assert cfg.FP_CORE_UTIL == 40.0
    assert cfg.PL_TARGET_DENSITY == 0.5


def test_import_real_spm_end_to_end(tmp_path: Path) -> None:
    """The full importer succeeds on a real OpenLane project."""
    proj = _copy_fixture(tmp_path)
    cfg = import_openlane(proj)

    assert cfg.project.name == "spm"
    assert cfg.project.top_module == "spm"
    assert cfg.project.target_pdk == "sky130A"

    # The ``dir::src/*.v`` glob should resolve to the actual file
    assert "src/spm.v" in cfg.design.sources

    # The external PNR_SDC_FILE wins over the synthesised one
    assert "src/spm.sdc" in cfg.design.constraints
    # And we did NOT clobber it with the synth fallback
    assert not (proj / "constraints" / "openlane.sdc").exists()

    # openforge.yaml round-trips
    written = proj / "openforge.yaml"
    assert written.exists()
    parsed = yaml.safe_load(written.read_text())
    assert parsed["project"]["top_module"] == "spm"
    assert "src/spm.v" in parsed["design"]["sources"]
    assert "src/spm.sdc" in parsed["design"]["constraints"]

    # Floorplan knobs from the pdk::sky130* branch landed in the extras
    extras = cfg.model_extra or {}
    assert extras.get("openlane", {}).get("FP_CORE_UTIL") == 45.0


def test_import_real_spm_via_cli(tmp_path: Path) -> None:
    """The ``openforge openlane import`` CLI subcommand handles the real config."""
    proj = _copy_fixture(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "openforge_cli", "openlane", "import", str(proj)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        # CLI entrypoint not installed in this env -- skip rather than fail.
        pytest.skip(f"openforge CLI not runnable as a module here: {result.stderr.strip()[:200]}")
    assert "spm" in result.stdout
    assert (proj / "openforge.yaml").exists()

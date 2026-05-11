"""End-to-end test of the native sign-off binaries against the real
PicoRV32 build artifacts. Exercises the same code paths that
`full_flow.py`'s `drc_native` / `lvs_native` / `xrc_native` stages drive.

Auto-skips when artifacts or binaries are absent so CI doesn't break in
fresh checkouts. Locally, after running the PicoRV32 flow once, this test
acts as a regression for the whole orchestration.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from openforge.flow.full_flow import (
    _find_native_signoff_binary,
    _select_lvs_netlist,
)

REPO = Path(__file__).resolve().parents[3]
PICO = REPO / "examples" / "asic-picorv32-sky130"
BUILD = PICO / "build"
GDS = BUILD / "gds_export" / "picorv32.gds"
ROUTED_DEF = BUILD / "routing" / "routed.def"
ROUTED_V = BUILD / "routing" / "routed.v"
LEF = REPO / "share" / "pdk" / "sky130" / "lef" / "sky130_fd_sc_hd_merged.lef"
DRC_RULES = REPO / "tools" / "openforge-drc" / "tests" / "fixtures" / "sky130_subset.drc"


def _need(*paths: Path) -> None:
    for p in paths:
        if not p.exists():
            pytest.skip(f"required artifact not present: {p}")


def _need_bin(name: str) -> str:
    bin_path = _find_native_signoff_binary(name)
    if bin_path is None or not Path(bin_path).exists():
        pytest.skip(f"native binary not built: {name}")
    return bin_path


def test_native_drc_runs_on_picorv32_gds(tmp_path: Path) -> None:
    drc = _need_bin("openforge-drc")
    _need(GDS, DRC_RULES)
    result = subprocess.run(
        [drc, "check", str(GDS), "--rules-drx", str(DRC_RULES), "--tech", "sky130A"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr
    # 8 rules across 6 layers per the documented baseline
    assert "rules across" in result.stdout
    assert "Total:" in result.stdout and "violations" in result.stdout


def test_native_lvs_matches_picorv32(tmp_path: Path) -> None:
    lvs = _need_bin("openforge-lvs")
    _need(ROUTED_DEF, ROUTED_V, LEF)
    result = subprocess.run(
        [
            lvs, "check",
            "--layout-def", str(ROUTED_DEF),
            "--layout-lef", str(LEF),
            "--schematic", str(ROUTED_V),
            "--top", "picorv32",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr
    assert "MATCH" in result.stdout, result.stdout

    report = tmp_path / "lvs.json"
    assert report.exists()
    data = json.loads(report.read_text())
    # device counts must agree
    devs_layout = data.get("layout_devices") or data.get("layout", {}).get("devices")
    devs_schem = data.get("schematic_devices") or data.get("schematic", {}).get("devices")
    if devs_layout is not None and devs_schem is not None:
        assert devs_layout == devs_schem


def test_native_xrc_extracts_picorv32(tmp_path: Path) -> None:
    xrc = _need_bin("openforge-xrc")
    _need(ROUTED_DEF, LEF)
    spef = tmp_path / "picorv32.spef"
    result = subprocess.run(
        [
            xrc, "extract",
            "--def", str(ROUTED_DEF),
            "--lef", str(LEF),
            "--tech", "sky130A",
            "--corner", "typ",
            "--output", str(spef),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr
    assert spef.exists() and spef.stat().st_size > 1024
    assert "Total wirelength" in result.stdout


def test_lvs_netlist_selector_prefers_routed_v() -> None:
    """The LVS netlist selector should prefer routed.v > cts.v > netlist.v
    when comparing against routed.def."""
    if not BUILD.exists():
        pytest.skip("picorv32 build dir absent")
    pick = _select_lvs_netlist(BUILD)
    assert pick is not None
    if ROUTED_V.exists():
        assert pick.name == "routed.v"

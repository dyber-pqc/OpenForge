"""Tests for openforge.yaml stage-override plumbing into full_flow TCL.

Closes the flow gap where ``floorplan.utilization`` / ``floorplan.die_area``
/ ``routing.droute_end_iter`` etc. set in openforge.yaml were ignored, and
the user had to hand-edit build/floorplan/floorplan.tcl after each run.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from openforge.config.schema import (
    CtsConfig,
    FloorplanConfig,
    OpenForgeConfig,
    PlacementConfig,
    RoutingConfig,
)
from openforge.flow.full_flow import (
    FullFlowConfig,
    _write_cts_tcl,
    _write_floorplan_tcl,
    _write_placement_tcl,
    _write_routing_tcl,
)


def _base_cfg(tmp_path: Path, **overrides: object) -> FullFlowConfig:
    sdc = tmp_path / "design.sdc"
    sdc.write_text("create_clock -period 10 [get_ports clk]\n", encoding="utf-8")
    rtl = tmp_path / "design.v"
    rtl.write_text("module top(input clk); endmodule\n", encoding="utf-8")
    return FullFlowConfig(
        top_module="top",
        rtl_files=[str(rtl)],
        sdc_file=str(sdc),
        **overrides,  # type: ignore[arg-type]
    )


# ── Floorplan overrides ──────────────────────────────────────────────────


def test_utilization_override_propagates_as_percent(tmp_path: Path) -> None:
    """``floorplan_utilization=0.30`` -> ``-utilization 30`` in the TCL."""
    out = tmp_path / "build"
    out.mkdir()
    cfg = _base_cfg(tmp_path, floorplan_utilization=0.30)
    tcl = Path(_write_floorplan_tcl(out, cfg)).read_text(encoding="utf-8")
    assert "-utilization 30" in tcl, tcl


def test_utilization_default_preserves_legacy_behaviour(tmp_path: Path) -> None:
    """Omitting the override falls back to ``core_utilization`` (default 50)."""
    out = tmp_path / "build"
    out.mkdir()
    cfg = _base_cfg(tmp_path)  # no override
    tcl = Path(_write_floorplan_tcl(out, cfg)).read_text(encoding="utf-8")
    assert "-utilization 50" in tcl
    # The historical defaults must still appear so existing flows aren't broken.
    assert "-aspect_ratio 1.0" in tcl
    assert "-site unithd" in tcl


def test_die_area_override_propagates(tmp_path: Path) -> None:
    """``die_area=[0,0,506,506]`` -> ``-die_area "0 0 506 506"``."""
    out = tmp_path / "build"
    out.mkdir()
    cfg = _base_cfg(
        tmp_path,
        floorplan_die_area=[0, 0, 506, 506],
        floorplan_core_area=[20, 20, 486, 486],
    )
    tcl = Path(_write_floorplan_tcl(out, cfg)).read_text(encoding="utf-8")
    assert '-die_area "0 0 506 506"' in tcl, tcl
    assert '-core_area "20 20 486 486"' in tcl, tcl


def test_aspect_ratio_and_core_margin_override(tmp_path: Path) -> None:
    out = tmp_path / "build"
    out.mkdir()
    cfg = _base_cfg(tmp_path, floorplan_aspect_ratio=1.5, floorplan_core_margin=4.0)
    tcl = Path(_write_floorplan_tcl(out, cfg)).read_text(encoding="utf-8")
    assert "-aspect_ratio 1.5" in tcl
    assert "-core_space 4.0" in tcl


# ── Placement / CTS overrides ────────────────────────────────────────────


def test_placement_target_density_override(tmp_path: Path) -> None:
    out = tmp_path / "build"
    out.mkdir()
    cfg = _base_cfg(tmp_path, placement_target_density=0.40)
    tcl = Path(_write_placement_tcl(out, cfg)).read_text(encoding="utf-8")
    assert "global_placement -density 0.4" in tcl


def test_placement_density_default(tmp_path: Path) -> None:
    out = tmp_path / "build"
    out.mkdir()
    cfg = _base_cfg(tmp_path)
    tcl = Path(_write_placement_tcl(out, cfg)).read_text(encoding="utf-8")
    assert "global_placement -density 0.6" in tcl


def test_cts_target_skew_override(tmp_path: Path) -> None:
    out = tmp_path / "build"
    out.mkdir()
    cfg = _base_cfg(tmp_path, cts_target_skew=0.05)
    tcl = Path(_write_cts_tcl(out, cfg)).read_text(encoding="utf-8")
    assert "-target_skew 0.05" in tcl


def test_cts_no_skew_by_default(tmp_path: Path) -> None:
    out = tmp_path / "build"
    out.mkdir()
    cfg = _base_cfg(tmp_path)
    tcl = Path(_write_cts_tcl(out, cfg)).read_text(encoding="utf-8")
    assert "-target_skew" not in tcl


# ── Routing overrides ───────────────────────────────────────────────────


def test_droute_end_iter_override(tmp_path: Path) -> None:
    """``routing_droute_end_iter=6`` -> ``-droute_end_iter 6`` in route.tcl."""
    out = tmp_path / "build"
    out.mkdir()
    cfg = _base_cfg(tmp_path, routing_droute_end_iter=6)
    tcl = Path(_write_routing_tcl(out, cfg)).read_text(encoding="utf-8")
    assert "-droute_end_iter 6" in tcl, tcl


def test_global_route_iters_override(tmp_path: Path) -> None:
    out = tmp_path / "build"
    out.mkdir()
    cfg = _base_cfg(tmp_path, routing_global_route_iters=8)
    tcl = Path(_write_routing_tcl(out, cfg)).read_text(encoding="utf-8")
    assert "-congestion_iterations 8" in tcl


def test_routing_defaults_omit_optional_args(tmp_path: Path) -> None:
    out = tmp_path / "build"
    out.mkdir()
    cfg = _base_cfg(tmp_path)
    tcl = Path(_write_routing_tcl(out, cfg)).read_text(encoding="utf-8")
    assert "-droute_end_iter" not in tcl
    assert "-congestion_iterations" not in tcl


# ── End-to-end: OpenForgeConfig -> FullFlowConfig -> TCL ────────────────


def test_from_openforge_config_round_trip(tmp_path: Path) -> None:
    """Stage overrides on OpenForgeConfig flow through to TCL output."""
    oc = OpenForgeConfig(
        floorplan=FloorplanConfig(
            utilization=0.30, die_area=[0, 0, 506, 506], core_area=[20, 20, 486, 486]
        ),
        placement=PlacementConfig(target_density=0.40),
        cts=CtsConfig(target_skew=0.05),
        routing=RoutingConfig(droute_end_iter=6),
    )
    sdc = tmp_path / "design.sdc"
    sdc.write_text("create_clock -period 10 [get_ports clk]\n", encoding="utf-8")
    rtl = tmp_path / "design.v"
    rtl.write_text("module top(input clk); endmodule\n", encoding="utf-8")

    cfg = FullFlowConfig.from_openforge_config(
        oc,
        top_module="top",
        rtl_files=[str(rtl)],
        sdc_file=str(sdc),
    )
    assert cfg.floorplan_utilization == 0.30
    assert cfg.floorplan_die_area == [0, 0, 506, 506]
    assert cfg.placement_target_density == 0.40
    assert cfg.cts_target_skew == 0.05
    assert cfg.routing_droute_end_iter == 6

    out = tmp_path / "build"
    out.mkdir()
    fp = Path(_write_floorplan_tcl(out, cfg)).read_text(encoding="utf-8")
    rt = Path(_write_routing_tcl(out, cfg)).read_text(encoding="utf-8")
    assert '-die_area "0 0 506 506"' in fp
    assert "-droute_end_iter 6" in rt


def test_picorv32_yaml_loads_with_overrides() -> None:
    """The shipped example yaml parses cleanly with new floorplan/routing keys."""
    repo_root = Path(__file__).resolve().parents[3]
    yaml_path = repo_root / "examples" / "asic-picorv32-sky130" / "openforge.yaml"
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    oc = OpenForgeConfig.model_validate(raw)
    assert oc.floorplan is not None
    assert oc.floorplan.utilization == 0.30
    assert oc.floorplan.die_area == [0, 0, 506, 506]
    assert oc.routing is not None
    assert oc.routing.droute_end_iter == 6
    assert oc.placement is not None
    assert oc.placement.target_density == 0.40

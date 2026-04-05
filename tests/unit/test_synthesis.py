"""Tests for the synthesis flow manager."""

from __future__ import annotations

from openforge.synthesis.optimization import (
    OptimizationPass,
    generate_abc_script,
    generate_synth_script,
)


def test_abc_script_area() -> None:
    script = generate_abc_script(OptimizationPass.AREA, liberty_file="sky130.lib")
    assert "strash" in script
    assert "map" in script.lower() or "abc" in script.lower()


def test_abc_script_speed() -> None:
    script = generate_abc_script(
        OptimizationPass.SPEED,
        target_delay_ps=5000,
        liberty_file="sky130.lib",
    )
    assert "strash" in script
    assert "5000" in script or "5.0" in script or "map" in script.lower()


def test_abc_script_balanced() -> None:
    script = generate_abc_script(OptimizationPass.BALANCED, liberty_file="sky130.lib")
    assert "strash" in script


def test_generate_synth_script_basic() -> None:
    script = generate_synth_script(
        sources=["rtl/top.sv", "rtl/sub.v"],
        top_module="top",
        liberty_file="sky130.lib",
        output_dir="/tmp/synth_out",
    )

    # Must read both sources
    assert "read_verilog -sv rtl/top.sv" in script or "read_verilog -sv" in script
    assert "read_verilog rtl/sub.v" in script or "read_verilog" in script

    # Must have hierarchy
    assert "hierarchy -top top" in script

    # Must have tech mapping
    assert "dfflibmap" in script
    assert "abc" in script
    assert "sky130.lib" in script

    # Must write outputs
    assert "write_verilog" in script or "write_json" in script

    # Must have stats
    assert "stat" in script


def test_generate_synth_script_flatten() -> None:
    script = generate_synth_script(
        sources=["rtl/top.sv"],
        top_module="top",
        liberty_file="sky130.lib",
        output_dir="/tmp",
        flatten=True,
    )
    assert "flatten" in script


def test_optimization_pass_enum() -> None:
    assert OptimizationPass.AREA.value == "area"
    assert OptimizationPass.SPEED.value == "speed"
    assert OptimizationPass.BALANCED.value == "balanced"
    assert OptimizationPass.LOW_POWER.value == "low_power"

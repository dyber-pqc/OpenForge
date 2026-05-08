"""Tests for the CTS stage of the full RTL-to-GDS flow.

Specifically validates that the CTS Tcl script emits a Verilog netlist
(``cts.v``) alongside ``cts.def`` so LVS can compare apples-to-apples
against the post-CTS layout, and that the LVS netlist selector picks
the most-faithful available netlist.
"""

from __future__ import annotations

from pathlib import Path

from openforge.flow.full_flow import (
    FullFlowConfig,
    FullFlowRunner,
    _select_lvs_netlist,
    _write_cts_tcl,
)


def _cfg(tmp_path: Path) -> FullFlowConfig:
    sdc = tmp_path / "design.sdc"
    sdc.write_text("create_clock -period 10 [get_ports clk]\n", encoding="utf-8")
    rtl = tmp_path / "design.v"
    rtl.write_text("module top(input clk); endmodule\n", encoding="utf-8")
    return FullFlowConfig(
        top_module="top",
        rtl_files=[str(rtl)],
        sdc_file=str(sdc),
    )


def test_cts_tcl_emits_both_def_and_verilog(tmp_path: Path) -> None:
    """The CTS Tcl script must produce cts.def AND cts.v."""
    out = tmp_path / "build"
    out.mkdir()
    cfg = _cfg(tmp_path)

    tcl_path = Path(_write_cts_tcl(out, cfg))
    assert tcl_path.exists()
    body = tcl_path.read_text(encoding="utf-8")
    assert "write_def cts.def" in body
    assert "write_verilog cts.v" in body
    # Must occur after CTS runs, not before
    assert body.index("clock_tree_synthesis") < body.index("write_verilog cts.v")


def test_cts_stage_advertises_verilog_artifact(tmp_path: Path) -> None:
    """The cts RunStage's `produces` glob list must include *.v."""
    cfg = _cfg(tmp_path)
    runner = FullFlowRunner(cfg, work_dir=tmp_path)
    graph = runner.build_graph()
    cts_stage = graph._stages["cts"]
    assert "*.v" in cts_stage.produces, (
        f"CTS stage must declare *.v artifact; got {cts_stage.produces}"
    )
    assert "*.def" in cts_stage.produces


def test_select_lvs_netlist_prefers_routed(tmp_path: Path) -> None:
    """Routed netlist beats CTS netlist beats synth netlist."""
    out = tmp_path / "build"
    (out / "synth").mkdir(parents=True)
    (out / "cts").mkdir(parents=True)
    (out / "routing").mkdir(parents=True)

    synth_v = out / "synth" / "netlist.v"
    cts_v = out / "cts" / "cts.v"
    routed_v = out / "routing" / "routed.v"

    synth_v.write_text("// synth\n", encoding="utf-8")
    assert _select_lvs_netlist(out) == synth_v

    cts_v.write_text("// cts\n", encoding="utf-8")
    assert _select_lvs_netlist(out) == cts_v

    routed_v.write_text("// routed\n", encoding="utf-8")
    assert _select_lvs_netlist(out) == routed_v


def test_select_lvs_netlist_fallback_when_nothing_exists(tmp_path: Path) -> None:
    """Returns synth path even if it doesn't exist (caller validates)."""
    out = tmp_path / "build"
    out.mkdir()
    picked = _select_lvs_netlist(out)
    assert picked == out / "synth" / "netlist.v"

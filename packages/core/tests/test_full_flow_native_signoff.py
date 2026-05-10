"""Tests for the native (Rust) signoff stages in the full RTL-to-GDS flow.

Validates that the three openforge-{drc,lvs,xrc} binaries are wired into
the DAG when available, declare the right ``produces`` outputs, and skip
gracefully when the binary isn't on the system.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from openforge.flow import full_flow as ff
from openforge.flow.full_flow import (
    ADVISORY_STAGE_IDS,
    FullFlowConfig,
    FullFlowRunner,
    NativeSignoffSummary,
    _collect_native_signoff,
    _find_native_signoff_binary,
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


def _build(tmp_path: Path, **overrides: object):
    cfg = _cfg(tmp_path).model_copy(update=overrides)
    runner = FullFlowRunner(cfg, work_dir=tmp_path)
    return runner.build_graph()


# ── Stage presence ─────────────────────────────────────────────────────


def test_native_stages_added_when_binaries_present(tmp_path: Path) -> None:
    """All three native stages join the DAG when the binaries are found."""
    with patch.object(ff, "_find_native_signoff_binary", lambda name: f"/fake/{name}"):
        graph = _build(tmp_path)
    for sid in ("drc_native", "lvs_native", "xrc_native"):
        assert sid in graph._stages, f"missing native stage {sid}"


def test_native_stages_skipped_when_binaries_missing(tmp_path: Path) -> None:
    """No native stage is added when openforge-{drc,lvs,xrc} can't be found."""
    with patch.object(ff, "_find_native_signoff_binary", lambda name: None):
        graph = _build(tmp_path)
    for sid in ("drc_native", "lvs_native", "xrc_native"):
        assert sid not in graph._stages


def test_signoff_native_flag_disables_all_three(tmp_path: Path) -> None:
    """signoff_native=False skips the native stages even if binaries exist."""
    with patch.object(ff, "_find_native_signoff_binary", lambda name: f"/fake/{name}"):
        graph = _build(tmp_path, signoff_native=False)
    for sid in ("drc_native", "lvs_native", "xrc_native"):
        assert sid not in graph._stages


# ── Stage shape ─────────────────────────────────────────────────────────


def test_drc_native_stage_shape(tmp_path: Path) -> None:
    with patch.object(ff, "_find_native_signoff_binary", lambda name: f"/fake/{name}"):
        graph = _build(tmp_path)
    s = graph._stages["drc_native"]
    assert s.depends_on == ["gds_export"]
    assert "*.rpt" in s.produces
    # The original (pre-resolver) command starts with the binary path.
    cmd = " ".join(s.command)
    assert "openforge-drc" in cmd
    assert "check" in s.command
    assert "--output" in s.command


def test_lvs_native_stage_shape(tmp_path: Path) -> None:
    with patch.object(ff, "_find_native_signoff_binary", lambda name: f"/fake/{name}"):
        graph = _build(tmp_path)
    s = graph._stages["lvs_native"]
    assert s.depends_on == ["gds_export"]
    assert "*.json" in s.produces
    assert "--layout" in s.command
    assert "--schematic" in s.command
    assert "--top" in s.command
    assert "top" in s.command  # the top_module value


def test_xrc_native_stage_shape(tmp_path: Path) -> None:
    with patch.object(ff, "_find_native_signoff_binary", lambda name: f"/fake/{name}"):
        graph = _build(tmp_path)
    s = graph._stages["xrc_native"]
    assert s.depends_on == ["routing"]
    assert "*.spef" in s.produces
    assert "extract" in s.command
    assert "--def" in s.command
    assert "--lef" in s.command


# ── Advisory classification ────────────────────────────────────────────


def test_advisory_set_includes_native_stages() -> None:
    for sid in ("drc_native", "lvs_native", "xrc_native"):
        assert sid in ADVISORY_STAGE_IDS, f"{sid} must be advisory, not chip-blocking"
    # Existing advisory stages preserved
    for sid in ("lint", "drc", "lvs"):
        assert sid in ADVISORY_STAGE_IDS


# ── Helper: binary discovery ───────────────────────────────────────────


def test_find_native_signoff_binary_returns_none_for_unknown() -> None:
    assert _find_native_signoff_binary("openforge-does-not-exist-xyz") is None


def test_find_native_signoff_binary_uses_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ff.shutil, "which", lambda n: "/usr/bin/" + n)
    assert _find_native_signoff_binary("openforge-drc") == "/usr/bin/openforge-drc"


# ── Result summary parser ──────────────────────────────────────────────


def test_collect_native_signoff_empty(tmp_path: Path) -> None:
    """No artifacts -> all-None summary."""
    summary = _collect_native_signoff(tmp_path)
    assert isinstance(summary, NativeSignoffSummary)
    assert summary.drc_violations is None
    assert summary.lvs_matched is None
    assert summary.xrc_total_capacitance_pf is None


def test_collect_native_signoff_parses_artifacts(tmp_path: Path) -> None:
    (tmp_path / "drc_native").mkdir()
    (tmp_path / "drc_native" / "drc.rpt").write_text("Total: 0\n", encoding="utf-8")
    (tmp_path / "lvs_native").mkdir()
    (tmp_path / "lvs_native" / "lvs.json").write_text('{"matched": true}', encoding="utf-8")
    (tmp_path / "xrc").mkdir()
    (tmp_path / "xrc" / "top.spef").write_text("1 net_a 0.0042\n2 net_b 0.0008\n", encoding="utf-8")

    summary = _collect_native_signoff(tmp_path)
    assert summary.drc_violations == 0
    assert summary.lvs_matched is True
    assert summary.xrc_total_capacitance_pf == pytest.approx(0.005, rel=1e-3)

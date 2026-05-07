"""End-to-end smoke test for the full RTL-to-GDS flow.

Runs on examples/simple-counter with sky130 PDK (mocked if tools not
available).
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from openforge.flow.full_flow import (
    STAGE_IDS,
    STAGE_NAMES,
    FullFlowConfig,
    FullFlowResult,
    FullFlowRunner,
)
from openforge.runner.engine import RunGraph, RunStage, RunStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples" / "simple-counter"


@pytest.fixture()
def flow_config(tmp_path: Path) -> FullFlowConfig:
    """A minimal config pointing at the simple-counter example."""
    src = EXAMPLES_DIR / "src" / "counter.v"
    sdc = EXAMPLES_DIR / "constraints" / "timing.sdc"
    return FullFlowConfig(
        top_module="counter",
        rtl_files=[str(src)],
        sdc_file=str(sdc),
        pdk="sky130A",
        std_cell_lib="sky130_fd_sc_hd",
        target_freq_mhz=100.0,
        core_utilization=50.0,
        output_dir="build",
    )


@pytest.fixture()
def work_dir(tmp_path: Path) -> Path:
    return tmp_path / "work"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFullFlowGraphBuilds:
    """Verify the DAG builds without errors."""

    def test_graph_has_all_stages(self, flow_config: FullFlowConfig, work_dir: Path) -> None:
        runner = FullFlowRunner(flow_config, work_dir)
        graph = runner.build_graph()
        ids = {s.id for s in graph.stages()}
        for sid in STAGE_IDS:
            assert sid in ids, f"Missing stage: {sid}"

    def test_graph_topological_order(self, flow_config: FullFlowConfig, work_dir: Path) -> None:
        runner = FullFlowRunner(flow_config, work_dir)
        graph = runner.build_graph()
        order = graph.topological_order()
        assert len(order) == len(graph.stages())

    def test_graph_lint_has_no_deps(self, flow_config: FullFlowConfig, work_dir: Path) -> None:
        runner = FullFlowRunner(flow_config, work_dir)
        graph = runner.build_graph()
        lint = graph.get("lint")
        assert lint.depends_on == []

    def test_graph_synth_depends_on_lint(self, flow_config: FullFlowConfig, work_dir: Path) -> None:
        runner = FullFlowRunner(flow_config, work_dir)
        graph = runner.build_graph()
        synth = graph.get("synth")
        assert "lint" in synth.depends_on

    def test_graph_skip_drc(self, work_dir: Path) -> None:
        cfg = FullFlowConfig(
            top_module="counter",
            rtl_files=["counter.v"],
            sdc_file="timing.sdc",
            skip_drc=True,
        )
        runner = FullFlowRunner(cfg, work_dir)
        graph = runner.build_graph()
        ids = {s.id for s in graph.stages()}
        assert "drc" not in ids

    def test_graph_skip_lvs(self, work_dir: Path) -> None:
        cfg = FullFlowConfig(
            top_module="counter",
            rtl_files=["counter.v"],
            sdc_file="timing.sdc",
            skip_lvs=True,
        )
        runner = FullFlowRunner(cfg, work_dir)
        graph = runner.build_graph()
        ids = {s.id for s in graph.stages()}
        assert "lvs" not in ids

    def test_stage_names_mapping(self) -> None:
        for sid in STAGE_IDS:
            assert sid in STAGE_NAMES, f"Missing name for {sid}"


class TestFullFlowWithMockTools:
    """Run the full flow with mock subprocess calls that return
    known-good outputs."""

    def _fake_popen(
        self,
        cmd: list[str],
        cwd: str | None = None,
        stdout: Any = None,
        stderr: Any = None,
        env: dict[str, str] | None = None,
    ) -> MagicMock:
        """Create a fake Popen that writes success output and exits 0."""
        proc = MagicMock()
        proc.stdout = iter([b"[mock] Running OK\n", b"[mock] Done\n"])
        proc.wait.return_value = 0
        proc.returncode = 0

        # Create dummy output files in cwd for artifact collection
        if cwd:
            cwd_path = Path(cwd)
            cwd_path.mkdir(parents=True, exist_ok=True)
            # Write dummy artifacts based on which tool is being run
            cmd_str = " ".join(cmd)
            if "yosys" in cmd_str:
                (cwd_path / "netlist.json").write_text("{}", encoding="utf-8")
                (cwd_path / "netlist.v").write_text("// netlist\n", encoding="utf-8")
            elif "openroad" in cmd_str:
                (cwd_path / "out.def").write_text("VERSION 5.8\nEND DESIGN\n", encoding="utf-8")
            elif "magic" in cmd_str and "drc" in cmd_str.lower():
                (cwd_path / "drc.rpt").write_text("DRC errors: 0\n", encoding="utf-8")
            elif "magic" in cmd_str:
                (cwd_path / "counter.gds").write_bytes(b"\x00GDS")
            elif "sta" in cmd_str:
                (cwd_path / "timing.rpt").write_text("WNS 0.500\nTNS 0.000\n", encoding="utf-8")
            elif "netgen" in cmd_str:
                (cwd_path / "lvs.rpt").write_text("Circuits match.\n", encoding="utf-8")
            elif "verible" in cmd_str:
                pass  # lint produces no files on success

        return proc

    @patch("subprocess.Popen")
    def test_full_flow_mock_success(
        self,
        mock_popen: MagicMock,
        flow_config: FullFlowConfig,
        work_dir: Path,
    ) -> None:
        mock_popen.side_effect = self._fake_popen

        runner = FullFlowRunner(flow_config, work_dir)
        progress_log: list[tuple[str, str]] = []

        def _cb(stage: str, status: str) -> None:
            progress_log.append((stage, status))

        result = runner.run(progress_callback=_cb)

        assert isinstance(result, FullFlowResult)
        assert result.overall_status == "success"
        assert result.total_runtime_s >= 0
        # Every stage should have been called back
        called_stages = {s for s, _ in progress_log}
        for sid in STAGE_IDS:
            assert sid in called_stages, f"Stage {sid} was not called back"

    @patch("subprocess.Popen")
    def test_full_flow_mock_synth_failure(
        self,
        mock_popen: MagicMock,
        flow_config: FullFlowConfig,
        work_dir: Path,
    ) -> None:
        call_count = 0

        def _fail_on_synth(cmd: list[str], **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            proc = MagicMock()
            cmd_str = " ".join(cmd)
            if "yosys" in cmd_str:
                proc.stdout = iter([b"ERROR: synthesis failed\n"])
                proc.wait.return_value = 1
                proc.returncode = 1
            else:
                proc.stdout = iter([b"OK\n"])
                proc.wait.return_value = 0
                proc.returncode = 0
            return proc

        mock_popen.side_effect = _fail_on_synth

        runner = FullFlowRunner(flow_config, work_dir)
        result = runner.run()

        assert result.overall_status == "failed"
        # Downstream stages should be skipped
        stage_map = {s.stage: s.status for s in result.stages}
        assert stage_map["synth"] == "failed"


class TestFullFlowArtifacts:
    """Verify all expected artifacts are created in the output directory."""

    @patch("subprocess.Popen")
    def test_artifacts_created(
        self,
        mock_popen: MagicMock,
        flow_config: FullFlowConfig,
        work_dir: Path,
    ) -> None:
        def _fake(cmd: list[str], **kwargs: Any) -> MagicMock:
            proc = MagicMock()
            proc.stdout = iter([b"OK\n"])
            proc.wait.return_value = 0
            proc.returncode = 0
            cwd = kwargs.get("cwd")
            if cwd:
                cwd_path = Path(cwd)
                cwd_path.mkdir(parents=True, exist_ok=True)
                cmd_str = " ".join(cmd)
                if "yosys" in cmd_str:
                    synth_dir = work_dir / "build" / "synth"
                    synth_dir.mkdir(parents=True, exist_ok=True)
                    (synth_dir / "netlist.json").write_text("{}", encoding="utf-8")
                    (synth_dir / "netlist.v").write_text("// netlist\n", encoding="utf-8")
                elif "openroad" in cmd_str and "floorplan" in cmd_str:
                    (cwd_path / "floorplan.def").write_text("VERSION 5.8\n", encoding="utf-8")
                elif "openroad" in cmd_str and "placement" in cmd_str:
                    (cwd_path / "placed.def").write_text("VERSION 5.8\n", encoding="utf-8")
                elif "openroad" in cmd_str and "cts" in cmd_str:
                    (cwd_path / "cts.def").write_text("VERSION 5.8\n", encoding="utf-8")
                elif "openroad" in cmd_str and "route" in cmd_str:
                    (cwd_path / "routed.def").write_text("VERSION 5.8\n", encoding="utf-8")
                    (cwd_path / "routed.spef").write_text("", encoding="utf-8")
                elif "openroad" in cmd_str and "fill" in cmd_str:
                    (cwd_path / "filled.def").write_text("VERSION 5.8\n", encoding="utf-8")
                elif "sta" in cmd_str:
                    (cwd_path / "timing.rpt").write_text("WNS 0.5\n", encoding="utf-8")
                elif "magic" in cmd_str and "drc" in cmd_str.lower():
                    (cwd_path / "drc.rpt").write_text("DRC errors: 0\n", encoding="utf-8")
                elif "magic" in cmd_str:
                    gds_dir = work_dir / "build" / "gds_export"
                    gds_dir.mkdir(parents=True, exist_ok=True)
                    (gds_dir / "counter.gds").write_bytes(b"\x00GDS")
                elif "netgen" in cmd_str:
                    (cwd_path / "lvs.rpt").write_text("Circuits match.\n", encoding="utf-8")
            return proc

        mock_popen.side_effect = _fake

        runner = FullFlowRunner(flow_config, work_dir)
        runner.run()

        build_dir = work_dir / "build"
        # Verify key directories were created
        assert (build_dir / "synth").is_dir()
        assert (build_dir / "floorplan").is_dir()
        assert (build_dir / "placement").is_dir()
        assert (build_dir / "cts").is_dir()
        assert (build_dir / "routing").is_dir()
        assert (build_dir / "fill").is_dir()
        assert (build_dir / "sta").is_dir()
        assert (build_dir / "drc").is_dir()
        assert (build_dir / "lvs").is_dir()
        assert (build_dir / "gds_export").is_dir()


class TestFullFlowConfig:
    """Test FullFlowConfig model validation."""

    def test_defaults(self) -> None:
        cfg = FullFlowConfig(
            top_module="top",
            rtl_files=["a.v"],
            sdc_file="a.sdc",
        )
        assert cfg.pdk == "sky130A"
        assert cfg.core_utilization == 50.0
        assert cfg.skip_drc is False
        assert cfg.skip_lvs is False

    def test_custom_values(self) -> None:
        cfg = FullFlowConfig(
            top_module="crypto_core",
            rtl_files=["a.v", "b.v"],
            sdc_file="crypto.sdc",
            pdk="gf180mcuD",
            std_cell_lib="gf180mcu_fd_sc_mcu7t5v0",
            target_freq_mhz=200.0,
            core_utilization=70.0,
            output_dir="out",
            skip_lvs=True,
            skip_drc=True,
        )
        assert cfg.pdk == "gf180mcuD"
        assert cfg.skip_lvs is True
        assert len(cfg.rtl_files) == 2

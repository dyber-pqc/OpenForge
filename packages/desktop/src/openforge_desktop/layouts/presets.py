"""Persona-based dock-layout presets for the OpenForge main window.

A *preset* describes which docks are visible, where they live, and how
they're sized. Presets are applied at runtime by walking the main
window's :class:`QDockWidget` children and matching their
``objectName()``. Unknown panel names are silently ignored so missing
optional panels never break a preset.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover
    from PySide6.QtWidgets import QMainWindow


class LayoutPreset(BaseModel):
    name: str
    description: str
    visible_docks: list[str] = Field(default_factory=list)
    dock_areas: dict[str, str] = Field(default_factory=dict)
    dock_sizes: dict[str, int] = Field(default_factory=dict)
    splitters: dict[str, list[int]] = Field(default_factory=dict)
    icon: str = "\u25a1"


# Dock object-name conventions in mainwindow.py:
#  flow_navigator_dock, hierarchy_dock, ip_catalog_dock, project_explorer_dock,
#  console_dock, waveform_dock, testbench_dock, reports_dock, timing_dock,
#  properties_dock, synthesis_dock, physical_design_dock, security_dock,
#  layout_dock, gds_viewer_dock, constraint_editor_dock, pin_planner_dock,
#  block_design_dock, git_dock, ai_assistant_dock, pdk_manager_dock,
#  cell_library_dock, floorplan_editor_dock


_DEFAULT = LayoutPreset(
    name="default",
    description="OpenForge default workspace.",
    visible_docks=[
        "hierarchy_dock",
        "ip_catalog_dock",
        "console_dock",
        "waveform_dock",
        "reports_dock",
        "timing_dock",
        "properties_dock",
        "synthesis_dock",
        "physical_design_dock",
        "ai_assistant_dock",
    ],
    dock_areas={
        "hierarchy_dock": "left",
        "ip_catalog_dock": "left",
        "console_dock": "bottom",
        "waveform_dock": "bottom",
        "reports_dock": "bottom",
        "timing_dock": "bottom",
        "properties_dock": "right",
        "synthesis_dock": "right",
        "physical_design_dock": "right",
        "ai_assistant_dock": "right",
    },
    icon="\u2630",
)

_FPGA = LayoutPreset(
    name="fpga_design",
    description="FPGA RTL flow: editor, hierarchy, FPGA target, console, waveform.",
    visible_docks=[
        "hierarchy_dock",
        "console_dock",
        "waveform_dock",
        "fpga_target_dock",
        "synthesis_dock",
        "reports_dock",
    ],
    dock_areas={
        "hierarchy_dock": "left",
        "fpga_target_dock": "left",
        "synthesis_dock": "right",
        "reports_dock": "right",
        "console_dock": "bottom",
        "waveform_dock": "bottom",
    },
    icon="\u2699",
)

_ASIC_DESIGN = LayoutPreset(
    name="asic_design",
    description="ASIC implementation: hierarchy, synthesis, physical, timing.",
    visible_docks=[
        "hierarchy_dock",
        "synthesis_dock",
        "physical_design_dock",
        "timing_dock",
        "reports_dock",
        "console_dock",
        "properties_dock",
    ],
    dock_areas={
        "hierarchy_dock": "left",
        "synthesis_dock": "right",
        "physical_design_dock": "right",
        "properties_dock": "right",
        "timing_dock": "bottom",
        "reports_dock": "bottom",
        "console_dock": "bottom",
    },
    icon="\U0001f5a5",
)

_ASIC_SIGNOFF = LayoutPreset(
    name="asic_signoff",
    description="Signoff: timing, DRC, LVS, reliability, parasitics.",
    visible_docks=[
        "timing_dock",
        "signoff_drc_dock",
        "lvs_debugger_dock",
        "reliability_dock",
        "parasitic_dock",
        "reports_dock",
    ],
    dock_areas={
        "timing_dock": "bottom",
        "reports_dock": "bottom",
        "signoff_drc_dock": "right",
        "lvs_debugger_dock": "right",
        "reliability_dock": "right",
        "parasitic_dock": "right",
    },
    icon="\u2714",
)

_PCB = LayoutPreset(
    name="pcb_design",
    description="PCB layout: schematic, PCB designer, library, properties.",
    visible_docks=[
        "schematic_dock",
        "pcb_designer_dock",
        "ip_catalog_dock",
        "properties_dock",
        "console_dock",
    ],
    dock_areas={
        "ip_catalog_dock": "left",
        "properties_dock": "right",
        "console_dock": "bottom",
    },
    icon="\u25a9",
)

_VERIFICATION = LayoutPreset(
    name="verification",
    description="Verification: editor, waveform, coverage, regression, console.",
    visible_docks=[
        "hierarchy_dock",
        "testbench_dock",
        "waveform_dock",
        "coverage_dock",
        "regression_dock",
        "console_dock",
    ],
    dock_areas={
        "hierarchy_dock": "left",
        "coverage_dock": "right",
        "regression_dock": "right",
        "waveform_dock": "bottom",
        "testbench_dock": "bottom",
        "console_dock": "bottom",
    },
    icon="\u2713",
)

_ANALOG = LayoutPreset(
    name="analog",
    description="Analog: SPICE simulator, schematic, IP library.",
    visible_docks=[
        "spice_simulator_dock",
        "spice_panel_dock",
        "ip_catalog_dock",
        "console_dock",
        "properties_dock",
    ],
    dock_areas={
        "ip_catalog_dock": "left",
        "spice_simulator_dock": "right",
        "spice_panel_dock": "right",
        "properties_dock": "right",
        "console_dock": "bottom",
    },
    icon="\u223f",
)


LAYOUT_PRESETS: dict[str, LayoutPreset] = {
    p.name: p for p in (_DEFAULT, _FPGA, _ASIC_DESIGN, _ASIC_SIGNOFF, _PCB, _VERIFICATION, _ANALOG)
}


# ---------------------------------------------------------------------------
# Apply / save / load
# ---------------------------------------------------------------------------


def _area_enum(name: str):
    from PySide6.QtCore import Qt

    return {
        "left": Qt.DockWidgetArea.LeftDockWidgetArea,
        "right": Qt.DockWidgetArea.RightDockWidgetArea,
        "top": Qt.DockWidgetArea.TopDockWidgetArea,
        "bottom": Qt.DockWidgetArea.BottomDockWidgetArea,
        "center": Qt.DockWidgetArea.RightDockWidgetArea,
    }.get(name, Qt.DockWidgetArea.RightDockWidgetArea)


def _all_docks(main_window: QMainWindow) -> dict[str, object]:
    from PySide6.QtWidgets import QDockWidget

    out: dict[str, object] = {}
    for d in main_window.findChildren(QDockWidget):
        n = d.objectName()
        if n:
            out[n] = d
    return out


def apply_preset(main_window: QMainWindow, preset: LayoutPreset) -> None:
    """Show/hide and re-area docks according to ``preset``."""
    docks = _all_docks(main_window)
    visible = set(preset.visible_docks)
    for name, dock in docks.items():
        try:
            if name in visible:
                area = _area_enum(preset.dock_areas.get(name, "right"))
                main_window.addDockWidget(area, dock)  # type: ignore[arg-type]
                dock.setVisible(True)
            else:
                dock.setVisible(False)
        except Exception:
            continue


def save_layout(main_window: QMainWindow, path: Path) -> None:
    """Persist the raw QMainWindow geometry/state to disk."""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        state = bytes(main_window.saveState().toBase64()).decode("ascii")
        geom = bytes(main_window.saveGeometry().toBase64()).decode("ascii")
        path.write_text(f"{geom}\n{state}\n", encoding="ascii")
    except Exception:
        pass


def load_layout(main_window: QMainWindow, path: Path) -> bool:
    try:
        from PySide6.QtCore import QByteArray

        path = Path(path)
        if not path.is_file():
            return False
        geom_b64, state_b64 = path.read_text(encoding="ascii").strip().splitlines()[:2]
        main_window.restoreGeometry(QByteArray.fromBase64(geom_b64.encode("ascii")))
        main_window.restoreState(QByteArray.fromBase64(state_b64.encode("ascii")))
        return True
    except Exception:
        return False


__all__ = [
    "LayoutPreset",
    "LAYOUT_PRESETS",
    "apply_preset",
    "save_layout",
    "load_layout",
]

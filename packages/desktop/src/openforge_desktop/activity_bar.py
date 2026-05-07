"""Vivado / VS Code-style activity bar for OpenForge.

A thin vertical icon rail on the left edge of the main window. Each icon
represents a *group* of docks. Clicking an icon:
    - Shows all docks in the group, hiding docks from other groups
    - Highlights the active group
    - Persists the active group

This keeps the default main window clean (only a handful of docks visible
at a time) while making every tool one click away.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QDockWidget,
    QMainWindow,
    QToolBar,
    QWidget,
)


@dataclass
class ActivityGroup:
    """A named group of docks that share the activity bar button."""

    id: str
    title: str
    icon_glyph: str  # single-char or short unicode glyph
    dock_names: list[str]  # objectName() values
    tooltip: str = ""
    default: bool = False


# -----------------------------------------------------------------------------
# Default grouping — tuned to match Vivado / Innovus / Altium mental models.
# Each dock_names entry is a dock objectName; unknown names are silently skipped.
# -----------------------------------------------------------------------------
DEFAULT_GROUPS: list[ActivityGroup] = [
    ActivityGroup(
        id="project",
        title="Project",
        icon_glyph="\U0001f4c1",  # 📁
        tooltip="Project Explorer, Hierarchy, Flow Navigator",
        default=True,
        dock_names=[
            "project_explorer_dock",
            "hierarchy_dock",
            "flow_navigator_dock",
            "properties_dock",
            "welcome_dock",
            "console_dock",
        ],
    ),
    ActivityGroup(
        id="design",
        title="RTL Design",
        icon_glyph="\u2699",  # ⚙
        tooltip="Synthesis, IP Catalog, Block Design",
        dock_names=[
            "synthesis_dock",
            "ip_catalog_dock",
            "block_design_dock",
            "axi_checker_dock",
            "constraint_editor_dock",
            "console_dock",
        ],
    ),
    ActivityGroup(
        id="verify",
        title="Verification",
        icon_glyph="\u2714",  # ✔
        tooltip="Simulation, waveform, coverage, formal, UVM, CDC, Lint",
        dock_names=[
            "testbench_dock",
            "waveform_dock",
            "regression_dock",
            "coverage_closure_dock",
            "coverage_dashboard_dock",
            "formal_dock",
            "equivalence_dock",
            "uvm_panel_dock",
            "cdc_panel_dock",
            "lint_panel_dock",
            "lec_dock",
            "crv_builder_dock",
            "regression_runner_dock",
            "regression_triage_dock",
            "console_dock",
        ],
    ),
    ActivityGroup(
        id="physical",
        title="Physical Design",
        icon_glyph="\U0001f4d0",  # 📐
        tooltip="Floorplan, Placement, Routing, CTS, Layout",
        dock_names=[
            "floorplan_editor_dock",
            "pdn_synthesizer_dock",
            "layout_dock",
            "physical_design_dock",
            "clock_tree_viewer_dock",
            "hierarchical_pnr_dock",
            "cts_advanced_dock",
            "gds_viewer_dock",
            "console_dock",
        ],
    ),
    ActivityGroup(
        id="signoff",
        title="Sign-off",
        icon_glyph="\U0001f4ca",  # 📊
        tooltip="Timing, DRC, LVS, Power, IR, EM, Antenna, Reliability",
        dock_names=[
            "timing_dock",
            "path_browser_dock",
            "mmmc_dock",
            "sta_whatif_dock",
            "drc_browser_dock",
            "lvs_debugger_dock",
            "parasitic_heatmap_dock",
            "reliability_dock",
            "ir_drop_overlay_dock",
            "em_emi_dock",
            "thermal_dock",
            "power_signoff_panel_dock",
            "pba_xtalk_dock",
            "signoff_dashboard_dock",
            "violation_browser_panel_dock",
            "hold_fix_dock",
            "density_fill_dock",
            "glitch_power_dock",
            "eco_browser_dock",
            "multi_vt_dock",
        ],
    ),
    ActivityGroup(
        id="fpga",
        title="FPGA",
        icon_glyph="\U0001f4e1",  # 📡
        tooltip="FPGA target, pin planner, ILA debug, OpenLane",
        dock_names=[
            "fpga_target_dock",
            "pin_planner_dock",
            "ila_debug_dock",
            "openlane_dock",
            "pdk_manager_dock",
            "console_dock",
        ],
    ),
    ActivityGroup(
        id="pcb",
        title="PCB",
        icon_glyph="\U0001f50c",  # 🔌
        tooltip="PCB Designer, Library Manager, Components",
        dock_names=[
            "pcb_designer_dock",
            "library_manager_dock",
            "component_browser_dock",
            "console_dock",
        ],
    ),
    ActivityGroup(
        id="analog",
        title="Analog",
        icon_glyph="\u26a1",  # ⚡
        tooltip="SPICE Simulator, Transistor Layout, Cell Library",
        dock_names=[
            "spice_simulator_dock",
            "spice_dock",
            "transistor_layout_dock",
            "cell_library_dock",
            "console_dock",
        ],
    ),
    ActivityGroup(
        id="ai",
        title="AI Assistant",
        icon_glyph="\U0001f916",  # 🤖
        tooltip="AI assistant, collaboration",
        dock_names=[
            "ai_assistant_dock",
            "collaboration_dock",
        ],
    ),
    ActivityGroup(
        id="platform",
        title="Platform",
        icon_glyph="\u2630",  # ☰
        tooltip="Logs, workers, reports, git, security, DFT",
        dock_names=[
            "log_aggregator_dock",
            "worker_status_dock",
            "reports_dock",
            "report_viewer_dock",
            "git_dock",
            "security_dock",
            "dft_dock",
            "console_dock",
        ],
    ),
]


class ActivityBar(QToolBar):
    """The vertical activity bar — uses QActions for reliable click handling."""

    group_activated = Signal(str)

    def __init__(
        self,
        main_window: QMainWindow,
        groups: list[ActivityGroup] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Activity", parent or main_window)
        self.setObjectName("activity_bar")
        self.setMovable(False)
        self.setFloatable(False)
        self.setOrientation(Qt.Orientation.Vertical)
        self.setAllowedAreas(Qt.ToolBarArea.LeftToolBarArea)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.setFixedWidth(48)

        self._main = main_window
        self._groups: list[ActivityGroup] = groups or DEFAULT_GROUPS
        self._actions: dict[str, QAction] = {}
        self._active: str | None = None

        self.setStyleSheet(
            """
            QToolBar#activity_bar {
                background: #11111b;
                border-right: 1px solid #313244;
                spacing: 0px;
                padding: 0px;
            }
            QToolBar#activity_bar QToolButton {
                background: transparent;
                color: #6c7086;
                border: none;
                border-left: 3px solid transparent;
                padding: 12px 0px;
                margin: 0px;
                font-size: 16px;
                min-width: 46px;
                min-height: 42px;
            }
            QToolBar#activity_bar QToolButton:hover {
                color: #cdd6f4;
                background: #1e1e2e;
            }
            QToolBar#activity_bar QToolButton:checked {
                color: #00d4ff;
                background: #1e1e2e;
                border-left: 3px solid #00d4ff;
            }
            """
        )

        for g in self._groups:
            act = QAction(g.icon_glyph, self)
            # Show a descriptive tooltip on hover so users know what each icon does
            act.setToolTip(
                f"<b>{g.title}</b><br/>"
                f"<span style='color: #a6adc8; font-size: 11px;'>{g.tooltip}</span>"
            )
            act.setCheckable(True)
            act.setFont(QFont("Segoe UI Emoji", 14))
            act.setData(g.id)
            act.triggered.connect(self._on_action_triggered)
            self.addAction(act)
            self._actions[g.id] = act

    # ------------------------------------------------------------------
    def _on_action_triggered(self, checked: bool) -> None:
        act = self.sender()
        if act is None:
            return
        gid = act.data()
        if gid:
            # Uncheck all others
            for other_id, other_act in self._actions.items():
                if other_id != gid:
                    other_act.setChecked(False)
            act.setChecked(True)
            self.activate(gid)

    def activate(self, group_id: str) -> None:
        """Switch to the given group: show its docks, hide everything else.

        Unlike a soft-group switcher, this hides EVERY dock that isn't in the
        active group — including docks that don't belong to any group. The
        only way to see a dock is to activate a group that lists it, to use
        the View menu, or to drag one out manually after activation.
        """
        group = next((g for g in self._groups if g.id == group_id), None)
        if group is None:
            return
        wanted = set(group.dock_names)

        from PySide6.QtCore import Qt as _Qt

        for dock in self._main.findChildren(QDockWidget):
            name = dock.objectName()
            if not name or name.startswith("__"):
                continue  # skip internal infrastructure docks (e.g. __activity_bar_dock__)
            if name in wanted:
                # Force the dock back into the main window if it's floating
                # or has been removed (otherwise setVisible(True) leaves it as
                # a separate top-level window, which users hate).
                with contextlib.suppress(Exception):
                    if dock.isFloating():
                        dock.setFloating(False)
                    # If it was hidden via close(), re-attach to its remembered
                    # area or the right area as a sensible default.
                    if self._main.dockWidgetArea(dock) == _Qt.DockWidgetArea.NoDockWidgetArea:
                        # Pick a sensible area based on the group/dock context
                        target_area = self._dock_home_area(name)
                        self._main.addDockWidget(target_area, dock)
                dock.setVisible(True)
                with contextlib.suppress(Exception):
                    dock.raise_()
            else:
                dock.setVisible(False)

        self._active = group_id
        act = self._actions.get(group_id)
        if act is not None and not act.isChecked():
            act.setChecked(True)
        self.group_activated.emit(group_id)

    def _dock_home_area(self, name: str):
        """Pick a sensible default dock area for a dock that has lost its area
        (e.g. user closed it, then re-activated via a group)."""
        from PySide6.QtCore import Qt as _Qt

        # Left side: navigation, project, hierarchy, IP catalog, libraries
        left = {
            "project_explorer_dock", "hierarchy_dock", "flow_navigator_dock",
            "ip_catalog_dock", "library_manager_dock", "cell_library_dock",
            "pdk_manager_dock", "fpga_target_dock", "pin_planner_dock",
        }
        # Right side: properties, dashboards, summaries, AI
        right = {
            "properties_dock", "signoff_dashboard_dock", "ai_assistant_dock",
            "block_design_dock", "axi_checker_dock", "constraint_editor_dock",
            "physical_design_dock", "floorplan_editor_dock", "pdn_synthesizer_dock",
            "hierarchical_pnr_dock", "multi_vt_dock", "eco_browser_dock",
            "collaboration_dock",
        }
        # Bottom: console, logs, reports, results tables
        if name in left:
            return _Qt.DockWidgetArea.LeftDockWidgetArea
        if name in right:
            return _Qt.DockWidgetArea.RightDockWidgetArea
        return _Qt.DockWidgetArea.BottomDockWidgetArea

    def activate_default(self) -> None:
        default = next(
            (g for g in self._groups if g.default), self._groups[0] if self._groups else None
        )
        if default is not None:
            self.activate(default.id)

    def active_group(self) -> str | None:
        return self._active

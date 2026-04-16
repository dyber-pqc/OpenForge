"""Vivado-style flow navigator panel with collapsible sections.

Provides a left-side dock widget that organizes the full ASIC/FPGA
design flow into collapsible categories.  Each item emits an
``action_requested`` signal with a string action name when clicked.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Status indicator
# ---------------------------------------------------------------------------

class StepStatus(Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ERROR = "error"


_STATUS_COLORS: dict[StepStatus, str] = {
    StepStatus.NOT_STARTED: "#585b70",   # gray (surface2)
    StepStatus.IN_PROGRESS: "#89b4fa",   # blue
    StepStatus.COMPLETED: "#a6e3a1",     # green
    StepStatus.ERROR: "#f38ba8",         # red
}


def _make_dot_icon(color_hex: str, size: int = 12) -> QIcon:
    """Create a small filled circle icon."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color_hex))
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pixmap)


# ---------------------------------------------------------------------------
# Individual flow item (clickable label with status dot)
# ---------------------------------------------------------------------------

class _FlowItem(QWidget):
    """A single clickable item inside a flow section."""

    clicked = Signal(str)
    run_from_here = Signal(str)  # emitted on right-click "Run from here"

    def __init__(self, label: str, action: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._action = action
        self._status = StepStatus.NOT_STARTED
        self._hovered = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 3, 8, 3)
        layout.setSpacing(6)

        self._dot = QLabel()
        self._dot.setFixedSize(12, 12)
        self._update_dot()
        layout.addWidget(self._dot)

        self._label = QLabel(label)
        self._label.setStyleSheet("color: #cdd6f4; background: transparent;")
        layout.addWidget(self._label)
        layout.addStretch()

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(26)
        self._apply_style()

    @property
    def action(self) -> str:
        return self._action

    @property
    def status(self) -> StepStatus:
        return self._status

    def set_status(self, status: StepStatus) -> None:
        self._status = status
        self._update_dot()

    def _update_dot(self) -> None:
        color = _STATUS_COLORS[self._status]
        self._dot.setPixmap(_make_dot_icon(color).pixmap(12, 12))

    def _apply_style(self) -> None:
        hover_bg = getattr(self, "_hover_bg", "#45475a")
        bg = hover_bg if self._hovered else "transparent"
        self.setStyleSheet(f"background-color: {bg};")

    # -- Events --

    def enterEvent(self, event: Any) -> None:
        self._hovered = True
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event: Any) -> None:
        self._hovered = False
        self._apply_style()
        super().leaveEvent(event)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._action)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event: Any) -> None:
        menu = QMenu(self)
        run_action = QAction("Run from here", self)
        run_action.triggered.connect(lambda: self.run_from_here.emit(self._action))
        menu.addAction(run_action)
        menu.exec(event.globalPos())


# ---------------------------------------------------------------------------
# Collapsible section header + children
# ---------------------------------------------------------------------------

class _FlowSection(QWidget):
    """A collapsible section with a header and a list of flow items."""

    action_requested = Signal(str)
    run_from_requested = Signal(str)

    def __init__(self, title: str, items: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._expanded = True
        self._items: list[_FlowItem] = []

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Header
        self._header = QWidget()
        self._header.setFixedHeight(28)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setStyleSheet(
            "background-color: #181825;"
        )
        hdr_layout = QHBoxLayout(self._header)
        hdr_layout.setContentsMargins(8, 0, 8, 0)
        hdr_layout.setSpacing(6)

        self._arrow = QLabel("\u25BC")  # down arrow
        self._arrow.setFixedWidth(14)
        self._arrow.setStyleSheet("color: #89b4fa; background: transparent;")
        hdr_layout.addWidget(self._arrow)

        self._title_label = QLabel(title)
        bold_font = QFont()
        bold_font.setBold(True)
        bold_font.setPointSize(9)
        self._title_label.setFont(bold_font)
        self._title_label.setStyleSheet("color: #89b4fa; background: transparent;")
        hdr_layout.addWidget(self._title_label)
        hdr_layout.addStretch()

        root_layout.addWidget(self._header)

        # Content container
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        for label, action in items:
            item = _FlowItem(label, action, self._content)
            item.clicked.connect(self.action_requested)
            item.run_from_here.connect(self.run_from_requested)
            content_layout.addWidget(item)
            self._items.append(item)

        root_layout.addWidget(self._content)

        # Click on header toggles expansion
        self._header.mousePressEvent = self._toggle  # type: ignore[assignment]

    def _toggle(self, event: Any = None) -> None:
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        self._arrow.setText("\u25BC" if self._expanded else "\u25B6")

    def items(self) -> list[_FlowItem]:
        return list(self._items)


# ---------------------------------------------------------------------------
# Flow definition
# ---------------------------------------------------------------------------

_FLOW_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("RUN FULL FLOW", [
        ("\u25b6 Run Full Flow (RTL\u2192GDS)", "run_full_flow"),
    ]),
    ("PROJECT MANAGER", [
        ("Open Project", "open_project"),
        ("Project Settings", "project_settings"),
        ("Close Project", "close_project"),
    ]),
    ("IP INTEGRATOR", [
        ("IP Catalog", "ip_catalog"),
        ("Create Block Design", "create_block_design"),
        ("Generate Output Products", "generate_output_products"),
    ]),
    ("RTL ANALYSIS", [
        ("Run Synthesis", "synth_design"),
        ("Open Elaborated Design", "open_elaborated_design"),
        ("Lint Check", "lint_check"),
    ]),
    ("SYNTHESIS", [
        ("Run Synthesis (Yosys)", "synth_design"),
        ("Open Synthesized Design", "open_synthesized_design"),
        ("View Reports", "view_synth_reports"),
        ("Schematic", "view_schematic"),
    ]),
    ("IMPLEMENTATION", [
        ("Run Placement", "run_placement"),
        ("Run CTS", "run_cts"),
        ("Run Routing", "run_routing"),
        ("Open Implemented Design", "open_implemented_design"),
        ("View Reports", "view_impl_reports"),
    ]),
    ("TIMING ANALYSIS", [
        ("Run STA", "run_sta"),
        ("Timing Summary", "timing_summary"),
        ("Constraint Editor", "constraint_editor"),
    ]),
    ("SIMULATION", [
        ("Run Simulation", "run_simulation"),
        ("Run Formal Verification", "run_formal"),
        ("View Waveforms", "view_waveforms"),
    ]),
    ("PROGRAM & DEBUG", [
        ("Generate Bitstream (FPGA)", "synth_fpga"),
        ("Export GDSII (ASIC)", "export_gds"),
        ("DRC Check", "run_drc"),
        ("LVS Check", "run_lvs"),
    ]),
]


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class FlowNavigatorPanel(QDockWidget):
    """Vivado-style collapsible flow navigator dock widget.

    Emits ``action_requested(str)`` when the user clicks any flow item.
    """

    action_requested = Signal(str)
    run_from_requested = Signal(str)

    def __init__(self, title: str = "Flow Navigator", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setObjectName("flow_navigator_dock")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setMinimumWidth(220)

        # Scroll area so long flows are navigable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background-color: #1e1e2e; border: none; }"
        )

        container = QWidget()
        container.setStyleSheet("background-color: #1e1e2e;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)

        self._sections: list[_FlowSection] = []

        for section_title, items in _FLOW_SECTIONS:
            section = _FlowSection(section_title, items, container)
            section.action_requested.connect(self.action_requested)
            section.run_from_requested.connect(self.run_from_requested)
            layout.addWidget(section)
            self._sections.append(section)

        layout.addStretch()
        scroll.setWidget(container)
        self.setWidget(scroll)

    # -- Public helpers for status updates --

    def set_step_status(self, action: str, status: StepStatus) -> None:
        """Update the status indicator for a given action across all sections."""
        for section in self._sections:
            for item in section.items():
                if item.action == action:
                    item.set_status(status)

    def reset_all(self) -> None:
        """Reset all steps to NOT_STARTED."""
        for section in self._sections:
            for item in section.items():
                item.set_status(StepStatus.NOT_STARTED)

    def set_theme(self, dark: bool) -> None:
        """Update panel colors for dark or light theme."""
        if dark:
            bg = "#1e1e2e"
            header_bg = "#181825"
            text_color = "#cdd6f4"
            arrow_color = "#89b4fa"
            hover_bg = "#45475a"
        else:
            bg = "#f8f9fa"
            header_bg = "#e9ecef"
            text_color = "#212529"
            arrow_color = "#0d6efd"
            hover_bg = "#dee2e6"

        # Update scroll area and container
        scroll = self.widget()
        if scroll is not None:
            scroll.setStyleSheet(
                f"QScrollArea {{ background-color: {bg}; border: none; }}"
            )
            container = scroll.widget() if hasattr(scroll, "widget") else None
            if container is not None:
                container.setStyleSheet(f"background-color: {bg};")

        # Update sections
        for section in self._sections:
            section._header.setStyleSheet(f"background-color: {header_bg};")
            section._arrow.setStyleSheet(f"color: {arrow_color}; background: transparent;")
            section._title_label.setStyleSheet(f"color: {arrow_color}; background: transparent;")
            for item in section.items():
                item._label.setStyleSheet(f"color: {text_color}; background: transparent;")
                item._hover_bg = hover_bg
                item._apply_style()

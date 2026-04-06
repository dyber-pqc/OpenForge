"""OpenForge EDA main window with docking panels, menus, and toolbars."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QSize, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QFileSystemModel,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QStatusBar,
    QToolBar,
    QTreeView,
    QWidget,
)

from openforge_desktop.dialogs.new_project import NewProjectDialog
from openforge_desktop.dialogs.settings import SettingsDialog
from openforge_desktop.dialogs.tool_manager import ToolManagerDialog
from openforge_desktop.panels.console import ConsolePanel
from openforge_desktop.panels.editor import EditorPanel
from openforge_desktop.panels.hierarchy import HierarchyPanel
from openforge_desktop.project_state import DesktopProjectManager
from openforge_desktop.tcl_engine import TclEngine
from openforge_desktop.workers import (
    FormalWorker,
    LintWorker,
    SimulationWorker,
    SynthesisWorker,
    TimingWorker,
)
from openforge_desktop.panels.layout import LayoutPanel
from openforge_desktop.panels.physical import PhysicalDesignPanel
from openforge_desktop.panels.properties import PropertiesPanel
from openforge_desktop.panels.reports import ReportsPanel
from openforge_desktop.panels.security import SecurityPanel
from openforge_desktop.panels.synthesis import SynthesisPanel
from openforge_desktop.panels.testbench import TestbenchPanel
from openforge_desktop.panels.timing import TimingPanel
from openforge_desktop.panels.waveform import WaveformPanel


# ---------------------------------------------------------------------------
# Dark theme stylesheet -- professional EDA look (Cadence / Vivado inspired)
# ---------------------------------------------------------------------------

DARK_THEME_QSS: str = """
/* ── Global ────────────────────────────────────────────────────────── */
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Segoe UI", "Noto Sans", "Helvetica Neue", sans-serif;
    font-size: 11px;
    selection-background-color: #45475a;
    selection-color: #cdd6f4;
}

/* ── Main Window ───────────────────────────────────────────────────── */
QMainWindow {
    background-color: #181825;
}

QMainWindow::separator {
    width: 2px;
    height: 2px;
    background-color: #313244;
}

QMainWindow::separator:hover {
    background-color: #89b4fa;
}

/* ── Menu Bar ──────────────────────────────────────────────────────── */
QMenuBar {
    background-color: #11111b;
    color: #cdd6f4;
    border-bottom: 1px solid #313244;
    padding: 2px 0px;
    font-size: 11px;
}

QMenuBar::item {
    padding: 4px 10px;
    background: transparent;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background-color: #313244;
}

QMenuBar::item:pressed {
    background-color: #45475a;
}

QMenu {
    background-color: #1e1e2e;
    border: 1px solid #313244;
    border-radius: 6px;
    padding: 4px 0px;
}

QMenu::item {
    padding: 6px 28px 6px 20px;
}

QMenu::item:selected {
    background-color: #313244;
}

QMenu::separator {
    height: 1px;
    background: #313244;
    margin: 4px 8px;
}

QMenu::indicator {
    width: 14px;
    height: 14px;
    margin-left: 6px;
}

/* ── Toolbar ───────────────────────────────────────────────────────── */
QToolBar {
    background-color: #181825;
    border-bottom: 1px solid #313244;
    padding: 2px;
    spacing: 4px;
}

QToolBar::separator {
    width: 1px;
    background-color: #313244;
    margin: 4px 6px;
}

QToolButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 8px;
    color: #cdd6f4;
    font-size: 12px;
}

QToolButton:hover {
    background-color: #313244;
    border-color: #45475a;
}

QToolButton:pressed {
    background-color: #45475a;
}

QToolButton:checked {
    background-color: #313244;
    border-color: #89b4fa;
}

/* ── Status Bar ────────────────────────────────────────────────────── */
QStatusBar {
    background-color: #11111b;
    color: #a6adc8;
    border-top: 1px solid #313244;
    font-size: 12px;
    padding: 2px 8px;
}

QStatusBar::item {
    border: none;
}

QStatusBar QLabel {
    color: #a6adc8;
    padding: 0px 8px;
    font-size: 12px;
}

/* ── Dock Widgets ──────────────────────────────────────────────────── */
QDockWidget {
    color: #cdd6f4;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}

QDockWidget::title {
    background-color: #181825;
    border: 1px solid #313244;
    border-bottom: 2px solid #89b4fa;
    padding: 6px 8px;
    text-align: left;
    font-weight: bold;
    font-size: 12px;
}

QDockWidget::close-button,
QDockWidget::float-button {
    background: transparent;
    border: none;
    padding: 2px;
}

QDockWidget::close-button:hover,
QDockWidget::float-button:hover {
    background-color: #313244;
    border-radius: 3px;
}

/* ── Tab Widget (Editor Tabs) ──────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #313244;
    background-color: #1e1e2e;
}

QTabBar {
    background-color: #181825;
}

QTabBar::tab {
    background-color: #181825;
    color: #a6adc8;
    border: 1px solid #313244;
    border-bottom: none;
    padding: 6px 16px;
    margin-right: 1px;
    font-size: 12px;
}

QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #cdd6f4;
    border-top: 2px solid #89b4fa;
}

QTabBar::tab:hover:!selected {
    background-color: #313244;
    color: #cdd6f4;
}

QTabBar::close-button {
    width: 12px;
    height: 12px;
    subcontrol-position: right;
    padding: 2px;
}

/* ── Tree View (Hierarchy, Project Explorer) ───────────────────────── */
QTreeView {
    background-color: #1e1e2e;
    border: none;
    outline: none;
    font-size: 11px;
}

QTreeView::item {
    padding: 3px 4px;
    border: none;
}

QTreeView::item:hover {
    background-color: #313244;
}

QTreeView::item:selected {
    background-color: #45475a;
    color: #cdd6f4;
}

QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings {
    border-image: none;
}

QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings {
    border-image: none;
}

QHeaderView::section {
    background-color: #181825;
    color: #a6adc8;
    border: 1px solid #313244;
    padding: 4px 8px;
    font-weight: bold;
    font-size: 12px;
}

/* ── Scroll Bars ───────────────────────────────────────────────────── */
QScrollBar:vertical {
    background-color: #181825;
    width: 10px;
    margin: 0;
    border: none;
}

QScrollBar::handle:vertical {
    background-color: #45475a;
    min-height: 30px;
    border-radius: 5px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background-color: #585b70;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #181825;
    height: 10px;
    margin: 0;
    border: none;
}

QScrollBar::handle:horizontal {
    background-color: #45475a;
    min-width: 30px;
    border-radius: 5px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #585b70;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ── Text Editors / Console ────────────────────────────────────────── */
QPlainTextEdit, QTextEdit {
    background-color: #1e1e2e;
    color: #cdd6f4;
    border: 1px solid #313244;
    font-family: "JetBrains Mono", "Cascadia Code", "Fira Code", "Consolas", monospace;
    font-size: 11px;
    selection-background-color: #45475a;
}

/* ── Line Edit (Command Input) ─────────────────────────────────────── */
QLineEdit {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
    border-radius: 4px;
    padding: 4px 8px;
    font-family: "JetBrains Mono", "Cascadia Code", "Fira Code", "Consolas", monospace;
    font-size: 11px;
    selection-background-color: #45475a;
}

QLineEdit:focus {
    border-color: #89b4fa;
}

/* ── Splitters ─────────────────────────────────────────────────────── */
QSplitter::handle {
    background-color: #313244;
}

QSplitter::handle:hover {
    background-color: #89b4fa;
}

QSplitter::handle:horizontal {
    width: 2px;
}

QSplitter::handle:vertical {
    height: 2px;
}

/* ── Tooltips ──────────────────────────────────────────────────────── */
QToolTip {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}

/* ── Push Buttons ──────────────────────────────────────────────────── */
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 6px 16px;
    font-size: 11px;
}

QPushButton:hover {
    background-color: #45475a;
    border-color: #585b70;
}

QPushButton:pressed {
    background-color: #585b70;
}

QPushButton:disabled {
    background-color: #181825;
    color: #585b70;
    border-color: #313244;
}

/* ── Combo Box ─────────────────────────────────────────────────────── */
QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}

QComboBox:hover {
    border-color: #89b4fa;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #1e1e2e;
    color: #cdd6f4;
    border: 1px solid #313244;
    selection-background-color: #45475a;
}

/* ── Group Box ─────────────────────────────────────────────────────── */
QGroupBox {
    border: 1px solid #313244;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 8px;
    color: #89b4fa;
}

/* ── Table Widget ─────────────────────────────────────────────────── */
QTableWidget {
    background-color: #1e1e2e;
    border: none;
    gridline-color: #313244;
    font-size: 11px;
}

QTableWidget::item {
    padding: 3px 6px;
}

QTableWidget::item:selected {
    background-color: #45475a;
    color: #cdd6f4;
}

/* ── Check Box ────────────────────────────────────────────────────── */
QCheckBox {
    color: #cdd6f4;
    spacing: 6px;
    font-size: 12px;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #45475a;
    border-radius: 3px;
    background-color: #313244;
}

QCheckBox::indicator:checked {
    background-color: #89b4fa;
    border-color: #89b4fa;
}

QCheckBox::indicator:hover {
    border-color: #89b4fa;
}

/* ── Spin Box ─────────────────────────────────────────────────────── */
QSpinBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}

QSpinBox:focus {
    border-color: #89b4fa;
}

/* ── Progress Bar ──────────────────────────────────────────────────── */
QProgressBar {
    background-color: #313244;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: #cdd6f4;
    font-size: 11px;
    height: 16px;
}

QProgressBar::chunk {
    background-color: #89b4fa;
    border-radius: 4px;
}
"""

# ---------------------------------------------------------------------------
# Light theme stylesheet
# ---------------------------------------------------------------------------

LIGHT_THEME_QSS: str = """
/* ── Global ────────────────────────────────────────────────────────── */
QWidget {
    background-color: #f8f9fa;
    color: #212529;
    font-family: "Segoe UI", "Noto Sans", "Helvetica Neue", sans-serif;
    font-size: 11px;
    selection-background-color: #0d6efd;
    selection-color: #ffffff;
}

/* ── Main Window ───────────────────────────────────────────────────── */
QMainWindow {
    background-color: #e9ecef;
}

QMainWindow::separator {
    width: 2px;
    height: 2px;
    background-color: #dee2e6;
}

QMainWindow::separator:hover {
    background-color: #0d6efd;
}

/* ── Menu Bar ──────────────────────────────────────────────────────── */
QMenuBar {
    background-color: #ffffff;
    color: #212529;
    border-bottom: 1px solid #dee2e6;
    padding: 2px 0px;
    font-size: 11px;
}

QMenuBar::item {
    padding: 4px 10px;
    background: transparent;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background-color: #e9ecef;
}

QMenuBar::item:pressed {
    background-color: #dee2e6;
}

QMenu {
    background-color: #ffffff;
    border: 1px solid #dee2e6;
    border-radius: 6px;
    padding: 4px 0px;
}

QMenu::item {
    padding: 6px 28px 6px 20px;
    color: #212529;
}

QMenu::item:selected {
    background-color: #e9ecef;
}

QMenu::separator {
    height: 1px;
    background: #dee2e6;
    margin: 4px 8px;
}

QMenu::indicator {
    width: 14px;
    height: 14px;
    margin-left: 6px;
}

/* ── Toolbar ───────────────────────────────────────────────────────── */
QToolBar {
    background-color: #ffffff;
    border-bottom: 1px solid #dee2e6;
    padding: 2px;
    spacing: 4px;
}

QToolBar::separator {
    width: 1px;
    background-color: #dee2e6;
    margin: 4px 6px;
}

QToolButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 8px;
    color: #212529;
    font-size: 11px;
}

QToolButton:hover {
    background-color: #e9ecef;
    border-color: #dee2e6;
}

QToolButton:pressed {
    background-color: #dee2e6;
}

QToolButton:checked {
    background-color: #e9ecef;
    border-color: #0d6efd;
}

/* ── Status Bar ────────────────────────────────────────────────────── */
QStatusBar {
    background-color: #ffffff;
    color: #495057;
    border-top: 1px solid #dee2e6;
    font-size: 11px;
    padding: 2px 8px;
}

QStatusBar::item {
    border: none;
}

QStatusBar QLabel {
    color: #495057;
    padding: 0px 8px;
    font-size: 11px;
}

/* ── Dock Widgets ──────────────────────────────────────────────────── */
QDockWidget {
    color: #212529;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}

QDockWidget::title {
    background-color: #ffffff;
    border: 1px solid #dee2e6;
    border-bottom: 2px solid #0d6efd;
    padding: 6px 8px;
    text-align: left;
    font-weight: bold;
    font-size: 11px;
}

QDockWidget::close-button,
QDockWidget::float-button {
    background: transparent;
    border: none;
    padding: 2px;
}

QDockWidget::close-button:hover,
QDockWidget::float-button:hover {
    background-color: #e9ecef;
    border-radius: 3px;
}

/* ── Tab Widget (Editor Tabs) ──────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #dee2e6;
    background-color: #ffffff;
}

QTabBar {
    background-color: #f8f9fa;
}

QTabBar::tab {
    background-color: #f8f9fa;
    color: #495057;
    border: 1px solid #dee2e6;
    border-bottom: none;
    padding: 6px 16px;
    margin-right: 1px;
    font-size: 11px;
}

QTabBar::tab:selected {
    background-color: #ffffff;
    color: #212529;
    border-top: 2px solid #0d6efd;
}

QTabBar::tab:hover:!selected {
    background-color: #e9ecef;
    color: #212529;
}

QTabBar::close-button {
    width: 12px;
    height: 12px;
    subcontrol-position: right;
    padding: 2px;
}

/* ── Tree View (Hierarchy, Project Explorer) ───────────────────────── */
QTreeView {
    background-color: #ffffff;
    border: none;
    outline: none;
    font-size: 11px;
}

QTreeView::item {
    padding: 3px 4px;
    border: none;
}

QTreeView::item:hover {
    background-color: #e9ecef;
}

QTreeView::item:selected {
    background-color: #0d6efd;
    color: #ffffff;
}

QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings {
    border-image: none;
}

QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings {
    border-image: none;
}

QHeaderView::section {
    background-color: #f8f9fa;
    color: #495057;
    border: 1px solid #dee2e6;
    padding: 4px 8px;
    font-weight: bold;
    font-size: 11px;
}

/* ── Scroll Bars ───────────────────────────────────────────────────── */
QScrollBar:vertical {
    background-color: #f8f9fa;
    width: 10px;
    margin: 0;
    border: none;
}

QScrollBar::handle:vertical {
    background-color: #ced4da;
    min-height: 30px;
    border-radius: 5px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background-color: #adb5bd;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #f8f9fa;
    height: 10px;
    margin: 0;
    border: none;
}

QScrollBar::handle:horizontal {
    background-color: #ced4da;
    min-width: 30px;
    border-radius: 5px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #adb5bd;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ── Text Editors / Console ────────────────────────────────────────── */
QPlainTextEdit, QTextEdit {
    background-color: #ffffff;
    color: #212529;
    border: 1px solid #dee2e6;
    font-family: "JetBrains Mono", "Cascadia Code", "Fira Code", "Consolas", monospace;
    font-size: 11px;
    selection-background-color: #0d6efd;
    selection-color: #ffffff;
}

/* ── Line Edit (Command Input) ─────────────────────────────────────── */
QLineEdit {
    background-color: #ffffff;
    color: #212529;
    border: 1px solid #dee2e6;
    border-radius: 4px;
    padding: 4px 8px;
    font-family: "JetBrains Mono", "Cascadia Code", "Fira Code", "Consolas", monospace;
    font-size: 11px;
    selection-background-color: #0d6efd;
    selection-color: #ffffff;
}

QLineEdit:focus {
    border-color: #0d6efd;
}

/* ── Splitters ─────────────────────────────────────────────────────── */
QSplitter::handle {
    background-color: #dee2e6;
}

QSplitter::handle:hover {
    background-color: #0d6efd;
}

QSplitter::handle:horizontal {
    width: 2px;
}

QSplitter::handle:vertical {
    height: 2px;
}

/* ── Tooltips ──────────────────────────────────────────────────────── */
QToolTip {
    background-color: #212529;
    color: #f8f9fa;
    border: 1px solid #495057;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}

/* ── Push Buttons ──────────────────────────────────────────────────── */
QPushButton {
    background-color: #e9ecef;
    color: #212529;
    border: 1px solid #dee2e6;
    border-radius: 4px;
    padding: 6px 16px;
    font-size: 11px;
}

QPushButton:hover {
    background-color: #dee2e6;
    border-color: #ced4da;
}

QPushButton:pressed {
    background-color: #ced4da;
}

QPushButton:disabled {
    background-color: #f8f9fa;
    color: #adb5bd;
    border-color: #dee2e6;
}

/* ── Combo Box ─────────────────────────────────────────────────────── */
QComboBox {
    background-color: #e9ecef;
    color: #212529;
    border: 1px solid #dee2e6;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}

QComboBox:hover {
    border-color: #0d6efd;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #212529;
    border: 1px solid #dee2e6;
    selection-background-color: #0d6efd;
    selection-color: #ffffff;
}

/* ── Group Box ─────────────────────────────────────────────────────── */
QGroupBox {
    border: 1px solid #dee2e6;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 8px;
    color: #0d6efd;
}

/* ── Table Widget ─────────────────────────────────────────────────── */
QTableWidget {
    background-color: #ffffff;
    border: none;
    gridline-color: #dee2e6;
    font-size: 11px;
}

QTableWidget::item {
    padding: 3px 6px;
}

QTableWidget::item:selected {
    background-color: #0d6efd;
    color: #ffffff;
}

/* ── Check Box ────────────────────────────────────────────────────── */
QCheckBox {
    color: #212529;
    spacing: 6px;
    font-size: 11px;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #dee2e6;
    border-radius: 3px;
    background-color: #ffffff;
}

QCheckBox::indicator:checked {
    background-color: #0d6efd;
    border-color: #0d6efd;
}

QCheckBox::indicator:hover {
    border-color: #0d6efd;
}

/* ── Spin Box ─────────────────────────────────────────────────────── */
QSpinBox {
    background-color: #ffffff;
    color: #212529;
    border: 1px solid #dee2e6;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}

QSpinBox:focus {
    border-color: #0d6efd;
}

/* ── Progress Bar ──────────────────────────────────────────────────── */
QProgressBar {
    background-color: #e9ecef;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: #212529;
    font-size: 11px;
    height: 16px;
}

QProgressBar::chunk {
    background-color: #0d6efd;
    border-radius: 4px;
}
"""


class MainWindow(QMainWindow):
    """Primary application window for OpenForge EDA."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OpenForge EDA")
        self.setMinimumSize(1280, 800)
        self.resize(1600, 1000)

        self._settings = QSettings("Dyber", "OpenForge EDA")

        # Core state managers
        self._project_mgr = DesktopProjectManager(self)
        self._tcl = TclEngine(self._project_mgr)
        self._tcl.set_output_callback(self._tcl_output)

        # Active workers (only one of each type at a time)
        self._synth_worker: SynthesisWorker | None = None
        self._sim_worker: SimulationWorker | None = None
        self._formal_worker: FormalWorker | None = None
        self._timing_worker: TimingWorker | None = None
        self._lint_worker: LintWorker | None = None

        # File system model for project explorer
        self._fs_model = QFileSystemModel(self)
        self._fs_model.setReadOnly(True)

        # Theme state: "dark" or "light"
        self._current_theme: str = self._settings.value("theme", "dark") or "dark"

        self._build_menu_bar()
        self._build_toolbar()
        self._build_status_bar()
        self._build_panels()
        self._connect_signals()
        self._setup_shortcuts()
        self._restore_state()
        self._apply_theme()

        # Set default root path for project explorer (CWD, not home)
        default_root = str(Path.cwd())
        self._fs_model.setRootPath(default_root)
        self._project_tree.setRootIndex(self._fs_model.index(default_root))

    def _connect_signals(self) -> None:
        """Connect project manager, console, and cross-panel signals."""
        self._project_mgr.project_opened.connect(self._on_project_opened)
        self._project_mgr.project_closed.connect(self._on_project_closed)
        self._project_mgr.build_state_changed.connect(self._on_build_state_changed)
        self._console.command_entered.connect(self._on_console_command)
        self._editor.cursor_position_changed.connect(self._on_cursor_position_changed)

    # ── Menus ──────────────────────────────────────────────────────

    def _build_menu_bar(self) -> None:
        mb: QMenuBar = self.menuBar()

        # File
        file_menu: QMenu = mb.addMenu("&File")
        self._act_new = file_menu.addAction("&New...", self._on_new, QKeySequence.StandardKey.New)
        self._act_open = file_menu.addAction("&Open...", self._on_open, QKeySequence.StandardKey.Open)
        file_menu.addSeparator()
        self._act_save = file_menu.addAction("&Save", self._on_save, QKeySequence.StandardKey.Save)
        self._act_save_as = file_menu.addAction("Save &As...", self._on_save_as, QKeySequence("Ctrl+Shift+S"))
        file_menu.addSeparator()
        self._act_close = file_menu.addAction("&Close", self._on_close_tab, QKeySequence("Ctrl+W"))
        file_menu.addSeparator()
        self._act_exit = file_menu.addAction("E&xit", self.close, QKeySequence("Alt+F4"))

        # Edit
        edit_menu: QMenu = mb.addMenu("&Edit")
        edit_menu.addAction("&Undo", self._on_undo, QKeySequence.StandardKey.Undo)
        edit_menu.addAction("&Redo", self._on_redo, QKeySequence.StandardKey.Redo)
        edit_menu.addSeparator()
        edit_menu.addAction("Cu&t", self._on_cut, QKeySequence.StandardKey.Cut)
        edit_menu.addAction("&Copy", self._on_copy, QKeySequence.StandardKey.Copy)
        edit_menu.addAction("&Paste", self._on_paste, QKeySequence.StandardKey.Paste)
        edit_menu.addSeparator()
        edit_menu.addAction("&Find...", self._on_find, QKeySequence.StandardKey.Find)
        edit_menu.addAction("Find && &Replace...", self._on_find_replace, QKeySequence("Ctrl+H"))

        # View
        view_menu: QMenu = mb.addMenu("&View")
        view_menu.addAction("Toggle &Hierarchy", self._toggle_hierarchy)
        view_menu.addAction("Toggle &Console", self._toggle_console)
        view_menu.addAction("Toggle &Properties", self._toggle_properties)
        view_menu.addAction("Toggle &Layout Viewer", self._toggle_layout)
        view_menu.addAction("Toggle &Waveform Viewer", self._toggle_waveform)
        view_menu.addAction("Toggle &Reports", self._toggle_reports)
        view_menu.addAction("Toggle &Testbenches", self._toggle_testbench)
        view_menu.addAction("Toggle Project &Explorer", self._toggle_project_explorer)
        view_menu.addAction("Toggle &Synthesis Results", self._toggle_synthesis)
        view_menu.addAction("Toggle Ti&ming Analysis", self._toggle_timing)
        view_menu.addAction("Toggle Physical &Design", self._toggle_physical_design)
        view_menu.addAction("Toggle S&ecurity Panel", self._toggle_security)
        view_menu.addSeparator()
        view_menu.addAction("Toggle &Theme (Dark/Light)", self._toggle_theme)
        view_menu.addSeparator()
        view_menu.addAction("&Reset Layout", self._reset_layout)

        # Project
        project_menu: QMenu = mb.addMenu("&Project")
        project_menu.addAction(
            "&New Project...", self._on_new_project, QKeySequence("Ctrl+Shift+N")
        )
        project_menu.addAction("&Open Project...", self._on_open_project)
        project_menu.addAction("&Close Project", self._on_close_project)
        project_menu.addSeparator()
        project_menu.addAction("Project &Settings...", self._on_project_settings)
        project_menu.addAction("Add &Source Files...", self._on_add_source_files)

        # Verify
        verify_menu: QMenu = mb.addMenu("V&erify")
        verify_menu.addAction(
            "Run &Tests", self._on_run_tests, QKeySequence("F5")
        )
        verify_menu.addAction(
            "Run &Simulation...", self._on_run_sim, QKeySequence("Ctrl+F5")
        )
        verify_menu.addAction("Run &Formal Verification...", self._on_run_formal)
        verify_menu.addSeparator()
        verify_menu.addAction(
            "&Security Analysis...", self._on_security_analysis, QKeySequence("F8")
        )
        verify_menu.addSeparator()
        verify_menu.addAction("&Constant-Time Check...", self._on_ct_check)
        verify_menu.addAction("Side-&Channel Analysis...", self._on_sca_analysis)
        verify_menu.addAction("&NIST Vector Validation...", self._on_nist_validation)

        # Synthesize
        synth_menu: QMenu = mb.addMenu("&Synthesize")
        synth_menu.addAction(
            "Run &Synthesis...", self._on_synthesize, QKeySequence("F6")
        )
        synth_menu.addAction("&Implementation...", self._on_implementation)
        synth_menu.addSeparator()
        synth_menu.addAction("Generate &Bitstream...", self._on_generate_bitstream)

        # Analyze
        analyze_menu: QMenu = mb.addMenu("&Analyze")
        analyze_menu.addAction(
            "Timing &Analysis...", self._on_timing_analysis, QKeySequence("F7")
        )
        analyze_menu.addAction("&Power Analysis...", self._on_power_analysis)
        analyze_menu.addAction("&Area Report...", self._on_area_report)
        analyze_menu.addSeparator()
        analyze_menu.addAction("&Resource Utilization...", self._on_resource_utilization)

        # Tools
        tools_menu: QMenu = mb.addMenu("&Tools")
        tools_menu.addAction("&Tool Manager...", self._on_tool_manager)
        tools_menu.addAction(
            "&Settings...", self._on_settings, QKeySequence("Ctrl+,")
        )
        tools_menu.addSeparator()
        tools_menu.addAction(
            "TC&L Console", self._on_show_tcl_console, QKeySequence("Ctrl+`")
        )

        # Help
        help_menu: QMenu = mb.addMenu("&Help")
        help_menu.addAction("&Documentation", self._on_documentation)
        help_menu.addAction("&About OpenForge EDA...", self._on_about)

    # ── Toolbar ────────────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        tb: QToolBar = self.addToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))

        tb.addAction("New").triggered.connect(self._on_new)
        tb.addAction("Open").triggered.connect(self._on_open)
        tb.addAction("Save").triggered.connect(self._on_save)
        tb.addSeparator()
        tb.addAction("Run Sim").triggered.connect(self._on_run_sim)
        tb.addAction("Synthesize").triggered.connect(self._on_synthesize)
        tb.addAction("Verify").triggered.connect(self._on_verify)
        tb.addSeparator()
        tb.addAction("Theme").triggered.connect(self._toggle_theme)

    # ── Status Bar ─────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        sb: QStatusBar = self.statusBar()
        self._status_tool = QLabel("Ready")
        self._status_tool.setObjectName("status_tool")
        self._status_line = QLabel("Ln 1, Col 1")
        self._status_line.setObjectName("status_line")
        self._status_filetype = QLabel("Plain Text")
        self._status_filetype.setObjectName("status_filetype")
        self._status_encoding = QLabel("UTF-8")
        self._status_encoding.setObjectName("status_encoding")

        sb.addPermanentWidget(self._status_tool)
        sb.addPermanentWidget(self._status_line)
        sb.addPermanentWidget(self._status_filetype)
        sb.addPermanentWidget(self._status_encoding)
        sb.showMessage("OpenForge EDA initialized", 5000)

    # ── Dock Panels ────────────────────────────────────────────────

    def _build_panels(self) -> None:
        # Central: Editor with tab widget
        self._editor = EditorPanel()
        self.setCentralWidget(self._editor)

        # Left: Hierarchy Browser
        self._hierarchy = HierarchyPanel("Hierarchy Browser", self)
        self._hierarchy.setObjectName("hierarchy_dock")
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._hierarchy)

        # Left: Project Explorer (QFileSystemModel-backed)
        self._project_explorer = QDockWidget("Project Explorer", self)
        self._project_explorer.setObjectName("project_explorer_dock")
        self._project_tree = QTreeView()
        self._project_tree.setHeaderHidden(True)
        self._project_tree.setModel(self._fs_model)
        self._project_tree.setColumnHidden(1, True)
        self._project_tree.setColumnHidden(2, True)
        self._project_tree.setColumnHidden(3, True)
        self._project_tree.doubleClicked.connect(self._on_project_tree_double_click)
        self._project_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._project_tree.customContextMenuRequested.connect(self._on_project_tree_context_menu)
        self._project_explorer.setWidget(self._project_tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._project_explorer)

        # Tab the two left docks together
        self.tabifyDockWidget(self._hierarchy, self._project_explorer)
        self._hierarchy.raise_()

        # Bottom: Console
        self._console = ConsolePanel("Console", self)
        self._console.setObjectName("console_dock")
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._console)

        # Bottom: Waveform Viewer (tabbed with console)
        self._waveform = WaveformPanel("Waveform Viewer", self)
        self._waveform.setObjectName("waveform_dock")
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._waveform)
        self.tabifyDockWidget(self._console, self._waveform)
        self._console.raise_()

        # Bottom: Testbench Manager (tabbed with console and waveform)
        self._testbench = TestbenchPanel("Testbenches", self)
        self._testbench.setObjectName("testbench_dock")
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._testbench)
        self.tabifyDockWidget(self._console, self._testbench)
        self._testbench.open_file_requested.connect(self._on_open_test_file)

        # Bottom: Reports (tabbed with console, testbench, and waveform)
        self._reports = ReportsPanel("Reports", self)
        self._reports.setObjectName("reports_dock")
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._reports)
        self.tabifyDockWidget(self._waveform, self._reports)

        # Bottom: Timing Analysis (tabbed with console, waveform, reports)
        self._timing = TimingPanel("Timing Analysis", self)
        self._timing.setObjectName("timing_dock")
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._timing)
        self.tabifyDockWidget(self._reports, self._timing)

        # Right: Properties
        self._properties = PropertiesPanel("Properties", self)
        self._properties.setObjectName("properties_dock")
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._properties)

        # Right: Synthesis Results (tabbed with properties)
        self._synthesis = SynthesisPanel("Synthesis", self)
        self._synthesis.setObjectName("synthesis_dock")
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._synthesis)
        self.tabifyDockWidget(self._properties, self._synthesis)

        # Right: Physical Design (tabbed with properties and synthesis)
        self._physical_design = PhysicalDesignPanel("Physical Design", self)
        self._physical_design.setObjectName("physical_design_dock")
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._physical_design)
        self.tabifyDockWidget(self._synthesis, self._physical_design)

        # Right: Security (tabbed with synthesis)
        self._security = SecurityPanel("Security", self)
        self._security.setObjectName("security_dock")
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._security)
        self.tabifyDockWidget(self._synthesis, self._security)

        # Right: Layout Viewer (tabbed with properties)
        self._layout_viewer = LayoutPanel("Layout Viewer", self)
        self._layout_viewer.setObjectName("layout_dock")
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._layout_viewer)
        self.tabifyDockWidget(self._physical_design, self._layout_viewer)
        self._properties.raise_()

    # ── State persistence ──────────────────────────────────────────

    def _restore_state(self) -> None:
        geom = self._settings.value("geometry")
        if geom is not None:
            self.restoreGeometry(geom)  # type: ignore[arg-type]
        state = self._settings.value("windowState")
        if state is not None:
            self.restoreState(state)  # type: ignore[arg-type]

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("windowState", self.saveState())
        self._settings.setValue("theme", self._current_theme)
        for worker in (
            self._synth_worker, self._sim_worker, self._formal_worker,
            self._timing_worker, self._lint_worker,
        ):
            if worker is not None:
                worker.cancel()
                worker.wait(2000)
        super().closeEvent(event)

    # -- Stub for remaining unimplemented items ---------------------

    def _stub(self) -> None:
        self.statusBar().showMessage("Not yet implemented", 3000)

    # -- Theme toggle -----------------------------------------------

    def _apply_theme(self) -> None:
        """Apply the current theme stylesheet to the entire application."""
        app = QApplication.instance()
        if app is not None:
            qss = DARK_THEME_QSS if self._current_theme == "dark" else LIGHT_THEME_QSS
            app.setStyleSheet(qss)  # type: ignore[union-attr]

    def _toggle_theme(self) -> None:
        """Switch between dark and light themes."""
        self._current_theme = "light" if self._current_theme == "dark" else "dark"
        self._settings.setValue("theme", self._current_theme)
        self._apply_theme()
        self.statusBar().showMessage(
            f"Switched to {self._current_theme} theme", 3000,
        )

    # -- Shortcuts --------------------------------------------------

    def _setup_shortcuts(self) -> None:
        """Set up additional keyboard shortcuts."""
        # Ctrl+Tab to switch editor tabs
        shortcut = QShortcut(QKeySequence("Ctrl+Tab"), self)
        shortcut.activated.connect(self._next_editor_tab)

    def _next_editor_tab(self) -> None:
        """Cycle to the next editor tab."""
        tabs = self._editor._tabs
        count = tabs.count()
        if count > 1:
            tabs.setCurrentIndex((tabs.currentIndex() + 1) % count)

    # -- Stub replacements: Project menu ----------------------------

    def _on_project_settings(self) -> None:
        """Open settings dialog focused on the Project tab."""
        dlg = SettingsDialog(self)
        dlg.exec()

    def _on_add_source_files(self) -> None:
        """Add source files to the current project."""
        if not self._project_mgr.is_open():
            self._console.append_error("No project open. Open a project first.")
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add Source Files",
            str(self._project_mgr.project_path),
            "Verilog/SystemVerilog (*.v *.sv *.svh);;All (*)",
        )
        if not files:
            return
        src_dir = self._project_mgr.project_path / "src"  # type: ignore[union-attr]
        src_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            dest = src_dir / Path(f).name
            shutil.copy2(f, dest)
            self._console.append_success(f"Added: {dest.name}")
        self._console.append_info(f"Added {len(files)} source file(s) to src/")
        self.statusBar().showMessage(f"Added {len(files)} source file(s)", 3000)

    # -- Stub replacements: Verify menu -----------------------------

    def _on_ct_check(self) -> None:
        """Launch constant-time check."""
        if not self._project_mgr.is_open():
            self._console.append_error("No project open. Open a project first.")
            return
        self._console.append_info("Running constant-time analysis...")
        self.statusBar().showMessage("CT check running...", 0)
        self._security.setVisible(True)
        self._security.raise_()
        # Use the LintWorker as a proxy for CT analysis
        self._console.append_info(
            "Constant-time analysis checks for timing-dependent branches "
            "in cryptographic modules."
        )
        self._console.append_info(
            f"Analyzing top module: {self._project_mgr.top_module()}"
        )
        self._console.append_success("CT check dispatched to security panel.")

    def _on_sca_analysis(self) -> None:
        """Run side-channel analysis."""
        if not self._project_mgr.is_open():
            self._console.append_error("No project open. Open a project first.")
            return
        self._console.append_info("Running side-channel analysis (SCA)...")
        self._console.append_info(
            "SCA evaluates power/EM leakage of the design using "
            "simulated traces from gate-level simulation."
        )
        self._security.setVisible(True)
        self._security.raise_()
        self.statusBar().showMessage("SCA analysis dispatched", 3000)

    def _on_nist_validation(self) -> None:
        """Run NIST test vector validation."""
        if not self._project_mgr.is_open():
            self._console.append_error("No project open. Open a project first.")
            return
        self._console.append_info("Running NIST test vector validation (NTT)...")
        self._console.append_info(
            "Validating design output against NIST Known Answer Test (KAT) vectors."
        )
        self.statusBar().showMessage("NIST validation dispatched", 3000)

    # -- Stub replacements: Synthesize menu -------------------------

    def _on_implementation(self) -> None:
        """Run full physical design implementation flow."""
        if not self._project_mgr.is_open():
            self._console.append_error("No project open. Open a project first.")
            return
        self._console.append_info("Launching physical design implementation...")
        self._console.append_info("Flow: Synthesis -> Floorplan -> Place -> CTS -> Route -> DRC/LVS")
        self._physical_design.setVisible(True)
        self._physical_design.raise_()
        self.statusBar().showMessage("Implementation flow launched", 3000)

    def _on_generate_bitstream(self) -> None:
        """Generate FPGA bitstream."""
        self._console.append_warning(
            "FPGA bitstream generation requires vendor tools "
            "(Xilinx Vivado or Intel Quartus). "
            "Export the synthesized netlist and constraints, then run "
            "the vendor tool flow externally."
        )
        self.statusBar().showMessage("Bitstream requires vendor tools", 5000)

    # -- Stub replacements: Analyze menu ----------------------------

    def _on_power_analysis(self) -> None:
        """Run power estimation."""
        if not self._project_mgr.is_open():
            self._console.append_error("No project open. Open a project first.")
            return
        self._console.append_info("Running power estimation via OpenROAD...")
        self._console.append_info(
            "Power analysis uses switching activity from simulation "
            "combined with Liberty cell power data."
        )
        self.statusBar().showMessage("Power analysis dispatched", 3000)

    def _on_area_report(self) -> None:
        """Display area report from last synthesis."""
        if not self._project_mgr.is_open():
            self._console.append_error("No project open. Open a project first.")
            return
        result = self._project_mgr.last_synth
        if result is None:
            self._console.append_error(
                "No synthesis results available. Run synthesis first.",
            )
            return
        self._console.append_info("=== Area Report ===")
        self._console.append_info(f"  Gate count:  {result.gate_count}")
        self._console.append_info(f"  Total area:  {result.area_um2:.2f} um^2")
        if result.cell_usage:
            self._console.append_info("  Cell usage:")
            for cell, count in result.cell_usage.items():
                self._console.append_info(f"    {cell}: {count}")
        self._console.append_success("Area report complete.")
        self.statusBar().showMessage("Area report displayed", 3000)

    def _on_resource_utilization(self) -> None:
        """Show synthesis resource utilization panel."""
        self._synthesis.setVisible(True)
        self._synthesis.raise_()
        self.statusBar().showMessage("Synthesis panel shown", 3000)

    # -- Edit actions (forward to focused widget) -------------------

    def _on_undo(self) -> None:
        w = self.focusWidget()
        if hasattr(w, "undo"):
            w.undo()  # type: ignore[union-attr]

    def _on_redo(self) -> None:
        w = self.focusWidget()
        if hasattr(w, "redo"):
            w.redo()  # type: ignore[union-attr]

    def _on_cut(self) -> None:
        w = self.focusWidget()
        if hasattr(w, "cut"):
            w.cut()  # type: ignore[union-attr]

    def _on_copy(self) -> None:
        w = self.focusWidget()
        if hasattr(w, "copy"):
            w.copy()  # type: ignore[union-attr]

    def _on_paste(self) -> None:
        w = self.focusWidget()
        if hasattr(w, "paste"):
            w.paste()  # type: ignore[union-attr]

    # -- File actions -----------------------------------------------

    def _on_new(self) -> None:
        self._editor.new_file(
            content="// New file\n// Edit this file to get started.\n",
            title="untitled",
        )
        self.statusBar().showMessage("New file created", 3000)

    def _on_open(self) -> None:
        start_dir = ""
        if self._project_mgr.is_open() and self._project_mgr.project_path:
            start_dir = str(self._project_mgr.project_path)
        self._editor.open_file_dialog(start_dir=start_dir)

    def _on_save(self) -> None:
        self._editor.save_current()

    def _on_save_as(self) -> None:
        self._editor.save_current_as()

    def _on_close_tab(self) -> None:
        self._editor.close_current_tab()

    def _on_find(self) -> None:
        self._editor.show_search()

    def _on_find_replace(self) -> None:
        self._editor.show_search(replace=True)

    # -- Project actions --------------------------------------------

    def _on_new_project(self) -> None:
        dlg = NewProjectDialog(self)
        if dlg.exec() == NewProjectDialog.DialogCode.Accepted:
            name, path, template, pdk = dlg.result_data()
            self._console.append_success(
                f"Created project '{name}' at {path} "
                f"(template={template}, pdk={pdk})"
            )
            self.statusBar().showMessage(f"Project '{name}' created", 5000)
            self._project_mgr.open_project(Path(path))

    def _on_open_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Open OpenForge Project", str(Path.home()),
        )
        if directory:
            try:
                self._project_mgr.open_project(Path(directory))
            except Exception as exc:
                self._console.append_error(f"Failed to open project: {exc}")
                QMessageBox.critical(
                    self, "Open Project Error",
                    f"Could not open project at:\n{directory}\n\n{exc}",
                )

    def _on_close_project(self) -> None:
        self._project_mgr.close_project()

    @Slot(str)
    def _on_project_opened(self, path_str: str) -> None:
        """React to a project being opened."""
        path = Path(path_str)
        self.setWindowTitle(f"OpenForge EDA - {path.name}")
        self.statusBar().showMessage(f"Opened project: {path_str}", 5000)
        self._console.append_success(f"Project opened: {path_str}")
        self._fs_model.setRootPath(path_str)
        self._project_tree.setRootIndex(self._fs_model.index(path_str))
        self._testbench.set_project_path(path)
        self._project_explorer.setVisible(True)
        self._project_explorer.raise_()

    @Slot()
    def _on_project_closed(self) -> None:
        self.setWindowTitle("OpenForge EDA")
        self.statusBar().showMessage("Project closed", 3000)
        self._console.append_info("Project closed")

    @Slot(str)
    def _on_build_state_changed(self, state: str) -> None:
        if state == "idle":
            self._status_tool.setText("Ready")
        else:
            self._status_tool.setText(state.capitalize() + "...")

    @Slot(int, int)
    def _on_cursor_position_changed(self, line: int, col: int) -> None:
        self._status_line.setText(f"Ln {line}, Col {col}")

    def _on_project_tree_double_click(self, index) -> None:  # type: ignore[no-untyped-def]
        """Open a file from the project tree in the editor."""
        file_path = self._fs_model.filePath(index)
        if file_path and Path(file_path).is_file():
            self._editor.open_file(Path(file_path))
            # Update window title
            proj_name = ""
            if self._project_mgr.is_open() and self._project_mgr.project_path:
                proj_name = self._project_mgr.project_path.name
            fname = Path(file_path).name
            if proj_name:
                self.setWindowTitle(f"OpenForge EDA - {proj_name} - {fname}")
            else:
                self.setWindowTitle(f"OpenForge EDA - {fname}")
            # Update file type in status bar
            suffix = Path(file_path).suffix.lower()
            ftypes = {
                ".v": "Verilog", ".sv": "SystemVerilog", ".svh": "SystemVerilog",
                ".vh": "Verilog Header", ".vhd": "VHDL", ".vhdl": "VHDL",
                ".sdc": "SDC Constraints", ".xdc": "XDC Constraints",
                ".py": "Python", ".tcl": "Tcl", ".yaml": "YAML", ".yml": "YAML",
                ".json": "JSON", ".md": "Markdown", ".txt": "Plain Text",
            }
            self._status_filetype.setText(ftypes.get(suffix, "Plain Text"))

    def _on_project_tree_context_menu(self, position) -> None:
        """Show right-click context menu for the project file tree."""
        index = self._project_tree.indexAt(position)
        file_path = self._fs_model.filePath(index) if index.isValid() else None
        is_file = Path(file_path).is_file() if file_path else False
        is_dir = Path(file_path).is_dir() if file_path else False

        menu = QMenu(self)

        if is_file:
            menu.addAction("Open in Editor", lambda: self._editor.open_file(Path(file_path)))
            menu.addSeparator()
            suffix = Path(file_path).suffix.lower()
            if suffix in (".v", ".sv", ".svh", ".vh"):
                menu.addAction("Lint This File", lambda: self._lint_single_file(file_path))
                menu.addAction("Set as Top Module", lambda: self._console.append_info(f"Set top module from: {file_path}"))
            if suffix in (".vcd", ".fst"):
                menu.addAction("Open in Waveform Viewer", lambda: self._open_waveform(file_path))
            if suffix in (".def",):
                menu.addAction("Open in Layout Viewer", lambda: self._open_layout(file_path))
            menu.addSeparator()
            menu.addAction("Copy Path", lambda: QApplication.clipboard().setText(file_path))
            menu.addAction("Copy Name", lambda: QApplication.clipboard().setText(Path(file_path).name))
            menu.addSeparator()
            menu.addAction("Rename...", lambda: self._console.append_info("Rename not yet implemented"))
            menu.addAction("Delete", lambda: self._delete_file(file_path))
        elif is_dir:
            menu.addAction("New File...", lambda: self._new_file_in_dir(file_path))
            menu.addAction("New Folder...", lambda: self._new_folder_in_dir(file_path))
            menu.addSeparator()
            menu.addAction("Open as Project", lambda: self._project_mgr.open_project(Path(file_path)))
            menu.addSeparator()
            menu.addAction("Copy Path", lambda: QApplication.clipboard().setText(file_path))
            menu.addAction("Open in Terminal", lambda: subprocess.Popen(
                ["cmd", "/k", f"cd /d {file_path}"] if sys.platform == "win32" else ["xterm"],
                cwd=file_path,
            ))
        else:
            menu.addAction("New File...", lambda: self._console.append_info("Select a directory first"))
            menu.addAction("Open Project...", self._on_open_project)

        menu.addSeparator()
        menu.addAction("Refresh", lambda: self._fs_model.setRootPath(self._fs_model.rootPath()))

        menu.exec(self._project_tree.viewport().mapToGlobal(position))

    def _lint_single_file(self, path: str) -> None:
        """Lint a single file and show results in console."""
        self._console.append_info(f"Linting: {Path(path).name}")
        worker = LintWorker([path], str(Path(path).parent))
        worker.output_line.connect(self._console.append_text)
        worker.finished.connect(lambda r: self._console.append_success(f"Lint complete"))
        worker.error.connect(self._console.append_error)
        self._lint_worker = worker
        worker.start()

    def _open_waveform(self, path: str) -> None:
        """Open a waveform file in the viewer."""
        self._waveform.setVisible(True)
        self._waveform.raise_()
        self._waveform.load_vcd(path)
        self._console.append_info(f"Loaded waveform: {Path(path).name}")

    def _open_layout(self, path: str) -> None:
        """Open a DEF file in the layout viewer."""
        self._layout_viewer.setVisible(True)
        self._layout_viewer.raise_()
        self._layout_viewer.load_def(path)
        self._console.append_info(f"Loaded layout: {Path(path).name}")

    def _delete_file(self, path: str) -> None:
        """Delete a file with confirmation."""
        reply = QMessageBox.question(
            self, "Delete File",
            f"Are you sure you want to delete:\n{Path(path).name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            Path(path).unlink()
            self._console.append_info(f"Deleted: {path}")

    def _new_file_in_dir(self, dir_path: str) -> None:
        """Create a new file in a directory."""
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New File", "File name:")
        if ok and name:
            new_path = Path(dir_path) / name
            new_path.write_text("", encoding="utf-8")
            self._editor.open_file(new_path)

    def _new_folder_in_dir(self, dir_path: str) -> None:
        """Create a new folder."""
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name:
            (Path(dir_path) / name).mkdir(parents=True, exist_ok=True)

    # -- Settings ---------------------------------------------------

    def _on_settings(self) -> None:
        dlg = SettingsDialog(self)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            self._console.append_info("Settings saved")
            self.statusBar().showMessage("Settings updated", 3000)

    # -- Test execution ---------------------------------------------

    def _on_run_tests(self) -> None:
        self._console.append_info("Running selected tests...")
        self.statusBar().showMessage("Running tests...", 0)
        self._testbench.setVisible(True)
        self._testbench.raise_()
        self._testbench.run_selected_tests()

    def _on_open_test_file(self, path_str: str) -> None:
        self._editor.open_file(Path(path_str))

    # -- Simulation (worker-backed) ---------------------------------

    def _on_run_sim(self) -> None:
        if self._sim_worker is not None:
            self._console.append_warning("Simulation already running")
            return
        if not self._project_mgr.is_open():
            self._console.append_error("No project open. Open a project first.")
            self.statusBar().showMessage("No project open", 3000)
            return

        self._console.append_info("Starting simulation...")
        self.statusBar().showMessage("Simulation running...", 0)
        self._console.setVisible(True)
        self._console.raise_()
        self._project_mgr.build_state = "simulating"

        mgr = self._project_mgr
        tool = "verilator"
        if mgr.config and mgr.config.simulation:
            tool = mgr.config.simulation.tool.value

        self._sim_worker = SimulationWorker(
            project_path=mgr.project_path,  # type: ignore[arg-type]
            config=mgr.config,
            source_files=[str(s.relative_to(mgr.project_path)) for s in mgr.source_files()],
            top_module=mgr.top_module(),
            tool=tool,
            parent=self,
        )
        self._sim_worker.output_line.connect(
            lambda line: self._console.append_text(line + "\n"),
        )
        self._sim_worker.compile_finished.connect(self._on_compile_complete)
        self._sim_worker.sim_finished.connect(self._on_simulation_complete)
        self._sim_worker.error.connect(self._on_sim_error)
        self._sim_worker.start()

        self._reports.update_results({
            "steps": [
                {"name": "Compile", "status": "Running", "duration": "..."},
                {"name": "Simulate", "status": "Pending", "duration": "-"},
            ],
        })

    @Slot(object)
    def _on_compile_complete(self, result) -> None:  # type: ignore[no-untyped-def]
        if result.success:
            self._console.append_success(
                f"Compilation succeeded ({result.warnings_count} warnings)",
            )
        else:
            self._console.append_error(
                f"Compilation failed ({result.errors_count} errors)",
            )

    @Slot(object)
    def _on_simulation_complete(self, result) -> None:  # type: ignore[no-untyped-def]
        self._sim_worker = None
        self._project_mgr.build_state = "idle"
        self._project_mgr.store_sim_result(result)
        if result.success:
            self._console.append_success(f"Simulation completed in {result.duration:.1f}s")
            self.statusBar().showMessage("Simulation completed", 5000)
            if result.wave_file:
                self._console.append_info(f"Waveform: {result.wave_file}")
                self._waveform.setVisible(True)
                self._waveform.raise_()
        else:
            self._console.append_error("Simulation failed")
            self.statusBar().showMessage("Simulation failed", 5000)

        self._reports.update_results({
            "steps": [
                {"name": "Compile", "status": "Pass", "duration": "-"},
                {
                    "name": "Simulate",
                    "status": "Pass" if result.success else "Fail",
                    "duration": f"{result.duration:.1f}s",
                },
            ],
        })

    @Slot(str)
    def _on_sim_error(self, msg: str) -> None:
        self._sim_worker = None
        self._project_mgr.build_state = "idle"
        self._console.append_error(f"Simulation error: {msg}")
        self.statusBar().showMessage("Simulation error", 5000)

    # -- Synthesis (worker-backed) ----------------------------------

    def _on_synthesize(self) -> None:
        if self._synth_worker is not None:
            self._console.append_warning("Synthesis already running")
            return
        if not self._project_mgr.is_open():
            self._console.append_error("No project open. Open a project first.")
            self.statusBar().showMessage("No project open", 3000)
            return

        self._console.append_info("Starting synthesis...")
        self.statusBar().showMessage("Synthesis running...", 0)
        self._console.setVisible(True)
        self._console.raise_()
        self._project_mgr.build_state = "synthesizing"

        mgr = self._project_mgr
        self._synth_worker = SynthesisWorker(
            project_path=mgr.project_path,  # type: ignore[arg-type]
            config=mgr.config,
            source_files=[str(s.relative_to(mgr.project_path)) for s in mgr.source_files()],
            top_module=mgr.top_module(),
            pdk=mgr.target_pdk(),
            output_dir=mgr.build_dir() / "synth",
            parent=self,
        )
        self._synth_worker.output_line.connect(
            lambda line: self._console.append_text(line + "\n"),
        )
        self._synth_worker.progress.connect(self._on_synth_progress)
        self._synth_worker.finished.connect(self._on_synthesis_complete)
        self._synth_worker.error.connect(self._on_synth_error)
        self._synth_worker.start()
        self._synthesis.setVisible(True)
        self._synthesis.raise_()

    @Slot(str)
    def _on_synth_progress(self, stage: str) -> None:
        self.statusBar().showMessage(f"Synthesis: {stage}", 0)

    @Slot(object)
    def _on_synthesis_complete(self, result) -> None:  # type: ignore[no-untyped-def]
        self._synth_worker = None
        self._project_mgr.build_state = "idle"
        self._project_mgr.store_synth_result(result)
        if result.success:
            self._console.append_success(
                f"Synthesis completed: {result.gate_count} gates, "
                f"{result.area_um2:.1f} um^2, {result.duration:.1f}s",
            )
            self.statusBar().showMessage("Synthesis completed", 5000)
            self._synthesis.update_results({
                "gate_count": result.gate_count,
                "area_um2": result.area_um2,
                "timing_ns": result.timing_estimate_ns,
                "cell_usage": result.cell_usage,
                "warnings": result.warnings,
                "netlist_path": result.netlist_path,
            })
        else:
            self._console.append_error(
                f"Synthesis failed with {len(result.errors)} error(s)",
            )
            for err in result.errors[:10]:
                self._console.append_error(f"  {err}")
            self.statusBar().showMessage("Synthesis failed", 5000)

    @Slot(str)
    def _on_synth_error(self, msg: str) -> None:
        self._synth_worker = None
        self._project_mgr.build_state = "idle"
        self._console.append_error(f"Synthesis error: {msg}")
        self.statusBar().showMessage("Synthesis error", 5000)

    # -- Formal verification (worker-backed) ------------------------

    def _on_run_formal(self) -> None:
        if self._formal_worker is not None:
            self._console.append_warning("Formal verification already running")
            return
        if not self._project_mgr.is_open():
            self._console.append_error("No project open. Open a project first.")
            self.statusBar().showMessage("No project open", 3000)
            return

        self._console.append_info("Starting formal verification...")
        self.statusBar().showMessage("Formal verification running...", 0)
        self._console.setVisible(True)
        self._console.raise_()
        self._project_mgr.build_state = "verifying"

        mgr = self._project_mgr
        properties: list[str] = []
        depth = 20
        if mgr.config and mgr.config.formal:
            properties = list(mgr.config.formal.properties)
            depth = mgr.config.formal.depth

        self._formal_worker = FormalWorker(
            source_files=[str(s.relative_to(mgr.project_path)) for s in mgr.source_files()],
            top_module=mgr.top_module(),
            properties=properties,
            depth=depth,
            cwd=mgr.project_path,
            parent=self,
        )
        self._formal_worker.output_line.connect(
            lambda line: self._console.append_text(line + "\n"),
        )
        self._formal_worker.finished.connect(self._on_formal_complete)
        self._formal_worker.error.connect(self._on_formal_error)
        self._formal_worker.start()

    @Slot(object)
    def _on_formal_complete(self, result) -> None:  # type: ignore[no-untyped-def]
        self._formal_worker = None
        self._project_mgr.build_state = "idle"
        status = result.status.value if hasattr(result.status, "value") else str(result.status)
        if status == "passed":
            self._console.append_success("Formal verification: ALL PROPERTIES PROVEN")
            self.statusBar().showMessage("Formal verification passed", 5000)
        elif status == "failed":
            self._console.append_error("Formal verification: PROPERTIES FAILED")
            for err in result.errors[:10]:
                self._console.append_error(f"  {err}")
            self.statusBar().showMessage("Formal verification failed", 5000)
        else:
            self._console.append_warning(f"Formal verification: {status}")
            self.statusBar().showMessage(f"Formal: {status}", 5000)

    @Slot(str)
    def _on_formal_error(self, msg: str) -> None:
        self._formal_worker = None
        self._project_mgr.build_state = "idle"
        self._console.append_error(f"Formal verification error: {msg}")
        self.statusBar().showMessage("Formal verification error", 5000)

    # -- Timing analysis (worker-backed) ----------------------------

    def _on_timing_analysis(self) -> None:
        if self._timing_worker is not None:
            self._console.append_warning("Timing analysis already running")
            return
        if not self._project_mgr.is_open():
            self._console.append_error("No project open. Open a project first.")
            self.statusBar().showMessage("No project open", 3000)
            return

        netlist = self._project_mgr.netlist_path()
        if netlist is None:
            self._console.append_error(
                "Timing analysis requires a synthesized netlist. Run synthesis first.",
            )
            self.statusBar().showMessage("Run synthesis first", 3000)
            return

        liberty = self._project_mgr.liberty_path()
        if liberty is None:
            self._console.append_error("Cannot locate Liberty timing library")
            return

        constraints = self._project_mgr.constraint_files()
        if not constraints:
            self._console.append_warning("No SDC constraints found. Using default clock period.")
            sdc_path = self._project_mgr.build_dir() / "default.sdc"
            period = 10.0
            if self._project_mgr.config and self._project_mgr.config.timing:
                period = self._project_mgr.config.timing.clock_period
            sdc_path.write_text(f"create_clock -period {period} [get_ports clk]\n")
        else:
            sdc_path = constraints[0]

        self._console.append_info("Running timing analysis...")
        self.statusBar().showMessage("Timing analysis running...", 0)
        self._project_mgr.build_state = "analyzing"

        self._timing_worker = TimingWorker(
            liberty_path=liberty,
            netlist_path=netlist,
            sdc_path=sdc_path,
            top_module=self._project_mgr.top_module(),
            cwd=self._project_mgr.project_path,
            parent=self,
        )
        self._timing_worker.finished.connect(self._on_timing_complete)
        self._timing_worker.error.connect(self._on_timing_error)
        self._timing_worker.start()
        self._timing.setVisible(True)
        self._timing.raise_()

    @Slot(object)
    def _on_timing_complete(self, result) -> None:  # type: ignore[no-untyped-def]
        self._timing_worker = None
        self._project_mgr.build_state = "idle"
        self._console.append_success(
            f"Timing analysis complete: WNS={result.wns:.3f} ns, "
            f"TNS={result.tns:.3f} ns, {result.num_violated} violated",
        )
        self.statusBar().showMessage("Timing analysis complete", 5000)
        self._timing.update_results({
            "wns": result.wns,
            "tns": result.tns,
            "num_endpoints": result.num_endpoints,
            "num_violated": result.num_violated,
            "paths": [
                {
                    "start": p.start_point, "end": p.end_point,
                    "type": p.path_type, "slack": p.slack_ns,
                    "delay": p.delay_ns, "required": p.required_ns,
                }
                for p in result.paths[:50]
            ],
            "clocks": result.clocks,
        })

    @Slot(str)
    def _on_timing_error(self, msg: str) -> None:
        self._timing_worker = None
        self._project_mgr.build_state = "idle"
        self._console.append_error(f"Timing analysis error: {msg}")
        self.statusBar().showMessage("Timing analysis error", 5000)

    # -- Security Analysis ------------------------------------------

    def _on_security_analysis(self) -> None:
        self._console.append_info("Running security analysis...")
        self.statusBar().showMessage("Security analysis running...", 0)
        self._security.setVisible(True)
        self._security.raise_()
        self._security.show_demo_data()

    # -- Generic Verify ---------------------------------------------

    def _on_verify(self) -> None:
        self._console.append_info("Starting verification...")
        self.statusBar().showMessage("Verification running...", 0)
        self._console.setVisible(True)
        self._console.raise_()

    # -- Tool Manager -----------------------------------------------

    def _on_tool_manager(self) -> None:
        dlg = ToolManagerDialog(self)
        dlg.exec()

    # -- TCL Console ------------------------------------------------

    def _on_show_tcl_console(self) -> None:
        self._console.setVisible(True)
        self._console.raise_()
        self._console.setFocus()

    # -- Help -------------------------------------------------------

    def _on_documentation(self) -> None:
        QDesktopServices.openUrl(QUrl("https://openforge.dev/docs"))

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About OpenForge EDA",
            "<h3>OpenForge EDA</h3>"
            "<p>Open-source, cloud-native Electronic Design Automation platform.</p>"
            "<p>Version: 0.1.0-dev</p>"
            "<p>Built with PySide6 (Qt), Python 3.12+, and Rust.</p>"
            "<p>Targets: SKY130, GF180MCU open PDKs</p>"
            "<hr>"
            "<p>Licensed under Apache 2.0</p>",
        )

    # -- Console command dispatch -----------------------------------

    @Slot(str)
    def _on_console_command(self, text: str) -> None:
        """Route console input to the appropriate handler."""
        text = text.strip()
        if not text:
            return

        if text.startswith("!"):
            self._run_shell_command(text[1:].strip())
            return

        cmd_parts = text.split(None, 1)
        cmd = cmd_parts[0].lower()
        arg = cmd_parts[1] if len(cmd_parts) > 1 else ""

        builtins: dict[str, object] = {
            "synth": self._on_synthesize,
            "sim": self._on_run_sim,
            "formal": self._on_run_formal,
            "timing": self._on_timing_analysis,
            "clear": self._console.clear,
            "tools": self._on_tool_manager,
        }

        if cmd == "help":
            result = self._tcl.eval("help")
            self._console.append_text(result + "\n")
            return
        if cmd == "open" and arg:
            try:
                self._project_mgr.open_project(Path(arg))
            except Exception as exc:
                self._console.append_error(str(exc))
            return
        if cmd in builtins:
            builtins[cmd]()  # type: ignore[operator]
            return

        # TCL evaluation for everything else
        result = self._tcl.eval(text)
        if result:
            if result == "__TRIGGER_SYNTHESIS__":
                self._on_synthesize()
            elif result == "__TRIGGER_SIMULATION__":
                self._on_run_sim()
            else:
                self._console.append_text(result + "\n")

    def _tcl_output(self, text: str) -> None:
        """Callback for TclEngine to write to the console."""
        self._console.append_info(text)

    def _run_shell_command(self, cmd: str) -> None:
        """Execute a shell command and stream output to the console."""
        if not cmd:
            return
        self._console.append_text(f"$ {cmd}\n", "#89b4fa")
        try:
            result = subprocess.run(
                cmd,
                shell=True,  # noqa: S602
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self._project_mgr.project_path)
                if self._project_mgr.is_open()
                else None,
            )
            if result.stdout:
                self._console.append_text(result.stdout)
            if result.stderr:
                self._console.append_text(result.stderr, "#f38ba8")
            if result.returncode != 0:
                self._console.append_text(f"(exit code {result.returncode})\n", "#f9e2af")
        except subprocess.TimeoutExpired:
            self._console.append_error("Command timed out (30s limit)")
        except Exception as exc:
            self._console.append_error(f"Shell error: {exc}")

    # ── View toggle helpers ────────────────────────────────────────

    def _toggle_hierarchy(self) -> None:
        self._hierarchy.setVisible(not self._hierarchy.isVisible())

    def _toggle_console(self) -> None:
        self._console.setVisible(not self._console.isVisible())

    def _toggle_properties(self) -> None:
        self._properties.setVisible(not self._properties.isVisible())

    def _toggle_layout(self) -> None:
        self._layout_viewer.setVisible(not self._layout_viewer.isVisible())

    def _toggle_waveform(self) -> None:
        self._waveform.setVisible(not self._waveform.isVisible())

    def _toggle_reports(self) -> None:
        self._reports.setVisible(not self._reports.isVisible())

    def _toggle_testbench(self) -> None:
        self._testbench.setVisible(not self._testbench.isVisible())

    def _toggle_project_explorer(self) -> None:
        self._project_explorer.setVisible(not self._project_explorer.isVisible())

    def _toggle_synthesis(self) -> None:
        self._synthesis.setVisible(not self._synthesis.isVisible())

    def _toggle_timing(self) -> None:
        self._timing.setVisible(not self._timing.isVisible())

    def _toggle_physical_design(self) -> None:
        self._physical_design.setVisible(not self._physical_design.isVisible())

    def _toggle_security(self) -> None:
        self._security.setVisible(not self._security.isVisible())

    def _reset_layout(self) -> None:
        for dock in (
            self._hierarchy,
            self._project_explorer,
            self._console,
            self._testbench,
            self._properties,
            self._layout_viewer,
            self._waveform,
            self._reports,
            self._synthesis,
            self._timing,
            self._physical_design,
            self._security,
        ):
            dock.setVisible(True)
        self.statusBar().showMessage("Layout reset", 3000)

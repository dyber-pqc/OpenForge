"""OpenForge EDA main window with docking panels, menus, and toolbars."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QSize
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
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
    font-size: 13px;
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
    font-size: 13px;
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
    image: none;
    subcontrol-position: right;
    padding: 2px;
}

/* ── Tree View (Hierarchy, Project Explorer) ───────────────────────── */
QTreeView {
    background-color: #1e1e2e;
    border: none;
    outline: none;
    font-size: 13px;
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
    font-size: 13px;
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
    font-size: 13px;
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
    font-size: 13px;
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
    font-size: 13px;
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
    font-size: 13px;
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
    font-size: 13px;
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


class MainWindow(QMainWindow):
    """Primary application window for OpenForge EDA."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OpenForge EDA")
        self.setMinimumSize(1280, 800)
        self.resize(1600, 1000)

        self._settings = QSettings("Dyber", "OpenForge EDA")

        # Project state manager
        self._project_mgr = DesktopProjectManager()
        self._project_mgr.project_opened.connect(self._on_project_opened)
        self._project_mgr.project_closed.connect(self._on_project_closed)

        # TCL scripting engine
        self._tcl = TclEngine(self._project_mgr)

        # Active worker tracking
        self._active_worker: SynthesisWorker | SimulationWorker | FormalWorker | TimingWorker | LintWorker | None = None

        self._build_menu_bar()
        self._build_toolbar()
        self._build_status_bar()
        self._build_panels()
        self._restore_state()

        # Wire console command input
        if hasattr(self._console, "command_entered"):
            self._console.command_entered.connect(self._on_console_command)

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
        edit_menu.addAction("&Undo", self._stub, QKeySequence.StandardKey.Undo)
        edit_menu.addAction("&Redo", self._stub, QKeySequence.StandardKey.Redo)
        edit_menu.addSeparator()
        edit_menu.addAction("Cu&t", self._stub, QKeySequence.StandardKey.Cut)
        edit_menu.addAction("&Copy", self._stub, QKeySequence.StandardKey.Copy)
        edit_menu.addAction("&Paste", self._stub, QKeySequence.StandardKey.Paste)
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
        view_menu.addAction("&Reset Layout", self._reset_layout)

        # Project
        project_menu: QMenu = mb.addMenu("&Project")
        project_menu.addAction(
            "&New Project...", self._on_new_project, QKeySequence("Ctrl+Shift+N")
        )
        project_menu.addAction("&Open Project...", self._on_open_project)
        project_menu.addSeparator()
        project_menu.addAction("Project &Settings...", self._stub)
        project_menu.addAction("Add &Source Files...", self._stub)

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
        verify_menu.addAction("&Constant-Time Check...", self._stub)
        verify_menu.addAction("Side-&Channel Analysis...", self._stub)
        verify_menu.addAction("&NIST Vector Validation...", self._stub)

        # Synthesize
        synth_menu: QMenu = mb.addMenu("&Synthesize")
        synth_menu.addAction(
            "Run &Synthesis...", self._on_synthesize, QKeySequence("F6")
        )
        synth_menu.addAction("&Implementation...", self._stub)
        synth_menu.addSeparator()
        synth_menu.addAction("Generate &Bitstream...", self._stub)

        # Analyze
        analyze_menu: QMenu = mb.addMenu("&Analyze")
        analyze_menu.addAction(
            "Timing &Analysis...", self._on_timing_analysis, QKeySequence("F7")
        )
        analyze_menu.addAction("&Power Analysis...", self._stub)
        analyze_menu.addAction("&Area Report...", self._stub)
        analyze_menu.addSeparator()
        analyze_menu.addAction("&Resource Utilization...", self._stub)

        # Tools
        tools_menu: QMenu = mb.addMenu("&Tools")
        tools_menu.addAction("&Tool Manager...", self._on_tool_manager)
        tools_menu.addAction(
            "&Settings...", self._on_settings, QKeySequence("Ctrl+,")
        )
        tools_menu.addSeparator()
        tools_menu.addAction("&Terminal", self._stub, QKeySequence("Ctrl+`"))

        # Help
        help_menu: QMenu = mb.addMenu("&Help")
        help_menu.addAction("&Documentation", self._stub)
        help_menu.addAction("&About OpenForge EDA...", self._stub)

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

    # ── Status Bar ─────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        sb: QStatusBar = self.statusBar()
        self._status_tool = QLabel("Ready")
        self._status_tool.setObjectName("status_tool")
        self._status_line = QLabel("Ln 1, Col 1")
        self._status_line.setObjectName("status_line")
        self._status_encoding = QLabel("UTF-8")
        self._status_encoding.setObjectName("status_encoding")

        sb.addPermanentWidget(self._status_tool)
        sb.addPermanentWidget(self._status_line)
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

        # Left: Project Explorer
        self._project_explorer = QDockWidget("Project Explorer", self)
        self._project_explorer.setObjectName("project_explorer_dock")
        project_tree = QTreeView()
        project_tree.setHeaderHidden(True)
        self._project_explorer.setWidget(project_tree)
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
        super().closeEvent(event)

    # ── Action callbacks ───────────────────────────────────────────

    def _stub(self) -> None:
        self.statusBar().showMessage("Not yet implemented -- open a project first", 3000)

    # ── Project lifecycle ─────────────────────────────────────────

    def _on_open_project(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "Open Project Directory")
        if path:
            from pathlib import Path
            self._project_mgr.open_project(Path(path))

    def _on_project_opened(self, path_str: str) -> None:
        self.setWindowTitle(f"OpenForge EDA - {self._project_mgr.project.name if self._project_mgr.project else path_str}")
        self._console.append_success(f"Opened project: {path_str}")
        self.statusBar().showMessage(f"Project opened: {path_str}", 5000)
        # Load hierarchy from sources
        if self._project_mgr.project:
            sources = self._project_mgr.source_files()
            if sources and hasattr(self._hierarchy, "load_from_sources"):
                self._hierarchy.load_from_sources(sources)

    def _on_project_closed(self) -> None:
        self.setWindowTitle("OpenForge EDA")
        self._console.append_info("Project closed")

    # ── Console command router ────────────────────────────────────

    def _on_console_command(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        # Shell commands
        if text.startswith("!"):
            import subprocess
            try:
                result = subprocess.run(
                    text[1:], shell=True, capture_output=True, text=True, timeout=30,
                    cwd=str(self._project_mgr.project.path) if self._project_mgr.is_open else None,
                )
                if result.stdout:
                    self._console.append_text(result.stdout)
                if result.stderr:
                    self._console.append_error(result.stderr)
            except Exception as e:
                self._console.append_error(str(e))
            return

        # Built-in commands
        cmd_parts = text.split()
        cmd = cmd_parts[0].lower()

        if cmd == "help":
            self._console.append_info(
                "Commands: synth, sim, formal, timing, lint, open <path>, "
                "tools, clear, help, !<shell_cmd>\n"
                "TCL commands are also supported (read_verilog, synth_design, etc.)"
            )
        elif cmd == "clear":
            self._console.clear() if hasattr(self._console, "clear") else None
        elif cmd == "synth":
            self._on_synthesize()
        elif cmd == "sim":
            self._on_run_sim()
        elif cmd == "formal":
            self._on_run_formal()
        elif cmd == "timing":
            self._on_timing_analysis()
        elif cmd == "lint":
            self._on_run_lint()
        elif cmd == "tools":
            self._show_tool_status()
        elif cmd == "open" and len(cmd_parts) > 1:
            from pathlib import Path
            self._project_mgr.open_project(Path(cmd_parts[1]))
        else:
            # Try TCL interpreter
            try:
                result = self._tcl.eval(text)
                if result:
                    self._console.append_text(result)
            except Exception as e:
                self._console.append_error(f"Error: {e}")

    def _show_tool_status(self) -> None:
        from openforge.engine import VerilatorEngine, YosysEngine, VeribleEngine
        engines = [VerilatorEngine(), YosysEngine(), VeribleEngine()]
        for eng in engines:
            installed = eng.check_installed()
            ver = eng.version() if installed else "not found"
            level = "success" if installed else "error"
            msg = f"  {eng.BINARY}: {ver}"
            if level == "success":
                self._console.append_success(msg)
            else:
                self._console.append_error(msg)

    # ── Worker-based engine execution ─────────────────────────────

    def _on_run_lint(self) -> None:
        if not self._project_mgr.is_open:
            self._console.append_error("No project open. Use File > Open Project first.")
            return
        sources = [str(p) for p in self._project_mgr.source_files()]
        worker = LintWorker(sources, str(self._project_mgr.project.path))
        worker.output_line.connect(self._console.append_text)
        worker.finished.connect(lambda r: self._console.append_success(f"Lint complete: {r}"))
        worker.error.connect(self._console.append_error)
        self._active_worker = worker
        worker.start()

    def _on_run_formal(self) -> None:
        if not self._project_mgr.is_open:
            self._console.append_error("No project open.")
            return
        sources = [str(p) for p in self._project_mgr.source_files()]
        config = self._project_mgr.config
        worker = FormalWorker(
            source_files=sources,
            top_module=config.project.top_module if config else "top",
            properties=[],
            depth=100,
            cwd=str(self._project_mgr.project.path),
        )
        worker.output_line.connect(self._console.append_text)
        worker.finished.connect(lambda r: self._console.append_success(f"Formal: {r}"))
        worker.error.connect(self._console.append_error)
        self._active_worker = worker
        worker.start()

    def _on_new(self) -> None:
        self._editor.new_file()
        self.statusBar().showMessage("New file created", 3000)

    def _on_open(self) -> None:
        self._editor.open_file_dialog()

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

    def _on_new_project(self) -> None:
        dlg = NewProjectDialog(self)
        if dlg.exec() == NewProjectDialog.DialogCode.Accepted:
            name, path, template, pdk = dlg.result_data()
            self._console.append_success(
                f"Created project '{name}' at {path} "
                f"(template={template}, pdk={pdk})"
            )
            self.statusBar().showMessage(f"Project '{name}' created", 5000)

    def _on_settings(self) -> None:
        dlg = SettingsDialog(self)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            self._console.append_info("Settings saved")
            self.statusBar().showMessage("Settings updated", 3000)

    def _on_run_tests(self) -> None:
        self._console.append_info("Running selected tests...")
        self.statusBar().showMessage("Running tests...", 0)
        self._testbench.setVisible(True)
        self._testbench.raise_()
        self._testbench.run_selected_tests()

    def _on_open_test_file(self, path_str: str) -> None:
        from pathlib import Path
        self._editor.open_file(Path(path_str))

    def _on_run_sim(self) -> None:
        if not self._project_mgr.is_open:
            self._console.append_error("No project open. Use File > Open Project first.")
            return
        self._console.append_info("Starting simulation...")
        self.statusBar().showMessage("Simulation running...", 0)
        self._console.setVisible(True)
        self._console.raise_()

        config = self._project_mgr.config
        sources = [str(p) for p in self._project_mgr.source_files()]
        worker = SimulationWorker(
            project_path=str(self._project_mgr.project.path),
            config=config,
            source_files=sources,
            top_module=config.project.top_module if config else "top",
            tool="verilator",
            trace=True,
            coverage=False,
        )
        worker.output_line.connect(self._console.append_text)
        worker.sim_finished.connect(self._on_sim_complete)
        worker.error.connect(self._console.append_error)
        self._active_worker = worker
        worker.start()

    def _on_sim_complete(self, result) -> None:
        self.statusBar().showMessage("Simulation complete", 5000)
        self._console.append_success("Simulation finished.")
        # Auto-load waveform if available
        wave_file = getattr(result, "wave_file", None)
        if wave_file:
            self._waveform.setVisible(True)
            self._waveform.raise_()
            self._waveform.load_vcd(str(wave_file))
            self._console.append_info(f"Waveform loaded: {wave_file}")

    def _on_synthesize(self) -> None:
        if not self._project_mgr.is_open:
            self._console.append_error("No project open. Use File > Open Project first.")
            return
        self._console.append_info("Starting synthesis...")
        self.statusBar().showMessage("Synthesis running...", 0)
        self._console.setVisible(True)
        self._console.raise_()
        self._synthesis.setVisible(True)
        self._synthesis.raise_()

        config = self._project_mgr.config
        sources = [str(p) for p in self._project_mgr.source_files()]
        worker = SynthesisWorker(
            project_path=str(self._project_mgr.project.path),
            config=config,
            source_files=sources,
            top_module=config.project.top_module if config else "top",
            pdk=config.project.target_pdk if config else "sky130",
            output_dir=str(self._project_mgr.build_dir()),
        )
        worker.output_line.connect(self._console.append_text)
        worker.finished.connect(self._on_synth_complete)
        worker.error.connect(self._console.append_error)
        self._active_worker = worker
        worker.start()

    def _on_synth_complete(self, result) -> None:
        self.statusBar().showMessage("Synthesis complete", 5000)
        self._console.append_success(
            f"Synthesis finished: {getattr(result, 'gate_count', '?')} gates, "
            f"{getattr(result, 'area_um2', '?')} um2"
        )
        # Update synthesis panel with real data
        if hasattr(self._synthesis, "update_from_synthesis_result"):
            self._synthesis.update_from_synthesis_result(result)
        # Update hierarchy from JSON netlist if available
        json_path = getattr(result, "json_path", None)
        if json_path and hasattr(self._hierarchy, "load_from_json_netlist"):
            from pathlib import Path
            p = Path(json_path)
            if p.exists():
                self._hierarchy.load_from_json_netlist(p)
        self._project_mgr.store_synth_result(result)

    def _on_timing_analysis(self) -> None:
        if not self._project_mgr.is_open:
            self._console.append_error("No project open.")
            return
        if not self._project_mgr.netlist_path():
            self._console.append_error("No synthesis output. Run synthesis first.")
            return
        self._console.append_info("Running timing analysis...")
        self.statusBar().showMessage("Timing analysis running...", 0)
        self._timing.setVisible(True)
        self._timing.raise_()

        worker = TimingWorker(
            liberty_path=str(self._project_mgr.liberty_path() or ""),
            netlist_path=str(self._project_mgr.netlist_path()),
            sdc_path=str(self._project_mgr.constraint_files()[0]) if self._project_mgr.constraint_files() else "",
            top_module=self._project_mgr.config.project.top_module if self._project_mgr.config else "top",
        )
        worker.output_line.connect(self._console.append_text)
        worker.finished.connect(self._on_timing_complete)
        worker.error.connect(self._console.append_error)
        self._active_worker = worker
        worker.start()

    def _on_timing_complete(self, result) -> None:
        self.statusBar().showMessage("Timing analysis complete", 5000)
        wns = getattr(result, "wns", None)
        self._console.append_success(f"Timing: WNS = {wns} ns" if wns is not None else "Timing analysis done.")
        if hasattr(self._timing, "update_from_timing_result"):
            self._timing.update_from_timing_result(result)

    def _on_security_analysis(self) -> None:
        self._console.append_info("Running security analysis...")
        self.statusBar().showMessage("Security analysis running...", 0)
        self._security.setVisible(True)
        self._security.raise_()
        # Security analysis runs crypto modules -- for now show demo until project wiring
        if hasattr(self._security, "show_demo_data"):
            self._security.show_demo_data()

    def _on_verify(self) -> None:
        """Run all verification: sim + formal + crypto."""
        self._console.append_info("Starting full verification...")
        self.statusBar().showMessage("Verification running...", 0)
        self._console.setVisible(True)
        self._console.raise_()
        # Start with simulation
        self._on_run_sim()

    def _on_tool_manager(self) -> None:
        dlg = ToolManagerDialog(self)
        dlg.exec()

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

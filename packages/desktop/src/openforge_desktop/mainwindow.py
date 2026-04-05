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

from openforge_desktop.panels.console import ConsolePanel
from openforge_desktop.panels.editor import EditorPanel
from openforge_desktop.panels.hierarchy import HierarchyPanel


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

        self._build_menu_bar()
        self._build_toolbar()
        self._build_status_bar()
        self._build_panels()
        self._restore_state()

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
        view_menu.addAction("Toggle Project &Explorer", self._toggle_project_explorer)
        view_menu.addSeparator()
        view_menu.addAction("&Reset Layout", self._reset_layout)

        # Project
        project_menu: QMenu = mb.addMenu("&Project")
        project_menu.addAction("&New Project...", self._stub)
        project_menu.addAction("&Open Project...", self._stub)
        project_menu.addSeparator()
        project_menu.addAction("Project &Settings...", self._stub)
        project_menu.addAction("Add &Source Files...", self._stub)

        # Verify
        verify_menu: QMenu = mb.addMenu("V&erify")
        verify_menu.addAction("Run &Simulation...", self._on_run_sim)
        verify_menu.addAction("Run &Formal Verification...", self._stub)
        verify_menu.addSeparator()
        verify_menu.addAction("&Constant-Time Check...", self._stub)
        verify_menu.addAction("Side-&Channel Analysis...", self._stub)
        verify_menu.addAction("&NIST Vector Validation...", self._stub)

        # Synthesize
        synth_menu: QMenu = mb.addMenu("&Synthesize")
        synth_menu.addAction("Run &Synthesis...", self._on_synthesize)
        synth_menu.addAction("&Implementation...", self._stub)
        synth_menu.addSeparator()
        synth_menu.addAction("Generate &Bitstream...", self._stub)

        # Analyze
        analyze_menu: QMenu = mb.addMenu("&Analyze")
        analyze_menu.addAction("Timing &Analysis...", self._stub)
        analyze_menu.addAction("&Power Analysis...", self._stub)
        analyze_menu.addAction("&Area Report...", self._stub)
        analyze_menu.addSeparator()
        analyze_menu.addAction("&Resource Utilization...", self._stub)

        # Tools
        tools_menu: QMenu = mb.addMenu("&Tools")
        tools_menu.addAction("&Tool Manager...", self._stub)
        tools_menu.addAction("&Settings...", self._stub)
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

        # Right: Properties
        self._properties = QDockWidget("Properties", self)
        self._properties.setObjectName("properties_dock")
        self._properties.setWidget(QLabel("  No selection"))
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._properties)

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
        self.statusBar().showMessage("Not yet implemented", 3000)

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

    def _on_run_sim(self) -> None:
        self._console.append_info("Starting simulation...")
        self.statusBar().showMessage("Simulation running...", 0)

    def _on_synthesize(self) -> None:
        self._console.append_info("Starting synthesis...")
        self.statusBar().showMessage("Synthesis running...", 0)

    def _on_verify(self) -> None:
        self._console.append_info("Starting verification...")
        self.statusBar().showMessage("Verification running...", 0)

    # ── View toggle helpers ────────────────────────────────────────

    def _toggle_hierarchy(self) -> None:
        self._hierarchy.setVisible(not self._hierarchy.isVisible())

    def _toggle_console(self) -> None:
        self._console.setVisible(not self._console.isVisible())

    def _toggle_properties(self) -> None:
        self._properties.setVisible(not self._properties.isVisible())

    def _toggle_project_explorer(self) -> None:
        self._project_explorer.setVisible(not self._project_explorer.isVisible())

    def _reset_layout(self) -> None:
        for dock in (self._hierarchy, self._project_explorer, self._console, self._properties):
            dock.setVisible(True)
        self.statusBar().showMessage("Layout reset", 3000)

"""In-app report viewer panel for OpenForge EDA - Dyber branded."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class ReportViewerPanel(QDockWidget):
    """Dock panel for viewing generated Dyber-branded HTML reports."""

    report_requested = Signal(str)  # report type to generate

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reports")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Report:"))
        self.report_combo = QComboBox()
        self.report_combo.addItems(
            [
                "Synthesis Report",
                "Timing Report",
                "Power Report",
                "DRC Report",
                "Utilization Report",
                "Summary Report (All)",
            ]
        )
        toolbar.addWidget(self.report_combo)

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.clicked.connect(self._on_generate)
        toolbar.addWidget(self.generate_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_reports)
        toolbar.addWidget(self.refresh_btn)

        self.open_browser_btn = QPushButton("Open in Browser")
        self.open_browser_btn.clicked.connect(self._on_open_browser)
        toolbar.addWidget(self.open_browser_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.report_list = QListWidget()
        self.report_list.itemClicked.connect(self._on_report_selected)
        self.report_list.setMinimumWidth(240)
        splitter.addWidget(self.report_list)

        # Right-hand side: stacked widget with a dark empty-state placeholder
        # and the QWebEngineView (shown only when a report loads).
        self._right_stack = QStackedWidget()
        self._right_stack.setStyleSheet("background-color: #1e1e2e;")

        # Empty-state placeholder (native Qt, renders synchronously)
        placeholder = QWidget()
        placeholder.setStyleSheet("background-color: #1e1e2e;")
        ph_layout = QVBoxLayout(placeholder)
        ph_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_title = QLabel("Report Viewer")
        ph_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_title.setStyleSheet(
            "color: #89b4fa; font-size: 16px; font-weight: 600; "
            "background: transparent; padding-bottom: 8px;"
        )
        ph_body = QLabel("Generate a report or select one from the list on the left.")
        ph_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_body.setWordWrap(True)
        ph_body.setStyleSheet("color: #a6adc8; font-size: 12px; background: transparent;")
        ph_layout.addWidget(ph_title)
        ph_layout.addWidget(ph_body)
        self._right_stack.addWidget(placeholder)  # index 0

        self.web = None
        self._has_web = False
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView  # type: ignore

            self.web = QWebEngineView()
            self._right_stack.addWidget(self.web)  # index 1
            self._has_web = True
        except Exception:
            fallback = QLabel(
                "QtWebEngine not installed.\n\n"
                "Install with: pip install PySide6-Addons\n\n"
                "Reports will open in your default browser."
            )
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setWordWrap(True)
            fallback.setStyleSheet(
                "background-color: #1e1e2e; color: #a6adc8; font-size: 12px; padding: 24px;"
            )
            self._right_stack.addWidget(fallback)  # index 1

        # Start on the dark placeholder
        self._right_stack.setCurrentIndex(0)
        splitter.addWidget(self._right_stack)

        # Make sure the container itself has the Catppuccin background
        container.setStyleSheet("background-color: #1e1e2e;")
        self.report_list.setStyleSheet(
            "QListWidget { background-color: #181825; color: #cdd6f4; "
            "border: 1px solid #313244; } "
            "QListWidget::item { padding: 6px 8px; } "
            "QListWidget::item:selected { background-color: #00d4ff; color: #11111b; } "
            "QListWidget::item:hover { background-color: #313244; }"
        )

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, stretch=1)

        self.setWidget(container)

        self._report_dir: Path | None = None
        self._current_report: Path | None = None

    def set_project_root(self, path) -> None:
        """Configure the project root; reports go to <root>/reports."""
        self._report_dir = Path(path) / "reports"
        self._report_dir.mkdir(parents=True, exist_ok=True)
        self.refresh_reports()

    def refresh_reports(self) -> None:
        self.report_list.clear()
        if self._report_dir is None or not self._report_dir.exists():
            return
        for f in sorted(
            self._report_dir.glob("*.html"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            item = QListWidgetItem(f.name)
            item.setData(Qt.ItemDataRole.UserRole, str(f))
            self.report_list.addItem(item)

    def _on_report_selected(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        self._current_report = Path(path)
        if self._has_web and self.web is not None:
            from PySide6.QtCore import QUrl

            self.web.load(QUrl.fromLocalFile(path))
            # Swap from placeholder to the web view
            self._right_stack.setCurrentIndex(1)

    def _on_generate(self) -> None:
        report_type = self.report_combo.currentText()
        self.report_requested.emit(report_type)

    def _on_open_browser(self) -> None:
        if self._current_report:
            import webbrowser

            webbrowser.open(self._current_report.as_uri())

    def set_theme(self, dark: bool) -> None:
        """Hook for theme switching - reports are always dark Dyber-branded."""
        pass

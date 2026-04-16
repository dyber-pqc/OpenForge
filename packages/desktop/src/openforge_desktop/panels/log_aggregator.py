"""Log Aggregator panel.

Central dark console that displays streamed :class:`LogEntry` events
from :class:`openforge.runner.log_aggregator.LogAggregator`, with
filter bar, save-to-file, clear, pause/resume and auto-scroll.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.runner.log_aggregator import (
        LogAggregator,
        LogEntry,
        LogFilter,
        LogLevel,
    )
except Exception:  # pragma: no cover
    LogAggregator = None  # type: ignore[assignment]
    LogEntry = None  # type: ignore[assignment]
    LogFilter = None  # type: ignore[assignment]

    class LogLevel:  # type: ignore[no-redef]
        DEBUG = "DEBUG"
        INFO = "INFO"
        WARN = "WARN"
        ERROR = "ERROR"
        FATAL = "FATAL"


_BG = "#0d0f15"
_SURFACE = "#1b1e27"
_TEXT = "#e5e9f0"
_BORDER = "#2b3040"
_ACCENT = "#4c8dff"


_LEVEL_COLORS = {
    "DEBUG": "#7a88a0",
    "INFO": "#d8e1f0",
    "WARN": "#f0c060",
    "ERROR": "#ef5c6b",
    "FATAL": "#ff3b58",
}


class LogAggregatorPanel(QWidget):
    """Live aggregated log console."""

    _entry_signal = Signal(object)

    def __init__(
        self, aggregator: LogAggregator | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LogAggregatorPanel")
        self.setStyleSheet(
            f"QWidget#LogAggregatorPanel {{ background: {_BG}; color: {_TEXT}; }}"
            f"QLineEdit, QComboBox {{ background: {_SURFACE}; color: {_TEXT};"
            f" border: 1px solid {_BORDER}; padding: 3px 6px; }}"
            f"QPushButton {{ background: {_SURFACE}; color: {_TEXT};"
            f" border: 1px solid {_BORDER}; padding: 4px 10px; }}"
            f"QPushButton:hover {{ border: 1px solid {_ACCENT}; }}"
            f"QLabel {{ color: {_TEXT}; }}"
            f"QCheckBox {{ color: {_TEXT}; }}"
            f"QPlainTextEdit {{ background: {_BG}; color: {_TEXT};"
            f" border: 1px solid {_BORDER}; font-family: Consolas, monospace; }}"
        )

        self._paused = False
        self._entry_signal.connect(self._on_entry_main)

        if aggregator is None and LogAggregator is not None:
            aggregator = LogAggregator()
        self.aggregator = aggregator
        if aggregator is not None:
            aggregator.subscribe(self._on_entry_bg)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # Filter bar
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Level:"))
        self.level_combo = QComboBox()
        for lv in ("ALL", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"):
            self.level_combo.addItem(lv)
        self.level_combo.currentIndexChanged.connect(self._refresh_view)
        bar.addWidget(self.level_combo)

        bar.addWidget(QLabel("Source:"))
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("any")
        self.source_edit.setMaximumWidth(160)
        self.source_edit.textChanged.connect(self._refresh_view)
        bar.addWidget(self.source_edit)

        bar.addWidget(QLabel("Stage:"))
        self.stage_edit = QLineEdit()
        self.stage_edit.setPlaceholderText("any")
        self.stage_edit.setMaximumWidth(160)
        self.stage_edit.textChanged.connect(self._refresh_view)
        bar.addWidget(self.stage_edit)

        bar.addWidget(QLabel("Regex:"))
        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText("pattern")
        self.pattern_edit.textChanged.connect(self._refresh_view)
        bar.addWidget(self.pattern_edit, 1)

        self.autoscroll = QCheckBox("Auto-scroll")
        self.autoscroll.setChecked(True)
        bar.addWidget(self.autoscroll)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self._toggle_pause)
        bar.addWidget(self.pause_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self._clear)
        bar.addWidget(self.clear_btn)

        self.save_btn = QPushButton("Save...")
        self.save_btn.clicked.connect(self._save)
        bar.addWidget(self.save_btn)

        root.addLayout(bar)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(100000)
        f = QFont("Consolas", 9)
        self.view.setFont(f)
        root.addWidget(self.view, 1)

    # ----- incoming entries ------------------------------------------------

    def _on_entry_bg(self, entry) -> None:  # type: ignore[no-untyped-def]
        # Invoked from aggregator thread; marshal to GUI thread
        with contextlib.suppress(Exception):
            self._entry_signal.emit(entry)

    def _on_entry_main(self, entry) -> None:  # type: ignore[no-untyped-def]
        if self._paused:
            return
        flt = self._current_filter()
        if flt is not None and hasattr(flt, "matches") and not flt.matches(entry):
            return
        self._append_entry(entry)

    def _append_entry(self, entry) -> None:  # type: ignore[no-untyped-def]
        level = getattr(entry.level, "value", str(entry.level))
        color = _LEVEL_COLORS.get(level, _TEXT)
        src = entry.source
        if getattr(entry, "stage_id", None):
            src = f"{src}:{entry.stage_id}"
        line = f"[{entry.timestamp}] [{level:<5}] [{src}] {entry.message}"
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.insertText(line + "\n", fmt)
        if self.autoscroll.isChecked():
            self.view.moveCursor(QTextCursor.MoveOperation.End)

    # ----- filter / view ---------------------------------------------------

    def _current_filter(self):  # type: ignore[no-untyped-def]
        if LogFilter is None:
            return None
        lv = self.level_combo.currentText()
        levels = None
        if lv != "ALL":
            # include this and higher severities
            order = ["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]
            try:
                idx = order.index(lv)
                levels = [LogLevel(x) for x in order[idx:]]  # type: ignore[call-arg]
            except Exception:
                levels = None
        return LogFilter(
            levels=levels,
            source=self.source_edit.text().strip() or None,
            stage=self.stage_edit.text().strip() or None,
            pattern=self.pattern_edit.text().strip() or None,
        )

    def _refresh_view(self) -> None:
        if self.aggregator is None:
            return
        self.view.clear()
        flt = self._current_filter()
        for e in self.aggregator.entries(flt):
            self._append_entry(e)

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_btn.setText("Resume" if self._paused else "Pause")

    def _clear(self) -> None:
        self.view.clear()

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save unified log", "openforge.log", "Log Files (*.log);;All Files (*)"
        )
        if not path:
            return
        if self.aggregator is not None:
            try:
                self.aggregator.save_unified_log(path)
            except Exception:
                # fallback: dump view text
                Path(path).write_text(self.view.toPlainText(), encoding="utf-8")
        else:
            Path(path).write_text(self.view.toPlainText(), encoding="utf-8")


__all__ = ["LogAggregatorPanel"]

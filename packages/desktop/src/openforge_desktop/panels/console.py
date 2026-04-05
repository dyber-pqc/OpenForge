"""Console output panel with styled log messages and command input."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

# Severity colours (Catppuccin Mocha palette)
_CLR_INFO: Final[str] = "#89b4fa"     # blue
_CLR_WARNING: Final[str] = "#f9e2af"  # yellow
_CLR_ERROR: Final[str] = "#f38ba8"    # red
_CLR_SUCCESS: Final[str] = "#a6e3a1"  # green
_CLR_DEBUG: Final[str] = "#a6adc8"    # subtext0
_CLR_DEFAULT: Final[str] = "#cdd6f4"  # text
_CLR_TIMESTAMP: Final[str] = "#585b70"  # overlay0


def _make_format(color: str, bold: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    return fmt


class ConsolePanel(QDockWidget):
    """Dock widget providing a console output area and command input line."""

    command_entered: Signal = Signal(str)

    def __init__(self, title: str = "Console", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea
        )

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Output area
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumBlockCount(10_000)
        font = QFont("JetBrains Mono", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._output.setFont(font)
        layout.addWidget(self._output, stretch=1)

        # Command input row
        input_row = QWidget()
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(4, 2, 4, 2)
        input_layout.setSpacing(4)

        prompt_label = QLabel(">")
        prompt_label.setStyleSheet(f"color: {_CLR_INFO}; font-weight: bold;")
        input_layout.addWidget(prompt_label)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Enter command...")
        self._input.returnPressed.connect(self._on_command_entered)
        input_layout.addWidget(self._input)

        layout.addWidget(input_row)
        self.setWidget(container)

        # Command history
        self._history: list[str] = []
        self._history_idx: int = -1

    # ── Public API ─────────────────────────────────────────────────

    def append_info(self, message: str) -> None:
        """Append an informational message (blue)."""
        self._append_styled("INFO", message, _CLR_INFO)

    def append_warning(self, message: str) -> None:
        """Append a warning message (yellow)."""
        self._append_styled("WARN", message, _CLR_WARNING)

    def append_error(self, message: str) -> None:
        """Append an error message (red, bold)."""
        self._append_styled("ERROR", message, _CLR_ERROR, bold=True)

    def append_success(self, message: str) -> None:
        """Append a success message (green)."""
        self._append_styled("OK", message, _CLR_SUCCESS)

    def append_debug(self, message: str) -> None:
        """Append a debug message (gray)."""
        self._append_styled("DEBUG", message, _CLR_DEBUG)

    def append_text(self, text: str, color: str = _CLR_DEFAULT) -> None:
        """Append plain text with an optional colour override."""
        cursor = self._output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text, _make_format(color))
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def clear(self) -> None:
        """Clear all console output."""
        self._output.clear()

    # ── Internal ───────────────────────────────────────────────────

    def _append_styled(
        self, tag: str, message: str, color: str, *, bold: bool = False
    ) -> None:
        timestamp = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
        cursor = self._output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)

        # Timestamp
        cursor.insertText(f"[{timestamp}] ", _make_format(_CLR_TIMESTAMP))
        # Severity tag
        cursor.insertText(f"[{tag}] ", _make_format(color, bold=True))
        # Message body
        cursor.insertText(f"{message}\n", _make_format(color, bold=bold))

        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def _on_command_entered(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._history.append(text)
        self._history_idx = len(self._history)
        self.append_text(f"> {text}\n", _CLR_INFO)
        self.command_entered.emit(text)
        self._input.clear()

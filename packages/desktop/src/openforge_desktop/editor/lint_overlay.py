"""Lint overlay: draws wavy underlines (squiggles) for diagnostics on a CodeEditor.

Integrates with external linters (verible-verilog-lint, etc.) by running
them asynchronously in a QThread and rendering results as red/yellow
wavy underlines with tooltip messages.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Final, TypedDict

from PySide6.QtCore import QObject, QPointF, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QToolTip

# ── Diagnostic types ─────────────────────────────────────────────────────


class Diagnostic(TypedDict, total=False):
    """A single lint diagnostic."""
    file: str
    line: int       # 1-based
    col: int        # 1-based
    end_col: int    # 1-based (optional, defaults to col + 1)
    severity: str   # "error", "warning", "info", "hint"
    message: str
    rule: str       # rule identifier


# Colors for severity levels
_SEVERITY_COLORS: Final[dict[str, str]] = {
    "error": "#f38ba8",    # Catppuccin red
    "warning": "#f9e2af",  # Catppuccin yellow
    "info": "#89b4fa",     # Catppuccin blue
    "hint": "#6c7086",     # Catppuccin overlay0
}


# ── Lint worker (runs in QThread) ────────────────────────────────────────


class _LintWorker(QObject):
    """Run an external linter and parse its output."""

    diagnostics_ready = Signal(list)  # list[Diagnostic]
    error_occurred = Signal(str)

    def __init__(self, file_path: str, linter_cmd: list[str]) -> None:
        super().__init__()
        self._file_path = file_path
        self._linter_cmd = linter_cmd

    def run(self) -> None:
        try:
            result = subprocess.run(
                self._linter_cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            diagnostics = self._parse_output(result.stdout + result.stderr)
            self.diagnostics_ready.emit(diagnostics)
        except FileNotFoundError:
            self.error_occurred.emit(f"Linter not found: {self._linter_cmd[0]}")
        except subprocess.TimeoutExpired:
            self.error_occurred.emit("Linter timed out (30s)")
        except Exception as e:
            self.error_occurred.emit(str(e))

    def _parse_output(self, output: str) -> list[Diagnostic]:
        """Parse linter output into diagnostics.

        Supports common output formats:
        - file:line:col: severity: message [rule]
        - file:line: severity: message
        """
        diagnostics: list[Diagnostic] = []

        # Pattern: file:line:col: error/warning: message [rule]
        pattern = re.compile(
            r"(?P<file>[^:]+):(?P<line>\d+):(?:(?P<col>\d+):)?\s*"
            r"(?P<severity>error|warning|note|info|hint):\s*"
            r"(?P<message>.+?)(?:\s*\[(?P<rule>[^\]]+)\])?\s*$",
            re.MULTILINE,
        )

        for m in pattern.finditer(output):
            severity = m.group("severity")
            if severity == "note":
                severity = "info"

            diag: Diagnostic = {
                "file": m.group("file"),
                "line": int(m.group("line")),
                "col": int(m.group("col")) if m.group("col") else 1,
                "severity": severity,
                "message": m.group("message").strip(),
            }
            if m.group("rule"):
                diag["rule"] = m.group("rule")

            diagnostics.append(diag)

        return diagnostics


# ═══════════════════════════════════════════════════════════════════════════
#  LintOverlay
# ═══════════════════════════════════════════════════════════════════════════


class LintOverlay(QObject):
    """Draws wavy red/yellow underlines for lint violations on a CodeEditor.

    Usage::

        overlay = LintOverlay(editor)
        overlay.set_diagnostics([
            {"file": "foo.v", "line": 10, "col": 5, "end_col": 15,
             "severity": "error", "message": "Syntax error", "rule": "E001"},
        ])

    Or run a linter asynchronously::

        overlay.run_verible_async("path/to/file.v")
    """

    diagnostics_changed = Signal()

    def __init__(self, editor: QPlainTextEdit) -> None:
        super().__init__(editor)
        self._editor = editor
        self._diagnostics: list[Diagnostic] = []
        self._thread: QThread | None = None
        self._worker: _LintWorker | None = None

        # Install event filter for tooltip on hover
        editor.viewport().installEventFilter(self)

    @property
    def diagnostics(self) -> list[Diagnostic]:
        return list(self._diagnostics)

    def set_diagnostics(self, diagnostics: list[Diagnostic]) -> None:
        """Set diagnostics and update the visual overlay."""
        self._diagnostics = list(diagnostics)
        self._apply_squiggles()
        self.diagnostics_changed.emit()

    def clear(self) -> None:
        """Remove all diagnostics and squiggles."""
        self._diagnostics.clear()
        self._apply_squiggles()
        self.diagnostics_changed.emit()

    def run_verible_async(self, file_path: str) -> None:
        """Run verible-verilog-lint asynchronously and update diagnostics."""
        verible = shutil.which("verible-verilog-lint")
        if not verible:
            return

        cmd = [verible, file_path]
        self._run_linter_async(file_path, cmd)

    def run_linter_async(self, file_path: str, cmd: list[str]) -> None:
        """Run an arbitrary linter command asynchronously."""
        self._run_linter_async(file_path, cmd)

    def _run_linter_async(self, file_path: str, cmd: list[str]) -> None:
        """Internal: start a lint worker in a background thread."""
        # Clean up previous run
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1000)

        self._thread = QThread()
        self._worker = _LintWorker(file_path, cmd)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.diagnostics_ready.connect(self._on_lint_done)
        self._worker.diagnostics_ready.connect(self._thread.quit)
        self._worker.error_occurred.connect(self._thread.quit)

        self._thread.start()

    def _on_lint_done(self, diagnostics: list[Diagnostic]) -> None:
        self.set_diagnostics(diagnostics)

    def _apply_squiggles(self) -> None:
        """Apply wavy underline extra selections to the editor."""
        selections: list[QTextEdit.ExtraSelection] = []

        for diag in self._diagnostics:
            line = diag.get("line", 1) - 1  # 0-based
            col = diag.get("col", 1) - 1    # 0-based
            end_col = diag.get("end_col", col + len(diag.get("message", "x").split()[0]) if col else col + 5)

            block = self._editor.document().findBlockByLineNumber(line)
            if not block.isValid():
                continue

            severity = diag.get("severity", "error")
            color = QColor(_SEVERITY_COLORS.get(severity, _SEVERITY_COLORS["error"]))

            fmt = QTextEdit.ExtraSelection()
            fmt.format.setUnderlineColor(color)
            fmt.format.setUnderlineStyle(
                fmt.format.UnderlineStyle.WaveUnderline,
            )
            fmt.format.setToolTip(self._format_tooltip(diag))

            cursor = QTextCursor(block)
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, col)
            # Clamp end_col to block length
            block_len = block.length() - 1  # -1 for newline
            actual_end = min(end_col, block_len)
            length = max(actual_end - col, 1)
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, length)
            fmt.cursor = cursor

            selections.append(fmt)

        # Merge with existing extra selections (keep line/bracket highlights)
        existing = [s for s in self._editor.extraSelections()
                    if not s.format.underlineColor().isValid()
                    or s.format.underlineStyle() != QTextEdit.ExtraSelection().format.UnderlineStyle.WaveUnderline]
        self._editor.setExtraSelections(existing + selections)

    @staticmethod
    def _format_tooltip(diag: Diagnostic) -> str:
        """Format a diagnostic for tooltip display."""
        severity = diag.get("severity", "error").upper()
        message = diag.get("message", "")
        rule = diag.get("rule", "")
        parts = [f"[{severity}]"]
        if rule:
            parts.append(f"({rule})")
        parts.append(message)
        return " ".join(parts)

    def eventFilter(self, obj: QObject, event) -> bool:
        """Show tooltip when hovering over a squiggle."""
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.Type.ToolTip and obj == self._editor.viewport():
            pos = event.pos()
            cursor = self._editor.cursorForPosition(pos)
            line = cursor.blockNumber() + 1
            col = cursor.columnNumber() + 1

            for diag in self._diagnostics:
                if diag.get("line") == line:
                    d_col = diag.get("col", 1)
                    d_end = diag.get("end_col", d_col + 10)
                    if d_col <= col <= d_end:
                        QToolTip.showText(
                            event.globalPos(),
                            self._format_tooltip(diag),
                            self._editor,
                        )
                        return True

            QToolTip.hideText()

        return super().eventFilter(obj, event)

"""Production code editor widget with line numbers, bracket matching,
indent guides, selection highlighting, auto-indent, and keyboard shortcuts.

Built on QPlainTextEdit with a custom line-number gutter, current-line
highlight, and integration points for syntax highlighting and lint overlays.
"""

from __future__ import annotations

import re
from typing import Final

from PySide6.QtCore import QRect, QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QPen,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)

from openforge_desktop.editor.highlighter import highlighter_for_extension

# ── Theme constants (Catppuccin Mocha) ───────────────────────────────────

_MONO_FONT_FAMILY: Final[str] = "JetBrains Mono"
_MONO_FONT_FALLBACK: Final[str] = "Consolas"
_MONO_FONT_FALLBACK2: Final[str] = "Courier New"
_MONO_FONT_SIZE: Final[int] = 11

_BG: Final[str] = "#1e1e2e"
_FG: Final[str] = "#cdd6f4"
_MARGIN_BG: Final[str] = "#181825"
_MARGIN_FG: Final[str] = "#585b70"
_MARGIN_CURRENT: Final[str] = "#cdd6f4"
_CARET: Final[str] = "#f5e0dc"
_SEL_BG: Final[str] = "#45475a"
_LINE_BG: Final[str] = "#11111b"
_BRACKET_BG: Final[str] = "#585b70"
_BRACKET_FG: Final[str] = "#f9e2af"
_OCCUR_BG: Final[str] = "#313244"
_INDENT_GUIDE: Final[str] = "#313244"
_MINIMAP_BG: Final[str] = "#181825"
_MINIMAP_VIEWPORT: Final[str] = "#313244"

# Bracket pairs
_OPEN_BRACKETS: Final[dict[str, str]] = {"(": ")", "[": "]", "{": "}"}
_CLOSE_BRACKETS: Final[dict[str, str]] = {")": "(", "]": "[", "}": "{"}


def _make_font() -> QFont:
    font = QFont(_MONO_FONT_FAMILY, _MONO_FONT_SIZE)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFamilies([_MONO_FONT_FAMILY, _MONO_FONT_FALLBACK, _MONO_FONT_FALLBACK2])
    return font


# ── Line number gutter ───────────────────────────────────────────────────


class _LineNumberArea(QWidget):
    """Paints line numbers alongside a CodeEditor."""

    def __init__(self, editor: CodeEditor) -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):  # noqa: N802
        return self._editor.line_number_area_size()

    def paintEvent(self, event):  # noqa: N802
        self._editor.line_number_area_paint(event)


# ── Auto-completion popup ────────────────────────────────────────────────


class _CompletionPopup(QListWidget):
    """Popup list for keyword and symbol auto-completion."""

    completion_accepted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.ToolTip)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMaximumHeight(200)
        self.setMaximumWidth(300)
        self.setStyleSheet(f"""
            QListWidget {{
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #585b70;
                border-radius: 4px;
                font-family: "{_MONO_FONT_FAMILY}", "{_MONO_FONT_FALLBACK}", monospace;
                font-size: 11px;
                padding: 2px;
            }}
            QListWidget::item {{
                padding: 3px 8px;
            }}
            QListWidget::item:selected {{
                background-color: #89b4fa;
                color: #1e1e2e;
            }}
        """)
        self.itemActivated.connect(self._on_item_activated)
        self._candidates: list[str] = []

    def set_candidates(self, candidates: list[str]) -> None:
        """Set the full list of completion candidates."""
        self._candidates = sorted(set(candidates))

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        if item:
            self.completion_accepted.emit(item.text())
            self.hide()

    def update_completions(self, prefix: str) -> None:
        self.clear()
        if len(prefix) < 2:
            self.hide()
            return
        prefix_lower = prefix.lower()
        matches = [
            c for c in self._candidates if c.lower().startswith(prefix_lower) and c != prefix
        ]
        if not matches:
            self.hide()
            return
        for m in matches[:50]:  # limit to 50 entries
            self.addItem(m)
        self.setCurrentRow(0)
        self.show()

    def accept_current(self) -> bool:
        item = self.currentItem()
        if item and self.isVisible():
            self.completion_accepted.emit(item.text())
            self.hide()
            return True
        return False

    def move_selection(self, delta: int) -> None:
        if not self.isVisible():
            return
        row = self.currentRow() + delta
        row = max(0, min(row, self.count() - 1))
        self.setCurrentRow(row)


# ── Minimap ──────────────────────────────────────────────────────────────


class _Minimap(QPlainTextEdit):
    """Narrow read-only preview of the editor content (minimap)."""

    scroll_requested = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFixedWidth(100)

        small_font = QFont(_MONO_FONT_FAMILY, 2)
        small_font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(small_font)

        self.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {_MINIMAP_BG};
                color: #585b70;
                border: none;
                border-left: 1px solid #313244;
            }}
        """)
        self._viewport_start: float = 0.0
        self._viewport_end: float = 0.1

    def set_viewport_highlight(self, start: float, end: float) -> None:
        self._viewport_start = start
        self._viewport_end = end
        self.viewport().update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        rect = self.viewport().rect()
        h = rect.height()
        y_start = int(h * self._viewport_start)
        y_end = int(h * self._viewport_end)
        painter.fillRect(
            QRect(0, y_start, rect.width(), max(y_end - y_start, 10)),
            QColor(69, 71, 90, 80),
        )
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            ratio = event.position().y() / max(self.viewport().height(), 1)
            self.scroll_requested.emit(max(0.0, min(1.0, ratio)))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            ratio = event.position().y() / max(self.viewport().height(), 1)
            self.scroll_requested.emit(max(0.0, min(1.0, ratio)))


# ═══════════════════════════════════════════════════════════════════════════
#  CodeEditor — the main editor widget
# ═══════════════════════════════════════════════════════════════════════════


class CodeEditor(QPlainTextEdit):
    """Production code editor with line numbers, current-line highlight,
    bracket matching, indent guides, auto-indent, selection highlighting,
    smart Home key, and configurable keyboard shortcuts.

    Designed for Verilog/SystemVerilog, VHDL, SDC/TCL, and general text.
    """

    cursor_position_changed = Signal(int, int)
    modification_changed = Signal(bool)
    go_to_definition_requested = Signal(str)  # symbol name

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        file_extension: str = ".v",
        tab_width: int = 4,
    ) -> None:
        super().__init__(parent)

        self._tab_width = tab_width
        self._file_extension = file_extension

        # Font
        font = _make_font()
        self.setFont(font)
        self.setTabStopDistance(font.pointSizeF() * tab_width)

        # Palette / colors
        palette = self.palette()
        palette.setColor(palette.ColorRole.Base, QColor(_BG))
        palette.setColor(palette.ColorRole.Text, QColor(_FG))
        palette.setColor(palette.ColorRole.Highlight, QColor(_SEL_BG))
        self.setPalette(palette)
        self.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {_BG};
                color: {_FG};
                selection-background-color: {_SEL_BG};
                border: none;
            }}
        """)
        self.setCursorWidth(2)

        # Line number area
        self._line_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        self._update_line_area_width(0)

        # Syntax highlighter
        self._highlighter = highlighter_for_extension(file_extension, self.document())

        # Modification tracking
        self.document().modificationChanged.connect(self._on_modification_changed)

        # Auto-completion
        self._completion_popup = _CompletionPopup(self)
        self._completion_popup.hide()
        self._completion_popup.completion_accepted.connect(self._accept_completion)
        self._completion_timer = QTimer(self)
        self._completion_timer.setSingleShot(True)
        self._completion_timer.setInterval(200)
        self._completion_timer.timeout.connect(self._update_completions)
        self.textChanged.connect(self._schedule_completion_update)

        # Selection highlight timer (debounce)
        self._sel_highlight_timer = QTimer(self)
        self._sel_highlight_timer.setSingleShot(True)
        self._sel_highlight_timer.setInterval(100)
        self._sel_highlight_timer.timeout.connect(self._highlight_occurrences)

        # Word wrap state
        self._word_wrap_enabled = False
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        # Indent guides
        self._indent_guides_enabled = True

        # Occurrence selections (stored separately to merge with bracket/line)
        self._occurrence_selections: list[QTextEdit.ExtraSelection] = []

        # Initial highlight
        self._on_cursor_moved()

    @property
    def file_extension(self) -> str:
        return self._file_extension

    @file_extension.setter
    def file_extension(self, ext: str) -> None:
        if ext != self._file_extension:
            self._file_extension = ext
            self._highlighter = highlighter_for_extension(ext, self.document())

    # ── Cursor movement handler ──────────────────────────────────────

    def _on_cursor_moved(self) -> None:
        self._emit_cursor_pos()
        self._highlight_current_line_and_brackets()
        self._sel_highlight_timer.start()

    def _emit_cursor_pos(self) -> None:
        cursor = self.textCursor()
        self.cursor_position_changed.emit(
            cursor.blockNumber() + 1,
            cursor.columnNumber() + 1,
        )

    def _on_modification_changed(self, changed: bool) -> None:
        self.modification_changed.emit(changed)

    # ── Current line + bracket matching ──────────────────────────────

    def _highlight_current_line_and_brackets(self) -> None:
        selections: list[QTextEdit.ExtraSelection] = []

        # Current line highlight
        if not self.isReadOnly():
            line_sel = QTextEdit.ExtraSelection()
            line_sel.format.setBackground(QColor(_LINE_BG))
            line_sel.format.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
            line_sel.cursor = self.textCursor()
            line_sel.cursor.clearSelection()
            selections.append(line_sel)

        # Bracket matching
        cursor = self.textCursor()
        pos = cursor.position()
        doc_text = self.document().toPlainText()

        for check_pos in (pos, pos - 1):
            if 0 <= check_pos < len(doc_text):
                char = doc_text[check_pos]
                if char in _OPEN_BRACKETS or char in _CLOSE_BRACKETS:
                    match_pos = self._find_matching_bracket(check_pos, char)
                    if match_pos >= 0:
                        for bp in (check_pos, match_pos):
                            sel = QTextEdit.ExtraSelection()
                            sel.format.setBackground(QColor(_BRACKET_BG))
                            sel.format.setForeground(QColor(_BRACKET_FG))
                            sel.format.setFontWeight(QFont.Weight.Bold)
                            c = self.textCursor()
                            c.setPosition(bp)
                            c.movePosition(
                                QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1
                            )
                            sel.cursor = c
                            selections.append(sel)

        # Merge in occurrence highlights
        selections.extend(self._occurrence_selections)

        self.setExtraSelections(selections)

    def _find_matching_bracket(self, pos: int, char: str) -> int:
        doc_text = self.document().toPlainText()
        if char in _OPEN_BRACKETS:
            target = _OPEN_BRACKETS[char]
            direction = 1
            opener = char
        elif char in _CLOSE_BRACKETS:
            target = char
            opener = _CLOSE_BRACKETS[char]
            direction = -1
        else:
            return -1

        depth = 0
        i = pos
        while 0 <= i < len(doc_text):
            c = doc_text[i]
            if c == opener:
                depth += 1
            elif c == target:
                depth -= 1
                if depth == 0:
                    return i
            i += direction
        return -1

    # ── Selection occurrence highlighting ────────────────────────────

    def _highlight_occurrences(self) -> None:
        """Highlight all occurrences of the currently selected word."""
        self._occurrence_selections.clear()

        cursor = self.textCursor()
        if not cursor.hasSelection():
            self._highlight_current_line_and_brackets()
            return

        selected = cursor.selectedText().strip()
        if not selected or len(selected) < 2 or " " in selected or "\n" in selected:
            self._highlight_current_line_and_brackets()
            return

        # Escape for regex, match whole word only
        pattern = QRegularExpression(r"\b" + re.escape(selected) + r"\b")
        doc_text = self.document().toPlainText()
        it = pattern.globalMatch(doc_text)

        while it.hasNext():
            m = it.next()
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(QColor(_OCCUR_BG))
            c = self.textCursor()
            c.setPosition(m.capturedStart())
            c.setPosition(m.capturedEnd(), QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = c
            self._occurrence_selections.append(sel)

        self._highlight_current_line_and_brackets()

    # ── Auto-completion ──────────────────────────────────────────────

    def _schedule_completion_update(self) -> None:
        self._completion_timer.start()

    def _current_word_prefix(self) -> str:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfWord, QTextCursor.MoveMode.KeepAnchor)
        return cursor.selectedText()

    def _update_completions(self) -> None:
        prefix = self._current_word_prefix()
        if len(prefix) < 2:
            self._completion_popup.hide()
            return
        self._completion_popup.update_completions(prefix)
        if self._completion_popup.count() > 0:
            cursor_rect = self.cursorRect()
            global_pos = self.mapToGlobal(cursor_rect.bottomLeft())
            self._completion_popup.move(global_pos)
            self._completion_popup.show()
        else:
            self._completion_popup.hide()

    def _accept_completion(self, text: str) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfWord, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        self.setTextCursor(cursor)

    def set_completion_candidates(self, candidates: list[str]) -> None:
        """Set the list of completion candidates (keywords + symbols)."""
        self._completion_popup.set_candidates(candidates)

    # ── Go to line ───────────────────────────────────────────────────

    def go_to_line(self) -> None:
        max_line = self.blockCount()
        line, ok = QInputDialog.getInt(
            self,
            "Go to Line",
            f"Line number (1-{max_line}):",
            self.textCursor().blockNumber() + 1,
            1,
            max_line,
        )
        if ok:
            block = self.document().findBlockByLineNumber(line - 1)
            cursor = self.textCursor()
            cursor.setPosition(block.position())
            self.setTextCursor(cursor)
            self.centerCursor()

    # ── Indent / Unindent ────────────────────────────────────────────

    def indent_selection(self) -> None:
        cursor = self.textCursor()
        indent = " " * self._tab_width
        if not cursor.hasSelection():
            cursor.insertText(indent)
            return
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.beginEditBlock()
        while cursor.position() <= end and not cursor.atEnd():
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.insertText(indent)
            end += self._tab_width
            if not cursor.movePosition(QTextCursor.MoveOperation.NextBlock):
                break
        cursor.endEditBlock()

    def unindent_selection(self) -> None:
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.beginEditBlock()
        while cursor.position() <= end and not cursor.atEnd():
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            line = cursor.block().text()
            if line.startswith(" " * self._tab_width):
                cursor.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.KeepAnchor,
                    self._tab_width,
                )
                cursor.removeSelectedText()
                end -= self._tab_width
            elif line.startswith("\t"):
                cursor.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.KeepAnchor,
                    1,
                )
                cursor.removeSelectedText()
                end -= 1
            if not cursor.movePosition(QTextCursor.MoveOperation.NextBlock):
                break
        cursor.endEditBlock()

    # ── Comment toggle ───────────────────────────────────────────────

    def toggle_comment(self) -> None:
        """Toggle line comment prefix for the current language."""
        # Determine comment string based on file type
        ext = self._file_extension.lower()
        if ext in {".vhd", ".vhdl"}:
            comment_str = "--"
        elif ext in {".sdc", ".xdc", ".tcl", ".py"}:
            comment_str = "#"
        else:
            comment_str = "//"

        cursor = self.textCursor()
        if cursor.hasSelection():
            start = cursor.selectionStart()
            end = cursor.selectionEnd()
        else:
            start = cursor.position()
            end = cursor.position()

        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)

        # First pass: check if all non-empty lines are commented
        check = self.textCursor()
        check.setPosition(start)
        check.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        all_commented = True
        while check.position() <= end and not check.atEnd():
            line = check.block().text()
            stripped = line.lstrip()
            if stripped and not stripped.startswith(comment_str):
                all_commented = False
                break
            if not check.movePosition(QTextCursor.MoveOperation.NextBlock):
                break

        # Second pass: toggle
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.beginEditBlock()
        while cursor.position() <= end and not cursor.atEnd():
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            line = cursor.block().text()
            if all_commented:
                idx = line.find(comment_str)
                if idx >= 0:
                    cursor.movePosition(
                        QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, idx
                    )
                    remove_len = len(comment_str)
                    remaining = line[idx + len(comment_str) :]
                    if remaining.startswith(" "):
                        remove_len += 1
                    cursor.movePosition(
                        QTextCursor.MoveOperation.Right,
                        QTextCursor.MoveMode.KeepAnchor,
                        remove_len,
                    )
                    cursor.removeSelectedText()
                    end -= remove_len
            else:
                cursor.insertText(comment_str + " ")
                end += len(comment_str) + 1
            if not cursor.movePosition(QTextCursor.MoveOperation.NextBlock):
                break
        cursor.endEditBlock()

    # ── Duplicate line (Ctrl+D) ──────────────────────────────────────

    def duplicate_line(self) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        text = cursor.selectedText()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.insertText("\n" + text)
        self.setTextCursor(cursor)

    # ── Delete line (Ctrl+Shift+K) ───────────────────────────────────

    def delete_line(self) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor)
        if cursor.atEnd():
            # Last line: select to end including preceding newline
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
            )
            if cursor.position() > 0:
                cursor.movePosition(
                    QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, 1
                )
        cursor.removeSelectedText()

    # ── Word wrap toggle ─────────────────────────────────────────────

    def toggle_word_wrap(self) -> None:
        self._word_wrap_enabled = not self._word_wrap_enabled
        self.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if self._word_wrap_enabled
            else QPlainTextEdit.LineWrapMode.NoWrap
        )

    @property
    def word_wrap_enabled(self) -> bool:
        return self._word_wrap_enabled

    # ── Key handling ─────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # Completion popup navigation
        if self._completion_popup.isVisible():
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                if self._completion_popup.accept_current():
                    return
            elif event.key() == Qt.Key.Key_Escape:
                self._completion_popup.hide()
                return
            elif event.key() == Qt.Key.Key_Down:
                self._completion_popup.move_selection(1)
                return
            elif event.key() == Qt.Key.Key_Up:
                self._completion_popup.move_selection(-1)
                return

        mods = event.modifiers()
        key = event.key()

        # Ctrl+/ toggle comment
        if key == Qt.Key.Key_Slash and mods == Qt.KeyboardModifier.ControlModifier:
            self.toggle_comment()
            return

        # Ctrl+D duplicate line
        if key == Qt.Key.Key_D and mods == Qt.KeyboardModifier.ControlModifier:
            self.duplicate_line()
            return

        # Ctrl+Shift+K delete line
        if key == Qt.Key.Key_K and mods == (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        ):
            self.delete_line()
            return

        # Ctrl+G go to line
        if key == Qt.Key.Key_G and mods == Qt.KeyboardModifier.ControlModifier:
            self.go_to_line()
            return

        # Tab → spaces (when no selection, or indent selection)
        if key == Qt.Key.Key_Tab and self.textCursor().hasSelection():
            self.indent_selection()
            return
        if key == Qt.Key.Key_Tab and mods == Qt.KeyboardModifier.NoModifier:
            self.textCursor().insertText(" " * self._tab_width)
            return
        if key == Qt.Key.Key_Backtab:
            self.unindent_selection()
            return

        # Smart Home: first press → first non-whitespace, second → column 0
        if key == Qt.Key.Key_Home and mods in (
            Qt.KeyboardModifier.NoModifier,
            Qt.KeyboardModifier.ShiftModifier,
        ):
            self._smart_home(mods == Qt.KeyboardModifier.ShiftModifier)
            return

        # Enter: auto-indent
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods == Qt.KeyboardModifier.NoModifier:
            self._auto_indent_newline()
            return

        # Zoom: Ctrl+= / Ctrl+- / Ctrl+0
        if key == Qt.Key.Key_Equal and mods == Qt.KeyboardModifier.ControlModifier:
            self.zoomIn(1)
            return
        if key == Qt.Key.Key_Minus and mods == Qt.KeyboardModifier.ControlModifier:
            self.zoomOut(1)
            return
        if key == Qt.Key.Key_0 and mods == Qt.KeyboardModifier.ControlModifier:
            self.setFont(_make_font())
            return

        # Ctrl+Click for go-to-definition is handled in mousePressEvent

        super().keyPressEvent(event)

    def _smart_home(self, extend_selection: bool) -> None:
        """Smart Home: jump to first non-ws, then to col 0."""
        cursor = self.textCursor()
        line = cursor.block().text()
        first_non_ws = len(line) - len(line.lstrip())
        col = cursor.columnNumber()

        mode = (
            QTextCursor.MoveMode.KeepAnchor if extend_selection else QTextCursor.MoveMode.MoveAnchor
        )

        if col == first_non_ws or col == 0:
            target = 0 if col == first_non_ws else first_non_ws
        else:
            target = first_non_ws

        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, mode)
        if target > 0:
            cursor.movePosition(QTextCursor.MoveOperation.Right, mode, target)
        self.setTextCursor(cursor)

    def _auto_indent_newline(self) -> None:
        """Insert newline and match the previous line's indent."""
        cursor = self.textCursor()
        line = cursor.block().text()
        indent = ""
        for ch in line:
            if ch in (" ", "\t"):
                indent += ch
            else:
                break

        # Increase indent after begin / { / (
        stripped = line.rstrip()
        if stripped.endswith(("begin", "{", "(", ":")):
            indent += " " * self._tab_width

        cursor.insertText("\n" + indent)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    # ── Mouse events (Ctrl+Click for go-to-definition) ───────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            cursor = self.cursorForPosition(event.position().toPoint())
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            word = cursor.selectedText().strip()
            if word and re.match(r"^[a-zA-Z_]\w*$", word):
                self.go_to_definition_requested.emit(word)
                return
        super().mousePressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self._completion_popup.hide()
        super().focusOutEvent(event)

    # ── Context menu ─────────────────────────────────────────────────

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)

        menu.addAction("Cut", self.cut, QKeySequence.StandardKey.Cut)
        menu.addAction("Copy", self.copy, QKeySequence.StandardKey.Copy)
        menu.addAction("Paste", self.paste, QKeySequence.StandardKey.Paste)
        menu.addAction("Select All", self.selectAll, QKeySequence.StandardKey.SelectAll)
        menu.addSeparator()

        # Go to definition (on word under cursor)
        cursor = self.cursorForPosition(self.mapFromGlobal(event.globalPos()))
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        word = cursor.selectedText().strip()
        if word:
            menu.addAction(
                f"Go to Definition: {word}", lambda: self.go_to_definition_requested.emit(word)
            )
        menu.addAction("Go to Line...", self.go_to_line)
        menu.addSeparator()

        menu.addAction("Comment/Uncomment", self.toggle_comment)
        indent_menu = menu.addMenu("Indentation")
        indent_menu.addAction("Indent", self.indent_selection)
        indent_menu.addAction("Unindent", self.unindent_selection)
        menu.addSeparator()

        menu.addAction("Duplicate Line", self.duplicate_line)
        menu.addAction("Delete Line", self.delete_line)

        menu.exec(event.globalPos())

    # ── Line number area ─────────────────────────────────────────────

    def line_number_area_size(self):
        digits = max(1, len(str(self.blockCount())))
        space = 16 + self.fontMetrics().horizontalAdvance("9") * digits
        return space

    def line_number_area_width(self) -> int:
        return self.line_number_area_size()

    def _update_line_area_width(self, _count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_area(self, rect, dy):
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_area_width(0)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(cr.left(), cr.top(), self.line_number_area_width(), cr.height())

    def line_number_area_paint(self, event):
        """Paint line numbers in the gutter."""
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), QColor(_MARGIN_BG))

        block = self.firstVisibleBlock()
        block_num = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        current_line = self.textCursor().blockNumber()

        painter.setFont(_make_font())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                # Highlight current line number
                if block_num == current_line:
                    painter.setPen(QColor(_MARGIN_CURRENT))
                else:
                    painter.setPen(QColor(_MARGIN_FG))
                painter.drawText(
                    0,
                    top,
                    self._line_area.width() - 8,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(block_num + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_num += 1

        painter.end()

    # ── Indent guides ────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        """Override to draw indent guides before the text."""
        super().paintEvent(event)

        if not self._indent_guides_enabled:
            return

        painter = QPainter(self.viewport())
        pen = QPen(QColor(_INDENT_GUIDE))
        pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)

        block = self.firstVisibleBlock()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        char_width = self.fontMetrics().horizontalAdvance(" ")

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                text = block.text()
                if text.strip():  # only for non-empty lines
                    indent_level = len(text) - len(text.lstrip())
                    tab = self._tab_width
                    for level in range(tab, indent_level + 1, tab):
                        x = int(self.contentOffset().x()) + level * char_width
                        painter.drawLine(x, top, x, bottom)

            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())

        painter.end()

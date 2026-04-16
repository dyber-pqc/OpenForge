"""Editor panel with tabbed code editors and Verilog syntax highlighting.

Uses QScintilla (Qsci) when available, falls back to QPlainTextEdit
with a custom QSyntaxHighlighter for Verilog/SystemVerilog.

Features: auto-completion, bracket matching, go-to-line, indent/unindent,
comment/uncomment, word-wrap toggle, minimap, and rich context menus.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from PySide6.QtCore import QRect, QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# Try to import QScintilla (PySide6 bindings)
_HAS_QSCI = False
try:
    from Qsci import QsciLexerVerilog, QsciScintilla  # type: ignore[import-untyped]

    _HAS_QSCI = True
except ImportError:
    pass

# ── Theme constants ���─────────────────────────────────────────────────────

_MONO_FONT_FAMILY: Final[str] = "JetBrains Mono"
_MONO_FONT_SIZE: Final[int] = 11
_BG: Final[str] = "#1e1e2e"
_FG: Final[str] = "#cdd6f4"
_MARGIN_BG: Final[str] = "#181825"
_MARGIN_FG: Final[str] = "#585b70"
_CARET: Final[str] = "#f5e0dc"
_SEL_BG: Final[str] = "#45475a"
_LINE_BG: Final[str] = "#11111b"
_BRACKET_BG: Final[str] = "#585b70"
_BRACKET_FG: Final[str] = "#f9e2af"
_MINIMAP_BG: Final[str] = "#181825"
_MINIMAP_VIEWPORT: Final[str] = "#313244"

# Verilog keyword lists for syntax highlighting and auto-completion
_KEYWORDS = {
    "module",
    "endmodule",
    "input",
    "output",
    "inout",
    "wire",
    "reg",
    "logic",
    "assign",
    "always",
    "always_ff",
    "always_comb",
    "always_latch",
    "begin",
    "end",
    "if",
    "else",
    "case",
    "casex",
    "casez",
    "endcase",
    "for",
    "while",
    "repeat",
    "forever",
    "generate",
    "endgenerate",
    "function",
    "endfunction",
    "task",
    "endtask",
    "parameter",
    "localparam",
    "defparam",
    "typedef",
    "enum",
    "struct",
    "initial",
    "posedge",
    "negedge",
    "or",
    "and",
    "not",
    "integer",
    "real",
    "time",
    "genvar",
    "assert",
    "assume",
    "cover",
    "property",
    "endproperty",
    "sequence",
    "endsequence",
    "disable",
    "iff",
    "interface",
    "endinterface",
    "modport",
    "clocking",
    "endclocking",
    "package",
    "endpackage",
    "import",
    "export",
}

_TYPES = {
    "bit",
    "byte",
    "shortint",
    "int",
    "longint",
    "shortreal",
    "string",
    "void",
    "automatic",
    "static",
    "signed",
    "unsigned",
}

# Combined keywords for auto-completion
_ALL_COMPLETIONS: list[str] = sorted(_KEYWORDS | _TYPES)

# Bracket pairs
_OPEN_BRACKETS = {"(": ")", "[": "]", "{": "}"}
_CLOSE_BRACKETS = {")": "(", "]": "[", "}": "{"}
_BLOCK_OPEN = "begin"
_BLOCK_CLOSE = "end"


def _make_font() -> QFont:
    font = QFont(_MONO_FONT_FAMILY, _MONO_FONT_SIZE)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


# ── QSyntaxHighlighter for Verilog (fallback when QScintilla unavailable) ─


class VerilogHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for Verilog/SystemVerilog using QRegularExpression."""

    def __init__(self, parent: QTextDocument | None = None) -> None:
        super().__init__(parent)

        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

        # Keywords (purple)
        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor("#cba6f7"))
        kw_fmt.setFontWeight(QFont.Weight.Bold)
        kw_pattern = r"\b(" + "|".join(_KEYWORDS) + r")\b"
        self._rules.append((QRegularExpression(kw_pattern), kw_fmt))

        # Types (blue)
        type_fmt = QTextCharFormat()
        type_fmt.setForeground(QColor("#89b4fa"))
        type_pattern = r"\b(" + "|".join(_TYPES) + r")\b"
        self._rules.append((QRegularExpression(type_pattern), type_fmt))

        # Numbers (yellow)
        num_fmt = QTextCharFormat()
        num_fmt.setForeground(QColor("#f9e2af"))
        self._rules.append((QRegularExpression(r"\b\d+'[bBhHdDoO][0-9a-fA-FxXzZ_]+\b"), num_fmt))
        self._rules.append((QRegularExpression(r"\b\d+\b"), num_fmt))

        # Strings (teal)
        str_fmt = QTextCharFormat()
        str_fmt.setForeground(QColor("#94e2d5"))
        self._rules.append((QRegularExpression(r'"[^"]*"'), str_fmt))

        # Preprocessor (peach)
        pp_fmt = QTextCharFormat()
        pp_fmt.setForeground(QColor("#fab387"))
        self._rules.append((QRegularExpression(r"`\w+"), pp_fmt))

        # Operators (red)
        op_fmt = QTextCharFormat()
        op_fmt.setForeground(QColor("#f38ba8"))
        self._rules.append((QRegularExpression(r"[{}()\[\];:,=<>!&|^~?+\-*/]"), op_fmt))

        # Single-line comment (green)
        self._comment_fmt = QTextCharFormat()
        self._comment_fmt.setForeground(QColor("#a6e3a1"))
        self._comment_fmt.setFontItalic(True)
        self._rules.append((QRegularExpression(r"//[^\n]*"), self._comment_fmt))

        # Multi-line comment markers
        self._ml_start = QRegularExpression(r"/\*")
        self._ml_end = QRegularExpression(r"\*/")

    def highlightBlock(self, text: str) -> None:
        # Apply single-line rules
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                match = it.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)

        # Multi-line comments
        self.setCurrentBlockState(0)
        start_index = 0

        if self.previousBlockState() != 1:
            m = self._ml_start.match(text)
            start_index = m.capturedStart() if m.hasMatch() else -1
        else:
            start_index = 0

        while start_index >= 0:
            end_match = self._ml_end.match(text, start_index + 2)
            if end_match.hasMatch():
                length = end_match.capturedEnd() - start_index
            else:
                self.setCurrentBlockState(1)
                length = len(text) - start_index

            self.setFormat(start_index, length, self._comment_fmt)

            next_match = self._ml_start.match(text, start_index + length)
            start_index = next_match.capturedStart() if next_match.hasMatch() else -1


# ── Line number area for QPlainTextEdit ────��─────────────────────────────


class _LineNumberArea(QWidget):
    """Paints line numbers alongside a QPlainTextEdit."""

    def __init__(self, editor: _CodeEditor) -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return self._editor.line_number_area_size()

    def paintEvent(self, event):
        self._editor.line_number_area_paint(event)


# ── Auto-completion popup ─────────���──────────────────────────────────────


class _CompletionPopup(QListWidget):
    """Popup list for Verilog keyword auto-completion."""

    completion_accepted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.ToolTip)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMaximumHeight(200)
        self.setMaximumWidth(280)
        self.setStyleSheet(f"""
            QListWidget {{
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #585b70;
                border-radius: 4px;
                font-family: "{_MONO_FONT_FAMILY}", monospace;
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

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        if item:
            self.completion_accepted.emit(item.text())
            self.hide()

    def update_completions(self, prefix: str) -> None:
        """Filter and show completions matching the given prefix."""
        self.clear()
        if len(prefix) < 3:
            self.hide()
            return
        prefix_lower = prefix.lower()
        matches = [kw for kw in _ALL_COMPLETIONS if kw.startswith(prefix_lower)]
        if not matches:
            self.hide()
            return
        for kw in matches:
            self.addItem(kw)
        self.setCurrentRow(0)
        self.show()

    def accept_current(self) -> bool:
        """Accept the currently selected completion. Returns True if accepted."""
        item = self.currentItem()
        if item and self.isVisible():
            self.completion_accepted.emit(item.text())
            self.hide()
            return True
        return False

    def move_selection(self, delta: int) -> None:
        """Move selection up or down."""
        if not self.isVisible():
            return
        row = self.currentRow() + delta
        row = max(0, min(row, self.count() - 1))
        self.setCurrentRow(row)


# ── Minimap widget ──────────────────────────────────────���────────────────


class _Minimap(QPlainTextEdit):
    """Narrow read-only preview of the editor content (minimap)."""

    scroll_requested = Signal(float)  # normalized 0.0-1.0

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
        self._viewport_ratio_start: float = 0.0
        self._viewport_ratio_end: float = 0.1

    def set_viewport_highlight(self, start: float, end: float) -> None:
        """Set the highlighted viewport region (0.0 to 1.0)."""
        self._viewport_ratio_start = start
        self._viewport_ratio_end = end
        self.viewport().update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        # Draw viewport highlight overlay
        painter = QPainter(self.viewport())
        rect = self.viewport().rect()
        h = rect.height()
        y_start = int(h * self._viewport_ratio_start)
        y_end = int(h * self._viewport_ratio_end)
        painter.fillRect(
            QRect(0, y_start, rect.width(), max(y_end - y_start, 10)),
            QColor(69, 71, 90, 80),  # semi-transparent surface1
        )
        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            ratio = event.position().y() / max(self.viewport().height(), 1)
            self.scroll_requested.emit(max(0.0, min(1.0, ratio)))

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            ratio = event.position().y() / max(self.viewport().height(), 1)
            self.scroll_requested.emit(max(0.0, min(1.0, ratio)))


class _CodeEditor(QPlainTextEdit):
    """QPlainTextEdit with line numbers, current-line highlight, bracket
    matching, auto-completion, indent/unindent, comment toggle, and
    syntax highlighting.
    """

    # Signal emitted when cursor position changes: (line, col)
    cursor_position_changed = Signal(int, int)
    # Signal emitted when document is modified
    modification_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None, verilog: bool = True) -> None:
        super().__init__(parent)

        font = _make_font()
        self.setFont(font)
        self.setTabStopDistance(font.pointSizeF() * 4)

        # Colors
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

        # Ensure caret is visible against dark background
        self.setCursorWidth(2)

        # Line number area
        self._line_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self.cursorPositionChanged.connect(self._highlight_current_line_and_brackets)
        self.cursorPositionChanged.connect(self._emit_cursor_pos)
        self._update_line_area_width(0)
        self._highlight_current_line_and_brackets()

        # Syntax highlighter (only for Verilog/SV files)
        self._highlighter: VerilogHighlighter | None = None
        self._is_verilog = verilog
        if verilog:
            self._highlighter = VerilogHighlighter(self.document())

        # Track modification
        self.document().modificationChanged.connect(self._on_modification_changed)

        # Auto-completion popup
        self._completion_popup = _CompletionPopup(self)
        self._completion_popup.hide()
        self._completion_popup.completion_accepted.connect(self._accept_completion)
        self._completion_timer = QTimer(self)
        self._completion_timer.setSingleShot(True)
        self._completion_timer.setInterval(150)
        self._completion_timer.timeout.connect(self._update_completions)
        self.textChanged.connect(self._schedule_completion_update)

        # Word wrap state
        self._word_wrap_enabled = False
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    # ── Auto-completion ───��───────────────────────────────────────

    def _schedule_completion_update(self) -> None:
        if self._is_verilog:
            self._completion_timer.start()

    def _current_word_prefix(self) -> str:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfWord, QTextCursor.MoveMode.KeepAnchor)
        return cursor.selectedText()

    def _update_completions(self) -> None:
        prefix = self._current_word_prefix()
        if len(prefix) < 3:
            self._completion_popup.hide()
            return
        self._completion_popup.update_completions(prefix)
        if self._completion_popup.count() > 0:
            # Position popup below cursor
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

    # ── Bracket matching ──────────────────────────────────────────

    def _find_matching_bracket(self, pos: int, char: str) -> int:
        """Find the position of the matching bracket. Returns -1 if not found."""
        doc = self.document()
        full_text = doc.toPlainText()
        if char in _OPEN_BRACKETS:
            target = _OPEN_BRACKETS[char]
            direction = 1
            start_char = char
        elif char in _CLOSE_BRACKETS:
            target = char
            start_char = _CLOSE_BRACKETS[char]
            direction = -1
        else:
            return -1

        depth = 0
        i = pos
        while 0 <= i < len(full_text):
            c = full_text[i]
            if c == start_char:
                depth += 1
            elif c == target:
                depth -= 1
                if depth == 0:
                    return i
            i += direction
        return -1

    def _highlight_current_line_and_brackets(self) -> None:
        """Highlight current line and matching brackets."""
        from PySide6.QtWidgets import QTextEdit

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

        if pos < len(doc_text):
            char = doc_text[pos]
            if char in _OPEN_BRACKETS or char in _CLOSE_BRACKETS:
                match_pos = self._find_matching_bracket(pos, char)
                if match_pos >= 0:
                    # Highlight the bracket at cursor
                    for bp in (pos, match_pos):
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

        # Also check character before cursor
        if pos > 0:
            prev_char = doc_text[pos - 1]
            if prev_char in _OPEN_BRACKETS or prev_char in _CLOSE_BRACKETS:
                match_pos = self._find_matching_bracket(pos - 1, prev_char)
                if match_pos >= 0:
                    for bp in (pos - 1, match_pos):
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

        self.setExtraSelections(selections)

    # ── Go to line ────────────────────────────────────────────────

    def go_to_line(self) -> None:
        """Show a dialog and scroll to the entered line number."""
        max_line = self.blockCount()
        line, ok = QInputDialog.getInt(
            self,
            "Go to Line",
            f"Line number (1-{max_line}):",
            self.textCursor().blockNumber() + 1,  # value
            1,  # min
            max_line,  # max
        )
        if ok:
            block = self.document().findBlockByLineNumber(line - 1)
            cursor = self.textCursor()
            cursor.setPosition(block.position())
            self.setTextCursor(cursor)
            self.centerCursor()

    # ── Indent / Unindent ─────────────────��───────────────────────

    def indent_selection(self) -> None:
        """Indent all selected lines by one tab (4 spaces)."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.insertText("    ")
            return
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.beginEditBlock()
        while cursor.position() <= end and not cursor.atEnd():
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.insertText("    ")
            end += 4
            if not cursor.movePosition(QTextCursor.MoveOperation.NextBlock):
                break
        cursor.endEditBlock()

    def unindent_selection(self) -> None:
        """Remove one level of indentation from selected lines."""
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.beginEditBlock()
        while cursor.position() <= end and not cursor.atEnd():
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            line = cursor.block().text()
            if line.startswith("    "):
                cursor.movePosition(
                    QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 4
                )
                cursor.removeSelectedText()
                end -= 4
            elif line.startswith("\t"):
                cursor.movePosition(
                    QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1
                )
                cursor.removeSelectedText()
                end -= 1
            if not cursor.movePosition(QTextCursor.MoveOperation.NextBlock):
                break
        cursor.endEditBlock()

    # ── Comment / Uncomment toggle ────────────────────────────────

    def toggle_comment(self) -> None:
        """Toggle // comment prefix on selected lines or current line."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            start = cursor.selectionStart()
            end = cursor.selectionEnd()
        else:
            start = cursor.position()
            end = cursor.position()

        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.beginEditBlock()

        # First pass: determine if we're commenting or uncommenting
        check_cursor = self.textCursor()
        check_cursor.setPosition(start)
        check_cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        all_commented = True
        while check_cursor.position() <= end and not check_cursor.atEnd():
            line = check_cursor.block().text()
            stripped = line.lstrip()
            if stripped and not stripped.startswith("//"):
                all_commented = False
                break
            if not check_cursor.movePosition(QTextCursor.MoveOperation.NextBlock):
                break

        # Second pass: apply the toggle
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        while cursor.position() <= end and not cursor.atEnd():
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            line = cursor.block().text()
            if all_commented:
                # Uncomment: remove first //
                idx = line.find("//")
                if idx >= 0:
                    cursor.movePosition(
                        QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, idx
                    )
                    cursor.movePosition(
                        QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 2
                    )
                    # Also remove a trailing space if present
                    if cursor.selectedText() == "//":
                        cursor.position()
                        remaining = line[idx + 2 :]
                        if remaining.startswith(" "):
                            cursor.movePosition(
                                QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1
                            )
                            end -= 3
                        else:
                            end -= 2
                    cursor.removeSelectedText()
            else:
                # Comment: add // at start of line
                cursor.insertText("// ")
                end += 3
            if not cursor.movePosition(QTextCursor.MoveOperation.NextBlock):
                break
        cursor.endEditBlock()

    # ── Word wrap toggle ──────────────────────────────────────────

    def toggle_word_wrap(self) -> None:
        """Toggle word wrap mode."""
        self._word_wrap_enabled = not self._word_wrap_enabled
        if self._word_wrap_enabled:
            self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        else:
            self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    @property
    def word_wrap_enabled(self) -> bool:
        return self._word_wrap_enabled

    # ── Key event handling ─────────���──────────────────────────────

    def keyPressEvent(self, event) -> None:
        # Handle completion popup keys
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

        # Ctrl+/ for comment toggle (explicit handling for Windows compatibility)
        if (
            event.key() == Qt.Key.Key_Slash
            and event.modifiers() == Qt.KeyboardModifier.ControlModifier
        ):
            self.toggle_comment()
            return

        # Ctrl+G for go-to-line
        if event.key() == Qt.Key.Key_G and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.go_to_line()
            return

        # Tab / Shift+Tab for indent/unindent when text is selected
        if event.key() == Qt.Key.Key_Tab and self.textCursor().hasSelection():
            self.indent_selection()
            return
        if event.key() == Qt.Key.Key_Backtab:
            self.unindent_selection()
            return

        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        self._completion_popup.hide()
        super().focusOutEvent(event)

    # ── Context menu ──────────────────────────────────────────────

    def contextMenuEvent(self, event) -> None:
        """Rich right-click context menu for the editor."""
        menu = QMenu(self)

        # Clipboard operations
        menu.addAction("Cut", self.cut, QKeySequence.StandardKey.Cut)
        menu.addAction("Copy", self.copy, QKeySequence.StandardKey.Copy)
        menu.addAction("Paste", self.paste, QKeySequence.StandardKey.Paste)
        menu.addAction("Select All", self.selectAll, QKeySequence.StandardKey.SelectAll)
        menu.addSeparator()

        # Navigation
        menu.addAction("Go to Definition", lambda: None).setToolTip("Placeholder")
        menu.addAction("Find References", lambda: None).setToolTip("Placeholder")
        menu.addAction("Rename Symbol...", lambda: None).setToolTip("Placeholder")
        menu.addSeparator()

        # Code editing
        menu.addAction("Comment/Uncomment Selection", self.toggle_comment)
        indent_menu = menu.addMenu("Indentation")
        indent_menu.addAction("Indent", self.indent_selection)
        indent_menu.addAction("Unindent", self.unindent_selection)
        menu.addSeparator()

        menu.addAction("Format Document", lambda: None).setToolTip("Placeholder")
        menu.addSeparator()

        # EDA-specific actions
        menu.addAction("Add to Waveform Viewer", lambda: None).setToolTip("Placeholder")
        menu.addAction("Simulate This Module", lambda: None).setToolTip("Placeholder")
        menu.addAction("Synthesize This Module", lambda: None).setToolTip("Placeholder")

        menu.exec(event.globalPos())

    # ── Cursor position / modification signals ────────────────────

    def _emit_cursor_pos(self) -> None:
        cursor = self.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        self.cursor_position_changed.emit(line, col)

    def _on_modification_changed(self, changed: bool) -> None:
        self.modification_changed.emit(changed)

    # ── Line number area ──────────────────────────────────────────

    def line_number_area_size(self):
        digits = max(1, len(str(self.blockCount())))
        space = 12 + self.fontMetrics().horizontalAdvance("9") * digits
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(cr.left(), cr.top(), self.line_number_area_width(), cr.height())

    def line_number_area_paint(self, event):
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), QColor(_MARGIN_BG))

        block = self.firstVisibleBlock()
        block_num = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        painter.setFont(_make_font())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor(_MARGIN_FG))
                painter.drawText(
                    0,
                    top,
                    self._line_area.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(block_num + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_num += 1

        painter.end()


# ── Editor Panel ──────���──────────────────────────────────────────────────


class EditorPanel(QWidget):
    """Central editor panel with tabbed interface for source files."""

    # Signal emitted when cursor position changes: (line, col)
    cursor_position_changed = Signal(int, int)

    # Verilog/SystemVerilog file extensions
    _VERILOG_EXTS: set[str] = {".v", ".sv", ".svh", ".vh"}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Horizontal layout for tabs + minimap
        self._editor_row = QHBoxLayout()
        self._editor_row.setContentsMargins(0, 0, 0, 0)
        self._editor_row.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        # Right-click on tab bar for context menu
        self._tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tabs.tabBar().customContextMenuRequested.connect(self._on_tab_context_menu)
        self._editor_row.addWidget(self._tabs, stretch=1)

        # Minimap
        self._minimap = _Minimap(self)
        self._minimap.scroll_requested.connect(self._on_minimap_scroll)
        self._minimap.setVisible(False)  # hidden by default
        self._editor_row.addWidget(self._minimap)

        layout.addLayout(self._editor_row)

        # File path tracking
        self._file_paths: dict[int, Path | None] = {}

        # Search bar
        self._search_bar = _SearchBar(self)
        self._search_bar.setVisible(False)
        layout.addWidget(self._search_bar)

        # Minimap sync timer
        self._minimap_sync_timer = QTimer(self)
        self._minimap_sync_timer.setInterval(300)
        self._minimap_sync_timer.timeout.connect(self._sync_minimap)

    @staticmethod
    def _is_verilog(path: Path | None) -> bool:
        """Return True if the path is a Verilog/SystemVerilog file."""
        if path is None:
            return True  # default for new files
        return path.suffix.lower() in EditorPanel._VERILOG_EXTS

    def new_file(
        self,
        content: str = "",
        title: str = "untitled",
        path: Path | None = None,
    ) -> QWidget:
        """Create a new editor tab."""
        use_verilog = self._is_verilog(path)
        editor = _CodeEditor(verilog=use_verilog)
        editor.setPlainText(content)
        # Reset modification state after initial content load
        editor.document().setModified(False)
        idx = self._tabs.addTab(editor, title)
        self._file_paths[idx] = path

        # Connect cursor position signal
        editor.cursor_position_changed.connect(
            lambda line, col: self.cursor_position_changed.emit(line, col),
        )

        # Connect modification tracking to update tab title with asterisk
        def _on_mod_changed(modified: bool, ed: QWidget = editor) -> None:
            tab_idx = self._tabs.indexOf(ed)
            if tab_idx < 0:
                return
            base_title = self._tabs.tabText(tab_idx).rstrip(" *")
            if modified:
                self._tabs.setTabText(tab_idx, base_title + " *")
            else:
                self._tabs.setTabText(tab_idx, base_title)

        editor.modification_changed.connect(_on_mod_changed)

        # Sync minimap when text changes
        editor.textChanged.connect(self._sync_minimap_content)
        editor.verticalScrollBar().valueChanged.connect(self._sync_minimap_viewport)

        self._tabs.setCurrentIndex(idx)
        return editor

    def open_file(self, path: Path) -> QWidget:
        """Open a file in a new editor tab.

        If the file is already open, switch to its tab.
        """
        # Check if already open
        for idx, p in self._file_paths.items():
            if p is not None and p.resolve() == path.resolve():
                self._tabs.setCurrentIndex(idx)
                return self._tabs.widget(idx)

        text = path.read_text(encoding="utf-8", errors="replace")
        editor = self.new_file(text, path.name, path=path)
        idx = self._tabs.currentIndex()
        self._file_paths[idx] = path
        return editor

    def open_file_dialog(self, start_dir: str = "") -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Open Source File",
            start_dir,
            "Verilog (*.v *.sv *.vh *.svh);;VHDL (*.vhd *.vhdl);;All (*)",
        )
        if path_str:
            self.open_file(Path(path_str))

    def save_current(self) -> None:
        idx = self._tabs.currentIndex()
        if idx < 0:
            return
        path = self._file_paths.get(idx)
        if path is None:
            self.save_current_as()
            return
        editor = self._tabs.widget(idx)
        if isinstance(editor, _CodeEditor):
            path.write_text(editor.toPlainText(), encoding="utf-8")
            editor.document().setModified(False)

    def save_current_as(self) -> None:
        idx = self._tabs.currentIndex()
        if idx < 0:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save File As",
            "",
            "Verilog (*.v *.sv);;All (*)",
        )
        if path_str:
            path = Path(path_str)
            editor = self._tabs.widget(idx)
            if isinstance(editor, _CodeEditor):
                path.write_text(editor.toPlainText(), encoding="utf-8")
                editor.document().setModified(False)
            self._file_paths[idx] = path
            self._tabs.setTabText(idx, path.name)

    def close_current_tab(self) -> None:
        idx = self._tabs.currentIndex()
        if idx >= 0:
            self._close_tab(idx)

    def show_search(self, *, replace: bool = False) -> None:
        self._search_bar.setVisible(True)
        self._search_bar.set_replace_visible(replace)
        self._search_bar.focus_search()

    # ── Go to line (public, for menu wiring) ──────────────────────

    def go_to_line(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.go_to_line()

    # ── Comment toggle (public) ───────────────────────────────────

    def toggle_comment(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.toggle_comment()

    # ── Word wrap toggle (public) ─────────────────────────────────

    def toggle_word_wrap(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.toggle_word_wrap()

    # ── Minimap toggle ───────��────────────────────────────────────

    def toggle_minimap(self) -> None:
        visible = not self._minimap.isVisible()
        self._minimap.setVisible(visible)
        if visible:
            self._sync_minimap_content()
            self._sync_minimap_viewport()

    @property
    def minimap_visible(self) -> bool:
        return self._minimap.isVisible()

    def _on_tab_changed(self, _index: int) -> None:
        if self._minimap.isVisible():
            self._sync_minimap_content()
            self._sync_minimap_viewport()

    def _sync_minimap_content(self) -> None:
        editor = self._current_editor()
        if editor and self._minimap.isVisible():
            self._minimap.setPlainText(editor.toPlainText())

    def _sync_minimap_viewport(self) -> None:
        editor = self._current_editor()
        if editor and self._minimap.isVisible():
            sb = editor.verticalScrollBar()
            max_val = max(sb.maximum(), 1)
            start = sb.value() / max_val
            page = sb.pageStep() / (max_val + sb.pageStep())
            self._minimap.set_viewport_highlight(start, start + page)

    def _sync_minimap(self) -> None:
        self._sync_minimap_content()
        self._sync_minimap_viewport()

    def _on_minimap_scroll(self, ratio: float) -> None:
        editor = self._current_editor()
        if editor:
            sb = editor.verticalScrollBar()
            sb.setValue(int(ratio * sb.maximum()))

    # ── Zoom ──────���───────────────────────────────────────────────

    def zoom_in(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.zoomIn(1)

    def zoom_out(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.zoomOut(1)

    def zoom_reset(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.setFont(_make_font())

    # ── Internal tab management ────���──────────────────────────────

    def _close_tab(self, index: int) -> None:
        self._tabs.removeTab(index)
        # Re-index file paths: shift all indices above the removed one
        new_paths: dict[int, Path | None] = {}
        for old_idx, p in self._file_paths.items():
            if old_idx == index:
                continue
            new_idx = old_idx if old_idx < index else old_idx - 1
            new_paths[new_idx] = p
        self._file_paths = new_paths

    def _current_editor(self) -> _CodeEditor | None:
        widget = self._tabs.currentWidget()
        return widget if isinstance(widget, _CodeEditor) else None

    def _on_tab_context_menu(self, position) -> None:
        """Right-click context menu on editor tabs."""
        tab_bar = self._tabs.tabBar()
        idx = tab_bar.tabAt(position)
        if idx < 0:
            return

        menu = QMenu(self)
        menu.addAction("Close", lambda: self._close_tab(idx))
        menu.addAction("Close Others", lambda: self._close_others(idx))
        menu.addAction("Close All", lambda: self._close_all())
        menu.addSeparator()

        path = self._file_paths.get(idx)
        if path:
            menu.addAction("Copy Path", lambda: QApplication.clipboard().setText(str(path)))
            menu.addAction("Copy Name", lambda: QApplication.clipboard().setText(path.name))
            menu.addSeparator()
            menu.addAction("Reveal in Explorer", lambda: self._reveal_in_explorer(path))

        menu.exec(tab_bar.mapToGlobal(position))

    def _close_others(self, keep_idx: int) -> None:
        """Close all tabs except the one at keep_idx."""
        for i in range(self._tabs.count() - 1, -1, -1):
            if i != keep_idx:
                self._close_tab(i)

    def _close_all(self) -> None:
        """Close all tabs."""
        while self._tabs.count() > 0:
            self._close_tab(0)

    def _reveal_in_explorer(self, path: Path) -> None:
        """Open the file's containing folder in the system file explorer."""
        import subprocess
        import sys

        folder = str(path.parent)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", folder])


# ── Search bar ───────────────────────────────────────────────────────────


class _SearchBar(QWidget):
    search_requested = Signal(str, bool)
    replace_requested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        layout.addWidget(QLabel("Find:"))
        self._find = QLineEdit()
        self._find.setPlaceholderText("Search...")
        self._find.returnPressed.connect(
            lambda: self.search_requested.emit(self._find.text(), True)
        )
        layout.addWidget(self._find)

        btn_prev = QPushButton("Prev")
        btn_prev.setFixedWidth(50)
        btn_prev.clicked.connect(lambda: self.search_requested.emit(self._find.text(), False))
        layout.addWidget(btn_prev)

        btn_next = QPushButton("Next")
        btn_next.setFixedWidth(50)
        btn_next.clicked.connect(lambda: self.search_requested.emit(self._find.text(), True))
        layout.addWidget(btn_next)

        self._replace_label = QLabel("Replace:")
        layout.addWidget(self._replace_label)
        self._replace_input = QLineEdit()
        self._replace_input.setPlaceholderText("Replace with...")
        layout.addWidget(self._replace_input)
        self._btn_replace = QPushButton("Replace")
        self._btn_replace.setFixedWidth(64)
        self._btn_replace.clicked.connect(
            lambda: self.replace_requested.emit(self._find.text(), self._replace_input.text())
        )
        layout.addWidget(self._btn_replace)

        btn_close = QPushButton("X")
        btn_close.setFixedWidth(24)
        btn_close.clicked.connect(lambda: self.setVisible(False))
        layout.addWidget(btn_close)

    def set_replace_visible(self, visible: bool) -> None:
        for w in (self._replace_label, self._replace_input, self._btn_replace):
            w.setVisible(visible)

    def focus_search(self) -> None:
        self._find.setFocus()
        self._find.selectAll()

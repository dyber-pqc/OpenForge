"""Editor panel with tabbed code editors and Verilog syntax highlighting.

Uses QScintilla (Qsci) when available, falls back to QPlainTextEdit
with a custom QSyntaxHighlighter for Verilog/SystemVerilog.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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

# ── Theme constants ──────────────────────────────────────────────────────

_MONO_FONT_FAMILY: Final[str] = "JetBrains Mono"
_MONO_FONT_SIZE: Final[int] = 11
_BG: Final[str] = "#1e1e2e"
_FG: Final[str] = "#cdd6f4"
_MARGIN_BG: Final[str] = "#181825"
_MARGIN_FG: Final[str] = "#585b70"
_CARET: Final[str] = "#f5e0dc"
_SEL_BG: Final[str] = "#45475a"
_LINE_BG: Final[str] = "#11111b"

# Verilog keyword lists for syntax highlighting
_KEYWORDS = {
    "module", "endmodule", "input", "output", "inout", "wire", "reg", "logic",
    "assign", "always", "always_ff", "always_comb", "always_latch",
    "begin", "end", "if", "else", "case", "casex", "casez", "endcase",
    "for", "while", "repeat", "forever", "generate", "endgenerate",
    "function", "endfunction", "task", "endtask",
    "parameter", "localparam", "defparam", "typedef", "enum", "struct",
    "initial", "posedge", "negedge", "or", "and", "not",
    "integer", "real", "time", "genvar",
    "assert", "assume", "cover", "property", "endproperty",
    "sequence", "endsequence", "disable", "iff",
    "interface", "endinterface", "modport", "clocking", "endclocking",
    "package", "endpackage", "import", "export",
}

_TYPES = {
    "bit", "byte", "shortint", "int", "longint", "shortreal",
    "string", "void", "automatic", "static", "signed", "unsigned",
}


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


# ── Line number area for QPlainTextEdit ──────────────────────────────────

class _LineNumberArea(QWidget):
    """Paints line numbers alongside a QPlainTextEdit."""

    def __init__(self, editor: _CodeEditor) -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return self._editor.line_number_area_size()

    def paintEvent(self, event):
        self._editor.line_number_area_paint(event)


class _CodeEditor(QPlainTextEdit):
    """QPlainTextEdit with line numbers, current-line highlight, and syntax highlighting."""

    def __init__(self, parent: QWidget | None = None) -> None:
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

        # Line number area
        self._line_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_line_area_width(0)
        self._highlight_current_line()

        # Syntax highlighter
        self._highlighter = VerilogHighlighter(self.document())

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
                    0, top, self._line_area.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, str(block_num + 1)
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_num += 1

        painter.end()

    def _highlight_current_line(self):
        selections = []
        if not self.isReadOnly():
            selection = QPlainTextEdit.ExtraSelection()
            selection.format.setBackground(QColor(_LINE_BG))
            selection.format.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            selections.append(selection)
        self.setExtraSelections(selections)


# ── Editor Panel ─────────────────────────────────────────────────────────

class EditorPanel(QWidget):
    """Central editor panel with tabbed interface for source files."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        layout.addWidget(self._tabs)

        # File path tracking
        self._file_paths: dict[int, Path | None] = {}

        # Search bar
        self._search_bar = _SearchBar(self)
        self._search_bar.setVisible(False)
        layout.addWidget(self._search_bar)

    def new_file(self, content: str = "", title: str = "untitled") -> QWidget:
        """Create a new editor tab."""
        editor = _CodeEditor()
        editor.setPlainText(content)
        idx = self._tabs.addTab(editor, title)
        self._file_paths[idx] = None
        self._tabs.setCurrentIndex(idx)
        return editor

    def open_file(self, path: Path) -> QWidget:
        """Open a file in a new editor tab."""
        text = path.read_text(encoding="utf-8", errors="replace")
        editor = self.new_file(text, path.name)
        idx = self._tabs.currentIndex()
        self._file_paths[idx] = path
        return editor

    def open_file_dialog(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open Source File", "",
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

    def save_current_as(self) -> None:
        idx = self._tabs.currentIndex()
        if idx < 0:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save File As", "",
            "Verilog (*.v *.sv);;All (*)",
        )
        if path_str:
            path = Path(path_str)
            editor = self._tabs.widget(idx)
            if isinstance(editor, _CodeEditor):
                path.write_text(editor.toPlainText(), encoding="utf-8")
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

    def _close_tab(self, index: int) -> None:
        self._file_paths.pop(index, None)
        self._tabs.removeTab(index)

    def _current_editor(self) -> _CodeEditor | None:
        widget = self._tabs.currentWidget()
        return widget if isinstance(widget, _CodeEditor) else None


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
        self._find.returnPressed.connect(lambda: self.search_requested.emit(self._find.text(), True))
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

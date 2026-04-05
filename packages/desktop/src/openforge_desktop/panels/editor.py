"""Editor panel with tabbed QScintilla code editors."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from Qsci import QsciLexerVerilog, QsciScintilla

# Default editor font
_MONO_FONT_FAMILY: Final[str] = "JetBrains Mono"
_MONO_FONT_SIZE: Final[int] = 11

# Scintilla colour palette (dark theme)
_BG: Final[str] = "#1e1e2e"
_FG: Final[str] = "#cdd6f4"
_MARGIN_BG: Final[str] = "#181825"
_MARGIN_FG: Final[str] = "#585b70"
_CARET: Final[str] = "#f5e0dc"
_SEL_BG: Final[str] = "#45475a"
_FOLD_BG: Final[str] = "#313244"
_BRACE_BG: Final[str] = "#45475a"
_BRACE_FG: Final[str] = "#89b4fa"


def _make_font() -> QFont:
    font = QFont(_MONO_FONT_FAMILY, _MONO_FONT_SIZE)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


def _configure_editor(editor: QsciScintilla) -> None:
    """Apply standard configuration to a QScintilla editor widget."""
    font = _make_font()
    editor.setFont(font)
    editor.setMarginsFont(font)

    # Line numbers
    editor.setMarginType(0, QsciScintilla.MarginType.NumberMargin)
    editor.setMarginWidth(0, "00000")
    editor.setMarginsForegroundColor(QColor(_MARGIN_FG))
    editor.setMarginsBackgroundColor(QColor(_MARGIN_BG))

    # Code folding
    editor.setFolding(QsciScintilla.FoldStyle.BoxedTreeFoldStyle, 1)
    editor.setFoldMarginColors(QColor(_FOLD_BG), QColor(_FOLD_BG))

    # Caret and selection
    editor.setCaretForegroundColor(QColor(_CARET))
    editor.setCaretLineVisible(True)
    editor.setCaretLineBackgroundColor(QColor("#11111b"))
    editor.setSelectionBackgroundColor(QColor(_SEL_BG))

    # Brace matching
    editor.setBraceMatching(QsciScintilla.BraceMatch.StrictBraceMatch)
    editor.setMatchedBraceForegroundColor(QColor(_BRACE_FG))
    editor.setMatchedBraceBackgroundColor(QColor(_BRACE_BG))

    # General appearance
    editor.setPaper(QColor(_BG))
    editor.setColor(QColor(_FG))
    editor.setIndentationsUseTabs(False)
    editor.setTabWidth(4)
    editor.setAutoIndent(True)
    editor.setIndentationGuides(True)
    editor.setIndentationGuidesForegroundColor(QColor("#313244"))
    editor.setEolMode(QsciScintilla.EolMode.EolUnix)
    editor.setWrapMode(QsciScintilla.WrapMode.WrapNone)

    # Edge column guide at 100 chars
    editor.setEdgeMode(QsciScintilla.EdgeMode.EdgeLine)
    editor.setEdgeColumn(100)
    editor.setEdgeColor(QColor("#313244"))


def _apply_verilog_lexer(editor: QsciScintilla) -> None:
    """Attach a Verilog lexer with dark theme colours."""
    lexer = QsciLexerVerilog(editor)
    font = _make_font()
    lexer.setFont(font)
    lexer.setDefaultPaper(QColor(_BG))
    lexer.setDefaultColor(QColor(_FG))

    # Token colours
    lexer.setColor(QColor("#cba6f7"), QsciLexerVerilog.Keyword)       # keywords: purple
    lexer.setColor(QColor("#89b4fa"), QsciLexerVerilog.KeywordSet2)   # types: blue
    lexer.setColor(QColor("#a6e3a1"), QsciLexerVerilog.Comment)       # comments: green
    lexer.setColor(QColor("#a6e3a1"), QsciLexerVerilog.CommentLine)
    lexer.setColor(QColor("#f9e2af"), QsciLexerVerilog.Number)        # numbers: yellow
    lexer.setColor(QColor("#f38ba8"), QsciLexerVerilog.Operator)      # operators: red
    lexer.setColor(QColor("#fab387"), QsciLexerVerilog.Preprocessor)  # preprocessor: peach
    lexer.setColor(QColor("#94e2d5"), QsciLexerVerilog.String)        # strings: teal

    # Set paper for all styles to match background
    for style_id in range(128):
        lexer.setPaper(QColor(_BG), style_id)
        lexer.setFont(font, style_id)

    editor.setLexer(lexer)


class EditorPanel(QWidget):
    """Central editor panel with a tabbed interface for source files."""

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

        # File path -> tab index tracking
        self._file_paths: dict[int, Path | None] = {}

        # Search bar (hidden by default)
        self._search_bar = _SearchBar(self)
        self._search_bar.setVisible(False)
        self._search_bar.search_requested.connect(self._do_search)
        self._search_bar.replace_requested.connect(self._do_replace)
        layout.addWidget(self._search_bar)

    # ── Public API ─────────────────────────────────────────────────

    def new_file(self, content: str = "", title: str = "untitled") -> QsciScintilla:
        """Create a new editor tab and return the editor widget."""
        editor = QsciScintilla()
        _configure_editor(editor)
        _apply_verilog_lexer(editor)
        editor.setText(content)

        idx = self._tabs.addTab(editor, title)
        self._file_paths[idx] = None
        self._tabs.setCurrentIndex(idx)
        return editor

    def open_file(self, path: Path) -> QsciScintilla:
        """Open a file in a new editor tab."""
        text = path.read_text(encoding="utf-8", errors="replace")
        editor = self.new_file(text, path.name)
        idx = self._tabs.currentIndex()
        self._file_paths[idx] = path
        return editor

    def open_file_dialog(self) -> None:
        """Show an open-file dialog and open the selected file."""
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Open Source File",
            "",
            "Verilog Files (*.v *.sv *.vh *.svh);;VHDL Files (*.vhd *.vhdl);;All Files (*)",
        )
        if path_str:
            self.open_file(Path(path_str))

    def save_current(self) -> None:
        """Save the current tab to its file path (or prompt Save As)."""
        idx = self._tabs.currentIndex()
        if idx < 0:
            return
        path = self._file_paths.get(idx)
        if path is None:
            self.save_current_as()
            return
        editor: QsciScintilla = self._tabs.widget(idx)  # type: ignore[assignment]
        path.write_text(editor.text(), encoding="utf-8")

    def save_current_as(self) -> None:
        """Prompt for a file path and save the current tab."""
        idx = self._tabs.currentIndex()
        if idx < 0:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save File As",
            "",
            "Verilog Files (*.v *.sv);;All Files (*)",
        )
        if path_str:
            path = Path(path_str)
            editor: QsciScintilla = self._tabs.widget(idx)  # type: ignore[assignment]
            path.write_text(editor.text(), encoding="utf-8")
            self._file_paths[idx] = path
            self._tabs.setTabText(idx, path.name)

    def close_current_tab(self) -> None:
        """Close the currently active tab."""
        idx = self._tabs.currentIndex()
        if idx >= 0:
            self._close_tab(idx)

    def show_search(self, *, replace: bool = False) -> None:
        """Show the search (and optionally replace) bar."""
        self._search_bar.setVisible(True)
        self._search_bar.set_replace_visible(replace)
        self._search_bar.focus_search()

    # ── Internal ───────────────────────────────────────────────────

    def _close_tab(self, index: int) -> None:
        self._file_paths.pop(index, None)
        self._tabs.removeTab(index)

    def _current_editor(self) -> QsciScintilla | None:
        widget = self._tabs.currentWidget()
        return widget if isinstance(widget, QsciScintilla) else None

    def _do_search(self, text: str, forward: bool) -> None:
        editor = self._current_editor()
        if editor is None or not text:
            return
        editor.findFirst(text, False, False, False, True, forward)

    def _do_replace(self, find_text: str, replace_text: str) -> None:
        editor = self._current_editor()
        if editor is None or not find_text:
            return
        if editor.findFirst(find_text, False, False, False, True):
            editor.replace(replace_text)


# ---------------------------------------------------------------------------
# Inline search / replace bar
# ---------------------------------------------------------------------------

from PySide6.QtCore import Signal  # noqa: E402


class _SearchBar(QWidget):
    """Inline search and replace bar for the editor panel."""

    search_requested: Signal = Signal(str, bool)   # text, forward
    replace_requested: Signal = Signal(str, str)    # find, replace

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        layout.addWidget(QLabel("Find:"))
        self._find_input = QLineEdit()
        self._find_input.setPlaceholderText("Search...")
        self._find_input.returnPressed.connect(self._on_find_next)
        layout.addWidget(self._find_input)

        btn_prev = QPushButton("Prev")
        btn_prev.setFixedWidth(50)
        btn_prev.clicked.connect(self._on_find_prev)
        layout.addWidget(btn_prev)

        btn_next = QPushButton("Next")
        btn_next.setFixedWidth(50)
        btn_next.clicked.connect(self._on_find_next)
        layout.addWidget(btn_next)

        self._replace_label = QLabel("Replace:")
        layout.addWidget(self._replace_label)

        self._replace_input = QLineEdit()
        self._replace_input.setPlaceholderText("Replace with...")
        layout.addWidget(self._replace_input)

        self._btn_replace = QPushButton("Replace")
        self._btn_replace.setFixedWidth(64)
        self._btn_replace.clicked.connect(self._on_replace)
        layout.addWidget(self._btn_replace)

        btn_close = QPushButton("X")
        btn_close.setFixedWidth(24)
        btn_close.clicked.connect(lambda: self.setVisible(False))
        layout.addWidget(btn_close)

    def set_replace_visible(self, visible: bool) -> None:
        for w in (self._replace_label, self._replace_input, self._btn_replace):
            w.setVisible(visible)

    def focus_search(self) -> None:
        self._find_input.setFocus()
        self._find_input.selectAll()

    def _on_find_next(self) -> None:
        self.search_requested.emit(self._find_input.text(), True)

    def _on_find_prev(self) -> None:
        self.search_requested.emit(self._find_input.text(), False)

    def _on_replace(self) -> None:
        self.replace_requested.emit(self._find_input.text(), self._replace_input.text())

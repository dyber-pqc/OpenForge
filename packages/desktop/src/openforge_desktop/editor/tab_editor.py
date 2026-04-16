"""Multi-tab code editor — the central widget of the OpenForge main window.

Manages multiple CodeEditor instances in a QTabWidget with:
- Open / close / reorder tabs
- Modified indicator (* in tab title)
- Language auto-detection from file extension
- Save / Save As / Save All
- Ctrl+Tab / Ctrl+Shift+Tab tab cycling
- Ctrl+W close, Ctrl+Shift+T reopen last closed
- Right-click tab context menu
- Welcome tab when no files are open
- Minimap sidebar
- Search/replace bar
- Split view (horizontal)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from openforge_desktop.editor.code_editor import CodeEditor, _make_font, _Minimap

# ── Constants ────────────────────────────────────────────────────────────

_VERILOG_EXTS: Final[set[str]] = {".v", ".sv", ".svh", ".vh"}
_VHDL_EXTS: Final[set[str]] = {".vhd", ".vhdl"}
_SDC_EXTS: Final[set[str]] = {".sdc", ".xdc", ".tcl"}
_ALL_SUPPORTED: Final[set[str]] = _VERILOG_EXTS | _VHDL_EXTS | _SDC_EXTS | {
    ".py", ".yaml", ".yml", ".json", ".md", ".txt", ".cfg", ".ini",
    ".def", ".lef", ".lib", ".spice", ".sp",
}


# ── Welcome page ─────────────────────────────────────────────────────────


class _WelcomeTab(QWidget):
    """Shown when no files are open."""

    open_file_requested = Signal()
    new_file_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("OpenForge EDA")
        title.setStyleSheet("font-size: 28px; font-weight: bold; color: #cba6f7; margin-bottom: 8px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Open-source EDA platform for ASIC and FPGA design")
        subtitle.setStyleSheet("font-size: 14px; color: #a6adc8; margin-bottom: 24px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        shortcuts_text = (
            "<table style='color: #cdd6f4; font-size: 13px;'>"
            "<tr><td style='padding: 4px 16px; color: #89b4fa;'>Ctrl+N</td><td>New file</td></tr>"
            "<tr><td style='padding: 4px 16px; color: #89b4fa;'>Ctrl+O</td><td>Open file</td></tr>"
            "<tr><td style='padding: 4px 16px; color: #89b4fa;'>Ctrl+S</td><td>Save</td></tr>"
            "<tr><td style='padding: 4px 16px; color: #89b4fa;'>Ctrl+/</td><td>Toggle comment</td></tr>"
            "<tr><td style='padding: 4px 16px; color: #89b4fa;'>Ctrl+G</td><td>Go to line</td></tr>"
            "<tr><td style='padding: 4px 16px; color: #89b4fa;'>Ctrl+D</td><td>Duplicate line</td></tr>"
            "<tr><td style='padding: 4px 16px; color: #89b4fa;'>Ctrl+Click</td><td>Go to definition</td></tr>"
            "<tr><td style='padding: 4px 16px; color: #89b4fa;'>Ctrl+F</td><td>Find</td></tr>"
            "<tr><td style='padding: 4px 16px; color: #89b4fa;'>Ctrl+H</td><td>Find and Replace</td></tr>"
            "</table>"
        )
        shortcuts = QLabel(shortcuts_text)
        shortcuts.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(shortcuts)

        self.setStyleSheet("background-color: #1e1e2e;")


# ── Search bar ───────────────────────────────────────────────────────────


class _SearchBar(QWidget):
    """Find / replace bar attached to the bottom of the editor."""

    search_requested = Signal(str, bool)   # (text, forward)
    replace_requested = Signal(str, str)   # (find, replace_with)
    replace_all_requested = Signal(str, str)

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
            lambda: self.replace_requested.emit(self._find.text(), self._replace_input.text()),
        )
        layout.addWidget(self._btn_replace)

        self._btn_replace_all = QPushButton("All")
        self._btn_replace_all.setFixedWidth(36)
        self._btn_replace_all.clicked.connect(
            lambda: self.replace_all_requested.emit(self._find.text(), self._replace_input.text()),
        )
        layout.addWidget(self._btn_replace_all)

        btn_close = QPushButton("X")
        btn_close.setFixedWidth(24)
        btn_close.clicked.connect(lambda: self.setVisible(False))
        layout.addWidget(btn_close)

    def set_replace_visible(self, visible: bool) -> None:
        for w in (self._replace_label, self._replace_input, self._btn_replace, self._btn_replace_all):
            w.setVisible(visible)

    def focus_search(self) -> None:
        self._find.setFocus()
        self._find.selectAll()


# ═══════════════════════════════════════════════════════════════════════════
#  EditorTabWidget — the main multi-tab editor
# ═══════════════════════════════════════════════════════════════════════════


class EditorTabWidget(QWidget):
    """Multi-tab code editor — the central widget of the main window.

    Drop-in replacement for the old EditorPanel with the same public API,
    plus additional features: go-to-definition wiring, lint overlay,
    split view, welcome tab, and reopen closed tabs.
    """

    # Signals (compatible with old EditorPanel)
    cursor_position_changed = Signal(int, int)
    file_opened = Signal(str)
    file_saved = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Horizontal layout: tabs + minimap
        self._editor_row = QHBoxLayout()
        self._editor_row.setContentsMargins(0, 0, 0, 0)
        self._editor_row.setSpacing(0)

        # Splitter for split view
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tabs.tabBar().customContextMenuRequested.connect(self._on_tab_context_menu)
        self._splitter.addWidget(self._tabs)

        # Secondary tab widget for split view (hidden by default)
        self._tabs2: QTabWidget | None = None

        self._editor_row.addWidget(self._splitter, stretch=1)

        # Minimap
        self._minimap = _Minimap(self)
        self._minimap.scroll_requested.connect(self._on_minimap_scroll)
        self._minimap.setVisible(False)
        self._editor_row.addWidget(self._minimap)

        layout.addLayout(self._editor_row)

        # Search bar
        self._search_bar = _SearchBar(self)
        self._search_bar.setVisible(False)
        self._search_bar.search_requested.connect(self._on_search)
        self._search_bar.replace_requested.connect(self._on_replace)
        self._search_bar.replace_all_requested.connect(self._on_replace_all)
        layout.addWidget(self._search_bar)

        # File path tracking
        self._file_paths: dict[int, Path | None] = {}

        # Recently closed tabs (for Ctrl+Shift+T)
        self._closed_tabs: list[tuple[str, Path | None]] = []  # (content, path)

        # Go-to-definition callback (set externally by mainwindow)
        self._goto_def_callback: object | None = None

        # Welcome tab
        self._show_welcome()

    # ── Welcome tab ──────────────────────────────────────────────────

    def _show_welcome(self) -> None:
        """Show the welcome tab if no files are open."""
        if self._tabs.count() == 0:
            welcome = _WelcomeTab()
            self._tabs.addTab(welcome, "Welcome")

    def _remove_welcome(self) -> None:
        """Remove the welcome tab if it exists."""
        for i in range(self._tabs.count()):
            if isinstance(self._tabs.widget(i), _WelcomeTab):
                self._tabs.removeTab(i)
                break

    # ── Public API (compatible with old EditorPanel) ─────────────────

    def new_file(
        self,
        content: str = "",
        title: str = "untitled",
        path: Path | None = None,
    ) -> QWidget:
        """Create a new editor tab and return the CodeEditor widget."""
        self._remove_welcome()

        ext = path.suffix.lower() if path else ".v"
        editor = CodeEditor(file_extension=ext)
        editor.setPlainText(content)
        editor.document().setModified(False)

        idx = self._tabs.addTab(editor, title)
        self._file_paths[idx] = path

        # Connect signals
        editor.cursor_position_changed.connect(
            lambda line, col: self.cursor_position_changed.emit(line, col),
        )

        def _on_mod_changed(modified: bool, ed: QWidget = editor) -> None:
            tab_idx = self._tabs.indexOf(ed)
            if tab_idx < 0:
                return
            base_title = self._tabs.tabText(tab_idx).rstrip(" *")
            self._tabs.setTabText(tab_idx, base_title + " *" if modified else base_title)

        editor.modification_changed.connect(_on_mod_changed)

        # Go-to-definition wiring
        editor.go_to_definition_requested.connect(self._on_goto_def_requested)

        # Minimap sync
        editor.textChanged.connect(self._sync_minimap_content)
        editor.verticalScrollBar().valueChanged.connect(self._sync_minimap_viewport)

        self._tabs.setCurrentIndex(idx)

        if path:
            self.file_opened.emit(str(path))

        return editor

    def open_file(self, path: Path) -> QWidget:
        """Open a file in a new tab, or switch to it if already open."""
        # Check if already open
        for idx, p in self._file_paths.items():
            if p is not None and p.resolve() == path.resolve():
                self._tabs.setCurrentIndex(idx)
                return self._tabs.widget(idx)

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = f"// Error: could not read {path}\n"

        editor = self.new_file(text, path.name, path=path)
        idx = self._tabs.currentIndex()
        self._file_paths[idx] = path
        return editor

    def open_file_dialog(self, start_dir: str = "") -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open Source File", start_dir,
            "Verilog (*.v *.sv *.vh *.svh);;"
            "VHDL (*.vhd *.vhdl);;"
            "Constraints (*.sdc *.xdc *.tcl);;"
            "All (*)",
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
        if isinstance(editor, CodeEditor):
            path.write_text(editor.toPlainText(), encoding="utf-8")
            editor.document().setModified(False)
            self.file_saved.emit(str(path))

    def save_current_as(self) -> None:
        idx = self._tabs.currentIndex()
        if idx < 0:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save File As", "",
            "Verilog (*.v *.sv);;"
            "VHDL (*.vhd *.vhdl);;"
            "Constraints (*.sdc *.xdc *.tcl);;"
            "All (*)",
        )
        if path_str:
            path = Path(path_str)
            editor = self._tabs.widget(idx)
            if isinstance(editor, CodeEditor):
                path.write_text(editor.toPlainText(), encoding="utf-8")
                editor.document().setModified(False)
                # Update highlighter for new extension
                editor.file_extension = path.suffix
            self._file_paths[idx] = path
            self._tabs.setTabText(idx, path.name)
            self.file_saved.emit(str(path))

    def save_all(self) -> None:
        """Save all modified tabs."""
        for idx in range(self._tabs.count()):
            path = self._file_paths.get(idx)
            editor = self._tabs.widget(idx)
            if isinstance(editor, CodeEditor) and path and editor.document().isModified():
                path.write_text(editor.toPlainText(), encoding="utf-8")
                editor.document().setModified(False)
                self.file_saved.emit(str(path))

    def close_current_tab(self) -> None:
        idx = self._tabs.currentIndex()
        if idx >= 0:
            self._close_tab(idx)

    def reopen_closed_tab(self) -> None:
        """Reopen the most recently closed tab (Ctrl+Shift+T)."""
        if not self._closed_tabs:
            return
        content, path = self._closed_tabs.pop()
        if path and path.exists():
            self.open_file(path)
        else:
            title = path.name if path else "untitled"
            self.new_file(content, title, path)

    # ── Search ───────────────────────────────────────────────────────

    def show_search(self, *, replace: bool = False) -> None:
        self._search_bar.setVisible(True)
        self._search_bar.set_replace_visible(replace)
        self._search_bar.focus_search()

    def _on_search(self, text: str, forward: bool) -> None:
        editor = self._current_editor()
        if not editor or not text:
            return
        flags = QTextDocument.FindFlag(0)
        if not forward:
            flags |= QTextDocument.FindFlag.FindBackward
        if not editor.find(text, flags):
            # Wrap around
            cursor = editor.textCursor()
            cursor.movePosition(
                QTextCursor.MoveOperation.Start if forward else QTextCursor.MoveOperation.End,
            )
            editor.setTextCursor(cursor)
            editor.find(text, flags)

    def _on_replace(self, find: str, replace: str) -> None:
        editor = self._current_editor()
        if not editor or not find:
            return
        cursor = editor.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == find:
            cursor.insertText(replace)
        self._on_search(find, True)

    def _on_replace_all(self, find: str, replace: str) -> None:
        editor = self._current_editor()
        if not editor or not find:
            return
        text = editor.toPlainText()
        new_text = text.replace(find, replace)
        if new_text != text:
            cursor = editor.textCursor()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.beginEditBlock()
            cursor.insertText(new_text)
            cursor.endEditBlock()

    # ── Go to line / comment / word wrap / zoom (public) ─────────────

    def go_to_line(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.go_to_line()

    def toggle_comment(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.toggle_comment()

    def toggle_word_wrap(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.toggle_word_wrap()

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

    # ── Minimap ──────────────────────────────────────────────────────

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

    def _on_minimap_scroll(self, ratio: float) -> None:
        editor = self._current_editor()
        if editor:
            sb = editor.verticalScrollBar()
            sb.setValue(int(ratio * sb.maximum()))

    # ── Split view ───────────────────────────────────────────────────

    def split_horizontal(self) -> None:
        """Toggle horizontal split view."""
        if self._tabs2 is not None:
            # Close split
            self._splitter.widget(1).setParent(None)  # type: ignore[arg-type]
            self._tabs2 = None
            return

        # Open split: clone current file into second tab widget
        editor = self._current_editor()
        if not editor:
            return

        self._tabs2 = QTabWidget()
        self._tabs2.setTabsClosable(True)
        self._tabs2.setMovable(True)
        self._tabs2.setDocumentMode(True)

        idx = self._tabs.currentIndex()
        path = self._file_paths.get(idx)
        ext = path.suffix.lower() if path else ".v"
        editor2 = CodeEditor(file_extension=ext)
        editor2.setPlainText(editor.toPlainText())
        editor2.document().setModified(False)
        title = self._tabs.tabText(idx).rstrip(" *")
        self._tabs2.addTab(editor2, title)

        self._splitter.addWidget(self._tabs2)

    # ── Go to definition ─────────────────────────────────────────────

    def set_goto_definition_callback(self, callback) -> None:
        """Set a callback: callback(symbol: str) -> (file_path, line) | None."""
        self._goto_def_callback = callback

    def _on_goto_def_requested(self, symbol: str) -> None:
        if self._goto_def_callback is None:
            return
        result = self._goto_def_callback(symbol)  # type: ignore[operator]
        if result is not None:
            file_path, line = result
            editor = self.open_file(Path(file_path))
            if isinstance(editor, CodeEditor):
                block = editor.document().findBlockByLineNumber(line - 1)
                cursor = editor.textCursor()
                cursor.setPosition(block.position())
                editor.setTextCursor(cursor)
                editor.centerCursor()

    # ── Tab management internals ─────────────────────────────────────

    def _close_tab(self, index: int) -> None:
        widget = self._tabs.widget(index)
        # Save content for reopen
        content = widget.toPlainText() if isinstance(widget, CodeEditor) else ""
        path = self._file_paths.get(index)
        self._closed_tabs.append((content, path))
        if len(self._closed_tabs) > 20:
            self._closed_tabs.pop(0)

        self._tabs.removeTab(index)

        # Re-index file paths
        new_paths: dict[int, Path | None] = {}
        for old_idx, p in self._file_paths.items():
            if old_idx == index:
                continue
            new_idx = old_idx if old_idx < index else old_idx - 1
            new_paths[new_idx] = p
        self._file_paths = new_paths

        # Show welcome if no tabs
        if self._tabs.count() == 0:
            self._show_welcome()

    def _current_editor(self) -> CodeEditor | None:
        widget = self._tabs.currentWidget()
        return widget if isinstance(widget, CodeEditor) else None

    def _on_tab_context_menu(self, position) -> None:
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

        if self._closed_tabs:
            menu.addSeparator()
            menu.addAction("Reopen Closed Tab", self.reopen_closed_tab)

        menu.exec(tab_bar.mapToGlobal(position))

    def _close_others(self, keep_idx: int) -> None:
        for i in range(self._tabs.count() - 1, -1, -1):
            if i != keep_idx:
                self._close_tab(i)

    def _close_all(self) -> None:
        while self._tabs.count() > 0:
            self._close_tab(0)

    def _reveal_in_explorer(self, path: Path) -> None:
        folder = str(path.parent)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", folder])

    # ── Tab cycling ──────────────────────────────────────────────────

    def next_tab(self) -> None:
        idx = self._tabs.currentIndex()
        if idx < self._tabs.count() - 1:
            self._tabs.setCurrentIndex(idx + 1)
        else:
            self._tabs.setCurrentIndex(0)

    def prev_tab(self) -> None:
        idx = self._tabs.currentIndex()
        if idx > 0:
            self._tabs.setCurrentIndex(idx - 1)
        else:
            self._tabs.setCurrentIndex(self._tabs.count() - 1)

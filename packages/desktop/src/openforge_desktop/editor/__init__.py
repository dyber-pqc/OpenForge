"""OpenForge production code editor package.

Provides syntax-highlighted, multi-tab code editing with:
- Verilog / SystemVerilog / VHDL / SDC syntax highlighting
- Line numbers, bracket matching, indent guides
- Auto-indent, smart Home, duplicate/delete line
- Go-to-definition via Ctrl+Click
- Lint squiggles (wavy underlines) for diagnostics
- Multi-tab interface with welcome page
- Minimap, search/replace, split view
"""

from openforge_desktop.editor.code_editor import CodeEditor
from openforge_desktop.editor.highlighter import (
    SdcHighlighter,
    VerilogHighlighter,
    VhdlHighlighter,
    highlighter_for_extension,
)
from openforge_desktop.editor.lint_overlay import LintOverlay
from openforge_desktop.editor.navigation import VerilogNavigator
from openforge_desktop.editor.tab_editor import EditorTabWidget

__all__ = [
    "CodeEditor",
    "EditorTabWidget",
    "LintOverlay",
    "SdcHighlighter",
    "VerilogHighlighter",
    "VerilogNavigator",
    "VhdlHighlighter",
    "highlighter_for_extension",
]

"""Regex-based syntax highlighters for Verilog/SystemVerilog, VHDL, and SDC/TCL.

Uses Catppuccin Mocha color palette for consistent dark-theme highlighting.
Each highlighter supports multi-line comments, strings, and language-specific
constructs.
"""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument

# ── Catppuccin Mocha palette ─────────────────────────────────────────────

_MAUVE: Final[str] = "#cba6f7"  # keywords
_BLUE: Final[str] = "#89b4fa"  # types
_PEACH: Final[str] = "#fab387"  # numbers
_GREEN: Final[str] = "#a6e3a1"  # strings
_OVERLAY0: Final[str] = "#6c7086"  # comments
_RED: Final[str] = "#f38ba8"  # preprocessor
_YELLOW: Final[str] = "#f9e2af"  # system tasks
_SKY: Final[str] = "#89dceb"  # operators
_TEAL: Final[str] = "#94e2d5"  # module instances / identifiers
_FLAMINGO: Final[str] = "#f2cdcd"  # labels
_LAVENDER: Final[str] = "#b4befe"  # constants


def _make_fmt(
    color: str,
    *,
    bold: bool = False,
    italic: bool = False,
) -> QTextCharFormat:
    """Create a QTextCharFormat with the given color and style."""
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    if italic:
        fmt.setFontItalic(True)
    return fmt


# ═══════════════════════════════════════════════════════════════════════════
#  Verilog / SystemVerilog highlighter
# ═══════════════════════════════════════════════════════════════════════════

_VERILOG_KEYWORDS: Final[set[str]] = {
    "module",
    "endmodule",
    "input",
    "output",
    "inout",
    "wire",
    "reg",
    "logic",
    "always",
    "always_ff",
    "always_comb",
    "always_latch",
    "assign",
    "if",
    "else",
    "begin",
    "end",
    "case",
    "casex",
    "casez",
    "endcase",
    "for",
    "while",
    "repeat",
    "forever",
    "do",
    "generate",
    "endgenerate",
    "function",
    "endfunction",
    "task",
    "endtask",
    "parameter",
    "localparam",
    "defparam",
    "integer",
    "real",
    "time",
    "initial",
    "posedge",
    "negedge",
    "typedef",
    "struct",
    "enum",
    "union",
    "interface",
    "endinterface",
    "modport",
    "clocking",
    "endclocking",
    "class",
    "endclass",
    "extends",
    "implements",
    "package",
    "endpackage",
    "import",
    "export",
    "constraint",
    "covergroup",
    "endgroup",
    "coverpoint",
    "cross",
    "property",
    "endproperty",
    "sequence",
    "endsequence",
    "assert",
    "assume",
    "cover",
    "expect",
    "rand",
    "randc",
    "virtual",
    "pure",
    "extern",
    "return",
    "break",
    "continue",
    "fork",
    "join",
    "join_any",
    "join_none",
    "disable",
    "iff",
    "inside",
    "dist",
    "with",
    "unique",
    "priority",
    "tagged",
    "packed",
    "const",
    "ref",
    "local",
    "protected",
    "static",
    "automatic",
    "new",
    "null",
    "this",
    "super",
    "program",
    "endprogram",
    "checker",
    "endchecker",
    "or",
    "and",
    "not",
    "nand",
    "nor",
    "xor",
    "xnor",
    "supply0",
    "supply1",
    "tri",
    "triand",
    "trior",
    "tri0",
    "tri1",
    "wand",
    "wor",
    "trireg",
    "pullup",
    "pulldown",
    "default",
    "specify",
    "endspecify",
    "primitive",
    "endprimitive",
    "table",
    "endtable",
}

_VERILOG_TYPES: Final[set[str]] = {
    "wire",
    "reg",
    "logic",
    "bit",
    "byte",
    "shortint",
    "int",
    "longint",
    "real",
    "shortreal",
    "realtime",
    "string",
    "void",
    "chandle",
    "event",
    "genvar",
    "signed",
    "unsigned",
    "integer",
    "time",
}

_VERILOG_SYSTASKS: Final[str] = (
    r"\$(?:display|write|strobe|monitor|monitoron|monitoroff|"
    r"finish|stop|fatal|error|warning|info|"
    r"time|stime|realtime|"
    r"random|urandom|urandom_range|"
    r"readmemh|readmemb|writememh|writememb|"
    r"dumpfile|dumpvars|dumpon|dumpoff|dumpall|dumplimit|dumpflush|"
    r"fopen|fclose|fwrite|fdisplay|fstrobe|fmonitor|fgets|fscanf|fread|fseek|ftell|feof|"
    r"sscanf|sformat|sformatf|"
    r"signed|unsigned|clog2|ln|log10|exp|sqrt|pow|floor|ceil|"
    r"bits|typename|"
    r"countones|onehot|onehot0|isunknown|"
    r"rose|fell|stable|changed|past|"
    r"test\$plusargs|value\$plusargs|"
    r"cast|itor|rtoi|"
    r"assertoff|asserton|assertkill|"
    r"assertpasson|assertpassoff|assertfailon|assertfailoff|"
    r"assertvacuousoff|"
    r"coverage_control|coverage_get_max|coverage_get|coverage_merge|coverage_save|"
    r"\w+)"
)

_VERILOG_PREPROC: Final[str] = (
    r"`(?:define|undef|include|ifdef|ifndef|else|elsif|endif|"
    r"timescale|default_nettype|resetall|"
    r"celldefine|endcelldefine|"
    r"pragma|line|file|"
    r"begin_keywords|end_keywords|"
    r"unconnected_drive|nounconnected_drive|"
    r"\w+)"
)

_VERILOG_NUMBER: Final[str] = (
    r"(?:\b\d+)?'[sS]?[bBhHdDoO][0-9a-fA-FxXzZ_]+\b"
    r"|\b\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?\b"
)

_VERILOG_OPERATORS: Final[str] = (
    r"<<=|>>=|===|!==|==\?|!=\?|"
    r"<=|>=|==|!=|&&|\|\||<<|>>|>>>|"
    r"\*\*|\+:|-:|"
    r"[=<>!&|^~?+\-*/%@#]"
)


class VerilogHighlighter(QSyntaxHighlighter):
    """Regex-based syntax highlighter for Verilog / SystemVerilog.

    Applies Catppuccin Mocha colors to keywords, types, numbers, strings,
    comments (single-line and multi-line), preprocessor directives, system
    tasks, and operators.
    """

    def __init__(self, parent: QTextDocument | None = None) -> None:
        super().__init__(parent)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

        # Order matters: later rules override earlier ones within a block.
        # Operators (sky)
        self._rules.append(
            (
                QRegularExpression(_VERILOG_OPERATORS),
                _make_fmt(_SKY),
            )
        )

        # Keywords (mauve, bold)
        kw_pattern = r"\b(?:" + "|".join(sorted(_VERILOG_KEYWORDS)) + r")\b"
        self._rules.append((QRegularExpression(kw_pattern), _make_fmt(_MAUVE, bold=True)))

        # Types (blue) — must come after keywords so types win on overlap
        type_pattern = r"\b(?:" + "|".join(sorted(_VERILOG_TYPES)) + r")\b"
        self._rules.append((QRegularExpression(type_pattern), _make_fmt(_BLUE)))

        # Numbers (peach)
        self._rules.append((QRegularExpression(_VERILOG_NUMBER), _make_fmt(_PEACH)))

        # Strings (green)
        self._rules.append((QRegularExpression(r'"(?:[^"\\]|\\.)*"'), _make_fmt(_GREEN)))

        # Preprocessor (red)
        self._rules.append((QRegularExpression(_VERILOG_PREPROC), _make_fmt(_RED)))

        # System tasks (yellow)
        self._rules.append((QRegularExpression(_VERILOG_SYSTASKS), _make_fmt(_YELLOW)))

        # Single-line comment (overlay0, italic)
        self._comment_fmt = _make_fmt(_OVERLAY0, italic=True)
        self._rules.append((QRegularExpression(r"//[^\n]*"), self._comment_fmt))

        # Multi-line comment delimiters
        self._ml_start = QRegularExpression(r"/\*")
        self._ml_end = QRegularExpression(r"\*/")

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        """Apply syntax highlighting rules to a single block of text."""
        # Single-line rules
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        # Multi-line comments
        self.setCurrentBlockState(0)

        if self.previousBlockState() == 1:
            start_index = 0
        else:
            m = self._ml_start.match(text)
            start_index = m.capturedStart() if m.hasMatch() else -1

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


# ═══════════════════════════════════════════════════════════════════════════
#  VHDL highlighter
# ═══════════════════════════════════════════════════════════════════════════

_VHDL_KEYWORDS: Final[set[str]] = {
    "abs",
    "access",
    "after",
    "alias",
    "all",
    "and",
    "architecture",
    "array",
    "assert",
    "assume",
    "attribute",
    "begin",
    "block",
    "body",
    "buffer",
    "bus",
    "case",
    "component",
    "configuration",
    "constant",
    "context",
    "default",
    "disconnect",
    "downto",
    "else",
    "elsif",
    "end",
    "entity",
    "exit",
    "file",
    "for",
    "force",
    "function",
    "generate",
    "generic",
    "group",
    "guarded",
    "if",
    "impure",
    "in",
    "inertial",
    "inout",
    "is",
    "label",
    "library",
    "linkage",
    "literal",
    "loop",
    "map",
    "mod",
    "nand",
    "new",
    "next",
    "nor",
    "not",
    "null",
    "of",
    "on",
    "open",
    "or",
    "others",
    "out",
    "package",
    "parameter",
    "port",
    "postponed",
    "procedure",
    "process",
    "property",
    "protected",
    "pure",
    "range",
    "record",
    "register",
    "reject",
    "release",
    "rem",
    "report",
    "restrict",
    "return",
    "rol",
    "ror",
    "select",
    "sequence",
    "severity",
    "signal",
    "shared",
    "sla",
    "sll",
    "sra",
    "srl",
    "subtype",
    "then",
    "to",
    "transport",
    "type",
    "unaffected",
    "units",
    "until",
    "use",
    "variable",
    "vmode",
    "vprop",
    "vunit",
    "wait",
    "when",
    "while",
    "with",
    "xnor",
    "xor",
}

_VHDL_TYPES: Final[set[str]] = {
    "bit",
    "bit_vector",
    "boolean",
    "character",
    "integer",
    "natural",
    "positive",
    "real",
    "string",
    "time",
    "std_logic",
    "std_logic_vector",
    "std_ulogic",
    "std_ulogic_vector",
    "signed",
    "unsigned",
    "line",
    "text",
    "side",
    "width",
}


class VhdlHighlighter(QSyntaxHighlighter):
    """Regex-based syntax highlighter for VHDL.

    Case-insensitive matching for VHDL keywords. Supports -- line comments
    and /* */ block comments (VHDL-2008).
    """

    def __init__(self, parent: QTextDocument | None = None) -> None:
        super().__init__(parent)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

        # Operators (sky)
        self._rules.append(
            (
                QRegularExpression(r"<=|:=|=>|/=|[=<>&|+\-*/()]"),
                _make_fmt(_SKY),
            )
        )

        # Keywords (mauve, bold) — case-insensitive
        kw_pattern = r"\b(?:" + "|".join(sorted(_VHDL_KEYWORDS)) + r")\b"
        rx = QRegularExpression(kw_pattern)
        rx.setPatternOptions(QRegularExpression.PatternOption.CaseInsensitiveOption)
        self._rules.append((rx, _make_fmt(_MAUVE, bold=True)))

        # Types (blue)
        type_pattern = r"\b(?:" + "|".join(sorted(_VHDL_TYPES)) + r")\b"
        rx_t = QRegularExpression(type_pattern)
        rx_t.setPatternOptions(QRegularExpression.PatternOption.CaseInsensitiveOption)
        self._rules.append((rx_t, _make_fmt(_BLUE)))

        # Numbers (peach): binary, octal, hex strings and integers/reals
        self._rules.append(
            (
                QRegularExpression(
                    r'[BOXbox]"[0-9a-fA-F_]+"|\b\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?\b'
                ),
                _make_fmt(_PEACH),
            )
        )

        # Character literals (green)
        self._rules.append((QRegularExpression(r"'[^']*'"), _make_fmt(_GREEN)))

        # Strings (green)
        self._rules.append((QRegularExpression(r'"(?:[^"\\]|\\.)*"'), _make_fmt(_GREEN)))

        # Library / use clauses (red) — treated like preprocessor
        self._rules.append(
            (
                QRegularExpression(
                    r"\b(?:library|use)\b\s+[\w.]+",
                    QRegularExpression.PatternOption.CaseInsensitiveOption,
                ),
                _make_fmt(_RED),
            )
        )

        # Attributes (yellow)
        self._rules.append((QRegularExpression(r"'\w+"), _make_fmt(_YELLOW)))

        # Single-line comment (overlay0, italic)
        self._comment_fmt = _make_fmt(_OVERLAY0, italic=True)
        self._rules.append((QRegularExpression(r"--[^\n]*"), self._comment_fmt))

        # Multi-line comment (VHDL-2008)
        self._ml_start = QRegularExpression(r"/\*")
        self._ml_end = QRegularExpression(r"\*/")

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        # Multi-line comments (VHDL-2008)
        self.setCurrentBlockState(0)

        if self.previousBlockState() == 1:
            start_index = 0
        else:
            m = self._ml_start.match(text)
            start_index = m.capturedStart() if m.hasMatch() else -1

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


# ═══════════════════════════════════════════════════════════════════════════
#  SDC / XDC / TCL highlighter
# ═══════════════════════════════════════════════════════════════════════════

_SDC_COMMANDS: Final[set[str]] = {
    # SDC commands
    "create_clock",
    "create_generated_clock",
    "set_clock_groups",
    "set_clock_latency",
    "set_clock_uncertainty",
    "set_input_delay",
    "set_output_delay",
    "set_false_path",
    "set_multicycle_path",
    "set_max_delay",
    "set_min_delay",
    "set_input_transition",
    "set_load",
    "set_driving_cell",
    "set_dont_touch",
    "set_wire_load_model",
    "set_wire_load_mode",
    "set_max_fanout",
    "set_max_capacitance",
    "set_max_area",
    "set_disable_timing",
    "set_case_analysis",
    "group_path",
    "set_timing_derate",
    "get_ports",
    "get_pins",
    "get_cells",
    "get_nets",
    "get_clocks",
    "get_lib_cells",
    "get_lib_pins",
    "all_inputs",
    "all_outputs",
    "all_clocks",
    "all_registers",
    "current_design",
    "current_instance",
    "report_timing",
    "report_constraint",
    "report_clock",
    # XDC / Vivado
    "set_property",
    "get_property",
    "create_pblock",
    "add_cells_to_pblock",
    "set_input_jitter",
    "set_system_jitter",
    "create_debug_core",
    "set_debug_port",
    # TCL builtins
    "set",
    "proc",
    "if",
    "else",
    "elseif",
    "for",
    "foreach",
    "while",
    "switch",
    "return",
    "break",
    "continue",
    "expr",
    "puts",
    "gets",
    "open",
    "close",
    "read",
    "source",
    "package",
    "namespace",
    "variable",
    "global",
    "upvar",
    "uplevel",
    "list",
    "lindex",
    "llength",
    "lappend",
    "lsort",
    "lsearch",
    "lrange",
    "string",
    "regexp",
    "regsub",
    "scan",
    "format",
    "file",
    "glob",
    "cd",
    "pwd",
    "exec",
    "catch",
    "error",
    "info",
    "rename",
    "unset",
    "array",
    "dict",
    "append",
    "incr",
}


class SdcHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for SDC / XDC / TCL constraint files.

    Highlights SDC timing commands, TCL builtins, variables, strings,
    comments, and numeric values.
    """

    def __init__(self, parent: QTextDocument | None = None) -> None:
        super().__init__(parent)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

        # Operators (sky)
        self._rules.append(
            (
                QRegularExpression(r"[{}\[\]();=<>!&|+\-*/]"),
                _make_fmt(_SKY),
            )
        )

        # Commands (mauve, bold)
        cmd_pattern = r"\b(?:" + "|".join(sorted(_SDC_COMMANDS)) + r")\b"
        self._rules.append((QRegularExpression(cmd_pattern), _make_fmt(_MAUVE, bold=True)))

        # Flags / options (red) — e.g. -period, -name
        self._rules.append(
            (
                QRegularExpression(r"\s-[a-zA-Z_]\w*"),
                _make_fmt(_RED),
            )
        )

        # Variables (teal) — $var, ${var}
        self._rules.append(
            (
                QRegularExpression(r"\$\{?\w+\}?"),
                _make_fmt(_TEAL),
            )
        )

        # Numbers (peach)
        self._rules.append(
            (
                QRegularExpression(r"\b\d[\d_.]*(?:[eE][+-]?\d+)?\b"),
                _make_fmt(_PEACH),
            )
        )

        # Strings (green)
        self._rules.append((QRegularExpression(r'"(?:[^"\\]|\\.)*"'), _make_fmt(_GREEN)))

        # Braced strings (green, lighter)
        # We handle these in the string rule above plus curly brace operators

        # Comments (overlay0, italic)
        self._comment_fmt = _make_fmt(_OVERLAY0, italic=True)
        self._rules.append((QRegularExpression(r"#[^\n]*"), self._comment_fmt))

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


# ═══════════════════════════════════════════════════════════════════════════
#  Language detection helper
# ═══════════════════════════════════════════════════════════════════════════


def highlighter_for_extension(
    ext: str,
    document: QTextDocument,
) -> QSyntaxHighlighter | None:
    """Return the appropriate highlighter for a file extension, or None."""
    ext = ext.lower()
    if ext in {".v", ".sv", ".svh", ".vh"}:
        return VerilogHighlighter(document)
    if ext in {".vhd", ".vhdl"}:
        return VhdlHighlighter(document)
    if ext in {".sdc", ".xdc", ".tcl"}:
        return SdcHighlighter(document)
    return None

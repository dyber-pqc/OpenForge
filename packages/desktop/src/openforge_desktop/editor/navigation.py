"""Verilog source navigation: index symbols for go-to-definition,
find-references, and auto-completion.

Scans Verilog/SystemVerilog source files for module, function, task,
class, interface, package, and parameter declarations. Builds an index
mapping symbol names to (file, line_number) for quick lookup.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

# ── Regex patterns for Verilog declarations ──────────────────────────────

# module foo (
_RE_MODULE: Final[re.Pattern[str]] = re.compile(
    r"^\s*module\s+(\w+)", re.MULTILINE,
)
# function [type] foo
_RE_FUNCTION: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:(?:static|automatic|virtual)\s+)?function\s+(?:\w+\s+)?(\w+)\s*[;(]", re.MULTILINE,
)
# task foo
_RE_TASK: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:(?:static|automatic|virtual)\s+)?task\s+(\w+)\s*[;(]", re.MULTILINE,
)
# class foo
_RE_CLASS: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:virtual\s+)?class\s+(\w+)", re.MULTILINE,
)
# interface foo
_RE_INTERFACE: Final[re.Pattern[str]] = re.compile(
    r"^\s*interface\s+(\w+)", re.MULTILINE,
)
# package foo
_RE_PACKAGE: Final[re.Pattern[str]] = re.compile(
    r"^\s*package\s+(\w+)", re.MULTILINE,
)
# parameter/localparam FOO =
_RE_PARAM: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:parameter|localparam)\s+(?:\w+\s+)?(\w+)\s*=", re.MULTILINE,
)
# typedef ... name;
_RE_TYPEDEF: Final[re.Pattern[str]] = re.compile(
    r"^\s*typedef\s+.*?\b(\w+)\s*;", re.MULTILINE,
)
# `define MACRO
_RE_DEFINE: Final[re.Pattern[str]] = re.compile(
    r"^\s*`define\s+(\w+)", re.MULTILINE,
)

# Port / signal declarations for references
_RE_PORT_SIGNAL: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:input|output|inout|wire|reg|logic|bit|integer|real|genvar)\s+"
    r"(?:\[.*?\]\s*)?(\w+)",
    re.MULTILINE,
)

_ALL_PATTERNS: Final[list[tuple[re.Pattern[str], str]]] = [
    (_RE_MODULE, "module"),
    (_RE_FUNCTION, "function"),
    (_RE_TASK, "task"),
    (_RE_CLASS, "class"),
    (_RE_INTERFACE, "interface"),
    (_RE_PACKAGE, "package"),
    (_RE_PARAM, "parameter"),
    (_RE_TYPEDEF, "typedef"),
    (_RE_DEFINE, "define"),
]


class VerilogNavigator:
    """Index Verilog source files for go-to-definition and auto-completion.

    Usage::

        nav = VerilogNavigator([Path("src/counter.v"), Path("src/alu.v")])
        nav.index()
        result = nav.find_definition("counter")
        # result: ("src/counter.v", 5) or None
    """

    def __init__(self, rtl_files: list[Path] | None = None) -> None:
        self._files: list[Path] = list(rtl_files) if rtl_files else []
        # symbol_name -> list of (file_path_str, line_number, kind)
        self._definitions: dict[str, list[tuple[str, int, str]]] = {}
        # symbol_name -> list of (file_path_str, line_number)
        self._references: dict[str, list[tuple[str, int]]] = {}
        # All known symbol names for completion
        self._all_symbols: list[str] = []

    @property
    def files(self) -> list[Path]:
        return self._files

    @files.setter
    def files(self, value: list[Path]) -> None:
        self._files = list(value)

    def add_file(self, path: Path) -> None:
        """Add a file to the index and re-scan it."""
        if path not in self._files:
            self._files.append(path)
        self._index_file(path)

    def index(self) -> None:
        """Scan all files for declarations. Rebuilds the index from scratch."""
        self._definitions.clear()
        self._references.clear()
        self._all_symbols.clear()

        for path in self._files:
            self._index_file(path)

        self._all_symbols = sorted(set(self._definitions.keys()))

    def _index_file(self, path: Path) -> None:
        """Scan a single file for declarations and signal/port references."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return

        file_str = str(path)
        lines = text.split("\n")

        # Find declarations
        for pattern, kind in _ALL_PATTERNS:
            for match in pattern.finditer(text):
                name = match.group(1)
                # Calculate line number from position
                line_num = text[:match.start()].count("\n") + 1
                if name not in self._definitions:
                    self._definitions[name] = []
                self._definitions[name].append((file_str, line_num, kind))

        # Find signal/port declarations for references
        for match in _RE_PORT_SIGNAL.finditer(text):
            name = match.group(1)
            line_num = text[:match.start()].count("\n") + 1
            if name not in self._references:
                self._references[name] = []
            self._references[name].append((file_str, line_num))

    def find_definition(self, symbol: str) -> tuple[str, int] | None:
        """Find the definition of a symbol. Returns (file_path, line) or None."""
        defs = self._definitions.get(symbol)
        if defs:
            return (defs[0][0], defs[0][1])
        return None

    def find_all_definitions(self, symbol: str) -> list[tuple[str, int, str]]:
        """Find all definitions of a symbol. Returns [(file, line, kind)]."""
        return self._definitions.get(symbol, [])

    def find_references(self, symbol: str) -> list[tuple[str, int]]:
        """Find all references to a symbol. Returns [(file, line)]."""
        refs: list[tuple[str, int]] = []
        # Include definitions as references too
        for file_str, line, _kind in self._definitions.get(symbol, []):
            refs.append((file_str, line))
        # Include port/signal references
        for file_str, line in self._references.get(symbol, []):
            refs.append((file_str, line))

        # Also do a simple grep-like search across all files
        for path in self._files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            file_str = str(path)
            pattern = re.compile(r"\b" + re.escape(symbol) + r"\b")
            for i, line_text in enumerate(text.split("\n"), 1):
                if pattern.search(line_text):
                    ref = (file_str, i)
                    if ref not in refs:
                        refs.append(ref)

        return refs

    def get_completions(self, prefix: str, context: str = "") -> list[str]:
        """Return completion candidates matching the given prefix.

        Includes module names, function names, signal names, etc.
        """
        if not prefix:
            return []
        prefix_lower = prefix.lower()
        matches = [s for s in self._all_symbols if s.lower().startswith(prefix_lower)]

        # Also include port/signal names
        for name in self._references:
            if name.lower().startswith(prefix_lower) and name not in matches:
                matches.append(name)

        return sorted(set(matches))[:100]

    def get_module_ports(self, module_name: str) -> list[str]:
        """Get port names for a given module (best-effort parsing)."""
        defs = self._definitions.get(module_name)
        if not defs:
            return []

        file_str, _line, kind = defs[0]
        if kind != "module":
            return []

        try:
            text = Path(file_str).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        # Find the module declaration and extract port names
        mod_pattern = re.compile(
            r"\bmodule\s+" + re.escape(module_name) + r"\s*(?:#\s*\(.*?\))?\s*\((.*?)\)\s*;",
            re.DOTALL,
        )
        m = mod_pattern.search(text)
        if not m:
            return []

        ports_text = m.group(1)
        # Extract identifiers from port list
        port_names: list[str] = []
        for port_match in re.finditer(r"\b(\w+)\s*(?:,|$)", ports_text):
            name = port_match.group(1)
            # Skip keywords
            if name not in {"input", "output", "inout", "wire", "reg", "logic", "signed", "unsigned"}:
                port_names.append(name)

        return port_names

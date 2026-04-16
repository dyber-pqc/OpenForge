"""Verible SystemVerilog linter and formatter engine."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from os import PathLike


class VeribleEngine(ToolEngine):
    """Unified wrapper around the Verible lint and format tools.

    Verible ships as two separate binaries:

    * ``verible-verilog-lint``  -- static analysis / linting
    * ``verible-verilog-format`` -- auto-formatting

    This engine delegates to the appropriate binary for each operation.

    Example::

        engine = VeribleEngine()
        lint_result = engine.lint(["rtl/top.sv"])
        fmt_result  = engine.format(["rtl/top.sv"], inplace=True)
    """

    BINARY = "verible-verilog-lint"
    DOCKER_IMAGE = "chipsalliance/verible:latest"

    _FORMAT_BINARY = "verible-verilog-format"

    def __init__(
        self,
        *,
        backend: ExecutionBackend = ExecutionBackend.NATIVE,
        binary_override: str | None = None,
    ) -> None:
        super().__init__(
            backend=backend,
            binary_override=binary_override,
        )

    # ------------------------------------------------------------------
    # ToolEngine interface
    # ------------------------------------------------------------------

    def check_installed(self) -> bool:
        if self.backend == ExecutionBackend.DOCKER:
            return self.run(["--version"]).ok
        return self._which() is not None

    def version(self) -> str:
        result = self.run(["--version"])
        if result.ok:
            text = result.stdout.strip() or result.stderr.strip()
            if m := re.search(r"v?([\d]+[\d.]*[\d]+)", text):
                return m.group(1)
            return text.splitlines()[0] if text else "unknown"
        return "unknown"

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------

    def lint(
        self,
        sources: Sequence[str | PathLike[str]],
        *,
        rules: Sequence[str] = (),
        waiver_file: str | PathLike[str] | None = None,
        generate_autofix: bool = False,
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Lint SystemVerilog source files.

        Parameters
        ----------
        sources:
            Files to lint.
        rules:
            Specific lint rule names to enable (comma-joined into
            ``--rules``).  When empty, the default ruleset is used.
        waiver_file:
            Path to a waiver-file that suppresses specific findings.
        generate_autofix:
            Add ``--autofix=inplace`` to apply automatic fixes.
        extra_args:
            Additional CLI flags.
        """
        args: list[str] = []

        if rules:
            args.extend(["--rules", ",".join(rules)])

        if waiver_file:
            args.extend(["--waiver_files", str(waiver_file)])

        if generate_autofix:
            args.append("--autofix=inplace")

        args.extend(extra_args)
        args.extend(str(s) for s in sources)

        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    def format(
        self,
        sources: Sequence[str | PathLike[str]],
        *,
        inplace: bool = False,
        column_limit: int | None = None,
        indentation_spaces: int | None = None,
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Format SystemVerilog source files.

        Uses ``verible-verilog-format`` (not the linter binary).

        Parameters
        ----------
        sources:
            Files to format.
        inplace:
            Overwrite files in place.
        column_limit:
            Maximum line length.
        indentation_spaces:
            Number of spaces per indentation level.
        extra_args:
            Additional CLI flags.
        """
        args: list[str] = []

        if inplace:
            args.append("--inplace")

        if column_limit is not None:
            args.extend(["--column_limit", str(column_limit)])

        if indentation_spaces is not None:
            args.extend(["--indentation_spaces", str(indentation_spaces)])

        args.extend(extra_args)
        args.extend(str(s) for s in sources)

        # Temporarily swap the binary to the format tool.
        saved = self.binary
        try:
            self.binary = self._FORMAT_BINARY
            return self.run(args, cwd=cwd, env=env, timeout=timeout)
        finally:
            self.binary = saved

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def parse_lint_findings(self, result: ToolResult) -> list[dict[str, str | int]]:
        """Extract structured lint findings from Verible output.

        Returns a list of dicts with keys ``file``, ``line``, ``column``,
        ``rule``, and ``message``.
        """
        findings: list[dict[str, str | int]] = []
        pattern = re.compile(
            r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s*"
            r"(?P<msg>.+?)\s*\[(?P<rule>[^\]]+)\]\s*$"
        )
        for line in result.stdout.splitlines():
            if m := pattern.match(line.strip()):
                findings.append({
                    "file": m.group("file"),
                    "line": int(m.group("line")),
                    "column": int(m.group("col")),
                    "rule": m.group("rule"),
                    "message": m.group("msg"),
                })
        return findings

"""SystemVerilog / Verilog lint engine.

Wraps Verible's ``verible-verilog-lint`` (if available) and layers a set of
custom regex-based rules on top for checks Verible doesn't cover.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel


class LintRule(BaseModel):
    id: str
    name: str
    severity: str = "warning"
    pattern: str = ""
    description: str = ""


class LintViolation(BaseModel):
    rule: str
    file: str
    line: int
    column: int = 0
    message: str
    severity: str = "warning"
    fix_suggestion: str | None = None


# ---------------------------------------------------------------------------
# Built-in custom rules (regex-based)
# ---------------------------------------------------------------------------


_BUILTIN_RULES: dict[str, LintRule] = {
    "inferred_latch": LintRule(
        id="inferred_latch",
        name="Possible inferred latch",
        severity="error",
        pattern=r"always\s*@\s*\*",
        description="always @* without default in every branch may infer a latch.",
    ),
    "blocking_in_clocked": LintRule(
        id="blocking_in_clocked",
        name="Blocking assignment in clocked always",
        severity="error",
        pattern=r"always\s*@\s*\(\s*posedge.*?\).*?=",
        description="Use non-blocking (<=) inside clocked always blocks.",
    ),
    "non_blocking_in_combo": LintRule(
        id="non_blocking_in_combo",
        name="Non-blocking in combinational always",
        severity="warning",
        pattern=r"always\s*@\s*\*.*?<=",
        description="Use blocking (=) inside combinational always blocks.",
    ),
    "incomplete_case": LintRule(
        id="incomplete_case",
        name="Case statement without default",
        severity="warning",
        pattern=r"\bcase\b",
        description="Case without default can cause latches/Xs.",
    ),
    "incomplete_sensitivity": LintRule(
        id="incomplete_sensitivity",
        name="Explicit sensitivity list (use @*)",
        severity="info",
        pattern=r"always\s*@\s*\(\s*\w+\s*(?:or\s+\w+\s*)+\)",
        description="Prefer @* to explicit lists for combinational logic.",
    ),
    "race_condition": LintRule(
        id="race_condition",
        name="Potential race: assign to signal in multiple always blocks",
        severity="error",
        pattern="",
        description="Detected by the custom engine, not regex.",
    ),
    "unused_signal": LintRule(
        id="unused_signal",
        name="Unused signal",
        severity="info",
        pattern="",
        description="Declared wires/regs that are never referenced.",
    ),
    "implicit_wire": LintRule(
        id="implicit_wire",
        name="Implicit wire",
        severity="warning",
        pattern="",
        description="Add `default_nettype none to disallow implicit wires.",
    ),
    "missing_default_in_case": LintRule(
        id="missing_default_in_case",
        name="Missing default in case",
        severity="warning",
        pattern="",
        description="Every case statement should have a default branch.",
    ),
    "magic_number": LintRule(
        id="magic_number",
        name="Magic number",
        severity="info",
        pattern=r"(?<![\w'])(?:\d{3,})(?![\w'])",
        description="Large unlabeled integer literals should be parameters.",
    ),
    "long_line": LintRule(
        id="long_line",
        name="Line too long",
        severity="info",
        pattern="",
        description="Lines should be <= 120 characters.",
    ),
}


class LintEngine:
    """Runs Verible + custom rules against a set of RTL files."""

    BUILTIN_RULES: dict[str, LintRule] = _BUILTIN_RULES

    def __init__(self, rtl_files: list[Path] | list[str]) -> None:
        self._files = [Path(p) for p in rtl_files]
        self._enabled: set[str] = set(self.BUILTIN_RULES.keys())
        self._severity_override: dict[str, str] = {}

    # -- rule management ---------------------------------------------

    def enable(self, rule_id: str) -> None:
        self._enabled.add(rule_id)

    def disable(self, rule_id: str) -> None:
        self._enabled.discard(rule_id)

    def set_severity(self, rule_id: str, severity: str) -> None:
        self._severity_override[rule_id] = severity

    # -- runners -----------------------------------------------------

    def run_verible(self) -> list[LintViolation]:
        """Invoke verible-verilog-lint if it's on PATH."""
        binary = shutil.which("verible-verilog-lint")
        if not binary:
            return []
        out: list[LintViolation] = []
        try:
            proc = subprocess.run(
                [binary, "--lint_fatal=false", "--parse_fatal=false", *[str(f) for f in self._files]],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        for line in (proc.stdout + proc.stderr).splitlines():
            # Format: file:line:col: msg [rule]
            m = re.match(r"(?P<file>.+?):(?P<line>\d+):(?P<col>\d+):\s*(?P<msg>.*?)\s*\[(?P<rule>[^\]]+)\]\s*$", line)
            if not m:
                continue
            rule = m.group("rule")
            out.append(
                LintViolation(
                    rule=rule,
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=int(m.group("col")),
                    message=m.group("msg"),
                    severity=self._severity_override.get(rule, "warning"),
                )
            )
        return out

    def run_custom_rules(self) -> list[LintViolation]:
        """Scan files with regex-based and structural checks."""
        violations: list[LintViolation] = []
        for f in self._files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lines = text.splitlines()

            # long_line
            if "long_line" in self._enabled:
                for i, line in enumerate(lines, start=1):
                    if len(line) > 120:
                        violations.append(
                            LintViolation(
                                rule="long_line",
                                file=str(f),
                                line=i,
                                message=f"line length {len(line)} exceeds 120",
                                severity=self._severity_override.get("long_line", "info"),
                                fix_suggestion="break into multiple lines",
                            )
                        )

            # magic_number
            if "magic_number" in self._enabled:
                pat = re.compile(self.BUILTIN_RULES["magic_number"].pattern)
                for i, line in enumerate(lines, start=1):
                    stripped = line.split("//", 1)[0]
                    for m in pat.finditer(stripped):
                        violations.append(
                            LintViolation(
                                rule="magic_number",
                                file=str(f),
                                line=i,
                                column=m.start(),
                                message=f"magic number {m.group(0)!r}",
                                severity=self._severity_override.get("magic_number", "info"),
                                fix_suggestion="replace with a named parameter/localparam",
                            )
                        )

            # incomplete_case / missing_default_in_case
            if "missing_default_in_case" in self._enabled:
                lowered = text.lower()
                cases = [m for m in re.finditer(r"\bcase\b", lowered)]
                for m in cases:
                    start_line = text.count("\n", 0, m.start()) + 1
                    # Find the matching endcase
                    end_m = re.search(r"\bendcase\b", lowered[m.end() :])
                    if not end_m:
                        continue
                    segment = text[m.end() : m.end() + end_m.start()]
                    if "default" not in segment.lower():
                        violations.append(
                            LintViolation(
                                rule="missing_default_in_case",
                                file=str(f),
                                line=start_line,
                                message="case without default",
                                severity=self._severity_override.get(
                                    "missing_default_in_case", "warning"
                                ),
                                fix_suggestion="add a default: branch",
                            )
                        )

            # implicit_wire
            if "implicit_wire" in self._enabled and "`default_nettype none" not in text:
                violations.append(
                    LintViolation(
                        rule="implicit_wire",
                        file=str(f),
                        line=1,
                        message="`default_nettype none not set; implicit wires possible",
                        severity=self._severity_override.get("implicit_wire", "warning"),
                        fix_suggestion="add `default_nettype none at file top",
                    )
                )

            # non_blocking_in_combo
            if "non_blocking_in_combo" in self._enabled:
                combo_pat = re.compile(
                    r"always\s*@\s*\*\s*begin(?P<body>.*?)end",
                    re.DOTALL,
                )
                for m in combo_pat.finditer(text):
                    if "<=" in m.group("body"):
                        start_line = text.count("\n", 0, m.start()) + 1
                        violations.append(
                            LintViolation(
                                rule="non_blocking_in_combo",
                                file=str(f),
                                line=start_line,
                                message="non-blocking assignment in combinational always",
                                severity=self._severity_override.get(
                                    "non_blocking_in_combo", "warning"
                                ),
                                fix_suggestion="change <= to = inside always @*",
                            )
                        )

            # blocking_in_clocked
            if "blocking_in_clocked" in self._enabled:
                clk_pat = re.compile(
                    r"always(?:_ff)?\s*@\s*\(\s*posedge[^)]*\)\s*begin(?P<body>.*?)end",
                    re.DOTALL,
                )
                for m in clk_pat.finditer(text):
                    body = m.group("body")
                    # Strip <= so remaining "=" would be blocking
                    stripped_body = re.sub(r"<=", "", body)
                    if re.search(r"[^=!<>]=[^=]", stripped_body):
                        start_line = text.count("\n", 0, m.start()) + 1
                        violations.append(
                            LintViolation(
                                rule="blocking_in_clocked",
                                file=str(f),
                                line=start_line,
                                message="blocking assignment in clocked always",
                                severity=self._severity_override.get(
                                    "blocking_in_clocked", "error"
                                ),
                                fix_suggestion="change = to <= inside clocked always",
                            )
                        )

        return violations

    def run_all(self) -> list[LintViolation]:
        return self.run_verible() + self.run_custom_rules()

    def auto_fix(self, violation: LintViolation) -> str | None:
        """Return a best-effort one-line replacement for ``violation``.

        Only handles trivial rules; returns ``None`` when no safe fix exists.
        """
        if violation.rule == "implicit_wire":
            return "`default_nettype none"
        if violation.rule == "long_line":
            return None  # requires context
        if violation.rule == "missing_default_in_case":
            return "      default: ;"
        return None

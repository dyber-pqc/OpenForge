"""Verilog synthesis attribute helpers.

Models the ``(* attr = "value" *)`` markers used by Yosys, Vivado, and
other synthesizers, with utilities to find them in source and insert
new ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class AttributeType(Enum):
    """Supported synthesis attribute names."""

    KEEP = "keep"
    DONT_TOUCH = "dont_touch"
    KEEP_HIERARCHY = "keep_hierarchy"
    MARK_DEBUG = "mark_debug"
    BLACKBOX = "blackbox"
    NOMERGE = "nomerge"
    USE_DSP = "use_dsp"
    USE_BRAM = "use_bram"
    ASYNC_REG = "async_reg"
    PRESERVE = "preserve"
    PARALLEL_CASE = "parallel_case"
    FULL_CASE = "full_case"


@dataclass
class SynthesisAttribute:
    """A single Verilog synthesis attribute.

    Use :meth:`to_verilog` to render the canonical
    ``(* keep = "true" *)`` form.
    """

    type: AttributeType
    value: str = "true"
    target: str = ""  # signal/module/instance name (for context only)
    comment: str = ""

    def to_verilog(self) -> str:
        """Format as a Verilog attribute string."""
        if self.value == "true":
            return f"(* {self.type.value} *)"
        return f'(* {self.type.value} = "{self.value}" *)'

    def to_verilog_with_comment(self) -> str:
        v = self.to_verilog()
        if self.comment:
            return f"{v}  // {self.comment}"
        return v

    def description(self) -> str:
        return ATTRIBUTE_DESCRIPTIONS.get(self.type, "")


ATTRIBUTE_DESCRIPTIONS: dict[AttributeType, str] = {
    AttributeType.KEEP: "Prevent removal of net or signal during optimization.",
    AttributeType.DONT_TOUCH: "Prevent any optimization on this signal/cell.",
    AttributeType.KEEP_HIERARCHY: "Don't flatten this module during synthesis.",
    AttributeType.MARK_DEBUG: "Mark for ChipScope/ILA debug observation.",
    AttributeType.BLACKBOX: "Treat as black box, don't synthesize.",
    AttributeType.NOMERGE: "Prevent merging with other identical signals.",
    AttributeType.USE_DSP: "Force inference of DSP block.",
    AttributeType.USE_BRAM: "Force inference of block RAM.",
    AttributeType.ASYNC_REG: "Mark register as asynchronous (CDC).",
    AttributeType.PRESERVE: "Preserve net/cell during optimization.",
    AttributeType.PARALLEL_CASE: "Hint that case items are parallel.",
    AttributeType.FULL_CASE: "Hint that all cases are covered.",
}

ATTRIBUTE_VALUES: dict[AttributeType, list[str]] = {
    AttributeType.KEEP: ["true", "false"],
    AttributeType.DONT_TOUCH: ["true", "false"],
    AttributeType.KEEP_HIERARCHY: ["true", "false", "soft", "yes"],
    AttributeType.MARK_DEBUG: ["true", "false"],
    AttributeType.BLACKBOX: ["true", "false"],
    AttributeType.NOMERGE: ["true", "false"],
    AttributeType.USE_DSP: ["yes", "no", "logic"],
    AttributeType.USE_BRAM: ["yes", "no", "logic", "distributed"],
    AttributeType.ASYNC_REG: ["true", "false"],
    AttributeType.PRESERVE: ["true", "false"],
    AttributeType.PARALLEL_CASE: ["true"],
    AttributeType.FULL_CASE: ["true"],
}


def attribute_type_from_str(name: str) -> AttributeType | None:
    """Look up an :class:`AttributeType` by canonical name."""
    name_l = name.strip().lower()
    for at in AttributeType:
        if at.value == name_l:
            return at
    return None


def find_attributes_in_source(source_text: str) -> list[tuple[int, str]]:
    """Find all ``(* attr *)`` markers in Verilog source.

    Returns a list of ``(line_number, attribute_text)`` tuples. Line
    numbers are 1-based.
    """
    results: list[tuple[int, str]] = []
    pattern = re.compile(r"\(\*([^*]+)\*\)")
    for i, line in enumerate(source_text.splitlines(), 1):
        for m in pattern.finditer(line):
            results.append((i, m.group(1).strip()))
    return results


def parse_attribute_text(text: str) -> SynthesisAttribute | None:
    """Parse the inside of a ``(* ... *)`` block into a SynthesisAttribute."""
    text = text.strip()
    if "=" in text:
        name, _, val = text.partition("=")
        name = name.strip()
        val = val.strip().strip('"').strip("'")
    else:
        name = text
        val = "true"
    at = attribute_type_from_str(name)
    if at is None:
        return None
    return SynthesisAttribute(type=at, value=val)


def find_typed_attributes(
    source_text: str,
) -> list[tuple[int, SynthesisAttribute]]:
    """Like :func:`find_attributes_in_source` but returns parsed objects."""
    parsed: list[tuple[int, SynthesisAttribute]] = []
    for line, text in find_attributes_in_source(source_text):
        attr = parse_attribute_text(text)
        if attr is not None:
            parsed.append((line, attr))
    return parsed


def _leading_indent(line: str) -> str:
    indent_chars: list[str] = []
    for c in line:
        if c in (" ", "\t"):
            indent_chars.append(c)
        else:
            break
    return "".join(indent_chars)


def insert_attribute_before(
    source_text: str,
    line_num: int,
    attr: SynthesisAttribute,
) -> str:
    """Insert an attribute on the line directly before ``line_num``.

    The new line is indented to match the target line. ``line_num`` is
    1-based.
    """
    lines = source_text.splitlines()
    if not (0 < line_num <= len(lines)):
        return source_text
    target_line = lines[line_num - 1]
    indent = _leading_indent(target_line)
    new_line = indent + attr.to_verilog()
    lines.insert(line_num - 1, new_line)
    # Preserve trailing newline behavior
    suffix = "\n" if source_text.endswith("\n") else ""
    return "\n".join(lines) + suffix


def insert_attribute_inline(
    source_text: str,
    line_num: int,
    attr: SynthesisAttribute,
) -> str:
    """Insert the attribute as a prefix on the target line itself."""
    lines = source_text.splitlines()
    if not (0 < line_num <= len(lines)):
        return source_text
    target = lines[line_num - 1]
    indent = _leading_indent(target)
    rest = target[len(indent) :]
    lines[line_num - 1] = f"{indent}{attr.to_verilog()} {rest}"
    suffix = "\n" if source_text.endswith("\n") else ""
    return "\n".join(lines) + suffix


def remove_attribute_at(source_text: str, line_num: int) -> str:
    """Remove the attribute marker(s) from a specific line.

    If the entire line is just an attribute marker the line is deleted;
    otherwise inline markers are stripped from it.
    """
    lines = source_text.splitlines()
    if not (0 < line_num <= len(lines)):
        return source_text
    line = lines[line_num - 1]
    pattern = re.compile(r"\(\*[^*]+\*\)\s*")
    stripped = pattern.sub("", line).rstrip()
    if not stripped:
        del lines[line_num - 1]
    else:
        lines[line_num - 1] = stripped
    suffix = "\n" if source_text.endswith("\n") else ""
    return "\n".join(lines) + suffix


def list_supported_attributes() -> list[AttributeType]:
    return list(AttributeType)


def attribute_help_table() -> list[tuple[str, str]]:
    """Return a list of ``(name, description)`` for UI display."""
    return [(at.value, ATTRIBUTE_DESCRIPTIONS[at]) for at in AttributeType]


def validate_value(attr_type: AttributeType, value: str) -> bool:
    """Return True if ``value`` is a recognized choice for ``attr_type``."""
    allowed = ATTRIBUTE_VALUES.get(attr_type, ["true", "false"])
    return value in allowed

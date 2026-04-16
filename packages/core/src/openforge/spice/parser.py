"""SPICE / SPECTRE netlist parser.

This module implements a tolerant, pure-Python parser for the dialect of
SPICE most commonly seen in open-source PDKs (ngspice / Xyce / HSPICE-ish).
It is intentionally lenient: unknown cards are preserved as raw text in the
``options`` dict so they round-trip through :func:`write_spice` without
losing information.

The parser handles:

* Component lines (``R1 a b 1k``, ``M1 d g s b nmos w=1u l=180n`` ...)
* ``.model`` cards including multi-line parameter blocks
* ``.subckt`` / ``.ends`` blocks (recursive components inside)
* ``.option`` / ``.options``
* ``.include`` / ``.lib``
* ``*`` and ``;`` style comments
* ``+`` line continuations
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SpiceComponent:
    """A single component instance in a netlist."""

    name: str
    type: str  # R/C/L/V/I/M/Q/D/X
    nodes: list[str]
    value: str = ""
    parameters: dict[str, str] = field(default_factory=dict)

    def to_line(self) -> str:
        """Reconstruct the original SPICE line."""
        parts: list[str] = [self.name, *self.nodes]
        if self.value:
            parts.append(self.value)
        for k, v in self.parameters.items():
            parts.append(f"{k}={v}")
        return " ".join(parts)


@dataclass
class SpiceModel:
    """A ``.model`` card."""

    name: str
    type: str
    parameters: dict[str, str] = field(default_factory=dict)

    def to_line(self) -> str:
        body = " ".join(f"{k}={v}" for k, v in self.parameters.items())
        if body:
            return f".model {self.name} {self.type} ({body})"
        return f".model {self.name} {self.type}"


@dataclass
class SpiceSubckt:
    """A ``.subckt`` definition with its body."""

    name: str
    ports: list[str]
    components: list[SpiceComponent] = field(default_factory=list)
    parameters: dict[str, str] = field(default_factory=dict)

    def to_lines(self) -> list[str]:
        head = f".subckt {self.name} " + " ".join(self.ports)
        if self.parameters:
            head += " " + " ".join(f"{k}={v}" for k, v in self.parameters.items())
        out = [head]
        out.extend(c.to_line() for c in self.components)
        out.append(f".ends {self.name}")
        return out


@dataclass
class SpiceNetlist:
    """A complete (parsed) SPICE netlist."""

    title: str = ""
    components: list[SpiceComponent] = field(default_factory=list)
    models: dict[str, SpiceModel] = field(default_factory=dict)
    subckts: dict[str, SpiceSubckt] = field(default_factory=dict)
    options: dict[str, str] = field(default_factory=dict)
    includes: list[Path] = field(default_factory=list)
    nets: set[str] = field(default_factory=set)
    raw_lines: list[str] = field(default_factory=list)

    def stats(self) -> dict[str, int]:
        """Return a small summary used by the desktop panel."""
        type_counts: dict[str, int] = {}
        for c in self.components:
            type_counts[c.type] = type_counts.get(c.type, 0) + 1
        return {
            "components": len(self.components),
            "subcircuits": len(self.subckts),
            "models": len(self.models),
            "nets": len(self.nets),
            "includes": len(self.includes),
            **{f"type_{k}": v for k, v in type_counts.items()},
        }


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_COMMENT_PREFIXES = ("*", ";", "//")
_DEVICE_LETTERS: dict[str, str] = {
    "R": "R",
    "C": "C",
    "L": "L",
    "V": "V",
    "I": "I",
    "M": "M",
    "Q": "Q",
    "D": "D",
    "X": "X",
    "K": "K",
    "B": "B",
    "E": "E",
    "F": "F",
    "G": "G",
    "H": "H",
    "J": "J",
    "T": "T",
    "S": "S",
    "U": "U",
    "W": "W",
}

# Number of *positional* nodes for each device type, before parameters/value.
# (Used as a hint - parser falls back to "everything looking like a node".)
_DEVICE_NODE_COUNT: dict[str, int] = {
    "R": 2,
    "C": 2,
    "L": 2,
    "V": 2,
    "I": 2,
    "D": 2,
    "Q": 3,
    "M": 4,
    "J": 3,
    "K": 0,
}

_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")


def _is_comment(line: str) -> bool:
    s = line.lstrip()
    return any(s.startswith(p) for p in _COMMENT_PREFIXES)


def _strip_inline_comment(line: str) -> str:
    """Strip ``; ...`` and ``$ ...`` style trailing comments."""
    out_chars: list[str] = []
    in_quote = False
    for ch in line:
        if ch in ('"', "'"):
            in_quote = not in_quote
            out_chars.append(ch)
            continue
        if not in_quote and ch in (";", "$"):
            break
        out_chars.append(ch)
    return "".join(out_chars).rstrip()


def _logical_lines(text: str) -> list[str]:
    """Collapse SPICE physical lines into logical lines (handle ``+``)."""
    raw = text.splitlines()
    out: list[str] = []
    for line in raw:
        if not line.strip():
            continue
        if _is_comment(line):
            continue
        s = _strip_inline_comment(line)
        if not s.strip():
            continue
        if s.lstrip().startswith("+"):
            cont = s.lstrip()[1:].strip()
            if out:
                out[-1] = out[-1] + " " + cont
            else:
                out.append(cont)
        else:
            out.append(s.strip())
    return out


def _split_kv(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split a token list into positional tokens and ``key=value`` pairs.

    Handles tokens that contain ``=`` directly (``w=1u``) and the rare
    spaced form (``w = 1u``).
    """
    positional: list[str] = []
    params: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if "=" in tok and not tok.startswith("="):
            key, _, val = tok.partition("=")
            if val == "" and i + 1 < len(tokens):
                val = tokens[i + 1]
                i += 1
            params[key.lower()] = val
        elif i + 1 < len(tokens) and tokens[i + 1] == "=" and i + 2 < len(tokens):
            params[tok.lower()] = tokens[i + 2]
            i += 2
        else:
            positional.append(tok)
        i += 1
    return positional, params


def _parse_component(line: str) -> SpiceComponent | None:
    """Parse a single component line (no leading dot)."""
    tokens = line.split()
    if not tokens:
        return None
    name = tokens[0]
    letter = name[0].upper()
    if letter not in _DEVICE_LETTERS:
        return None
    dev_type = _DEVICE_LETTERS[letter]
    rest = tokens[1:]
    positional, params = _split_kv(rest)

    expected = _DEVICE_NODE_COUNT.get(dev_type)
    if dev_type == "X":
        # X<name> n1 n2 ... subckt_name [params]
        if not positional:
            return SpiceComponent(name=name, type=dev_type, nodes=[], value="", parameters=params)
        # Last positional is the subckt name; everything before is nodes.
        subckt_name = positional[-1]
        nodes = positional[:-1]
        return SpiceComponent(
            name=name,
            type=dev_type,
            nodes=nodes,
            value=subckt_name,
            parameters=params,
        )
    if expected is None:
        # Heuristic: assume first half is nodes, last token is value/model.
        if len(positional) >= 2:
            nodes = positional[:-1]
            value = positional[-1]
        else:
            nodes = positional
            value = ""
        return SpiceComponent(
            name=name, type=dev_type, nodes=nodes, value=value, parameters=params
        )

    nodes = positional[:expected]
    tail = positional[expected:]
    value = " ".join(tail) if tail else ""
    return SpiceComponent(
        name=name,
        type=dev_type,
        nodes=nodes,
        value=value,
        parameters=params,
    )


def _parse_model(line: str) -> SpiceModel | None:
    """Parse a ``.model name type (params)`` line."""
    body = line[len(".model") :].strip()
    # Pull off the parenthesised parameter block (may have spaces).
    paren_idx = body.find("(")
    params_text = ""
    if paren_idx >= 0:
        end = body.rfind(")")
        params_text = body[paren_idx + 1 : end if end > paren_idx else len(body)]
        head = body[:paren_idx].strip()
    else:
        head = body
    head_tokens = head.split()
    if len(head_tokens) < 2:
        return None
    name, mtype = head_tokens[0], head_tokens[1]
    params: dict[str, str] = {}
    if params_text:
        # tokens may be "k=v k=v" or "k = v"
        toks = params_text.replace("=", " = ").split()
        _, params = _split_kv(toks)
    elif len(head_tokens) > 2:
        _, params = _split_kv(head_tokens[2:])
    return SpiceModel(name=name, type=mtype.lower(), parameters=params)


def _parse_subckt_header(line: str) -> SpiceSubckt | None:
    """Parse a ``.subckt name p1 p2 ... [k=v ...]`` line."""
    tokens = line.split()[1:]  # drop ".subckt"
    if not tokens:
        return None
    name = tokens[0]
    rest = tokens[1:]
    positional, params = _split_kv(rest)
    return SpiceSubckt(name=name, ports=positional, parameters=params)


def parse_spice(filepath: Path) -> SpiceNetlist:
    """Parse a SPICE / SPECTRE-flavoured netlist file."""
    filepath = Path(filepath)
    text = filepath.read_text(encoding="utf-8", errors="replace")
    return parse_spice_text(text, source=filepath)


def parse_spice_text(text: str, source: Path | None = None) -> SpiceNetlist:
    """Parse SPICE netlist content already loaded into memory."""
    netlist = SpiceNetlist()
    lines = _logical_lines(text)
    netlist.raw_lines = list(lines)

    # The very first line of a SPICE deck is conventionally the title.
    if lines and not lines[0].lstrip().startswith("."):
        first = lines[0].strip()
        if first and first[0].upper() not in _DEVICE_LETTERS:
            netlist.title = first
            lines = lines[1:]

    current_subckt: SpiceSubckt | None = None
    end_seen = False

    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        low = line.lower()
        if not low:
            continue

        if low.startswith(".end") and not low.startswith(".ends"):
            end_seen = True
            continue
        if low.startswith(".ends"):
            if current_subckt is not None:
                netlist.subckts[current_subckt.name] = current_subckt
                current_subckt = None
            continue
        if low.startswith(".subckt"):
            current_subckt = _parse_subckt_header(line)
            continue
        if low.startswith(".model"):
            model = _parse_model(line)
            if model is not None:
                netlist.models[model.name] = model
            continue
        if low.startswith(".include") or low.startswith(".inc"):
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                inc = parts[1].strip().strip("'\"")
                netlist.includes.append(Path(inc))
            continue
        if low.startswith(".lib"):
            netlist.options[".lib"] = line.split(maxsplit=1)[1] if " " in line else ""
            continue
        if low.startswith(".option"):
            body = line.split(maxsplit=1)[1] if " " in line else ""
            for tok in body.split():
                if "=" in tok:
                    k, _, v = tok.partition("=")
                    netlist.options[k.strip().lower()] = v.strip()
                else:
                    netlist.options[tok.strip().lower()] = "1"
            continue
        if low.startswith(".global"):
            for n in line.split()[1:]:
                netlist.nets.add(n)
            continue
        if low.startswith(".param"):
            body = line.split(maxsplit=1)[1] if " " in line else ""
            for tok in body.split():
                if "=" in tok:
                    k, _, v = tok.partition("=")
                    netlist.options[f"param.{k.lower()}"] = v
            continue
        if low.startswith("."):
            # Unknown directive; preserve verbatim.
            netlist.options[f"_raw{len(netlist.options)}"] = line
            continue

        comp = _parse_component(line)
        if comp is None:
            continue
        if current_subckt is not None:
            current_subckt.components.append(comp)
        else:
            netlist.components.append(comp)
            for n in comp.nodes:
                netlist.nets.add(n)

    # Flush any unclosed subckt (defensive: shouldn't normally happen).
    if current_subckt is not None:
        netlist.subckts[current_subckt.name] = current_subckt

    _ = end_seen  # informational only
    return netlist


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_spice(netlist: SpiceNetlist, filepath: Path) -> Path:
    """Serialise a :class:`SpiceNetlist` back to disk."""
    filepath = Path(filepath)
    out: list[str] = []
    out.append(netlist.title or "* OpenForge generated netlist")
    for inc in netlist.includes:
        out.append(f".include {inc.as_posix()}")
    for k, v in netlist.options.items():
        if k.startswith("_raw"):
            out.append(v)
        elif k.startswith("param."):
            out.append(f".param {k[6:]}={v}")
        elif k == ".lib":
            out.append(f".lib {v}")
        else:
            out.append(f".option {k}={v}")
    for model in netlist.models.values():
        out.append(model.to_line())
    for sub in netlist.subckts.values():
        out.extend(sub.to_lines())
    for comp in netlist.components:
        out.append(comp.to_line())
    out.append(".end")
    filepath.write_text("\n".join(out) + "\n", encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Helpers used by the desktop UI
# ---------------------------------------------------------------------------


def find_top_subckt(netlist: SpiceNetlist) -> str | None:
    """Heuristically pick the most likely top-level subcircuit.

    The heuristic counts how many times each subckt is *instantiated* by
    others; the unique subckt with no parent is considered the top.
    """
    if not netlist.subckts:
        return None
    referenced: set[str] = set()
    for sub in netlist.subckts.values():
        for c in sub.components:
            if c.type == "X" and c.value:
                referenced.add(c.value)
    for c in netlist.components:
        if c.type == "X" and c.value:
            referenced.add(c.value)
    candidates = [n for n in netlist.subckts if n not in referenced]
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        return candidates[0]
    return next(iter(netlist.subckts))


def list_node_voltages(netlist: SpiceNetlist) -> list[str]:
    """Return ``v(net)`` strings for every distinct net in the design."""
    return [f"v({n})" for n in sorted(netlist.nets)]


__all__ = [
    "SpiceComponent",
    "SpiceModel",
    "SpiceSubckt",
    "SpiceNetlist",
    "parse_spice",
    "parse_spice_text",
    "write_spice",
    "find_top_subckt",
    "list_node_voltages",
]

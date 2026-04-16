"""SPICE netlist parser and writer.

Supports the common subset of SPICE used by ngspice / Xyce / HSPICE:

- Top-level devices (M, R, C, L, V, I, D, Q, X)
- Hierarchical ``.subckt`` definitions (with parameters)
- ``.model`` cards
- ``.include`` / ``.lib`` references
- ``.param`` global parameters
- Line continuation with leading ``+``
- ``*`` and inline ``$`` comments

The parser is intentionally permissive: unknown cards are preserved as raw
text so that round-tripping a netlist does not lose information.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SpiceDevice:
    """A single SPICE device instance.

    The SPICE device letter (first character of the instance name) determines
    the type. ``nodes`` is the list of net names connected to this device,
    in the order required by SPICE. ``parameters`` holds key=value pairs
    that follow the model name (or replace the model for passives).
    """

    name: str
    type: str
    nodes: list[str]
    model: str = ""
    parameters: dict[str, str] = field(default_factory=dict)
    raw: str = ""

    def to_string(self) -> str:
        if self.raw:
            return self.raw
        parts: list[str] = [self.name, *self.nodes]
        if self.model:
            parts.append(self.model)
        for k, v in self.parameters.items():
            parts.append(f"{k}={v}")
        return " ".join(parts)


@dataclass
class SpiceSubckt:
    """A ``.subckt`` definition (may be nested)."""

    name: str
    ports: list[str]
    devices: list[SpiceDevice] = field(default_factory=list)
    parameters: dict[str, str] = field(default_factory=dict)
    subckts: dict[str, SpiceSubckt] = field(default_factory=dict)
    models: dict[str, dict[str, str]] = field(default_factory=dict)

    def to_string(self) -> str:
        header = f".subckt {self.name} " + " ".join(self.ports)
        if self.parameters:
            header += " " + " ".join(f"{k}={v}" for k, v in self.parameters.items())
        lines = [header]
        for d in self.devices:
            lines.append(d.to_string())
        for sub in self.subckts.values():
            lines.append(sub.to_string())
        for mname, mparams in self.models.items():
            lines.append(_format_model(mname, mparams))
        lines.append(f".ends {self.name}")
        return "\n".join(lines)


@dataclass
class SpiceNetlist:
    """A complete SPICE netlist."""

    title: str = ""
    top_devices: list[SpiceDevice] = field(default_factory=list)
    subckts: dict[str, SpiceSubckt] = field(default_factory=dict)
    models: dict[str, dict[str, str]] = field(default_factory=dict)
    includes: list[str] = field(default_factory=list)
    libraries: list[tuple[str, str]] = field(default_factory=list)
    parameters: dict[str, str] = field(default_factory=dict)
    options: list[str] = field(default_factory=list)
    raw_cards: list[str] = field(default_factory=list)

    # ----- introspection -----
    def find_device(self, name: str) -> SpiceDevice | None:
        for d in self.top_devices:
            if d.name.lower() == name.lower():
                return d
        return None

    def all_devices(self) -> list[SpiceDevice]:
        out = list(self.top_devices)
        for sub in self.subckts.values():
            out.extend(_recurse_devices(sub))
        return out

    def device_count_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in self.all_devices():
            counts[d.type] = counts.get(d.type, 0) + 1
        return counts

    # ----- serialization -----
    def to_string(self) -> str:
        lines: list[str] = []
        lines.append(self.title or "* OpenForge SPICE netlist")
        for inc in self.includes:
            lines.append(f".include {inc}")
        for lib_path, lib_section in self.libraries:
            lines.append(f".lib {lib_path} {lib_section}")
        for k, v in self.parameters.items():
            lines.append(f".param {k}={v}")
        for opt in self.options:
            lines.append(f".options {opt}")
        for mname, mparams in self.models.items():
            lines.append(_format_model(mname, mparams))
        for sub in self.subckts.values():
            lines.append(sub.to_string())
        for dev in self.top_devices:
            lines.append(dev.to_string())
        for raw in self.raw_cards:
            lines.append(raw)
        lines.append(".end")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Device type table
# ---------------------------------------------------------------------------


_DEVICE_LETTER_TO_TYPE: dict[str, str] = {
    "M": "mosfet",
    "R": "resistor",
    "C": "capacitor",
    "L": "inductor",
    "K": "mutual",
    "V": "vsource",
    "I": "isource",
    "D": "diode",
    "Q": "bjt",
    "J": "jfet",
    "X": "subckt",
    "B": "bsource",
    "E": "vcvs",
    "F": "cccs",
    "G": "vccs",
    "H": "ccvs",
    "T": "tline",
    "S": "switch",
    "W": "iswitch",
    "U": "uniform_rc",
}

# Number of mandatory nodes per device letter (used to split nodes/model).
_DEVICE_NODE_COUNT: dict[str, int] = {
    "M": 4,
    "R": 2,
    "C": 2,
    "L": 2,
    "V": 2,
    "I": 2,
    "D": 2,
    "Q": 3,
    "J": 3,
    "E": 4,
    "F": 2,
    "G": 4,
    "H": 2,
    "S": 4,
    "W": 2,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_spice(filepath: Path | str) -> SpiceNetlist:
    """Parse a SPICE netlist file."""
    filepath = Path(filepath)
    text = filepath.read_text(encoding="utf-8", errors="replace")
    return parse_spice_text(text)


def parse_spice_text(text: str) -> SpiceNetlist:
    """Parse a SPICE netlist from a string."""
    lines = _join_continuations(_strip_comments(text.splitlines()))
    netlist = SpiceNetlist()
    if lines:
        netlist.title = lines[0].rstrip()
        body = lines[1:]
    else:
        body = []
    _parse_block(body, netlist, parent_subckt=None)
    return netlist


def write_spice(netlist: SpiceNetlist, filepath: Path | str) -> None:
    """Write SPICE netlist to file."""
    Path(filepath).write_text(netlist.to_string(), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tokenization helpers
# ---------------------------------------------------------------------------


_PARAM_RX = re.compile(r"([A-Za-z_][\w]*)\s*=\s*('[^']*'|\"[^\"]*\"|\{[^}]*\}|\S+)")


def _strip_comments(lines: Iterable[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        s = line.rstrip("\r\n")
        # Full-line comment
        if s.lstrip().startswith("*"):
            out.append("")
            continue
        # Inline $ comment
        if "$" in s:
            s = s.split("$", 1)[0]
        # Inline ; comment (HSPICE)
        if ";" in s:
            s = s.split(";", 1)[0]
        out.append(s.rstrip())
    return out


def _join_continuations(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if line.startswith("+") and out:
            out[-1] = out[-1] + " " + line[1:].strip()
        else:
            out.append(line)
    return [ln for ln in out if ln.strip()]


def _parse_kv(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split a token list into positional tokens and key=value parameters."""
    positional: list[str] = []
    params: dict[str, str] = {}
    for tok in tokens:
        if "=" in tok and not tok.startswith("="):
            k, _, v = tok.partition("=")
            params[k.strip()] = v.strip()
        else:
            positional.append(tok)
    return positional, params


# ---------------------------------------------------------------------------
# Block parser
# ---------------------------------------------------------------------------


def _parse_block(
    lines: list[str],
    netlist: SpiceNetlist,
    parent_subckt: SpiceSubckt | None,
) -> int:
    """Parse a list of cards into either the top netlist or a subckt.

    Returns the number of lines consumed (used by recursive subckt parsing).
    """
    i = 0
    target_subckts = parent_subckt.subckts if parent_subckt else netlist.subckts
    target_models = parent_subckt.models if parent_subckt else netlist.models
    target_devices = parent_subckt.devices if parent_subckt else netlist.top_devices

    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        low = line.lower()

        if low.startswith(".end") and not low.startswith(".ends"):
            return i
        if low.startswith(".ends"):
            return i
        if low.startswith(".subckt"):
            sub = _parse_subckt_header(line)
            consumed = _parse_block(lines[i:], netlist, sub)
            i += consumed
            target_subckts[sub.name] = sub
            continue
        if low.startswith(".model"):
            name, params = _parse_model_card(line)
            target_models[name] = params
            continue
        if low.startswith(".include"):
            path = line.split(None, 1)[1].strip().strip('"').strip("'")
            netlist.includes.append(path)
            continue
        if low.startswith(".lib"):
            parts = line.split()
            if len(parts) >= 3:
                netlist.libraries.append((parts[1], parts[2]))
            elif len(parts) == 2:
                netlist.libraries.append((parts[1], ""))
            continue
        if low.startswith(".param"):
            rest = line.split(None, 1)[1] if len(line.split(None, 1)) > 1 else ""
            for m in _PARAM_RX.finditer(rest):
                netlist.parameters[m.group(1)] = m.group(2)
            continue
        if low.startswith(".option"):
            netlist.options.append(line.split(None, 1)[1] if " " in line else "")
            continue
        if low.startswith("."):
            # Unknown directive: store raw
            netlist.raw_cards.append(line)
            continue

        # Otherwise: a device instance.
        dev = _parse_device(line)
        if dev is not None:
            target_devices.append(dev)

    return i


def _parse_subckt_header(line: str) -> SpiceSubckt:
    tokens = line.split()
    # tokens[0] == ".subckt"
    name = tokens[1]
    rest = tokens[2:]
    positional, params = _parse_kv(rest)
    return SpiceSubckt(name=name, ports=positional, parameters=params)


def _parse_model_card(line: str) -> tuple[str, dict[str, str]]:
    # .model NAME TYPE (key=val ...)
    # may also appear without parens
    tokens = line.split(None, 2)
    if len(tokens) < 3:
        return tokens[1] if len(tokens) > 1 else "", {}
    name = tokens[1]
    rest = tokens[2]
    type_match = re.match(r"\s*([A-Za-z_]\w*)", rest)
    mtype = type_match.group(1) if type_match else ""
    body = rest[len(mtype) :].strip() if mtype else rest
    body = body.strip("()")
    params: dict[str, str] = {"__type__": mtype}
    for m in _PARAM_RX.finditer(body):
        params[m.group(1).lower()] = m.group(2)
    return name, params


def _parse_device(line: str) -> SpiceDevice | None:
    tokens = line.split()
    if not tokens:
        return None
    name = tokens[0]
    letter = name[0].upper()
    dtype = _DEVICE_LETTER_TO_TYPE.get(letter, "unknown")

    # Strip key=value tokens to find positional ones
    positional, params = _parse_kv(tokens[1:])

    if letter == "X":
        # Subckt instance: nodes... subckt_name [params]
        if positional:
            subname = positional[-1]
            nodes = positional[:-1]
            return SpiceDevice(
                name=name,
                type="subckt",
                nodes=nodes,
                model=subname,
                parameters=params,
                raw=line,
            )
        return SpiceDevice(name=name, type="subckt", nodes=[], raw=line)

    n_nodes = _DEVICE_NODE_COUNT.get(letter, 2)
    nodes = positional[:n_nodes]
    rest = positional[n_nodes:]
    model = rest[0] if rest else ""
    extras = rest[1:]
    # Treat any extras as positional model parameters; tag with index keys
    for idx, extra in enumerate(extras):
        params.setdefault(f"_pos{idx}", extra)
    return SpiceDevice(
        name=name,
        type=dtype,
        nodes=nodes,
        model=model,
        parameters=params,
        raw=line,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_model(name: str, params: dict[str, str]) -> str:
    mtype = params.get("__type__", "")
    other = {k: v for k, v in params.items() if k != "__type__"}
    body = " ".join(f"{k}={v}" for k, v in other.items())
    return f".model {name} {mtype} ({body})"


def _recurse_devices(sub: SpiceSubckt) -> list[SpiceDevice]:
    out = list(sub.devices)
    for child in sub.subckts.values():
        out.extend(_recurse_devices(child))
    return out


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------


def make_resistor(name: str, n_plus: str, n_minus: str, value: str) -> SpiceDevice:
    return SpiceDevice(name=name, type="resistor", nodes=[n_plus, n_minus], model=value)


def make_capacitor(name: str, n_plus: str, n_minus: str, value: str) -> SpiceDevice:
    return SpiceDevice(name=name, type="capacitor", nodes=[n_plus, n_minus], model=value)


def make_inductor(name: str, n_plus: str, n_minus: str, value: str) -> SpiceDevice:
    return SpiceDevice(name=name, type="inductor", nodes=[n_plus, n_minus], model=value)


def make_vsource(
    name: str, n_plus: str, n_minus: str, dc_value: float = 0.0, ac: float | None = None
) -> SpiceDevice:
    params: dict[str, str] = {"DC": str(dc_value)}
    if ac is not None:
        params["AC"] = str(ac)
    return SpiceDevice(name=name, type="vsource", nodes=[n_plus, n_minus], parameters=params)


def make_mosfet(
    name: str,
    drain: str,
    gate: str,
    source: str,
    body: str,
    model: str,
    width: str = "1u",
    length: str = "1u",
) -> SpiceDevice:
    return SpiceDevice(
        name=name,
        type="mosfet",
        nodes=[drain, gate, source, body],
        model=model,
        parameters={"W": width, "L": length},
    )


def make_subckt_instance(
    name: str, nodes: list[str], subckt_name: str, **params: str
) -> SpiceDevice:
    return SpiceDevice(
        name=name,
        type="subckt",
        nodes=list(nodes),
        model=subckt_name,
        parameters={k: str(v) for k, v in params.items()},
    )


__all__ = [
    "SpiceDevice",
    "SpiceSubckt",
    "SpiceNetlist",
    "parse_spice",
    "parse_spice_text",
    "write_spice",
    "make_resistor",
    "make_capacitor",
    "make_inductor",
    "make_vsource",
    "make_mosfet",
    "make_subckt_instance",
]

"""SPEF (Standard Parasitic Exchange Format) parser.

Handles production-scale DSPEF (Detailed SPEF) files emitted by tools such
as OpenROAD's ``rcx`` / ``write_spef``, Synopsys StarRC and Cadence Quantus.

The parser is streaming-friendly and tolerant of whitespace, name-maps and
hierarchical nets.  Only the fields needed by downstream analysis
(capacitance/resistance totals, cross-coupling, histograms) are retained —
inductance and delay sections are skipped.

Reference: IEEE 1481-2009 "Standard for Integrated Circuit (IC) Delay
and Power Calculation System".
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

_CAP_TO_PF = {
    "FF": 1.0e-3,
    "PF": 1.0,
    "NF": 1.0e3,
}

_RES_TO_OHM = {
    "OHM": 1.0,
    "KOHM": 1.0e3,
    "MOHM": 1.0e6,
}

_TIME_TO_NS = {
    "PS": 1.0e-3,
    "NS": 1.0,
    "US": 1.0e3,
}

_IND_TO_NH = {
    "PH": 1.0e-3,
    "NH": 1.0,
    "UH": 1.0e3,
}


def _parse_unit_line(value: str, scale: dict[str, float]) -> float:
    """Parse a ``*?_UNIT N UNIT`` payload, returning the conversion factor.

    Returns the multiplier to convert a raw SPEF scalar into the canonical
    unit (pF for cap, Ohm for res, ns for time, nH for ind).
    """
    parts = value.strip().split()
    if len(parts) < 2:
        return 1.0
    try:
        n = float(parts[0])
    except ValueError:
        return 1.0
    unit = parts[1].upper()
    return n * scale.get(unit, 1.0)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SpefPort(BaseModel):
    """A top-level port on the design (``*PORTS`` entry)."""

    model_config = ConfigDict(extra="ignore")

    name: str
    direction: str = ""  # I, O, B
    cap_pf: float = 0.0


class SpefCap(BaseModel):
    """A lumped grounded or coupling capacitance."""

    model_config = ConfigDict(extra="ignore")

    node: str  # for coupling caps: "<net_a>:<node_a>|<net_b>:<node_b>"
    cap_pf: float
    coupled_to: str | None = None  # second node when this is a coupling cap


class SpefRes(BaseModel):
    """A lumped interconnect resistance between two nodes on a net."""

    model_config = ConfigDict(extra="ignore")

    node1: str
    node2: str
    res_ohm: float


class SpefNet(BaseModel):
    """A ``*D_NET`` record: one physical net with detailed R/C."""

    model_config = ConfigDict(extra="ignore")

    name: str
    total_cap_pf: float = 0.0
    ports: list[SpefPort] = Field(default_factory=list)
    caps: list[SpefCap] = Field(default_factory=list)
    resistances: list[SpefRes] = Field(default_factory=list)

    # --- convenience ------------------------------------------------------

    @property
    def max_cap_pf(self) -> float:
        return max((c.cap_pf for c in self.caps), default=0.0)

    @property
    def max_res_ohm(self) -> float:
        return max((r.res_ohm for r in self.resistances), default=0.0)

    @property
    def total_res_ohm(self) -> float:
        return sum(r.res_ohm for r in self.resistances)

    @property
    def aggressor_count(self) -> int:
        """Number of distinct neighbouring nets this net couples to."""
        agg: set[str] = set()
        for c in self.caps:
            if c.coupled_to:
                other_net = c.coupled_to.split(":", 1)[0]
                if other_net != self.name:
                    agg.add(other_net)
        return len(agg)

    def aggressors(self) -> dict[str, float]:
        """Return {neighbour_net -> summed coupling cap in pF}."""
        out: dict[str, float] = {}
        for c in self.caps:
            if not c.coupled_to:
                continue
            other_net = c.coupled_to.split(":", 1)[0]
            if other_net == self.name:
                continue
            out[other_net] = out.get(other_net, 0.0) + c.cap_pf
        return out


class SpefFile(BaseModel):
    """A fully parsed SPEF file."""

    model_config = ConfigDict(extra="ignore")

    design_name: str = ""
    units: dict[str, float] = Field(default_factory=dict)
    # Keys: T_UNIT (ns), C_UNIT (pF), R_UNIT (ohm), L_UNIT (nH)
    divider: str = "/"
    delimiter: str = ":"
    nets: list[SpefNet] = Field(default_factory=list)

    _re_section: ClassVar[re.Pattern[str]] = re.compile(r"^\*[A-Z_]")

    # ------------------------------------------------------------------ api

    @classmethod
    def parse(cls, path: str | Path) -> SpefFile:
        """Parse a SPEF file from ``path``."""
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        return cls.parse_text(text)

    @classmethod
    def parse_text(cls, text: str) -> SpefFile:
        return _SpefParser(text).parse()

    # ------------------------------------------------------------------ qry

    def worst_cap_nets(self, n: int = 20) -> list[SpefNet]:
        return sorted(self.nets, key=lambda x: x.total_cap_pf, reverse=True)[:n]

    def worst_res_nets(self, n: int = 20) -> list[SpefNet]:
        return sorted(self.nets, key=lambda x: x.total_res_ohm, reverse=True)[:n]

    def total_cap(self) -> float:
        """Total grounded+coupling capacitance over all nets in pF."""
        return sum(n.total_cap_pf for n in self.nets)

    def total_res(self) -> float:
        """Total metal resistance over all nets in Ohms."""
        return sum(n.total_res_ohm for n in self.nets)

    def histogram_cap(self, bins: int = 30) -> tuple[list[float], list[int]]:
        """Return (bin_edges, counts) for per-net total capacitance."""
        return _histogram([n.total_cap_pf for n in self.nets], bins)

    def histogram_res(self, bins: int = 30) -> tuple[list[float], list[int]]:
        return _histogram([n.total_res_ohm for n in self.nets], bins)

    def find_net(self, name: str) -> SpefNet | None:
        for n in self.nets:
            if n.name == name:
                return n
        return None


# ---------------------------------------------------------------------------
# Parser implementation
# ---------------------------------------------------------------------------


def _histogram(values: list[float], bins: int) -> tuple[list[float], list[int]]:
    if not values:
        return ([0.0, 1.0], [0])
    lo = min(values)
    hi = max(values)
    if hi <= lo:
        hi = lo + 1.0
    step = (hi - lo) / bins
    edges = [lo + i * step for i in range(bins + 1)]
    counts = [0] * bins
    for v in values:
        idx = int((v - lo) / step)
        if idx >= bins:
            idx = bins - 1
        if idx < 0:
            idx = 0
        counts[idx] += 1
    return (edges, counts)


class _SpefParser:
    """Low level tokeniser/sectioniser for SPEF text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.file = SpefFile()
        self.name_map: dict[str, str] = {}
        self.c_scale = 1.0  # values * c_scale -> pF
        self.r_scale = 1.0  # values * r_scale -> Ohm

    # -- entry -------------------------------------------------------------

    def parse(self) -> SpefFile:
        text = self._strip_comments(self.text)
        self._parse_header(text)
        self._parse_name_map(text)
        self._parse_nets(text)
        self.file.units = {
            "C_UNIT": self.c_scale,
            "R_UNIT": self.r_scale,
            "T_UNIT": 1.0,
            "L_UNIT": 1.0,
        }
        return self.file

    # -- scrubbing ---------------------------------------------------------

    @staticmethod
    def _strip_comments(text: str) -> str:
        out: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == "/" and i + 1 < n and text[i + 1] == "/":
                j = text.find("\n", i)
                if j == -1:
                    break
                i = j
                continue
            if ch == "/" and i + 1 < n and text[i + 1] == "*":
                j = text.find("*/", i + 2)
                if j == -1:
                    break
                i = j + 2
                continue
            out.append(ch)
            i += 1
        return "".join(out)

    # -- header ------------------------------------------------------------

    def _parse_header(self, text: str) -> None:
        def grab(key: str) -> str | None:
            m = re.search(rf"^\*{key}\s+([^\n]+)", text, re.MULTILINE)
            return m.group(1).strip() if m else None

        if (v := grab("DESIGN")):
            self.file.design_name = v.strip('"')
        if (v := grab("DIVIDER")):
            self.file.divider = v.strip().split()[0]
        if (v := grab("DELIMITER")):
            self.file.delimiter = v.strip().split()[0]
        if (v := grab("C_UNIT")):
            self.c_scale = _parse_unit_line(v, _CAP_TO_PF)
        if (v := grab("R_UNIT")):
            self.r_scale = _parse_unit_line(v, _RES_TO_OHM)
        if (v := grab("T_UNIT")):
            self.file.units["T_UNIT"] = _parse_unit_line(v, _TIME_TO_NS)
        if (v := grab("L_UNIT")):
            self.file.units["L_UNIT"] = _parse_unit_line(v, _IND_TO_NH)

    # -- name map ----------------------------------------------------------

    def _parse_name_map(self, text: str) -> None:
        m = re.search(r"\*NAME_MAP(.*?)(?=\n\*PORTS|\n\*D_NET|\n\*PHYSICAL_PORTS|\Z)",
                      text, re.DOTALL)
        if not m:
            return
        body = m.group(1)
        for line in body.splitlines():
            line = line.strip()
            if not line or not line.startswith("*"):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                self.name_map[parts[0]] = parts[1].strip()

    def _resolve(self, token: str) -> str:
        """Replace ``*123`` refs with their mapped names (hierarchical path)."""
        if not token:
            return token
        # Fast path: no references
        if "*" not in token:
            return token
        # Replace *NNN tokens (possibly followed by delimiter/pin)
        def repl(m: re.Match[str]) -> str:
            key = m.group(0)
            return self.name_map.get(key, key)
        return re.sub(r"\*\d+", repl, token)

    # -- nets --------------------------------------------------------------

    def _parse_nets(self, text: str) -> None:
        # Split on *D_NET markers.  Use a lookahead so we keep the marker.
        chunks = re.split(r"(?=^\*D_NET\b)", text, flags=re.MULTILINE)
        for chunk in chunks:
            if not chunk.startswith("*D_NET"):
                continue
            net = self._parse_one_net(chunk)
            if net is not None:
                self.file.nets.append(net)

    def _parse_one_net(self, chunk: str) -> SpefNet | None:
        # Drop *END marker onward
        end_idx = chunk.find("*END")
        if end_idx != -1:
            chunk = chunk[:end_idx]

        lines = [l.strip() for l in chunk.splitlines() if l.strip()]
        if not lines:
            return None

        # Header: *D_NET <name> <total_cap>
        header = lines[0].split()
        if len(header) < 2:
            return None
        name = self._resolve(header[1])
        try:
            total_cap = float(header[2]) * self.c_scale if len(header) > 2 else 0.0
        except ValueError:
            total_cap = 0.0
        net = SpefNet(name=name, total_cap_pf=total_cap)

        section: str | None = None
        for line in lines[1:]:
            if line.startswith("*CONN"):
                section = "CONN"
                continue
            if line.startswith("*CAP"):
                section = "CAP"
                continue
            if line.startswith("*RES"):
                section = "RES"
                continue
            if line.startswith("*INDUC") or line.startswith("*L"):
                section = "IND"
                continue
            if line.startswith("*DRIVER") or line.startswith("*LOAD"):
                section = None
                continue
            if line.startswith("*"):
                # Some other subsection we don't care about
                if not line.startswith("*P") and not line.startswith("*I"):
                    section = None
                    continue

            if section == "CONN":
                self._parse_conn_entry(line, net)
            elif section == "CAP":
                self._parse_cap_entry(line, net)
            elif section == "RES":
                self._parse_res_entry(line, net)

        # If header didn't advertise a total cap, derive it.
        if net.total_cap_pf == 0.0 and net.caps:
            net.total_cap_pf = sum(c.cap_pf for c in net.caps)
        return net

    def _parse_conn_entry(self, line: str, net: SpefNet) -> None:
        # *P <port_name> <direction> [*C x y] [*L cap]
        # *I <inst:pin> <direction> [*C x y] [*L cap]
        parts = line.split()
        if len(parts) < 2:
            return
        kind = parts[0]
        if kind not in ("*P", "*I"):
            return
        name = self._resolve(parts[1])
        direction = parts[2] if len(parts) > 2 else ""
        cap_pf = 0.0
        # scan for *L cap token
        for i, tok in enumerate(parts):
            if tok == "*L" and i + 1 < len(parts):
                with contextlib.suppress(ValueError):
                    cap_pf = float(parts[i + 1]) * self.c_scale
                break
        net.ports.append(SpefPort(name=name, direction=direction, cap_pf=cap_pf))

    def _parse_cap_entry(self, line: str, net: SpefNet) -> None:
        # grounded:  <id> <node> <value>
        # coupling:  <id> <node_a> <node_b> <value>
        parts = line.split()
        if len(parts) < 3:
            return
        # drop leading id if numeric
        if parts[0].isdigit() or (parts[0].replace(".", "", 1).isdigit()):
            parts = parts[1:]
        if len(parts) < 2:
            return

        try:
            value = float(parts[-1])
        except ValueError:
            return
        cap_pf = value * self.c_scale

        if len(parts) == 2:
            node = self._resolve(parts[0])
            net.caps.append(SpefCap(node=node, cap_pf=cap_pf))
        else:
            node_a = self._resolve(parts[0])
            node_b = self._resolve(parts[1])
            net.caps.append(
                SpefCap(node=node_a, cap_pf=cap_pf, coupled_to=node_b)
            )

    def _parse_res_entry(self, line: str, net: SpefNet) -> None:
        # <id> <node1> <node2> <value>
        parts = line.split()
        if len(parts) < 3:
            return
        if parts[0].isdigit() or (parts[0].replace(".", "", 1).isdigit()):
            parts = parts[1:]
        if len(parts) < 3:
            return
        try:
            value = float(parts[2])
        except ValueError:
            return
        node1 = self._resolve(parts[0])
        node2 = self._resolve(parts[1])
        net.resistances.append(
            SpefRes(node1=node1, node2=node2, res_ohm=value * self.r_scale)
        )


__all__ = [
    "SpefPort",
    "SpefCap",
    "SpefRes",
    "SpefNet",
    "SpefFile",
]

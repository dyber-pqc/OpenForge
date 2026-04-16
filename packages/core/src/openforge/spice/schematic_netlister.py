"""Schematic-editor to SPICE-netlist bridge.

Converts an :class:`openforge_desktop.widgets.schematic_editor.Schematic`
document into a Pydantic-modelled :class:`SpiceSchematic` and produces a
flat ngspice-compatible netlist.

The mapping table understands the symbol names from the desktop
schematic editor's built-in library and translates them to either SPICE
primitives (R/C/L/D/Q/M/V/I) or to subckt instantiations (X) with the
right ``.model`` / ``.include`` directives emitted in the file header.

Models target the sky130A PDK device names by default
(``sky130_fd_pr__nfet_01v8`` etc.) so the resulting netlists can be
simulated with ngspice + sky130_fd_pr if installed, or with the
generic-ish 2N3904/2N3906/1N4148 models we ship inline otherwise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openforge_desktop.widgets.schematic_editor import Schematic


# ---------------------------------------------------------------------------
# Symbol -> SPICE element kind table
# ---------------------------------------------------------------------------

#: Maps schematic-editor symbol names (case-insensitive) to a *kind*
#: tag understood by :meth:`SpiceComponent.to_spice_line`.
SYMBOL_KIND_MAP: dict[str, str] = {
    "resistor": "R",
    "r": "R",
    "capacitor": "C",
    "c": "C",
    "polarized_capacitor": "C",
    "inductor": "L",
    "l": "L",
    "diode": "D",
    "d": "D",
    "led": "DLED",
    "zener": "DZ",
    "npn": "QNPN",
    "npn_bjt": "QNPN",
    "2n3904": "QNPN",
    "pnp": "QPNP",
    "pnp_bjt": "QPNP",
    "2n3906": "QPNP",
    "nmos": "MN",
    "n_mosfet": "MN",
    "pmos": "MP",
    "p_mosfet": "MP",
    "opamp": "XOPAMP",
    "op_amp": "XOPAMP",
    "vsource": "V",
    "voltage_source": "V",
    "vdc": "V",
    "vsin": "VSIN",
    "vpulse": "VPULSE",
    "isource": "I",
    "current_source": "I",
    "gnd": "GND",
    "ground": "GND",
    "vcc": "VCC",
    "vdd": "VCC",
}


_BUILTIN_INCLUDES = """\
* OpenForge built-in generic models
.model D1N4148 D(IS=2.52n RS=0.568 N=1.752 CJO=4p VJ=0.4 BV=100 IBV=100u)
.model DLED D(IS=2.0n RS=2.0 N=2.0 CJO=15p VJ=2.0 BV=5 IBV=10u)
.model DZ5V1 D(IS=1.0n RS=1.0 N=1.5 BV=5.1 IBV=20m)
.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF=416.4 NE=1.259 ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0 IKR=0 RC=1 CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p MJE=.2593 VJE=.75 TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2)
.model Q2N3906 PNP(IS=1.41f XTI=3 EG=1.11 VAF=18.7 BF=180.7 NE=1.5 ISE=0 IKF=80m XTB=1.5 BR=4.977 NC=2 ISC=0 IKR=0 RC=2.5 CJC=9.728p MJC=.5776 VJC=.75 FC=.5 CJE=8.063p MJE=.3677 VJE=.75 TR=33.42n TF=179.3p ITF=.4 VTF=4 XTF=6)

* Generic 1.8 V level-1 MOS used when sky130 PDK isn't installed
.model NMOS_GENERIC NMOS (LEVEL=1 VTO=0.4 KP=120u GAMMA=0.4 LAMBDA=0.02)
.model PMOS_GENERIC PMOS (LEVEL=1 VTO=-0.4 KP=40u  GAMMA=0.4 LAMBDA=0.04)

* Minimal opamp subckt (single-pole, gain 1e5, GBW 10 MHz)
.subckt OPAMP_IDEAL inp inn out vdd vss
Eout out 0 inp inn 1e5
.ends OPAMP_IDEAL
"""


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SpiceComponent(BaseModel):
    """A single placed SPICE element (post-translation)."""

    ref: str
    kind: str  # one of the entries in SYMBOL_KIND_MAP values
    value: str = ""
    model: str = ""
    nodes: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)

    def to_spice_line(self) -> str:
        ref = self.ref
        nodes = " ".join(self.nodes) if self.nodes else ""
        v = self.value
        m = self.model
        p = " ".join(f"{k}={v_}" for k, v_ in self.params.items())
        kind = self.kind.upper()

        if kind == "R":
            return f"R{_strip_prefix(ref, 'R')} {nodes} {v or '1k'}"
        if kind == "C":
            return f"C{_strip_prefix(ref, 'C')} {nodes} {v or '1u'}"
        if kind == "L":
            return f"L{_strip_prefix(ref, 'L')} {nodes} {v or '1u'}"
        if kind == "D":
            return f"D{_strip_prefix(ref, 'D')} {nodes} {m or 'D1N4148'}"
        if kind == "DLED":
            return f"D{_strip_prefix(ref, 'D')} {nodes} DLED"
        if kind == "DZ":
            return f"D{_strip_prefix(ref, 'D')} {nodes} DZ5V1"
        if kind == "QNPN":
            return f"Q{_strip_prefix(ref, 'Q')} {nodes} {m or 'Q2N3904'} {p}".rstrip()
        if kind == "QPNP":
            return f"Q{_strip_prefix(ref, 'Q')} {nodes} {m or 'Q2N3906'} {p}".rstrip()
        if kind == "MN":
            model = m or "sky130_fd_pr__nfet_01v8"
            base = f"M{_strip_prefix(ref, 'M')} {nodes} {model}"
            wl = self.params or {"W": "1u", "L": "0.15u"}
            return base + " " + " ".join(f"{k}={v_}" for k, v_ in wl.items())
        if kind == "MP":
            model = m or "sky130_fd_pr__pfet_01v8"
            base = f"M{_strip_prefix(ref, 'M')} {nodes} {model}"
            wl = self.params or {"W": "2u", "L": "0.15u"}
            return base + " " + " ".join(f"{k}={v_}" for k, v_ in wl.items())
        if kind == "XOPAMP":
            return f"X{_strip_prefix(ref, 'X')} {nodes} {m or 'OPAMP_IDEAL'}"
        if kind == "V":
            return f"V{_strip_prefix(ref, 'V')} {nodes} DC {v or '5'}"
        if kind == "VSIN":
            offset = self.params.get("offset", 0)
            amp = self.params.get("amp", 1)
            freq = self.params.get("freq", "1k")
            return f"V{_strip_prefix(ref, 'V')} {nodes} SIN({offset} {amp} {freq})"
        if kind == "VPULSE":
            v1 = self.params.get("v1", 0)
            v2 = self.params.get("v2", 5)
            td = self.params.get("td", 0)
            tr = self.params.get("tr", "1n")
            tf = self.params.get("tf", "1n")
            pw = self.params.get("pw", "10u")
            per = self.params.get("per", "20u")
            return (
                f"V{_strip_prefix(ref, 'V')} {nodes} "
                f"PULSE({v1} {v2} {td} {tr} {tf} {pw} {per})"
            )
        if kind == "I":
            return f"I{_strip_prefix(ref, 'I')} {nodes} DC {v or '1m'}"
        # GND/VCC are virtual — handled at netlist gen time
        return f"* unhandled element {ref} ({kind})"


def _strip_prefix(ref: str, letter: str) -> str:
    if ref.upper().startswith(letter.upper()):
        return ref[1:]
    return ref


class SpiceSchematic(BaseModel):
    """Pydantic representation of a flat analog schematic."""

    name: str = "untitled"
    components: list[SpiceComponent] = Field(default_factory=list)
    nets: dict[str, list[tuple[str, str]]] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    simulations: list[dict[str, Any]] = Field(default_factory=list)
    includes: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Construction from desktop Schematic
    # ------------------------------------------------------------------

    @classmethod
    def from_sch_editor(cls, sch: Schematic) -> SpiceSchematic:
        """Build a :class:`SpiceSchematic` from a desktop Schematic."""

        nets_raw: dict[str, list[tuple[str, str]]] = {}
        try:
            nets_raw = sch.generate_netlist()
        except Exception:  # pragma: no cover - defensive
            nets_raw = {}

        # Build a (refdes, pin) -> net_name index
        pin_to_net: dict[tuple[str, str], str] = {}
        for net_name, pins in nets_raw.items():
            for refdes, pin in pins:
                pin_to_net[(refdes, str(pin))] = net_name

        comps: list[SpiceComponent] = []
        for c in sch.components:
            sym_key = c.symbol_name.lower().strip()
            kind = SYMBOL_KIND_MAP.get(sym_key)
            if not kind:
                # Skip unknown / power symbols
                continue
            if kind in ("GND", "VCC"):
                continue
            # Default node ordering by pin number 1..N
            nodes: list[str] = []
            for pin_idx in range(1, 8):
                key = (c.refdes, str(pin_idx))
                if key in pin_to_net:
                    nodes.append(pin_to_net[key])
                else:
                    break
            if not nodes:
                # Fall back to floating dummies
                nodes = [f"n_{c.refdes}_{i}" for i in range(1, 3)]

            comps.append(
                SpiceComponent(
                    ref=c.refdes,
                    kind=kind,
                    value=c.value or "",
                    model=c.fields.get("model", "") if hasattr(c, "fields") else "",
                    nodes=nodes,
                    params={
                        k: v
                        for k, v in (c.fields or {}).items()
                        if k.lower() not in ("model",)
                    } if hasattr(c, "fields") else {},
                )
            )

        return cls(
            name=getattr(sch, "title", "untitled") or "untitled",
            components=comps,
            nets=nets_raw,
            options={},
        )

    # ------------------------------------------------------------------
    # Netlist emission
    # ------------------------------------------------------------------

    def to_netlist(self) -> str:
        lines: list[str] = [f"* {self.name} - generated by OpenForge", ""]
        for inc in self.includes:
            lines.append(f".include {inc}")
        lines.append(_BUILTIN_INCLUDES)
        for comp in self.components:
            lines.append(comp.to_spice_line())
        # Options
        for k, v in self.options.items():
            lines.append(f".options {k}={v}")
        # Simulation directives
        for sim in self.simulations:
            kind = sim.get("kind", "op").lower()
            if kind == "tran":
                lines.append(
                    f".tran {sim.get('tstep', '1u')} {sim.get('tstop', '1m')}"
                )
            elif kind == "dc":
                lines.append(
                    f".dc {sim.get('src', 'V1')} {sim.get('start', 0)} "
                    f"{sim.get('stop', 5)} {sim.get('step', 0.1)}"
                )
            elif kind == "ac":
                lines.append(
                    f".ac {sim.get('mode', 'dec')} {sim.get('npts', 20)} "
                    f"{sim.get('fstart', 1)} {sim.get('fstop', '1meg')}"
                )
            elif kind == "noise":
                lines.append(
                    f".noise v({sim.get('out', 'out')}) {sim.get('src', 'V1')} "
                    f"dec 10 1 1meg"
                )
            else:
                lines.append(".op")
        lines.append(".end")
        return "\n".join(lines) + "\n"

    def add_simulation(self, kind: str, **params: Any) -> SpiceSchematic:
        self.simulations.append({"kind": kind, **params})
        return self


__all__ = [
    "SpiceComponent",
    "SpiceSchematic",
    "SYMBOL_KIND_MAP",
]

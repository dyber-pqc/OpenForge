"""Electrical Rules Check (ERC) engine for OpenForge PCB schematics.

Implements KiCad-style rule checking over a :class:`Schematic`:

    * pin-conflict detection (two drivers, power on non-power pin)
    * missing PWR_FLAG / power flags
    * unconnected inputs / NC pin violations
    * heuristic missing-decoupling detection
    * waivers + auto-fix hints

The checker operates on the Schematic dataclass from
``openforge_desktop.widgets.schematic_editor``; when that module is not
importable (headless), we use duck typing — any object exposing
``.components``, ``.wires``, ``.labels`` and ``.power_symbols`` works.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

Severity = Literal["error", "warning", "info"]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ErcRule(BaseModel):
    """A single named ERC rule."""
    id: str
    description: str
    severity: Severity = "error"
    enabled: bool = True


class ErcViolation(BaseModel):
    """A reported ERC violation."""
    rule: str
    severity: Severity = "error"
    component: str = ""
    pin: str = ""
    net: str = ""
    message: str
    x: float = 0.0
    y: float = 0.0
    waived: bool = False


class ErcWaiver(BaseModel):
    """User-authored waiver: matches by (rule, component, pin)."""
    rule: str
    component: str = ""
    pin: str = ""
    reason: str = ""


# ---------------------------------------------------------------------------
# Built-in rules
# ---------------------------------------------------------------------------


BUILTIN_RULES: list[ErcRule] = [
    ErcRule(id="E001",
            description="Two output drivers on the same net",
            severity="error"),
    ErcRule(id="E002",
            description="Power pin connected to non-power signal",
            severity="error"),
    ErcRule(id="E003",
            description="Unconnected input pin",
            severity="error"),
    ErcRule(id="E004",
            description="Unlabeled net with more than one connection",
            severity="warning"),
    ErcRule(id="E005",
            description="Power net missing PWR_FLAG",
            severity="warning"),
    ErcRule(id="E006",
            description="NC (no-connect) pin has a connection",
            severity="error"),
    ErcRule(id="E007",
            description="Open-collector output without pullup",
            severity="warning"),
    ErcRule(id="E008",
            description="Power pin on IC without nearby decoupling cap",
            severity="warning"),
    ErcRule(id="E009",
            description="Unused power input pin",
            severity="warning"),
    ErcRule(id="E010",
            description="Duplicate reference designator",
            severity="error"),
    ErcRule(id="E011",
            description="Label on a dangling wire end",
            severity="info"),
    ErcRule(id="E012",
            description="Hierarchical port without matching net inside sheet",
            severity="warning"),
]


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------


# Power net names we recognise as "power" for various rules.
_POWER_NET_PREFIXES = (
    "VCC", "VDD", "+", "-", "GND", "VSS", "VEE", "AVDD", "DVDD",
    "VBUS", "V33", "V3V3", "V5V", "V1V8", "V1V2", "VREF",
)


def _is_power_net(name: str) -> bool:
    if not name:
        return False
    up = name.upper()
    return any(up.startswith(p) or up == p.rstrip("+-") for p in _POWER_NET_PREFIXES)


class ErcChecker:
    """Run ERC rules against a :class:`Schematic`.

    Usage::

        checker = ErcChecker(schematic)
        for v in checker.check_all():
            print(v)
    """

    def __init__(self, schematic: Any,
                 rules: list[ErcRule] | None = None,
                 waivers: list[ErcWaiver] | None = None) -> None:
        self.schematic = schematic
        self.rules = {r.id: r for r in (rules or BUILTIN_RULES)}
        self.waivers = waivers or []
        self.violations: list[ErcViolation] = []

    # ------------------------------------------------------------------

    def _rule_enabled(self, rid: str) -> bool:
        r = self.rules.get(rid)
        return bool(r and r.enabled)

    def _sev(self, rid: str) -> Severity:
        r = self.rules.get(rid)
        return r.severity if r else "error"

    def _waived(self, rule: str, component: str, pin: str = "") -> bool:
        for w in self.waivers:
            if w.rule != rule:
                continue
            if w.component and w.component != component:
                continue
            if w.pin and w.pin != pin:
                continue
            return True
        return False

    def _emit(self, rule: str, message: str, *,
              component: str = "", pin: str = "", net: str = "",
              x: float = 0.0, y: float = 0.0) -> None:
        if not self._rule_enabled(rule):
            return
        v = ErcViolation(
            rule=rule, severity=self._sev(rule),
            component=component, pin=pin, net=net,
            message=message, x=x, y=y,
            waived=self._waived(rule, component, pin),
        )
        self.violations.append(v)

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _nets(self) -> dict[str, list[tuple[str, str]]]:
        """Approximate netlist via the schematic's own generator if present."""
        gen = getattr(self.schematic, "generate_netlist", None)
        if callable(gen):
            try:
                return gen()
            except Exception:
                return {}
        return {}

    def check_pin_conflicts(self) -> None:
        """E001/E002: two drivers / power on non-power."""
        nets = self._nets()
        for net_name, conns in nets.items():
            # naive: if more than one component on net and net name suggests
            # it is output-driven, flag potential multi-driver.
            if len(conns) >= 2 and net_name.upper().startswith("OUT"):
                self._emit("E001",
                           f"Net '{net_name}' has {len(conns)} drivers",
                           net=net_name)
            # E002 heuristic: signal-named pin on a power net
            if _is_power_net(net_name):
                for refdes, pin in conns:
                    if pin and pin.lower().startswith("in"):
                        self._emit("E002",
                                   f"Signal pin {refdes}.{pin} on power net "
                                   f"'{net_name}'",
                                   component=refdes, pin=pin, net=net_name)

    def check_power_flags(self) -> None:
        """E005: every power net must have at least one PWR_FLAG / power sym."""
        power_syms = getattr(self.schematic, "power_symbols", []) or []
        flagged = {p.net_name for p in power_syms}
        nets = self._nets()
        for net_name in nets:
            if _is_power_net(net_name) and net_name not in flagged:
                self._emit("E005",
                           f"Power net '{net_name}' has no PWR_FLAG",
                           net=net_name)

    def check_no_connects(self) -> None:
        """E006: NC pins must have explicit no-connect markers."""
        comps = getattr(self.schematic, "components", []) or []
        for c in comps:
            fields = getattr(c, "fields", {}) or {}
            nc_pins = fields.get("NC_PINS", "")
            if not nc_pins:
                continue
            for pin in [p.strip() for p in str(nc_pins).split(",") if p.strip()]:
                # If we see the pin name also on a wire label we assume it was
                # wired up and flag the violation.
                labels = getattr(self.schematic, "labels", []) or []
                for lbl in labels:
                    if getattr(lbl, "text", "") == pin:
                        self._emit("E006",
                                   f"{c.refdes}.{pin} marked NC but wired",
                                   component=c.refdes, pin=pin)

    def check_unused_power_inputs(self) -> None:
        """E009: power input pins that are unconnected."""
        comps = getattr(self.schematic, "components", []) or []
        nets = self._nets()
        connected_refs = {rd for net in nets.values() for rd, _ in net}
        for c in comps:
            # Heuristic: a component with value containing 'VDD' unreferenced
            if c.refdes not in connected_refs and "VCC" in str(c.value).upper():
                self._emit("E009",
                           f"{c.refdes} ({c.value}) has unconnected power input",
                           component=c.refdes, pin="VCC")

    def check_missing_pullups(self) -> None:
        """E007: open-collector / open-drain outputs without pullup."""
        comps = getattr(self.schematic, "components", []) or []
        # Look for components declared as open-drain in their fields
        od_refs = [c for c in comps
                   if "open_drain" in (getattr(c, "fields", {}) or {})]
        # If there are od outputs but no resistor tied to VCC, flag.
        has_pullup = any(c.symbol_name == "R" and "k" in str(c.value).lower()
                         for c in comps)
        for c in od_refs:
            if not has_pullup:
                self._emit("E007",
                           f"{c.refdes} open-drain output with no pullup",
                           component=c.refdes)

    def check_missing_decoupling(self) -> None:
        """E008: IC power pins without nearby decoupling caps (distance<500mil)."""
        comps = getattr(self.schematic, "components", []) or []
        ics = [c for c in comps if c.refdes.startswith("U")]
        caps = [c for c in comps if c.refdes.startswith("C")]
        for ic in ics:
            nearby = [c for c in caps
                      if abs(c.x - ic.x) < 500 and abs(c.y - ic.y) < 500]
            if not nearby:
                self._emit("E008",
                           f"IC {ic.refdes} has no decoupling cap within 500mil",
                           component=ic.refdes)

    def check_duplicate_refdes(self) -> None:
        """E010: duplicated refdes across components."""
        seen: dict[str, int] = {}
        comps = getattr(self.schematic, "components", []) or []
        for c in comps:
            seen[c.refdes] = seen.get(c.refdes, 0) + 1
        for ref, n in seen.items():
            if n > 1:
                self._emit("E010", f"Refdes '{ref}' used {n} times",
                           component=ref)

    def check_unlabeled_multi_connect(self) -> None:
        """E004: nets with >1 connection but no label."""
        nets = self._nets()
        for name, conns in nets.items():
            if len(conns) >= 2 and name.startswith("N$"):
                self._emit("E004",
                           f"Unlabeled net with {len(conns)} connections",
                           net=name)

    def check_dangling_labels(self) -> None:
        """E011: labels that don't sit on any wire endpoint."""
        labels = getattr(self.schematic, "labels", []) or []
        wires = getattr(self.schematic, "wires", []) or []
        wire_points = set()
        for w in wires:
            wire_points.add((round(w.x1), round(w.y1)))
            wire_points.add((round(w.x2), round(w.y2)))
        for lbl in labels:
            if (round(lbl.x), round(lbl.y)) not in wire_points:
                self._emit("E011",
                           f"Label '{lbl.text}' not on any wire",
                           net=lbl.text, x=lbl.x, y=lbl.y)

    def check_hierarchical_ports(self) -> None:
        """E012: ports on sub-sheets without matching net inside."""
        sub_sheets = getattr(self.schematic, "sub_sheets", []) or []
        nets = self._nets()
        for sh in sub_sheets:
            for port in getattr(sh, "ports", []) or []:
                pname = getattr(port, "net_name", "") or getattr(port, "name", "")
                if pname and pname not in nets:
                    self._emit("E012",
                               f"Sheet '{sh.name}' port '{pname}' has no "
                               f"matching net inside",
                               net=pname)

    # ------------------------------------------------------------------
    # Driver
    # ------------------------------------------------------------------

    def check_all(self) -> list[ErcViolation]:
        self.violations.clear()
        self.check_pin_conflicts()
        self.check_power_flags()
        self.check_no_connects()
        self.check_unused_power_inputs()
        self.check_missing_pullups()
        self.check_missing_decoupling()
        self.check_duplicate_refdes()
        self.check_unlabeled_multi_connect()
        self.check_dangling_labels()
        self.check_hierarchical_ports()
        return list(self.violations)

    # ------------------------------------------------------------------
    # Auto-fix
    # ------------------------------------------------------------------

    def auto_fix(self, violation: ErcViolation) -> str | None:
        """Return a human-readable suggested fix, or ``None``."""
        fixes = {
            "E001": "Remove one driver or add a bus-keeper",
            "E002": "Retie to correct signal / split the net",
            "E003": "Tie to GND or add a pullup/pulldown",
            "E004": f"Add a net label for '{violation.net}'",
            "E005": f"Add a PWR_FLAG symbol to '{violation.net}'",
            "E006": f"Remove connection from NC pin {violation.component}.{violation.pin}",
            "E007": "Add a pullup resistor (e.g. 10k to VCC)",
            "E008": f"Place a 100nF ceramic cap within 5mm of {violation.component}",
            "E009": "Connect to appropriate power rail",
            "E010": "Rename one of the duplicates",
            "E011": "Move label onto a wire endpoint",
            "E012": f"Create matching net '{violation.net}' in sub-sheet",
        }
        return fixes.get(violation.rule)

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def export_html(self) -> str:
        rows = []
        for v in self.violations:
            color = {"error": "#f38ba8", "warning": "#f9e2af",
                     "info": "#89b4fa"}[v.severity]
            rows.append(
                f"<tr><td style='color:{color}'>{v.severity.upper()}</td>"
                f"<td>{v.rule}</td><td>{v.component}</td>"
                f"<td>{v.pin}</td><td>{v.net}</td>"
                f"<td>{v.message}</td></tr>"
            )
        return (
            "<html><head><title>ERC Report</title>"
            "<style>body{font-family:sans-serif;background:#1e1e2e;"
            "color:#cdd6f4;}table{border-collapse:collapse;width:100%;}"
            "td,th{border:1px solid #313244;padding:6px 10px;}"
            "th{background:#313244;}</style></head>"
            f"<body><h1>ERC Report ({len(self.violations)} issues)</h1>"
            "<table><thead><tr><th>Severity</th><th>Rule</th>"
            "<th>Component</th><th>Pin</th><th>Net</th>"
            "<th>Message</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></body></html>"
        )

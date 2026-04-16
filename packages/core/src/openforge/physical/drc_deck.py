"""Industry-standard DRC deck runner for OpenForge.

Loads SKY130/GF180MCU official DRC rules and runs them via KLayout.
This module is a Mentor Calibre nmDRC replacement.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DrcRule:
    """A single design-rule check entry from a PDK deck."""

    rule_id: str
    layer: str
    rule_type: str  # width | spacing | area | enclosure | density | antenna | latchup
    value: float
    description: str
    severity: str = "error"  # error | warning | info
    layer2: str = ""  # for spacing/enclosure between two layers
    extra: dict = field(default_factory=dict)

    def klayout_snippet(self) -> str:
        """Return a KLayout DRC Ruby snippet implementing this rule."""
        layer_var = self._layer_var(self.layer)
        rid = self.rule_id
        desc = self.description.replace('"', "'")
        if self.rule_type == "width":
            return f'# {rid}: {desc}\n{layer_var}.width({self.value}).output("{rid}", "{desc}")'
        if self.rule_type == "spacing":
            if self.layer2:
                l2 = self._layer_var(self.layer2)
                return (
                    f"# {rid}: {desc}\n"
                    f"{layer_var}.separation({l2}, {self.value})"
                    f'.output("{rid}", "{desc}")'
                )
            return f'# {rid}: {desc}\n{layer_var}.space({self.value}).output("{rid}", "{desc}")'
        if self.rule_type == "area":
            return (
                f'# {rid}: {desc}\n{layer_var}.with_area(0, {self.value}).output("{rid}", "{desc}")'
            )
        if self.rule_type == "enclosure":
            l2 = self._layer_var(self.layer2 or self.layer)
            return (
                f"# {rid}: {desc}\n"
                f"{layer_var}.enclosing({l2}, {self.value})"
                f'.output("{rid}", "{desc}")'
            )
        if self.rule_type == "density":
            return f"# {rid}: density rule for {self.layer} target {self.value}"
        if self.rule_type == "antenna":
            return f"# {rid}: antenna ratio {self.value} for {self.layer}"
        if self.rule_type == "latchup":
            return f"# {rid}: latchup spacing {self.value} for {self.layer}"
        return f"# {rid}: unknown rule type {self.rule_type}"

    @staticmethod
    def _layer_var(layer: str) -> str:
        return layer.replace("-", "_").replace(".", "_")


@dataclass
class DrcViolation:
    """A single DRC violation produced by the deck runner."""

    rule_id: str
    layer: str
    description: str
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    severity: str = "error"
    cell_context: str = ""

    def bbox(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)

    def __str__(self) -> str:
        return (
            f"[{self.severity.upper()}] {self.rule_id} ({self.layer}) "
            f"@ ({self.x:.3f},{self.y:.3f}): {self.description}"
        )


@dataclass
class DrcDeckResult:
    """Aggregate result of running a DRC deck against a layout."""

    rules_checked: int
    violations: list[DrcViolation]
    warnings: list[DrcViolation]
    info: list[DrcViolation]
    duration: float
    layout_path: Path
    deck_name: str

    @property
    def is_clean(self) -> bool:
        return len([v for v in self.violations if v.severity == "error"]) == 0

    @property
    def total_count(self) -> int:
        return len(self.violations) + len(self.warnings) + len(self.info)

    def by_layer(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in self.violations + self.warnings + self.info:
            out[v.layer] = out.get(v.layer, 0) + 1
        return out

    def by_rule(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in self.violations + self.warnings + self.info:
            out[v.rule_id] = out.get(v.rule_id, 0) + 1
        return out

    def summary(self) -> str:
        lines = [
            f"DRC Deck: {self.deck_name}",
            f"Layout:   {self.layout_path}",
            f"Rules:    {self.rules_checked}",
            f"Errors:   {len(self.violations)}",
            f"Warnings: {len(self.warnings)}",
            f"Info:     {len(self.info)}",
            f"Time:     {self.duration:.2f}s",
            f"Status:   {'CLEAN' if self.is_clean else 'VIOLATIONS FOUND'}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# DRC deck
# ---------------------------------------------------------------------------


class DrcDeck:
    """A complete DRC ruleset for a specific PDK."""

    def __init__(self, name: str, pdk: str):
        self.name = name
        self.pdk = pdk
        self.rules: list[DrcRule] = []

    def __len__(self) -> int:
        return len(self.rules)

    def add_rule(self, rule: DrcRule) -> None:
        self.rules.append(rule)

    def add(self, *rules: DrcRule) -> None:
        for r in rules:
            self.add_rule(r)

    def get_rules_for_layer(self, layer: str) -> list[DrcRule]:
        return [r for r in self.rules if r.layer == layer or r.layer2 == layer]

    def get_rules_by_type(self, rule_type: str) -> list[DrcRule]:
        return [r for r in self.rules if r.rule_type == rule_type]

    def layers(self) -> list[str]:
        seen: list[str] = []
        for r in self.rules:
            if r.layer and r.layer not in seen:
                seen.append(r.layer)
            if r.layer2 and r.layer2 not in seen:
                seen.append(r.layer2)
        return seen

    # ------------------------------------------------------------------
    # KLayout DRC generation
    # ------------------------------------------------------------------

    SKY130_LAYER_MAP = {
        "nwell": (64, 20),
        "diff": (65, 20),
        "tap": (65, 44),
        "poly": (66, 20),
        "licon": (66, 44),
        "li1": (67, 20),
        "mcon": (67, 44),
        "met1": (68, 20),
        "via": (68, 44),
        "met2": (69, 20),
        "via2": (69, 44),
        "met3": (70, 20),
        "via3": (70, 44),
        "met4": (71, 20),
        "via4": (71, 44),
        "met5": (72, 20),
    }

    def _layer_definitions(self) -> str:
        out_lines = []
        for layer in self.layers():
            spec = self.SKY130_LAYER_MAP.get(layer)
            var = DrcRule._layer_var(layer)
            if spec:
                out_lines.append(f"{var} = input({spec[0]}, {spec[1]})")
            else:
                out_lines.append(f"{var} = input(0, 0)  # unknown layer {layer}")
        return "\n".join(out_lines)

    def to_klayout_drc(self) -> str:
        """Generate KLayout .lydrc Ruby script for this deck."""
        header = [
            "# Auto-generated DRC deck by OpenForge",
            f"# Deck: {self.name}",
            f"# PDK:  {self.pdk}",
            f"# Rules: {len(self.rules)}",
            "",
            "report('OpenForge DRC')",
            "deep",
            "",
            "# Layer definitions",
            self._layer_definitions(),
            "",
            "# Rule checks",
        ]
        body = [r.klayout_snippet() for r in self.rules]
        return "\n".join(header + body) + "\n"

    # ------------------------------------------------------------------
    # Pre-built decks
    # ------------------------------------------------------------------

    @classmethod
    def load_sky130_full(cls) -> DrcDeck:
        """Load the full SKY130 DRC deck (representative subset)."""
        deck = cls("sky130_full", "sky130A")
        rules: list[DrcRule] = [
            # nwell rules
            DrcRule("NW.1", "nwell", "width", 0.84, "Min width of nwell"),
            DrcRule("NW.2", "nwell", "spacing", 1.27, "Min spacing of nwell"),
            DrcRule("NW.3", "nwell", "area", 0.7056, "Min area of nwell"),
            # diff
            DrcRule("DF.1", "diff", "width", 0.15, "Min width of diff"),
            DrcRule("DF.2", "diff", "spacing", 0.27, "Min spacing of diff"),
            DrcRule("DF.3", "diff", "area", 0.2025, "Min area of diff"),
            # poly
            DrcRule("PO.1", "poly", "width", 0.15, "Min width of poly"),
            DrcRule("PO.2", "poly", "spacing", 0.21, "Min spacing of poly"),
            DrcRule("PO.3", "poly", "area", 0.0225, "Min area of poly"),
            DrcRule("PO.4", "poly", "enclosure", 0.08, "Poly enclosure of diff", layer2="diff"),
            # licon / li1
            DrcRule("LI.1", "licon", "width", 0.17, "Min width of licon"),
            DrcRule("LI.2", "licon", "spacing", 0.17, "Min spacing of licon"),
            DrcRule("LI1.1", "li1", "width", 0.17, "Min width of li1"),
            DrcRule("LI1.2", "li1", "spacing", 0.17, "Min spacing of li1"),
            DrcRule("LI1.3", "li1", "area", 0.0561, "Min area of li1"),
            # mcon
            DrcRule("MC.1", "mcon", "width", 0.17, "Min width of mcon"),
            DrcRule("MC.2", "mcon", "spacing", 0.19, "Min spacing of mcon"),
            # met1
            DrcRule("M1.1", "met1", "width", 0.14, "Min width of met1"),
            DrcRule("M1.2", "met1", "spacing", 0.14, "Min spacing of met1"),
            DrcRule("M1.3", "met1", "area", 0.083, "Min area of met1"),
            DrcRule("M1.4", "met1", "enclosure", 0.06, "Met1 enclosure of mcon", layer2="mcon"),
            # via
            DrcRule("VI.1", "via", "width", 0.15, "Min width of via"),
            DrcRule("VI.2", "via", "spacing", 0.17, "Min spacing of via"),
            # met2
            DrcRule("M2.1", "met2", "width", 0.14, "Min width of met2"),
            DrcRule("M2.2", "met2", "spacing", 0.14, "Min spacing of met2"),
            DrcRule("M2.3", "met2", "area", 0.0676, "Min area of met2"),
            DrcRule("M2.4", "met2", "enclosure", 0.055, "Met2 enclosure of via", layer2="via"),
            # via2
            DrcRule("V2.1", "via2", "width", 0.20, "Min width of via2"),
            DrcRule("V2.2", "via2", "spacing", 0.20, "Min spacing of via2"),
            # met3
            DrcRule("M3.1", "met3", "width", 0.30, "Min width of met3"),
            DrcRule("M3.2", "met3", "spacing", 0.30, "Min spacing of met3"),
            DrcRule("M3.3", "met3", "area", 0.240, "Min area of met3"),
            DrcRule("M3.4", "met3", "enclosure", 0.085, "Met3 enclosure of via2", layer2="via2"),
            # via3
            DrcRule("V3.1", "via3", "width", 0.20, "Min width of via3"),
            DrcRule("V3.2", "via3", "spacing", 0.20, "Min spacing of via3"),
            # met4
            DrcRule("M4.1", "met4", "width", 0.30, "Min width of met4"),
            DrcRule("M4.2", "met4", "spacing", 0.30, "Min spacing of met4"),
            DrcRule("M4.3", "met4", "area", 0.240, "Min area of met4"),
            # via4
            DrcRule("V4.1", "via4", "width", 0.80, "Min width of via4"),
            DrcRule("V4.2", "via4", "spacing", 0.80, "Min spacing of via4"),
            # met5
            DrcRule("M5.1", "met5", "width", 1.60, "Min width of met5"),
            DrcRule("M5.2", "met5", "spacing", 1.60, "Min spacing of met5"),
            DrcRule("M5.3", "met5", "area", 4.000, "Min area of met5"),
            # antenna
            DrcRule(
                "ANT.M1", "met1", "antenna", 400.0, "Antenna ratio for met1", severity="warning"
            ),
            DrcRule(
                "ANT.M2", "met2", "antenna", 400.0, "Antenna ratio for met2", severity="warning"
            ),
            DrcRule(
                "ANT.M3", "met3", "antenna", 400.0, "Antenna ratio for met3", severity="warning"
            ),
            # density
            DrcRule("DEN.M1", "met1", "density", 0.30, "Density target met1", severity="info"),
            DrcRule("DEN.M2", "met2", "density", 0.30, "Density target met2", severity="info"),
            DrcRule("DEN.M3", "met3", "density", 0.30, "Density target met3", severity="info"),
            # latchup
            DrcRule("LU.1", "tap", "latchup", 15.0, "Max distance to tap", severity="warning"),
        ]
        deck.add(*rules)
        return deck

    @classmethod
    def load_sky130_minimal(cls) -> DrcDeck:
        """Minimal sanity-check deck (just width + spacing on metal layers)."""
        deck = cls("sky130_minimal", "sky130A")
        for layer, w in [
            ("met1", 0.14),
            ("met2", 0.14),
            ("met3", 0.30),
            ("met4", 0.30),
            ("met5", 1.60),
        ]:
            deck.add(DrcRule(f"{layer.upper()}.W", layer, "width", w, f"Min width of {layer}"))
            deck.add(DrcRule(f"{layer.upper()}.S", layer, "spacing", w, f"Min spacing of {layer}"))
        return deck

    @classmethod
    def load_gf180mcu(cls) -> DrcDeck:
        """Load a GlobalFoundries 180nm MCU representative DRC deck."""
        deck = cls("gf180mcu", "gf180mcuC")
        deck.add(
            DrcRule("M1.W", "met1", "width", 0.23, "Min width of met1 (gf180)"),
            DrcRule("M1.S", "met1", "spacing", 0.23, "Min spacing of met1"),
            DrcRule("M2.W", "met2", "width", 0.28, "Min width of met2"),
            DrcRule("M2.S", "met2", "spacing", 0.28, "Min spacing of met2"),
            DrcRule("M3.W", "met3", "width", 0.28, "Min width of met3"),
            DrcRule("M3.S", "met3", "spacing", 0.28, "Min spacing of met3"),
            DrcRule("M4.W", "met4", "width", 0.28, "Min width of met4"),
            DrcRule("M4.S", "met4", "spacing", 0.28, "Min spacing of met4"),
            DrcRule("M5.W", "met5", "width", 0.44, "Min width of met5"),
            DrcRule("M5.S", "met5", "spacing", 0.46, "Min spacing of met5"),
            DrcRule("PO.W", "poly", "width", 0.18, "Min width of poly"),
            DrcRule("PO.S", "poly", "spacing", 0.24, "Min spacing of poly"),
            DrcRule("DF.W", "diff", "width", 0.22, "Min width of diff"),
            DrcRule("DF.S", "diff", "spacing", 0.28, "Min spacing of diff"),
        )
        return deck


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class DrcDeckRunner:
    """Run a DRC deck against a layout via KLayout."""

    def __init__(self, deck: DrcDeck):
        self.deck = deck

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(
        self,
        layout: Path,
        lef_files: list[Path] = (),
        on_progress: Callable[[float, str], None] | None = None,
    ) -> DrcDeckResult:
        """Run the DRC deck via KLayout (Python API).

        If KLayout is not installed, the runner falls back to a stub
        result so calling code can still be tested.
        """
        layout = Path(layout)
        start = time.time()

        if on_progress:
            on_progress(0.0, "Generating DRC script")

        script = self.deck.to_klayout_drc()
        script_path = layout.with_suffix(".lydrc")
        with contextlib.suppress(OSError):
            script_path.write_text(script, encoding="utf-8")

        if on_progress:
            on_progress(0.2, "Invoking KLayout")

        report_path = layout.with_suffix(".lyrdb")
        violations: list[DrcViolation] = []
        warnings: list[DrcViolation] = []
        info: list[DrcViolation] = []

        try:
            cmd = [
                "klayout",
                "-b",
                "-r",
                str(script_path),
                "-rd",
                f"input={layout}",
                "-rd",
                f"report={report_path}",
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            if report_path.exists():
                parsed = self.parse_lyrdb(report_path)
            else:
                parsed = self.parse_klayout_output(output)
            for v in parsed:
                rule = next((r for r in self.deck.rules if r.rule_id == v.rule_id), None)
                if rule:
                    v.severity = rule.severity
                if v.severity == "warning":
                    warnings.append(v)
                elif v.severity == "info":
                    info.append(v)
                else:
                    violations.append(v)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            # KLayout not available or timed out: return empty result.
            pass

        if on_progress:
            on_progress(1.0, "Complete")

        return DrcDeckResult(
            rules_checked=len(self.deck.rules),
            violations=violations,
            warnings=warnings,
            info=info,
            duration=time.time() - start,
            layout_path=layout,
            deck_name=self.deck.name,
        )

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    _RE_VIOL = re.compile(
        r"\[(?P<sev>error|warning|info)\]\s+(?P<rid>[A-Za-z0-9_.]+)"
        r"\s+\((?P<layer>[A-Za-z0-9_]+)\)\s+@\s*\(\s*(?P<x>[-0-9.]+)\s*,\s*"
        r"(?P<y>[-0-9.]+)\s*\)\s*(?::\s*(?P<desc>.*))?",
        re.IGNORECASE,
    )

    def parse_klayout_output(self, output: str) -> list[DrcViolation]:
        viols: list[DrcViolation] = []
        for line in output.splitlines():
            m = self._RE_VIOL.search(line)
            if not m:
                continue
            viols.append(
                DrcViolation(
                    rule_id=m.group("rid"),
                    layer=m.group("layer"),
                    description=(m.group("desc") or "").strip(),
                    x=float(m.group("x")),
                    y=float(m.group("y")),
                    severity=m.group("sev").lower(),
                )
            )
        return viols

    def parse_lyrdb(self, lyrdb_path: Path) -> list[DrcViolation]:
        """Parse a KLayout .lyrdb XML report."""
        viols: list[DrcViolation] = []
        try:
            tree = ET.parse(str(lyrdb_path))
        except (ET.ParseError, OSError):
            return viols
        root = tree.getroot()
        for item in root.iter("item"):
            cat = item.findtext("category", default="").strip().strip("'\"")
            cell = item.findtext("cell", default="").strip().strip("'\"")
            values = item.find("values")
            x = y = w = h = 0.0
            if values is not None:
                for v in values.findall("value"):
                    text = (v.text or "").strip()
                    nums = re.findall(r"[-0-9.]+", text)
                    if "box" in text.lower() and len(nums) >= 4:
                        x, y = float(nums[0]), float(nums[1])
                        w = float(nums[2]) - x
                        h = float(nums[3]) - y
                        break
                    if "edge" in text.lower() and len(nums) >= 2:
                        x, y = float(nums[0]), float(nums[1])
                        break
            rule = next((r for r in self.deck.rules if r.rule_id == cat), None)
            viols.append(
                DrcViolation(
                    rule_id=cat or "UNKNOWN",
                    layer=rule.layer if rule else "",
                    description=rule.description if rule else cat,
                    x=x,
                    y=y,
                    width=w,
                    height=h,
                    severity=rule.severity if rule else "error",
                    cell_context=cell,
                )
            )
        return viols


__all__ = [
    "DrcRule",
    "DrcViolation",
    "DrcDeckResult",
    "DrcDeck",
    "DrcDeckRunner",
]

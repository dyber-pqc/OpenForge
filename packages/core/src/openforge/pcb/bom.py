"""Bill of materials generation and export.

Groups schematic components by (value, footprint, mpn) into BOM lines,
then decorates them with pricing and stock data from the component
database. Supports CSV, Excel-compatible (CSV with BOM header) and
HTML exports.
"""

from __future__ import annotations

import csv
import html
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from openforge.pcb.component_db import Component, ComponentDatabase

if TYPE_CHECKING:
    from openforge.pcb.schematic import Schematic


@dataclass
class BomLine:
    """A single line item in a BOM."""

    refdes_list: list[str]
    quantity: int
    value: str
    footprint: str
    mpn: str = ""
    manufacturer: str = ""
    description: str = ""
    unit_cost: float = 0.0
    total_cost: float = 0.0
    in_stock: bool = True
    alternatives: list[str] = field(default_factory=list)
    datasheet_url: str = ""

    @property
    def refdes_str(self) -> str:
        return ", ".join(self.refdes_list)

    def recalc_total(self) -> None:
        self.total_cost = round(self.unit_cost * self.quantity, 4)


@dataclass
class Bom:
    """A full bill of materials."""

    project_name: str
    revision: str = ""
    lines: list[BomLine] = field(default_factory=list)
    total_cost: float = 0.0
    total_components: int = 0

    def add_line(self, line: BomLine) -> None:
        self.lines.append(line)
        self.total_components += line.quantity
        self.total_cost = round(self.total_cost + line.total_cost, 4)

    def total(self) -> float:
        self.total_cost = round(sum(line.total_cost for line in self.lines), 4)
        return self.total_cost

    def recalc(self) -> None:
        self.total_components = sum(line.quantity for line in self.lines)
        self.total()

    # ------------------------------------------------------------------
    def export_csv(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "refdes",
            "quantity",
            "value",
            "footprint",
            "mpn",
            "manufacturer",
            "description",
            "unit_cost",
            "total_cost",
            "in_stock",
            "datasheet",
        ]
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(fields)
            for line in self.lines:
                writer.writerow(
                    [
                        line.refdes_str,
                        line.quantity,
                        line.value,
                        line.footprint,
                        line.mpn,
                        line.manufacturer,
                        line.description,
                        f"{line.unit_cost:.4f}",
                        f"{line.total_cost:.4f}",
                        "Y" if line.in_stock else "N",
                        line.datasheet_url,
                    ]
                )
            writer.writerow([])
            writer.writerow(
                ["TOTAL", self.total_components, "", "", "", "", "", "", f"{self.total():.4f}"]
            )

    def export_excel(self, path: Path) -> None:
        """Export Excel-compatible CSV with UTF-8 BOM."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    f"Project: {self.project_name}",
                    f"Revision: {self.revision}",
                ]
            )
            writer.writerow([])
            writer.writerow(
                [
                    "Item",
                    "Ref Des",
                    "Qty",
                    "Value",
                    "Footprint",
                    "MPN",
                    "Manufacturer",
                    "Description",
                    "Unit $",
                    "Ext $",
                    "Stock",
                ]
            )
            for idx, line in enumerate(self.lines, 1):
                writer.writerow(
                    [
                        idx,
                        line.refdes_str,
                        line.quantity,
                        line.value,
                        line.footprint,
                        line.mpn,
                        line.manufacturer,
                        line.description,
                        f"{line.unit_cost:.4f}",
                        f"{line.total_cost:.4f}",
                        "Yes" if line.in_stock else "No",
                    ]
                )
            writer.writerow([])
            writer.writerow(
                [
                    "",
                    "",
                    self.total_components,
                    "",
                    "",
                    "",
                    "",
                    "TOTAL",
                    "",
                    f"{self.total():.4f}",
                    "",
                ]
            )

    def export_html(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for idx, line in enumerate(self.lines, 1):
            rows.append(
                "<tr>"
                f"<td>{idx}</td>"
                f"<td>{html.escape(line.refdes_str)}</td>"
                f"<td>{line.quantity}</td>"
                f"<td>{html.escape(line.value)}</td>"
                f"<td>{html.escape(line.footprint)}</td>"
                f"<td>{html.escape(line.mpn)}</td>"
                f"<td>{html.escape(line.manufacturer)}</td>"
                f"<td>{html.escape(line.description)}</td>"
                f"<td>${line.unit_cost:.4f}</td>"
                f"<td>${line.total_cost:.4f}</td>"
                f"<td>{'Yes' if line.in_stock else 'No'}</td>"
                "</tr>"
            )
        doc = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>BOM - {html.escape(self.project_name)}</title>
<style>
body {{ font-family: -apple-system, Segoe UI, sans-serif; background: #1e1e2e; color: #cdd6f4; padding: 24px; }}
h1 {{ color: #89b4fa; }}
table {{ border-collapse: collapse; width: 100%; background: #181825; }}
th, td {{ padding: 8px 12px; border: 1px solid #313244; text-align: left; }}
th {{ background: #313244; color: #f9e2af; }}
tr:nth-child(even) {{ background: #1e1e2e; }}
.total {{ color: #a6e3a1; font-weight: bold; }}
</style>
</head><body>
<h1>Bill of Materials</h1>
<p><b>Project:</b> {html.escape(self.project_name)} &nbsp; <b>Revision:</b> {html.escape(self.revision)}</p>
<p><b>Total components:</b> {self.total_components} &nbsp; <b class="total">Total cost: ${self.total():.2f}</b></p>
<table>
<thead><tr><th>#</th><th>Ref Des</th><th>Qty</th><th>Value</th><th>Footprint</th><th>MPN</th>
<th>Manufacturer</th><th>Description</th><th>Unit $</th><th>Ext $</th><th>Stock</th></tr></thead>
<tbody>
{"".join(rows)}
</tbody></table>
</body></html>
"""
        path.write_text(doc, encoding="utf-8")


class BomGenerator:
    """Generate and price BOMs from schematics."""

    def __init__(self, db: ComponentDatabase | None = None):
        self.db = db or ComponentDatabase()

    def from_schematic(self, sch: Schematic, project_name: str = "") -> Bom:
        """Group schematic components by (value, footprint, mpn)."""
        groups: dict[tuple[str, str, str], BomLine] = {}
        for refdes, comp in sch.components.items():
            if comp.do_not_populate:
                continue
            key = (comp.value, comp.footprint, comp.mpn)
            if key in groups:
                line = groups[key]
                line.refdes_list.append(refdes)
                line.quantity += 1
            else:
                line = BomLine(
                    refdes_list=[refdes],
                    quantity=1,
                    value=comp.value,
                    footprint=comp.footprint,
                    mpn=comp.mpn,
                    manufacturer=comp.manufacturer,
                )
                groups[key] = line

        # sort refdes alphanumerically inside each line
        for line in groups.values():
            line.refdes_list.sort(key=_natural_key)

        bom = Bom(project_name=project_name or sch.name, revision=sch.revision)
        # stable order: by first refdes
        for line in sorted(groups.values(), key=lambda l: _natural_key(l.refdes_list[0])):
            bom.lines.append(line)
        bom.recalc()
        self.lookup_pricing(bom)
        return bom

    def lookup_pricing(self, bom: Bom) -> Bom:
        """Look up unit costs and stock from the component database."""
        for line in bom.lines:
            comp = None
            if line.mpn:
                comp = self.db.get(line.mpn)
            if comp is None:
                # Try finding by value+footprint
                candidates = self.db.search(line.value, limit=5)
                for c in candidates:
                    if not line.footprint or c.package == line.footprint:
                        comp = c
                        break
                if comp is None and candidates:
                    comp = candidates[0]
            if comp is not None:
                line.mpn = line.mpn or comp.mpn
                line.manufacturer = line.manufacturer or comp.manufacturer
                line.description = line.description or comp.description
                line.datasheet_url = comp.datasheet_url
                line.unit_cost = comp.unit_price(line.quantity)
                line.in_stock = comp.stock >= line.quantity
                line.recalc_total()
        bom.recalc()
        return bom

    def find_alternatives(self, bom_line: BomLine) -> list[Component]:
        """Find functionally equivalent parts for a BOM line."""
        results: list[Component] = []
        seen: set[str] = set()
        if bom_line.value:
            for c in self.db.search(bom_line.value, limit=30):
                if c.mpn == bom_line.mpn or c.mpn in seen:
                    continue
                if bom_line.footprint and c.package != bom_line.footprint:
                    continue
                results.append(c)
                seen.add(c.mpn)
        return results


def _natural_key(s: str) -> list:
    """Alphanumeric sort key: R2 before R10."""
    import re

    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]

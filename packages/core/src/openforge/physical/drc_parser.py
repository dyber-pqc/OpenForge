"""DRC report parser.

Supports the three formats OpenForge flows commonly encounter:

* **Magic** (``feedback`` / ``.mag`` drc lists) — line based text with
  ``box`` coordinates.
* **KLayout** — XML ``*.lyrdb`` / ``*.rve`` reports.
* **OpenROAD** — JSON style from ``detailed_route -output_drc``.

Every parser normalises into :class:`DrcReport` / :class:`DrcViolation`,
letting the UI stay format-agnostic.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Iterable


class DrcViolation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rule: str
    layer: str = ""
    count: int = 1
    x_um: float = 0.0
    y_um: float = 0.0
    x2_um: float = 0.0
    y2_um: float = 0.0
    severity: str = "error"  # error | warning | info
    message: str = ""

    @property
    def center(self) -> tuple[float, float]:
        if self.x2_um or self.y2_um:
            return ((self.x_um + self.x2_um) / 2, (self.y_um + self.y2_um) / 2)
        return (self.x_um, self.y_um)


class DrcReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool: str = "unknown"
    design: str = ""
    violations: list[DrcViolation] = Field(default_factory=list)

    # ------------------------------------------------------------------ api

    @classmethod
    def auto_load(cls, path: str | Path) -> DrcReport:
        p = Path(path)
        text = p.read_text(encoding="utf-8", errors="replace")
        stripped = text.lstrip()
        if stripped.startswith("<?xml") or stripped.startswith("<report"):
            return cls.from_klayout_drc(text)
        if stripped.startswith("{") or stripped.startswith("["):
            return cls.from_openroad_drc(text)
        return cls.from_magic_report(text)

    # --- Magic ------------------------------------------------------------

    @classmethod
    def from_magic_report(cls, text: str) -> DrcReport:
        """Parse a magic ``drc find`` / ``drc listall why`` text report.

        The format is::

            ----------------------------------------
            Metal2 spacing < 0.28um (met2)
            ----------------------------------------
               0.145um 3.420um 0.285um 3.580um

        i.e. a rule banner followed by one or more ``box`` lines with
        four µm coordinates.
        """
        violations: list[DrcViolation] = []
        current_rule: str | None = None
        current_layer = ""
        current_severity = "error"

        rule_re = re.compile(r"^[-=]{3,}")
        box_re = re.compile(
            r"^\s*([-\d.]+)\s*(?:um)?\s+([-\d.]+)\s*(?:um)?\s+"
            r"([-\d.]+)\s*(?:um)?\s+([-\d.]+)\s*(?:um)?\s*$"
        )
        layer_re = re.compile(r"\(([^)]+)\)\s*$")

        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if rule_re.match(line) and i + 1 < len(lines):
                current_rule = lines[i + 1].strip()
                m = layer_re.search(current_rule)
                if m:
                    current_layer = m.group(1).strip()
                    current_rule = layer_re.sub("", current_rule).strip()
                else:
                    current_layer = ""
                current_severity = "warning" if "warning" in current_rule.lower() else "error"
                i += 2
                # skip the trailing "----" banner line if present
                if i < len(lines) and rule_re.match(lines[i]):
                    i += 1
                continue

            m = box_re.match(line)
            if m and current_rule:
                x1, y1, x2, y2 = (float(v) for v in m.groups())
                violations.append(
                    DrcViolation(
                        rule=current_rule,
                        layer=current_layer,
                        x_um=x1,
                        y_um=y1,
                        x2_um=x2,
                        y2_um=y2,
                        severity=current_severity,
                        message=current_rule,
                    )
                )
            i += 1

        return cls(tool="magic", violations=violations)

    # --- KLayout ----------------------------------------------------------

    @classmethod
    def from_klayout_drc(cls, xml_text: str) -> DrcReport:
        """Parse a KLayout ``rdb``/``lyrdb`` XML report."""
        violations: list[DrcViolation] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return cls(tool="klayout", violations=violations)

        categories: dict[str, str] = {}
        for cat in root.iter("category"):
            cid = cat.findtext("name", default="") or cat.get("id", "")
            desc = cat.findtext("description", default="") or cid
            categories[cid] = desc

        for item in root.iter("item"):
            cat_id = item.findtext("category", default="")
            rule_name = categories.get(cat_id, cat_id) or "unknown"
            cell = item.findtext("cell", default="")
            value = item.findtext("value", default="")
            x, y, x2, y2 = 0.0, 0.0, 0.0, 0.0
            # values can be polygons/boxes; extract bbox crudely
            nums = re.findall(r"-?\d+(?:\.\d+)?", value)
            if len(nums) >= 4:
                xs = [float(n) for n in nums[0::2]]
                ys = [float(n) for n in nums[1::2]]
                x, y = min(xs), min(ys)
                x2, y2 = max(xs), max(ys)
            violations.append(
                DrcViolation(
                    rule=rule_name,
                    layer=cell or "",
                    x_um=x,
                    y_um=y,
                    x2_um=x2,
                    y2_um=y2,
                    severity="error",
                    message=rule_name,
                )
            )

        return cls(tool="klayout", violations=violations)

    # --- OpenROAD ---------------------------------------------------------

    @classmethod
    def from_openroad_drc(cls, json_text: str) -> DrcReport:
        """Parse the JSON style output from OpenROAD detailed route."""
        violations: list[DrcViolation] = []
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError:
            return cls(tool="openroad", violations=violations)

        raw: Iterable[dict]
        if isinstance(data, dict):
            raw = data.get("violations") or data.get("drcs") or []
            design = data.get("design", "")
        else:
            raw = data
            design = ""

        for v in raw:
            rule = v.get("rule") or v.get("name") or v.get("type", "unknown")
            layer = v.get("layer", "")
            sev = v.get("severity", "error")
            x = float(v.get("x") or v.get("x1") or 0.0)
            y = float(v.get("y") or v.get("y1") or 0.0)
            x2 = float(v.get("x2", x))
            y2 = float(v.get("y2", y))
            if "bbox" in v and isinstance(v["bbox"], (list, tuple)) and len(v["bbox"]) == 4:
                x, y, x2, y2 = (float(c) for c in v["bbox"])
            violations.append(
                DrcViolation(
                    rule=str(rule),
                    layer=str(layer),
                    x_um=x,
                    y_um=y,
                    x2_um=x2,
                    y2_um=y2,
                    severity=str(sev),
                    message=v.get("message", str(rule)),
                )
            )

        return cls(tool="openroad", design=design, violations=violations)

    # ------------------------------------------------------------------ qry

    def grouped_by_rule(self) -> dict[str, list[DrcViolation]]:
        out: dict[str, list[DrcViolation]] = {}
        for v in self.violations:
            out.setdefault(v.rule, []).append(v)
        return out

    def grouped_by_layer(self) -> dict[str, list[DrcViolation]]:
        out: dict[str, list[DrcViolation]] = {}
        for v in self.violations:
            out.setdefault(v.layer or "-", []).append(v)
        return out

    def total_count(self) -> int:
        return sum(v.count for v in self.violations)

    def density_grid(self, grid_size_um: float) -> np.ndarray:
        """Bin violations into a 2D density grid (counts per bin)."""
        if not self.violations or grid_size_um <= 0:
            return np.zeros((1, 1), dtype=np.int32)
        xs = [v.center[0] for v in self.violations]
        ys = [v.center[1] for v in self.violations]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        w = max(x_max - x_min, grid_size_um)
        h = max(y_max - y_min, grid_size_um)
        nx = max(1, int(np.ceil(w / grid_size_um)))
        ny = max(1, int(np.ceil(h / grid_size_um)))
        grid = np.zeros((ny, nx), dtype=np.int32)
        for v in self.violations:
            cx, cy = v.center
            ix = int((cx - x_min) / grid_size_um)
            iy = int((cy - y_min) / grid_size_um)
            ix = min(max(ix, 0), nx - 1)
            iy = min(max(iy, 0), ny - 1)
            grid[iy, ix] += v.count
        return grid


__all__ = ["DrcViolation", "DrcReport"]

"""Multi-Vt optimization.

Swap cells between low / regular / high threshold voltage variants to
trade leakage power against delay. The optimizer consumes an
:class:`~openforge.physical.sta_parser.StaReport` to know which paths
have positive slack (safe to swap to a slower variant) and which are
critical (need a faster variant).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from openforge.physical.eco import EcoCommand, EcoCommandKind, EcoScript

if TYPE_CHECKING:
    from openforge.physical.sta_parser import StaReport


class VtClass(StrEnum):
    LVT = "lvt"
    RVT = "rvt"
    HVT = "hvt"
    ULVT = "ulvt"


# Relative leakage / delay multipliers used when a liberty file does
# not supply explicit numbers. These are representative of a typical
# bulk CMOS process — ULVT is fastest and leakiest, HVT is slowest and
# lowest-leakage.
_DEFAULT_LEAKAGE = {
    VtClass.ULVT: 100.0,
    VtClass.LVT: 20.0,
    VtClass.RVT: 5.0,
    VtClass.HVT: 1.0,
}
_DEFAULT_DELAY = {
    VtClass.ULVT: 0.85,
    VtClass.LVT: 1.0,
    VtClass.RVT: 1.15,
    VtClass.HVT: 1.4,
}


class CellVtVariant(BaseModel):
    model_config = ConfigDict(extra="allow")

    cell_name: str
    base_name: str
    drive: str
    vt: VtClass
    leakage_pw: float = 0.0
    delay_ps: float = 0.0


class MultiVtLibrary(BaseModel):
    """Collection of known Vt variants, keyed by cell name."""

    model_config = ConfigDict(extra="allow")

    cells: dict[str, CellVtVariant] = Field(default_factory=dict)
    families: dict[str, list[str]] = Field(default_factory=dict)

    # ----- construction --------------------------------------------------

    def add(self, variant: CellVtVariant) -> None:
        self.cells[variant.cell_name] = variant
        key = f"{variant.base_name}_{variant.drive}"
        bucket = self.families.setdefault(key, [])
        if variant.cell_name not in bucket:
            bucket.append(variant.cell_name)

    @classmethod
    def synthetic(
        cls,
        bases: list[str] | None = None,
        drives: list[str] | None = None,
    ) -> MultiVtLibrary:
        """Build a fallback library when no liberty files are available."""
        lib = cls()
        bases = bases or ["INV", "BUF", "NAND2", "NOR2", "AND2", "OR2", "DFF"]
        drives = drives or ["X1", "X2", "X4", "X8"]
        for base in bases:
            for drive in drives:
                for vt in (VtClass.LVT, VtClass.RVT, VtClass.HVT):
                    name = f"{base}_{vt.value}_{drive}"
                    drive_n = int("".join(ch for ch in drive if ch.isdigit()) or 1)
                    lib.add(
                        CellVtVariant(
                            cell_name=name,
                            base_name=base,
                            drive=drive,
                            vt=vt,
                            leakage_pw=_DEFAULT_LEAKAGE[vt] * drive_n,
                            delay_ps=_DEFAULT_DELAY[vt] * 40.0 / max(drive_n, 1),
                        )
                    )
        return lib

    # ----- queries -------------------------------------------------------

    def siblings(self, cell_name: str) -> list[CellVtVariant]:
        cell = self.cells.get(cell_name)
        if cell is None:
            return []
        key = f"{cell.base_name}_{cell.drive}"
        return [self.cells[n] for n in self.families.get(key, []) if n in self.cells]

    def find_swap(
        self, current: str, slack_change_target: float
    ) -> str | None:
        """Find a sibling variant that changes the delay by about
        ``slack_change_target`` nanoseconds.

        Positive targets ask for a slower cell (leakage down); negative
        targets ask for a faster cell (leakage up).
        """
        cell = self.cells.get(current)
        if cell is None:
            return None
        siblings = [s for s in self.siblings(current) if s.cell_name != current]
        if not siblings:
            return None
        want_ps = slack_change_target * 1000.0  # ns -> ps
        current_delay = cell.delay_ps
        best: tuple[float, CellVtVariant] | None = None
        for s in siblings:
            delta = s.delay_ps - current_delay
            # We want ``delta`` to match ``want_ps`` in sign and be as
            # close in magnitude as possible without exceeding it.
            if want_ps >= 0 and delta < 0:
                continue
            if want_ps < 0 and delta > 0:
                continue
            score = abs(delta - want_ps)
            if best is None or score < best[0]:
                best = (score, s)
        return best[1].cell_name if best else None


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------


class MultiVtOptimizer:
    """Top-level driver for leakage / speed multi-Vt optimization."""

    def __init__(
        self,
        lib: MultiVtLibrary,
        def_path: Path,
        sta_report: StaReport,
    ) -> None:
        self.lib = lib
        self.def_path = Path(def_path)
        self.sta = sta_report
        self._instance_to_cell = self._parse_instance_cells()

    # ----- DEF parsing ---------------------------------------------------

    def _parse_instance_cells(self) -> dict[str, str]:
        import re

        mapping: dict[str, str] = {}
        try:
            text = self.def_path.read_text(errors="ignore")
        except OSError:
            return mapping
        # DEF COMPONENTS rows: "    - inst_name cell_name + ..."
        for m in re.finditer(
            r"^\s*-\s+(\S+)\s+(\S+)\b", text, re.MULTILINE
        ):
            mapping[m.group(1)] = m.group(2)
        return mapping

    # ----- leakage reduction --------------------------------------------

    def reduce_leakage(
        self,
        target_leakage_pw: float | None = None,
    ) -> EcoScript:
        """Swap cells on paths with positive slack to lower Vt variants.

        Safe order: HVT is slowest + lowest leakage, so we try
        LVT -> RVT -> HVT without crossing zero slack.
        """
        commands: list[EcoCommand] = []
        touched: set[str] = set()

        # Skip data paths with any slack violation.
        safe_insts: dict[str, float] = {}
        for path in self.sta.setup_paths():
            slack = path.slack_ns
            if slack <= 0:
                continue
            for stage in path.data_path:
                inst = stage.cell_instance
                if not inst:
                    continue
                # Slowest allowed swap per instance is limited by the
                # path with smallest slack that uses it.
                prev = safe_insts.get(inst)
                if prev is None or slack < prev:
                    safe_insts[inst] = slack

        running_savings_pw = 0.0
        for inst, slack in sorted(safe_insts.items(), key=lambda kv: -kv[1]):
            if inst in touched:
                continue
            current_cell = self._instance_to_cell.get(inst)
            if current_cell is None:
                continue
            current = self.lib.cells.get(current_cell)
            if current is None:
                continue
            # Try to spend roughly 50% of available slack on leakage.
            target_ns = slack * 0.5
            new_cell = self.lib.find_swap(current_cell, target_ns)
            if new_cell is None or new_cell == current_cell:
                continue
            variant = self.lib.cells[new_cell]
            leakage_delta = current.leakage_pw - variant.leakage_pw
            if leakage_delta <= 0:
                continue
            running_savings_pw += leakage_delta
            commands.append(
                EcoCommand(
                    kind=EcoCommandKind.CHANGE_CELL,
                    target_inst=inst,
                    new_cell=new_cell,
                    slack_before_ns=slack,
                    notes=(
                        f"leakage: {current_cell} ({current.vt.value}) -> "
                        f"{new_cell} ({variant.vt.value}) "
                        f"saves {leakage_delta:.1f} pW"
                    ),
                )
            )
            touched.add(inst)
            if (
                target_leakage_pw is not None
                and running_savings_pw >= target_leakage_pw
            ):
                break

        return EcoScript(
            commands=commands,
            metadata={
                "kind": "leakage_reduction",
                "savings_pw": running_savings_pw,
                "target_pw": target_leakage_pw,
                "cells_swapped": len(commands),
            },
        )

    # ----- speed recovery -----------------------------------------------

    def increase_speed(self, target_slack_ns: float) -> EcoScript:
        """Swap critical cells to faster (lower Vt) variants."""
        commands: list[EcoCommand] = []
        touched: set[str] = set()
        added_leakage_pw = 0.0

        critical = [
            p for p in self.sta.setup_paths() if p.slack_ns < target_slack_ns
        ]
        critical.sort(key=lambda p: p.slack_ns)
        for path in critical:
            needed = target_slack_ns - path.slack_ns
            if needed <= 0:
                continue
            # Budget the speedup across the worst stages
            worst = sorted(
                [s for s in path.data_path if s.cell_instance and s.cell_type],
                key=lambda s: s.delay_ns,
                reverse=True,
            )[:5]
            for stage in worst:
                inst = stage.cell_instance
                if inst in touched:
                    continue
                current_cell = self._instance_to_cell.get(inst, stage.cell_type)
                current = self.lib.cells.get(current_cell)
                if current is None:
                    continue
                # negative target = faster (smaller delay)
                chunk = -min(needed, 0.05)
                new_cell = self.lib.find_swap(current_cell, chunk)
                if new_cell is None or new_cell == current_cell:
                    continue
                variant = self.lib.cells[new_cell]
                delay_gain_ns = (current.delay_ps - variant.delay_ps) / 1000.0
                if delay_gain_ns <= 0:
                    continue
                leakage_cost = variant.leakage_pw - current.leakage_pw
                added_leakage_pw += max(0.0, leakage_cost)
                commands.append(
                    EcoCommand(
                        kind=EcoCommandKind.CHANGE_CELL,
                        target_inst=inst,
                        new_cell=new_cell,
                        slack_before_ns=path.slack_ns,
                        slack_after_ns=path.slack_ns + delay_gain_ns,
                        notes=(
                            f"speed: {current_cell} ({current.vt.value}) -> "
                            f"{new_cell} ({variant.vt.value}) "
                            f"gains {delay_gain_ns*1000:.1f} ps"
                        ),
                    )
                )
                touched.add(inst)
                needed -= delay_gain_ns
                if needed <= 0:
                    break
        return EcoScript(
            commands=commands,
            metadata={
                "kind": "speed_recovery",
                "target_slack_ns": target_slack_ns,
                "added_leakage_pw": added_leakage_pw,
                "cells_swapped": len(commands),
            },
        )

    # ----- distribution -------------------------------------------------

    def report_distribution(self) -> dict[VtClass, int]:
        counts: dict[VtClass, int] = {vt: 0 for vt in VtClass}
        for cell_name in self._instance_to_cell.values():
            cell = self.lib.cells.get(cell_name)
            if cell is None:
                continue
            counts[cell.vt] = counts.get(cell.vt, 0) + 1
        return counts


__all__ = [
    "VtClass",
    "CellVtVariant",
    "MultiVtLibrary",
    "MultiVtOptimizer",
]

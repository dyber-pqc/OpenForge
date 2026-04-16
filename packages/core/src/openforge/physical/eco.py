"""Engineering Change Order (ECO) engine.

Turns STA violations into a structured list of :class:`EcoCommand`
actions that can be rendered as OpenROAD or Innovus Tcl scripts and
applied to a routed design without a full re-synthesis.

The engine deliberately treats commands as data — callers (the ECO
browser panel, the scheduler, regression scripts) can inspect,
reorder, filter or persist the output before invoking the tool.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from openforge.physical.sta_parser import StaReport, TimingPath


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


class EcoCommandKind(StrEnum):
    CHANGE_CELL = "change_cell"
    ADD_BUFFER = "add_buffer"
    ADD_REPEATER = "add_repeater"
    DELETE_INSTANCE = "delete_instance"
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    REASSIGN = "reassign"
    FREEZE_NET = "freeze_net"
    UNFREEZE_NET = "unfreeze_net"


class EcoCommand(BaseModel):
    """A single ECO operation.

    Fields used depend on ``kind`` — for example ``ADD_BUFFER`` uses
    ``net`` and ``location`` while ``CHANGE_CELL`` uses ``target_inst``
    and ``new_cell``.
    """

    model_config = ConfigDict(extra="allow")

    kind: EcoCommandKind
    target_inst: str | None = None
    new_cell: str | None = None
    net: str | None = None
    location: tuple[float, float] | None = None
    notes: str | None = None

    # optional bookkeeping fields
    slack_before_ns: float | None = None
    slack_after_ns: float | None = None
    buffer_cell: str | None = None


class EcoScript(BaseModel):
    """Ordered list of ECO commands plus metadata."""

    model_config = ConfigDict(extra="allow")

    commands: list[EcoCommand] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    # ----- serialisation --------------------------------------------------

    def to_openroad_tcl(self) -> str:
        """Render as an OpenROAD ECO Tcl script.

        Uses the same command subset OpenROAD's restore/ECO mode
        accepts: ``replace_cell``, ``insert_buffer``, ``disconnect_pin``
        / ``connect_pin`` and ``remove_buffers`` for deletion.
        """
        lines: list[str] = []
        lines.append("# OpenForge ECO script (OpenROAD)")
        lines.append("# Load prerequisites before sourcing this file:")
        lines.append("#   read_lef <tech.lef> <cells.lef>")
        lines.append("#   read_def <placed.def>")
        lines.append("#   read_liberty <corner.lib>")
        lines.append("")
        for idx, cmd in enumerate(self.commands, 1):
            if cmd.notes:
                lines.append(f"# [{idx}] {cmd.notes}")
            if cmd.kind is EcoCommandKind.CHANGE_CELL:
                lines.append(
                    f"replace_cell {{{cmd.target_inst}}} {cmd.new_cell}"
                )
            elif cmd.kind is EcoCommandKind.ADD_BUFFER:
                loc = cmd.location or (0.0, 0.0)
                buf = cmd.buffer_cell or cmd.new_cell or "BUF_X2"
                lines.append(
                    f"insert_buffer -net {{{cmd.net}}} -master {buf} "
                    f"-location {{{loc[0]:.3f} {loc[1]:.3f}}}"
                )
            elif cmd.kind is EcoCommandKind.ADD_REPEATER:
                buf = cmd.buffer_cell or cmd.new_cell or "BUF_X4"
                lines.append(
                    f"repair_design -max_utilization 100 "
                    f"-buffer_gain 8 ;# repeater on net {cmd.net}"
                )
                lines.append(
                    f"insert_buffer -net {{{cmd.net}}} -master {buf}"
                )
            elif cmd.kind is EcoCommandKind.DELETE_INSTANCE:
                lines.append(f"delete_instance {{{cmd.target_inst}}}")
            elif cmd.kind is EcoCommandKind.CONNECT:
                lines.append(
                    f"connect_pin -inst {{{cmd.target_inst}}} -net {{{cmd.net}}}"
                )
            elif cmd.kind is EcoCommandKind.DISCONNECT:
                lines.append(
                    f"disconnect_pin -inst {{{cmd.target_inst}}} -net {{{cmd.net}}}"
                )
            elif cmd.kind is EcoCommandKind.REASSIGN:
                lines.append(
                    f"disconnect_pin -inst {{{cmd.target_inst}}}"
                )
                lines.append(
                    f"connect_pin -inst {{{cmd.target_inst}}} -net {{{cmd.net}}}"
                )
            elif cmd.kind is EcoCommandKind.FREEZE_NET:
                lines.append(f"set_dont_touch {{{cmd.net}}}")
            elif cmd.kind is EcoCommandKind.UNFREEZE_NET:
                lines.append(f"unset_dont_touch {{{cmd.net}}}")
        lines.append("")
        lines.append("# re-route ECO")
        lines.append("detailed_route_eco")
        lines.append("write_def eco_out.def")
        lines.append("")
        return "\n".join(lines)

    def to_innovus_tcl(self) -> str:
        """Render as Cadence Innovus ECO Tcl."""
        lines: list[str] = []
        lines.append("# OpenForge ECO script (Innovus)")
        lines.append("setEcoMode -honorDontUse false -honorDontTouch true \\")
        lines.append("    -honorFixedStatus true -refinePlace true")
        lines.append("")
        for idx, cmd in enumerate(self.commands, 1):
            if cmd.notes:
                lines.append(f"# [{idx}] {cmd.notes}")
            if cmd.kind is EcoCommandKind.CHANGE_CELL:
                lines.append(
                    f"ecoChangeCell -inst {cmd.target_inst} -cell {cmd.new_cell}"
                )
            elif cmd.kind is EcoCommandKind.ADD_BUFFER:
                loc = cmd.location or (0.0, 0.0)
                buf = cmd.buffer_cell or cmd.new_cell or "BUFX2"
                lines.append(
                    f"ecoAddRepeater -net {cmd.net} -cell {buf} "
                    f"-loc {{{loc[0]:.3f} {loc[1]:.3f}}}"
                )
            elif cmd.kind is EcoCommandKind.ADD_REPEATER:
                buf = cmd.buffer_cell or cmd.new_cell or "BUFX4"
                lines.append(
                    f"ecoAddRepeater -net {cmd.net} -cell {buf} -stages 2"
                )
            elif cmd.kind is EcoCommandKind.DELETE_INSTANCE:
                lines.append(f"ecoDeleteRepeater -inst {cmd.target_inst}")
            elif cmd.kind is EcoCommandKind.CONNECT:
                lines.append(
                    f"attachTerm {cmd.target_inst} {cmd.net}"
                )
            elif cmd.kind is EcoCommandKind.DISCONNECT:
                lines.append(
                    f"detachTerm {cmd.target_inst} {cmd.net}"
                )
            elif cmd.kind is EcoCommandKind.REASSIGN:
                lines.append(
                    f"detachTerm {cmd.target_inst} ;# reassign"
                )
                lines.append(
                    f"attachTerm {cmd.target_inst} {cmd.net}"
                )
            elif cmd.kind is EcoCommandKind.FREEZE_NET:
                lines.append(f"setDontTouch {cmd.net} true")
            elif cmd.kind is EcoCommandKind.UNFREEZE_NET:
                lines.append(f"setDontTouch {cmd.net} false")
        lines.append("")
        lines.append("ecoRoute")
        lines.append("defOut -routing eco_out.def")
        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Drive strength heuristics
# ---------------------------------------------------------------------------


_DRIVE_RE = re.compile(r"(?P<base>[A-Za-z][\w]*?)(?:_)?(?P<x>[xX])(?P<num>\d+)$")


def _parse_drive(cell: str) -> tuple[str, str, int] | None:
    """Split a cell name like ``NAND2_X1`` -> (``NAND2``, ``_X``, 1)."""
    m = _DRIVE_RE.search(cell)
    if not m:
        return None
    base = m.group("base")
    sep = "_" + m.group("x")
    return base, sep, int(m.group("num"))


def _upsize_cell(cell: str) -> str | None:
    """Propose a higher drive strength variant.

    Uses the common powers-of-two convention (X1 -> X2 -> X4 -> X8 ->
    X16). Returns ``None`` if the cell name doesn't follow the pattern.
    """
    parts = _parse_drive(cell)
    if parts is None:
        return None
    base, sep, drive = parts
    next_drive = drive * 2 if drive >= 1 else 2
    if next_drive > 32:
        return None
    return f"{base}{sep}{next_drive}"


# ---------------------------------------------------------------------------
# ECO engine
# ---------------------------------------------------------------------------


class EcoEngine:
    """Generate ECO scripts from STA reports."""

    def __init__(
        self,
        def_path: Path,
        lef_path: Path,
        lib_path: Path | None = None,
        *,
        default_buffer: str = "BUF_X2",
        default_repeater: str = "BUF_X4",
    ) -> None:
        self.def_path = Path(def_path)
        self.lef_path = Path(lef_path)
        self.lib_path = Path(lib_path) if lib_path else None
        self.default_buffer = default_buffer
        self.default_repeater = default_repeater
        self._cell_cache: dict[str, dict] = {}

    # ----- setup ---------------------------------------------------------

    def fix_setup_violations(
        self,
        sta_report: StaReport,
        slack_threshold: float = 0.0,
        max_changes: int = 100,
    ) -> EcoScript:
        """Walk the worst paths and propose upsizes/buffers."""
        from openforge.physical.sta_parser import StaReport  # noqa: F401

        commands: list[EcoCommand] = []
        touched_insts: set[str] = set()

        paths = [
            p for p in sta_report.setup_paths() if p.slack_ns < slack_threshold
        ]
        paths.sort(key=lambda p: p.slack_ns)

        for path in paths:
            if len(commands) >= max_changes:
                break
            # Identify worst-delay stages on the data path
            worst = self._worst_data_stages(path, k=3)
            for stage in worst:
                if len(commands) >= max_changes:
                    break
                inst = stage.cell_instance
                if not inst or inst in touched_insts:
                    continue
                new_cell = _upsize_cell(stage.cell_type)
                if new_cell is None:
                    # Fall back: convert HVT->RVT by stripping hvt marker
                    new_cell = self._vt_step_up(stage.cell_type)
                if new_cell is None or new_cell == stage.cell_type:
                    continue
                commands.append(
                    EcoCommand(
                        kind=EcoCommandKind.CHANGE_CELL,
                        target_inst=inst,
                        new_cell=new_cell,
                        slack_before_ns=path.slack_ns,
                        notes=(
                            f"setup fix: {stage.cell_type} -> {new_cell} "
                            f"on endpoint {path.endpoint}"
                        ),
                    )
                )
                touched_insts.add(inst)

            # If we still need more help, insert a buffer on the worst net
            if (
                path.slack_ns < slack_threshold * 2
                and len(commands) < max_changes
            ):
                pivot = worst[0] if worst else None
                if pivot and pivot.cell_instance:
                    commands.append(
                        EcoCommand(
                            kind=EcoCommandKind.ADD_BUFFER,
                            net=pivot.cell_instance,
                            buffer_cell=self.default_buffer,
                            location=None,
                            slack_before_ns=path.slack_ns,
                            notes=(
                                f"setup fix: insert buffer after "
                                f"{pivot.cell_instance}"
                            ),
                        )
                    )
        return EcoScript(
            commands=commands,
            metadata={
                "kind": "setup_fix",
                "slack_threshold": slack_threshold,
                "paths_considered": len(paths),
                "changes": len(commands),
            },
        )

    # ----- hold ----------------------------------------------------------

    def fix_hold_violations(
        self,
        sta_report: StaReport,
        slack_threshold: float = 0.0,
        max_changes: int = 100,
    ) -> EcoScript:
        """Insert buffers on violating hold paths to add data delay."""
        commands: list[EcoCommand] = []
        paths = [
            p for p in sta_report.hold_paths() if p.slack_ns < slack_threshold
        ]
        paths.sort(key=lambda p: p.slack_ns)

        for path in paths:
            if len(commands) >= max_changes:
                break
            # How many delay buffers are needed to cover the violation
            # (assume ~40 ps per BUF_X1 at the target corner).
            violation_ns = max(0.0, -path.slack_ns)
            nbufs = max(1, int(round(violation_ns / 0.04)))
            nbufs = min(nbufs, 8)
            anchor = self._hold_anchor(path)
            if anchor is None:
                continue
            for _ in range(nbufs):
                if len(commands) >= max_changes:
                    break
                commands.append(
                    EcoCommand(
                        kind=EcoCommandKind.ADD_BUFFER,
                        net=anchor,
                        buffer_cell=self.default_buffer,
                        slack_before_ns=path.slack_ns,
                        notes=(
                            f"hold fix: delay buffer on {anchor} "
                            f"({violation_ns:.3f} ns)"
                        ),
                    )
                )
        return EcoScript(
            commands=commands,
            metadata={
                "kind": "hold_fix",
                "slack_threshold": slack_threshold,
                "paths_considered": len(paths),
                "changes": len(commands),
            },
        )

    # ----- metal-only ----------------------------------------------------

    def metal_only_eco(self, commands: list[EcoCommand]) -> bool:
        """True if the command list only touches routing.

        Metal-only ECOs cannot add, remove or swap logic cells — only
        re-route or freeze nets.
        """
        forbidden = {
            EcoCommandKind.CHANGE_CELL,
            EcoCommandKind.ADD_BUFFER,
            EcoCommandKind.ADD_REPEATER,
            EcoCommandKind.DELETE_INSTANCE,
        }
        return all(cmd.kind not in forbidden for cmd in commands)

    # ----- disturbance ---------------------------------------------------

    def estimate_disturbance(self, script: EcoScript) -> dict:
        """Rough estimate of the cost of applying ``script``."""
        cells_changed = 0
        nets_rerouted: set[str] = set()
        added_cells = 0
        deleted = 0
        area_delta = 0.0
        for cmd in script.commands:
            if cmd.kind is EcoCommandKind.CHANGE_CELL:
                cells_changed += 1
                # upsizing doubles drive -> ~2x the transistor width
                area_delta += 2.5
                if cmd.target_inst:
                    nets_rerouted.add(cmd.target_inst)
            elif cmd.kind in (
                EcoCommandKind.ADD_BUFFER,
                EcoCommandKind.ADD_REPEATER,
            ):
                added_cells += 1
                area_delta += 3.0
                if cmd.net:
                    nets_rerouted.add(cmd.net)
            elif cmd.kind is EcoCommandKind.DELETE_INSTANCE:
                deleted += 1
                area_delta -= 2.0
            elif cmd.kind in (
                EcoCommandKind.CONNECT,
                EcoCommandKind.DISCONNECT,
                EcoCommandKind.REASSIGN,
            ):
                if cmd.net:
                    nets_rerouted.add(cmd.net)
        # Rough runtime model: 0.5s baseline + 0.2s per change
        estimated_runtime = 0.5 + 0.2 * (
            cells_changed + added_cells + deleted + len(nets_rerouted)
        )
        return {
            "cells_changed": cells_changed,
            "cells_added": added_cells,
            "cells_deleted": deleted,
            "nets_rerouted": len(nets_rerouted),
            "area_delta": area_delta,
            "estimated_runtime": estimated_runtime,
            "metal_only": self.metal_only_eco(script.commands),
        }

    # ----- helpers -------------------------------------------------------

    def _worst_data_stages(self, path: TimingPath, k: int = 3) -> list:
        stages = [
            s
            for s in path.data_path
            if s.cell_type and not s.is_register and not s.is_clock_edge
        ]
        stages.sort(key=lambda s: s.delay_ns, reverse=True)
        return stages[:k]

    def _hold_anchor(self, path: TimingPath) -> str | None:
        for stage in path.data_path:
            if stage.cell_instance and not stage.is_register:
                return stage.cell_instance
        return None

    def _vt_step_up(self, cell: str) -> str | None:
        """Heuristic Vt swap that reduces delay (HVT->RVT->LVT)."""
        lower = cell.lower()
        if "hvt" in lower:
            return cell.replace("hvt", "rvt").replace("HVT", "RVT")
        if "rvt" in lower:
            return cell.replace("rvt", "lvt").replace("RVT", "LVT")
        return None


# ---------------------------------------------------------------------------
# Spare cells
# ---------------------------------------------------------------------------


class SpareCellAllocator:
    """Sprinkle spare cells across a DEF for future metal-only ECOs."""

    def __init__(self, util_target: float = 0.8) -> None:
        self.util_target = util_target
        self.families: list[str] = [
            "NAND2_X1",
            "NOR2_X1",
            "INV_X1",
            "BUF_X1",
            "DFF_X1",
        ]

    def insert_spares(
        self,
        def_path: Path,
        density_per_um2: float,
        output: Path,
    ) -> int:
        """Insert spare instances into ``def_path``, write to ``output``.

        Returns the number of instances inserted. Density is "cells per
        square micron", e.g. ``0.001`` inserts roughly one spare per
        1000 um\u00b2.
        """
        def_path = Path(def_path)
        text = def_path.read_text(errors="ignore")

        # Extract die area to compute number of spares
        m = re.search(
            r"DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)",
            text,
        )
        units_m = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", text)
        units = int(units_m.group(1)) if units_m else 1000
        if m:
            llx, lly, urx, ury = (
                int(m.group(1)),
                int(m.group(2)),
                int(m.group(3)),
                int(m.group(4)),
            )
            width_um = (urx - llx) / units
            height_um = (ury - lly) / units
        else:
            width_um = height_um = 100.0

        total = int(width_um * height_um * density_per_um2)
        total = max(total, 0)

        spare_lines: list[str] = []
        grid = max(1, int(total ** 0.5) or 1)
        step_x = max(1.0, width_um / (grid + 1))
        step_y = max(1.0, height_um / (grid + 1))
        idx = 0
        for gy in range(grid):
            for gx in range(grid):
                if idx >= total:
                    break
                cell = self.families[idx % len(self.families)]
                x_dbu = int((gx + 1) * step_x * units)
                y_dbu = int((gy + 1) * step_y * units)
                spare_lines.append(
                    f"    - SPARE_{idx} {cell} + PLACED ( {x_dbu} {y_dbu} ) N ;"
                )
                idx += 1

        # Inject spares into the COMPONENTS section. If there is none,
        # append one before END DESIGN.
        comp_re = re.compile(r"(COMPONENTS\s+)(\d+)(\s*;)")
        mcomp = comp_re.search(text)
        injection = "\n".join(spare_lines)
        if mcomp:
            existing = int(mcomp.group(2))
            new_count = existing + idx
            text = comp_re.sub(
                f"\\g<1>{new_count}\\g<3>", text, count=1
            )
            end_re = re.compile(r"(END\s+COMPONENTS)")
            text = end_re.sub(injection + "\n\\1", text, count=1)
        else:
            insertion = (
                f"\nCOMPONENTS {idx} ;\n{injection}\nEND COMPONENTS\n"
            )
            text = text.replace("END DESIGN", insertion + "END DESIGN")

        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(text)
        return idx


__all__ = [
    "EcoCommandKind",
    "EcoCommand",
    "EcoScript",
    "EcoEngine",
    "SpareCellAllocator",
]

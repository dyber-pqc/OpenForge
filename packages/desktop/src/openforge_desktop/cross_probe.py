"""Cross-probing manager for OpenForge.

The :class:`CrossProbeManager` is the central nervous system that ties the
RTL editor, gate-level netlist viewer, layout (GDS/DEF) viewer, and waveform
viewer together. Selecting an object in any one of these views causes the
others to highlight or jump to the corresponding object.

The manager is a pure ``QObject`` so it can live in the main window and be
shared by every panel. Panels connect their selection signals to the
``select_*`` slots and listen on the ``*_selected`` signals to update their
own highlighting.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from PySide6.QtCore import QObject, Signal, Slot


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RtlLocation:
    file: str
    line: int
    col: int = 0
    end_line: int = 0
    end_col: int = 0


@dataclass
class LayoutBox:
    name: str
    x: float
    y: float
    width: float
    height: float
    orientation: str = "N"


@dataclass
class NetlistCell:
    instance: str
    cell_type: str
    src: Optional[RtlLocation] = None
    nets: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The manager
# ---------------------------------------------------------------------------


class CrossProbeManager(QObject):
    """Coordinates highlighting and navigation across panels."""

    rtl_location_selected = Signal(str, int)        # (file, line)
    netlist_cell_selected = Signal(str)             # cell instance
    layout_cell_selected = Signal(str, float, float)  # (name, x, y)
    waveform_signal_selected = Signal(str)          # signal name
    selection_cleared = Signal()
    map_loaded = Signal(str)                        # source ("yosys", "def", ...)

    # The Yosys src attribute format is:
    #   "<file>:<line>.<col>-<line>.<col>"
    # Multiple files may be comma-joined; we take the first.
    _SRC_RE = re.compile(r"([^:,]+):(\d+)\.(\d+)-(\d+)\.(\d+)")

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._source_map: dict[str, RtlLocation] = {}
        self._layout_map: dict[str, LayoutBox] = {}
        self._netlist_map: dict[str, NetlistCell] = {}
        self._signal_to_cells: dict[str, list[str]] = {}
        self._cell_to_signals: dict[str, list[str]] = {}
        self._current: Optional[str] = None  # last selected cell instance
        self._suppress = False  # re-entrancy guard

    # ------------------------------------------------------------------
    # Registration / loading
    # ------------------------------------------------------------------
    def register_source_map(self, mapping: dict) -> None:
        """Register a precomputed cell -> source mapping.

        ``mapping`` may be ``{cell: (file, line)}`` or ``{cell: RtlLocation}``.
        """
        for cell, value in mapping.items():
            if isinstance(value, RtlLocation):
                self._source_map[cell] = value
            elif isinstance(value, tuple) and len(value) >= 2:
                self._source_map[cell] = RtlLocation(file=str(value[0]), line=int(value[1]))
            elif isinstance(value, dict):
                self._source_map[cell] = RtlLocation(
                    file=str(value.get("file", "")),
                    line=int(value.get("line", 0)),
                    col=int(value.get("col", 0)),
                )
        self.map_loaded.emit("source")

    def register_layout_map(self, mapping: dict) -> None:
        """Register a precomputed cell -> layout box mapping."""
        for name, value in mapping.items():
            if isinstance(value, LayoutBox):
                self._layout_map[name] = value
            elif isinstance(value, tuple):
                if len(value) == 4:
                    x, y, w, h = value
                    self._layout_map[name] = LayoutBox(name, float(x), float(y), float(w), float(h))
                elif len(value) == 2:
                    x, y = value
                    self._layout_map[name] = LayoutBox(name, float(x), float(y), 0.0, 0.0)
            elif isinstance(value, dict):
                self._layout_map[name] = LayoutBox(
                    name=name,
                    x=float(value.get("x", 0.0)),
                    y=float(value.get("y", 0.0)),
                    width=float(value.get("width", 0.0)),
                    height=float(value.get("height", 0.0)),
                    orientation=str(value.get("orientation", "N")),
                )
        self.map_loaded.emit("layout")

    def register_netlist(self, cells: Iterable[NetlistCell]) -> None:
        for c in cells:
            self._netlist_map[c.instance] = c
            if c.src is not None:
                self._source_map[c.instance] = c.src
            for net in c.nets:
                self._signal_to_cells.setdefault(net, []).append(c.instance)
                self._cell_to_signals.setdefault(c.instance, []).append(net)
        self.map_loaded.emit("netlist")

    # ------------------------------------------------------------------
    # Yosys JSON parser
    # ------------------------------------------------------------------
    def parse_yosys_json(self, json_path: Path) -> None:
        """Build the source / netlist maps from a Yosys JSON dump.

        Yosys writes ``(* src = "file:line.col-line.col" *)`` attributes on
        cells, modules and wires when invoked with ``-defines -src``. This
        parser ignores parse errors so it can be used during early bring-up
        when the JSON may be incomplete.
        """
        try:
            data = json.loads(Path(json_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        modules = data.get("modules", {})
        for module_name, module in modules.items():
            cells = module.get("cells", {})
            for inst_name, cell in cells.items():
                src_attr = cell.get("attributes", {}).get("src", "")
                loc = self._parse_src_attr(src_attr)

                connections = cell.get("connections", {})
                nets: list[str] = []
                for port, bits in connections.items():
                    if isinstance(bits, list):
                        for b in bits:
                            net_name = self._resolve_bit(module, b)
                            if net_name:
                                nets.append(net_name)

                netlist_cell = NetlistCell(
                    instance=inst_name,
                    cell_type=cell.get("type", ""),
                    src=loc,
                    nets=nets,
                )
                self._netlist_map[inst_name] = netlist_cell
                if loc is not None:
                    self._source_map[inst_name] = loc
                for n in nets:
                    self._signal_to_cells.setdefault(n, []).append(inst_name)
                    self._cell_to_signals.setdefault(inst_name, []).append(n)

            # Wires also carry src information
            wires = module.get("netnames", {})
            for wire_name, wire in wires.items():
                src_attr = wire.get("attributes", {}).get("src", "")
                loc = self._parse_src_attr(src_attr)
                if loc is not None:
                    self._source_map.setdefault(wire_name, loc)

        self.map_loaded.emit("yosys")

    def _parse_src_attr(self, attr: str) -> Optional[RtlLocation]:
        if not attr:
            return None
        # Yosys may pack multiple sources separated by '|'.
        for chunk in attr.split("|"):
            m = self._SRC_RE.search(chunk)
            if m:
                return RtlLocation(
                    file=m.group(1),
                    line=int(m.group(2)),
                    col=int(m.group(3)),
                    end_line=int(m.group(4)),
                    end_col=int(m.group(5)),
                )
        return None

    def _resolve_bit(self, module: dict, bit) -> Optional[str]:
        if isinstance(bit, str):
            return bit
        if isinstance(bit, int):
            netnames = module.get("netnames", {})
            for name, info in netnames.items():
                if bit in info.get("bits", []):
                    return name
        return None

    # ------------------------------------------------------------------
    # DEF parser
    # ------------------------------------------------------------------
    def parse_def(self, def_path: Path) -> None:
        """Parse the COMPONENTS section of a DEF file.

        DEF COMPONENTS look like::

            COMPONENTS 100 ;
              - inst_name CELL_TYPE + PLACED ( 1234 5678 ) N ;
              ...
            END COMPONENTS

        Coordinates are in DBU (database units). Width/height are not in the
        COMPONENTS section so the manager records 0; the GDS viewer can
        enrich it later from the LEF.
        """
        try:
            text = Path(def_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return

        unit_scale = 1.0
        m = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", text)
        if m:
            unit_scale = 1.0 / float(m.group(1))

        in_components = False
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("COMPONENTS"):
                in_components = True
                continue
            if line.startswith("END COMPONENTS"):
                break
            if not in_components:
                continue
            if not line.startswith("-"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            inst = parts[1]
            placed = re.search(r"\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*([NSEW]+)?", line)
            if placed:
                x = int(placed.group(1)) * unit_scale
                y = int(placed.group(2)) * unit_scale
                orient = placed.group(3) or "N"
                self._layout_map[inst] = LayoutBox(
                    name=inst,
                    x=x,
                    y=y,
                    width=0.0,
                    height=0.0,
                    orientation=orient,
                )
        self.map_loaded.emit("def")

    # ------------------------------------------------------------------
    # Selection slots
    # ------------------------------------------------------------------
    @Slot(str)
    def select_rtl_signal(self, signal: str) -> None:
        if self._suppress:
            return
        self._suppress = True
        try:
            cells = self._signal_to_cells.get(signal, [])
            for c in cells:
                box = self._layout_map.get(c)
                if box is not None:
                    self.layout_cell_selected.emit(box.name, box.x, box.y)
                self.netlist_cell_selected.emit(c)
            self.waveform_signal_selected.emit(signal)
            loc = self._source_map.get(signal)
            if loc is not None:
                self.rtl_location_selected.emit(loc.file, loc.line)
        finally:
            self._suppress = False

    @Slot(str)
    def select_layout_cell(self, name: str) -> None:
        if self._suppress:
            return
        self._suppress = True
        try:
            self._current = name
            box = self._layout_map.get(name)
            if box is not None:
                self.layout_cell_selected.emit(box.name, box.x, box.y)
            self.netlist_cell_selected.emit(name)
            loc = self._source_map.get(name)
            if loc is not None:
                self.rtl_location_selected.emit(loc.file, loc.line)
            for net in self._cell_to_signals.get(name, []):
                self.waveform_signal_selected.emit(net)
        finally:
            self._suppress = False

    @Slot(str)
    def select_netlist_cell(self, name: str) -> None:
        if self._suppress:
            return
        self._suppress = True
        try:
            self._current = name
            self.netlist_cell_selected.emit(name)
            box = self._layout_map.get(name)
            if box is not None:
                self.layout_cell_selected.emit(box.name, box.x, box.y)
            loc = self._source_map.get(name)
            if loc is not None:
                self.rtl_location_selected.emit(loc.file, loc.line)
            for net in self._cell_to_signals.get(name, []):
                self.waveform_signal_selected.emit(net)
        finally:
            self._suppress = False

    @Slot(str)
    def select_waveform_signal(self, name: str) -> None:
        if self._suppress:
            return
        self._suppress = True
        try:
            self.waveform_signal_selected.emit(name)
            loc = self._source_map.get(name)
            if loc is not None:
                self.rtl_location_selected.emit(loc.file, loc.line)
            for c in self._signal_to_cells.get(name, []):
                box = self._layout_map.get(c)
                if box is not None:
                    self.layout_cell_selected.emit(box.name, box.x, box.y)
                self.netlist_cell_selected.emit(c)
        finally:
            self._suppress = False

    @Slot()
    def clear_selection(self) -> None:
        self._current = None
        self.selection_cleared.emit()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------
    def get_source_for(self, name: str) -> Optional[RtlLocation]:
        return self._source_map.get(name)

    def get_layout_for(self, name: str) -> Optional[LayoutBox]:
        return self._layout_map.get(name)

    def get_cells_for_signal(self, signal: str) -> list[str]:
        return list(self._signal_to_cells.get(signal, []))

    def get_signals_for_cell(self, cell: str) -> list[str]:
        return list(self._cell_to_signals.get(cell, []))

    def all_cells(self) -> list[str]:
        return list(self._netlist_map.keys())

    def all_signals(self) -> list[str]:
        return list(self._signal_to_cells.keys())

    def stats(self) -> dict:
        return {
            "source_entries": len(self._source_map),
            "layout_entries": len(self._layout_map),
            "netlist_cells": len(self._netlist_map),
            "signals": len(self._signal_to_cells),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save_to_json(self, path: Path) -> None:
        data = {
            "source_map": {
                k: {"file": v.file, "line": v.line, "col": v.col}
                for k, v in self._source_map.items()
            },
            "layout_map": {
                k: {"x": v.x, "y": v.y, "width": v.width, "height": v.height, "orient": v.orientation}
                for k, v in self._layout_map.items()
            },
            "netlist": {
                k: {"type": v.cell_type, "nets": v.nets}
                for k, v in self._netlist_map.items()
            },
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_from_json(self, path: Path) -> None:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for k, v in data.get("source_map", {}).items():
            self._source_map[k] = RtlLocation(file=v.get("file", ""), line=int(v.get("line", 0)), col=int(v.get("col", 0)))
        for k, v in data.get("layout_map", {}).items():
            self._layout_map[k] = LayoutBox(
                name=k,
                x=float(v.get("x", 0)),
                y=float(v.get("y", 0)),
                width=float(v.get("width", 0)),
                height=float(v.get("height", 0)),
                orientation=str(v.get("orient", "N")),
            )
        for k, v in data.get("netlist", {}).items():
            nets = list(v.get("nets", []))
            self._netlist_map[k] = NetlistCell(instance=k, cell_type=str(v.get("type", "")), nets=nets)
            for n in nets:
                self._signal_to_cells.setdefault(n, []).append(k)
                self._cell_to_signals.setdefault(k, []).append(n)
        self.map_loaded.emit("json")

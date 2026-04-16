"""Floorplan Editor Panel.

Visual floorplan editor for OpenForge EDA. Allows users to interactively
define die area, core area, place macros, regions, exclusions, IO pins,
and design power grids before running place-and-route.

Generates OpenROAD TCL output suitable for use with OpenLane / OpenROAD
flows.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    Qt,
    Signal,
    QPointF,
    QRectF,
    QSize,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QPainter,
    QPen,
    QPolygonF,
    QKeySequence,
    QFont,
    QIcon,
)
from PySide6.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QToolBar,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsPolygonItem,
    QGraphicsLineItem,
    QGraphicsSimpleTextItem,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QDoubleSpinBox,
    QSpinBox,
    QComboBox,
    QCheckBox,
    QPushButton,
    QLabel,
    QTabWidget,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QFileDialog,
    QMessageBox,
    QMenu,
    QGroupBox,
    QPlainTextEdit,
    QSizePolicy,
)


# ---------------------------------------------------------------------------
# Catppuccin Mocha palette
# ---------------------------------------------------------------------------

CAT_BASE = "#1e1e2e"
CAT_SURFACE = "#313244"
CAT_OVERLAY = "#45475a"
CAT_TEXT = "#cdd6f4"
CAT_SUBTEXT = "#a6adc8"
CAT_BLUE = "#89b4fa"
CAT_SAPPHIRE = "#74c7ec"
CAT_GREEN = "#a6e3a1"
CAT_YELLOW = "#f9e2af"
CAT_RED = "#f38ba8"
CAT_PEACH = "#fab387"
CAT_LAVENDER = "#b4befe"
CAT_MAUVE = "#cba6f7"

# Light theme fallbacks
LIGHT_BASE = "#ffffff"
LIGHT_SURFACE = "#eff1f5"
LIGHT_TEXT = "#4c4f69"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class DieArea:
    width: float = 100.0  # micrometers
    height: float = 100.0
    site: str = "unithd"


@dataclass
class CoreArea:
    margin: float = 5.0  # um from die edge


@dataclass
class FloorplanMacro:
    name: str
    module_type: str
    x: float
    y: float
    width: float
    height: float
    orientation: str = "R0"
    fixed: bool = True


@dataclass
class FloorplanRegion:
    name: str
    region_type: str  # density / keepout / fence / guide
    x: float
    y: float
    width: float
    height: float
    density: float = 0.5


@dataclass
class FloorplanIoPin:
    port_name: str
    direction: str  # input / output / inout
    side: str  # N / S / E / W
    position_um: float
    layer: str = "met3"


@dataclass
class PowerGrid:
    vdd_net: str = "VPWR"
    vss_net: str = "VGND"
    ring_layers: list[str] = field(default_factory=lambda: ["met4", "met5"])
    ring_width: float = 1.6
    ring_spacing: float = 1.6
    strap_layers: dict[str, dict] = field(default_factory=dict)


@dataclass
class Floorplan:
    die: DieArea = field(default_factory=DieArea)
    core: CoreArea = field(default_factory=CoreArea)
    macros: list[FloorplanMacro] = field(default_factory=list)
    regions: list[FloorplanRegion] = field(default_factory=list)
    io_pins: list[FloorplanIoPin] = field(default_factory=list)
    power_grid: PowerGrid = field(default_factory=PowerGrid)

    def to_dict(self) -> dict:
        return {
            "die": asdict(self.die),
            "core": asdict(self.core),
            "macros": [asdict(m) for m in self.macros],
            "regions": [asdict(r) for r in self.regions],
            "io_pins": [asdict(p) for p in self.io_pins],
            "power_grid": {
                "vdd_net": self.power_grid.vdd_net,
                "vss_net": self.power_grid.vss_net,
                "ring_layers": list(self.power_grid.ring_layers),
                "ring_width": self.power_grid.ring_width,
                "ring_spacing": self.power_grid.ring_spacing,
                "strap_layers": dict(self.power_grid.strap_layers),
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Floorplan":
        fp = cls()
        d = data.get("die", {})
        fp.die = DieArea(
            width=float(d.get("width", 100.0)),
            height=float(d.get("height", 100.0)),
            site=str(d.get("site", "unithd")),
        )
        c = data.get("core", {})
        fp.core = CoreArea(margin=float(c.get("margin", 5.0)))
        for m in data.get("macros", []):
            fp.macros.append(FloorplanMacro(**m))
        for r in data.get("regions", []):
            fp.regions.append(FloorplanRegion(**r))
        for p in data.get("io_pins", []):
            fp.io_pins.append(FloorplanIoPin(**p))
        pg = data.get("power_grid", {})
        fp.power_grid = PowerGrid(
            vdd_net=pg.get("vdd_net", "VPWR"),
            vss_net=pg.get("vss_net", "VGND"),
            ring_layers=list(pg.get("ring_layers", ["met4", "met5"])),
            ring_width=float(pg.get("ring_width", 1.6)),
            ring_spacing=float(pg.get("ring_spacing", 1.6)),
            strap_layers=dict(pg.get("strap_layers", {})),
        )
        return fp


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------


class NewFloorplanDialog(QDialog):
    """Dialog to define die / core area for a new floorplan."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Floorplan")
        self.setMinimumWidth(360)

        form = QFormLayout()

        self.die_w = QDoubleSpinBox()
        self.die_w.setRange(1.0, 100000.0)
        self.die_w.setValue(200.0)
        self.die_w.setSuffix(" um")
        self.die_w.setDecimals(3)
        form.addRow("Die width:", self.die_w)

        self.die_h = QDoubleSpinBox()
        self.die_h.setRange(1.0, 100000.0)
        self.die_h.setValue(200.0)
        self.die_h.setSuffix(" um")
        self.die_h.setDecimals(3)
        form.addRow("Die height:", self.die_h)

        self.core_margin = QDoubleSpinBox()
        self.core_margin.setRange(0.0, 10000.0)
        self.core_margin.setValue(10.0)
        self.core_margin.setSuffix(" um")
        self.core_margin.setDecimals(3)
        form.addRow("Core margin:", self.core_margin)

        self.site = QLineEdit("unithd")
        form.addRow("Site name:", self.site)

        self.utilization = QDoubleSpinBox()
        self.utilization.setRange(0.05, 0.95)
        self.utilization.setSingleStep(0.05)
        self.utilization.setValue(0.5)
        form.addRow("Utilization target:", self.utilization)

        layout = QVBoxLayout(self)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        return {
            "die_width": self.die_w.value(),
            "die_height": self.die_h.value(),
            "core_margin": self.core_margin.value(),
            "site": self.site.text().strip() or "unithd",
            "utilization": self.utilization.value(),
        }


class AddMacroDialog(QDialog):
    """Dialog to add or edit a manually placed macro."""

    ORIENTATIONS = ["R0", "R90", "R180", "R270", "MX", "MY", "MXR90", "MYR90"]

    def __init__(
        self,
        parent: QWidget | None = None,
        macro: FloorplanMacro | None = None,
        module_types: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Macro" if macro is None else "Edit Macro")
        self.setMinimumWidth(360)

        form = QFormLayout()

        self.name = QLineEdit(macro.name if macro else "macro_inst")
        form.addRow("Instance name:", self.name)

        self.module = QComboBox()
        self.module.setEditable(True)
        for mod in module_types or ["sky130_sram_1kbyte", "PLL", "io_block"]:
            self.module.addItem(mod)
        if macro:
            self.module.setCurrentText(macro.module_type)
        form.addRow("Module type:", self.module)

        self.x = QDoubleSpinBox()
        self.x.setRange(-1e6, 1e6)
        self.x.setDecimals(3)
        self.x.setSuffix(" um")
        if macro:
            self.x.setValue(macro.x)
        form.addRow("X position:", self.x)

        self.y = QDoubleSpinBox()
        self.y.setRange(-1e6, 1e6)
        self.y.setDecimals(3)
        self.y.setSuffix(" um")
        if macro:
            self.y.setValue(macro.y)
        form.addRow("Y position:", self.y)

        self.w = QDoubleSpinBox()
        self.w.setRange(0.1, 1e6)
        self.w.setDecimals(3)
        self.w.setSuffix(" um")
        self.w.setValue(macro.width if macro else 30.0)
        form.addRow("Width:", self.w)

        self.h = QDoubleSpinBox()
        self.h.setRange(0.1, 1e6)
        self.h.setDecimals(3)
        self.h.setSuffix(" um")
        self.h.setValue(macro.height if macro else 30.0)
        form.addRow("Height:", self.h)

        self.orient = QComboBox()
        self.orient.addItems(self.ORIENTATIONS)
        if macro:
            self.orient.setCurrentText(macro.orientation)
        form.addRow("Orientation:", self.orient)

        self.fixed = QCheckBox("Fixed (locked) placement")
        self.fixed.setChecked(macro.fixed if macro else True)
        form.addRow("", self.fixed)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def to_macro(self) -> FloorplanMacro:
        return FloorplanMacro(
            name=self.name.text().strip() or "macro_inst",
            module_type=self.module.currentText().strip(),
            x=self.x.value(),
            y=self.y.value(),
            width=self.w.value(),
            height=self.h.value(),
            orientation=self.orient.currentText(),
            fixed=self.fixed.isChecked(),
        )


class AddRegionDialog(QDialog):
    """Dialog to define a region constraint or exclusion zone."""

    REGION_TYPES = ["density", "keepout", "fence", "guide"]

    def __init__(
        self,
        parent: QWidget | None = None,
        region: FloorplanRegion | None = None,
        default_type: str = "density",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Region" if region is None else "Edit Region")
        self.setMinimumWidth(360)

        form = QFormLayout()

        self.name = QLineEdit(region.name if region else "region_1")
        form.addRow("Region name:", self.name)

        self.region_type = QComboBox()
        self.region_type.addItems(self.REGION_TYPES)
        if region:
            self.region_type.setCurrentText(region.region_type)
        else:
            self.region_type.setCurrentText(default_type)
        form.addRow("Type:", self.region_type)

        self.x = QDoubleSpinBox()
        self.x.setRange(-1e6, 1e6)
        self.x.setDecimals(3)
        self.x.setSuffix(" um")
        if region:
            self.x.setValue(region.x)
        form.addRow("X:", self.x)

        self.y = QDoubleSpinBox()
        self.y.setRange(-1e6, 1e6)
        self.y.setDecimals(3)
        self.y.setSuffix(" um")
        if region:
            self.y.setValue(region.y)
        form.addRow("Y:", self.y)

        self.w = QDoubleSpinBox()
        self.w.setRange(0.1, 1e6)
        self.w.setDecimals(3)
        self.w.setSuffix(" um")
        self.w.setValue(region.width if region else 20.0)
        form.addRow("Width:", self.w)

        self.h = QDoubleSpinBox()
        self.h.setRange(0.1, 1e6)
        self.h.setDecimals(3)
        self.h.setSuffix(" um")
        self.h.setValue(region.height if region else 20.0)
        form.addRow("Height:", self.h)

        self.density = QDoubleSpinBox()
        self.density.setRange(0.0, 1.0)
        self.density.setSingleStep(0.05)
        self.density.setDecimals(3)
        self.density.setValue(region.density if region else 0.5)
        form.addRow("Density:", self.density)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def to_region(self) -> FloorplanRegion:
        return FloorplanRegion(
            name=self.name.text().strip() or "region",
            region_type=self.region_type.currentText(),
            x=self.x.value(),
            y=self.y.value(),
            width=self.w.value(),
            height=self.h.value(),
            density=self.density.value(),
        )


class PowerGridWizard(QDialog):
    """Wizard for designing the power distribution network."""

    LAYER_OPTIONS = ["met1", "met2", "met3", "met4", "met5"]

    def __init__(
        self,
        parent: QWidget | None = None,
        grid: PowerGrid | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Power Grid Wizard")
        self.setMinimumWidth(480)
        self._preview_callback = None

        form = QFormLayout()

        self.vdd = QLineEdit(grid.vdd_net if grid else "VPWR")
        form.addRow("VDD net:", self.vdd)

        self.vss = QLineEdit(grid.vss_net if grid else "VGND")
        form.addRow("VSS net:", self.vss)

        self.ring_layer1 = QComboBox()
        self.ring_layer1.addItems(self.LAYER_OPTIONS)
        self.ring_layer1.setCurrentText(
            grid.ring_layers[0] if grid and grid.ring_layers else "met4"
        )
        form.addRow("Ring layer 1:", self.ring_layer1)

        self.ring_layer2 = QComboBox()
        self.ring_layer2.addItems(self.LAYER_OPTIONS)
        self.ring_layer2.setCurrentText(
            grid.ring_layers[1] if grid and len(grid.ring_layers) > 1 else "met5"
        )
        form.addRow("Ring layer 2:", self.ring_layer2)

        self.ring_width = QDoubleSpinBox()
        self.ring_width.setRange(0.05, 100.0)
        self.ring_width.setDecimals(3)
        self.ring_width.setValue(grid.ring_width if grid else 1.6)
        self.ring_width.setSuffix(" um")
        form.addRow("Ring width:", self.ring_width)

        self.ring_spacing = QDoubleSpinBox()
        self.ring_spacing.setRange(0.05, 100.0)
        self.ring_spacing.setDecimals(3)
        self.ring_spacing.setValue(grid.ring_spacing if grid else 1.6)
        self.ring_spacing.setSuffix(" um")
        form.addRow("Ring spacing:", self.ring_spacing)

        # Strap layer settings
        strap_box = QGroupBox("Power Straps")
        strap_form = QFormLayout(strap_box)

        self.strap_met1 = QCheckBox("Enable met1 follow-pin straps")
        self.strap_met1.setChecked(True)
        strap_form.addRow(self.strap_met1)

        self.strap_met1_width = QDoubleSpinBox()
        self.strap_met1_width.setRange(0.05, 100.0)
        self.strap_met1_width.setDecimals(3)
        self.strap_met1_width.setValue(0.48)
        self.strap_met1_width.setSuffix(" um")
        strap_form.addRow("met1 width:", self.strap_met1_width)

        self.strap_met1_pitch = QDoubleSpinBox()
        self.strap_met1_pitch.setRange(0.1, 1000.0)
        self.strap_met1_pitch.setDecimals(3)
        self.strap_met1_pitch.setValue(6.0)
        self.strap_met1_pitch.setSuffix(" um")
        strap_form.addRow("met1 pitch:", self.strap_met1_pitch)

        self.strap_met4 = QCheckBox("Enable met4 vertical straps")
        self.strap_met4.setChecked(True)
        strap_form.addRow(self.strap_met4)

        self.strap_met4_width = QDoubleSpinBox()
        self.strap_met4_width.setRange(0.05, 100.0)
        self.strap_met4_width.setDecimals(3)
        self.strap_met4_width.setValue(1.6)
        self.strap_met4_width.setSuffix(" um")
        strap_form.addRow("met4 width:", self.strap_met4_width)

        self.strap_met4_pitch = QDoubleSpinBox()
        self.strap_met4_pitch.setRange(0.1, 10000.0)
        self.strap_met4_pitch.setDecimals(3)
        self.strap_met4_pitch.setValue(27.2)
        self.strap_met4_pitch.setSuffix(" um")
        strap_form.addRow("met4 pitch:", self.strap_met4_pitch)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(strap_box)

        preview_btn = QPushButton("Generate Preview")
        preview_btn.clicked.connect(self._on_preview)
        layout.addWidget(preview_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_preview_callback(self, callback) -> None:
        self._preview_callback = callback

    def _on_preview(self) -> None:
        if self._preview_callback is not None:
            self._preview_callback(self.to_power_grid())

    def to_power_grid(self) -> PowerGrid:
        pg = PowerGrid(
            vdd_net=self.vdd.text().strip() or "VPWR",
            vss_net=self.vss.text().strip() or "VGND",
            ring_layers=[
                self.ring_layer1.currentText(),
                self.ring_layer2.currentText(),
            ],
            ring_width=self.ring_width.value(),
            ring_spacing=self.ring_spacing.value(),
        )
        if self.strap_met1.isChecked():
            pg.strap_layers["met1"] = {
                "width": self.strap_met1_width.value(),
                "pitch": self.strap_met1_pitch.value(),
                "direction": "horizontal",
                "followpins": True,
            }
        if self.strap_met4.isChecked():
            pg.strap_layers["met4"] = {
                "width": self.strap_met4_width.value(),
                "pitch": self.strap_met4_pitch.value(),
                "direction": "vertical",
                "followpins": False,
            }
        return pg


class PinPlacementDialog(QDialog):
    """Dialog for assigning IO pin positions on the die boundary."""

    MODES = ["Manual", "Auto-distribute", "Side-grouped"]
    SIDES = ["N", "S", "E", "W"]
    DIRECTIONS = ["input", "output", "inout"]

    def __init__(
        self,
        parent: QWidget | None = None,
        existing_pins: list[FloorplanIoPin] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("IO Pin Placement")
        self.setMinimumSize(640, 420)

        layout = QVBoxLayout(self)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.mode = QComboBox()
        self.mode.addItems(self.MODES)
        mode_row.addWidget(self.mode)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Port Name", "Direction", "Side", "Position (um)", "Layer"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.table)

        if existing_pins:
            for pin in existing_pins:
                self._add_row(pin)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Pin")
        add_btn.clicked.connect(lambda: self._add_row())
        btn_row.addWidget(add_btn)
        rm_btn = QPushButton("Remove Selected")
        rm_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(rm_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_row(self, pin: FloorplanIoPin | None = None) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        name_item = QTableWidgetItem(pin.port_name if pin else f"pin_{row}")
        self.table.setItem(row, 0, name_item)

        dir_combo = QComboBox()
        dir_combo.addItems(self.DIRECTIONS)
        if pin:
            dir_combo.setCurrentText(pin.direction)
        self.table.setCellWidget(row, 1, dir_combo)

        side_combo = QComboBox()
        side_combo.addItems(self.SIDES)
        if pin:
            side_combo.setCurrentText(pin.side)
        self.table.setCellWidget(row, 2, side_combo)

        pos_spin = QDoubleSpinBox()
        pos_spin.setRange(0.0, 1e6)
        pos_spin.setDecimals(3)
        pos_spin.setValue(pin.position_um if pin else 10.0)
        self.table.setCellWidget(row, 3, pos_spin)

        layer_combo = QComboBox()
        layer_combo.addItems(["met1", "met2", "met3", "met4", "met5"])
        if pin:
            layer_combo.setCurrentText(pin.layer)
        else:
            layer_combo.setCurrentText("met3")
        self.table.setCellWidget(row, 4, layer_combo)

    def _remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def to_pins(self) -> list[FloorplanIoPin]:
        pins: list[FloorplanIoPin] = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            name = name_item.text().strip() if name_item else f"pin_{row}"
            direction = self.table.cellWidget(row, 1).currentText()
            side = self.table.cellWidget(row, 2).currentText()
            pos = self.table.cellWidget(row, 3).value()
            layer = self.table.cellWidget(row, 4).currentText()
            pins.append(
                FloorplanIoPin(
                    port_name=name,
                    direction=direction,
                    side=side,
                    position_um=pos,
                    layer=layer,
                )
            )
        return pins

    def selected_mode(self) -> str:
        return self.mode.currentText()


# ---------------------------------------------------------------------------
# Graphics items
# ---------------------------------------------------------------------------


# Custom Z-values to ensure proper draw order.
Z_DIE = 0
Z_CORE = 1
Z_REGION = 5
Z_EXCLUSION = 6
Z_POWER = 8
Z_MACRO = 10
Z_PIN = 12
Z_LABEL = 20


class _BaseRectItem(QGraphicsRectItem):
    """Base item that knows about its data model object."""

    def __init__(self, model_obj, kind: str, scale: float):
        super().__init__()
        self.model_obj = model_obj
        self.kind = kind
        self.scale_factor = scale
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)


class MacroItem(_BaseRectItem):
    def __init__(self, macro: FloorplanMacro, scale: float):
        super().__init__(macro, "macro", scale)
        self.setRect(0, 0, macro.width * scale, macro.height * scale)
        self.setPos(macro.x * scale, macro.y * scale)
        pen = QPen(QColor(CAT_GREEN))
        pen.setWidthF(1.5)
        self.setPen(pen)
        self.setBrush(QBrush(QColor(166, 227, 161, 90)))
        self.setZValue(Z_MACRO)
        self._label = QGraphicsSimpleTextItem(macro.name, self)
        font = QFont()
        font.setPointSizeF(8.0)
        self._label.setFont(font)
        self._label.setBrush(QBrush(QColor(CAT_TEXT)))
        self._label.setPos(2, 2)
        self._label.setZValue(Z_LABEL)
        if macro.fixed:
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)


class RegionItem(_BaseRectItem):
    def __init__(self, region: FloorplanRegion, scale: float):
        super().__init__(region, "region", scale)
        self.setRect(0, 0, region.width * scale, region.height * scale)
        self.setPos(region.x * scale, region.y * scale)
        if region.region_type == "keepout":
            self.setBrush(QBrush(QColor(243, 139, 168, 80)))
            pen = QPen(QColor(CAT_RED))
        else:
            self.setBrush(QBrush(QColor(249, 226, 175, 70)))
            pen = QPen(QColor(CAT_YELLOW))
        pen.setWidthF(1.0)
        pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.setZValue(Z_REGION if region.region_type != "keepout" else Z_EXCLUSION)
        self._label = QGraphicsSimpleTextItem(
            f"{region.name} [{region.region_type}]", self
        )
        font = QFont()
        font.setPointSizeF(7.5)
        self._label.setFont(font)
        self._label.setBrush(QBrush(QColor(CAT_TEXT)))
        self._label.setPos(2, 2)
        self._label.setZValue(Z_LABEL)


class IoPinItem(QGraphicsPolygonItem):
    """Triangular pin marker on the die boundary."""

    def __init__(self, pin: FloorplanIoPin, die: DieArea, scale: float):
        super().__init__()
        self.model_obj = pin
        self.kind = "pin"
        self.scale_factor = scale
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

        size = 4.0
        tri = QPolygonF()
        if pin.side == "N":
            cx = pin.position_um * scale
            cy = die.height * scale
            tri.append(QPointF(cx, cy))
            tri.append(QPointF(cx - size, cy + size * 1.5))
            tri.append(QPointF(cx + size, cy + size * 1.5))
        elif pin.side == "S":
            cx = pin.position_um * scale
            cy = 0.0
            tri.append(QPointF(cx, cy))
            tri.append(QPointF(cx - size, cy - size * 1.5))
            tri.append(QPointF(cx + size, cy - size * 1.5))
        elif pin.side == "E":
            cx = die.width * scale
            cy = pin.position_um * scale
            tri.append(QPointF(cx, cy))
            tri.append(QPointF(cx + size * 1.5, cy - size))
            tri.append(QPointF(cx + size * 1.5, cy + size))
        else:  # W
            cx = 0.0
            cy = pin.position_um * scale
            tri.append(QPointF(cx, cy))
            tri.append(QPointF(cx - size * 1.5, cy - size))
            tri.append(QPointF(cx - size * 1.5, cy + size))
        self.setPolygon(tri)

        if pin.direction == "input":
            color = QColor(CAT_BLUE)
        elif pin.direction == "output":
            color = QColor(CAT_GREEN)
        else:
            color = QColor(CAT_MAUVE)
        self.setBrush(QBrush(color))
        self.setPen(QPen(color.darker(150), 0.8))
        self.setZValue(Z_PIN)


# ---------------------------------------------------------------------------
# Graphics scene / view
# ---------------------------------------------------------------------------


class FloorplanScene(QGraphicsScene):
    """Scene that holds floorplan graphics. Y axis is flipped (chip-style)."""

    item_moved = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(QColor(CAT_BASE)))
        self.scale_factor = 4.0  # pixels per micrometer
        self.snap_grid = 1.0  # in micrometers
        self.snap_enabled = True
        self.die_item: QGraphicsRectItem | None = None
        self.core_item: QGraphicsRectItem | None = None
        self._power_items: list[QGraphicsItem] = []

    def set_snap_enabled(self, enabled: bool) -> None:
        self.snap_enabled = enabled

    def snap(self, value_um: float) -> float:
        if not self.snap_enabled or self.snap_grid <= 0:
            return value_um
        return round(value_um / self.snap_grid) * self.snap_grid

    def clear_all(self) -> None:
        self.clear()
        self.die_item = None
        self.core_item = None
        self._power_items.clear()

    def draw_die(self, die: DieArea, core: CoreArea) -> None:
        s = self.scale_factor
        die_pen = QPen(QColor(CAT_BLUE))
        die_pen.setWidthF(2.5)
        self.die_item = self.addRect(
            0, 0, die.width * s, die.height * s, die_pen, QBrush(Qt.BrushStyle.NoBrush)
        )
        self.die_item.setZValue(Z_DIE)

        core_pen = QPen(QColor(CAT_SAPPHIRE))
        core_pen.setWidthF(1.5)
        core_pen.setStyle(Qt.PenStyle.DashLine)
        self.core_item = self.addRect(
            core.margin * s,
            core.margin * s,
            (die.width - 2 * core.margin) * s,
            (die.height - 2 * core.margin) * s,
            core_pen,
            QBrush(Qt.BrushStyle.NoBrush),
        )
        self.core_item.setZValue(Z_CORE)

    def draw_power_grid(self, fp: Floorplan) -> None:
        for it in self._power_items:
            self.removeItem(it)
        self._power_items.clear()

        s = self.scale_factor
        die = fp.die
        core = fp.core
        pen_ring = QPen(QColor(CAT_PEACH))
        pen_ring.setWidthF(2.0)

        # Power ring around core boundary
        ring = self.addRect(
            core.margin * s,
            core.margin * s,
            (die.width - 2 * core.margin) * s,
            (die.height - 2 * core.margin) * s,
            pen_ring,
            QBrush(Qt.BrushStyle.NoBrush),
        )
        ring.setZValue(Z_POWER)
        self._power_items.append(ring)

        pen_strap = QPen(QColor(CAT_PEACH))
        pen_strap.setWidthF(1.0)
        pen_strap.setStyle(Qt.PenStyle.DotLine)
        for layer, info in fp.power_grid.strap_layers.items():
            pitch = float(info.get("pitch", 10.0))
            direction = info.get("direction", "horizontal")
            if pitch <= 0:
                continue
            if direction == "horizontal":
                y = core.margin
                while y <= die.height - core.margin:
                    line = QGraphicsLineItem(
                        core.margin * s, y * s, (die.width - core.margin) * s, y * s
                    )
                    line.setPen(pen_strap)
                    line.setZValue(Z_POWER)
                    self.addItem(line)
                    self._power_items.append(line)
                    y += pitch
            else:
                x = core.margin
                while x <= die.width - core.margin:
                    line = QGraphicsLineItem(
                        x * s, core.margin * s, x * s, (die.height - core.margin) * s
                    )
                    line.setPen(pen_strap)
                    line.setZValue(Z_POWER)
                    self.addItem(line)
                    self._power_items.append(line)
                    x += pitch


class FloorplanView(QGraphicsView):
    """Graphics view with zoom + pan support."""

    def __init__(self, scene: FloorplanScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        # Flip Y axis so origin is bottom-left like a chip
        self.scale(1.0, -1.0)
        self._zoom = 1.0

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        self.scale(factor, factor)
        self._zoom *= factor

    def zoom_in(self) -> None:
        self.scale(1.2, 1.2)
        self._zoom *= 1.2

    def zoom_out(self) -> None:
        self.scale(1 / 1.2, 1 / 1.2)
        self._zoom /= 1.2

    def zoom_fit(self) -> None:
        if self.scene() is None:
            return
        rect = self.scene().itemsBoundingRect()
        if rect.isEmpty():
            return
        self.fitInView(rect.adjusted(-20, -20, 20, 20), Qt.AspectRatioMode.KeepAspectRatio)
        # Re-apply Y flip after fit
        tr = self.transform()
        if tr.m22() > 0:
            self.scale(1.0, -1.0)


# ---------------------------------------------------------------------------
# Properties side panel
# ---------------------------------------------------------------------------


class PropertiesPanel(QWidget):
    """Right-hand side panel showing properties for the selected item."""

    properties_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = None
        self._building = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.title = QLabel("No selection")
        self.title.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.title)

        self.form_widget = QWidget()
        self.form = QFormLayout(self.form_widget)
        layout.addWidget(self.form_widget)
        layout.addStretch()

        self._fields: dict[str, QWidget] = {}

    def clear(self) -> None:
        self._current = None
        self.title.setText("No selection")
        while self.form.rowCount():
            self.form.removeRow(0)
        self._fields.clear()

    def show_object(self, obj) -> None:
        self.clear()
        self._current = obj
        self._building = True
        if isinstance(obj, FloorplanMacro):
            self.title.setText(f"Macro: {obj.name}")
            self._add_str("name", obj.name)
            self._add_str("module_type", obj.module_type)
            self._add_float("x", obj.x)
            self._add_float("y", obj.y)
            self._add_float("width", obj.width)
            self._add_float("height", obj.height)
            self._add_combo(
                "orientation",
                obj.orientation,
                ["R0", "R90", "R180", "R270", "MX", "MY", "MXR90", "MYR90"],
            )
            self._add_bool("fixed", obj.fixed)
        elif isinstance(obj, FloorplanRegion):
            self.title.setText(f"Region: {obj.name}")
            self._add_str("name", obj.name)
            self._add_combo(
                "region_type", obj.region_type, ["density", "keepout", "fence", "guide"]
            )
            self._add_float("x", obj.x)
            self._add_float("y", obj.y)
            self._add_float("width", obj.width)
            self._add_float("height", obj.height)
            self._add_float("density", obj.density)
        elif isinstance(obj, FloorplanIoPin):
            self.title.setText(f"IO Pin: {obj.port_name}")
            self._add_str("port_name", obj.port_name)
            self._add_combo("direction", obj.direction, ["input", "output", "inout"])
            self._add_combo("side", obj.side, ["N", "S", "E", "W"])
            self._add_float("position_um", obj.position_um)
            self._add_str("layer", obj.layer)
        self._building = False

    def _add_str(self, key: str, value: str) -> None:
        edit = QLineEdit(str(value))
        edit.editingFinished.connect(lambda k=key, w=edit: self._set_attr(k, w.text()))
        self.form.addRow(key + ":", edit)
        self._fields[key] = edit

    def _add_float(self, key: str, value: float) -> None:
        spin = QDoubleSpinBox()
        spin.setRange(-1e6, 1e6)
        spin.setDecimals(3)
        spin.setValue(float(value))
        spin.valueChanged.connect(lambda v, k=key: self._set_attr(k, float(v)))
        self.form.addRow(key + ":", spin)
        self._fields[key] = spin

    def _add_combo(self, key: str, value: str, options: list[str]) -> None:
        combo = QComboBox()
        combo.addItems(options)
        combo.setCurrentText(value)
        combo.currentTextChanged.connect(lambda v, k=key: self._set_attr(k, v))
        self.form.addRow(key + ":", combo)
        self._fields[key] = combo

    def _add_bool(self, key: str, value: bool) -> None:
        cb = QCheckBox()
        cb.setChecked(bool(value))
        cb.toggled.connect(lambda v, k=key: self._set_attr(k, bool(v)))
        self.form.addRow(key + ":", cb)
        self._fields[key] = cb

    def _set_attr(self, key: str, value) -> None:
        if self._building or self._current is None:
            return
        if hasattr(self._current, key):
            setattr(self._current, key, value)
            self.properties_changed.emit()


# ---------------------------------------------------------------------------
# TCL generator
# ---------------------------------------------------------------------------


class TclGenerator:
    """Convert a Floorplan into OpenROAD TCL commands."""

    @staticmethod
    def generate(fp: Floorplan) -> str:
        lines: list[str] = []
        lines.append("# Floorplan generated by OpenForge Floorplan Editor")
        lines.append("# DO NOT EDIT BY HAND - regenerate from the Floorplan Editor panel")
        lines.append("")
        die = fp.die
        core = fp.core
        die_area = f"{{0 0 {die.width:g} {die.height:g}}}"
        core_area = (
            f"{{{core.margin:g} {core.margin:g} "
            f"{die.width - core.margin:g} {die.height - core.margin:g}}}"
        )
        lines.append(
            f"initialize_floorplan -die_area {die_area} \\"
        )
        lines.append(f"                     -core_area {core_area} \\")
        lines.append(f"                     -site {die.site}")
        lines.append("")
        lines.append("make_tracks")
        lines.append("")

        if fp.macros:
            lines.append("# Manual macro placement")
            for m in fp.macros:
                status = "FIXED" if m.fixed else "PLACED"
                lines.append(
                    f"place_cell -inst_name {m.name} -origin {{{m.x:g} {m.y:g}}} "
                    f"-orient {m.orientation} -status {status}"
                )
            lines.append("")

        if fp.regions:
            lines.append("# Region constraints")
            for r in fp.regions:
                if r.region_type == "density":
                    lines.append(
                        f"set_placement_density -region {{{r.x:g} {r.y:g} "
                        f"{r.x + r.width:g} {r.y + r.height:g}}} "
                        f"-density {r.density:g}"
                    )
                elif r.region_type == "keepout":
                    lines.append(
                        f"create_blockage -region {{{r.x:g} {r.y:g} "
                        f"{r.x + r.width:g} {r.y + r.height:g}}}"
                    )
                elif r.region_type == "fence":
                    lines.append(
                        f"create_fence -name {r.name} -region {{{r.x:g} {r.y:g} "
                        f"{r.x + r.width:g} {r.y + r.height:g}}}"
                    )
                else:
                    lines.append(
                        f"create_guide -name {r.name} -region {{{r.x:g} {r.y:g} "
                        f"{r.x + r.width:g} {r.y + r.height:g}}}"
                    )
            lines.append("")

        # Power network
        pg = fp.power_grid
        lines.append("# Global connections")
        lines.append(
            f"add_global_connection -net {pg.vdd_net} -inst_pattern .* -pin_pattern {pg.vdd_net} -power"
        )
        lines.append(
            f"add_global_connection -net {pg.vss_net} -inst_pattern .* -pin_pattern {pg.vss_net} -ground"
        )
        lines.append("global_connect")
        lines.append("")

        lines.append("# Power grid")
        lines.append(
            f"set_voltage_domain -name CORE -power {pg.vdd_net} -ground {pg.vss_net}"
        )
        lines.append("define_pdn_grid -name top_grid -voltage_domain CORE")
        ring_layers = " ".join(pg.ring_layers)
        lines.append(
            f"add_pdn_ring -grid top_grid -layers {{{ring_layers}}} "
            f"-widths {pg.ring_width:g} -spacings {pg.ring_spacing:g} \\"
        )
        lines.append(
            f"             -core_offsets {{2 2 2 2}}"
        )
        for layer, info in pg.strap_layers.items():
            width = info.get("width", 0.48)
            pitch = info.get("pitch", 6.0)
            followpins = info.get("followpins", False)
            extra = " -followpins" if followpins else " -snap_to_grid"
            lines.append(
                f"add_pdn_stripe -grid top_grid -layer {layer} -width {width:g} "
                f"-pitch {pitch:g} -offset 0{extra}"
            )
        lines.append("")

        if fp.io_pins:
            lines.append("# Pin placement")
            for pin in fp.io_pins:
                if pin.side == "N":
                    loc = f"{{{pin.position_um:g} {fp.die.height:g}}}"
                elif pin.side == "S":
                    loc = f"{{{pin.position_um:g} 0}}"
                elif pin.side == "E":
                    loc = f"{{{fp.die.width:g} {pin.position_um:g}}}"
                else:
                    loc = f"{{0 {pin.position_um:g}}}"
                lines.append(
                    f"place_pin -pin_name {pin.port_name} -layer {pin.layer} "
                    f"-location {loc} -force_to_die_boundary"
                )
            lines.append("")

        lines.append("# End of generated floorplan")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# DEF loader (very loose, best-effort)
# ---------------------------------------------------------------------------


class DefLoader:
    """Best-effort DEF parser to bootstrap a floorplan."""

    @staticmethod
    def load(path: Path) -> Floorplan:
        fp = Floorplan()
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return fp
        units = 1000.0
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("UNITS DISTANCE MICRONS"):
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        units = float(parts[3].rstrip(";"))
                    except ValueError:
                        pass
            elif line.startswith("DIEAREA"):
                # DIEAREA ( x1 y1 ) ( x2 y2 ) ;
                nums: list[float] = []
                for token in line.replace("(", " ").replace(")", " ").split():
                    try:
                        nums.append(float(token))
                    except ValueError:
                        pass
                if len(nums) >= 4:
                    x1, y1, x2, y2 = nums[:4]
                    fp.die.width = (x2 - x1) / units
                    fp.die.height = (y2 - y1) / units
        return fp


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class FloorplanEditorPanel(QDockWidget):
    """Visual floorplan editor dock widget."""

    floorplan_changed = Signal()
    tcl_generated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Floorplan Editor")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setObjectName("FloorplanEditorPanel")

        self.floorplan = Floorplan()
        self._dark = True
        self._module_types: list[str] = ["sky130_sram_1kbyte", "PLL", "io_block"]
        self._current_path: Path | None = None

        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Canvas (must be built BEFORE toolbar since toolbar connects to view actions)
        self.scene = FloorplanScene(self)
        self.view = FloorplanView(self.scene, self)

        # Toolbar
        self.toolbar = QToolBar("Floorplan Tools")
        self.toolbar.setIconSize(QSize(18, 18))
        self._build_toolbar()
        root.addWidget(self.toolbar)

        # Main horizontal splitter: canvas | properties
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # Canvas container
        canvas_widget = QWidget()
        canvas_layout = QVBoxLayout(canvas_widget)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.addWidget(self.view)
        self.status = QLabel("Ready")
        self.status.setStyleSheet("padding: 4px;")
        canvas_layout.addWidget(self.status)
        self.splitter.addWidget(canvas_widget)

        # Right tabs: properties, list, TCL preview
        right_tabs = QTabWidget()
        self.props_panel = PropertiesPanel()
        self.props_panel.properties_changed.connect(self._on_properties_changed)
        right_tabs.addTab(self.props_panel, "Properties")

        self.item_list = QListWidget()
        self.item_list.itemSelectionChanged.connect(self._on_list_selection)
        right_tabs.addTab(self.item_list, "Items")

        self.tcl_preview = QPlainTextEdit()
        self.tcl_preview.setReadOnly(True)
        font = QFont("Consolas", 9)
        self.tcl_preview.setFont(font)
        right_tabs.addTab(self.tcl_preview, "TCL Preview")

        self.splitter.addWidget(right_tabs)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([800, 280])
        root.addWidget(self.splitter, 1)

        self.setWidget(container)

        self.scene.selectionChanged.connect(self._on_scene_selection)

        # Initialize with a default floorplan so the canvas isn't empty
        self._initialize_default()
        self.set_theme(True)

    # ------------------------------------------------------------------
    # Toolbar construction
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        tb = self.toolbar

        new_act = QAction("New", self)
        new_act.setToolTip("New Floorplan")
        new_act.triggered.connect(self._action_new)
        tb.addAction(new_act)

        load_act = QAction("Load DEF", self)
        load_act.setToolTip("Load DEF file as starting point")
        load_act.triggered.connect(self._action_load_def)
        tb.addAction(load_act)

        save_act = QAction("Save", self)
        save_act.setShortcut(QKeySequence("Ctrl+S"))
        save_act.setToolTip("Save floorplan as JSON")
        save_act.triggered.connect(self._action_save)
        tb.addAction(save_act)

        open_act = QAction("Open", self)
        open_act.setToolTip("Open floorplan JSON")
        open_act.triggered.connect(self._action_open)
        tb.addAction(open_act)

        tb.addSeparator()

        region_act = QAction("Region", self)
        region_act.setToolTip("Add region constraint")
        region_act.triggered.connect(self._action_add_region)
        tb.addAction(region_act)

        excl_act = QAction("Exclusion", self)
        excl_act.setToolTip("Add exclusion zone")
        excl_act.triggered.connect(self._action_add_exclusion)
        tb.addAction(excl_act)

        macro_act = QAction("Macro", self)
        macro_act.setToolTip("Add macro")
        macro_act.triggered.connect(self._action_add_macro)
        tb.addAction(macro_act)

        pin_act = QAction("IO Pin", self)
        pin_act.setToolTip("Add / edit IO pins")
        pin_act.triggered.connect(self._action_pins)
        tb.addAction(pin_act)

        tb.addSeparator()

        pdn_act = QAction("Power Grid", self)
        pdn_act.setToolTip("Power grid wizard")
        pdn_act.triggered.connect(self._action_power_grid)
        tb.addAction(pdn_act)

        autopin_act = QAction("Auto-Pin", self)
        autopin_act.setToolTip("Auto-distribute IO pins along die boundary")
        autopin_act.triggered.connect(self._action_auto_pins)
        tb.addAction(autopin_act)

        tb.addSeparator()

        gen_act = QAction("Generate TCL", self)
        gen_act.setToolTip("Generate OpenROAD TCL")
        gen_act.triggered.connect(self._action_generate_tcl)
        tb.addAction(gen_act)

        export_act = QAction("Export TCL...", self)
        export_act.setToolTip("Export OpenROAD TCL to file")
        export_act.triggered.connect(self._action_export_tcl)
        tb.addAction(export_act)

        tb.addSeparator()

        zfit = QAction("Zoom Fit", self)
        zfit.triggered.connect(self.view.zoom_fit)
        tb.addAction(zfit)
        zin = QAction("Zoom In", self)
        zin.triggered.connect(self.view.zoom_in)
        tb.addAction(zin)
        zout = QAction("Zoom Out", self)
        zout.triggered.connect(self.view.zoom_out)
        tb.addAction(zout)

        self.snap_act = QAction("Snap", self)
        self.snap_act.setCheckable(True)
        self.snap_act.setChecked(True)
        self.snap_act.toggled.connect(self.scene.set_snap_enabled)
        tb.addAction(self.snap_act)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_theme(self, dark: bool) -> None:
        self._dark = dark
        if dark:
            base = CAT_BASE
            surface = CAT_SURFACE
            text = CAT_TEXT
        else:
            base = LIGHT_BASE
            surface = LIGHT_SURFACE
            text = LIGHT_TEXT
        self.setStyleSheet(
            f"""
            QDockWidget {{ color: {text}; }}
            QWidget {{ background-color: {base}; color: {text}; }}
            QToolBar {{ background-color: {surface}; border: none; padding: 4px; spacing: 4px; }}
            QToolBar QToolButton {{
                background-color: {surface};
                color: {text};
                padding: 4px 8px;
                border-radius: 4px;
            }}
            QToolBar QToolButton:hover {{ background-color: {CAT_OVERLAY}; }}
            QListWidget, QPlainTextEdit, QLineEdit, QDoubleSpinBox, QComboBox, QSpinBox, QTableWidget {{
                background-color: {surface};
                color: {text};
                border: 1px solid {CAT_OVERLAY};
                border-radius: 3px;
            }}
            QLabel {{ color: {text}; }}
            QGroupBox {{ color: {text}; border: 1px solid {CAT_OVERLAY}; margin-top: 10px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
            QTabWidget::pane {{ border: 1px solid {CAT_OVERLAY}; }}
            QTabBar::tab {{ background: {surface}; color: {text}; padding: 6px 10px; }}
            QTabBar::tab:selected {{ background: {CAT_OVERLAY}; }}
            """
        )
        if dark:
            self.scene.setBackgroundBrush(QBrush(QColor(CAT_BASE)))
        else:
            self.scene.setBackgroundBrush(QBrush(QColor(LIGHT_BASE)))

    def load_def(self, def_path: Path) -> None:
        fp = DefLoader.load(Path(def_path))
        self.floorplan = fp
        self._rebuild_scene()
        self._rebuild_list()
        self.view.zoom_fit()
        self.status.setText(f"Loaded DEF: {def_path}")
        self.floorplan_changed.emit()

    def export_tcl(self) -> str:
        tcl = TclGenerator.generate(self.floorplan)
        self.tcl_preview.setPlainText(tcl)
        self.tcl_generated.emit(tcl)
        return tcl

    def clear(self) -> None:
        self.floorplan = Floorplan()
        self.scene.clear_all()
        self.props_panel.clear()
        self.item_list.clear()
        self.tcl_preview.clear()
        self.status.setText("Cleared")
        self.floorplan_changed.emit()

    def set_module_types(self, module_types: list[str]) -> None:
        self._module_types = list(module_types)

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------

    def _initialize_default(self) -> None:
        self.floorplan = Floorplan(
            die=DieArea(width=200.0, height=200.0, site="unithd"),
            core=CoreArea(margin=10.0),
        )
        self._rebuild_scene()
        self._rebuild_list()
        self.view.zoom_fit()

    # ------------------------------------------------------------------
    # Scene management
    # ------------------------------------------------------------------

    def _rebuild_scene(self) -> None:
        self.scene.clear_all()
        self.scene.draw_die(self.floorplan.die, self.floorplan.core)
        s = self.scene.scale_factor
        for region in self.floorplan.regions:
            item = RegionItem(region, s)
            self.scene.addItem(item)
        for macro in self.floorplan.macros:
            item = MacroItem(macro, s)
            self.scene.addItem(item)
        for pin in self.floorplan.io_pins:
            item = IoPinItem(pin, self.floorplan.die, s)
            self.scene.addItem(item)
        # Power grid
        if self.floorplan.power_grid.strap_layers or self.floorplan.power_grid.ring_layers:
            self.scene.draw_power_grid(self.floorplan)

    def _rebuild_list(self) -> None:
        self.item_list.clear()
        for m in self.floorplan.macros:
            QListWidgetItem(f"[macro] {m.name} ({m.module_type})", self.item_list)
        for r in self.floorplan.regions:
            QListWidgetItem(f"[{r.region_type}] {r.name}", self.item_list)
        for p in self.floorplan.io_pins:
            QListWidgetItem(f"[pin/{p.direction}] {p.port_name} on {p.side}", self.item_list)

    # ------------------------------------------------------------------
    # Selection / properties
    # ------------------------------------------------------------------

    def _on_scene_selection(self) -> None:
        items = self.scene.selectedItems()
        if not items:
            self.props_panel.clear()
            return
        first = items[0]
        model = getattr(first, "model_obj", None)
        if model is not None:
            self.props_panel.show_object(model)

    def _on_list_selection(self) -> None:
        idx = self.item_list.currentRow()
        if idx < 0:
            return
        n_macros = len(self.floorplan.macros)
        n_regions = len(self.floorplan.regions)
        if idx < n_macros:
            self.props_panel.show_object(self.floorplan.macros[idx])
        elif idx < n_macros + n_regions:
            self.props_panel.show_object(self.floorplan.regions[idx - n_macros])
        else:
            pin_idx = idx - n_macros - n_regions
            if 0 <= pin_idx < len(self.floorplan.io_pins):
                self.props_panel.show_object(self.floorplan.io_pins[pin_idx])

    def _on_properties_changed(self) -> None:
        self._rebuild_scene()
        self._rebuild_list()
        self.floorplan_changed.emit()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _action_new(self) -> None:
        dlg = NewFloorplanDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            v = dlg.values()
            self.floorplan = Floorplan(
                die=DieArea(
                    width=v["die_width"], height=v["die_height"], site=v["site"]
                ),
                core=CoreArea(margin=v["core_margin"]),
            )
            self._rebuild_scene()
            self._rebuild_list()
            self.view.zoom_fit()
            self.status.setText(
                f"New floorplan: {v['die_width']:g} x {v['die_height']:g} um"
            )
            self.floorplan_changed.emit()

    def _action_load_def(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load DEF File", "", "DEF Files (*.def);;All Files (*)"
        )
        if path:
            self.load_def(Path(path))

    def _action_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Floorplan", "floorplan.json", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps(self.floorplan.to_dict(), indent=2), encoding="utf-8"
            )
            self._current_path = Path(path)
            self.status.setText(f"Saved: {path}")
        except OSError as e:
            QMessageBox.warning(self, "Save Failed", str(e))

    def _action_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Floorplan", "", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.floorplan = Floorplan.from_dict(data)
            self._rebuild_scene()
            self._rebuild_list()
            self.view.zoom_fit()
            self.status.setText(f"Loaded: {path}")
            self.floorplan_changed.emit()
        except (OSError, json.JSONDecodeError) as e:
            QMessageBox.warning(self, "Load Failed", str(e))

    def _action_add_region(self) -> None:
        dlg = AddRegionDialog(self, default_type="density")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.floorplan.regions.append(dlg.to_region())
            self._rebuild_scene()
            self._rebuild_list()
            self.floorplan_changed.emit()

    def _action_add_exclusion(self) -> None:
        dlg = AddRegionDialog(self, default_type="keepout")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            region = dlg.to_region()
            region.region_type = "keepout"
            self.floorplan.regions.append(region)
            self._rebuild_scene()
            self._rebuild_list()
            self.floorplan_changed.emit()

    def _action_add_macro(self) -> None:
        dlg = AddMacroDialog(self, module_types=self._module_types)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.floorplan.macros.append(dlg.to_macro())
            self._rebuild_scene()
            self._rebuild_list()
            self.floorplan_changed.emit()

    def _action_pins(self) -> None:
        dlg = PinPlacementDialog(self, existing_pins=self.floorplan.io_pins)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.floorplan.io_pins = dlg.to_pins()
            self._rebuild_scene()
            self._rebuild_list()
            self.floorplan_changed.emit()

    def _action_power_grid(self) -> None:
        dlg = PowerGridWizard(self, grid=self.floorplan.power_grid)

        def _preview(pg: PowerGrid) -> None:
            self.floorplan.power_grid = pg
            self.scene.draw_power_grid(self.floorplan)

        dlg.set_preview_callback(_preview)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.floorplan.power_grid = dlg.to_power_grid()
            self._rebuild_scene()
            self.status.setText("Power grid updated")
            self.floorplan_changed.emit()

    def _action_auto_pins(self) -> None:
        if not self.floorplan.io_pins:
            QMessageBox.information(
                self,
                "No Pins Defined",
                "Add some IO pins first using the IO Pin button.",
            )
            return
        # Distribute existing pins evenly across their assigned sides
        sides: dict[str, list[FloorplanIoPin]] = {"N": [], "S": [], "E": [], "W": []}
        for pin in self.floorplan.io_pins:
            sides.setdefault(pin.side, []).append(pin)

        die = self.floorplan.die
        for side, pins in sides.items():
            if not pins:
                continue
            length = die.width if side in ("N", "S") else die.height
            step = length / (len(pins) + 1)
            for i, pin in enumerate(pins):
                pin.position_um = step * (i + 1)
        self._rebuild_scene()
        self._rebuild_list()
        self.status.setText("Auto-distributed IO pins")
        self.floorplan_changed.emit()

    def _action_generate_tcl(self) -> None:
        tcl = self.export_tcl()
        self.status.setText(f"Generated TCL ({len(tcl.splitlines())} lines)")

    def _action_export_tcl(self) -> None:
        tcl = self.export_tcl()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export OpenROAD TCL", "floorplan.tcl", "TCL Files (*.tcl)"
        )
        if not path:
            return
        try:
            Path(path).write_text(tcl, encoding="utf-8")
            self.status.setText(f"Exported TCL: {path}")
        except OSError as e:
            QMessageBox.warning(self, "Export Failed", str(e))

    # ------------------------------------------------------------------
    # Keyboard handling
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            self._delete_selected()
        else:
            super().keyPressEvent(event)

    def _delete_selected(self) -> None:
        items = self.scene.selectedItems()
        if not items:
            return
        for it in items:
            model = getattr(it, "model_obj", None)
            if isinstance(model, FloorplanMacro) and model in self.floorplan.macros:
                self.floorplan.macros.remove(model)
            elif isinstance(model, FloorplanRegion) and model in self.floorplan.regions:
                self.floorplan.regions.remove(model)
            elif isinstance(model, FloorplanIoPin) and model in self.floorplan.io_pins:
                self.floorplan.io_pins.remove(model)
        self._rebuild_scene()
        self._rebuild_list()
        self.props_panel.clear()
        self.floorplan_changed.emit()

    # ------------------------------------------------------------------
    # Context menu on right-click
    # ------------------------------------------------------------------

    def contextMenuEvent(self, event):
        items = self.scene.selectedItems()
        if not items:
            return
        menu = QMenu(self)
        del_act = menu.addAction("Delete")
        lock_act = menu.addAction("Toggle Lock")
        props_act = menu.addAction("Properties...")
        action = menu.exec(event.globalPos())
        if action == del_act:
            self._delete_selected()
        elif action == lock_act:
            for it in items:
                model = getattr(it, "model_obj", None)
                if isinstance(model, FloorplanMacro):
                    model.fixed = not model.fixed
            self._rebuild_scene()
            self.floorplan_changed.emit()
        elif action == props_act:
            for it in items:
                model = getattr(it, "model_obj", None)
                if isinstance(model, FloorplanMacro):
                    dlg = AddMacroDialog(self, macro=model, module_types=self._module_types)
                    if dlg.exec() == QDialog.DialogCode.Accepted:
                        new_m = dlg.to_macro()
                        idx = self.floorplan.macros.index(model)
                        self.floorplan.macros[idx] = new_m
                elif isinstance(model, FloorplanRegion):
                    dlg = AddRegionDialog(self, region=model)
                    if dlg.exec() == QDialog.DialogCode.Accepted:
                        new_r = dlg.to_region()
                        idx = self.floorplan.regions.index(model)
                        self.floorplan.regions[idx] = new_r
            self._rebuild_scene()
            self._rebuild_list()
            self.floorplan_changed.emit()


__all__ = [
    "FloorplanEditorPanel",
    "Floorplan",
    "DieArea",
    "CoreArea",
    "FloorplanMacro",
    "FloorplanRegion",
    "FloorplanIoPin",
    "PowerGrid",
    "TclGenerator",
    "DefLoader",
    "NewFloorplanDialog",
    "AddMacroDialog",
    "AddRegionDialog",
    "PowerGridWizard",
    "PinPlacementDialog",
]

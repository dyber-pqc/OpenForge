"""Power-Delivery Network synthesizer panel.

Interactive form for building :class:`~openforge.floorplan.model.PdnConfig`
objects. Provides ring/stripe/followpin/via-stack editors, a top-down 2D
preview of the resulting power grid, and quick estimates of wirelength,
area overhead and IR-drop bound. Pre-loaded with SKY130 density templates.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from openforge.floorplan.model import (
        Core,
        Die,
        PdnConfig,
        PowerRing,
        PowerStripe,
        ViaStack,
    )
except Exception:  # pragma: no cover - defensive import for standalone dev
    Core = Die = PdnConfig = PowerRing = PowerStripe = ViaStack = None  # type: ignore

try:
    from openforge_desktop.panels._theme import panel_tab_qss
except Exception:  # pragma: no cover
    def panel_tab_qss(dark: bool, *, extra: str = "") -> str:  # type: ignore
        return ""


# ---------------------------------------------------------------------------
# SKY130 PDN templates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PdnTemplate:
    name: str
    description: str
    rings: list[dict]
    stripes: list[dict]
    followpins_layer: str
    via_stack: list[tuple[str, str]]


SKY130_TEMPLATES: dict[str, PdnTemplate] = {
    "sky130_low_density": PdnTemplate(
        name="Sky130 - Low density",
        description="Few wide stripes, low overhead. Good for small blocks.",
        rings=[
            dict(layer_h="met4", layer_v="met5", width_um=1.6, spacing_um=1.6, offset_um=0.0),
        ],
        stripes=[
            dict(layer="met4", direction="HORIZONTAL", pitch_um=40.0, width_um=1.6, offset_um=2.0),
            dict(layer="met5", direction="VERTICAL", pitch_um=40.0, width_um=1.6, offset_um=2.0),
        ],
        followpins_layer="met1",
        via_stack=[("met1", "met4"), ("met4", "met5")],
    ),
    "sky130_medium_density": PdnTemplate(
        name="Sky130 - Medium density",
        description="Balanced PDN for typical ASIC blocks.",
        rings=[
            dict(layer_h="met4", layer_v="met5", width_um=2.0, spacing_um=1.6, offset_um=0.0),
        ],
        stripes=[
            dict(layer="met4", direction="HORIZONTAL", pitch_um=20.0, width_um=1.6, offset_um=2.0),
            dict(layer="met5", direction="VERTICAL", pitch_um=20.0, width_um=1.6, offset_um=2.0),
        ],
        followpins_layer="met1",
        via_stack=[("met1", "met4"), ("met4", "met5")],
    ),
    "sky130_high_density": PdnTemplate(
        name="Sky130 - High density",
        description="Dense grid for high-activity, current-hungry designs.",
        rings=[
            dict(layer_h="met4", layer_v="met5", width_um=3.0, spacing_um=1.6, offset_um=0.0),
        ],
        stripes=[
            dict(layer="met4", direction="HORIZONTAL", pitch_um=10.0, width_um=2.0, offset_um=2.0),
            dict(layer="met5", direction="VERTICAL", pitch_um=10.0, width_um=2.0, offset_um=2.0),
        ],
        followpins_layer="met1",
        via_stack=[("met1", "met4"), ("met4", "met5")],
    ),
}


# ---------------------------------------------------------------------------
# Preview scene
# ---------------------------------------------------------------------------


class PdnPreviewView(QGraphicsView):
    """2D top-down preview of the rings + stripes over the die/core."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setBackgroundBrush(QBrush(QColor("#11111b")))
        self.setMinimumHeight(280)
        self._die_w = 200.0
        self._die_h = 200.0
        self._core = (10.0, 10.0, 190.0, 190.0)

    def set_box(self, die_w: float, die_h: float, core: tuple[float, float, float, float]) -> None:
        self._die_w = max(die_w, 1.0)
        self._die_h = max(die_h, 1.0)
        self._core = core

    def render_pdn(self, pdn: PdnConfig) -> None:  # type: ignore[name-defined]
        self._scene.clear()
        w, h = self._die_w, self._die_h
        # Die + core outlines
        die_item = QGraphicsRectItem(QRectF(0, 0, w, h))
        die_item.setPen(QPen(QColor("#cdd6f4"), 0.3))
        die_item.setBrush(QBrush(QColor("#181825")))
        self._scene.addItem(die_item)

        cx1, cy1, cx2, cy2 = self._core
        core_item = QGraphicsRectItem(QRectF(cx1, cy1, cx2 - cx1, cy2 - cy1))
        core_item.setPen(QPen(QColor("#89b4fa"), 0.3, Qt.PenStyle.DashLine))
        core_item.setBrush(QBrush(QColor("#1e1e2e")))
        self._scene.addItem(core_item)

        layer_colors = {
            "met1": "#f38ba8",
            "met2": "#fab387",
            "met3": "#f9e2af",
            "met4": "#a6e3a1",
            "met5": "#89b4fa",
        }

        if pdn is None:
            return

        # Rings around the core
        for ring in pdn.rings:
            ch = QColor(layer_colors.get(ring.layer_h, "#cdd6f4"))
            cv = QColor(layer_colors.get(ring.layer_v, "#cdd6f4"))
            off = ring.offset_um
            wid = ring.width_um
            # horizontal top/bottom
            top = QGraphicsRectItem(QRectF(cx1 - off, cy2 + off, (cx2 - cx1) + 2 * off, wid))
            bot = QGraphicsRectItem(QRectF(cx1 - off, cy1 - off - wid, (cx2 - cx1) + 2 * off, wid))
            for it in (top, bot):
                it.setPen(QPen(ch, 0))
                it.setBrush(QBrush(ch))
                self._scene.addItem(it)
            # vertical left/right
            left = QGraphicsRectItem(QRectF(cx1 - off - wid, cy1 - off, wid, (cy2 - cy1) + 2 * off))
            right = QGraphicsRectItem(QRectF(cx2 + off, cy1 - off, wid, (cy2 - cy1) + 2 * off))
            for it in (left, right):
                it.setPen(QPen(cv, 0))
                it.setBrush(QBrush(cv))
                self._scene.addItem(it)

        # Stripes across the core
        for stripe in pdn.stripes:
            color = QColor(layer_colors.get(stripe.layer, "#cdd6f4"))
            color.setAlpha(200)
            if stripe.direction == "HORIZONTAL":
                y = cy1 + stripe.offset_um
                while y < cy2:
                    item = QGraphicsRectItem(QRectF(cx1, y, cx2 - cx1, stripe.width_um))
                    item.setPen(QPen(color, 0))
                    item.setBrush(QBrush(color))
                    self._scene.addItem(item)
                    y += stripe.pitch_um
            else:
                x = cx1 + stripe.offset_um
                while x < cx2:
                    item = QGraphicsRectItem(QRectF(x, cy1, stripe.width_um, cy2 - cy1))
                    item.setPen(QPen(color, 0))
                    item.setBrush(QBrush(color))
                    self._scene.addItem(item)
                    x += stripe.pitch_um

        self._scene.setSceneRect(-w * 0.1, -h * 0.1, w * 1.2, h * 1.2)
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # noqa: D401 - Qt override
        super().resizeEvent(event)
        if self._scene.sceneRect().width() > 0:
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class PdnSynthesizerPanel(QDockWidget):
    """Dockable panel for constructing and previewing a PDN."""

    configChanged = Signal(object)  # emits PdnConfig

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("PDN Synthesizer", parent)
        self.setObjectName("pdn_synthesizer_dock")

        self._die_w = 200.0
        self._die_h = 200.0
        self._core = (10.0, 10.0, 190.0, 190.0)

        root = QWidget(self)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(6, 6, 6, 6)

        splitter = QSplitter(Qt.Orientation.Horizontal, root)
        root_layout.addWidget(splitter)

        # ── Left side: forms ────────────────────────────────────────────
        forms = QWidget(splitter)
        forms_layout = QVBoxLayout(forms)
        forms_layout.setContentsMargins(0, 0, 0, 0)

        # Template picker
        tmpl_group = QGroupBox("Template")
        tmpl_layout = QHBoxLayout(tmpl_group)
        self._tmpl_combo = QComboBox()
        self._tmpl_combo.addItem("(custom)", "")
        for key, t in SKY130_TEMPLATES.items():
            self._tmpl_combo.addItem(t.name, key)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_template)
        tmpl_layout.addWidget(self._tmpl_combo, 1)
        tmpl_layout.addWidget(apply_btn)
        forms_layout.addWidget(tmpl_group)

        # Ring group
        ring_group = QGroupBox("Power ring")
        ring_form = QFormLayout(ring_group)
        self._ring_hlayer = QLineEdit("met4")
        self._ring_vlayer = QLineEdit("met5")
        self._ring_width = QDoubleSpinBox()
        self._ring_width.setRange(0.1, 50.0)
        self._ring_width.setValue(2.0)
        self._ring_width.setSuffix(" um")
        self._ring_spacing = QDoubleSpinBox()
        self._ring_spacing.setRange(0.1, 50.0)
        self._ring_spacing.setValue(1.6)
        self._ring_spacing.setSuffix(" um")
        self._ring_offset = QDoubleSpinBox()
        self._ring_offset.setRange(0.0, 50.0)
        self._ring_offset.setValue(0.0)
        self._ring_offset.setSuffix(" um")
        ring_form.addRow("Horizontal layer", self._ring_hlayer)
        ring_form.addRow("Vertical layer", self._ring_vlayer)
        ring_form.addRow("Width", self._ring_width)
        ring_form.addRow("Spacing", self._ring_spacing)
        ring_form.addRow("Offset", self._ring_offset)
        forms_layout.addWidget(ring_group)

        # Stripes table
        stripe_group = QGroupBox("Stripes")
        stripe_layout = QVBoxLayout(stripe_group)
        self._stripe_table = QTableWidget(0, 5)
        self._stripe_table.setHorizontalHeaderLabels(
            ["Layer", "Direction", "Pitch um", "Width um", "Offset um"]
        )
        self._stripe_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._stripe_table.verticalHeader().setVisible(False)
        stripe_layout.addWidget(self._stripe_table)
        stripe_btns = QHBoxLayout()
        add_stripe = QPushButton("+ Add")
        rm_stripe = QPushButton("- Remove")
        add_stripe.clicked.connect(self._add_stripe_row)
        rm_stripe.clicked.connect(self._remove_stripe_row)
        stripe_btns.addWidget(add_stripe)
        stripe_btns.addWidget(rm_stripe)
        stripe_btns.addStretch(1)
        stripe_layout.addLayout(stripe_btns)
        forms_layout.addWidget(stripe_group, 1)

        # Followpins + via stack
        fp_group = QGroupBox("Followpins and vias")
        fp_form = QFormLayout(fp_group)
        self._fp_enable = QCheckBox("Enable followpins")
        self._fp_enable.setChecked(True)
        self._fp_layer = QLineEdit("met1")
        self._via_stack_edit = QLineEdit("met1->met4, met4->met5")
        self._via_stack_edit.setToolTip(
            "Comma-separated via cuts, e.g. 'met1->met4, met4->met5'"
        )
        fp_form.addRow(self._fp_enable)
        fp_form.addRow("Followpins layer", self._fp_layer)
        fp_form.addRow("Via stack", self._via_stack_edit)
        forms_layout.addWidget(fp_group)

        # Generate button
        gen_btn = QPushButton("Regenerate PDN")
        gen_btn.clicked.connect(self._regenerate)
        forms_layout.addWidget(gen_btn)

        splitter.addWidget(forms)

        # ── Right side: preview + metrics + tcl ────────────────────────
        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._preview = PdnPreviewView(right)
        right_layout.addWidget(self._preview, 1)

        self._metrics_label = QLabel("Metrics: (click Regenerate)")
        self._metrics_label.setWordWrap(True)
        right_layout.addWidget(self._metrics_label)

        self._tcl_view = QPlainTextEdit()
        self._tcl_view.setReadOnly(True)
        self._tcl_view.setMaximumBlockCount(10000)
        self._tcl_view.setPlaceholderText("Generated pdngen Tcl will appear here.")
        right_layout.addWidget(self._tcl_view, 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self.setWidget(root)
        self.setStyleSheet(panel_tab_qss(dark=True))

        # Seed with the medium-density template.
        self._tmpl_combo.setCurrentIndex(2)
        self._apply_template()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_die_core(
        self,
        die_w: float,
        die_h: float,
        core: tuple[float, float, float, float],
    ) -> None:
        self._die_w = die_w
        self._die_h = die_h
        self._core = core
        self._preview.set_box(die_w, die_h, core)
        self._regenerate()

    def current_config(self) -> PdnConfig:  # type: ignore[name-defined]
        if PdnConfig is None:
            raise RuntimeError("openforge.floorplan model is not importable")
        rings = [
            PowerRing(
                layer_h=self._ring_hlayer.text().strip() or "met4",
                layer_v=self._ring_vlayer.text().strip() or "met5",
                width_um=self._ring_width.value(),
                spacing_um=self._ring_spacing.value(),
                offset_um=self._ring_offset.value(),
            )
        ]
        stripes: list = []
        for row in range(self._stripe_table.rowCount()):
            try:
                layer = self._stripe_table.item(row, 0).text().strip()
                direction = self._stripe_table.item(row, 1).text().strip().upper()
                pitch = float(self._stripe_table.item(row, 2).text())
                width = float(self._stripe_table.item(row, 3).text())
                offset = float(self._stripe_table.item(row, 4).text())
            except (AttributeError, ValueError):
                continue
            if direction not in ("HORIZONTAL", "VERTICAL"):
                direction = "HORIZONTAL"
            stripes.append(
                PowerStripe(
                    layer=layer or "met4",
                    direction=direction,  # type: ignore[arg-type]
                    pitch_um=max(pitch, 0.1),
                    width_um=max(width, 0.1),
                    offset_um=offset,
                )
            )
        via_stack: list = []
        for token in self._via_stack_edit.text().split(","):
            token = token.strip()
            if "->" not in token:
                continue
            a, b = [t.strip() for t in token.split("->", 1)]
            if a and b:
                via_stack.append(ViaStack(from_layer=a, to_layer=b))

        return PdnConfig(
            rings=rings,
            stripes=stripes,
            followpins=self._fp_enable.isChecked(),
            followpins_layer=self._fp_layer.text().strip() or "met1",
            via_stack=via_stack,
        )

    def current_tcl(self) -> str:
        return self._tcl_view.toPlainText()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _apply_template(self) -> None:
        key = self._tmpl_combo.currentData()
        if not key or key not in SKY130_TEMPLATES:
            return
        t = SKY130_TEMPLATES[key]
        r = t.rings[0]
        self._ring_hlayer.setText(r["layer_h"])
        self._ring_vlayer.setText(r["layer_v"])
        self._ring_width.setValue(r["width_um"])
        self._ring_spacing.setValue(r["spacing_um"])
        self._ring_offset.setValue(r["offset_um"])

        self._stripe_table.setRowCount(0)
        for s in t.stripes:
            self._add_stripe_row(
                layer=s["layer"],
                direction=s["direction"],
                pitch=s["pitch_um"],
                width=s["width_um"],
                offset=s["offset_um"],
            )

        self._fp_enable.setChecked(True)
        self._fp_layer.setText(t.followpins_layer)
        self._via_stack_edit.setText(
            ", ".join(f"{a}->{b}" for a, b in t.via_stack)
        )
        self._regenerate()

    def _add_stripe_row(
        self,
        layer: str = "met4",
        direction: str = "HORIZONTAL",
        pitch: float = 20.0,
        width: float = 1.6,
        offset: float = 2.0,
    ) -> None:
        row = self._stripe_table.rowCount()
        self._stripe_table.insertRow(row)
        self._stripe_table.setItem(row, 0, QTableWidgetItem(layer))
        self._stripe_table.setItem(row, 1, QTableWidgetItem(direction))
        self._stripe_table.setItem(row, 2, QTableWidgetItem(f"{pitch:g}"))
        self._stripe_table.setItem(row, 3, QTableWidgetItem(f"{width:g}"))
        self._stripe_table.setItem(row, 4, QTableWidgetItem(f"{offset:g}"))

    def _remove_stripe_row(self) -> None:
        row = self._stripe_table.currentRow()
        if row >= 0:
            self._stripe_table.removeRow(row)

    def _regenerate(self) -> None:
        if PdnConfig is None:
            return
        try:
            cfg = self.current_config()
        except Exception as exc:
            self._metrics_label.setText(f"Invalid config: {exc}")
            return
        self._preview.set_box(self._die_w, self._die_h, self._core)
        self._preview.render_pdn(cfg)
        self._metrics_label.setText(self._format_metrics(cfg))
        self._tcl_view.setPlainText(self._to_tcl(cfg))
        self.configChanged.emit(cfg)

    # ------------------------------------------------------------------
    # Metrics and Tcl
    # ------------------------------------------------------------------

    def _format_metrics(self, cfg: PdnConfig) -> str:  # type: ignore[name-defined]
        cx1, cy1, cx2, cy2 = self._core
        core_w = max(cx2 - cx1, 0.0)
        core_h = max(cy2 - cy1, 0.0)
        core_area = core_w * core_h

        wirelen = 0.0
        overhead = 0.0
        for ring in cfg.rings:
            # Outer perimeter of the ring loop.
            perim = 2.0 * ((core_w + 2 * ring.offset_um) + (core_h + 2 * ring.offset_um))
            wirelen += 2 * perim  # VDD + VSS
            overhead += 2 * perim * ring.width_um
        for stripe in cfg.stripes:
            if stripe.direction == "HORIZONTAL":
                count = max(int(core_h / stripe.pitch_um), 1)
                wirelen += count * core_w
                overhead += count * core_w * stripe.width_um
            else:
                count = max(int(core_w / stripe.pitch_um), 1)
                wirelen += count * core_h
                overhead += count * core_h * stripe.width_um

        area_pct = (overhead / core_area * 100.0) if core_area > 0 else 0.0
        # Very rough IR drop bound proportional to inverse wirelength density.
        ir_mv = 50.0 / (1.0 + wirelen / max(core_area, 1.0)) if wirelen > 0 else 999.0

        return (
            f"Wirelength: {wirelen:,.0f} um    "
            f"Area overhead: {area_pct:.1f}%    "
            f"Estimated IR bound: {ir_mv:.1f} mV"
        )

    def _to_tcl(self, cfg: PdnConfig) -> str:  # type: ignore[name-defined]
        lines: list[str] = []
        push = lines.append
        push("# pdngen configuration - generated by OpenForge PDN Synthesizer")
        push("pdngen -reset")
        push(
            'add_global_connection -net VDD -inst_pattern ".*" '
            '-pin_pattern "^VPWR$|^VDD$" -power'
        )
        push(
            'add_global_connection -net VSS -inst_pattern ".*" '
            '-pin_pattern "^VGND$|^VSS$" -ground'
        )
        push("set_voltage_domain -name CORE -power VDD -ground VSS")
        push(
            "define_pdn_grid -name core_grid -voltage_domains CORE -pins {}"
        )
        if cfg.followpins:
            push(
                f"add_pdn_stripe -grid core_grid -layer {cfg.followpins_layer} "
                f"-width 0.48 -followpins"
            )
        for ring in cfg.rings:
            push(
                f"add_pdn_ring -grid core_grid "
                f"-layers {{{ring.layer_h} {ring.layer_v}}} "
                f'-widths "{ring.width_um:g} {ring.width_um:g}" '
                f'-spacings "{ring.spacing_um:g} {ring.spacing_um:g}" '
                f'-core_offset "{ring.offset_um:g} {ring.offset_um:g}"'
            )
        for s in cfg.stripes:
            push(
                f"add_pdn_stripe -grid core_grid -layer {s.layer} "
                f"-width {s.width_um:g} -pitch {s.pitch_um:g} "
                f"-offset {s.offset_um:g} -extend_to_core_ring"
            )
        for v in cfg.via_stack:
            push(
                f"add_pdn_connect -grid core_grid "
                f"-layers {{{v.from_layer} {v.to_layer}}}"
            )
        push("pdngen")
        return "\n".join(lines) + "\n"

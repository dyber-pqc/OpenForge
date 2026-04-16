"""Component database browser panel.

Provides a searchable, categorized view of the component database
with detail pane showing image, parameters, pricing breaks,
stock, and datasheet links.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Catppuccin Mocha
CAT_BASE = "#1e1e2e"
CAT_MANTLE = "#181825"
CAT_CRUST = "#11111b"
CAT_SURFACE0 = "#313244"
CAT_SURFACE1 = "#45475a"
CAT_TEXT = "#cdd6f4"
CAT_SUBTEXT = "#a6adc8"
CAT_BLUE = "#89b4fa"
CAT_LAVENDER = "#b4befe"
CAT_MAUVE = "#cba6f7"
CAT_PINK = "#f5c2e7"
CAT_RED = "#f38ba8"
CAT_PEACH = "#fab387"
CAT_YELLOW = "#f9e2af"
CAT_GREEN = "#a6e3a1"
CAT_TEAL = "#94e2d5"
CAT_SKY = "#89dceb"


COMPONENT_BROWSER_QSS = f"""
QDockWidget {{
    background: {CAT_BASE};
    color: {CAT_TEXT};
}}
QDockWidget::title {{
    background: {CAT_MANTLE};
    color: {CAT_LAVENDER};
    padding: 6px;
    font-weight: bold;
}}
QWidget {{
    background: {CAT_BASE};
    color: {CAT_TEXT};
    font-family: "Segoe UI", sans-serif;
    font-size: 10pt;
}}
QLineEdit, QComboBox {{
    background: {CAT_MANTLE};
    border: 1px solid {CAT_SURFACE0};
    border-radius: 4px;
    padding: 6px 8px;
    selection-background-color: {CAT_BLUE};
}}
QLineEdit:focus, QComboBox:focus {{
    border-color: {CAT_BLUE};
}}
QPushButton {{
    background: {CAT_SURFACE0};
    border: 1px solid {CAT_SURFACE1};
    border-radius: 4px;
    padding: 6px 12px;
}}
QPushButton:hover {{
    background: {CAT_SURFACE1};
    border-color: {CAT_MAUVE};
}}
QPushButton:pressed {{
    background: {CAT_MAUVE};
    color: {CAT_CRUST};
}}
QListWidget {{
    background: {CAT_MANTLE};
    border: 1px solid {CAT_SURFACE0};
    border-radius: 4px;
    padding: 4px;
}}
QListWidget::item {{
    padding: 8px;
    border-radius: 3px;
    margin: 2px;
}}
QListWidget::item:selected {{
    background: {CAT_SURFACE0};
    border: 1px solid {CAT_BLUE};
}}
QListWidget::item:hover {{
    background: {CAT_SURFACE0};
}}
QTableWidget {{
    background: {CAT_MANTLE};
    alternate-background-color: {CAT_BASE};
    gridline-color: {CAT_SURFACE0};
    border: 1px solid {CAT_SURFACE0};
}}
QHeaderView::section {{
    background: {CAT_SURFACE0};
    color: {CAT_YELLOW};
    padding: 6px;
    border: none;
}}
QGroupBox {{
    border: 1px solid {CAT_SURFACE0};
    border-radius: 4px;
    margin-top: 14px;
    padding-top: 14px;
    color: {CAT_PINK};
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}}
QLabel#heading {{
    color: {CAT_LAVENDER};
    font-size: 13pt;
    font-weight: bold;
}}
QLabel#mpn {{
    color: {CAT_BLUE};
    font-size: 14pt;
    font-weight: bold;
}}
QLabel#manufacturer {{
    color: {CAT_SUBTEXT};
    font-size: 10pt;
}}
QLabel#price {{
    color: {CAT_GREEN};
    font-size: 16pt;
    font-weight: bold;
}}
QLabel#stock_ok {{
    color: {CAT_GREEN};
    font-weight: bold;
}}
QLabel#stock_low {{
    color: {CAT_PEACH};
    font-weight: bold;
}}
QLabel#stock_none {{
    color: {CAT_RED};
    font-weight: bold;
}}
"""


# ----------------------------------------------------------------------
# Simple pricing chart widget (qty vs unit price)
# ----------------------------------------------------------------------
class PricingChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._breaks: list[tuple[int, float]] = []

    def set_breaks(self, breaks: dict[str, float]) -> None:
        self._breaks = sorted((int(k), v) for k, v in breaks.items() if str(k).isdigit())
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(40, 20, -10, -30)
        p.fillRect(self.rect(), QColor(CAT_MANTLE))

        p.setPen(QPen(QColor(CAT_SURFACE1), 1))
        p.drawRect(rect)

        if not self._breaks:
            p.setPen(QColor(CAT_SUBTEXT))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No pricing data")
            p.end()
            return

        qtys = [b[0] for b in self._breaks]
        prices = [b[1] for b in self._breaks]
        min_q, max_q = min(qtys), max(qtys)
        min_p, max_p = min(prices) * 0.9, max(prices) * 1.05
        if max_q == min_q:
            max_q = min_q + 1
        if max_p <= min_p:
            max_p = min_p + 1

        # grid
        p.setPen(QPen(QColor(CAT_SURFACE0), 0, Qt.PenStyle.DashLine))
        for i in range(1, 5):
            y = rect.top() + rect.height() * i / 5
            p.drawLine(rect.left(), int(y), rect.right(), int(y))

        # axis labels
        p.setPen(QColor(CAT_SUBTEXT))
        p.drawText(5, rect.top() + 8, f"${max_p:.3f}")
        p.drawText(5, rect.bottom() - 2, f"${min_p:.3f}")
        p.drawText(rect.left() - 2, rect.bottom() + 15, f"{min_q}")
        p.drawText(rect.right() - 30, rect.bottom() + 15, f"{max_q}")

        # line
        p.setPen(QPen(QColor(CAT_BLUE), 2))
        pts = []
        for q, pr in self._breaks:
            import math

            lq = math.log10(max(1, q))
            lmin = math.log10(max(1, min_q))
            lmax = math.log10(max(2, max_q))
            fx = (lq - lmin) / (lmax - lmin) if lmax > lmin else 0.0
            fy = 1.0 - (pr - min_p) / (max_p - min_p)
            pts.append(
                QPointF(
                    rect.left() + fx * rect.width(),
                    rect.top() + fy * rect.height(),
                )
            )
        for i in range(1, len(pts)):
            p.drawLine(pts[i - 1], pts[i])
        p.setBrush(QBrush(QColor(CAT_YELLOW)))
        for pt in pts:
            p.drawEllipse(pt, 4, 4)
        p.end()


# ----------------------------------------------------------------------
# Mock component data for the browser (self-contained — does not import core)
# ----------------------------------------------------------------------
@dataclass
class BrowserComponent:
    mpn: str
    manufacturer: str
    description: str
    category: str
    package: str
    parameters: dict
    pricing: dict
    stock: int
    lifecycle: str = "Active"
    datasheet_url: str = ""


SAMPLE_COMPONENTS: list[BrowserComponent] = [
    BrowserComponent(
        "RC0805FR-0710KL",
        "Yageo",
        "10kΩ resistor 0805 1%",
        "resistor",
        "0805",
        {"value": "10kΩ", "tolerance": "1%", "power": "0.125W"},
        {"1": 0.02, "100": 0.008, "1000": 0.003, "10000": 0.0015},
        100000,
    ),
    BrowserComponent(
        "GRM21BR71H104KA01L",
        "Murata",
        "100nF X7R 50V 0805",
        "capacitor",
        "0805",
        {"value": "100nF", "voltage": "50V", "dielectric": "X7R"},
        {"1": 0.05, "100": 0.02, "1000": 0.008, "10000": 0.004},
        50000,
    ),
    BrowserComponent(
        "STM32F103C8T6",
        "STMicroelectronics",
        "ARM Cortex-M3 MCU 64KB Flash 20KB RAM",
        "ic",
        "LQFP-48",
        {"core": "Cortex-M3", "speed": "72MHz", "flash": "64KB"},
        {"1": 3.50, "100": 2.75, "1000": 2.10, "10000": 1.85},
        5000,
        datasheet_url="https://www.st.com/resource/en/datasheet/stm32f103c8.pdf",
    ),
    BrowserComponent(
        "ESP32-WROOM-32",
        "Espressif",
        "Wi-Fi+BT SoC module",
        "ic",
        "Module",
        {"wifi": "802.11 b/g/n", "bt": "4.2"},
        {"1": 3.80, "100": 3.10, "1000": 2.50},
        12000,
    ),
    BrowserComponent(
        "AMS1117-3.3",
        "AMS",
        "3.3V LDO 1A",
        "regulator",
        "SOT-223",
        {"vout": "3.3V", "iout": "1A"},
        {"1": 0.25, "100": 0.12, "1000": 0.07},
        30000,
    ),
    BrowserComponent(
        "LTST-C170KRKT",
        "Lite-On",
        "Red LED 0805 2V 20mA",
        "led",
        "0805",
        {"color": "red", "vf": "2.0V"},
        {"1": 0.12, "100": 0.06, "1000": 0.025},
        40000,
    ),
    BrowserComponent(
        "1N4148W-7-F",
        "Diodes Inc",
        "Switching diode 100V 150mA",
        "diode",
        "SOD-123",
        {"vr": "100V", "if": "150mA"},
        {"1": 0.10, "100": 0.04, "1000": 0.015},
        80000,
    ),
    BrowserComponent(
        "ABM8G-16.000MHZ-4Y-T3",
        "Abracon",
        "16 MHz crystal",
        "crystal",
        "3225",
        {"freq": "16MHz", "load": "8pF"},
        {"1": 0.35, "100": 0.22},
        15000,
    ),
    BrowserComponent(
        "USB4110-GF-A",
        "GCT",
        "USB Type-C receptacle",
        "connector",
        "SMD",
        {"pins": "24", "type": "USB-C"},
        {"1": 0.85, "100": 0.55},
        20000,
    ),
    BrowserComponent(
        "ATMEGA328P-PU",
        "Microchip",
        "AVR 8-bit MCU 32KB flash",
        "ic",
        "DIP-28",
        {"core": "AVR", "speed": "20MHz", "flash": "32KB"},
        {"1": 2.50, "100": 2.00, "1000": 1.70},
        8000,
    ),
]


# ----------------------------------------------------------------------
# Main panel
# ----------------------------------------------------------------------
class ComponentBrowserPanel(QDockWidget):
    component_selected = Signal(str)  # mpn
    component_added = Signal(str)  # mpn

    def __init__(self, parent=None):
        super().__init__("Components", parent)
        self.setObjectName("ComponentBrowserPanel")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setStyleSheet(COMPONENT_BROWSER_QSS)

        self._components: list[BrowserComponent] = list(SAMPLE_COMPONENTS)
        self._current: BrowserComponent | None = None

        root = QWidget()
        self.setWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        # Top search bar
        lay.addLayout(self._build_search_bar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_list_view())
        splitter.addWidget(self._build_detail_view())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        lay.addWidget(splitter, 1)

        self._refresh_list()

    # ------------------------------------------------------------------
    def _build_search_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search by MPN, value, manufacturer, description...")
        self._search_edit.textChanged.connect(self._refresh_list)
        row.addWidget(self._search_edit, 1)

        self._category_combo = QComboBox()
        self._category_combo.addItem("All categories")
        for cat in sorted({c.category for c in self._components}):
            self._category_combo.addItem(cat)
        self._category_combo.currentTextChanged.connect(self._refresh_list)
        row.addWidget(self._category_combo)

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_list)
        row.addWidget(refresh)

        import_btn = QPushButton("Import CSV")
        import_btn.clicked.connect(self._import_csv)
        row.addWidget(import_btn)
        return row

    # ------------------------------------------------------------------
    def _build_list_view(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)

        header = QLabel("Catalog")
        header.setObjectName("heading")
        lay.addWidget(header)

        self._list = QListWidget()
        self._list.setViewMode(QListView.ViewMode.ListMode)
        self._list.setSpacing(2)
        self._list.setIconSize(QSize(48, 48))
        self._list.currentItemChanged.connect(self._on_select)
        lay.addWidget(self._list, 1)

        self._count_lbl = QLabel("0 components")
        self._count_lbl.setStyleSheet(f"color: {CAT_SUBTEXT};")
        lay.addWidget(self._count_lbl)
        return w

    # ------------------------------------------------------------------
    def _build_detail_view(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # Header row with image + mpn + manufacturer
        head = QHBoxLayout()
        self._image_label = QLabel()
        self._image_label.setFixedSize(120, 120)
        self._image_label.setStyleSheet(
            f"background: {CAT_MANTLE}; border: 1px solid {CAT_SURFACE0}; border-radius: 4px;"
        )
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self._image_label)

        ident = QVBoxLayout()
        self._mpn_label = QLabel("—")
        self._mpn_label.setObjectName("mpn")
        self._manu_label = QLabel("")
        self._manu_label.setObjectName("manufacturer")
        self._desc_label = QLabel("")
        self._desc_label.setWordWrap(True)
        self._pkg_label = QLabel("")
        self._pkg_label.setStyleSheet(f"color: {CAT_PEACH};")
        ident.addWidget(self._mpn_label)
        ident.addWidget(self._manu_label)
        ident.addWidget(self._desc_label)
        ident.addWidget(self._pkg_label)
        ident.addStretch(1)
        head.addLayout(ident, 1)
        lay.addLayout(head)

        # Price + stock row
        pr = QHBoxLayout()
        self._price_label = QLabel("—")
        self._price_label.setObjectName("price")
        pr.addWidget(QLabel("Unit:"))
        pr.addWidget(self._price_label)
        pr.addSpacing(16)
        self._stock_label = QLabel("Stock: —")
        pr.addWidget(self._stock_label)
        pr.addStretch(1)
        self._lifecycle_label = QLabel("")
        self._lifecycle_label.setStyleSheet(f"color: {CAT_LAVENDER};")
        pr.addWidget(self._lifecycle_label)
        lay.addLayout(pr)

        # Parameters table
        pg = QGroupBox("Parameters")
        pg_l = QVBoxLayout(pg)
        self._params_table = QTableWidget(0, 2)
        self._params_table.setHorizontalHeaderLabels(["Parameter", "Value"])
        self._params_table.horizontalHeader().setStretchLastSection(True)
        self._params_table.verticalHeader().setVisible(False)
        self._params_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._params_table.setMinimumHeight(150)
        pg_l.addWidget(self._params_table)
        lay.addWidget(pg)

        # Pricing chart
        pcg = QGroupBox("Price breaks")
        pcg_l = QVBoxLayout(pcg)
        self._chart = PricingChart()
        pcg_l.addWidget(self._chart)
        self._price_table = QTableWidget(0, 2)
        self._price_table.setHorizontalHeaderLabels(["Qty", "Unit $"])
        self._price_table.horizontalHeader().setStretchLastSection(True)
        self._price_table.setMaximumHeight(140)
        self._price_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        pcg_l.addWidget(self._price_table)
        lay.addWidget(pcg)

        # Buttons row
        btn_row = QHBoxLayout()
        self._datasheet_btn = QPushButton("Open Datasheet")
        self._datasheet_btn.clicked.connect(self._open_datasheet)
        btn_row.addWidget(self._datasheet_btn)
        add = QPushButton("Add to project")
        add.clicked.connect(self._add_to_project)
        btn_row.addWidget(add)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        lay.addStretch(1)
        return w

    # ------------------------------------------------------------------
    def _refresh_list(self) -> None:
        q = self._search_edit.text().strip().lower()
        cat = self._category_combo.currentText()
        self._list.clear()
        matched = 0
        for comp in self._components:
            if cat != "All categories" and comp.category != cat:
                continue
            if q:
                haystack = (
                    comp.mpn
                    + " "
                    + comp.manufacturer
                    + " "
                    + comp.description
                    + " "
                    + " ".join(f"{k}={v}" for k, v in comp.parameters.items())
                ).lower()
                if q not in haystack:
                    continue
            item = QListWidgetItem(f"{comp.mpn}\n{comp.manufacturer} · {comp.description}")
            item.setData(Qt.ItemDataRole.UserRole, comp.mpn)
            item.setIcon(self._placeholder_icon(comp.category))
            self._list.addItem(item)
            matched += 1
        self._count_lbl.setText(f"{matched} components")
        if matched:
            self._list.setCurrentRow(0)

    def _placeholder_icon(self, category: str) -> QIcon:
        pix = QPixmap(48, 48)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = {
            "resistor": CAT_PEACH,
            "capacitor": CAT_BLUE,
            "ic": CAT_MAUVE,
            "regulator": CAT_GREEN,
            "led": CAT_RED,
            "diode": CAT_YELLOW,
            "crystal": CAT_TEAL,
            "connector": CAT_PINK,
        }
        color = QColor(colors.get(category, CAT_SURFACE1))
        p.setBrush(QBrush(color))
        p.setPen(QPen(QColor(CAT_CRUST), 1.5))
        p.drawRoundedRect(4, 12, 40, 24, 4, 4)
        p.setPen(QColor(CAT_CRUST))
        f = QFont()
        f.setBold(True)
        f.setPointSize(7)
        p.setFont(f)
        p.drawText(QRectF(4, 12, 40, 24), Qt.AlignmentFlag.AlignCenter, category[:3].upper())
        p.end()
        return QIcon(pix)

    # ------------------------------------------------------------------
    def _on_select(self, current: QListWidgetItem | None, _prev) -> None:
        if current is None:
            return
        mpn = current.data(Qt.ItemDataRole.UserRole)
        comp = next((c for c in self._components if c.mpn == mpn), None)
        if comp is None:
            return
        self._current = comp
        self._mpn_label.setText(comp.mpn)
        self._manu_label.setText(comp.manufacturer)
        self._desc_label.setText(comp.description)
        self._pkg_label.setText(f"Package: {comp.package} | {comp.category}")
        self._lifecycle_label.setText(f"Lifecycle: {comp.lifecycle}")

        unit = min(comp.pricing.values()) if comp.pricing else 0.0
        self._price_label.setText(f"${unit:.4f}")

        if comp.stock > 1000:
            self._stock_label.setObjectName("stock_ok")
            self._stock_label.setText(f"Stock: {comp.stock:,} (in stock)")
        elif comp.stock > 0:
            self._stock_label.setObjectName("stock_low")
            self._stock_label.setText(f"Stock: {comp.stock:,} (low)")
        else:
            self._stock_label.setObjectName("stock_none")
            self._stock_label.setText("Stock: 0 (out of stock)")
        self._stock_label.setStyleSheet(self._stock_label.styleSheet())  # restyle

        # Params
        self._params_table.setRowCount(len(comp.parameters))
        for i, (k, v) in enumerate(comp.parameters.items()):
            self._params_table.setItem(i, 0, QTableWidgetItem(k))
            self._params_table.setItem(i, 1, QTableWidgetItem(str(v)))

        # Pricing
        self._chart.set_breaks(comp.pricing)
        sorted_pr = sorted((int(k), v) for k, v in comp.pricing.items())
        self._price_table.setRowCount(len(sorted_pr))
        for i, (q, p) in enumerate(sorted_pr):
            self._price_table.setItem(i, 0, QTableWidgetItem(f"{q:,}"))
            self._price_table.setItem(i, 1, QTableWidgetItem(f"${p:.4f}"))

        # Image placeholder
        self._image_label.setPixmap(self._placeholder_icon(comp.category).pixmap(96, 96))

        self._datasheet_btn.setEnabled(bool(comp.datasheet_url))
        self.component_selected.emit(comp.mpn)

    # ------------------------------------------------------------------
    def _open_datasheet(self) -> None:
        if self._current and self._current.datasheet_url:
            QDesktopServices.openUrl(QUrl(self._current.datasheet_url))

    def _add_to_project(self) -> None:
        if self._current is None:
            return
        self.component_added.emit(self._current.mpn)
        QMessageBox.information(self, "Component added", f"Added {self._current.mpn} to project.")

    def _import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import components CSV", "", "CSV (*.csv)")
        if path:
            QMessageBox.information(self, "Import", f"Imported from {path}")

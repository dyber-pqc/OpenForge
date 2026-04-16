"""UVM-lite panel: wizard, agent library, run controls, log, phase tracker."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from ._theme import panel_tab_qss
except Exception:  # pragma: no cover
    def panel_tab_qss(dark: bool, *, extra: str = "") -> str:  # type: ignore
        return ""

try:
    from openforge.verification.uvm_lite import (
        AgentSpec,
        generate_agent,
        generate_test_skeleton,
        list_protocols,
    )
except Exception:  # pragma: no cover
    AgentSpec = None  # type: ignore
    generate_agent = None  # type: ignore
    generate_test_skeleton = None  # type: ignore

    def list_protocols() -> list[str]:  # type: ignore
        return []


_PHASES = ["build", "connect", "run", "report"]


class _NewTestWizard(QDialog):
    """Tiny dialog asking for test name, DUT module, and the list of agents."""

    def __init__(self, protocols: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New UVM-lite Test")
        self.resize(420, 360)

        form = QFormLayout()
        self._name = QLineEdit("smoke_test")
        self._dut = QLineEdit("dut")
        form.addRow("Test name", self._name)
        form.addRow("DUT module", self._dut)

        self._agents = QListWidget()
        self._agents.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for p in protocols:
            self._agents.addItem(QListWidgetItem(p))
        form.addRow("Agents", self._agents)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(btns)

    def result_data(self) -> tuple[str, str, list[str]]:
        agents = [self._agents.item(i).text() for i in range(self._agents.count()) if self._agents.item(i).isSelected()]
        return self._name.text().strip() or "test", self._dut.text().strip() or "dut", agents


class UvmPanel(QWidget):
    """Dockable UVM-lite control panel."""

    log_line = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("uvm_panel")
        self.setStyleSheet(panel_tab_qss(True))

        self._project_dir: Path = Path.cwd()
        self._tests: list[dict[str, object]] = []

        # ── Top bar ─────────────────────────────────────────────────
        top_bar = QHBoxLayout()
        self._new_btn = QPushButton("New Test...")
        self._run_btn = QPushButton("Run")
        self._run_all_btn = QPushButton("Run All")
        self._stop_btn = QPushButton("Stop")
        self._dir_btn = QPushButton("Set Output Dir...")
        for b in (self._new_btn, self._run_btn, self._run_all_btn, self._stop_btn, self._dir_btn):
            top_bar.addWidget(b)
        top_bar.addStretch(1)

        self._new_btn.clicked.connect(self._on_new_test)
        self._run_btn.clicked.connect(self._on_run)
        self._run_all_btn.clicked.connect(self._on_run_all)
        self._stop_btn.clicked.connect(self._on_stop)
        self._dir_btn.clicked.connect(self._on_set_dir)

        # ── Left: agent library ─────────────────────────────────────
        self._agent_list = QListWidget()
        for p in list_protocols():
            self._agent_list.addItem(QListWidgetItem(p))
        agents_box = QGroupBox("Agent Library")
        v = QVBoxLayout(agents_box)
        v.addWidget(self._agent_list)
        add_btn = QPushButton("Add Agent to Project")
        add_btn.clicked.connect(self._on_add_agent)
        v.addWidget(add_btn)

        # ── Center: tests ────────────────────────────────────────────
        self._test_list = QListWidget()
        self._test_list.itemSelectionChanged.connect(self._on_test_selected)
        tests_box = QGroupBox("Tests")
        tv = QVBoxLayout(tests_box)
        tv.addWidget(self._test_list)

        # Phase tracker
        phase_box = QGroupBox("Phase")
        pv = QHBoxLayout(phase_box)
        self._phase_labels: dict[str, QLabel] = {}
        for p in _PHASES:
            lbl = QLabel(p)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("QLabel { padding: 4px 10px; border: 1px solid #45475a; border-radius: 4px; }")
            self._phase_labels[p] = lbl
            pv.addWidget(lbl)
        pv.addStretch(1)

        # Status table
        self._status_table = QTableWidget(0, 3)
        self._status_table.setHorizontalHeaderLabels(["Test", "Status", "Details"])
        h = self._status_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        # Generated files tab + log tab
        self._files_view = QPlainTextEdit()
        self._files_view.setReadOnly(True)
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)

        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("Filter:"))
        self._filter = QComboBox()
        self._filter.addItems(["ALL", "UVM_INFO", "UVM_WARNING", "UVM_ERROR", "UVM_FATAL"])
        self._filter.currentTextChanged.connect(self._apply_log_filter)
        filter_bar.addWidget(self._filter)
        filter_bar.addStretch(1)

        log_widget = QWidget()
        lw = QVBoxLayout(log_widget)
        lw.setContentsMargins(0, 0, 0, 0)
        lw.addLayout(filter_bar)
        lw.addWidget(self._log_view)

        tabs = QTabWidget()
        tabs.addTab(self._files_view, "Generated Files")
        tabs.addTab(log_widget, "Log")
        tabs.addTab(self._status_table, "Status")

        center = QWidget()
        cv = QVBoxLayout(center)
        cv.addWidget(tests_box)
        cv.addWidget(phase_box)
        cv.addWidget(tabs, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(agents_box)
        splitter.addWidget(center)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(top_bar)
        layout.addWidget(splitter, 1)

        self._raw_log: list[str] = []

    # -- slots ---------------------------------------------------

    def _on_set_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "UVM output directory", str(self._project_dir))
        if d:
            self._project_dir = Path(d)
            self._log(f"output dir = {d}")

    def _on_new_test(self) -> None:
        dlg = _NewTestWizard(list_protocols(), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, dut, agents = dlg.result_data()
        if generate_test_skeleton is None or AgentSpec is None:
            self._log("uvm_lite not available")
            return
        out = self._project_dir / "uvm_tests" / name
        files = generate_test_skeleton(name, dut, agents, out)
        for a in agents:
            generate_agent(AgentSpec(name=a, protocol=a), out)
        self._tests.append({"name": name, "dut": dut, "agents": agents, "dir": out})
        self._test_list.addItem(QListWidgetItem(name))
        self._files_view.setPlainText(
            "\n".join(f"{k}: {v}" for k, v in files.items())
        )
        self._log(f"generated {name} at {out}")

    def _on_add_agent(self) -> None:
        it = self._agent_list.currentItem()
        if not it or AgentSpec is None or generate_agent is None:
            return
        proto = it.text()
        out = self._project_dir / "uvm_agents"
        path = generate_agent(AgentSpec(name=proto, protocol=proto), out)
        self._log(f"wrote {path}")

    def _on_test_selected(self) -> None:
        it = self._test_list.currentItem()
        if not it:
            return
        for t in self._tests:
            if t["name"] == it.text():
                self._files_view.setPlainText(
                    f"test:   {t['name']}\n"
                    f"dut:    {t['dut']}\n"
                    f"agents: {t['agents']}\n"
                    f"dir:    {t['dir']}"
                )
                return

    def _on_run(self) -> None:
        it = self._test_list.currentItem()
        if not it:
            return
        self._simulate_phases(it.text())

    def _on_run_all(self) -> None:
        for i in range(self._test_list.count()):
            self._simulate_phases(self._test_list.item(i).text())

    def _on_stop(self) -> None:
        self._log("stop requested")
        self._reset_phases()

    def _simulate_phases(self, test_name: str) -> None:
        """Mark phase labels as they 'run'. Real dispatch happens via a worker."""
        self._reset_phases()
        for phase in _PHASES:
            self._phase_labels[phase].setStyleSheet(
                "QLabel { padding: 4px 10px; border: 1px solid #89b4fa; "
                "background: #89b4fa; color: #1e1e2e; border-radius: 4px; }"
            )
        self._log(f"UVM_INFO [TEST] {test_name} launched")
        row = self._status_table.rowCount()
        self._status_table.insertRow(row)
        self._status_table.setItem(row, 0, QTableWidgetItem(test_name))
        self._status_table.setItem(row, 1, QTableWidgetItem("running"))
        self._status_table.setItem(row, 2, QTableWidgetItem("phase tracking only"))

    def _reset_phases(self) -> None:
        for lbl in self._phase_labels.values():
            lbl.setStyleSheet(
                "QLabel { padding: 4px 10px; border: 1px solid #45475a; border-radius: 4px; }"
            )

    # -- logging -------------------------------------------------

    def _log(self, msg: str) -> None:
        self._raw_log.append(msg)
        self._apply_log_filter(self._filter.currentText())
        self.log_line.emit(msg)

    def _apply_log_filter(self, level: str) -> None:
        if level == "ALL":
            shown = self._raw_log
        else:
            shown = [ln for ln in self._raw_log if level in ln]
        self._log_view.setPlainText("\n".join(shown))

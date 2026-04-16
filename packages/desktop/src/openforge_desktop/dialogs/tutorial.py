"""In-app interactive tutorial system.

Defines a small DSL of TutorialStep objects, eight built-in tutorials, a
floating step dialog with prev/next/skip controls, and a Qt overlay that
dims the main window while highlighting the active target widget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from PySide6.QtCore import (
    Qt,
    Signal,
    QSize,
    QRect,
    QPoint,
    QPropertyAnimation,
    QEasingCurve,
    QTimer,
)
from PySide6.QtGui import (
    QPainter,
    QColor,
    QPen,
    QBrush,
    QPainterPath,
    QRegion,
    QFont,
    QPalette,
    QPixmap,
)
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QProgressBar,
    QGraphicsDropShadowEffect,
    QSizePolicy,
    QApplication,
    QTextBrowser,
    QSpacerItem,
)


# ---------------------------------------------------------------------------
# Step / tutorial dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TutorialStep:
    title: str
    description: str  # markdown supported
    target_widget: Optional[str] = None  # widget objectName to highlight
    action: Optional[str] = None  # "click", "type", "wait_for"
    action_data: Optional[str] = None
    can_skip: bool = True
    validation: Optional[Callable[[], bool]] = None


@dataclass
class Tutorial:
    id: str
    title: str
    description: str
    estimated_minutes: int
    difficulty: str  # "Beginner", "Intermediate", "Advanced"
    steps: list[TutorialStep]
    category: str  # "Getting Started", "ASIC", "FPGA", "Verification"


# ---------------------------------------------------------------------------
# Built-in tutorial library
# ---------------------------------------------------------------------------


def _first_project_steps() -> list[TutorialStep]:
    return [
        TutorialStep(
            title="Welcome to OpenForge!",
            description=(
                "This quick tour walks you through creating your first OpenForge "
                "project, writing a small Verilog module, and running synthesis. "
                "You can leave at any time with **Skip Tutorial**."
            ),
        ),
        TutorialStep(
            title="Create a new project",
            description=(
                "Click the **New Project** button on the welcome page, or use "
                "`File → New Project...`. Give it a name like `hello_forge`."
            ),
            target_widget="WelcomePanel",
            action="click",
            action_data="new_project_button",
        ),
        TutorialStep(
            title="Pick a target",
            description=(
                "OpenForge supports both ASIC and FPGA targets. For now, choose "
                "**ASIC → SkyWater 130nm** as the target technology."
            ),
            target_widget="NewProjectDialog",
        ),
        TutorialStep(
            title="Write a tiny module",
            description=(
                "Open `src/top.v` in the editor and paste a 4-bit counter. The "
                "editor highlights Verilog syntax automatically."
            ),
            target_widget="EditorPanel",
            action="type",
            action_data="counter.v",
        ),
        TutorialStep(
            title="Run synthesis",
            description=(
                "Press **F7** or click the ⚙️ button on the toolbar to run "
                "Yosys synthesis. The output appears in the console."
            ),
            target_widget="ToolbarSynthesisButton",
            action="click",
        ),
        TutorialStep(
            title="View the netlist",
            description=(
                "Once synthesis finishes, the **Netlist** dock shows the gate-"
                "level result. You can zoom and pan to inspect each cell."
            ),
            target_widget="NetlistPanel",
        ),
        TutorialStep(
            title="You're done!",
            description=(
                "That's it — you have a synthesized design. Next, try the "
                "**RTL-to-GDSII** tutorial to take it all the way to layout."
            ),
        ),
    ]


def _rtl_to_gds_steps() -> list[TutorialStep]:
    return [
        TutorialStep("Open the simple-counter example",
                     "From the welcome page, click the **Simple Counter** card to "
                     "load the example project."),
        TutorialStep("Inspect the RTL", "Open `src/counter.v` to see the 8-bit counter."),
        TutorialStep("Run synthesis", "Press **F7** to run Yosys.", target_widget="ToolbarSynthesisButton"),
        TutorialStep("Open the floorplan", "Switch to the **Floorplan** tab."),
        TutorialStep("Run place & route", "Press **F8** to run OpenROAD."),
        TutorialStep("Inspect congestion", "Use the heatmap toggle in the toolbar."),
        TutorialStep("Run DRC", "Press **F9** to run DRC with Magic."),
        TutorialStep("Run LVS", "Press **Shift+F9** to run LVS with Netgen."),
        TutorialStep("Export GDSII", "Use `Tools → Export GDSII`."),
        TutorialStep("Open the layout", "Open the GDS Viewer to admire your chip!"),
    ]


def _fpga_bitstream_steps() -> list[TutorialStep]:
    return [
        TutorialStep("Open the FPGA example", "Load the `blinky-ice40` example."),
        TutorialStep("Select your board", "Pick `iCEBreaker` from the board list."),
        TutorialStep("Run FPGA synthesis", "Use `FPGA → Synthesize`."),
        TutorialStep("Run FPGA P&R", "Use `FPGA → Place & Route` (nextpnr)."),
        TutorialStep("Generate bitstream", "Use `FPGA → Generate Bitstream`."),
        TutorialStep("Plug in the board", "Connect your iCEBreaker via USB."),
        TutorialStep("Program", "Click **Program Board**. The LED should blink!"),
    ]


def _testbench_steps() -> list[TutorialStep]:
    return [
        TutorialStep("Open a design", "Use the simple-counter example."),
        TutorialStep("Create a testbench", "Right-click `src/` → **New Testbench**."),
        TutorialStep("Generate stimulus", "Use the **Stimulus Wizard** for clock and reset."),
        TutorialStep("Add assertions", "Add a SystemVerilog assertion."),
        TutorialStep("Run simulation", "Press **F5** to run with Icarus Verilog."),
        TutorialStep("Open the waveform", "The VCD auto-loads in the Wave panel."),
        TutorialStep("Add cursors", "Drag a cursor to measure timing."),
        TutorialStep("Check coverage", "Open the Coverage report."),
    ]


def _constraints_steps() -> list[TutorialStep]:
    return [
        TutorialStep("Open constraints", "Open `constraints.sdc` in the editor."),
        TutorialStep("Define a clock", "`create_clock -period 10 [get_ports clk]`"),
        TutorialStep("Set input delay", "`set_input_delay -clock clk 1.0 [all_inputs]`"),
        TutorialStep("Run STA", "Use `Timing → Run STA`."),
        TutorialStep("Read the report", "Look at the worst negative slack."),
        TutorialStep("Fix violations", "Pipeline the slow path or relax the period."),
    ]


def _crypto_steps() -> list[TutorialStep]:
    return [
        TutorialStep("Open the AES S-Box example", "Load `aes-sbox`."),
        TutorialStep("Run constant-time check", "Use `Crypto → Constant-Time`."),
        TutorialStep("Run TVLA", "Use `Crypto → TVLA Leakage Test` with 10k traces."),
        TutorialStep("Inspect the t-statistic", "Verify |t| < 4.5 across the window."),
        TutorialStep("Run FIPS checks", "Use `Crypto → FIPS 140-3`."),
        TutorialStep("Generate the report", "Export the certification artifacts."),
    ]


def _block_steps() -> list[TutorialStep]:
    return [
        TutorialStep("Open Block Designer", "`View → Block Designer`."),
        TutorialStep("Add an IP core", "Drag an AXI uart from the IP catalog."),
        TutorialStep("Add a CPU", "Drag the PicoRV32 core."),
        TutorialStep("Auto-connect", "Click **Auto-Connect**."),
        TutorialStep("Generate wrapper", "Click **Generate Wrapper**."),
    ]


def _git_steps() -> list[TutorialStep]:
    return [
        TutorialStep("Open the Source Control panel", "Press **Ctrl+Shift+G**."),
        TutorialStep("Stage changes", "Click the + next to a modified file."),
        TutorialStep("Commit", "Type a message and press **Ctrl+Enter**."),
        TutorialStep("Push", "Click the **Push** button in the status bar."),
    ]


BUILTIN_TUTORIALS: list[Tutorial] = [
    Tutorial(
        id="first-project",
        title="Your First Project",
        description="Create a project, write Verilog, run synthesis.",
        estimated_minutes=10,
        difficulty="Beginner",
        steps=_first_project_steps(),
        category="Getting Started",
    ),
    Tutorial(
        id="rtl-to-gds",
        title="RTL to GDSII",
        description="Take a counter all the way from Verilog to a tape-out-ready layout.",
        estimated_minutes=20,
        difficulty="Intermediate",
        steps=_rtl_to_gds_steps(),
        category="ASIC",
    ),
    Tutorial(
        id="fpga-bitstream",
        title="FPGA Bitstream",
        description="Synthesize, P&R, and program an iCE40 board.",
        estimated_minutes=15,
        difficulty="Beginner",
        steps=_fpga_bitstream_steps(),
        category="FPGA",
    ),
    Tutorial(
        id="testbenches",
        title="Writing Testbenches",
        description="Author a testbench, simulate, and view the waveform.",
        estimated_minutes=25,
        difficulty="Intermediate",
        steps=_testbench_steps(),
        category="Verification",
    ),
    Tutorial(
        id="constraints",
        title="Constraints & Timing",
        description="Write SDC, run STA, and fix timing violations.",
        estimated_minutes=20,
        difficulty="Intermediate",
        steps=_constraints_steps(),
        category="ASIC",
    ),
    Tutorial(
        id="crypto",
        title="Crypto Hardware Verification",
        description="Constant-time, TVLA leakage, and FIPS 140-3 checks.",
        estimated_minutes=30,
        difficulty="Advanced",
        steps=_crypto_steps(),
        category="Verification",
    ),
    Tutorial(
        id="block-design",
        title="Block Design",
        description="Drag-drop IP integration with auto-wiring.",
        estimated_minutes=15,
        difficulty="Beginner",
        steps=_block_steps(),
        category="Getting Started",
    ),
    Tutorial(
        id="git-workflow",
        title="Git Workflow",
        description="Use the source control panel for stage/commit/push.",
        estimated_minutes=10,
        difficulty="Beginner",
        steps=_git_steps(),
        category="Getting Started",
    ),
]


def get_tutorial(tutorial_id: str) -> Optional[Tutorial]:
    for t in BUILTIN_TUTORIALS:
        if t.id == tutorial_id:
            return t
    return None


# ---------------------------------------------------------------------------
# Highlight overlay
# ---------------------------------------------------------------------------


class TutorialOverlay(QWidget):
    """Full-window dim overlay with a transparent rectangular cutout."""

    def __init__(self, parent_window: QWidget):
        super().__init__(parent_window)
        self._parent_window = parent_window
        self._target_rect: Optional[QRect] = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setGeometry(parent_window.rect())
        self.hide()

    def set_target_rect(self, rect: Optional[QRect]) -> None:
        self._target_rect = rect
        self.setGeometry(self._parent_window.rect())
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        full = self.rect()
        path = QPainterPath()
        path.addRect(full)
        if self._target_rect is not None:
            cutout = QPainterPath()
            cutout.addRoundedRect(self._target_rect.adjusted(-6, -6, 6, 6), 8, 8)
            path = path.subtracted(cutout)
        painter.fillPath(path, QColor(0, 0, 0, 170))

        if self._target_rect is not None:
            pen = QPen(QColor("#89b4fa"))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                self._target_rect.adjusted(-6, -6, 6, 6), 8, 8
            )


# ---------------------------------------------------------------------------
# Tutorial dialog
# ---------------------------------------------------------------------------


class TutorialDialog(QDialog):
    """Floating dialog showing tutorial steps with prev/next/skip controls."""

    tutorial_finished = Signal(str)  # tutorial id

    def __init__(self, tutorial: Tutorial, parent=None):
        super().__init__(parent)
        self._tutorial = tutorial
        self._index = 0
        self._overlay: Optional[TutorialOverlay] = None
        self.setWindowTitle(f"Tutorial: {tutorial.title}")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(440, 320)

        if parent is not None:
            self._overlay = TutorialOverlay(parent)

        self._build_ui()
        self._refresh()

    # ----- ui ---------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._frame = QFrame(self)
        self._frame.setObjectName("TutorialFrame")
        outer.addWidget(self._frame)

        shadow = QGraphicsDropShadowEffect(self._frame)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 200))
        self._frame.setGraphicsEffect(shadow)

        body = QVBoxLayout(self._frame)
        body.setContentsMargins(20, 18, 20, 16)
        body.setSpacing(10)

        # Header: tutorial title + difficulty
        header = QHBoxLayout()
        self._tut_title = QLabel(self._tutorial.title)
        self._tut_title.setStyleSheet(
            "color: #b4befe; font-size: 12px; font-weight: 700; "
            "letter-spacing: 1.2px; background: transparent;"
        )
        header.addWidget(self._tut_title)
        header.addStretch(1)
        self._diff = QLabel(
            f"{self._tutorial.difficulty}  •  ~{self._tutorial.estimated_minutes} min"
        )
        self._diff.setStyleSheet("color: #9399b2; font-size: 11px; background: transparent;")
        header.addWidget(self._diff)
        body.addLayout(header)

        # Step title
        self._step_title = QLabel("")
        self._step_title.setWordWrap(True)
        self._step_title.setStyleSheet(
            "color: #cdd6f4; font-size: 18px; font-weight: 700; background: transparent;"
        )
        body.addWidget(self._step_title)

        # Description
        self._desc = QTextBrowser()
        self._desc.setOpenExternalLinks(True)
        self._desc.setFrameShape(QFrame.Shape.NoFrame)
        self._desc.setStyleSheet(
            "QTextBrowser { background: transparent; color: #bac2de; "
            "font-size: 13px; border: none; }"
        )
        body.addWidget(self._desc, stretch=1)

        # Progress
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.setStyleSheet(
            """
            QProgressBar { background: #313244; border: none; border-radius: 3px; }
            QProgressBar::chunk { background: #89b4fa; border-radius: 3px; }
            """
        )
        body.addWidget(self._progress)

        # Buttons
        button_row = QHBoxLayout()
        self._skip_btn = QPushButton("Skip Tutorial")
        self._skip_btn.setFlat(True)
        self._skip_btn.clicked.connect(self.skip)
        button_row.addWidget(self._skip_btn)

        button_row.addStretch(1)

        self._prev_btn = QPushButton("◀ Back")
        self._prev_btn.clicked.connect(self.prev_step)
        button_row.addWidget(self._prev_btn)

        self._next_btn = QPushButton("Next ▶")
        self._next_btn.setDefault(True)
        self._next_btn.clicked.connect(self.next_step)
        button_row.addWidget(self._next_btn)

        body.addLayout(button_row)

        self._step_indicator = QLabel("")
        self._step_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._step_indicator.setStyleSheet(
            "color: #6c7086; font-size: 10px; background: transparent;"
        )
        body.addWidget(self._step_indicator)

        self._apply_styles()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QFrame#TutorialFrame {
                background: #1e1e2e;
                border: 1px solid #45475a;
                border-radius: 14px;
            }
            QPushButton {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
            }
            QPushButton:hover { background: #45475a; }
            QPushButton:default { background: #89b4fa; color: #1e1e2e; border: none; }
            QPushButton:default:hover { background: #b4befe; }
            QPushButton:flat {
                background: transparent; color: #9399b2; border: none;
            }
            QPushButton:flat:hover { color: #f38ba8; }
            """
        )

    # ----- navigation -------------------------------------------------------

    def next_step(self) -> None:
        if self._index >= len(self._tutorial.steps) - 1:
            self._finish()
            return
        self._index += 1
        self._refresh()

    def prev_step(self) -> None:
        if self._index == 0:
            return
        self._index -= 1
        self._refresh()

    def skip(self) -> None:
        self._finish()

    def _finish(self) -> None:
        if self._overlay is not None:
            self._overlay.hide()
        self.tutorial_finished.emit(self._tutorial.id)
        self.close()

    # ----- rendering --------------------------------------------------------

    def _refresh(self) -> None:
        step = self._tutorial.steps[self._index]
        self._step_title.setText(step.title)
        self._desc.setMarkdown(step.description)
        total = len(self._tutorial.steps)
        self._progress.setMaximum(total)
        self._progress.setValue(self._index + 1)
        self._step_indicator.setText(f"Step {self._index + 1} of {total}")
        self._prev_btn.setEnabled(self._index > 0)
        if self._index == total - 1:
            self._next_btn.setText("Finish ✓")
        else:
            self._next_btn.setText("Next ▶")
        self._highlight_target(step)

    def _highlight_target(self, step: TutorialStep) -> None:
        if self._overlay is None or step.target_widget is None:
            if self._overlay is not None:
                self._overlay.set_target_rect(None)
                self._overlay.hide()
            return
        parent = self.parentWidget()
        if parent is None:
            return
        widget = parent.findChild(QWidget, step.target_widget)
        if widget is None:
            self._overlay.set_target_rect(None)
            self._overlay.show()
            self._overlay.raise_()
            return
        top_left = widget.mapTo(parent, QPoint(0, 0))
        rect = QRect(top_left, widget.size())
        self._overlay.set_target_rect(rect)
        self._overlay.show()
        self._overlay.raise_()
        # Position our dialog near the target
        global_pos = parent.mapToGlobal(top_left)
        screen = QApplication.primaryScreen().availableGeometry()
        x = min(global_pos.x() + widget.width() + 24, screen.right() - self.width() - 20)
        y = min(global_pos.y(), screen.bottom() - self.height() - 20)
        self.move(max(20, x), max(20, y))

    # ----- close cleanup ----------------------------------------------------

    def closeEvent(self, event):
        if self._overlay is not None:
            self._overlay.hide()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Library-backed tutorial picker (Phase 7)
# ---------------------------------------------------------------------------
import json as _json  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

try:
    from openforge.tutorials.library import TUTORIALS as _LIB_TUTORIALS
except Exception:  # noqa: BLE001
    _LIB_TUTORIALS = {}

from PySide6.QtWidgets import (  # noqa: E402
    QListWidget as _QListWidget,
    QListWidgetItem as _QListWidgetItem,
    QSplitter as _QSplitter,
    QTextBrowser as _QTextBrowser2,
)


def _progress_file() -> _Path:
    import os as _os
    import sys as _sys
    if _sys.platform.startswith("win") and _os.environ.get("APPDATA"):
        return _Path(_os.environ["APPDATA"]) / "OpenForge" / "tutorial_progress.json"
    return _Path.home() / ".openforge" / "tutorial_progress.json"


def _load_progress() -> dict:
    f = _progress_file()
    if not f.exists():
        return {}
    try:
        return _json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_progress(data: dict) -> None:
    f = _progress_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(_json.dumps(data, indent=2), encoding="utf-8")


class TutorialPlayerDialog(QDialog):
    """Plays a single openforge.tutorials.library.Tutorial step-by-step."""

    def __init__(self, tutorial, parent=None) -> None:
        super().__init__(parent)
        self._tutorial = tutorial
        self._step = 0
        self.setWindowTitle(f"Tutorial - {tutorial.title}")
        self.resize(640, 520)

        lay = QVBoxLayout(self)
        self._progress = QProgressBar()
        self._progress.setRange(0, max(1, len(tutorial.steps)))
        lay.addWidget(self._progress)

        self._title_label = QLabel()
        f = QFont()
        f.setBold(True)
        f.setPointSize(13)
        self._title_label.setFont(f)
        lay.addWidget(self._title_label)

        self._body = _QTextBrowser2()
        lay.addWidget(self._body, 1)

        self._hint = QLabel()
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: #888;")
        lay.addWidget(self._hint)

        btn_row = QHBoxLayout()
        self._btn_prev = QPushButton("Previous")
        self._btn_prev.clicked.connect(self._prev)
        self._btn_next = QPushButton("Next")
        self._btn_next.clicked.connect(self._next)
        self._btn_skip = QPushButton("Skip")
        self._btn_skip.clicked.connect(self.reject)
        self._btn_highlight = QPushButton("Highlight Target")
        self._btn_highlight.clicked.connect(self._highlight)
        btn_row.addWidget(self._btn_prev)
        btn_row.addWidget(self._btn_next)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_highlight)
        btn_row.addWidget(self._btn_skip)
        lay.addLayout(btn_row)

        self._render()

    def _render(self) -> None:
        n = len(self._tutorial.steps)
        if n == 0:
            self._title_label.setText("(empty tutorial)")
            return
        step = self._tutorial.steps[self._step]
        self._progress.setValue(self._step + 1)
        self._progress.setFormat(f"Step {self._step + 1} / {n}")
        self._title_label.setText(step.title)
        self._body.setMarkdown(step.content or "")
        self._hint.setText(f"Hint: {step.hint}" if step.hint else "")
        self._btn_prev.setEnabled(self._step > 0)
        self._btn_next.setText("Finish" if self._step == n - 1 else "Next")

    def _prev(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._render()

    def _next(self) -> None:
        n = len(self._tutorial.steps)
        if self._step < n - 1:
            self._step += 1
            self._render()
            return
        prog = _load_progress()
        prog[self._tutorial.id] = {"completed": True, "last_step": n}
        _save_progress(prog)
        self.accept()

    def _highlight(self) -> None:
        step = self._tutorial.steps[self._step]
        parent = self.parentWidget()
        target = step.target_panel or step.target_widget
        if not parent or not target:
            return
        try:
            for child in parent.findChildren(QWidget):
                if child.objectName() and child.objectName().lower() == str(target).lower():
                    child.raise_()
                    child.setFocus()
                    break
        except Exception:  # noqa: BLE001
            pass


class TutorialPickerDialog(QDialog):
    """Library-driven tutorial picker grouped by persona."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OpenForge Tutorials")
        self.resize(820, 540)

        outer = QHBoxLayout(self)
        split = _QSplitter()
        outer.addWidget(split, 1)

        self._list = _QListWidget()
        split.addWidget(self._list)
        self._details = _QTextBrowser2()
        split.addWidget(self._details)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)

        prog = _load_progress()
        personas: dict = {}
        for t in _LIB_TUTORIALS.values():
            personas.setdefault(t.persona, []).append(t)

        for persona in sorted(personas):
            hdr = _QListWidgetItem(f"-- {persona.upper()} --")
            hdr.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(hdr)
            for t in personas[persona]:
                done = "[done] " if prog.get(t.id, {}).get("completed") else ""
                item = _QListWidgetItem(
                    f"  {done}{t.title}  ({t.duration_minutes} min, {t.difficulty})"
                )
                item.setData(Qt.ItemDataRole.UserRole, t.id)
                self._list.addItem(item)

        self._list.itemSelectionChanged.connect(self._on_select)
        self._list.itemDoubleClicked.connect(lambda *_: self._launch())

        btns = QVBoxLayout()
        b_start = QPushButton("Start")
        b_start.clicked.connect(self._launch)
        btns.addWidget(b_start)
        b_close = QPushButton("Close")
        b_close.clicked.connect(self.reject)
        btns.addWidget(b_close)
        btns.addStretch()
        outer.addLayout(btns)

    def _current(self):
        it = self._list.currentItem()
        if it is None:
            return None
        tid = it.data(Qt.ItemDataRole.UserRole)
        return _LIB_TUTORIALS.get(tid) if tid else None

    def _on_select(self) -> None:
        t = self._current()
        if t is None:
            self._details.setMarkdown("")
            return
        md = [
            f"# {t.title}",
            "",
            f"*{t.description}*",
            "",
            f"- Persona: **{t.persona}**",
            f"- Duration: **{t.duration_minutes} min**",
            f"- Difficulty: **{t.difficulty}**",
            f"- Prerequisites: {', '.join(t.prerequisites) or 'none'}",
            "",
            "## Steps",
            "",
        ]
        for i, s in enumerate(t.steps, 1):
            md.append(f"{i}. **{s.title}**")
        self._details.setMarkdown("\n".join(md))

    def _launch(self) -> None:
        t = self._current()
        if t is None:
            return
        dlg = TutorialPlayerDialog(t, parent=self.parent())
        dlg.exec()

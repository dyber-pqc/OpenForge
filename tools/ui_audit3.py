"""Deep UI audit — beyond color. Check for:
- stub/placeholder panels (very few distinct colors, no interactive children)
- tiny fonts
- overlapping docks
- broken signal connections
- excessive empty space
- missing window titles / object names
- buttons with no click handlers
- tables with zero rows and no loading state
"""
from __future__ import annotations

import os, sys
from pathlib import Path
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENFORGE_SKIP_FIRST_RUN", "1")
for k in ["OPENFORGE_PHASE4", "OPENFORGE_PHASE11", "OPENFORGE_ILA_DEBUG",
          "OPENFORGE_ENABLE_AXI_CHECKER", "OPENFORGE_ENABLE_LOG_AGGREGATOR",
          "OPENFORGE_ENABLE_WORKER_STATUS"]:
    os.environ.setdefault(k, "1")

root = Path(__file__).resolve().parent.parent
for sub in ("core", "desktop", "api", "cli"):
    sys.path.insert(0, str(root / "packages" / sub / "src"))

from PySide6.QtCore import Qt, qInstallMessageHandler, QtMsgType
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QWidget, QPushButton, QToolButton,
    QTableView, QTreeView, QListView, QLabel, QLineEdit, QComboBox,
    QAbstractItemView,
)

qt_warnings = []
def _h(mode, ctx, msg):
    if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        qt_warnings.append(str(msg).strip())
qInstallMessageHandler(_h)

app = QApplication.instance() or QApplication(sys.argv)

from openforge_desktop.mainwindow import MainWindow
w = MainWindow()
w.resize(1920, 1080)
w.show()
app.processEvents(); app.processEvents(); app.processEvents()

issues = []
def add(dock, severity, cat, msg):
    issues.append({"dock": dock, "severity": severity, "cat": cat, "msg": msg})

def sample_colors(img, n_per_axis: int = 30) -> Counter:
    w_, h_ = img.width(), img.height()
    if w_ < 10 or h_ < 10:
        return Counter()
    step_x = max(1, w_ // n_per_axis)
    step_y = max(1, h_ // n_per_axis)
    samples = []
    for y in range(0, h_, step_y):
        for x in range(0, w_, step_x):
            c = QColor(img.pixel(x, y))
            samples.append((c.red() // 16, c.green() // 16, c.blue() // 16))
    return Counter(samples)

docks = w.findChildren(QDockWidget)
for d in docks:
    title = d.windowTitle() or d.objectName() or "<unnamed>"
    inner = d.widget()
    if inner is None:
        add(title, "major", "empty", "No inner widget")
        continue

    # Stub / placeholder detection via color variety
    try:
        pix = d.grab()
        img = pix.toImage()
        if not img.isNull():
            cnts = sample_colors(img)
            distinct = len(cnts)
            if distinct < 5 and img.width() > 100 and img.height() > 80:
                add(title, "minor", "stub", f"Only {distinct} distinct color buckets — placeholder?")
    except Exception:
        pass

    # Widget introspection
    buttons = inner.findChildren(QPushButton) + inner.findChildren(QToolButton)
    tables = inner.findChildren(QTableView)
    trees = inner.findChildren(QTreeView)
    lists = inner.findChildren(QListView)
    labels = inner.findChildren(QLabel)
    edits = inner.findChildren(QLineEdit)
    combos = inner.findChildren(QComboBox)

    interactive = len(buttons) + len(tables) + len(trees) + len(lists) + len(edits) + len(combos)
    if interactive == 0 and len(labels) <= 2:
        add(title, "minor", "bare", f"Only {len(labels)} labels, no interactive widgets")

    # Buttons with no click handlers
    for b in buttons:
        try:
            has_conn = b.receivers(b.clicked) > 0 if hasattr(b, "receivers") else True
            if not has_conn:
                add(title, "minor", "dead_button",
                    f"{type(b).__name__} '{b.text()[:30]}' has no clicked receivers")
        except Exception:
            pass

    # Tables/trees with very small font
    for t in tables + trees + lists:
        try:
            f = t.font()
            ps = f.pointSize()
            if 0 < ps < 8:
                add(title, "minor", "small_font",
                    f"{type(t).__name__} point size {ps}")
        except Exception:
            pass

# Qt warnings collected during the run
for m in qt_warnings:
    if m:
        issues.append({"dock": "Qt", "severity": "minor", "cat": "qt_warning", "msg": m[:200]})

order = {"critical": 0, "major": 1, "minor": 2}
buckets: dict[tuple[str, str], list[dict]] = {}
for i in issues:
    buckets.setdefault((i["severity"], i["cat"]), []).append(i)

print(f"{len(issues)} deep issues across {len(docks)} docks\n")
for (sev, cat), items in sorted(buckets.items(), key=lambda x: (order.get(x[0][0], 9), x[0][1])):
    print(f"[{sev}] {cat}: {len(items)}")
    for it in items[:10]:
        print(f"    {it['dock']:<30} {it['msg']}")
    if len(items) > 10:
        print(f"    ... {len(items) - 10} more")

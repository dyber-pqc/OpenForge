"""Headless UI audit — build the main window, render every dock to a QPixmap,
sample pixels, capture Qt warnings, capture construction exceptions, find
hardcoded light colors, and report prioritized issues.

Run:  python tools/ui_audit.py
"""
from __future__ import annotations

import os
import sys
import traceback
from collections import Counter
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENFORGE_SKIP_FIRST_RUN", "1")
for k in [
    "OPENFORGE_PHASE4", "OPENFORGE_PHASE11", "OPENFORGE_ILA_DEBUG",
    "OPENFORGE_ENABLE_AXI_CHECKER", "OPENFORGE_ENABLE_LOG_AGGREGATOR",
    "OPENFORGE_ENABLE_WORKER_STATUS",
]:
    os.environ.setdefault(k, "1")

root = Path(__file__).resolve().parent.parent
for sub in ("core", "desktop", "api", "cli"):
    sys.path.insert(0, str(root / "packages" / sub / "src"))

from PySide6.QtCore import Qt, QSize, qInstallMessageHandler, QtMsgType
from PySide6.QtGui import QColor, QPixmap, QImage
from PySide6.QtWidgets import QApplication, QWidget, QDockWidget

qt_messages: list[tuple[str, str]] = []

def _msg_handler(mode, ctx, msg):
    m = str(msg).strip()
    if not m:
        return
    kind = {
        QtMsgType.QtDebugMsg: "debug",
        QtMsgType.QtInfoMsg: "info",
        QtMsgType.QtWarningMsg: "warning",
        QtMsgType.QtCriticalMsg: "critical",
        QtMsgType.QtFatalMsg: "fatal",
    }.get(mode, "?")
    qt_messages.append((kind, m))

qInstallMessageHandler(_msg_handler)
app = QApplication.instance() or QApplication(sys.argv)

issues: list[dict] = []
def add(kind, sev, where, msg, hint=""):
    issues.append({"kind": kind, "severity": sev, "where": where, "message": msg, "fix_hint": hint})

# -----------------------------------------------------------------------------
# Build main window
# -----------------------------------------------------------------------------
print("[audit] importing mainwindow...")
try:
    from openforge_desktop.mainwindow import MainWindow
except Exception as e:
    traceback.print_exc()
    sys.exit(1)

print("[audit] constructing...")
try:
    w = MainWindow()
except Exception as e:
    traceback.print_exc()
    add("startup", "critical", "MainWindow.__init__", str(e))
    sys.exit(2)

w.resize(1920, 1080)
app.processEvents()
app.processEvents()

docks = w.findChildren(QDockWidget)
print(f"[audit] {len(docks)} docks")

# -----------------------------------------------------------------------------
# Render each dock to a pixmap and sample
# -----------------------------------------------------------------------------
report_dir = root / "tools" / "ui_audit_pixmaps"
report_dir.mkdir(exist_ok=True)

def sample_pixmap(img: QImage, label: str) -> dict:
    if img.isNull():
        return {"ok": False, "reason": "null"}
    w_, h_ = img.width(), img.height()
    if w_ < 10 or h_ < 10:
        return {"ok": False, "reason": f"tiny ({w_}x{h_})"}
    # Count colors across a grid of sample points
    samples: list[QColor] = []
    step_x = max(1, w_ // 40)
    step_y = max(1, h_ // 30)
    for y in range(0, h_, step_y):
        for x in range(0, w_, step_x):
            samples.append(QColor(img.pixel(x, y)))
    colors = Counter((c.red() // 16, c.green() // 16, c.blue() // 16) for c in samples)
    dominant_key, dom_count = colors.most_common(1)[0]
    dom_pct = dom_count / len(samples)
    pure_black = sum(1 for c in samples if c.red() < 10 and c.green() < 10 and c.blue() < 10)
    pure_white = sum(1 for c in samples if c.red() > 245 and c.green() > 245 and c.blue() > 245)
    distinct = len(colors)
    return {
        "ok": True,
        "size": (w_, h_),
        "samples": len(samples),
        "dominant": dominant_key,
        "dom_pct": dom_pct,
        "pure_black_pct": pure_black / len(samples),
        "pure_white_pct": pure_white / len(samples),
        "distinct_color_buckets": distinct,
    }

for d in docks:
    title = d.windowTitle() or d.objectName() or "<unnamed>"
    inner = d.widget()
    if inner is None:
        add("dock_empty", "major", title, "Dock has no inner widget")
        continue
    try:
        inner.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        inner.resize(900, 700)
        inner.show()
        app.processEvents()
        pix = inner.grab()
        img = pix.toImage()
        inner.hide()
    except Exception as e:
        add("render", "major", title, f"grab() failed: {e}")
        continue
    s = sample_pixmap(img, title)
    if not s["ok"]:
        add("render", "minor", title, f"pixmap: {s.get('reason', '?')}")
        continue
    # Save for optional human inspection
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in title)[:60]
    img.save(str(report_dir / f"{safe}.png"))

    # Heuristic issues
    if s["pure_black_pct"] > 0.85:
        add("blank_dock", "major", title,
            f"Dock is {s['pure_black_pct']*100:.0f}% pure black — likely broken rendering or missing child widgets",
            "Inner widget may have failed to construct or has no content")
    elif s["pure_white_pct"] > 0.75:
        add("white_dock", "major", title,
            f"Dock is {s['pure_white_pct']*100:.0f}% pure white — hardcoded light theme in dark app",
            "Replace hardcoded colors with design_system palette")
    elif s["distinct_color_buckets"] < 4:
        add("flat_dock", "minor", title,
            f"Only {s['distinct_color_buckets']} distinct colors — may be placeholder",
            "Add real content")

# -----------------------------------------------------------------------------
# Check for hardcoded light-theme colors in stylesheets
# -----------------------------------------------------------------------------
BAD_COLORS = [
    "#f0f0f0", "#e8e8e8", "#ffffff",
    "background: white", "background-color: white",
    "#212529",  # Bootstrap dark gray text (wrong for dark theme)
    "#f8f9fa",  # Bootstrap light bg
]
for widget in w.findChildren(QWidget):
    ss = (widget.styleSheet() or "").lower()
    if not ss:
        continue
    parts = []
    cur = widget
    while cur is not None and len(parts) < 5:
        parts.append(cur.objectName() or type(cur).__name__)
        cur = cur.parent() if isinstance(cur.parent(), QWidget) else None
    path = " > ".join(reversed(parts))
    for bad in BAD_COLORS:
        if bad.lower() in ss:
            add("hardcoded_color", "major", path, f"{type(widget).__name__} stylesheet contains '{bad}'")
            break

# -----------------------------------------------------------------------------
# Layout presets smoke test
# -----------------------------------------------------------------------------
try:
    from openforge_desktop.layouts.presets import LAYOUT_PRESETS, apply_preset
    for name, preset in LAYOUT_PRESETS.items():
        try:
            apply_preset(w, preset)
            app.processEvents()
        except Exception as e:
            add("layout_preset", "major", f"preset:{name}", str(e))
except Exception as e:
    add("layout_module", "minor", "layouts.presets", str(e))

# -----------------------------------------------------------------------------
# Qt warnings
# -----------------------------------------------------------------------------
for kind, m in qt_messages:
    sev = "major" if kind in ("warning", "critical", "fatal") else "minor"
    add("qt_message", sev, f"qt:{kind}", m[:200])

# -----------------------------------------------------------------------------
# Report
# -----------------------------------------------------------------------------
out = root / "tools" / "ui_audit_report.txt"
order = {"critical": 0, "major": 1, "minor": 2}
buckets: dict[tuple[str, str], list[dict]] = {}
for i in issues:
    buckets.setdefault((i["severity"], i["kind"]), []).append(i)

with out.open("w", encoding="utf-8") as f:
    f.write(f"OpenForge UI audit — {len(issues)} issues, {len(docks)} docks\n\n")
    for (sev, kind), items in sorted(buckets.items(), key=lambda x: (order.get(x[0][0], 9), x[0][1])):
        f.write(f"\n=== [{sev}] {kind}: {len(items)} ===\n")
        for it in items[:80]:
            f.write(f"  - {it['where']}\n      {it['message']}\n")
            if it.get("fix_hint"):
                f.write(f"      hint: {it['fix_hint']}\n")
        if len(items) > 80:
            f.write(f"  ... and {len(items) - 80} more\n")

print(f"[audit] wrote {out}")
print(f"[audit] pixmaps in {report_dir}")
print(f"[audit] {len(issues)} issues")
for (sev, kind), items in sorted(buckets.items(), key=lambda x: (order.get(x[0][0], 9), x[0][1])):
    print(f"  [{sev}] {kind}: {len(items)}")

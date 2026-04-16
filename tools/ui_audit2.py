"""Full mainwindow rendering audit — shows the window offscreen, grabs its pixmap,
and grabs each currently-visible dock widget so we see the ACTUAL rendered state
as a user would."""
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

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDockWidget

app = QApplication.instance() or QApplication(sys.argv)

from openforge_desktop.mainwindow import MainWindow
w = MainWindow()
print(f"[audit] detected theme = {w._current_theme}")
w.resize(1920, 1080)
w.show()  # Triggers full layout + QSS cascade
app.processEvents()
app.processEvents()
app.processEvents()

out_dir = root / "tools" / "ui_audit_live"
out_dir.mkdir(exist_ok=True)

# Full window
main_pix = w.grab()
main_pix.save(str(out_dir / "_MAIN_WINDOW.png"))
print(f"main window: {main_pix.width()}x{main_pix.height()}")

def stats(img):
    w_, h_ = img.width(), img.height()
    step_x = max(1, w_ // 40)
    step_y = max(1, h_ // 30)
    samples = []
    for y in range(0, h_, step_y):
        for x in range(0, w_, step_x):
            samples.append(QColor(img.pixel(x, y)))
    n = len(samples)
    pw = sum(1 for c in samples if c.red() > 245 and c.green() > 245 and c.blue() > 245) / n
    pb = sum(1 for c in samples if c.red() < 10 and c.green() < 10 and c.blue() < 10) / n
    return pw, pb

img = main_pix.toImage()
pw, pb = stats(img)
print(f"main: {pw*100:.0f}% white, {pb*100:.0f}% black")

# Every dock — grabbed while in its real position
docks = w.findChildren(QDockWidget)
bad: list[tuple[str, float]] = []
for d in docks:
    title = d.windowTitle() or d.objectName() or "<unnamed>"
    if not d.isVisible():
        continue
    try:
        pix = d.grab()
    except Exception:
        continue
    im = pix.toImage()
    if im.isNull() or im.width() < 20:
        continue
    pw, pb = stats(im)
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in title)[:60]
    pix.save(str(out_dir / f"{safe}.png"))
    if pw > 0.5:
        bad.append((title, pw))

bad.sort(key=lambda x: -x[1])
print(f"\n{len(bad)} docks >50% white when visible in the live window:")
for t, p in bad[:20]:
    print(f"  {p*100:3.0f}%  {t}")

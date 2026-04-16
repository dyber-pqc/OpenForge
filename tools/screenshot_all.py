"""Render the main window + each activity bar group to separate screenshots.
This gives pixel-accurate views of what the user sees on each tab."""
from __future__ import annotations
import os, sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENFORGE_SKIP_FIRST_RUN", "1")
for k in ["OPENFORGE_PHASE4", "OPENFORGE_PHASE11", "OPENFORGE_ILA_DEBUG",
          "OPENFORGE_ENABLE_AXI_CHECKER", "OPENFORGE_ENABLE_LOG_AGGREGATOR",
          "OPENFORGE_ENABLE_WORKER_STATUS"]:
    os.environ.setdefault(k, "1")

root = Path(__file__).resolve().parent.parent
for sub in ("core", "desktop", "api", "cli"):
    sys.path.insert(0, str(root / "packages" / sub / "src"))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
# Clear persisted state for fresh layout
s = QSettings('Dyber', 'OpenForge EDA')
s.remove('windowState'); s.remove('geometry'); s.sync()

from openforge_desktop.mainwindow import MainWindow, DARK_THEME_QSS
app.setStyleSheet(DARK_THEME_QSS)
w = MainWindow()
w.resize(1920, 1080)
w.show()
app.processEvents(); app.processEvents(); app.processEvents()

out = root / "tools" / "screenshots"
out.mkdir(exist_ok=True)

# Default startup
pix = w.grab()
pix.save(str(out / "01_startup_project.png"))
print("saved 01_startup_project.png")

# Each activity group
bar = getattr(w, "_activity_bar", None)
if bar is None:
    print("No activity bar found!")
    sys.exit(1)

from openforge_desktop.activity_bar import DEFAULT_GROUPS
for idx, g in enumerate(DEFAULT_GROUPS, start=2):
    bar.activate(g.id)
    app.processEvents(); app.processEvents(); app.processEvents()
    pix = w.grab()
    fname = f"{idx:02d}_{g.id}.png"
    pix.save(str(out / fname))
    print(f"saved {fname} ({g.title})")

print(f"\nAll screenshots saved to {out}")

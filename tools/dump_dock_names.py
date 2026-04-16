"""Dump every dock's objectName so we can fix the activity bar mapping."""
import os, sys, pathlib
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['OPENFORGE_SKIP_FIRST_RUN'] = '1'
for k in ["OPENFORGE_PHASE4", "OPENFORGE_PHASE11", "OPENFORGE_ILA_DEBUG",
          "OPENFORGE_ENABLE_AXI_CHECKER", "OPENFORGE_ENABLE_LOG_AGGREGATOR",
          "OPENFORGE_ENABLE_WORKER_STATUS"]:
    os.environ.setdefault(k, "1")
for sub in ('core', 'desktop', 'api', 'cli'):
    sys.path.insert(0, str(pathlib.Path('packages') / sub / 'src'))
from PySide6.QtWidgets import QApplication, QDockWidget
app = QApplication(sys.argv)
from openforge_desktop.mainwindow import MainWindow
w = MainWindow()
app.processEvents()
docks = w.findChildren(QDockWidget)
print(f"{'OBJECT NAME':<45} {'TITLE':<35} {'VISIBLE'}")
print("-" * 90)
for d in sorted(docks, key=lambda d: d.objectName()):
    print(f"{d.objectName():<45} {(d.windowTitle() or '?'):<35} {d.isVisible()}")

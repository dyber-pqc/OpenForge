"""Headless test: open MainWindow, simulate "open project" + "Run Flow" click,
wait for the FullFlowWorker to finish, verify GDS produced."""
from __future__ import annotations
import os, sys, pathlib, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENFORGE_SKIP_FIRST_RUN", "1")
for sub in ("core", "desktop", "api", "cli"):
    sys.path.insert(0, str(pathlib.Path("packages") / sub / "src"))

from PySide6.QtCore import QTimer, QEventLoop
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setApplicationName("OpenForge EDA")
app.setOrganizationName("Dyber")

from openforge_desktop.mainwindow import MainWindow

w = MainWindow()
w.show()

# Open the asic-counter-sky130 project programmatically
proj_path = pathlib.Path("examples/asic-counter-sky130").resolve()
print(f"[test] Opening project: {proj_path}")
try:
    w._project_mgr.open_project(proj_path)
    app.processEvents()
    print(f"[test] Project root: {w._project_mgr.project_path}")
    src = w._project_mgr.source_files()
    print(f"[test] Source files: {len(src)}")
    for s in src[:5]:
        print(f"  {s}")
except Exception as e:
    print(f"[test] Open project failed: {e}")

# Now invoke the Run Flow handler
print("\n[test] Calling _on_run_full_flow()...")

# Override the file dialog so it doesn't pop up if the project loader fails
from openforge_desktop import mainwindow as mw_mod
class _FakeQInputDialog:
    @staticmethod
    def getText(*a, **k):
        return "counter", True
class _FakeFileDialog:
    @staticmethod
    def getOpenFileNames(*a, **k):
        return ([str(proj_path / "rtl/counter.v")], "")
    @staticmethod
    def getOpenFileName(*a, **k):
        return (str(proj_path / "constraints/counter.sdc"), "")

# Don't actually monkeypatch; just call directly.
# Watch the worker complete.
worker_finished = {"done": False, "result": None, "error": None}

def on_finished(result):
    worker_finished["done"] = True
    worker_finished["result"] = result
    print(f"[test] Flow finished: status={result.overall_status}, gds={result.gds_path}")
    QTimer.singleShot(500, app.quit)

def on_error(msg):
    worker_finished["done"] = True
    worker_finished["error"] = msg
    print(f"[test] Flow error: {msg}")
    QTimer.singleShot(500, app.quit)

def on_stage_update(stage, status):
    if status in ("success", "failed"):
        print(f"[test] [{stage}] {status}")

# Patch the worker creation to attach our test signals
original_method = w._on_run_full_flow

def patched():
    original_method()
    if hasattr(w, "_full_flow_worker") and w._full_flow_worker is not None:
        w._full_flow_worker.finished_result.connect(on_finished)
        w._full_flow_worker.error.connect(on_error)
        w._full_flow_worker.stage_update.connect(on_stage_update)

QTimer.singleShot(500, patched)
# 5-minute timeout
QTimer.singleShot(300_000, app.quit)

app.exec()

# Final report
if worker_finished["error"]:
    print(f"\n[test] FAILED: {worker_finished['error']}")
    sys.exit(1)
elif worker_finished["result"]:
    r = worker_finished["result"]
    if r.gds_path and pathlib.Path(r.gds_path).exists():
        size = pathlib.Path(r.gds_path).stat().st_size
        print(f"\n[test] PASS: GDS produced at {r.gds_path} ({size} bytes)")
        sys.exit(0)
    else:
        print(f"\n[test] FAIL: status={r.overall_status}, no GDS")
        sys.exit(2)
else:
    print("\n[test] FAIL: timeout, worker never finished")
    sys.exit(3)

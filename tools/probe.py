import os, sys, pathlib
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['OPENFORGE_SKIP_FIRST_RUN']='1'
for sub in ('core','desktop','api','cli'): sys.path.insert(0, str(pathlib.Path('packages')/sub/'src'))
from PySide6.QtWidgets import QApplication, QDockWidget
app = QApplication(sys.argv)
from openforge_desktop.mainwindow import MainWindow
w = MainWindow()
app.processEvents()
print('theme:', w._current_theme)
print('console:', type(w._console).__name__ if w._console else None)
if w._console:
    for attr in ('_output', '_input', 'widget'):
        o = getattr(w._console, attr, None)
        if callable(o):
            try:
                o = o()
            except Exception:
                o = None
        if o is not None:
            print(f'  {attr}: {type(o).__name__} ss={(o.styleSheet() or "(none)")[:80]!r}')
print()
for title in ['Console', 'Reports', 'GDS Viewer', 'Floorplan Editor', 'Testbenches']:
    for d in w.findChildren(QDockWidget):
        if d.windowTitle() == title:
            inner = d.widget()
            print(f'{title}: outer={type(d).__name__} inner={type(inner).__name__ if inner else None}')
            if inner is not None:
                print(f'  dock ss={(d.styleSheet() or "")[:80]!r}')
                print(f'  inner ss={(inner.styleSheet() or "")[:80]!r}')
            break

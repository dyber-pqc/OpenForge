import os, sys, pathlib
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['OPENFORGE_SKIP_FIRST_RUN'] = '1'
for sub in ('core', 'desktop', 'api', 'cli'):
    sys.path.insert(0, str(pathlib.Path('packages') / sub / 'src'))
from PySide6.QtWidgets import QApplication, QDockWidget
from PySide6.QtCore import QSettings
app = QApplication(sys.argv)
# Clear persisted state to force fresh layout
s = QSettings('Dyber', 'OpenForge EDA')
s.remove('windowState')
s.remove('geometry')
s.sync()
from openforge_desktop.mainwindow import MainWindow, DARK_THEME_QSS
app.setStyleSheet(DARK_THEME_QSS)
w = MainWindow()
w.show()
app.processEvents(); app.processEvents(); app.processEvents()
total = w.findChildren(QDockWidget)
visible = [d for d in total if d.isVisible()]
print(f'Total docks: {len(total)}')
print(f'Visible on startup: {len(visible)}')
print('Visible dock list:')
for d in visible:
    print(f'  - {d.windowTitle()}')
print('Activity bar:', bool(getattr(w, '_activity_bar', None)))
print('Nesting enabled:', w.isDockNestingEnabled())

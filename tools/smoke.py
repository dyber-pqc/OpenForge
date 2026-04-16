import os, sys, pathlib
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['OPENFORGE_SKIP_FIRST_RUN']='1'
for sub in ('core','desktop','api','cli'):
    sys.path.insert(0, str(pathlib.Path('packages')/sub/'src'))
from PySide6.QtWidgets import QApplication, QDockWidget
app = QApplication(sys.argv)
app.setApplicationName('OpenForge EDA')
app.setOrganizationName('Dyber')
from openforge_desktop.mainwindow import MainWindow, DARK_THEME_QSS
app.setStyleSheet(DARK_THEME_QSS)
w = MainWindow()
w.show()
app.processEvents(); app.processEvents(); app.processEvents()
print(f'theme={w._current_theme}')
print(f'docks={len(w.findChildren(QDockWidget))}')
print('CLEAN LAUNCH')

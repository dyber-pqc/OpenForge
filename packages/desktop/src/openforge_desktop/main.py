"""OpenForge EDA desktop application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon

from openforge_desktop.mainwindow import MainWindow, DARK_THEME_QSS


def main() -> int:
    """Launch the OpenForge EDA desktop application."""
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    app.setApplicationName("OpenForge EDA")
    app.setOrganizationName("Dyber")
    app.setOrganizationDomain("dyber.io")
    app.setApplicationVersion("0.1.0")

    # Apply monospace base font for the entire application
    mono_font = QFont("JetBrains Mono", 10)
    mono_font.setStyleHint(QFont.StyleHint.Monospace)

    # Apply comprehensive dark theme
    app.setStyleSheet(DARK_THEME_QSS)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

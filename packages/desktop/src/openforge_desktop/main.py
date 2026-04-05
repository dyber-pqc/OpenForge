"""OpenForge EDA desktop application entry point."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from openforge_desktop.mainwindow import DARK_THEME_QSS, MainWindow
from openforge_desktop.widgets.splash import OpenForgeSplash


def main() -> int:
    """Launch the OpenForge EDA desktop application."""
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    app.setApplicationName("OpenForge EDA")
    app.setOrganizationName("Dyber")
    app.setOrganizationDomain("dyber.io")
    app.setApplicationVersion("0.1.0")

    # Apply dark theme immediately so splash matches
    app.setStyleSheet(DARK_THEME_QSS)

    # Show splash screen
    splash = OpenForgeSplash()
    splash.show()
    app.processEvents()

    # Simulate loading stages
    stages = [
        ("Loading core libraries...", 0.15),
        ("Detecting EDA tools...", 0.30),
        ("Initializing engine wrappers...", 0.45),
        ("Loading PDK configurations...", 0.60),
        ("Setting up workspace...", 0.75),
        ("Building user interface...", 0.90),
    ]

    for status_text, progress in stages:
        splash.set_status(status_text, progress)
        app.processEvents()
        # Brief pause to show each stage (real loading will replace this)
        QTimer.singleShot(0, lambda: None)
        import time
        time.sleep(0.15)

    splash.set_status("Ready.", 1.0)
    app.processEvents()

    # Create main window
    window = MainWindow()
    window.show()
    splash.finish(window)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

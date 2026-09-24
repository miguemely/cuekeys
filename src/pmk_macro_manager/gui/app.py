"""Qt application bootstrap for the editor and the stand-alone overlay."""

import os
import signal
import sys

from .. import config as cfg


def _prepare_env():
    # Wayland compositors ignore "stay on top" and window positioning, which the
    # overlay needs. Use XWayland unless the user chose a platform explicitly.
    if sys.platform.startswith("linux") and os.environ.get("WAYLAND_DISPLAY") \
            and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def _make_app():
    _prepare_env()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    from .theme import apply as apply_theme

    apply_theme(app)
    app.setApplicationName("PMK Macro Manager")
    app.setOrganizationName("pmk-macro-manager")
    # Let Ctrl+C in the terminal close the app.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    timer = QTimer()
    timer.start(250)
    timer.timeout.connect(lambda: None)
    app._sigint_timer = timer
    return app


def _load_config(path):
    if path:
        return cfg.load(path), path
    from PySide6.QtCore import QSettings

    last = QSettings("pmk-macro-manager", "PMK Macro Manager").value("last_file")
    if last and os.path.exists(last):
        try:
            return cfg.load(last), last
        except (OSError, ValueError):
            pass
    return cfg.default_config(), None


def run_editor(path=None, port=None):
    app = _make_app()
    from ..runtime import Runtime
    from .common import RuntimeSignals
    from .editor import MainWindow

    config, path = _load_config(path)
    runtime = Runtime(config, port=port)
    signals = RuntimeSignals(runtime)
    window = MainWindow(runtime, signals, path)
    runtime.start()
    window.show()
    try:
        return app.exec()
    finally:
        runtime.stop()


def run_overlay(path=None, port=None):
    """Overlay + bridge only, no editor window (e.g. on a show machine)."""
    app = _make_app()
    from PySide6.QtWidgets import QMenu, QSystemTrayIcon

    from ..runtime import Runtime
    from .common import RuntimeSignals
    from .overlay import OverlayWindow

    config, path = _load_config(path)
    runtime = Runtime(config, port=port)
    signals = RuntimeSignals(runtime)
    overlay = OverlayWindow(runtime, signals)
    runtime.start()
    overlay.show()

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(app.style().standardIcon(app.style().StandardPixmap.SP_ComputerIcon))
        menu = QMenu()
        menu.addAction("Show / hide overlay", lambda: overlay.setVisible(not overlay.isVisible()))
        menu.addAction("Quit", app.quit)
        tray.setContextMenu(menu)
        tray.setToolTip("PMK Macro Manager overlay")
        tray.show()
        app._tray = tray
    app.setQuitOnLastWindowClosed(False)
    try:
        return app.exec()
    finally:
        runtime.stop()

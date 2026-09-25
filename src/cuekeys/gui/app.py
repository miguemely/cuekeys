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
    app.setApplicationName("CueKeys")
    app.setOrganizationName("cuekeys")
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

    from .common import app_settings

    last = app_settings().value("last_file")
    if last and os.path.exists(last):
        try:
            return cfg.load(last), last
        except (OSError, ValueError):
            pass
    return cfg.default_config(), None


def make_hub(path=None, port=None):
    """Hub for the GUI: every connected keypad, or just ``port`` when given.

    Returns (hub, session to show first). Keypads without a layout of their own
    use ``path`` (else the last file, else a blank layout).
    """
    from ..keypads import KeypadStore
    from ..runtime import Hub, Runtime

    explicit = path
    config, path = _load_config(path)
    if port:
        session = Runtime(config, port=port, store=KeypadStore())
        session.layout_path = path
        return session.hub, session
    hub = Hub(default_config=config, store=KeypadStore(), layout_loader=cfg.load)
    hub.default_path = path
    if path:
        hub._layouts[str(path)] = config
    return hub, explicit


def _first_session(hub, explicit):
    session = next(iter(hub.sessions.values()))
    if explicit and session.config is not hub.default_config:
        # A file named on the command line is what the user wants to edit.
        hub.assign_layout(session, hub.default_config, hub.default_path)
    return session


def run_editor(path=None, port=None):
    app = _make_app()
    from .common import RuntimeSignals
    from .editor import MainWindow

    hub, first = make_hub(path, port)
    signals = RuntimeSignals(hub)
    hub.start()                      # finds keypads (or adds the "No keypad" stand-in)
    session = first if port else _first_session(hub, first)
    window = MainWindow(session, signals)
    window.show()
    try:
        return app.exec()
    finally:
        hub.stop()


def run_overlay(path=None, port=None):
    """Overlays + bridges only, no editor window (e.g. on a show machine)."""
    app = _make_app()
    from PySide6.QtWidgets import QMenu, QSystemTrayIcon

    from .common import RuntimeSignals
    from .overlay import OverlayGroup

    hub, first = make_hub(path, port)
    signals = RuntimeSignals(hub)
    hub.start()
    if not port:
        _first_session(hub, first)
    overlays = OverlayGroup(hub, signals)
    overlays.show()

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(app.style().standardIcon(app.style().StandardPixmap.SP_ComputerIcon))
        menu = QMenu()
        menu.addAction("Show / hide overlay", lambda: overlays.setVisible(not overlays.isVisible()))
        menu.addAction("Quit", app.quit)
        tray.setContextMenu(menu)
        tray.setToolTip("CueKeys overlay")
        tray.show()
        app._tray = tray
    app.setQuitOnLastWindowClosed(False)
    try:
        return app.exec()
    finally:
        hub.stop()

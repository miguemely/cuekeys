#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Render the screenshots used by README.md and docs/ (docs/images/*.png).

    python scripts/screenshots.py [--out docs/images] [--scale 2]

Everything is drawn offscreen from the demo layout with fake keypads and a fake
Companion connection, so the images are reproducible, need no hardware, and
never contain anything from the machine they're made on. Re-run it after UI
changes and commit the PNGs.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

FOH, STAGE = "E6617C93E35B8C2B", "0123456789ABCDEF"

# A lighting-console page on the Companion surface (Satellite index -> button).
COMPANION_PAGE = [
    ("House\nlights", "#f5c518"), ("Stage\nwash", "#3070ff"), ("Spot 1", "#ffffff"), ("Spot 2", "#ffffff"),
    ("Strobe", "#ff2020"), ("Fog", "#8a8a8a"), ("Haze", "#6a7a8a"), ("Blackout", "#000000"),
    ("Walk-in\nmusic", "#20c050"), ("Mic 1\nmute", "#ff7000"), ("Mic 2\nmute", "#ff7000"), ("GO", "#00ff60"),
]


class FakeLink:
    connected = True

    def start(self):
        pass

    def stop(self):
        pass

    def send(self, _message):
        return True


class FakeSatellite:
    def __init__(self, host="127.0.0.1", port=16622, **_kw):
        self.host, self.port = host, int(port)
        self.devices, self.registered = {}, {}
        self.connected = True
        self.can_change_page = True

    def add_device(self, device_id, name, keys_total=16, keys_per_row=4):
        self.devices[device_id] = (name, keys_total, keys_per_row)
        self.registered[device_id] = True

    def remove_device(self, device_id):
        self.devices.pop(device_id, None)

    def key_press(self, *_a):
        pass

    def change_page(self, *_a, **_kw):
        return True

    def start(self):
        pass

    def stop(self):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT / "docs" / "images"))
    parser.add_argument("--scale", default="2", help="device pixel ratio (2 = crisp on high-DPI screens)")
    args = parser.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="cuekeys-shots-"))
    # A virtual display that is 1920x1200 after scaling. Without it the offscreen screen is
    # 800x600 / scale, and menus wrap into columns.
    factor = float(args.scale)
    screen = tmp / "offscreen.json"
    screen.write_text(json.dumps({"screens": [{"name": "Display", "x": 0, "y": 0, "width": int(1920 * factor),
                                                "height": int(1200 * factor), "logicalDpi": 96}]}))
    os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=%s" % screen
    os.environ["QT_SCALE_FACTOR"] = args.scale

    from PySide6.QtCore import QPoint, QPointF, QRectF, QSettings
    from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap, QRadialGradient
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp))
    app.setApplicationName("CueKeys")

    from cuekeys import devices
    from cuekeys.examples import example_config
    from cuekeys.gui import settings as settings_module
    from cuekeys.gui.calibration import CalibrationDialog
    from cuekeys.gui.common import RuntimeSignals
    from cuekeys.gui.editor import MainWindow
    from cuekeys.gui.overlay import OverlayGroup
    from cuekeys.gui.theme import apply as apply_theme
    from cuekeys.keypads import KeypadStore
    from cuekeys.runtime import Hub

    apply_theme(app)
    generic_dir = Path("~/.config/cuekeys/devices")          # never the real (user-named) path
    devices.user_device_dir = lambda: generic_dir
    settings_module.devices.user_device_dir = lambda: generic_dir

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scale = float(args.scale)

    def save(pixmap, name):
        path = out / name
        pixmap.save(str(path), "PNG")
        print("wrote %s (%dx%d)" % (path.relative_to(ROOT) if path.is_relative_to(ROOT) else path,
                                    pixmap.width(), pixmap.height()))

    # ---- two keypads, both "connected", one Companion server
    store = KeypadStore(tmp / "keypads.json")
    store.update(FOH, name="FOH")
    store.update(STAGE, name="Stage")
    config = example_config()
    hub = Hub(default_config=config, store=store, satellite_factory=FakeSatellite, discover=False,
              link_factory=lambda session, port: FakeLink())
    hub.scan([{"uid": FOH, "data_port": "/dev/cu.usbmodem1203", "console_port": None},
              {"uid": STAGE, "data_port": "/dev/cu.usbmodem2203", "console_port": None}])
    for uid, session in hub.sessions.items():
        session.connected, session.firmware, session.port = True, "0.1.0", "/dev/ttyACM%d" % len(uid)
    foh, stage = hub.sessions[FOH], hub.sessions[STAGE]

    companion_layer = next(i for i, layer in enumerate(config["layers"]) if layer.get("mode") == "companion")
    profile = devices.profile_for(config)
    for index, (text, color) in enumerate(COMPANION_PAGE):
        key = profile.key_from_satellite(index, 0)
        row, col = divmod(index, profile.cols)
        state = {"text": text, "color": QColor(color).getRgb()[:3], "type": "BUTTON",
                 "location": "4/%d/%d" % (row, col), "page": 4}
        if color == "#000000":
            state["text_color"] = (255, 255, 255)
        for session in (foh, stage):
            session.companion_states[(companion_layer, key)] = dict(state)
    endpoint = next(iter(hub.satellites))
    hub.page_names[(endpoint, 4)] = "CueKeys 1"
    for session in (foh, stage):
        session.companion_pages[companion_layer] = 4
    signals = RuntimeSignals(hub)

    # ---- editor
    window = MainWindow(foh, signals)
    window.setWindowTitle("demo-layout.json — CueKeys")
    window.overlays.hide()
    window.resize(1280, 800)
    window.show()
    window.layer_list.setCurrentRow(0)
    window.grid.select(10)
    app.processEvents()
    save(window.grab(), "editor.png")

    # right-click colour menu over the key it belongs to
    key = 5
    window.grid.select(key)
    app.processEvents()
    row, col = profile.key_to_cell(key, 0)
    cell = window.grid._cell_rect(row, col)
    anchor = window.grid.mapTo(window, QPoint(int(cell.center().x()), int(cell.center().y())))
    menu = window._key_menu(key, window.mapToGlobal(anchor))
    app.processEvents()
    shot = window.grab()
    menu_image = menu.grab()
    menu_h = menu_image.height() / menu_image.devicePixelRatio()
    top = min(anchor.y(), window.height() - menu_h - 12)          # keep the whole menu in the shot
    p = QPainter(shot)
    p.drawPixmap(QPointF(anchor.x(), top), menu_image)
    p.end()
    menu.close()
    save(shot, "editor-key-colours.png")

    window.layer_list.setCurrentRow(companion_layer)
    window.grid.select(profile.key_from_satellite(11, 0))
    app.processEvents()
    save(window.grab(), "editor-companion.png")

    # ---- overlays on a "desktop" backdrop
    def backdrop(width, height):
        pixmap = QPixmap(int(width * scale), int(height * scale))
        pixmap.setDevicePixelRatio(scale)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        grad = QLinearGradient(0, 0, width, height)
        grad.setColorAt(0, QColor("#1d2b4a"))
        grad.setColorAt(0.55, QColor("#3b2350"))
        grad.setColorAt(1, QColor("#0f1a2c"))
        p.fillRect(QRectF(0, 0, width, height), grad)
        glow = QRadialGradient(width * 0.2, height * 0.25, width * 0.6)
        glow.setColorAt(0, QColor(255, 170, 90, 90))
        glow.setColorAt(1, QColor(255, 170, 90, 0))
        p.fillRect(QRectF(0, 0, width, height), glow)
        p.end()
        return pixmap

    def compose(images, margin=24, gap=8):
        """Overlay windows stacked in the bottom-right corner of a backdrop."""
        widths = [i.width() / scale for i in images]
        heights = [i.height() / scale for i in images]
        width = max(widths) + 2 * margin + 120
        height = sum(heights) + gap * (len(images) - 1) + 2 * margin + 60
        canvas = backdrop(width, height)
        p = QPainter(canvas)
        y = height - margin
        for image, w, h in zip(images, widths, heights, strict=True):
            y -= h
            p.setOpacity(0.92)
            p.drawPixmap(QPointF(width - margin - w, y), image)
            y -= gap
        p.end()
        return canvas

    group = OverlayGroup(hub, signals)
    for session in (foh, stage):
        session.config.setdefault("overlay", {})["opacity"] = 0.9

    def overlay_image(session, layer):
        session.layer = layer
        overlay = group.get(session.uid)
        overlay.apply_settings()
        overlay.show()
        app.processEvents()
        return overlay.grab()

    group.restack()
    group.overlays[STAGE].set_stacking("", 0)          # single-keypad look first
    group.overlays[FOH].set_stacking("", 0)
    save(compose([overlay_image(foh, 0)]), "overlay.png")
    save(compose([overlay_image(foh, companion_layer)]), "overlay-companion.png")
    group.overlays[FOH].set_stacking("FOH", 0)
    group.overlays[STAGE].set_stacking("Stage", 0)
    save(compose([overlay_image(foh, companion_layer), overlay_image(stage, 1)]), "overlays-two-keypads.png")
    group.close()

    # ---- dialogs
    dialog = settings_module.SettingsDialog(config, window)
    dialog.resize(560, 520)
    tabs = dialog.findChild(settings_module.QTabWidget)
    for prefix, name in (("Overlay", "overlay"), ("OSC", "companion")):
        index = next(i for i in range(tabs.count()) if tabs.tabText(i).startswith(prefix))
        tabs.setCurrentIndex(index)
        dialog.show()
        app.processEvents()
        save(dialog.grab(), "settings-%s.png" % name)
    dialog.close()

    calibration = CalibrationDialog(config, foh, window, keypad=store.get(FOH), on_save=lambda *_: None)
    calibration.show()
    app.processEvents()
    save(calibration.grab(), "led-calibration.png")
    calibration.reject()

    window.overlays.close()
    window.close()
    hub.stop()


if __name__ == "__main__":
    main()

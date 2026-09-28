# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
"""Settings dialog for the device, overlay and bridge sections of a config."""

import copy
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import devices
from ..config import CORNERS

# (section path, key, kind, extra)
DEVICE_FIELDS = [
    ("profile", "Device", "profile", None),
    ("brightness", "LED brightness", "float", (0.0, 1.0)),
    ("hold_time_ms", "Hold time (ms)", "int", (50, 5000)),
    ("debounce_ms", "Debounce (ms)", "int", (0, 200)),
    ("midi_channel", "Default MIDI channel", "int", (1, 16)),
    ("keyboard_layout", "Keyboard layout", "str",
     "us, or a community layout module suffix e.g. win_de, mac_fr"),
    ("host_os", "Host OS (PRIMARY key)", "choice", ("auto", "mac", "windows", "linux")),
    ("pressed_color", "Pressed colour", "str", "#rrggbb"),
]
OVERLAY_FIELDS = [
    ("enabled", "Show overlay", "bool", None),
    ("opacity", "Opacity", "float", (0.1, 1.0)),
    ("corner", "Corner", "choice", CORNERS),
    ("margin", "Margin (px)", "int", (0, 500)),
    ("key_size", "Key size (px)", "int", (24, 200)),
    ("click_through", "Click-through (ignore mouse)", "bool", None),
    ("all_spaces", "All desktops + full-screen apps", "bool",
     "macOS: keep the overlay on every Space (Ctrl+←/→) and above full-screen apps"),
    ("screens", "Displays", "screens", None),
    ("rotation", "Keypad rotation", "choice", ("0", "90", "180", "270")),
]
MA3_FIELDS = [
    ("host", "grandMA3 host", "str", "console / onPC IP"),
    ("port", "OSC port", "int", (1, 65535)),
    ("prefix", "OSC prefix", "str", "as set in In & Out > OSC (e.g. gma3)"),
]
MA2_FIELDS = [
    ("host", "grandMA2 host", "str", "console / onPC IP"),
    ("port", "Telnet port", "int", (1, 65535)),
    ("user", "User", "str", None),
    ("password", "Password", "password", None),
]


class _ScreenPicker(QWidget):
    """Main display / all / mouse / a chosen set of displays."""

    MODES = [("Main display", "primary"), ("All displays", "all"),
             ("Display with the mouse pointer", "mouse"), ("Selected displays", "list")]

    def __init__(self, value):
        super().__init__()
        from .overlay import screen_names

        self.mode = QComboBox()
        for label, data in self.MODES:
            self.mode.addItem(label, data)
        self.list = QListWidget()
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.ElideMiddle)
        chosen = value if isinstance(value, list) else []
        names = list(screen_names().values())
        for name in names + [n for n in chosen if n not in names]:
            item = QListWidgetItem(name if name in names else "%s (not connected)" % name)
            item.setData(Qt.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if name in chosen else Qt.Unchecked)
            self.list.addItem(item)
        self.list.setFixedHeight(min(6, max(1, self.list.count())) * 28 + 10)
        mode = "list" if isinstance(value, list) else (value or "primary")
        self.mode.setCurrentIndex(max(0, self.mode.findData(mode)))
        self.mode.currentIndexChanged.connect(self._sync)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.mode)
        layout.addWidget(self.list)
        self._sync()

    def _sync(self):
        self.list.setVisible(self.mode.currentData() == "list")

    def value(self):
        mode = self.mode.currentData()
        if mode != "list":
            return mode
        chosen = [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                  if self.list.item(i).checkState() == Qt.Checked]
        return chosen or "primary"


class _Section:
    def __init__(self, data, fields, form):
        self.data = data
        self.widgets = {}
        for key, label, kind, extra in fields:
            value = data.get(key)
            if kind == "screens":
                w = _ScreenPicker(value)
            elif kind == "profile":
                w = QComboBox()
                for profile in sorted(devices.all_profiles().values(), key=lambda p: p.name):
                    label = "%s  (%d×%d%s)" % (profile.name, profile.cols, profile.rows,
                                              "" if profile.tested else ", untested")
                    w.addItem(label, profile.id)
                w.setCurrentIndex(max(0, w.findData(value or devices.DEFAULT_PROFILE)))
            elif kind == "choice":
                w = QComboBox()
                w.addItems([str(c) for c in extra])
                w.setCurrentText(str(value))
            elif kind == "bool":
                w = QCheckBox()
                w.setChecked(bool(value))
                if extra:
                    w.setToolTip(extra)
            elif kind == "int":
                w = QSpinBox()
                w.setRange(*extra)
                w.setValue(int(value or 0))
            elif kind == "float":
                w = QDoubleSpinBox()
                w.setRange(*extra)
                w.setSingleStep(0.05)
                w.setValue(float(value or 0))
            else:
                w = QLineEdit("" if value is None else str(value))
                if kind == "password":
                    w.setEchoMode(QLineEdit.Password)
                elif extra:
                    w.setPlaceholderText(extra)
            self.widgets[key] = (kind, w)
            form.addRow(label, w)

    def apply(self):
        for key, (kind, w) in self.widgets.items():
            if kind == "screens":
                self.data[key] = w.value()
            elif kind == "profile":
                self.data[key] = w.currentData()
                self.data.pop("hardware", None)
            elif kind == "choice":
                text = w.currentText()
                self.data[key] = int(text) if text.isdigit() else text
            elif kind == "bool":
                self.data[key] = w.isChecked()
            elif kind in ("int", "float"):
                self.data[key] = w.value()
            else:
                self.data[key] = w.text()


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(520, 480)
        self.result_config = copy.deepcopy(config)
        cfg = self.result_config
        bridge = cfg.setdefault("bridge", {})
        self.sections = []
        tabs = QTabWidget()

        def page(title, sections, note=None):
            w = QWidget()
            form = QFormLayout(w)
            if note:
                label = QLabel(note)
                label.setWordWrap(True)
                form.addRow(label)
            for data, fields in sections:
                self.sections.append(_Section(data, fields, form))
            tabs.addTab(w, title)
            return form

        page("Keypad", [(cfg.setdefault("device", {}), DEVICE_FIELDS)],
             "Stored in config.json on the keypad. After changing the device, use Keypad → "
             "Install / update firmware. More devices: add a profile folder to %s "
             "(see docs/devices.md)." % devices.user_device_dir())
        page("Overlay", [(cfg.setdefault("overlay", {}), OVERLAY_FIELDS)])
        page("grandMA", [(bridge.setdefault("ma3", {}), MA3_FIELDS),
                         (bridge.setdefault("ma2", {}), MA2_FIELDS)],
             "grandMA3: enable OSC input with 'Receive Command'. grandMA2: enable "
             "Telnet login in Setup > Console > Global Settings. MIDI/MSC actions go "
             "straight from the keypad over USB MIDI and need no settings here.")

        net = QWidget()
        form = QFormLayout(net)
        self.osc_edit = QPlainTextEdit(json.dumps(bridge.get("osc_targets", {}), indent=2))
        self.comp_edit = QPlainTextEdit(json.dumps(bridge.get("companion", {}), indent=2))
        form.addRow(QLabel('OSC targets: {"name": {"host": "...", "port": 8000}}'))
        form.addRow(self.osc_edit)
        form.addRow(QLabel('Companion servers: {"name": {"host": "...", "http_port": 8000, '
                           '"satellite_port": 16622}}'))
        form.addRow(self.comp_edit)
        tabs.addTab(net, "OSC && Companion")

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(box)

    def _accept(self):
        bridge = self.result_config["bridge"]
        for name, edit, keys in (("osc_targets", self.osc_edit, ("host", "port")),
                                 ("companion", self.comp_edit, ("host",))):
            try:
                value = json.loads(edit.toPlainText() or "{}")
                if not isinstance(value, dict) or not all(
                        isinstance(v, dict) and all(k in v for k in keys) for v in value.values()):
                    raise ValueError("each entry needs %s" % ", ".join(keys))
            except ValueError as err:
                QMessageBox.warning(self, "Settings", "%s: %s" % (name, err))
                return
            bridge[name] = value
        for section in self.sections:
            section.apply()
        self.accept()

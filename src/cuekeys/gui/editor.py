"""Main window: layers, key grid, key/macro editor, device + overlay control."""

import copy
import uuid
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, device, devices
from .. import config as cfg
from ..keypads import VIRTUAL_UID, short_id
from .actions import ActionListEditor
from .common import app_settings, cell_badge, cell_content, paint_key, text_color_for, to_qcolor
from .overlay import OverlayGroup
from .settings import SettingsDialog
from .theme import T, repolish

SLOT_TITLES = {"press": "Press / tap", "release": "Release", "hold": "Hold"}
SLOT_HINTS = {
    "press": "No actions yet. Add some, or Record a key combo.",
    "release": ("Runs when the key is released.\nHeld keys, MIDI notes and momentary layers\n"
                "already switch off by themselves."),
    "hold": "Add Hold actions to make this a tap/hold key:\na short tap runs Press, holding runs Hold.",
}


def swatch_icon(color, size=12):
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(255, 255, 255, 60), 1))
    p.setBrush(to_qcolor(color or "#555a66"))
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QIcon(pix)


def section(text):
    label = QLabel(text.upper())
    label.setObjectName("section")
    return label


def muted(text):
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


class ColorButton(QPushButton):
    changed = Signal(str)

    def __init__(self, allow_clear=True):
        super().__init__()
        self.value = None
        self.allow_clear = allow_clear
        self.clicked.connect(self._pick)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda _pos: self._clear())
        self.setToolTip("Click to pick, right-click to reset")
        self.set_value(None)

    def set_value(self, value):
        self.value = value
        if value:
            color = to_qcolor(value)
            self.setText(value)
            self.setStyleSheet("QPushButton { background:%s; color:%s; border-color:%s }"
                               % (color.name(), text_color_for(color).name(), color.darker(130).name()))
        else:
            self.setText("Default")
            self.setStyleSheet("")

    def _pick(self):
        color = QColorDialog.getColor(to_qcolor(self.value or "#ffffff"), self)
        if color.isValid():
            self.set_value(color.name())
            self.changed.emit(color.name())

    def _clear(self):
        if self.allow_clear:
            self.set_value(None)
            self.changed.emit("")


class KeyPad(QWidget):
    """Custom-painted keypad, laid out like the physical device (any grid size)."""

    selected = Signal(int)
    PAD = 18
    GAP = 10
    TOP = 22  # room for the USB connector hint

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setMinimumSize(340, 360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.current = 0
        self.hover = None
        self.rotation = 0
        self.profile = devices.get_profile(devices.DEFAULT_PROFILE)
        self.cells = {}
        self.badges = {}
        self.pressed = set()
        self.region_rows = 0  # rows handed to Companion on this layer (0 = none)

    def select(self, key):
        self.current = key
        self.update()
        self.selected.emit(key)

    def set_state(self, config, layer_index, companion_states, pressed=()):
        self.rotation = int(config.get("overlay", {}).get("rotation", 0))
        self.profile = devices.profile_for(config)
        keys = self.profile.keys()
        self.cells = {k: cell_content(config, layer_index, k, companion_states) for k in keys}
        self.badges = {k: cell_badge(config, layer_index, k, companion_states) for k in keys}
        self.pressed = set(pressed)
        layer = config["layers"][layer_index]
        self.region_rows = (cfg.companion_rows(layer, self.profile, self.rotation)
                            if layer.get("mode") == "companion" else 0)
        if self.current >= self.profile.num_keys:
            self.current = 0
        self.update()

    def _grid(self):
        return self.profile.display_size(self.rotation)

    def _tile(self):
        rows, cols = self._grid()
        avail_w = self.width() - 8 - 2 * self.PAD - (cols - 1) * self.GAP
        avail_h = self.height() - self.TOP - 8 - 2 * self.PAD - (rows - 1) * self.GAP
        return max(24.0, min(avail_w / cols, avail_h / rows, 150.0))

    def _chassis(self):
        rows, cols = self._grid()
        tile = self._tile()
        w = 2 * self.PAD + cols * tile + (cols - 1) * self.GAP
        h = 2 * self.PAD + rows * tile + (rows - 1) * self.GAP
        return QRectF((self.width() - w) / 2, self.TOP, w, h)

    def _cell_rect(self, row, col):
        chassis = self._chassis()
        tile = self._tile()
        return QRectF(chassis.left() + self.PAD + col * (tile + self.GAP),
                      chassis.top() + self.PAD + row * (tile + self.GAP), tile, tile)

    def _key_at(self, pos):
        rows, cols = self._grid()
        for row in range(rows):
            for col in range(cols):
                if self._cell_rect(row, col).contains(pos):
                    return self.profile.cell_to_key(row, col, self.rotation)
        return None

    def mousePressEvent(self, event):
        key = self._key_at(event.position())
        if key is not None:
            self.select(key)

    def mouseMoveEvent(self, event):
        key = self._key_at(event.position())
        if key != self.hover:
            self.hover = key
            self.setCursor(Qt.PointingHandCursor if key is not None else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, _event):
        self.hover = None
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rows, cols = self._grid()
        chassis = self._chassis()
        p.setPen(QPen(QColor(T["border"]), 1))
        p.setBrush(QColor("#0f1115"))
        p.drawRoundedRect(chassis, 18, 18)
        p.setPen(QColor(T["muted"]))
        font = p.font()
        font.setPixelSize(10)
        p.setFont(font)
        p.drawText(QRectF(chassis.left() - 60, 0, chassis.width() + 120, 20), Qt.AlignCenter,
                   "%s  ·  USB connector: %s" % (self.profile.name, self.profile.connector_side(self.rotation)))
        tile = self._tile()
        region = None
        if self.region_rows:
            top = self._cell_rect(0, 0)
            bottom = self._cell_rect(self.region_rows - 1, cols - 1)
            region = QRectF(top.topLeft(), bottom.bottomRight()).adjusted(-7, -7, 7, 7)
            p.setPen(QPen(QColor(T["success"]), 1.2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(region, 12, 12)
        for key in self.profile.keys():
            row, col = self.profile.key_to_cell(key, self.rotation)
            label, color = self.cells.get(key, ("", QColor("#000000")))
            paint_key(p, self._cell_rect(row, col), label, color, number=key,
                      selected=key == self.current, pressed=key in self.pressed,
                      hover=key == self.hover, radius=10, font_px=max(10, int(tile / 7.5)),
                      accent=T["accent"], empty=T["empty_key"], badge=self.badges.get(key))
        if region is not None:
            # Legends sit on the left edge (in the chassis margin), after the keys so
            # nothing covers them.
            self._side_label(p, region.left(), region.center().y(), "COMPANION", T["success"])
            if self.region_rows < rows:
                last = self._cell_rect(rows - 1, 0)
                first = self._cell_rect(self.region_rows, 0)
                self._side_label(p, region.left(), (first.top() + last.bottom()) / 2, "LOCAL", T["muted"])
        p.end()

    @staticmethod
    def _side_label(p, x, y, text, color):
        """Vertical legend centred on (x, y), breaking the dashed outline behind it."""
        font = p.font()
        font.setPixelSize(10)
        font.setBold(True)
        font.setLetterSpacing(font.SpacingType.AbsoluteSpacing, 1.0)
        p.setFont(font)
        metrics = p.fontMetrics()
        w, h = metrics.horizontalAdvance(text) + 10, metrics.height()
        p.save()
        p.translate(x, y)
        p.rotate(-90)
        box = QRectF(-w / 2, -h / 2, w, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#0f1115"))  # chassis colour
        p.drawRect(box)
        p.setPen(QColor(color))
        p.drawText(box, Qt.AlignCenter, text)
        p.restore()


class MainWindow(QMainWindow):
    def __init__(self, runtime, signals, path=None):
        """``runtime``: the keypad session to start with; the editor can switch
        to any keypad of its hub (toolbar picker)."""
        super().__init__()
        self.runtime = runtime            # the keypad being edited
        self.hub = runtime.hub
        self.signals = signals
        self.config = runtime.config
        path = path or runtime.layout_path
        self.path = Path(path) if path else None
        self.dirty = False
        self.layer_index = 0
        self.key = 0
        self.pressed = set()
        self.settings = app_settings()
        self.overlays = OverlayGroup(self.hub, signals)
        self.overlays.visibility_changed.connect(lambda _on: self._sync_overlay_action())

        self._build_menus()
        self._build_toolbar()
        self._build_ui()
        signals.event.connect(self._on_event)
        self._load_into_ui()
        self._refresh_keypads()
        self.overlays.show()           # each keypad's layout says whether its overlay is enabled
        self.resize(1280, 800)

    @property
    def overlay(self):
        """The overlay of the keypad being edited."""
        return self.overlays.get(self.runtime.uid)

    @property
    def keypad_uid(self):
        """Hardware id for drive/port lookups; None for the virtual keypad."""
        return None if self.runtime.uid == VIRTUAL_UID else self.runtime.uid

    # ---------------------------------------------------------------- UI
    def _build_toolbar(self):
        bar = QToolBar("Main")
        bar.setMovable(False)
        bar.setIconSize(QSize(16, 16))
        bar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(bar)
        for a in (self.act_new, self.act_open, self.act_save):
            bar.addAction(a)
        bar.addSeparator()
        bar.addAction(self.act_deploy)
        bar.widgetForAction(self.act_deploy).setObjectName("primary")
        bar.addAction(self.act_settings)
        bar.addAction(self.overlay_action)
        bar.addSeparator()
        self.keypad_combo = QComboBox()
        self.keypad_combo.setToolTip("Keypad being edited. Each keypad has its own layout, "
                                     "overlay and Companion surfaces.")
        self.keypad_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.keypad_combo.activated.connect(
            lambda i: self.switch_keypad(self.keypad_combo.itemData(i)))
        bar.addWidget(self.keypad_combo)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)
        self.pill_companion = QLabel()
        self.pill_companion.setObjectName("pill")
        self.pill_keypad = QLabel()
        self.pill_keypad.setObjectName("pill")
        # Widgets inside a toolbar are shown/hidden through their QAction.
        self.pill_companion_action = bar.addWidget(self.pill_companion)
        bar.addWidget(self.pill_keypad)

    def _build_ui(self):
        # ---- layers (left)
        self.layer_list = QListWidget()
        self.layer_list.setIconSize(QSize(12, 12))
        self.layer_list.currentRowChanged.connect(self._layer_selected)
        layer_buttons = QHBoxLayout()
        layer_buttons.setSpacing(2)
        for text, tip, slot in (("＋", "Add layer", self.add_layer), ("⧉", "Duplicate layer", self.duplicate_layer),
                                ("✕", "Remove layer", self.remove_layer),
                                ("↑", "Move up", lambda: self.move_layer(-1)),
                                ("↓", "Move down", lambda: self.move_layer(1))):
            b = QPushButton(text)
            b.setObjectName("flat")
            b.setToolTip(tip)
            b.clicked.connect(slot)
            layer_buttons.addWidget(b)
        layer_buttons.addStretch()

        self.layer_name = QLineEdit()
        self.layer_name.textEdited.connect(self._layer_edited)
        self.layer_color = ColorButton()
        self.layer_color.changed.connect(self._layer_edited)
        self.layer_mode = QComboBox()
        self.layer_mode.addItem("Local actions", "local")
        self.layer_mode.addItem("Companion surface", "companion")
        self.layer_mode.currentIndexChanged.connect(self._layer_edited)
        self.layer_target = QLineEdit()
        self.layer_target.setPlaceholderText("default")
        self.layer_target.textEdited.connect(self._layer_edited)
        self.layer_rows = QComboBox()
        self.layer_rows.currentIndexChanged.connect(self._layer_edited)
        self.layer_hint = muted("")
        props = QFormLayout()
        props.setLabelAlignment(Qt.AlignRight)
        props.addRow("Name", self.layer_name)
        props.addRow("Colour", self.layer_color)
        props.addRow("Mode", self.layer_mode)
        self.target_label = QLabel("Server")
        props.addRow(self.target_label, self.layer_target)
        self.rows_label = QLabel("Surface")
        props.addRow(self.rows_label, self.layer_rows)
        props.addRow(self.layer_hint)
        box = QGroupBox("Layer settings")
        box.setLayout(props)

        left = QWidget()
        left.setObjectName("panel")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(12, 12, 12, 12)
        lv.addWidget(section("Layers"))
        lv.addWidget(self.layer_list, 1)
        lv.addLayout(layer_buttons)
        lv.addWidget(box)

        # ---- keypad (centre)
        self.grid = KeyPad()
        self.grid.selected.connect(self._key_selected)
        self.grid_title = QLabel()
        self.grid_title.setObjectName("title")
        self.live_pill = QLabel("● live on keypad")
        self.live_pill.setObjectName("pill")
        self.live_pill.setProperty("state", "ok")
        head = QHBoxLayout()
        head.addWidget(self.grid_title)
        head.addStretch()
        head.addWidget(self.live_pill)
        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(16, 12, 16, 12)
        cv.addLayout(head)
        cv.addWidget(self.grid, 1)
        cv.addWidget(muted("Click a key to edit it. Keys pressed on the keypad light up here and on the overlay."))

        # ---- key editor (right)
        self.key_title = QLabel()
        self.key_title.setObjectName("title")
        self.key_subtitle = muted("")
        self.key_label = QLineEdit()
        self.key_label.setPlaceholderText("Shown on the overlay (optional)")
        self.key_label.textEdited.connect(self._key_edited)
        self.key_color = ColorButton()
        self.key_color.changed.connect(self._key_edited)
        key_form = QFormLayout()
        key_form.setLabelAlignment(Qt.AlignRight)
        key_form.addRow("Label", self.key_label)
        key_form.addRow("Colour", self.key_color)
        key_buttons = QHBoxLayout()
        key_buttons.setSpacing(2)
        for text, slot in (("Copy", self.copy_key), ("Paste", self.paste_key), ("Clear", self.clear_key)):
            b = QPushButton(text)
            b.setObjectName("flat")
            b.clicked.connect(slot)
            key_buttons.addWidget(b)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(self.key_title)
        titles.addWidget(self.key_subtitle)
        header.addLayout(titles)
        header.addStretch()
        header.addLayout(key_buttons)
        self.slot_tabs = QTabWidget()
        self.slot_editors = {}
        for slot in cfg.KEY_SLOTS:
            editor = ActionListEditor(self.layer_names, SLOT_HINTS[slot])
            editor.changed.connect(self._actions_changed)
            self.slot_editors[slot] = editor
            self.slot_tabs.addTab(editor, SLOT_TITLES[slot])
        self.companion_note = muted("")
        right = QWidget()
        right.setObjectName("panel")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(14, 12, 14, 12)
        rv.addLayout(header)
        rv.addLayout(key_form)
        rv.addWidget(self.companion_note)
        rv.addWidget(self.slot_tabs, 1)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([260, 480, 540])
        outer = QWidget()
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(8, 8, 8, 8)
        ov.addWidget(splitter)
        self.setCentralWidget(outer)
        self._update_status()

    def _build_menus(self):
        def action(menu, text, slot, shortcut=None):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(shortcut)
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        m = self.menuBar().addMenu("&File")
        self.act_new = action(m, "&New", self.new_file, QKeySequence.New)
        self.act_open = action(m, "&Open…", self.open_file, QKeySequence.Open)
        self.act_save = action(m, "&Save", self.save_file, QKeySequence.Save)
        action(m, "Save &As…", self.save_file_as, QKeySequence.SaveAs)
        m.addSeparator()
        self.act_settings = action(m, "Settings…", self.open_settings, QKeySequence.Preferences)
        m.addSeparator()
        action(m, "&Quit", self.close, QKeySequence.Quit)

        m = self.menuBar().addMenu("&Keypad")
        self.act_deploy = action(m, "Deploy to keypad", self.deploy, "Ctrl+D")
        self.act_deploy.setToolTip("Write this layout to the keypad (Ctrl+D)")
        action(m, "&Load layout from keypad", self.load_from_device)
        action(m, "LED colour balance…", self.calibrate_leds)
        m.addSeparator()
        action(m, "&Install / update firmware…", self.install_firmware)
        action(m, "Open CIRCUITPY drive", self.open_drive)
        action(m, "&Reload keypad", lambda: self.runtime.link.send({"t": "reload"}))
        m.addSeparator()
        self.act_rename = action(m, "Re&name keypad…", self.rename_keypad)

        m = self.menuBar().addMenu("&View")
        self.overlay_action = action(m, "Overlay", self.toggle_overlay, "Ctrl+Shift+O")
        self.overlay_action.setCheckable(True)
        self.overlay_action.setChecked(self.config.get("overlay", {}).get("enabled", True))
        self.sync_action = action(m, "Sync selected layer to keypad", lambda: None)
        self.sync_action.setCheckable(True)
        self.sync_action.setChecked(self.settings.value("sync_layer", True, type=bool))
        self.sync_action.toggled.connect(lambda on: self.settings.setValue("sync_layer", on))
        action(m, "Next layer", lambda: self._step_layer(1), "Ctrl+]")
        action(m, "Previous layer", lambda: self._step_layer(-1), "Ctrl+[")

        m = self.menuBar().addMenu("&Help")
        action(m, "About", self.show_about)

    def show_about(self):
        import PySide6
        from PySide6.QtCore import qVersion

        QMessageBox.about(
            self, "CueKeys",
            "<b>CueKeys %s</b><br>Macros, layers, MIDI/OSC, grandMA and Companion for "
            "CircuitPython macro keypads.<br><br>"
            "Free for non-commercial use under the PolyForm Noncommercial License 1.0.0; commercial "
            "use needs a commercial license (see COMMERCIAL-LICENSE.md).<br><br>"
            "Uses PySide6 %s and Qt %s under the LGPL-3.0 (source: code.qt.io), and pyserial "
            "(BSD-3-Clause). See THIRD_PARTY_NOTICES.md.<br>Not affiliated with Pimoroni, Adafruit "
            "or Bitfocus." % (__version__, PySide6.__version__, qVersion()))

    # ---------------------------------------------------------------- data
    def layer_names(self):
        return [layer.get("name", "") for layer in self.config["layers"]]

    @property
    def layer(self):
        return self.config["layers"][self.layer_index]

    def _key_cfg(self, create=False):
        keys = self.layer.setdefault("keys", {})
        key = keys.get(str(self.key))
        if key is None and create:
            key = keys[str(self.key)] = {}
        return key

    def _set_dirty(self, dirty=True):
        self.dirty = dirty
        name = self.path.name if self.path else "untitled"
        self.setWindowTitle("%s%s — CueKeys" % (name, " •" if dirty else ""))

    def _changed(self):
        self._set_dirty(True)
        self._render_grid()
        self.overlays.update()

    def _load_into_ui(self):
        self.hub.config_changed(self.config)
        self.layer_index = min(self.layer_index, len(self.config["layers"]) - 1)
        self._refresh_layers()
        self.layer_list.setCurrentRow(self.layer_index)
        self._layer_selected(self.layer_index)
        self._set_dirty(self.dirty)
        self.overlays.apply_settings()

    @staticmethod
    def _layer_item_text(index, layer):
        suffix = "   ⇄" if layer.get("mode") == "companion" else ""
        return "%d   %s%s" % (index + 1, layer.get("name", "") or "Untitled", suffix)

    def _refresh_layers(self):
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        for i, layer in enumerate(self.config["layers"]):
            item = QListWidgetItem(swatch_icon(layer.get("color")), self._layer_item_text(i, layer), self.layer_list)
            if layer.get("mode") == "companion":
                item.setToolTip("Companion surface layer")
        self.layer_list.setCurrentRow(self.layer_index)
        self.layer_list.blockSignals(False)

    def _render_grid(self):
        live = self.runtime.layer == self.layer_index
        self.grid.set_state(self.config, self.layer_index, self.runtime.companion_states,
                            self.pressed if live else ())
        self.grid_title.setText(self.layer.get("name", "") or "Untitled layer")
        self.live_pill.setVisible(live and self.runtime.connected)

    # ---------------------------------------------------------------- layers
    def _layer_selected(self, row):
        if row < 0:
            return
        self.layer_index = row
        layer = self.layer
        for w in (self.layer_name, self.layer_mode, self.layer_target, self.layer_rows):
            w.blockSignals(True)
        self.layer_name.setText(layer.get("name", ""))
        self.layer_color.set_value(layer.get("color"))
        self.layer_mode.setCurrentIndex(max(0, self.layer_mode.findData(layer.get("mode", "local"))))
        self.layer_target.setText(layer.get("companion_target", ""))
        self._populate_layer_rows()
        rows = cfg.companion_rows(layer, self._profile(), self._rotation())
        self.layer_rows.setCurrentIndex(max(0, self.layer_rows.findData(rows)))
        for w in (self.layer_name, self.layer_mode, self.layer_target, self.layer_rows):
            w.blockSignals(False)
        self._update_layer_hint()
        self._render_grid()
        self._key_selected(self.grid.current)
        # Preview the layer on the overlay / keypad while editing.
        if self.sync_action.isChecked() and self.runtime.layer != row:
            self.runtime.select_layer(row)

    def _profile(self):
        return devices.profile_for(self.config)

    def _rotation(self):
        return int(self.config.get("overlay", {}).get("rotation", 0))

    def _populate_layer_rows(self):
        """Companion surface sizes the current device allows (default first)."""
        total, cols = self._profile().display_size(self._rotation())
        order = ([total - 1] if total > 1 else []) + [total] + list(range(total - 2, 0, -1))
        self.layer_rows.clear()
        for rows in order:
            left = total - rows
            suffix = ("whole keypad" if left == 0 else
                      "bottom row stays local" if left == 1 else "bottom %d rows stay local" % left)
            self.layer_rows.addItem("%d×%d · %s" % (cols, rows, suffix), rows)

    def _update_layer_hint(self):
        companion = self.layer.get("mode") == "companion"
        for w in (self.layer_target, self.target_label, self.layer_rows, self.rows_label, self.layer_hint):
            w.setVisible(companion)
        total, cols = self._profile().display_size(self._rotation())
        rows = cfg.companion_rows(self.layer, self._profile(), self._rotation())
        self.layer_hint.setText(
            "Shows up in Companion → Surfaces as a %d×%d surface. Give it its own pages with the "
            "surface's Startup Page and Page Permissions. Empty keys in the top %d rows are "
            "controlled by Companion%s." % (cols, rows, rows, "; the rest are yours" if rows < total else ""))

    def _layer_edited(self, *_args):
        layer = self.layer
        layer["name"] = self.layer_name.text()
        if self.layer_color.value:
            layer["color"] = self.layer_color.value
        else:
            layer.pop("color", None)
        mode = self.layer_mode.currentData()
        layer["mode"] = mode
        if mode == "companion":
            layer.setdefault("companion_id", uuid.uuid4().hex[:6])
            layer["companion_rows"] = self.layer_rows.currentData()
            target = self.layer_target.text().strip()
            if target:
                layer["companion_target"] = target
            else:
                layer.pop("companion_target", None)
        self._update_layer_hint()
        item = self.layer_list.item(self.layer_index)
        if item is not None:
            item.setText(self._layer_item_text(self.layer_index, layer))
            item.setIcon(swatch_icon(layer.get("color")))
        self.hub.config_changed(self.config)
        self._update_status()
        self._changed()

    def add_layer(self):
        self.config["layers"].append({"name": "Layer %d" % (len(self.config["layers"]) + 1),
                                      "mode": "local", "keys": {}})
        self.layer_index = len(self.config["layers"]) - 1
        self._layers_changed()

    def duplicate_layer(self):
        layer = copy.deepcopy(self.layer)
        layer["name"] = layer.get("name", "") + " copy"
        layer.pop("companion_id", None)
        if layer.get("mode") == "companion":
            layer["companion_id"] = uuid.uuid4().hex[:6]
        self.config["layers"].insert(self.layer_index + 1, layer)
        self.layer_index += 1
        self._layers_changed()

    def remove_layer(self):
        if len(self.config["layers"]) <= 1:
            return
        if QMessageBox.question(self, "Remove layer",
                                "Remove layer '%s'?" % self.layer.get("name")) != QMessageBox.Yes:
            return
        del self.config["layers"][self.layer_index]
        self.layer_index = max(0, self.layer_index - 1)
        self._layers_changed()

    def move_layer(self, step):
        layers = self.config["layers"]
        new = self.layer_index + step
        if 0 <= new < len(layers):
            layers[self.layer_index], layers[new] = layers[new], layers[self.layer_index]
            self.layer_index = new
            self._layers_changed()

    def _layers_changed(self):
        self.hub.config_changed(self.config)
        self._update_status()
        self._refresh_layers()
        self._layer_selected(self.layer_index)
        self._changed()

    def _step_layer(self, step):
        self.layer_list.setCurrentRow((self.layer_index + step) % len(self.config["layers"]))

    # ---------------------------------------------------------------- keys
    def _key_selected(self, key):
        self.key = key
        key_cfg = self._key_cfg() or {}
        self.key_title.setText("Key %d" % key)
        self.key_subtitle.setText("on layer “%s”" % (self.layer.get("name", "") or "Untitled"))
        rotation = int(self.config.get("overlay", {}).get("rotation", 0))
        companion_key = (cfg.in_companion_region(self.layer, key, self._profile(), rotation)
                         and not cfg.key_is_assigned(key_cfg))
        self.companion_note.setVisible(companion_key)
        self.companion_note.setText("Controlled by Companion. Add actions here to take this key over locally.")
        self.key_label.setText(key_cfg.get("label", ""))
        self.key_color.set_value(key_cfg.get("color"))
        # Editors mutate these lists in place; they are pruned on save/deploy.
        target = self._key_cfg(create=True)
        for slot, editor in self.slot_editors.items():
            editor.set_actions(target.setdefault(slot, []))
        self.slot_tabs.setTabText(2, "Hold (%d)" % len(target["hold"]) if target["hold"] else "Hold")

    def _key_edited(self, *_args):
        key = self._key_cfg(create=True)
        text = self.key_label.text()
        if text:
            key["label"] = text
        else:
            key.pop("label", None)
        if self.key_color.value:
            key["color"] = self.key_color.value
        else:
            key.pop("color", None)
        self._changed()

    def _actions_changed(self):
        hold = self._key_cfg(create=True).get("hold") or []
        self.slot_tabs.setTabText(2, "Hold (%d)" % len(hold) if hold else "Hold")
        self._changed()

    def clear_key(self):
        self.layer.setdefault("keys", {}).pop(str(self.key), None)
        self._key_selected(self.key)
        self._changed()

    def copy_key(self):
        self._clipboard = copy.deepcopy(self._key_cfg() or {})

    def paste_key(self):
        data = getattr(self, "_clipboard", None)
        if data is not None:
            self.layer.setdefault("keys", {})[str(self.key)] = copy.deepcopy(data)
            self._key_selected(self.key)
            self._changed()

    # ---------------------------------------------------------------- runtime
    def _on_event(self, name, data):
        if name == "keypads":
            self._keypads_changed(data)
            return
        if data.get("keypad", self.runtime.uid) != self.runtime.uid:
            if name == "status":
                self._refresh_keypads()
            return
        if name == "key":
            (self.pressed.add if data["pressed"] else self.pressed.discard)(data["key"])
            self._render_grid()
        elif name == "layer":
            self.pressed.clear()
            self._render_grid()
        elif name == "companion":
            if "layer" in data and data["layer"] == self.layer_index:
                self._render_grid()
            self._update_status()
        elif name == "status":
            if not data.get("connected"):
                self.pressed.clear()
            self._update_status()
            self._refresh_keypads()
        elif name == "log":
            self.statusBar().showMessage(data.get("message", ""), 8000)

    @staticmethod
    def _set_pill(pill, text, state, tip=""):
        pill.setText(text)
        pill.setToolTip(tip)
        pill.setProperty("state", state)
        repolish(pill)

    # ---------------------------------------------------------------- keypads
    def _keypad_text(self, session):
        if session.uid == VIRTUAL_UID:
            return "No keypad"
        return "%s %s" % ("●" if session.connected else "○", session.name)

    def _refresh_keypads(self):
        combo = self.keypad_combo
        combo.blockSignals(True)
        combo.clear()
        for uid, session in list(self.hub.sessions.items()):
            combo.addItem(self._keypad_text(session), uid)
            combo.setItemData(combo.count() - 1,
                              "%s\n%s" % (session.name, uid if uid != VIRTUAL_UID else
                                           "Plug in a keypad to edit it"), Qt.ToolTipRole)
        combo.setCurrentIndex(max(0, combo.findData(self.runtime.uid)))
        combo.blockSignals(False)
        self.act_rename.setEnabled(self.runtime.uid != VIRTUAL_UID)

    def _keypads_changed(self, data):
        removed = data.get("removed")
        if removed and removed == self.runtime.uid and self.hub.sessions:
            # e.g. the virtual stand-in went away because a real keypad arrived:
            # keep editing the same layout on it when it uses that layout.
            sessions = list(self.hub.sessions.values())
            same = [s for s in sessions if s.config is self.config]
            self._bind(same[0] if same else sessions[0], force=True)
        self._refresh_keypads()
        self._update_status()

    def switch_keypad(self, uid):
        session = self.hub.sessions.get(uid)
        if session is None or session is self.runtime:
            return
        if session.config is not self.config and not self._confirm_discard():
            self._refresh_keypads()          # put the picker back
            return
        self._bind(session)

    def _bind(self, session, force=False):
        """Edit ``session``'s keypad (and its layout)."""
        self.runtime = session
        self.pressed = {k for k in session.pressed}
        if session.config is not self.config or force:
            if session.config is not self.config:
                self.config = session.config
                self.dirty = False
                self.layer_index = 0
            path = session.layout_path
            self.path = Path(path) if path else self.path if force else None
            self._load_into_ui()
        self.overlay_action.setChecked(self.config.get("overlay", {}).get("enabled", True))
        self._refresh_keypads()
        self._update_status()
        self._render_grid()

    def rename_keypad(self):
        from PySide6.QtWidgets import QInputDialog

        if self.runtime.uid == VIRTUAL_UID:
            return
        name, ok = QInputDialog.getText(
            self, "Rename keypad",
            "Name for keypad %s (shown here, on the overlay and in Companion):" % short_id(self.runtime.uid),
            text=self.hub.store.get(self.runtime.uid).get("name", "") if self.hub.store else "")
        if ok:
            self.hub.rename(self.runtime.uid, name)

    def _sync_overlay_action(self):
        overlay = self.overlay
        self.overlay_action.setChecked(bool(overlay and overlay.isVisible()))

    def _update_status(self):
        rt = self.runtime
        if rt.uid == VIRTUAL_UID:
            self._set_pill(self.pill_keypad, "○ Keypad", "bad", "No keypad connected")
        elif rt.connected:
            self._set_pill(self.pill_keypad, "● Keypad", "ok",
                           "%s (%s)\n%s, firmware %s" % (rt.name, rt.uid, rt.port, rt.firmware or "?"))
        else:
            self._set_pill(self.pill_keypad, "○ Keypad", "bad", "%s is not connected" % rt.name)
        if rt.satellites:
            states = {t: rt.companion_status(t) for t in rt.satellites}
            worst = "offline" if "offline" in states.values() else (
                "busy" if "busy" in states.values() else "online")
            pill_state = {"online": "ok", "busy": "warn", "offline": "bad"}[worst]
            tip = "\n".join("%s: %s" % item for item in states.items())
            self._set_pill(self.pill_companion, "● Companion", pill_state, tip)
            self.pill_companion_action.setVisible(True)
        else:
            self.pill_companion_action.setVisible(False)
        if hasattr(self, "live_pill"):
            self.live_pill.setVisible(rt.connected and rt.layer == self.layer_index)

    def toggle_overlay(self):
        on = self.overlay_action.isChecked()
        self.config.setdefault("overlay", {})["enabled"] = on
        self.overlays.setVisible(True)        # re-applies every keypad's "enabled"
        self._set_dirty(True)

    # ---------------------------------------------------------------- files
    def _confirm_discard(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, "Unsaved changes", "Save changes first?",
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if answer == QMessageBox.Save:
            return self.save_file()
        return answer == QMessageBox.Discard

    def _replace_config(self, config, path):
        """Give the current keypad a different layout (other keypads keep theirs)."""
        self.config = config
        self.path = Path(path) if path else None
        self.dirty = False
        self.layer_index = 0
        self.hub.assign_layout(self.runtime, config, str(self.path) if self.path else None)
        self._load_into_ui()
        self.overlay_action.setChecked(config.get("overlay", {}).get("enabled", True))
        if path:
            self.settings.setValue("last_file", str(path))

    def new_file(self):
        if self._confirm_discard():
            self._replace_config(cfg.default_config(), None)

    def open_file(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open layout", "", "Layouts (*.json)")
        if path:
            self.open_path(path)

    def open_path(self, path):
        try:
            config = cfg.load(path)
        except (OSError, ValueError) as err:
            QMessageBox.critical(self, "Open", "Could not open %s:\n%s" % (path, err))
            return
        self._replace_config(config, path)
        problems = cfg.validate(config)
        if problems:
            QMessageBox.warning(self, "Layout problems", "\n".join(problems[:20]))

    def save_file(self):
        if self.path is None:
            return self.save_file_as()
        try:
            cfg.save(self.config, self.path)
        except OSError as err:
            QMessageBox.critical(self, "Save", str(err))
            return False
        self.settings.setValue("last_file", str(self.path))
        if self.runtime.layout_path != str(self.path):
            self.hub.assign_layout(self.runtime, self.config, str(self.path))
        self._set_dirty(False)
        self.statusBar().showMessage("Saved %s" % self.path, 4000)
        return True

    def save_file_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save layout", "layout.json", "Layouts (*.json)")
        if not path:
            return False
        self.path = Path(path)
        return self.save_file()

    def open_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            new = dialog.result_config
            self.config.clear()
            self.config.update(new)
            self.hub.config_changed(self.config)
            self.overlays.apply_settings()
            self.overlay_action.setChecked(self.config["overlay"].get("enabled", True))
            # The device (grid size) may have changed: refresh layer + key panels.
            self._layer_selected(self.layer_index)
            self._set_dirty(True)
            problems = cfg.validate(cfg.prune(self.config))
            if problems:
                QMessageBox.warning(self, "Layout problems",
                                    "Some keys don't exist on this device:\n" + "\n".join(problems[:15]))

    # ---------------------------------------------------------------- device
    def deploy(self):
        problems = cfg.validate(cfg.prune(self.config))
        if problems:
            QMessageBox.warning(self, "Fix these first", "\n".join(problems[:20]))
            return
        try:
            target = device.deploy_config(self.config, uid=self.keypad_uid, keypad=self.runtime.settings)
        except (OSError, RuntimeError) as err:
            QMessageBox.critical(self, "Deploy", str(err))
            return
        self.statusBar().showMessage("Deployed to %s — keypad is reloading" % target, 6000)

    def load_from_device(self):
        if not self._confirm_discard():
            return
        try:
            config = device.read_device_config(uid=self.keypad_uid)
        except (OSError, RuntimeError, ValueError) as err:
            QMessageBox.critical(self, "Load from keypad", str(err))
            return
        # The keypad copy has no bridge/overlay settings; keep the current ones.
        config["bridge"] = copy.deepcopy(self.config.get("bridge", {}))
        config["overlay"] = copy.deepcopy(self.config.get("overlay", {}))
        self._replace_config(config, None)
        self._set_dirty(True)

    def calibrate_leds(self):
        from .calibration import CalibrationDialog

        if self.keypad_uid and self.hub.store is not None:
            # Calibration belongs to the physical keypad, not the (shareable) layout.
            def save(gamma, balance):
                self.hub.store.update(self.keypad_uid, led_gamma=gamma, led_balance=balance)

            if CalibrationDialog(self.config, self.runtime, self, keypad=self.runtime.settings,
                                 on_save=save).exec():
                self.statusBar().showMessage(
                    "Colour balance saved for %s. Deploy (Ctrl+D) to keep it after the keypad "
                    "restarts." % self.runtime.name, 8000)
            return
        before = (self.config["device"].get("led_gamma"), self.config["device"].get("led_balance"))
        if CalibrationDialog(self.config, self.runtime, self).exec():
            after = (self.config["device"].get("led_gamma"), self.config["device"].get("led_balance"))
            if after != before:
                self._set_dirty(True)
                self.statusBar().showMessage(
                    "Colour balance saved to the layout. Deploy (Ctrl+D) to keep it after the "
                    "keypad restarts.", 8000)

    def install_firmware(self):
        try:
            drive = device.pick_drive(uid=self.keypad_uid)
        except (OSError, RuntimeError) as err:
            QMessageBox.critical(self, "Install firmware", str(err))
            return
        info = device.board_info(drive)
        profile = self._profile()
        board = device.board_id(drive)
        warning = ""
        if board and profile.board_ids and board not in profile.board_ids:
            others = ", ".join(p.name for p in devices.match_board(board)) or "none"
            warning = ("\n\n⚠ This board (%s) doesn't match the layout's device, %s. Matching "
                       "profiles: %s. Change it in Settings → Keypad first if that's wrong."
                       % (board, profile.name, others))
        if QMessageBox.question(
                self, "Install firmware",
                "Copy CueKeys firmware for %s to\n%s\n%s\n\n"
                "Existing code.py/boot.py will be replaced.%s" % (profile.name, drive, info, warning)
        ) != QMessageBox.Yes:
            return
        try:
            device.install_firmware(drive, profile=profile)
            device.deploy_config(self.config, drive, keypad=self.runtime.settings)
            missing = device.missing_libraries(drive, profile)
        except OSError as err:
            QMessageBox.critical(self, "Install firmware", str(err))
            return
        msg = "Firmware installed. Unplug and replug the keypad once so boot.py can " \
              "enable the serial data port."
        if missing:
            msg += ("\n\nMissing libraries in lib/: %s\nDownload the firmware bundle from the "
                    "releases page (or run scripts/build_firmware_bundle.py) and copy its lib "
                    "folder to the drive." % ", ".join(missing))
        QMessageBox.information(self, "Install firmware", msg)

    def open_drive(self):
        try:
            drive = device.pick_drive(uid=self.keypad_uid)
        except (OSError, RuntimeError) as err:
            QMessageBox.critical(self, "Open drive", str(err))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(drive)))

    # ---------------------------------------------------------------- close
    def closeEvent(self, event):
        if not self._confirm_discard():
            event.ignore()
            return
        self.overlays.close()
        event.accept()


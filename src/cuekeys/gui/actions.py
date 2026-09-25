"""Widgets for editing lists of actions (macros)."""

import copy
import json
import sys

from PySide6.QtCore import QElapsedTimer, Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import ACTION_SPECS, default_action, describe_action, validate_action
from ..keycodes import KEYCODES, format_combo, parse_combo
from .theme import ACTION_CATEGORY, CATEGORY_COLORS

_ICONS = {}


def category_icon(kind):
    """Small rounded colour tag identifying the action's category."""
    category = ACTION_CATEGORY.get(kind, "keyboard")
    if category not in _ICONS:
        from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

        pix = QPixmap(12, 12)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(CATEGORY_COLORS[category]))
        p.drawRoundedRect(1, 1, 10, 10, 3, 3)
        p.end()
        _ICONS[category] = QIcon(pix)
    return _ICONS[category]


class ActionForm(QWidget):
    """Form for one action, generated from ``ACTION_SPECS``."""

    changed = Signal()

    def __init__(self, layer_names_fn, parent=None):
        super().__init__(parent)
        self.layer_names_fn = layer_names_fn
        self.action = None
        self.editors = {}
        self.form = QFormLayout(self)
        self.error = QLabel()
        self.error.setStyleSheet("color: #d04040")
        self.error.setWordWrap(True)

    def set_action(self, action):
        self.action = action
        while self.form.rowCount():
            self.form.removeRow(0)
        self.editors = {}
        self.error = QLabel()
        self.error.setStyleSheet("color: #d04040")
        self.error.setWordWrap(True)
        if action is None:
            return
        spec = ACTION_SPECS[action["type"]]
        self.form.addRow(QLabel("<b>%s</b>" % spec["label"]))
        for field in spec["fields"]:
            editor = self._make_editor(field, action.get(field["name"]))
            if field.get("help"):
                editor.setToolTip(field["help"])
            self.editors[field["name"]] = (field, editor)
            self.form.addRow(field["label"], editor)
        self.form.addRow(self.error)
        self._validate()

    # ---------------------------------------------------------------- editors
    def _make_editor(self, field, value):
        kind = field["kind"]
        if kind == "choice":
            w = QComboBox()
            w.addItems(list(field["choices"]))
            w.setCurrentText(str(value if value is not None else field["default"]))
            w.currentTextChanged.connect(self._commit)
        elif kind == "layer":
            w = QComboBox()
            for i, name in enumerate(self.layer_names_fn()):
                w.addItem("%d: %s" % (i, name), i)
            w.setCurrentIndex(max(0, int(value or 0)))
            w.currentIndexChanged.connect(self._commit)
        elif kind == "int" and not field["optional"]:
            w = QSpinBox()
            w.setRange(field["min"] if field["min"] is not None else -(2 ** 31),
                       field["max"] if field["max"] is not None else 2 ** 31 - 1)
            w.setValue(int(value if value is not None else field["default"] or 0))
            w.valueChanged.connect(self._commit)
        elif kind == "int":
            w = QLineEdit("" if value is None else str(value))
            w.setPlaceholderText("(none)")
            w.setValidator(QIntValidator(field["min"] or 0, field["max"] or 2 ** 31 - 1))
            w.textChanged.connect(self._commit)
        elif kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
            w.toggled.connect(self._commit)
        elif kind == "text":
            w = QPlainTextEdit(value or "")
            w.setFixedHeight(70)
            w.textChanged.connect(self._commit)
        elif kind == "keys":
            w = QLineEdit(format_combo(value or []))
            w.setPlaceholderText("e.g. PRIMARY+SHIFT+S")
            w.setCompleter(QCompleter(KEYCODES, w))
            w.completer().setCaseSensitivity(Qt.CaseInsensitive)
            w.textChanged.connect(self._commit)
        elif kind == "json":
            w = QLineEdit("" if value is None else json.dumps(value))
            w.setPlaceholderText('e.g. ["Go+ Executor 1", 1, 0.5]')
            w.textChanged.connect(self._commit)
        else:
            w = QLineEdit("" if value is None else str(value))
            w.textChanged.connect(self._commit)
        return w

    def _read(self, field, w):
        kind = field["kind"]
        if kind == "choice":
            return w.currentText()
        if kind == "layer":
            return w.currentData()
        if kind == "int" and isinstance(w, QSpinBox):
            return w.value()
        if kind == "int":
            return int(w.text()) if w.text().strip() else None
        if kind == "bool":
            return w.isChecked()
        if kind == "text":
            return w.toPlainText()
        if kind == "keys":
            return parse_combo(w.text())
        if kind == "json":
            text = w.text().strip()
            return json.loads(text) if text else None
        text = w.text()
        return text if text or not field["optional"] else None

    def _commit(self, *_args):
        if self.action is None:
            return
        problems = []
        for name, (field, w) in self.editors.items():
            try:
                value = self._read(field, w)
            except ValueError as err:
                problems.append("%s: %s" % (field["label"], err))
                continue
            if value is None or (value == "" and field["optional"]):
                self.action.pop(name, None)
            else:
                self.action[name] = value
        self._validate(problems)
        self.changed.emit()

    def _validate(self, problems=()):
        problems = list(problems) + validate_action(self.action, "action",
                                                    max(1, len(self.layer_names_fn())))
        self.error.setText("\n".join(p.replace("action: ", "") for p in problems))


class ActionListEditor(QWidget):
    """Ordered list of actions with add/remove/reorder and an inline form."""

    changed = Signal()

    def __init__(self, layer_names_fn, empty_hint="No actions yet — click Add or Record.", parent=None):
        super().__init__(parent)
        self.actions = []
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        self.form = ActionForm(layer_names_fn)
        self.form.changed.connect(self._form_changed)
        self.empty = QLabel(empty_hint)
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.list)
        self.stack.addWidget(self.empty)

        add = QPushButton("＋ Add")
        add.setObjectName("primary")
        menu = QMenu(add)
        current = None
        for kind, spec in ACTION_SPECS.items():
            category = ACTION_CATEGORY.get(kind)
            if current is not None and category != current:
                menu.addSeparator()
            current = category
            menu.addAction(category_icon(kind), spec["label"],
                           lambda k=kind: self.add(default_action(k)))
        add.setMenu(menu)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        record = QPushButton("● Record")
        record.setToolTip("Record key combos by typing them")
        record.clicked.connect(self.record)
        buttons.addWidget(record)
        buttons.addStretch()
        for text, tip, slot in (("⧉", "Duplicate", self.duplicate), ("✕", "Remove", self.remove),
                                ("↑", "Move up", lambda: self.move(-1)),
                                ("↓", "Move down", lambda: self.move(1))):
            b = QPushButton(text)
            b.setObjectName("flat")
            b.setToolTip(tip)
            b.clicked.connect(slot)
            buttons.addWidget(b)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.addWidget(self.stack, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.form)

    def set_actions(self, actions):
        """Edit ``actions`` in place (the list object is shared with the config)."""
        self.actions = actions
        self._refresh()
        self.list.blockSignals(True)
        self.list.setCurrentRow(0 if actions else -1)
        self.list.blockSignals(False)
        self._select(self.list.currentRow())

    def _refresh(self):
        row = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        for action in self.actions:
            QListWidgetItem(category_icon(action.get("type")), describe_action(action), self.list)
        self.list.blockSignals(False)
        self.stack.setCurrentWidget(self.list if self.actions else self.empty)
        if 0 <= row < len(self.actions):
            self.list.setCurrentRow(row)

    def _select(self, row):
        self.form.set_action(self.actions[row] if 0 <= row < len(self.actions) else None)

    def _form_changed(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.actions):
            self.list.item(row).setText(describe_action(self.actions[row]))
        self.changed.emit()

    def add(self, action):
        row = self.list.currentRow() + 1 if self.actions else 0
        self.actions.insert(row, action)
        self._refresh()
        self.list.setCurrentRow(row)
        self.changed.emit()

    def duplicate(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.actions):
            self.add(copy.deepcopy(self.actions[row]))

    def remove(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.actions):
            del self.actions[row]
            self._refresh()
            self.list.setCurrentRow(min(row, len(self.actions) - 1))
            if not self.actions:
                self.form.set_action(None)
            self.changed.emit()

    def move(self, step):
        row = self.list.currentRow()
        new = row + step
        if 0 <= row < len(self.actions) and 0 <= new < len(self.actions):
            self.actions[row], self.actions[new] = self.actions[new], self.actions[row]
            self._refresh()
            self.list.setCurrentRow(new)
            self.changed.emit()

    def record(self):
        dialog = RecordDialog(self)
        if dialog.exec() == QDialog.Accepted:
            for action in dialog.actions():
                self.add(action)


# ------------------------------------------------------------------ recorder
_QT_KEYS = {
    Qt.Key_Return: "ENTER", Qt.Key_Enter: "ENTER", Qt.Key_Escape: "ESCAPE",
    Qt.Key_Backspace: "BACKSPACE", Qt.Key_Tab: "TAB", Qt.Key_Space: "SPACEBAR",
    Qt.Key_Insert: "INSERT", Qt.Key_Delete: "DELETE", Qt.Key_Home: "HOME",
    Qt.Key_End: "END", Qt.Key_PageUp: "PAGE_UP", Qt.Key_PageDown: "PAGE_DOWN",
    Qt.Key_Up: "UP_ARROW", Qt.Key_Down: "DOWN_ARROW", Qt.Key_Left: "LEFT_ARROW",
    Qt.Key_Right: "RIGHT_ARROW", Qt.Key_Minus: "MINUS", Qt.Key_Equal: "EQUALS",
    Qt.Key_BracketLeft: "LEFT_BRACKET", Qt.Key_BracketRight: "RIGHT_BRACKET",
    Qt.Key_Backslash: "BACKSLASH", Qt.Key_Semicolon: "SEMICOLON",
    Qt.Key_Apostrophe: "QUOTE", Qt.Key_QuoteLeft: "GRAVE_ACCENT",
    Qt.Key_Comma: "COMMA", Qt.Key_Period: "PERIOD", Qt.Key_Slash: "FORWARD_SLASH",
    Qt.Key_CapsLock: "CAPS_LOCK", Qt.Key_Print: "PRINT_SCREEN", Qt.Key_Pause: "PAUSE",
}
_DIGITS = ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"]
_MODIFIER_KEYS = {Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr}


def qt_key_name(key):
    if Qt.Key_A <= key <= Qt.Key_Z:
        return chr(key)
    if Qt.Key_0 <= key <= Qt.Key_9:
        return _DIGITS[key - Qt.Key_0]
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return "F%d" % (key - Qt.Key_F1 + 1)
    return _QT_KEYS.get(key)


class _Capture(QLabel):
    captured = Signal(list, int)

    def __init__(self):
        super().__init__("Click here, then type the key combos to record…")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(60)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("border: 2px dashed #888; border-radius: 6px")
        self.timer = QElapsedTimer()

    def keyPressEvent(self, event):
        key = event.key()
        if key in _MODIFIER_KEYS or event.isAutoRepeat():
            return
        name = qt_key_name(key)
        if name is None:
            return
        mods = event.modifiers()
        keys = []
        # Qt swaps Control/Meta on macOS; Qt.ControlModifier is Cmd there.
        if mods & Qt.ControlModifier:
            keys.append("PRIMARY")
        if mods & Qt.MetaModifier:
            keys.append("CONTROL" if sys.platform == "darwin" else "GUI")
        if mods & Qt.AltModifier:
            keys.append("ALT")
        if mods & Qt.ShiftModifier:
            keys.append("SHIFT")
        keys.append(name)
        elapsed = self.timer.restart() if self.timer.isValid() else 0
        if not self.timer.isValid():
            self.timer.start()
        self.captured.emit(keys, elapsed)

    def focusNextPrevChild(self, _next):
        return False  # keep Tab for recording


class RecordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Record macro")
        self._actions = []
        self.capture = _Capture()
        self.capture.captured.connect(self._captured)
        self.keep_delays = QCheckBox("Keep delays between keys")
        self.keep_delays.toggled.connect(self._render)
        self.preview = QListWidget()
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.capture)
        layout.addWidget(self.preview)
        row = QHBoxLayout()
        row.addWidget(self.keep_delays)
        row.addStretch()
        row.addWidget(clear)
        layout.addLayout(row)
        layout.addWidget(box)

    def _captured(self, keys, elapsed):
        if self._actions and elapsed:
            self._actions.append({"type": "delay", "ms": int(elapsed)})
        self._actions.append({"type": "keys", "keys": keys, "mode": "tap"})
        self._render()

    def _clear(self):
        self._actions = []
        self.capture.timer.invalidate()
        self._render()

    def _render(self):
        self.preview.clear()
        for action in self.actions():
            self.preview.addItem(describe_action(action))

    def actions(self):
        if self.keep_delays.isChecked():
            return list(self._actions)
        return [a for a in self._actions if a["type"] != "delay"]

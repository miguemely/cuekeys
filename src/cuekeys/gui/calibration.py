"""Live LED colour calibration (gamma + white balance) against the real keypad."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .. import devices

PATTERNS = [
    ("White", "#ffffff"),
    ("Grey", "#808080"),
    ("Red", "#ff0000"),
    ("Green", "#00ff00"),
    ("Blue", "#0000ff"),
    ("Layout", None),
]


class _Slider(QWidget):
    """Horizontal slider with a live value readout."""

    def __init__(self, minimum, maximum, value, fmt, on_change):
        super().__init__()
        self.fmt = fmt
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.label = QLabel()
        self.label.setMinimumWidth(44)
        self.slider.valueChanged.connect(self._changed)
        self.slider.valueChanged.connect(lambda _v: on_change())
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.label)
        self._changed(value)

    def _changed(self, value):
        self.label.setText(self.fmt(value))

    def value(self):
        return self.slider.value()

    def set_value(self, value):
        self.slider.setValue(value)


class CalibrationDialog(QDialog):
    def __init__(self, config, runtime, parent=None, keypad=None, on_save=None):
        """``keypad``: this keypad's stored settings (they win over the layout's);
        ``on_save(gamma, balance)`` stores the result somewhere other than the layout."""
        super().__init__(parent)
        self.setWindowTitle("LED colour balance")
        self.config = config
        self.runtime = runtime
        self.on_save = on_save
        self.profile = devices.profile_for(config)
        device = dict(config.setdefault("device", {}))
        device.update({k: v for k, v in (keypad or {}).items() if k in ("led_gamma", "led_balance")})
        self.original = (float(device.get("led_gamma", self.profile.led_gamma)),
                         [float(v) for v in device.get("led_balance", self.profile.led_balance)])

        gamma, balance = self.original
        self.gamma = _Slider(100, 300, round(gamma * 100), lambda v: "%.1f" % (v / 100), self._push)
        self.channels = [_Slider(0, 100, round(b * 100), lambda v: "%d%%" % v, self._push)
                         for b in balance]

        intro = QLabel(
            "Adjust until the white test pattern looks neutral on the keypad (not pink, green or "
            "blue), then check the other colours. Lower a channel that's too strong; keep the "
            "weakest one at 100%. Gamma controls how saturated in-between colours look.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")

        form = QFormLayout()
        form.addRow("Red", self.channels[0])
        form.addRow("Green", self.channels[1])
        form.addRow("Blue", self.channels[2])
        form.addRow("Gamma", self.gamma)

        patterns = QHBoxLayout()
        self.pattern_group = QButtonGroup(self)
        for i, (name, _rgb) in enumerate(PATTERNS):
            button = QPushButton(name)
            button.setCheckable(True)
            button.setChecked(i == 0)
            self.pattern_group.addButton(button, i)
            patterns.addWidget(button)
        self.pattern_group.idClicked.connect(lambda _i: self._push())

        reset = QPushButton("Reset to %s defaults" % self.profile.name)
        reset.setObjectName("flat")
        reset.clicked.connect(self._reset)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)

        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(QLabel("Test pattern on the keypad"))
        layout.addLayout(patterns)
        layout.addWidget(reset, 0, Qt.AlignLeft)
        layout.addWidget(self.status)
        layout.addWidget(box)
        # A word-wrapped label only gets its full height if the dialog can't shrink below its
        # layout's minimum; otherwise the intro text overlaps the sliders.
        self.setMinimumWidth(480)
        layout.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        self._push()

    def values(self):
        return (round(self.gamma.value() / 100, 2), [round(c.value() / 100, 2) for c in self.channels])

    def _push(self):
        gamma, balance = self.values()
        pattern = PATTERNS[max(0, self.pattern_group.checkedId())][1]
        sent = self.runtime.link.send({"t": "led_cal", "gamma": gamma, "balance": balance})
        self.runtime.link.send({"t": "led_test", "rgb": pattern})
        self.status.setText("" if sent else
                            "The keypad isn't connected, so there's no live preview. "
                            "Values are still saved.")

    def _reset(self):
        self.gamma.set_value(round(self.profile.led_gamma * 100))
        for slider, value in zip(self.channels, self.profile.led_balance, strict=True):
            slider.set_value(round(value * 100))

    def done(self, result):
        # Always leave the keypad showing the layout again.
        self.runtime.link.send({"t": "led_test", "rgb": None})
        if result == QDialog.Accepted:
            gamma, balance = self.values()
            if self.on_save is not None:
                self.on_save(gamma, balance)
            else:
                device = self.config["device"]
                device["led_gamma"], device["led_balance"] = gamma, balance
        else:
            gamma, balance = self.original
            self.runtime.link.send({"t": "led_cal", "gamma": gamma, "balance": balance})
        super().done(result)

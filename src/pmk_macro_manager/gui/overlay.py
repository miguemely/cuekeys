"""Floating, semi-transparent, always-on-top reference of the current layer."""

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..config import DEFAULT_OVERLAY_LEVELS
from ..devices import profile_for
from .common import cell_badge, cell_content, paint_key, to_qcolor
from .theme import T

HEADER = 30
MIN_WIDTH = 230  # room for the header on narrow pads
PAD = 10
GAP = 5


class OverlayWindow(QWidget):
    # Emitted when a keypad overlay action shows/hides the window.
    visibility_changed = Signal(bool)

    def __init__(self, runtime, signals):
        super().__init__(None)
        self.runtime = runtime
        self.pressed = set()
        self.setWindowTitle("PMK overlay")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        # macOS hides Qt::Tool windows when the app is inactive unless told not to.
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)
        signals.event.connect(self._on_event)
        self.apply_settings()
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            screen.availableGeometryChanged.connect(lambda _geo: self.reposition())

    # ----------------------------------------------------------- settings
    @property
    def settings(self):
        return self.runtime.config.get("overlay", {})

    def apply_settings(self):
        s = self.settings
        flags = (Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                 | Qt.WindowDoesNotAcceptFocus)
        if s.get("click_through", True):
            flags |= Qt.WindowTransparentForInput
        visible = self.isVisible()
        self.setWindowFlags(flags)
        self.setWindowOpacity(float(s.get("opacity", 0.8)))
        size = int(s.get("key_size", 64))
        rows, cols = self._grid_size()
        grid_width = cols * size + (cols - 1) * GAP
        self._x0 = PAD + max(0, (MIN_WIDTH - 2 * PAD - grid_width) // 2)
        self.setFixedSize(max(MIN_WIDTH, PAD * 2 + grid_width),
                          PAD * 2 + HEADER + rows * size + (rows - 1) * GAP)
        self.reposition()
        if visible:
            self.show()
        self.update()

    def reposition(self):
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        margin = int(self.settings.get("margin", 24))
        corner = self.settings.get("corner", "bottom-right")
        x = geo.left() + margin if "left" in corner else geo.right() - self.width() - margin
        y = geo.top() + margin if "top" in corner else geo.bottom() - self.height() - margin
        self.move(QPoint(x, y))

    # ----------------------------------------------------------- events
    def run_command(self, op, levels=None):
        """Handle an ``overlay`` action from the keypad (cycle / toggle / show / hide)."""
        levels = [float(v) for v in (levels or DEFAULT_OVERLAY_LEVELS)]
        if op == "toggle":
            visible = not self.isVisible()
        elif op in ("show", "hide"):
            visible = op == "show"
        else:
            current = self.windowOpacity() if self.isVisible() else 0.0
            index = min(range(len(levels)), key=lambda i: abs(levels[i] - current))
            level = levels[(index + 1) % len(levels)]
            visible = level > 0
            if visible:
                self.setWindowOpacity(level)
        if visible and self.windowOpacity() <= 0.01:
            self.setWindowOpacity(float(self.settings.get("opacity", 0.8)))
        if visible != self.isVisible():
            self.setVisible(visible)
            self.visibility_changed.emit(visible)

    def _on_event(self, name, data):
        if name == "overlay":
            self.run_command(data.get("op", "cycle"), data.get("levels"))
            return
        if name == "key":
            (self.pressed.add if data["pressed"] else self.pressed.discard)(data["key"])
        elif name == "status" and not data.get("connected"):
            self.pressed.clear()
        if name in ("key", "layer", "status", "companion", "config"):
            self.update()

    def _profile(self):
        return profile_for(self.runtime.config)

    def _grid_size(self):
        return self._profile().display_size(int(self.settings.get("rotation", 0)))

    def _cell_rect(self, row, col):
        size = int(self.settings.get("key_size", 64))
        x0 = getattr(self, "_x0", PAD)
        return QRectF(x0 + col * (size + GAP), PAD + HEADER + row * (size + GAP), size, size)

    def _key_at(self, pos):
        rotation = int(self.settings.get("rotation", 0))
        rows, cols = self._grid_size()
        profile = self._profile()
        for row in range(rows):
            for col in range(cols):
                if self._cell_rect(row, col).contains(pos):
                    return profile.cell_to_key(row, col, rotation)
        return None

    def mousePressEvent(self, event):
        key = self._key_at(event.position())
        if key is not None and event.button() == Qt.LeftButton:
            self._clicked = key
            self.runtime.press_key(key)
        elif event.button() == Qt.RightButton:
            self._step_layer(1)

    def mouseReleaseEvent(self, event):
        key = getattr(self, "_clicked", None)
        if key is not None:
            self._clicked = None
            self.runtime.release_key(key)

    def wheelEvent(self, event):
        self._step_layer(-1 if event.angleDelta().y() > 0 else 1)

    def _step_layer(self, step):
        count = len(self.runtime.config["layers"])
        self.runtime.select_layer((self.runtime.layer + step) % count)

    # ----------------------------------------------------------- painting
    def paintEvent(self, _event):
        runtime = self.runtime
        config = runtime.config
        layer_index, layer = runtime.layer_info()
        rotation = int(self.settings.get("rotation", 0))
        key_size = int(self.settings.get("key_size", 64))
        layer_color = to_qcolor(layer.get("color") or T["accent"])

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        panel = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(QColor(16, 18, 23, 240))
        p.drawRoundedRect(panel, 12, 12)

        # accent bar in the layer colour
        p.setPen(Qt.NoPen)
        p.setBrush(layer_color)
        p.drawRoundedRect(QRectF(PAD, PAD + 4, 4, HEADER - 14), 2, 2)

        # page dots (one per layer), right aligned
        count = len(config["layers"])
        dot, gap = 6, 5
        dots_w = min(count, 12) * (dot + gap)
        x0 = self.width() - PAD - dots_w
        for i in range(min(count, 12)):
            p.setBrush(QColor(T["text"]) if i == layer_index else QColor(255, 255, 255, 50))
            p.drawEllipse(QRectF(x0 + i * (dot + gap), PAD + (HEADER - 6 - dot) / 2, dot, dot))

        # title: layer name + status
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(13)
        p.setFont(font)
        title = layer.get("name", "") or "Layer %d" % (layer_index + 1)
        status = None
        if not runtime.connected:
            status = ("keypad offline", T["muted"])
        elif layer.get("mode") == "companion":
            state = runtime.companion_status(layer.get("companion_target", "default"))
            status = {"online": ("Companion", T["success"]), "busy": ("Companion busy", T["warn"]),
                      "offline": ("Companion offline", T["danger"])}[state]
            page = runtime.companion_page_label(layer_index)
            if state == "online" and page:
                status = ("Companion · %s" % page, T["success"])
        header = QRectF(PAD + 12, PAD, x0 - PAD - 18, HEADER - 6)
        p.setPen(QColor(T["text"]))
        metrics = p.fontMetrics()
        name_w = min(metrics.horizontalAdvance(title), header.width())
        p.drawText(header, Qt.AlignVCenter | Qt.AlignLeft,
                   metrics.elidedText(title, Qt.ElideRight, int(header.width())))
        if status and name_w + 60 < header.width():
            small = QFont(self.font())
            small.setPixelSize(10)
            p.setFont(small)
            p.setPen(QColor(status[1]))
            rest = header.adjusted(name_w + 8, 1, 0, 0)
            p.drawText(rest, Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText("● " + status[0], Qt.ElideRight, int(rest.width())))

        profile = self._profile()
        for key in profile.keys():
            row, col = profile.key_to_cell(key, rotation)
            label, color = cell_content(config, layer_index, key, runtime.companion_states)
            paint_key(p, self._cell_rect(row, col), label, color, pressed=key in self.pressed,
                      radius=7, font_px=max(9, key_size // 6), empty=T["empty_key"],
                      badge=cell_badge(config, layer_index, key, runtime.companion_states))
        p.end()

"""Floating, semi-transparent, always-on-top reference of the current layer.

``Overlay`` manages one ``OverlayWindow`` per chosen display (main display,
all displays, selected displays, or whichever display the mouse is on) and
keeps their opacity and visibility in sync.
"""

import sys

from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..config import DEFAULT_OVERLAY_LEVELS
from ..devices import profile_for
from .common import cell_badge, cell_content, paint_key, to_qcolor
from .theme import T

SCREEN_MODES = ("primary", "all", "mouse")  # or a list of display names
HEADER = 30
MIN_WIDTH = 230  # room for the header on narrow pads
PAD = 10
GAP = 5


def screen_names(screens=None):
    """Stable, unique names for displays (identical monitors get " #2", " #3" ...)."""
    screens = QGuiApplication.screens() if screens is None else screens
    names, seen = {}, {}
    for screen in screens:
        base = screen.name() or "Display"
        seen[base] = seen.get(base, 0) + 1
        names[screen] = base if seen[base] == 1 else "%s #%d" % (base, seen[base])
    return names


class Overlay(QObject):
    """All overlay windows; the editor and overlay-only mode talk to this."""

    visibility_changed = Signal(bool)

    def __init__(self, runtime, signals):
        super().__init__()
        self.runtime = runtime
        self.signals = signals
        self.windows = {}          # QScreen -> OverlayWindow
        self._visible = False
        self._opacity = float(self.settings.get("opacity", 0.8))
        signals.event.connect(self._on_event)
        app = QGuiApplication.instance()
        app.screenAdded.connect(lambda _s: self._rebuild())
        app.screenRemoved.connect(lambda _s: self._rebuild())
        app.primaryScreenChanged.connect(lambda _s: self._rebuild())
        self._mouse_timer = QTimer(self)
        self._mouse_timer.setInterval(400)
        self._mouse_timer.timeout.connect(self._follow_mouse)

    @property
    def settings(self):
        return self.runtime.config.get("overlay", {})

    # ------------------------------------------------------------- displays
    def target_screens(self):
        mode = self.settings.get("screens", "primary")
        screens = QGuiApplication.screens()
        primary = QGuiApplication.primaryScreen()
        if mode == "all":
            return list(screens)
        if mode == "mouse":
            return [QGuiApplication.screenAt(QCursor.pos()) or primary]
        if isinstance(mode, list):
            names = screen_names(screens)
            chosen = [s for s in screens if names[s] in mode]
            if chosen:
                return chosen
        return [primary] if primary is not None else []

    def _rebuild(self):
        targets = [s for s in self.target_screens() if s is not None]
        for screen in list(self.windows):
            if screen not in targets:
                self.windows.pop(screen).close()
        for screen in targets:
            if screen not in self.windows:
                self.windows[screen] = OverlayWindow(self.runtime, self.signals, screen)
        for window in self.windows.values():
            window.apply_settings(self._opacity)
            window.setVisible(self._visible)
        if self.settings.get("screens") == "mouse":
            self._mouse_timer.start()
        else:
            self._mouse_timer.stop()

    def _follow_mouse(self):
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is not None and screen not in self.windows:
            self._rebuild()

    # ------------------------------------------------------------- control
    def apply_settings(self):
        self._opacity = float(self.settings.get("opacity", 0.8))
        self._rebuild()

    def setVisible(self, visible):
        self._visible = bool(visible)
        if not self.windows:
            self._rebuild()
        for window in self.windows.values():
            window.setWindowOpacity(self._opacity)
            window.setVisible(self._visible)

    def show(self):
        self.setVisible(True)

    def hide(self):
        self.setVisible(False)

    def isVisible(self):
        return self._visible

    def windowOpacity(self):
        return self._opacity

    def update(self):
        for window in self.windows.values():
            window.update()

    def close(self):
        self._mouse_timer.stop()
        for window in self.windows.values():
            window.close()
        self.windows.clear()

    def grab(self):
        """Image of the first overlay window (tests, screenshots)."""
        if not self.windows:
            self._rebuild()
        return next(iter(self.windows.values())).grab()

    def run_command(self, op, levels=None):
        """Handle an ``overlay`` action from the keypad (cycle / toggle / show / hide)."""
        levels = [float(v) for v in (levels or DEFAULT_OVERLAY_LEVELS)]
        if op == "toggle":
            visible = not self._visible
        elif op in ("show", "hide"):
            visible = op == "show"
        else:
            current = self._opacity if self._visible else 0.0
            index = min(range(len(levels)), key=lambda i: abs(levels[i] - current))
            level = levels[(index + 1) % len(levels)]
            visible = level > 0
            if visible:
                self._opacity = level
        if visible and self._opacity <= 0.01:
            self._opacity = float(self.settings.get("opacity", 0.8))
        changed = visible != self._visible
        self.setVisible(visible)
        if changed:
            self.visibility_changed.emit(visible)

    def _on_event(self, name, data):
        if name == "overlay":
            self.run_command(data.get("op", "cycle"), data.get("levels"))


class OverlayWindow(QWidget):
    """The overlay on one display."""

    def __init__(self, runtime, signals, screen=None):
        super().__init__(None)
        self.runtime = runtime
        self.target_screen = screen
        self.pressed = set()
        self.setWindowTitle("CueKeys overlay")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        # macOS hides Qt::Tool windows when the app is inactive unless told not to.
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)
        signals.event.connect(self._on_event)
        self.apply_settings()
        if screen is not None:
            screen.availableGeometryChanged.connect(lambda _geo: self.reposition())

    # ----------------------------------------------------------- settings
    @property
    def settings(self):
        return self.runtime.config.get("overlay", {})

    def apply_settings(self, opacity=None):
        s = self.settings
        flags = (Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                 | Qt.WindowDoesNotAcceptFocus)
        if s.get("click_through", True):
            flags |= Qt.WindowTransparentForInput
        visible = self.isVisible()
        self.setWindowFlags(flags)
        self.setWindowOpacity(float(s.get("opacity", 0.8)) if opacity is None else opacity)
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

    def showEvent(self, event):
        super().showEvent(event)
        # Qt recreates the native window when flags change, so re-apply on every show.
        if sys.platform == "darwin":
            from . import macos

            macos.show_on_all_spaces(self, bool(self.settings.get("all_spaces", True)))

    def reposition(self):
        screen = self.target_screen or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        margin = int(self.settings.get("margin", 24))
        corner = self.settings.get("corner", "bottom-right")
        x = geo.left() + margin if "left" in corner else geo.right() - self.width() - margin
        y = geo.top() + margin if "top" in corner else geo.bottom() - self.height() - margin
        self.move(QPoint(x, y))

    # ----------------------------------------------------------- events
    def _on_event(self, name, data):
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

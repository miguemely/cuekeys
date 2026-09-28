# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
"""Floating, semi-transparent, always-on-top reference of the current layer.

``Overlay`` is one keypad's overlay: one ``OverlayWindow`` per chosen display
(main display, all displays, selected displays, or whichever display the mouse
is on), with opacity and visibility kept in sync. ``OverlayGroup`` keeps one
``Overlay`` per connected keypad, stacked in the corner.
"""

import sys

from PySide6.QtCore import QElapsedTimer, QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..config import DEFAULT_OVERLAY_LEVELS
from ..devices import profile_for
from .common import cell_badge, cell_content, paint_key, to_qcolor
from .theme import T

SCREEN_MODES = ("primary", "all", "mouse")  # or a list of display names

# Header ticker: text that doesn't fit shows its start, scrolls to its end, then
# jumps back. Only runs while the text overflows.
SCROLL_SPEED = 30        # px per second
SCROLL_PAUSE_MS = 1500   # hold at the start and at the end
SCROLL_TICK_MS = 33


def marquee_offset(elapsed_ms, overflow, speed=SCROLL_SPEED, pause_ms=SCROLL_PAUSE_MS):
    """Horizontal scroll offset (px) for text that is ``overflow`` px too wide."""
    if overflow <= 0:
        return 0.0
    travel_ms = overflow / speed * 1000.0
    t = elapsed_ms % (pause_ms + travel_ms + pause_ms)
    if t < pause_ms:
        return 0.0
    if t < pause_ms + travel_ms:
        return (t - pause_ms) * speed / 1000.0
    return float(overflow)
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
        self.label = ""            # keypad name in the header (several keypads)
        self.stack_offset = 0      # px away from the corner (several keypads)
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
                self.windows[screen] = OverlayWindow(self.runtime, self.signals, screen, self)
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

    def height(self):
        if not self.windows:
            self._rebuild()
        return max((w.height() for w in self.windows.values()), default=0)

    def set_stacking(self, label, offset):
        self.label, self.stack_offset = label, int(offset)
        for window in self.windows.values():
            window.reposition()
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
        if name == "overlay" and data.get("keypad", self.runtime.uid) == self.runtime.uid:
            self.run_command(data.get("op", "cycle"), data.get("levels"))


class OverlayGroup(QObject):
    """One overlay per keypad, stacked in the corner and named when there are several."""

    GAP = 8
    visibility_changed = Signal(bool)

    def __init__(self, hub, signals):
        super().__init__()
        self.hub = hub
        self.signals = signals
        self.overlays = {}          # uid -> Overlay
        self._visible = False
        signals.event.connect(self._on_event)
        self.sync()

    def get(self, uid):
        return self.overlays.get(uid)

    def sync(self):
        sessions = dict(self.hub.sessions)
        for uid in list(self.overlays):
            if uid not in sessions:
                self.overlays.pop(uid).close()
        for uid, session in sessions.items():
            if uid not in self.overlays:
                overlay = Overlay(session, self.signals)
                overlay.visibility_changed.connect(self._child_visibility)
                self.overlays[uid] = overlay
                if self._visible:
                    overlay.setVisible(self._enabled(session))
            else:
                self.overlays[uid].runtime = session
        self.restack()

    @staticmethod
    def _enabled(session):
        return bool(session.config.get("overlay", {}).get("enabled", True))

    def restack(self):
        several = len(self.overlays) > 1
        offset = 0
        for uid, overlay in self.overlays.items():
            overlay.set_stacking(self.hub.sessions[uid].name if several else "", offset)
            if overlay.isVisible():
                offset += overlay.height() + self.GAP

    def setVisible(self, visible):
        self._visible = bool(visible)
        for overlay in self.overlays.values():
            overlay.setVisible(self._visible and self._enabled(overlay.runtime))
        self.restack()

    def show(self):
        self.setVisible(True)

    def hide(self):
        self.setVisible(False)

    def isVisible(self):
        return self._visible

    def apply_settings(self):
        for overlay in self.overlays.values():
            overlay.apply_settings()
        self.setVisible(self._visible)

    def update(self):
        for overlay in self.overlays.values():
            overlay.update()

    def close(self):
        for overlay in self.overlays.values():
            overlay.close()
        self.overlays.clear()

    def _child_visibility(self, _visible):
        self.restack()
        self.visibility_changed.emit(any(o.isVisible() for o in self.overlays.values()))

    def _on_event(self, name, data):
        if name == "keypads":
            self.sync()
        elif name == "config":
            overlay = self.overlays.get(data.get("keypad"))
            if overlay is not None:
                overlay.apply_settings()
                overlay.setVisible(self._visible and self._enabled(overlay.runtime))
                self.restack()


class OverlayWindow(QWidget):
    """The overlay on one display."""

    def __init__(self, runtime, signals, screen=None, owner=None):
        super().__init__(None)
        self.runtime = runtime
        self.owner = owner
        self.target_screen = screen
        self.pressed = set()
        self._scroll_clock = QElapsedTimer()
        self._scroll_text = None
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(SCROLL_TICK_MS)
        self._scroll_timer.timeout.connect(lambda: self.update(QRect(0, 0, self.width(), PAD + HEADER)))
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

    def hideEvent(self, event):
        self._scroll_timer.stop()
        super().hideEvent(event)

    @property
    def scrolling(self):
        return self._scroll_timer.isActive()

    def reposition(self):
        screen = self.target_screen or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        margin = int(self.settings.get("margin", 24))
        corner = self.settings.get("corner", "bottom-right")
        stack = self.owner.stack_offset if self.owner is not None else 0
        x = geo.left() + margin if "left" in corner else geo.right() - self.width() - margin
        y = geo.top() + margin + stack if "top" in corner else geo.bottom() - self.height() - margin - stack
        self.move(QPoint(x, y))

    # ----------------------------------------------------------- events
    def _on_event(self, name, data):
        if data.get("keypad", self.runtime.uid) != self.runtime.uid:
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
        label = self.owner.label if self.owner is not None else ""
        if label:
            title = "%s · %s" % (label, title)
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
        self._paint_header_text(p, header, font, title, status)

        profile = self._profile()
        for key in profile.keys():
            row, col = profile.key_to_cell(key, rotation)
            label, color = cell_content(config, layer_index, key, runtime.companion_states)
            paint_key(p, self._cell_rect(row, col), label, color, pressed=key in self.pressed,
                      radius=7, font_px=max(9, key_size // 6), empty=T["empty_key"],
                      badge=cell_badge(config, layer_index, key, runtime.companion_states))
        p.end()

    def _paint_header_text(self, p, header, title_font, title, status):
        """Layer name stays put; only the status scrolls (ticker) when it doesn't fit.

        With no status the name itself scrolls; with a status, a very long name is
        capped (elided) so the status always has room.
        """
        status_font = QFont(self.font())
        status_font.setPixelSize(10)
        p.setFont(title_font)
        title_w = p.fontMetrics().horizontalAdvance(title)
        status_text = ("● " + status[0]) if status else ""
        overflow = 0

        if not status_text:
            overflow = self._draw_marquee(p, header, title, title_font, QColor(T["text"]), 0)
        else:
            p.setFont(status_font)
            status_w = p.fontMetrics().horizontalAdvance(status_text)
            fits = title_w + 8 + status_w <= header.width()
            name_w = title_w if fits else min(title_w, header.width() * 0.55)
            p.setFont(title_font)
            p.setPen(QColor(T["text"]))
            p.drawText(QRectF(header.left(), header.top(), name_w + 1, header.height()),
                       Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText(title, Qt.ElideRight, int(name_w + 1)))
            # The coloured dot is a status light: it stays put, only the words scroll.
            p.setFont(status_font)
            p.setPen(QColor(status[1]))
            dot_w = p.fontMetrics().horizontalAdvance("● ")
            dot_x = header.left() + name_w + 8
            p.drawText(QRectF(dot_x, header.top() + 1, dot_w + 1, header.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, "●")
            rest = QRectF(dot_x + dot_w, header.top(), header.right() - dot_x - dot_w, header.height())
            overflow = self._draw_marquee(p, rest, status[0], status_font, QColor(status[1]), 1)

        if overflow > 0 and self.isVisible():
            if not self._scroll_timer.isActive():
                self._scroll_timer.start()
        else:
            self._scroll_timer.stop()

    def _draw_marquee(self, p, rect, text, font, color, dy):
        """Draw ``text`` in ``rect``; scroll it with faded edges if it's too wide. Returns overflow px."""
        p.setFont(font)
        text_w = p.fontMetrics().horizontalAdvance(text)
        overflow = text_w - rect.width()
        key = (text, int(rect.width()))
        if key != self._scroll_text:          # new text: start again from the beginning
            self._scroll_text = key
            self._scroll_clock.restart()
        offset = marquee_offset(self._scroll_clock.elapsed(), overflow)

        # Draw into a transparent layer so the edges can fade the text itself
        # (a painted gradient would show against the translucent panel).
        dpr = self.devicePixelRatioF()
        w, h = max(1, int(rect.width())), max(1, int(rect.height()))
        layer = QImage(int(w * dpr), int(h * dpr), QImage.Format_ARGB32_Premultiplied)
        layer.setDevicePixelRatio(dpr)
        layer.fill(Qt.transparent)
        lp = QPainter(layer)
        lp.setRenderHint(QPainter.Antialiasing)
        lp.setRenderHint(QPainter.TextAntialiasing)
        lp.setFont(font)
        lp.setPen(color)
        lp.drawText(QRectF(-offset, dy, text_w + 2, h), Qt.AlignVCenter | Qt.AlignLeft, text)
        if overflow > 0:
            fade = 12.0
            left = fade / w if offset > 0 else 0.0
            right = fade / w if offset < overflow else 0.0
            mask = QLinearGradient(0, 0, w, 0)
            mask.setColorAt(0.0, QColor(0, 0, 0, 0 if left else 255))
            mask.setColorAt(left, QColor(0, 0, 0, 255))
            mask.setColorAt(1.0 - right, QColor(0, 0, 0, 255))
            mask.setColorAt(1.0, QColor(0, 0, 0, 0 if right else 255))
            lp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            lp.fillRect(QRectF(0, 0, w, h), mask)
        lp.end()
        p.drawImage(QPointF(rect.left(), rect.top()), layer)
        return overflow

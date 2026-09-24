"""Shared Qt helpers."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

from ..config import describe_action, in_companion_region, key_is_assigned
from ..devices import profile_for


class RuntimeSignals(QObject):
    """Re-emits Runtime listener callbacks (background threads) on the Qt thread."""

    event = Signal(str, dict)

    def __init__(self, runtime):
        super().__init__()
        runtime.add_listener(lambda name, data: self.event.emit(name, data))


def to_qcolor(value, default="#000000"):
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return QColor(*[int(v) for v in value])
    color = QColor(value or default)
    return color if color.isValid() else QColor(default)


def text_color_for(background):
    luminance = 0.299 * background.red() + 0.587 * background.green() + 0.114 * background.blue()
    return QColor("#000000") if luminance > 150 else QColor("#ffffff")


def key_label(key_cfg):
    """Short label for a key: explicit label, else a summary of its first action."""
    if not key_cfg:
        return ""
    if key_cfg.get("label"):
        return key_cfg["label"]
    for slot in ("press", "hold"):
        actions = key_cfg.get(slot) or []
        if actions:
            return describe_action(actions[0])
    return ""


# Companion page-navigation buttons arrive without text.
COMPANION_TYPE_LABELS = {"PAGEUP": "Page ▲", "PAGEDOWN": "Page ▼", "PAGENUM": "Page"}


def companion_type_label(state):
    kind = state.get("type")
    if kind == "PAGENUM":
        # Companion draws the page name on this button; so do we once it's known.
        if state.get("page_name"):
            return state["page_name"]
        if state.get("page") is not None:
            return "Page %d" % state["page"]
    return COMPANION_TYPE_LABELS.get(kind, "")


def cell_content(config, layer_index, key, companion_states=None):
    """(label, QColor) for a key as the overlay/editor should show it."""
    layers = config["layers"]
    layer = layers[layer_index]
    key_cfg = (layer.get("keys") or {}).get(str(key))
    if key_is_assigned(key_cfg):
        color = to_qcolor(key_cfg.get("color") or layer.get("color") or "#282828")
        return key_label(key_cfg), color
    rotation = int(config.get("overlay", {}).get("rotation", 0))
    if in_companion_region(layer, key, profile_for(config), rotation):
        state = (companion_states or {}).get((layer_index, key)) or {}
        text = state.get("text", "") or companion_type_label(state)
        color = to_qcolor(state.get("color") or (0, 0, 0))
        if text and color.name() == "#000000":
            # A real black Companion button (not an empty slot): draw it as one.
            color = QColor(1, 1, 1)
        return text, color
    return "", QColor("#000000")


# Companion's colour for the page/row/column label on its buttons.
BADGE_COLOR = "#f5c518"


def cell_badge(config, layer_index, key, companion_states=None):
    """Companion "page/row/column" for a key, like Companion shows on its buttons.

    Only for real buttons with content in the Companion region; not for page
    up/down/number buttons, empty buttons or keys assigned locally.
    """
    layer = config["layers"][layer_index]
    rotation = int(config.get("overlay", {}).get("rotation", 0))
    if not in_companion_region(layer, key, profile_for(config), rotation):
        return None
    if key_is_assigned((layer.get("keys") or {}).get(str(key))):
        return None
    state = (companion_states or {}).get((layer_index, key)) or {}
    if not state.get("location") or state.get("type", "BUTTON") != "BUTTON":
        return None
    color = state.get("color")
    if not state.get("text") and (not color or tuple(color) == (0, 0, 0)):
        return None  # empty button slot
    return state["location"]


def paint_key(p, rect, label, fill, number=None, selected=False, pressed=False,
              hover=False, radius=8, font_px=11, accent="#5b8cff", empty="#2a2e37", badge=None):
    """Draw one key cap. ``fill`` black (#000000) means "unassigned".

    ``badge`` is a small tag drawn in the top-left corner (Companion location),
    where Companion draws it on its own buttons.
    """
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QFont, QLinearGradient, QPen

    assigned = fill.name() != "#000000"
    base = QColor(fill) if assigned else QColor(empty)
    if pressed:
        base = base.lighter(135)
    elif hover:
        base = base.lighter(112)

    if selected:
        p.setPen(QPen(QColor(accent), 2.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), radius + 3, radius + 3)

    grad = QLinearGradient(QPointF(rect.topLeft()), QPointF(rect.bottomLeft()))
    grad.setColorAt(0.0, base.lighter(118) if assigned else base.lighter(105))
    grad.setColorAt(1.0, base.darker(108) if assigned else base)
    p.setBrush(grad)
    if pressed:
        p.setPen(QPen(QColor("#ffffff"), 2.5))
    else:
        p.setPen(QPen(QColor(255, 255, 255, 28 if assigned else 14), 1))
    p.drawRoundedRect(rect, radius, radius)

    text_color = text_color_for(base) if assigned else QColor(255, 255, 255, 90)
    if number is not None:
        small = QFont(p.font())
        small.setPixelSize(max(8, font_px - 2))
        small.setBold(False)
        p.setFont(small)
        faded = QColor(text_color)
        faded.setAlpha(110)
        p.setPen(faded)
        p.drawText(rect.adjusted(5, 3, -6, -4), Qt.AlignRight | Qt.AlignBottom, str(number))
    top_inset = 4
    if badge:
        small = QFont(p.font())
        small.setPixelSize(max(8, font_px - 2))
        small.setBold(True)
        p.setFont(small)
        metrics = p.fontMetrics()
        w = min(metrics.horizontalAdvance(badge) + 8, rect.width() - 6)
        h = metrics.height() + 1
        tag = QRectF(rect.left() + 3, rect.top() + 3, w, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(tag, 3, 3)
        p.setPen(QColor(BADGE_COLOR))
        p.drawText(tag, Qt.AlignCenter, metrics.elidedText(badge, Qt.ElideRight, int(w - 4)))
        top_inset = h + 4
    if label:
        font = QFont(p.font())
        font.setPixelSize(font_px)
        font.setBold(True)
        p.setFont(font)
        p.setPen(text_color)
        inner = QRectF(rect).adjusted(5, top_inset, -5, -10 if number is not None else -4)
        p.drawText(inner, Qt.AlignCenter | Qt.TextWordWrap, label)

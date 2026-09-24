"""Shared Qt helpers."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

from ..config import describe_action, in_companion_region, key_is_assigned


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


def cell_content(config, layer_index, key, companion_states=None):
    """(label, QColor) for a key as the overlay/editor should show it."""
    layers = config["layers"]
    layer = layers[layer_index]
    key_cfg = (layer.get("keys") or {}).get(str(key))
    if key_is_assigned(key_cfg):
        color = to_qcolor(key_cfg.get("color") or layer.get("color") or "#282828")
        return key_label(key_cfg), color
    rotation = int(config.get("overlay", {}).get("rotation", 0))
    if in_companion_region(layer, key, rotation):
        state = (companion_states or {}).get((layer_index, key)) or {}
        text = state.get("text", "") or COMPANION_TYPE_LABELS.get(state.get("type"), "")
        return text, to_qcolor(state.get("color") or (0, 0, 0))
    return "", QColor("#000000")


def paint_key(p, rect, label, fill, number=None, selected=False, pressed=False,
              hover=False, radius=8, font_px=11, accent="#5b8cff", empty="#2a2e37"):
    """Draw one key cap. ``fill`` black (#000000) means "unassigned"."""
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
    if label:
        font = QFont(p.font())
        font.setPixelSize(font_px)
        font.setBold(True)
        p.setFont(font)
        p.setPen(text_color)
        inner = QRectF(rect).adjusted(5, 4, -5, -10 if number is not None else -4)
        p.drawText(inner, Qt.AlignCenter | Qt.TextWordWrap, label)

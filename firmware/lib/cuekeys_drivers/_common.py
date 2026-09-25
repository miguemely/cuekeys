# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Helpers shared by the generic drivers (CircuitPython ``keypad`` + NeoPixels)."""

import board


def pin(name):
    try:
        return getattr(board, name)
    except AttributeError:
        raise ValueError("board has no pin %s" % name)


def drain(queue, key_map=None):
    """Turn a keypad EventQueue into [(key, pressed)], applying an optional key map."""
    out = []
    event = queue.get()
    while event:
        key = event.key_number
        if key_map is not None:
            key = key_map[key] if key < len(key_map) else None
        if key is not None:
            out.append((key, event.pressed))
        event = queue.get()
    return out


class Pixels:
    """NeoPixels addressed by logical key number."""

    def __init__(self, config, num_keys):
        import neopixel

        count = int(config.get("count", num_keys))
        order = getattr(neopixel, config.get("order", "GRB"))
        self.strip = neopixel.NeoPixel(pin(config.get("pin", "NEOPIXEL")), count,
                                       brightness=float(config.get("brightness", 1.0)),
                                       auto_write=False, pixel_order=order)
        self.map = config.get("map") or list(range(num_keys))
        self.dirty = True

    def set(self, key, rgb):
        index = self.map[key] if key < len(self.map) else None
        if index is not None and 0 <= index < len(self.strip):
            self.strip[index] = rgb
            self.dirty = True

    def show(self):
        if self.dirty:
            self.strip.show()
            self.dirty = False


def make_pixels(config, num_keys):
    return Pixels(config, num_keys) if config else None

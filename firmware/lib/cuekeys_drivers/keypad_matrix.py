# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
"""Diode key matrix (CircuitPython ``keypad.KeyMatrix``), optional NeoPixels.

driver_config::

    {
      "rows": ["GP0", "GP1", "GP2"],
      "columns": ["GP3", "GP4", "GP5"],
      "columns_to_anodes": true,        # diode direction
      "key_map": null,                  # optional: matrix index (row * ncols + col) -> key
      "pixels": {"pin": "GP16", "count": 9}
    }
"""

import keypad

from ._common import drain, make_pixels, pin


class Hardware:
    def __init__(self, config):
        rows = tuple(pin(name) for name in config["rows"])
        cols = tuple(pin(name) for name in config["columns"])
        self.matrix = keypad.KeyMatrix(row_pins=rows, column_pins=cols,
                                       columns_to_anodes=bool(config.get("columns_to_anodes", True)))
        self.key_map = config.get("key_map")
        mapped = [k for k in self.key_map if k is not None] if self.key_map else None
        self.num_keys = len(mapped) if mapped else len(rows) * len(cols)
        self.pixels = make_pixels(config.get("pixels"), self.num_keys)
        self.has_leds = self.pixels is not None

    def poll(self, now_ms):
        return drain(self.matrix.events, self.key_map)

    def set_led(self, key, rgb):
        if self.pixels is not None:
            self.pixels.set(key, rgb)

    def show(self):
        if self.pixels is not None:
            self.pixels.show()

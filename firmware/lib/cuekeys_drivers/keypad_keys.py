# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
"""One GPIO pin per key (CircuitPython ``keypad.Keys``), optional NeoPixels.

driver_config::

    {
      "pins": ["GP0", "GP1", ...],      # board pin names, in key-number order
      "value_when_pressed": false,      # false = key connects the pin to GND
      "pull": true,                     # enable the internal pull resistor
      "key_map": null,                  # optional: pin index -> key number (null = ignore)
      "pixels": {"pin": "NEOPIXEL", "count": 12, "order": "GRB", "map": null}
    }
"""

import keypad

from ._common import drain, make_pixels, pin


class Hardware:
    def __init__(self, config):
        pins = tuple(pin(name) for name in config["pins"])
        self.keys = keypad.Keys(pins, value_when_pressed=bool(config.get("value_when_pressed", False)),
                                pull=bool(config.get("pull", True)))
        self.key_map = config.get("key_map")
        mapped = [k for k in self.key_map if k is not None] if self.key_map else None
        self.num_keys = len(mapped) if mapped else len(pins)
        self.pixels = make_pixels(config.get("pixels"), self.num_keys)
        self.has_leds = self.pixels is not None

    def poll(self, now_ms):
        return drain(self.keys.events, self.key_map)

    def set_led(self, key, rgb):
        if self.pixels is not None:
            self.pixels.set(key, rgb)

    def show(self):
        if self.pixels is not None:
            self.pixels.show()

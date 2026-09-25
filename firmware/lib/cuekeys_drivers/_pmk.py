# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Shared driver for Pimoroni boards via the ``pmk`` library."""

from pmk import PMK


class PMKHardware:
    has_leds = True

    def __init__(self, platform, config):
        self.keypad = PMK(platform)
        self.num_keys = len(self.keypad.keys)
        self.debounce_ms = int(config.get("debounce_ms", 15))
        self._pressed = [False] * self.num_keys
        self._changed_at = [0] * self.num_keys

    def poll(self, now_ms):
        self.keypad.update()
        events = []
        for key in self.keypad.keys:
            i = key.number
            pressed = key.pressed
            if pressed != self._pressed[i] and now_ms - self._changed_at[i] >= self.debounce_ms:
                self._pressed[i] = pressed
                self._changed_at[i] = now_ms
                events.append((i, pressed))
        return events

    def set_led(self, key, rgb):
        self.keypad.keys[key].set_led(*rgb)

    def show(self):
        pass

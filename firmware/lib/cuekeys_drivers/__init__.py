# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
"""Keypad hardware drivers.

A driver is a module in this package that defines ``Hardware``::

    class Hardware:
        num_keys = 16          # logical keys, numbered 0..num_keys-1
        has_leds = True

        def __init__(self, config):
            # ``config`` is the profile's "driver_config" (plus "debounce_ms")
            ...

        def poll(self, now_ms):
            # Return a list of (key, pressed) changes since the last call.
            return []

        def set_led(self, key, rgb):
            # rgb is an (r, g, b) tuple 0-255, brightness already applied.
            pass

        def show(self):
            # Push buffered LED changes (called once per main-loop pass).
            pass

The key numbers must match the "grid" of the device profile on the host.
Profiles pick a driver with "driver": "<module name>".
"""

# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
"""Firmware drivers, run on desktop Python with stub CircuitPython modules."""

import importlib
import sys
import types

import pytest


class FakeEvent:
    def __init__(self, key_number, pressed):
        self.key_number, self.pressed = key_number, pressed


class FakeQueue:
    def __init__(self):
        self.items = []

    def get(self):
        return self.items.pop(0) if self.items else None


class FakeKeys:
    def __init__(self, pins, value_when_pressed, pull):
        self.pins, self.events = pins, FakeQueue()


class FakeMatrix:
    def __init__(self, row_pins, column_pins, columns_to_anodes):
        self.rows, self.cols, self.events = row_pins, column_pins, FakeQueue()


class FakeStrip(list):
    def __init__(self, pin, count, brightness, auto_write, pixel_order):
        super().__init__([(0, 0, 0)] * count)
        self.shown = 0

    def show(self):
        self.shown += 1


@pytest.fixture
def drivers(monkeypatch):
    board = types.ModuleType("board")
    for name in ["GP%d" % i for i in range(30)] + ["KEY%d" % i for i in range(1, 13)] + ["NEOPIXEL"]:
        setattr(board, name, name)
    keypad = types.ModuleType("keypad")
    keypad.Keys, keypad.KeyMatrix = FakeKeys, FakeMatrix
    neopixel = types.ModuleType("neopixel")
    neopixel.NeoPixel, neopixel.GRB, neopixel.RGB = FakeStrip, "GRB", "RGB"
    for name, module in (("board", board), ("keypad", keypad), ("neopixel", neopixel)):
        monkeypatch.setitem(sys.modules, name, module)
    for name in [m for m in sys.modules if m.startswith("cuekeys_drivers")]:
        monkeypatch.delitem(sys.modules, name)
    return importlib


def test_keypad_keys_driver_with_pixels(drivers):
    mod = drivers.import_module("cuekeys_drivers.keypad_keys")
    hw = mod.Hardware({"pins": ["KEY1", "KEY2", "KEY3"], "pixels": {"pin": "NEOPIXEL", "count": 3}})
    assert hw.num_keys == 3 and hw.has_leds
    hw.keys.events.items = [FakeEvent(2, True), FakeEvent(2, False)]
    assert hw.poll(0) == [(2, True), (2, False)]
    hw.set_led(1, (1, 2, 3))
    hw.show()
    hw.show()  # nothing changed: no second write
    assert hw.pixels.strip[1] == (1, 2, 3) and hw.pixels.strip.shown == 1


def test_keypad_keys_key_map_and_no_leds(drivers):
    mod = drivers.import_module("cuekeys_drivers.keypad_keys")
    hw = mod.Hardware({"pins": ["GP0", "GP1", "GP2"], "key_map": [1, None, 0]})
    assert hw.num_keys == 2 and not hw.has_leds
    hw.keys.events.items = [FakeEvent(0, True), FakeEvent(1, True), FakeEvent(2, True)]
    assert hw.poll(0) == [(1, True), (0, True)]
    hw.set_led(0, (1, 1, 1))  # no-op without pixels
    hw.show()


def test_keypad_matrix_driver(drivers):
    mod = drivers.import_module("cuekeys_drivers.keypad_matrix")
    hw = mod.Hardware({"rows": ["GP0", "GP1"], "columns": ["GP2", "GP3", "GP4"],
                       "pixels": {"pin": "GP16", "map": [5, 4, 3, 2, 1, 0], "count": 6}})
    assert hw.num_keys == 6
    hw.matrix.events.items = [FakeEvent(4, True)]
    assert hw.poll(0) == [(4, True)]
    hw.set_led(0, (7, 7, 7))
    assert hw.pixels.strip[5] == (7, 7, 7)   # pixel map applied


def test_bad_pin_name(drivers):
    mod = drivers.import_module("cuekeys_drivers.keypad_keys")
    with pytest.raises(ValueError, match="no pin"):
        mod.Hardware({"pins": ["NOPE"]})


def test_builtin_profiles_name_existing_drivers():
    from pathlib import Path

    from cuekeys import devices

    driver_dir = Path(__file__).resolve().parent.parent / "firmware" / "lib" / "cuekeys_drivers"
    for profile in devices.all_profiles().values():
        if profile.driver_file is None:
            assert (driver_dir / (profile.driver + ".py")).exists(), profile.id

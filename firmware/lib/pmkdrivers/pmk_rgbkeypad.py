# SPDX-License-Identifier: MIT
"""Pimoroni Pico RGB Keypad Base."""

from pmk.platform.rgbkeypadbase import RGBKeypadBase

from ._pmk import PMKHardware


class Hardware(PMKHardware):
    def __init__(self, config):
        super().__init__(RGBKeypadBase(), config)

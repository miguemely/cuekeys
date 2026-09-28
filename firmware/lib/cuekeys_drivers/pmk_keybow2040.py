# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
"""Pimoroni Keybow 2040."""

from pmk.platform.keybow2040 import Keybow2040

from ._pmk import PMKHardware


class Hardware(PMKHardware):
    def __init__(self, config):
        super().__init__(Keybow2040(), config)

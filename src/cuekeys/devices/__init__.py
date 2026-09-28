# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
"""Device profiles: which keypads CueKeys can drive.

A profile is a folder with a ``device.json`` (and optionally a firmware
``driver.py``)::

    {
      "id": "keybow2040",
      "name": "Pimoroni Keybow 2040",
      "vendor": "Pimoroni",
      "board_ids": ["pimoroni_keybow2040"],        # from boot_out.txt, for detection
      "grid": [[3, 7, 11, 15],                     # key numbers, top row first,
               [2, 6, 10, 14],                     # null for gaps
               [1, 5,  9, 13],
               [0, 4,  8, 12]],
      "leds": "rgb",                               # "rgb" or "none"
      "led_gamma": 2.2,                            # colour correction defaults;
      "led_balance": [1.0, 1.0, 1.0],              # layouts can override both
      "connector": "top",                          # USB side, for the editor hint
      "driver": "pmk_keybow2040",                  # module in CIRCUITPY/lib/cuekeys_drivers
      "driver_config": {},                         # passed to the driver
      "libraries": ["pmk", "adafruit_is31fl3731"]  # extra CIRCUITPY/lib requirements
    }

Profiles are loaded from, in order (later ones override earlier ones with the
same id):

1. the built-in ``devices/builtin`` folder,
2. installed packages exposing the ``cuekeys.devices`` entry point
   (a callable returning a folder path or a list of them),
3. the user folder (see :func:`user_device_dir`),
4. folders listed in ``$CUEKEYS_DEVICE_PATH`` (``os.pathsep`` separated).

Each search folder may contain profile folders (``<dir>/<id>/device.json``) or
plain ``*.json`` profile files.
"""

import json
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"
ENTRY_POINT_GROUP = "cuekeys.devices"
DEFAULT_PROFILE = "keybow2040"
DEFAULT_GAMMA = 2.2
LED_TYPES = ("rgb", "none")
SIDES = ("top", "right", "bottom", "left")
# Legacy "device.hardware" values -> profile ids.
LEGACY_HARDWARE = {"keybow2040": "keybow2040", "rgbkeypad": "rgbkeypad"}


class ProfileError(ValueError):
    pass


class DeviceProfile:
    """A keypad model: its key grid, LEDs and firmware driver."""

    def __init__(self, data, source=None):
        self.data = data
        self.source = Path(source) if source else None
        try:
            self.id = str(data["id"])
            self.name = str(data.get("name") or self.id)
            grid = data["grid"]
            self.driver = str(data["driver"])
        except KeyError as err:
            raise ProfileError("missing field %s" % err) from None
        self.vendor = str(data.get("vendor", ""))
        self.description = str(data.get("description", ""))
        self.board_ids = [str(b) for b in data.get("board_ids", [])]
        self.leds = data.get("leds", "rgb")
        self.connector = data.get("connector", "top")
        self.driver_config = dict(data.get("driver_config") or {})
        self.libraries = [str(lib) for lib in data.get("libraries", [])]
        self.tested = bool(data.get("tested", False))
        self.led_gamma = float(data.get("led_gamma", DEFAULT_GAMMA))
        self.led_balance = [float(v) for v in data.get("led_balance", [1.0, 1.0, 1.0])]
        if len(self.led_balance) != 3 or not all(0 <= v <= 1 for v in self.led_balance):
            raise ProfileError("%s: led_balance must be three numbers 0-1" % data.get("id"))
        self._parse_grid(grid)
        if self.leds not in LED_TYPES:
            raise ProfileError("%s: leds must be one of %s" % (self.id, ", ".join(LED_TYPES)))
        if self.connector not in SIDES:
            raise ProfileError("%s: connector must be one of %s" % (self.id, ", ".join(SIDES)))
        # A plugin may ship its own firmware driver next to device.json.
        self.driver_file = None
        if self.source is not None:
            candidate = self.source.parent / "driver.py"
            if self.source.name == "device.json" and candidate.exists():
                self.driver_file = candidate

    def _parse_grid(self, grid):
        if not isinstance(grid, list) or not grid or not all(isinstance(r, list) for r in grid):
            raise ProfileError("%s: grid must be a list of rows" % self.id)
        width = len(grid[0])
        if width == 0 or any(len(row) != width for row in grid):
            raise ProfileError("%s: every grid row must have the same length" % self.id)
        cells = {}
        for r, row in enumerate(grid):
            for c, key in enumerate(row):
                if key is None:
                    continue
                if isinstance(key, bool) or not isinstance(key, int) or key < 0:
                    raise ProfileError("%s: grid entries must be key numbers or null" % self.id)
                if key in cells:
                    raise ProfileError("%s: key %d appears twice in the grid" % (self.id, key))
                cells[key] = (r, c)
        if sorted(cells) != list(range(len(cells))):
            raise ProfileError("%s: keys must be numbered 0..%d without gaps" % (self.id, len(cells) - 1))
        self.grid = [list(row) for row in grid]
        self.rows, self.cols = len(grid), width
        self.num_keys = len(cells)
        self._cells = cells

    # ------------------------------------------------------------------ geometry
    def display_size(self, rotation=0):
        """(rows, cols) as drawn on screen for a rotation of 0/90/180/270."""
        return (self.cols, self.rows) if (rotation // 90) % 2 else (self.rows, self.cols)

    def key_to_cell(self, key, rotation=0):
        """Key number -> (row, col) on screen, row 0 at the top."""
        row, col = self._cells[key]
        height, width = self.rows, self.cols
        for _ in range((rotation // 90) % 4):
            # rotate 90 degrees clockwise: (r, c) in H x W -> (c, H-1-r) in W x H
            row, col = col, height - 1 - row
            height, width = width, height
        return row, col

    def cell_to_key(self, row, col, rotation=0):
        """Key at a screen cell, or None for a gap / outside the grid."""
        for key in self._cells:
            if self.key_to_cell(key, rotation) == (row, col):
                return key
        return None

    def keys(self):
        return range(self.num_keys)

    def satellite_index(self, key, rotation=0):
        """Companion Satellite key index: left-to-right, top-to-bottom."""
        row, col = self.key_to_cell(key, rotation)
        return row * self.display_size(rotation)[1] + col

    def key_from_satellite(self, index, rotation=0):
        cols = self.display_size(rotation)[1]
        return self.cell_to_key(index // cols, index % cols, rotation)

    def connector_side(self, rotation=0):
        return SIDES[(SIDES.index(self.connector) + (rotation // 90)) % 4]

    # ------------------------------------------------------------------ firmware
    def firmware_device(self):
        """Fields the keypad firmware needs to pick and configure its driver."""
        return {"profile": self.id, "driver": self.driver,
                "driver_config": self.driver_config, "num_keys": self.num_keys,
                "led_gamma": self.led_gamma, "led_balance": list(self.led_balance)}

    def __repr__(self):
        return "<DeviceProfile %s %dx%d>" % (self.id, self.cols, self.rows)


# ---------------------------------------------------------------------- loading
def _config_base():
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def user_device_dir():
    """Per-user folder for device plugins."""
    return _config_base() / "cuekeys" / "devices"


def legacy_device_dir():
    """Plugin folder used before the project was renamed from "PMK Macro Manager"."""
    return _config_base() / "pmk-macro-manager" / "devices"


def _entry_point_dirs():
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover
        return []
    dirs = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            result = ep.load()
            result = result() if callable(result) else result
            dirs.extend(result if isinstance(result, (list, tuple)) else [result])
        except Exception as err:  # noqa: BLE001 - a broken plugin must not break the app
            log.warning("device plugin %s failed to load: %s", ep.name, err)
    return [Path(d) for d in dirs]


def search_paths():
    paths = [BUILTIN_DIR]
    paths.extend(_entry_point_dirs())
    if legacy_device_dir().is_dir():
        paths.append(legacy_device_dir())
    paths.append(user_device_dir())
    extra = os.environ.get("CUEKEYS_DEVICE_PATH")
    if extra:
        paths.extend(Path(p) for p in extra.split(os.pathsep) if p)
    return paths


def _profile_files(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    files = sorted(folder.glob("*/device.json"))
    files.extend(sorted(p for p in folder.glob("*.json") if p.is_file()))
    return files


def load_profile(path):
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        return DeviceProfile(json.load(f), path)


_cache = None
_errors = []


def reload():
    """(Re)scan all search paths. Returns {id: DeviceProfile}."""
    global _cache
    profiles, errors = {}, []
    for folder in search_paths():
        for path in _profile_files(folder):
            try:
                profile = load_profile(path)
            except (OSError, ValueError) as err:
                errors.append("%s: %s" % (path, err))
                log.warning("skipping device profile %s: %s", path, err)
                continue
            profiles[profile.id] = profile
    _cache = profiles
    _errors[:] = errors
    return profiles


def all_profiles():
    return dict(_cache if _cache is not None else reload())


def load_errors():
    all_profiles()
    return list(_errors)


def get_profile(profile_id):
    profiles = all_profiles()
    if profile_id not in profiles:
        raise KeyError("unknown device profile %r (known: %s)" % (profile_id, ", ".join(sorted(profiles))))
    return profiles[profile_id]


def profile_id(config):
    device = (config or {}).get("device") or {}
    return device.get("profile") or LEGACY_HARDWARE.get(device.get("hardware"), DEFAULT_PROFILE)


def profile_for(config):
    """The profile a layout targets; falls back to the default for unknown ids."""
    try:
        return get_profile(profile_id(config))
    except KeyError:
        return get_profile(DEFAULT_PROFILE)


def match_board(board_id):
    """Profiles whose ``board_ids`` include this CircuitPython board id."""
    return [p for p in all_profiles().values() if board_id and board_id in p.board_ids]

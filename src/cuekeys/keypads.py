# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Per-keypad settings, keyed by the keypad's hardware id.

Layouts are portable (share them, use one on several keypads); things that
belong to one physical unit live here instead::

    {
      "E6617C93E35B8C2B": {
        "name": "Keybow FOH",            # shown in the editor, overlay and Companion
        "layout": "/path/to/show.json",  # layout this keypad uses
        "led_gamma": 2.2,                # LED calibration of this unit
        "led_balance": [0.7, 1.0, 0.8],
        "last_seen": 1790000000
      }
    }

Stored in ``<config dir>/cuekeys/keypads.json``.
"""

import copy
import json
import os
import threading
import time
from pathlib import Path

from . import devices

VIRTUAL_UID = "VIRTUAL"   # the editor's stand-in when no keypad is connected
KNOWN_FIELDS = ("name", "layout", "led_gamma", "led_balance", "last_seen")


def default_path():
    return devices._config_base() / "cuekeys" / "keypads.json"


def short_id(uid):
    """Last 8 hex digits, lower case: enough to tell keypads apart in ids and UI."""
    return str(uid)[-8:].lower()


class KeypadStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else default_path()
        self._lock = threading.Lock()
        self._data = self._read()

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    def get(self, uid):
        with self._lock:
            return copy.deepcopy(self._data.get(str(uid).upper(), {}))

    def all(self):
        with self._lock:
            return copy.deepcopy(self._data)

    def update(self, uid, **fields):
        """Set fields (``None`` removes one) and save."""
        uid = str(uid).upper()
        with self._lock:
            entry = self._data.setdefault(uid, {})
            for key, value in fields.items():
                if value is None:
                    entry.pop(key, None)
                else:
                    entry[key] = value
            self._write()
            return copy.deepcopy(entry)

    def forget(self, uid):
        with self._lock:
            if self._data.pop(str(uid).upper(), None) is not None:
                self._write()
                return True
            return False

    def seen(self, uid):
        return self.update(uid, last_seen=int(time.time()))

    def name(self, uid):
        if uid == VIRTUAL_UID:
            return "No keypad"
        return self.get(uid).get("name") or "Keypad %s" % short_id(uid)

"""Layout configuration: schema, defaults, validation, load/save.

A config is plain JSON so the keypad can read it directly::

    {
      "version": 1,
      "device":  {...},              # read by the firmware
      "layers":  [{"name", "color", "mode", "keys": {"0": KEY, ...}}],
      "bridge":  {...},              # OSC / grandMA / Companion targets (host only)
      "overlay": {...}               # on-screen reference window (host only)
    }

    KEY = {"label", "color", "press": [ACTION], "release": [...], "hold": [...]}

``ACTION_SPECS`` describes every action type; the GUI builds its editor forms
from it and ``validate()`` checks configs against it.
"""

import copy
import json
import os
from pathlib import Path

from . import devices
from .keycodes import CONSUMER_CODES, KEYCODE_SET

CONFIG_VERSION = 1

LAYER_MODES = ("local", "companion")
LAYER_OPS = ("goto", "next", "prev", "toggle", "momentary")
MSC_COMMANDS = ("go", "stop", "resume", "timed_go", "load", "set", "fire",
                "all_off", "restore", "reset", "go_off")
MSC_FORMATS = ("all", "lighting", "moving_lights")
MA_CONSOLES = ("ma3", "ma2")
KEY_SLOTS = ("press", "release", "hold")
OVERLAY_OPS = ("cycle", "toggle", "show", "hide")
DEFAULT_OVERLAY_LEVELS = [0.9, 0.6, 0.3, 0]
CORNERS = ("bottom-right", "bottom-left", "top-right", "top-left")


def F(name, kind, default=None, label=None, choices=None, optional=False,
      minimum=None, maximum=None, help=None):
    return {"name": name, "kind": kind, "default": default,
            "label": label or name.replace("_", " ").capitalize(),
            "choices": choices, "optional": optional,
            "min": minimum, "max": maximum, "help": help}


CHANNEL = F("channel", "int", None, "MIDI channel", optional=True, minimum=1, maximum=16,
            help="Blank = device default channel")

# kind: str | text | int | bool | choice | keys | json | layer
ACTION_SPECS = {
    "keys": {
        "label": "Key combo",
        "fields": [
            F("keys", "keys", ["PRIMARY", "C"], help="e.g. ctrl+shift+s. PRIMARY = Cmd on Mac, Ctrl elsewhere"),
            F("mode", "choice", "tap", choices=("tap", "hold"),
              help="hold = keep keys down while the button is held"),
        ],
    },
    "text": {"label": "Type text", "fields": [F("text", "text", "")]},
    "delay": {"label": "Delay", "fields": [F("ms", "int", 100, "Milliseconds", minimum=0, maximum=60000)]},
    "key_down": {"label": "Key down", "fields": [F("keys", "keys", ["SHIFT"])]},
    "key_up": {"label": "Key up", "fields": [F("keys", "keys", ["SHIFT"])]},
    "release_all": {"label": "Release all keys", "fields": []},
    "consumer": {"label": "Media key", "fields": [F("code", "choice", "PLAY_PAUSE", choices=tuple(CONSUMER_CODES))]},
    "layer": {
        "label": "Layer",
        "fields": [
            F("op", "choice", "goto", "Operation", choices=LAYER_OPS),
            F("layer", "layer", 0, optional=True, help="Ignored for next/prev"),
        ],
    },
    "midi_note": {
        "label": "MIDI note",
        "fields": [
            F("note", "int", 60, minimum=0, maximum=127),
            F("velocity", "int", 127, minimum=0, maximum=127),
            CHANNEL,
            F("mode", "choice", "momentary", choices=("momentary", "tap", "toggle"),
              help="momentary = note off on release (grandMA flash/temp)"),
        ],
    },
    "midi_cc": {
        "label": "MIDI CC",
        "fields": [
            F("cc", "int", 1, "CC number", minimum=0, maximum=127),
            F("value", "int", 127, minimum=0, maximum=127),
            F("release_value", "int", None, optional=True, minimum=0, maximum=127),
            CHANNEL,
        ],
    },
    "midi_pc": {"label": "MIDI program change",
                "fields": [F("program", "int", 0, minimum=0, maximum=127), CHANNEL]},
    "msc": {
        "label": "MIDI Show Control",
        "fields": [
            F("command", "choice", "go", choices=MSC_COMMANDS),
            F("cue", "str", "", optional=True, help="e.g. 1.5"),
            F("cue_list", "str", "", "Cue list / exec.page", optional=True,
              help="grandMA2 Exec.Page mode: executor.page, e.g. 1.1"),
            F("cue_path", "str", "", optional=True),
            F("macro", "int", None, "Macro (fire)", optional=True, minimum=0, maximum=127),
            F("control", "int", None, "Control (set)", optional=True, minimum=0, maximum=16383),
            F("value", "int", None, "Value (set)", optional=True, minimum=0, maximum=16383),
            F("device_id", "int", 127, "Device ID", minimum=0, maximum=127, help="127 = all devices"),
            F("command_format", "choice", "all", choices=MSC_FORMATS),
        ],
    },
    "osc": {
        "label": "OSC message",
        "fields": [
            F("address", "str", "/"),
            F("args", "json", [], "Arguments (JSON list)"),
            F("release_args", "json", None, "Release arguments", optional=True,
              help="Sent again on release with these arguments"),
            F("target", "str", "default", help="Name of an OSC target in bridge settings"),
        ],
    },
    "ma": {
        "label": "grandMA command",
        "fields": [
            F("command", "str", "Go+ Executor 201", help="Command line text"),
            F("release_command", "str", "", optional=True, help="e.g. Off Executor 201"),
            F("console", "choice", "ma3", choices=MA_CONSOLES,
              help="ma3 = OSC /cmd, ma2 = Telnet"),
        ],
    },
    "companion": {
        "label": "Companion button",
        "fields": [
            F("page", "int", 1, minimum=1, maximum=999),
            F("row", "int", 0, minimum=0, maximum=99),
            F("column", "int", 0, minimum=0, maximum=99),
            F("mode", "choice", "hold", choices=("hold", "press"),
              help="hold = down on press, up on release"),
            F("target", "str", "default"),
        ],
    },
    "companion_page": {
        "label": "Companion page",
        "fields": [
            F("direction", "choice", "next", choices=("next", "prev"),
              help="Pages the Companion surface of the current layer (Companion 4.3+)"),
        ],
    },
    "overlay": {
        "label": "Overlay",
        "fields": [
            F("op", "choice", "cycle", "Operation", choices=OVERLAY_OPS,
              help="cycle = step through the opacity levels (0 = hidden)"),
            F("levels", "json", None, "Opacity levels", optional=True,
              help="Default [0.9, 0.6, 0.3, 0]"),
        ],
    },
    "host": {
        "label": "Host event",
        "fields": [F("event", "str", ""), F("data", "json", None, optional=True)],
    },
}

ACTION_TYPES = tuple(ACTION_SPECS)


def default_action(kind):
    action = {"type": kind}
    for field in ACTION_SPECS[kind]["fields"]:
        if not field["optional"]:
            action[field["name"]] = copy.deepcopy(field["default"])
    return action


def describe_action(action):
    """One-line human readable summary, used in lists and the overlay."""
    kind = action.get("type")
    if kind in ("keys", "key_down", "key_up"):
        return "%s %s" % (ACTION_SPECS[kind]["label"], "+".join(action.get("keys", [])))
    if kind == "text":
        text = action.get("text", "")
        return "Type %r" % (text if len(text) < 24 else text[:21] + "...")
    if kind == "delay":
        return "Wait %d ms" % action.get("ms", 0)
    if kind == "consumer":
        return "Media %s" % action.get("code")
    if kind == "layer":
        op = action.get("op", "goto")
        return "Layer %s" % op if op in ("next", "prev") else "Layer %s %s" % (op, action.get("layer", 0))
    if kind == "midi_note":
        return "Note %s vel %s" % (action.get("note"), action.get("velocity", 127))
    if kind == "midi_cc":
        return "CC %s = %s" % (action.get("cc"), action.get("value"))
    if kind == "midi_pc":
        return "Program %s" % action.get("program")
    if kind == "msc":
        detail = action.get("cue") or action.get("macro") or ""
        return ("MSC %s %s" % (action.get("command", "go"), detail)).strip()
    if kind == "osc":
        return "OSC %s %s" % (action.get("address"), json.dumps(action.get("args", [])))
    if kind == "ma":
        return "MA: %s" % action.get("command", "")
    if kind == "companion":
        return "Companion %s/%s/%s" % (action.get("page"), action.get("row"), action.get("column"))
    if kind == "companion_page":
        return "Companion page %s" % ("◀" if action.get("direction") == "prev" else "▶")
    if kind == "overlay":
        return "Overlay %s" % action.get("op", "cycle")
    if kind == "host":
        return "Host %s" % action.get("event")
    return kind or "?"


def default_config():
    return {
        "version": CONFIG_VERSION,
        "device": {
            "profile": devices.DEFAULT_PROFILE,
            "brightness": 0.5,
            "hold_time_ms": 500,
            "debounce_ms": 15,
            "midi_channel": 1,
            "keyboard_layout": "us",
            "host_os": "auto",
            "pressed_color": "#ffffff",
        },
        "layers": [
            {"name": "Main", "color": "#3050ff", "mode": "local", "keys": {}},
        ],
        "bridge": {
            "osc_targets": {"default": {"host": "127.0.0.1", "port": 8000}},
            "ma3": {"host": "127.0.0.1", "port": 8000, "prefix": "gma3"},
            "ma2": {"host": "127.0.0.1", "port": 30000, "user": "administrator", "password": ""},
            "companion": {"default": {"host": "127.0.0.1", "http_port": 8000,
                                      "satellite_port": 16622}},
        },
        "overlay": {
            "enabled": True,
            "opacity": 0.8,
            "corner": "bottom-right",
            "margin": 24,
            "key_size": 64,
            "click_through": True,
            "all_spaces": True,
            "screens": "primary",  # "primary", "all", "mouse", or a list of display names
            "rotation": 0,
        },
    }


def merge_defaults(config):
    """Fill in missing top-level sections/keys without touching existing ones."""
    base = default_config()
    out = copy.deepcopy(config)
    legacy = (out.get("device") or {}).get("hardware")
    for section in ("device", "bridge", "overlay"):
        merged = copy.deepcopy(base[section])
        merged.update(out.get(section) or {})
        out[section] = merged
    # Layouts from before device profiles name the hardware instead.
    if legacy and "profile" not in (config.get("device") or {}):
        out["device"]["profile"] = devices.LEGACY_HARDWARE.get(legacy, legacy)
    out["device"].pop("hardware", None)
    out.setdefault("version", CONFIG_VERSION)
    if not out.get("layers"):
        out["layers"] = base["layers"]
    return out


# --------------------------------------------------------------------- validation
def _check_field(field, value, where, errors, layer_count):
    kind = field["kind"]
    if value is None:
        if not field["optional"]:
            errors.append("%s: missing %s" % (where, field["name"]))
        return
    if kind in ("int", "layer"):
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append("%s: %s must be an integer" % (where, field["name"]))
            return
        lo = 0 if kind == "layer" else field["min"]
        hi = layer_count - 1 if kind == "layer" else field["max"]
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            errors.append("%s: %s=%s out of range" % (where, field["name"], value))
    elif kind in ("str", "text"):
        if not isinstance(value, str):
            errors.append("%s: %s must be a string" % (where, field["name"]))
    elif kind == "choice":
        if value not in field["choices"]:
            errors.append("%s: %s=%r not one of %s" % (where, field["name"], value,
                                                       ", ".join(field["choices"])))
    elif kind == "keys":
        if not isinstance(value, list) or not value:
            errors.append("%s: keys must be a non-empty list" % where)
            return
        for name in value:
            if name not in KEYCODE_SET:
                errors.append("%s: unknown key %r" % (where, name))


def validate_action(action, where, layer_count=1):
    errors = []
    if not isinstance(action, dict):
        return ["%s: action must be an object" % where]
    kind = action.get("type")
    spec = ACTION_SPECS.get(kind)
    if spec is None:
        return ["%s: unknown action type %r" % (where, kind)]
    for field in spec["fields"]:
        _check_field(field, action.get(field["name"]), where, errors, layer_count)
    if kind == "osc" and not str(action.get("address", "")).startswith("/"):
        errors.append("%s: OSC address must start with /" % where)
    if kind == "osc" and not isinstance(action.get("args", []), list):
        errors.append("%s: OSC args must be a list" % where)
    if kind == "overlay" and action.get("levels") is not None:
        levels = action["levels"]
        if not isinstance(levels, list) or not levels or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in levels):
            errors.append("%s: overlay levels must be a list of numbers 0-1" % where)
    if kind == "msc":
        cmd = action.get("command")
        if cmd == "fire" and action.get("macro") is None:
            errors.append("%s: MSC fire needs a macro" % where)
        if cmd == "set" and (action.get("control") is None or action.get("value") is None):
            errors.append("%s: MSC set needs control and value" % where)
        for name in ("cue", "cue_list", "cue_path"):
            text = action.get(name) or ""
            if any(ord(c) > 127 for c in text):
                errors.append("%s: MSC %s must be ASCII" % (where, name))
    return errors


def validate(config):
    """Return a list of human readable problems (empty = valid)."""
    errors = []
    if not isinstance(config, dict):
        return ["config must be a JSON object"]
    device = config.get("device", {})
    try:
        profile = devices.get_profile(devices.profile_id(config))
    except KeyError as err:
        errors.append(str(err).strip("'\""))
        profile = devices.profile_for(config)
    rotation = int(config.get("overlay", {}).get("rotation", 0))
    display_rows = profile.display_size(rotation)[0]
    brightness = device.get("brightness", 0.5)
    if not isinstance(brightness, (int, float)) or not 0 <= brightness <= 1:
        errors.append("device.brightness must be between 0 and 1")
    gamma = device.get("led_gamma", 2.2)
    if isinstance(gamma, bool) or not isinstance(gamma, (int, float)) or not 1 <= gamma <= 3:
        errors.append("device.led_gamma must be between 1 and 3")
    balance = device.get("led_balance", [1, 1, 1])
    if not isinstance(balance, list) or len(balance) != 3 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in balance):
        errors.append("device.led_balance must be three numbers between 0 and 1")
    layers = config.get("layers")
    if not isinstance(layers, list) or not layers:
        return errors + ["config needs at least one layer"]
    for li, layer in enumerate(layers):
        lw = "layer %d (%s)" % (li, layer.get("name", ""))
        if layer.get("mode", "local") not in LAYER_MODES:
            errors.append("%s: mode must be one of %s" % (lw, ", ".join(LAYER_MODES)))
        rows = layer.get("companion_rows")
        if rows is not None and (isinstance(rows, bool) or not isinstance(rows, int)
                                 or not 1 <= rows <= display_rows):
            errors.append("%s: companion_rows must be 1-%d for %s" % (lw, display_rows, profile.name))
        keys = layer.get("keys") or {}
        if not isinstance(keys, dict):
            errors.append("%s: keys must be an object" % lw)
            continue
        for key_id, key in keys.items():
            if not str(key_id).isdigit() or not 0 <= int(key_id) < profile.num_keys:
                errors.append("%s: invalid key number %r (%s has keys 0-%d)"
                              % (lw, key_id, profile.name, profile.num_keys - 1))
                continue
            for slot in KEY_SLOTS:
                actions = key.get(slot) or []
                if not isinstance(actions, list):
                    errors.append("%s key %s: %s must be a list" % (lw, key_id, slot))
                    continue
                for ai, action in enumerate(actions):
                    where = "%s key %s %s[%d]" % (lw, key_id, slot, ai)
                    errors.extend(validate_action(action, where, len(layers)))
    return errors


def companion_rows(layer, profile, rotation=0):
    """Rows (from the top) a Companion layer hands to Companion.

    Defaults to all but the bottom row, which stays local.
    """
    rows = profile.display_size(rotation)[0]
    wanted = layer.get("companion_rows")
    if wanted is None:
        wanted = rows - 1 if rows > 1 else rows
    return max(1, min(int(wanted), rows))


def in_companion_region(layer, key, profile, rotation=0):
    """True if ``key`` sits in the part of the pad a Companion layer hands to Companion."""
    if layer.get("mode") != "companion" or not 0 <= key < profile.num_keys:
        return False
    row, _col = profile.key_to_cell(key, rotation)
    return row < companion_rows(layer, profile, rotation)


def key_is_assigned(key):
    return bool(key) and (any(key.get(slot) for slot in KEY_SLOTS)
                          or bool(key.get("label")) or bool(key.get("color")))


def prune(config):
    """Copy of ``config`` without empty action lists / keys left by the editor."""
    out = copy.deepcopy(config)
    for layer in out.get("layers", []):
        keys = layer.get("keys") or {}
        for key_id in list(keys):
            key = keys[key_id]
            for slot in KEY_SLOTS:
                if slot in key and not key[slot]:
                    del key[slot]
            if not key_is_assigned(key):
                del keys[key_id]
        layer["keys"] = dict(sorted(keys.items(), key=lambda kv: int(kv[0])))
    return out


# --------------------------------------------------------------------- file I/O
def load(path):
    with open(path, encoding="utf-8") as f:
        return merge_defaults(json.load(f))


def dumps(config):
    return json.dumps(config, indent=2, sort_keys=False) + "\n"


def save(config, path):
    """Write atomically where the filesystem allows it."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(prune(config)))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def firmware_view(config):
    """The subset of a config that the keypad needs (keeps secrets off the drive)."""
    device = dict(config.get("device", {}))
    device.pop("hardware", None)
    # The keypad needs the resolved driver details, not just the profile id.
    # LED colour correction from the layout (a calibrated pad) beats the profile's.
    for key, value in devices.profile_for(config).firmware_device().items():
        if key.startswith("led_"):
            device.setdefault(key, value)
        else:
            device[key] = value
    return {
        "version": config.get("version", CONFIG_VERSION),
        "device": device,
        "layers": config.get("layers", []),
    }

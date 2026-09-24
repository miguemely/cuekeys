"""Demo layout showing every major feature."""

from .config import default_config


def _k(keys, mode="tap"):
    return {"type": "keys", "keys": keys, "mode": mode}


# Bottom-left key on every layer: tap = next layer, hold = back to layer 0.
LAYER_KEY = {
    "label": "Next layer\n(hold: home)",
    "color": "#ffffff",
    "press": [{"type": "layer", "op": "next"}],
    "hold": [{"type": "layer", "op": "goto", "layer": 0}],
}


def example_config():
    config = default_config()
    editing = {
        "name": "Editing",
        "color": "#3050ff",
        "mode": "local",
        "keys": {
            "0": LAYER_KEY,
            "3": {"label": "Copy", "press": [_k(["PRIMARY", "C"])]},
            "7": {"label": "Paste", "press": [_k(["PRIMARY", "V"])]},
            "11": {"label": "Undo", "press": [_k(["PRIMARY", "Z"])]},
            "15": {"label": "Redo", "press": [_k(["PRIMARY", "SHIFT", "Z"])]},
            "2": {"label": "Save", "color": "#20c050", "press": [_k(["PRIMARY", "S"])]},
            "6": {"label": "Hello", "press": [{"type": "text", "text": "Hello from PMK!"}]},
            "10": {"label": "Select all\n+ copy", "press": [
                _k(["PRIMARY", "A"]), {"type": "delay", "ms": 50}, _k(["PRIMARY", "C"])]},
            "14": {"label": "Shift\n(held)", "press": [_k(["SHIFT"], "hold")]},
            "1": {"label": "Vol -", "color": "#ff8800", "press": [{"type": "consumer", "code": "VOLUME_DECREMENT"}]},
            "5": {"label": "Mute", "color": "#ff8800", "press": [{"type": "consumer", "code": "MUTE"}]},
            "9": {"label": "Vol +", "color": "#ff8800", "press": [{"type": "consumer", "code": "VOLUME_INCREMENT"}]},
            "13": {"label": "Play", "color": "#ff8800", "press": [{"type": "consumer", "code": "PLAY_PAUSE"}]},
        },
    }
    ma3 = {
        "name": "grandMA3",
        "color": "#ffb000",
        "mode": "local",
        "keys": {
            "0": LAYER_KEY,
            "3": {"label": "Go+ 201", "color": "#20c050",
                  "press": [{"type": "ma", "console": "ma3", "command": "Go+ Executor 201"}]},
            "7": {"label": "Go- 201",
                  "press": [{"type": "ma", "console": "ma3", "command": "Go- Executor 201"}]},
            "11": {"label": "Pause 201", "color": "#ffff00",
                   "press": [{"type": "ma", "console": "ma3", "command": "Pause Executor 201"}]},
            "15": {"label": "Off 201", "color": "#ff2020",
                   "press": [{"type": "ma", "console": "ma3", "command": "Off Executor 201"}]},
            "2": {"label": "Clear", "press": [{"type": "ma", "console": "ma3", "command": "Clear"}]},
            "6": {"label": "MSC Go\ncue 1", "color": "#00c0ff",
                  "press": [{"type": "msc", "command": "go", "cue": "1", "device_id": 127,
                             "command_format": "all"}]},
            "10": {"label": "MSC fire\nmacro 1", "color": "#00c0ff",
                   "press": [{"type": "msc", "command": "fire", "macro": 1, "device_id": 127,
                              "command_format": "all"}]},
            "14": {"label": "Fader 201\n100%", "color": "#c000ff",
                   "press": [{"type": "osc", "address": "/gma3/Page1/Fader201", "args": [100],
                              "release_args": [0], "target": "default"}]},
        },
    }
    ma2 = {
        "name": "grandMA2",
        "color": "#ff5000",
        "mode": "local",
        "keys": dict(
            {"0": LAYER_KEY,
             "15": {"label": "Telnet\nGo 1.1", "color": "#20c050",
                    "press": [{"type": "ma", "console": "ma2", "command": "Go Executor 1.1"}]}},
            **{
                str(k): {"label": "Exec note %d" % n,
                         "press": [{"type": "midi_note", "note": n, "velocity": 127,
                                    "mode": "momentary"}]}
                for n, k in enumerate([3, 7, 11, 2, 6, 10, 14, 1, 5, 9, 13, 4, 8, 12])
            }),
    }
    # Top three rows: a 4x3 Companion surface. Bottom row: PMK's own keys.
    companion = {
        "name": "Companion",
        "color": "#e03030",
        "mode": "companion",
        "companion_id": "pmk-example",
        "companion_rows": 3,
        "keys": {
            "0": LAYER_KEY,
            "4": {"label": "◀ Page", "color": "#4a5670",
                  "press": [{"type": "companion_page", "direction": "prev"}]},
            "8": {"label": "Page ▶", "color": "#4a5670",
                  "press": [{"type": "companion_page", "direction": "next"}]},
            "12": {"label": "Overlay\nopacity", "color": "#8a5cff",
                   "press": [{"type": "overlay", "op": "cycle", "levels": [0.9, 0.6, 0.3, 0]}]},
        },
    }
    config["layers"] = [editing, ma3, ma2, companion]
    return config

from cuekeys_engine import midi
from cuekeys_engine.engine import ACTION_TYPES, Engine


class Clock:
    def __init__(self):
        self.now = 1000

    def __call__(self):
        return self.now


class Backend:
    def __init__(self):
        self.events = []
        self.leds = {}

    def key_down(self, names):
        self.events.append(("down", tuple(names)))

    def key_up(self, names):
        self.events.append(("up", tuple(names)))

    def release_all(self):
        self.events.append(("release_all",))

    def write_text(self, text):
        self.events.append(("text", text))

    def consumer(self, name):
        self.events.append(("consumer", name))

    def midi(self, data):
        self.events.append(("midi", bytes(data)))

    def host(self, message):
        if message["t"] not in ("key", "layer"):
            self.events.append(("host", message))

    def set_led(self, index, rgb):
        self.leds[index] = rgb

    def take(self):
        out, self.events = self.events, []
        return out


def make(layers, device=None):
    clock, backend = Clock(), Backend()
    engine = Engine({"device": device or {"brightness": 1.0}, "layers": layers}, backend, clock)
    return engine, backend, clock


def tap(engine, clock, key, hold_ms=10):
    engine.press(key)
    engine.tick()
    clock.now += hold_ms
    engine.tick()
    engine.release(key)
    engine.tick()


def test_key_combo_tap():
    engine, backend, clock = make([{"keys": {"0": {"press": [{"type": "keys", "keys": ["PRIMARY", "C"]}]}}}])
    tap(engine, clock, 0)
    assert backend.take() == [("down", ("CONTROL", "C")), ("up", ("CONTROL", "C"))]
    engine.host_os = "mac"
    tap(engine, clock, 0)
    assert backend.take()[0] == ("down", ("COMMAND", "C"))


def test_held_combo_released_on_key_up():
    engine, backend, clock = make([{"keys": {"1": {"press": [{"type": "keys", "keys": ["SHIFT"], "mode": "hold"}]}}}])
    engine.press(1)
    engine.tick()
    assert backend.take() == [("down", ("SHIFT",))]
    engine.release(1)
    engine.tick()
    assert backend.take() == [("up", ("SHIFT",))]


def test_macro_delays_are_ordered():
    actions = [{"type": "text", "text": "a"}, {"type": "delay", "ms": 100}, {"type": "text", "text": "b"}]
    engine, backend, clock = make([{"keys": {"0": {"press": actions}}}])
    engine.press(0)
    engine.release(0)
    engine.tick()
    assert backend.take() == [("text", "a")]
    clock.now += 99
    engine.tick()
    assert backend.take() == []
    clock.now += 1
    engine.tick()
    assert backend.take() == [("text", "b")]
    assert engine.idle()


def test_tap_hold():
    key = {"press": [{"type": "text", "text": "tap"}], "hold": [{"type": "text", "text": "hold"}]}
    engine, backend, clock = make([{"keys": {"0": key}}], {"hold_time_ms": 300})
    tap(engine, clock, 0, hold_ms=100)
    assert backend.take() == [("text", "tap")]
    engine.press(0)
    clock.now += 300
    engine.tick()
    engine.release(0)
    engine.tick()
    assert backend.take() == [("text", "hold")]


def test_layers():
    layers = [
        {"name": "A", "keys": {"0": {"press": [{"type": "layer", "op": "next"}]},
                               "1": {"press": [{"type": "layer", "op": "momentary", "layer": 2}]},
                               "2": {"press": [{"type": "layer", "op": "toggle", "layer": 2}]}}},
        {"name": "B", "keys": {"0": {"press": [{"type": "layer", "op": "prev"}]}}},
        {"name": "C", "keys": {"2": {"press": [{"type": "layer", "op": "toggle", "layer": 2}]}}},
    ]
    engine, backend, clock = make(layers)
    tap(engine, clock, 0)
    assert engine.layer == 1
    tap(engine, clock, 0)
    assert engine.layer == 0
    engine.press(1)
    engine.tick()
    assert engine.layer == 2
    engine.release(1)
    engine.tick()
    assert engine.layer == 0
    tap(engine, clock, 2)
    assert engine.layer == 2
    tap(engine, clock, 2)
    assert engine.layer == 0


def test_midi_note_modes():
    layers = [{"keys": {
        "0": {"press": [{"type": "midi_note", "note": 60, "channel": 2}]},
        "1": {"press": [{"type": "midi_note", "note": 61, "mode": "toggle"}]},
    }}]
    engine, backend, clock = make(layers)
    engine.press(0)
    engine.tick()
    assert backend.take() == [("midi", midi.note_on(60, 127, 2))]
    engine.release(0)
    engine.tick()
    assert backend.take() == [("midi", midi.note_off(60, 0, 2))]
    tap(engine, clock, 1)
    tap(engine, clock, 1)
    assert backend.take() == [("midi", midi.note_on(61, 127, 1)), ("midi", midi.note_off(61, 0, 1))]


def test_msc_and_cc():
    layers = [{"keys": {"0": {"press": [
        {"type": "msc", "command": "fire", "macro": 3},
        {"type": "midi_cc", "cc": 1, "value": 100, "release_value": 0},
    ]}}}]
    engine, backend, clock = make(layers)
    tap(engine, clock, 0)
    assert backend.take() == [
        ("midi", midi.msc("fire", macro=3)),
        ("midi", midi.control_change(1, 100)),
        ("midi", midi.control_change(1, 0)),
    ]


def test_host_forwarded_actions():
    layers = [{"keys": {"0": {"press": [
        {"type": "osc", "address": "/x", "args": [1], "release_args": [0]},
        {"type": "ma", "command": "Go+ Executor 1", "release_command": "Off Executor 1", "console": "ma2"},
        {"type": "companion", "page": 2, "row": 1, "column": 3},
    ]}}}]
    engine, backend, clock = make(layers)
    tap(engine, clock, 0)
    msgs = [e[1] for e in backend.take()]
    assert msgs[0] == {"t": "osc", "addr": "/x", "args": [1], "target": "default"}
    assert msgs[1] == {"t": "ma", "cmd": "Go+ Executor 1", "console": "ma2"}
    assert msgs[2]["op"] == "down" and msgs[2]["page"] == 2
    # undo runs in reverse order on release
    assert msgs[3]["op"] == "up"
    assert msgs[4]["cmd"] == "Off Executor 1"
    assert msgs[5]["args"] == [0]


def test_companion_page_and_overlay_are_forwarded():
    layers = [{"keys": {"0": {"press": [
        {"type": "companion_page", "direction": "prev"},
        {"type": "overlay", "op": "cycle", "levels": [0.5, 0]},
    ]}}}]
    engine, backend, clock = make(layers)
    tap(engine, clock, 0)
    msgs = [e[1] for e in backend.take()]
    assert msgs == [{"t": "companion_page", "l": 0, "dir": 0},
                    {"t": "overlay", "op": "cycle", "levels": [0.5, 0]}]


def test_bad_action_is_reported_not_raised():
    engine, backend, clock = make([{"keys": {"0": {"press": [{"type": "nope"}]}}}])
    tap(engine, clock, 0)
    assert backend.take()[0][1]["t"] == "log"


def test_leds_and_companion_layer():
    layers = [
        {"color": "#102030", "keys": {"0": {"press": [{"type": "text", "text": "x"}]},
                                      "1": {"color": "#ff0000", "press": []}}},
        {"mode": "companion", "keys": {}},
    ]
    engine, backend, clock = make(layers, {"brightness": 1.0, "pressed_color": "#00ff00", "led_gamma": 1.0})
    assert backend.leds[0] == (0x10, 0x20, 0x30)
    assert backend.leds[1] == (255, 0, 0)
    assert backend.leds[2] == (0, 0, 0)
    engine.press(0)
    assert backend.leds[0] == (0, 255, 0)
    engine.release(0)
    engine.set_remote_color(1, 5, [1, 2, 3])
    assert backend.leds[5] == (0, 0, 0)  # not the current layer yet
    engine.set_layer(1)
    assert backend.leds[5] == (1, 2, 3)


def test_colour_preview_from_the_editor():
    layers = [
        {"color": "#0000ff", "keys": {"0": {"press": [{"type": "text", "text": "x"}]},
                                      "1": {"color": "#00ff00", "press": []}}},
        {"mode": "companion", "keys": {}},
    ]
    engine, backend, clock = make(layers, {"brightness": 1.0, "led_gamma": 1.0})
    assert backend.leds[0] == (0, 0, 255)
    # layer turned red, key 1 recoloured, key 3 newly assigned (layer colour), key 1 of layer 2 local
    engine.set_preview([{"c": "#ff0000", "k": {"0": None, "1": "#ffff00", "3": None}},
                        {"c": None, "k": {"1": "#123456"}}])
    assert backend.leds[0] == (255, 0, 0)
    assert backend.leds[1] == (255, 255, 0)
    assert backend.leds[3] == (255, 0, 0)
    assert backend.leds[2] == (0, 0, 0)
    engine.set_remote_color(1, 5, [1, 2, 3])
    engine.set_layer(1)
    assert backend.leds[1] == (0x12, 0x34, 0x56) and backend.leds[5] == (1, 2, 3)
    engine.set_layer(0)
    engine.set_preview(None)                     # back to the deployed layout
    assert backend.leds[0] == (0, 0, 255) and backend.leds[3] == (0, 0, 0)
    engine.set_preview([{"c": "#ff0000", "k": {"0": None}}])
    engine.load({"device": {"brightness": 1.0, "led_gamma": 1.0}, "layers": layers})
    assert engine.preview is None and backend.leds[0] == (0, 0, 255)     # a deploy ends the preview


def test_led_gamma_balance_and_test_pattern():
    from cuekeys_engine.engine import color_lut

    layers = [{"keys": {"0": {"color": "#ffffff", "press": [{"type": "text", "text": "x"}]},
                        "1": {"color": "#80ff40", "press": [{"type": "text", "text": "x"}]}}}]
    engine, backend, clock = make(layers, {"brightness": 1.0, "led_balance": [0.5, 1.0, 0.8]})
    assert backend.leds[0] == (128, 255, 204)            # white balanced
    r, g, b = backend.leds[1]
    assert (r, g, b) == (28, 255, 10)                     # gamma + balance: mid-tones stay saturated
    engine.set_calibration(1.0, (1, 1, 1))
    assert backend.leds[1] == (128, 255, 64)              # linear again, re-rendered live
    engine.set_test_color("#ffffff")
    assert all(backend.leds[k] == (255, 255, 255) for k in range(16))
    engine.set_test_color(None)
    assert backend.leds[2] == (0, 0, 0)
    assert color_lut(0.5)[255] == 128 and color_lut(1.0)[0] == 0


def test_action_types_match_host_schema():
    from cuekeys.config import ACTION_TYPES as HOST_TYPES

    assert set(ACTION_TYPES) == set(HOST_TYPES)

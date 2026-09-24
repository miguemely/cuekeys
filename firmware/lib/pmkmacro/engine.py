# SPDX-License-Identifier: MIT
"""Macro / layer engine.

Hardware independent: all I/O goes through a *backend* object and time comes
from a ``clock()`` callable returning integer milliseconds. That keeps it
runnable (and tested) on desktop Python as well as on CircuitPython.

Backend interface::

    key_down(names)      # list of adafruit_hid Keycode attribute names
    key_up(names)
    release_all()
    write_text(text)
    consumer(name)       # ConsumerControlCode attribute name
    midi(data)           # raw MIDI bytes
    host(message)        # dict, sent to the host app as a JSON line
    set_led(index, rgb)  # rgb tuple 0-255, brightness already applied

Key semantics
-------------
* A key without ``hold`` actions runs ``press`` immediately on press and
  ``release`` on release.
* A key *with* ``hold`` actions is tap/hold: releasing before
  ``hold_time_ms`` runs ``press`` (the tap), holding past it runs ``hold``.
* Actions that have a natural "off" (held key combos, MIDI notes, momentary
  layers, OSC/MA ``release_*`` payloads) undo themselves when the key is
  released.

All actions share one timeline, so a macro with delays never interleaves with
the next one and release/undo steps always run after the matching press steps.
"""

from . import midi as _midi

VERSION = "0.1.0"
NUM_KEYS = 16  # default; the layout's device section sets the real count

ACTION_TYPES = (
    "keys", "key_down", "key_up", "release_all", "text", "delay", "consumer",
    "layer", "midi_note", "midi_cc", "midi_pc", "msc", "osc", "ma", "companion",
    "companion_page", "overlay", "host",
)

# Layer modes. "companion" layers are Bitfocus Companion Satellite surfaces:
# unassigned keys in the top ``companion_rows`` rows are handled by Companion
# (via the host app) and their LED colours come from Companion's button state.
LAYER_MODES = ("local", "companion")

LAYER_OPS = ("goto", "next", "prev", "toggle", "momentary")

# Pseudo key that resolves to COMMAND on macOS hosts and CONTROL elsewhere, so
# one layout works on every OS.
PRIMARY = "PRIMARY"


def parse_color(value, default=(0, 0, 0)):
    """Accept "#rrggbb", "rrggbb" or [r, g, b]; return an (r, g, b) tuple."""
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        if len(text) != 6:
            return default
        try:
            return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
        except ValueError:
            return default
    try:
        r, g, b = value
        return (int(r) & 0xFF, int(g) & 0xFF, int(b) & 0xFF)
    except (TypeError, ValueError):
        return default


DEFAULT_GAMMA = 2.2


def color_lut(brightness, gamma=DEFAULT_GAMMA, gain=1.0):
    """256-entry table: linear 0-255 input -> corrected LED drive level.

    Gamma makes mid-tones look right on linear PWM LEDs; ``gain`` is the
    per-channel white balance (LED dies aren't equally bright).
    """
    lut = bytearray(256)
    factor = 255.0 * brightness * gain
    for i in range(256):
        value = int(((i / 255.0) ** gamma) * factor + 0.5)
        lut[i] = 255 if value > 255 else value
    return lut


def scale(rgb, brightness):
    """Plain brightness scaling (no gamma / balance)."""
    return (int(rgb[0] * brightness), int(rgb[1] * brightness),
            int(rgb[2] * brightness))


class Engine:
    def __init__(self, config, backend, clock):
        self.backend = backend
        self.clock = clock
        self.queue = []          # [(due_ms, callable)] in timeline order
        self.cursor = 0          # end of the scheduled timeline (ms)
        self.active = {}         # key index -> per-press state dict
        self.toggles = {}        # (channel, note) -> bool for toggle notes
        self.layer = 0
        self.prev_layer = 0
        self.host_os = None
        self.remote_colors = {}  # (layer, key) -> rgb pushed by the host
        self.load(config)

    # ------------------------------------------------------------------ config
    def load(self, config):
        device = config.get("device", {}) if config else {}
        self.num_keys = int(device.get("num_keys", NUM_KEYS))
        self.layers = (config or {}).get("layers") or [{"name": "Default", "keys": {}}]
        self.hold_time = int(device.get("hold_time_ms", 500))
        self.brightness = float(device.get("brightness", 0.5))
        self.test_color = None
        self.set_calibration(device.get("led_gamma", DEFAULT_GAMMA),
                             device.get("led_balance", (1.0, 1.0, 1.0)), render=False)
        self.pressed_color = parse_color(device.get("pressed_color"), (255, 255, 255))
        self.midi_channel = int(device.get("midi_channel", 1))
        os_hint = device.get("host_os", "auto")
        if os_hint != "auto":
            self.host_os = os_hint
        if self.layer >= len(self.layers):
            self.layer = 0
        self.render()

    def key_config(self, index, layer=None):
        layer = self.layer if layer is None else layer
        keys = self.layers[layer].get("keys") or {}
        return keys.get(str(index))

    # ------------------------------------------------------------------ events
    def press(self, index):
        cfg = self.key_config(index)
        state = {"cfg": cfg, "t0": self.clock(), "hold_fired": False, "undo": []}
        self.active[index] = state
        self.backend.host({"t": "key", "k": index, "s": 1, "l": self.layer})
        if cfg and not cfg.get("hold"):
            self.run(cfg.get("press"), state)
        self.render_key(index)

    def release(self, index):
        state = self.active.pop(index, None)
        self.backend.host({"t": "key", "k": index, "s": 0, "l": self.layer})
        if state is None:
            return
        cfg = state["cfg"]
        if cfg:
            if cfg.get("hold") and not state["hold_fired"]:
                self.run(cfg.get("press"), state)
            self._schedule(lambda: self._undo(state))
            self.run(cfg.get("release"), state)
        self.render_key(index)

    def tick(self):
        now = self.clock()
        for state in self.active.values():
            cfg = state["cfg"]
            if cfg and cfg.get("hold") and not state["hold_fired"]:
                if now - state["t0"] >= self.hold_time:
                    state["hold_fired"] = True
                    self.run(cfg.get("hold"), state)
        while self.queue and self.queue[0][0] <= now:
            _, fn = self.queue.pop(0)
            try:
                fn()
            except Exception as err:  # never let a bad action kill the loop
                self.backend.host({"t": "log", "level": "error", "msg": str(err)})

    def idle(self):
        return not self.queue

    # --------------------------------------------------------------- timeline
    def _schedule(self, fn, delay_ms=0):
        now = self.clock()
        if self.cursor < now:
            self.cursor = now
        self.cursor += delay_ms
        self.queue.append((self.cursor, fn))

    def run(self, actions, state=None):
        if not actions:
            return
        if state is None:
            state = {"undo": []}
        for action in actions:
            kind = action.get("type")
            if kind == "delay":
                self._schedule(_noop, int(action.get("ms", 0)))
            else:
                self._schedule(_bind(self.execute, action, state))

    def _undo(self, state):
        undo = state["undo"]
        while undo:
            undo.pop()()

    # ---------------------------------------------------------------- actions
    def resolve_keys(self, names):
        out = []
        for name in names or ():
            name = str(name).upper()
            if name == PRIMARY:
                name = "COMMAND" if self.host_os == "mac" else "CONTROL"
            out.append(name)
        return out

    def execute(self, action, state):
        kind = action.get("type")
        backend = self.backend
        undo = state["undo"]
        channel = int(action.get("channel", self.midi_channel))

        if kind == "keys":
            keys = self.resolve_keys(action.get("keys"))
            backend.key_down(keys)
            if action.get("mode") == "hold":
                undo.append(_bind(backend.key_up, keys))
            else:
                backend.key_up(keys)
        elif kind == "key_down":
            backend.key_down(self.resolve_keys(action.get("keys")))
        elif kind == "key_up":
            backend.key_up(self.resolve_keys(action.get("keys")))
        elif kind == "release_all":
            backend.release_all()
        elif kind == "text":
            backend.write_text(str(action.get("text", "")))
        elif kind == "consumer":
            backend.consumer(str(action.get("code", "")).upper())
        elif kind == "layer":
            self._layer_action(action, undo)
        elif kind == "midi_note":
            note = int(action.get("note", 60))
            velocity = int(action.get("velocity", 127))
            mode = action.get("mode", "momentary")
            if mode == "toggle":
                key = (channel, note)
                on = not self.toggles.get(key, False)
                self.toggles[key] = on
                if on:
                    backend.midi(_midi.note_on(note, velocity, channel))
                else:
                    backend.midi(_midi.note_off(note, 0, channel))
            else:
                backend.midi(_midi.note_on(note, velocity, channel))
                off = _midi.note_off(note, 0, channel)
                if mode == "tap":
                    backend.midi(off)
                else:
                    undo.append(_bind(backend.midi, off))
        elif kind == "midi_cc":
            cc = int(action.get("cc", 0))
            backend.midi(_midi.control_change(cc, int(action.get("value", 127)), channel))
            if action.get("release_value") is not None:
                off = _midi.control_change(cc, int(action["release_value"]), channel)
                undo.append(_bind(backend.midi, off))
        elif kind == "midi_pc":
            backend.midi(_midi.program_change(int(action.get("program", 0)), channel))
        elif kind == "msc":
            backend.midi(_midi.msc(
                action.get("command", "go"),
                cue=action.get("cue"),
                cue_list=action.get("cue_list"),
                cue_path=action.get("cue_path"),
                device_id=int(action.get("device_id", 0x7F)),
                command_format=action.get("command_format", "all"),
                macro=action.get("macro"),
                control=action.get("control"),
                value=action.get("value"),
            ))
        elif kind == "osc":
            msg = {"t": "osc", "addr": action.get("address", "/"),
                   "args": action.get("args") or [],
                   "target": action.get("target", "default")}
            backend.host(msg)
            if action.get("release_args") is not None:
                off = dict(msg)
                off["args"] = action["release_args"]
                undo.append(_bind(backend.host, off))
        elif kind == "ma":
            msg = {"t": "ma", "cmd": action.get("command", ""),
                   "console": action.get("console", "ma3")}
            backend.host(msg)
            if action.get("release_command"):
                off = dict(msg)
                off["cmd"] = action["release_command"]
                undo.append(_bind(backend.host, off))
        elif kind == "companion":
            msg = {"t": "companion", "page": action.get("page", 1),
                   "row": int(action.get("row", 0)),
                   "column": int(action.get("column", 0)),
                   "target": action.get("target", "default")}
            if action.get("mode", "hold") == "hold":
                msg["op"] = "down"
                backend.host(msg)
                up = dict(msg)
                up["op"] = "up"
                undo.append(_bind(backend.host, up))
            else:
                msg["op"] = "press"
                backend.host(msg)
        elif kind == "companion_page":
            backend.host({"t": "companion_page", "l": self.layer,
                          "dir": 0 if action.get("direction") == "prev" else 1})
        elif kind == "overlay":
            backend.host({"t": "overlay", "op": action.get("op", "cycle"),
                          "levels": action.get("levels")})
        elif kind == "host":
            backend.host({"t": "host", "event": action.get("event", ""),
                          "data": action.get("data")})
        else:
            raise ValueError("unknown action type: %s" % kind)

    def _layer_action(self, action, undo):
        op = action.get("op", "goto")
        count = len(self.layers)
        target = int(action.get("layer", 0))
        if op == "next":
            self.set_layer((self.layer + 1) % count)
        elif op == "prev":
            self.set_layer((self.layer - 1) % count)
        elif op == "toggle":
            if self.layer == target:
                self.set_layer(self.prev_layer)
            else:
                self.set_layer(target)
        elif op == "momentary":
            previous = self.layer
            self.set_layer(target)
            undo.append(_bind(self.set_layer, previous))
        else:
            self.set_layer(target)

    # ----------------------------------------------------------------- layers
    def set_layer(self, index):
        index = int(index)
        if index < 0 or index >= len(self.layers):
            return
        if index != self.layer:
            self.prev_layer = self.layer
            self.layer = index
        self.announce_layer()
        self.render()

    def announce_layer(self):
        self.backend.host({"t": "layer", "i": self.layer,
                           "name": self.layers[self.layer].get("name", ""),
                           "count": len(self.layers)})

    def layer_mode(self, layer=None):
        layer = self.layer if layer is None else layer
        return self.layers[layer].get("mode", "local")

    def set_remote_color(self, layer, index, rgb):
        self.remote_colors[(int(layer), int(index))] = parse_color(rgb)
        if int(layer) == self.layer:
            self.render_key(int(index))

    # ------------------------------------------------------------------- LEDs
    def key_color(self, index):
        if index in self.active:
            return self.pressed_color
        cfg = self.key_config(index)
        if not cfg:
            if self.layer_mode() == "companion":
                return self.remote_colors.get((self.layer, index), (0, 0, 0))
            return (0, 0, 0)
        layer_color = parse_color(self.layers[self.layer].get("color"), (40, 40, 40))
        return parse_color(cfg.get("color"), layer_color)

    def set_calibration(self, gamma=DEFAULT_GAMMA, balance=(1.0, 1.0, 1.0), render=True):
        """LED colour correction; the host's calibration dialog calls this live."""
        self.gamma = float(gamma)
        self.balance = tuple(float(b) for b in balance)
        self.luts = [color_lut(self.brightness, self.gamma, gain) for gain in self.balance]
        if render:
            self.render()

    def set_test_color(self, rgb=None):
        """Show one colour on every key (calibration), or None to go back."""
        self.test_color = parse_color(rgb) if rgb is not None else None
        self.render()

    def corrected(self, rgb):
        luts = self.luts
        return (luts[0][rgb[0]], luts[1][rgb[1]], luts[2][rgb[2]])

    def render_key(self, index):
        color = self.test_color if self.test_color is not None else self.key_color(index)
        self.backend.set_led(index, self.corrected(color))

    def render(self):
        for index in range(self.num_keys):
            self.render_key(index)


def _noop():
    pass


def _bind(fn, *args):
    # functools.partial is not available on every CircuitPython build.
    return lambda: fn(*args)

# SPDX-License-Identifier: MIT
"""PMK Macro Manager firmware.

Reads ``/config.json`` (written by the host app) and turns the keypad into a
USB keyboard + USB MIDI device with layers and macros. OSC, grandMA and
Companion actions are forwarded to the host app over the ``usb_cdc.data``
serial port as JSON lines.

Requires in /lib: pmk, adafruit_hid, and adafruit_is31fl3731 (Keybow 2040) or
adafruit_dotstar (Pico RGB Keypad Base).
"""

import json
import time

import supervisor
import usb_cdc
import usb_hid
import usb_midi
from adafruit_hid.consumer_control import ConsumerControl
from adafruit_hid.consumer_control_code import ConsumerControlCode
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode
from pmk import PMK
from pmkmacro.engine import VERSION, Engine

CONFIG_PATH = "/config.json"


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f), None
    except (OSError, ValueError) as err:
        return {"layers": [{"name": "No config", "keys": {}}]}, str(err)


def make_hardware(name):
    if name == "rgbkeypad":
        from pmk.platform.rgbkeypadbase import RGBKeypadBase as Hardware
    else:
        from pmk.platform.keybow2040 import Keybow2040 as Hardware
    return Hardware()


def make_layout(name, keyboard):
    # Non-US layouts come from the community bundle (keyboard_layout_win_*).
    if name and name != "us":
        try:
            module = __import__("keyboard_layout_" + name)
            return module.KeyboardLayout(keyboard)
        except ImportError:
            print("layout %s not installed, using US" % name)
    from adafruit_hid.keyboard_layout_us import KeyboardLayoutUS
    return KeyboardLayoutUS(keyboard)


class HostLink:
    """Newline-delimited JSON over the secondary USB serial port."""

    def __init__(self):
        self.port = usb_cdc.data
        self.buffer = b""

    def send(self, message):
        if self.port is None or not self.port.connected:
            return
        try:
            self.port.write(json.dumps(message).encode() + b"\n")
        except OSError:
            pass

    def poll(self):
        if self.port is None or not self.port.in_waiting:
            return []
        self.buffer += self.port.read(self.port.in_waiting)
        lines = self.buffer.split(b"\n")
        self.buffer = lines.pop()
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out


class Backend:
    def __init__(self, keypad, keyboard, layout, consumer, midi_out, link):
        self.keypad = keypad
        self.keyboard = keyboard
        self.layout = layout
        self.consumer_control = consumer
        self.midi_out = midi_out
        self.link = link

    def _codes(self, names):
        return [getattr(Keycode, n) for n in names]

    def key_down(self, names):
        self.keyboard.press(*self._codes(names))

    def key_up(self, names):
        self.keyboard.release(*self._codes(names))

    def release_all(self):
        self.keyboard.release_all()

    def write_text(self, text):
        self.layout.write(text)

    def consumer(self, name):
        self.consumer_control.send(getattr(ConsumerControlCode, name))

    def midi(self, data):
        if self.midi_out is not None:
            self.midi_out.write(data)

    def host(self, message):
        self.link.send(message)

    def set_led(self, index, rgb):
        self.keypad.keys[index].set_led(*rgb)


def main():
    config, error = load_config()
    device = config.get("device", {})
    keypad = PMK(make_hardware(device.get("hardware", "keybow2040")))
    keyboard = Keyboard(usb_hid.devices)
    midi_out = usb_midi.ports[1] if len(usb_midi.ports) > 1 else None
    link = HostLink()
    backend = Backend(keypad, keyboard, make_layout(device.get("keyboard_layout"), keyboard),
                      ConsumerControl(usb_hid.devices), midi_out, link)
    engine = Engine(config, backend, lambda: time.monotonic_ns() // 1000000)

    if error:
        print("config error:", error)
        for key in keypad.keys:
            key.set_led(64, 0, 0)

    def hello():
        link.send({"t": "hello", "fw": VERSION,
                   "hw": device.get("hardware", "keybow2040"),
                   "config_error": error})
        engine.announce_layer()

    debounce_ms = int(device.get("debounce_ms", 15))
    was_connected = False
    previous = [False] * len(keypad.keys)
    changed_at = [0] * len(keypad.keys)

    while True:
        keypad.update()
        now = time.monotonic_ns() // 1000000
        for key in keypad.keys:
            pressed = key.pressed
            if pressed != previous[key.number] and now - changed_at[key.number] >= debounce_ms:
                previous[key.number] = pressed
                changed_at[key.number] = now
                if pressed:
                    engine.press(key.number)
                else:
                    engine.release(key.number)
        engine.tick()

        connected = link.port is not None and link.port.connected
        if connected and not was_connected:
            hello()
        was_connected = connected

        for msg in link.poll():
            kind = msg.get("t")
            if kind == "hello?":
                hello()
            elif kind == "layer":
                engine.set_layer(msg.get("i", 0))
            elif kind == "os":
                engine.host_os = msg.get("os")
            elif kind == "led":
                engine.set_remote_color(msg.get("l", engine.layer), msg.get("k", 0),
                                        msg.get("rgb"))
            elif kind == "press":
                engine.press(int(msg.get("k", 0)))
            elif kind == "release":
                engine.release(int(msg.get("k", 0)))
            elif kind == "reload":
                supervisor.reload()


main()

# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""CueKeys firmware.

Reads ``/config.json`` (written by the host app) and turns the keypad into a
USB keyboard + USB MIDI device with layers and macros. OSC, grandMA and
Companion actions are forwarded to the host app over the ``usb_cdc.data``
serial port as JSON lines.

The keypad hardware is handled by a driver in /lib/cuekeys_drivers, chosen by the
layout's ``device.driver`` (see cuekeys_drivers/__init__.py for the interface).
Requires /lib/adafruit_hid plus whatever the driver needs (e.g. pmk).
"""

import json
import time

import microcontroller
import supervisor
import usb_cdc
import usb_hid
import usb_midi
from adafruit_hid.consumer_control import ConsumerControl
from adafruit_hid.consumer_control_code import ConsumerControlCode
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode
from cuekeys_engine.engine import VERSION, Engine

CONFIG_PATH = "/config.json"
# Unique per chip; CircuitPython also uses it as the USB serial number, so the
# host can match this keypad's serial ports and CIRCUITPY drive to it.
KEYPAD_UID = "".join("%02X" % b for b in microcontroller.cpu.uid)


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f), None
    except (OSError, ValueError) as err:
        return {"layers": [{"name": "No config", "keys": {}}]}, str(err)


# Layouts written before device profiles existed only name the hardware.
LEGACY_DRIVERS = {"keybow2040": "pmk_keybow2040", "rgbkeypad": "pmk_rgbkeypad"}


def make_hardware(device):
    name = device.get("driver") or LEGACY_DRIVERS.get(device.get("hardware"), "pmk_keybow2040")
    package = __import__("cuekeys_drivers." + name)
    module = getattr(package, name)
    config = dict(device.get("driver_config") or {})
    config.setdefault("debounce_ms", device.get("debounce_ms", 15))
    return module.Hardware(config)


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
    def __init__(self, hardware, keyboard, layout, consumer, midi_out, link):
        self.hardware = hardware
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
        if index < self.hardware.num_keys:
            self.hardware.set_led(index, rgb)


def main():
    config, error = load_config()
    device = config.get("device", {})
    hardware = make_hardware(device)
    if not device.get("num_keys"):
        device["num_keys"] = hardware.num_keys
    keyboard = Keyboard(usb_hid.devices)
    midi_out = usb_midi.ports[1] if len(usb_midi.ports) > 1 else None
    link = HostLink()
    backend = Backend(hardware, keyboard, make_layout(device.get("keyboard_layout"), keyboard),
                      ConsumerControl(usb_hid.devices), midi_out, link)
    engine = Engine(config, backend, lambda: time.monotonic_ns() // 1000000)

    if error:
        print("config error:", error)
        for key in range(hardware.num_keys):
            hardware.set_led(key, (64, 0, 0))

    def hello():
        link.send({"t": "hello", "fw": VERSION, "uid": KEYPAD_UID,
                   "profile": device.get("profile") or device.get("hardware", "keybow2040"),
                   "num_keys": hardware.num_keys,
                   "config_error": error})
        engine.announce_layer()

    was_connected = False

    while True:
        now = time.monotonic_ns() // 1000000
        for key, pressed in hardware.poll(now):
            if pressed:
                engine.press(key)
            else:
                engine.release(key)
        engine.tick()
        hardware.show()

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
            elif kind == "led_cal":
                engine.set_calibration(msg.get("gamma", engine.gamma),
                                       msg.get("balance", engine.balance))
            elif kind == "led_test":
                engine.set_test_color(msg.get("rgb"))
            elif kind == "reload":
                supervisor.reload()


main()

"""Host-side runtime: keypad link + OSC / grandMA / Companion bridge.

The keypad does HID and MIDI itself. Everything that needs a network (OSC,
grandMA2 Telnet, grandMA3 OSC, Companion) is forwarded here over the serial
link and sent on by this class. It also tracks the live state (current layer,
pressed keys, Companion button states) for the overlay.

Listeners are called as ``listener(event, data)`` from background threads:

* ``status``    {"connected", "port", "firmware"}
* ``layer``     {"index", "name", "count"}
* ``key``       {"key", "pressed", "layer"}
* ``companion`` {"layer", "key", "state"} / {"connected", "target"}
* ``overlay``   {"op", "levels"}  (from an overlay action on the keypad)
* ``log``       {"level", "message"}
"""

import logging
import queue
import re
import socket
import threading

from . import companion as comp
from . import grandma
from .config import companion_rows, in_companion_region, key_is_assigned
from .devices import profile_for
from .link import DeviceLink
from .osc import OscSender

log = logging.getLogger(__name__)


def companion_device_id(layer, index):
    if layer.get("companion_id"):
        return str(layer["companion_id"])
    host = re.sub(r"[^A-Za-z0-9]+", "-", socket.gethostname()).strip("-").lower() or "host"
    return "pmk-%s-l%d" % (host, index)


class Runtime:
    def __init__(self, config, port=None, link=None, satellite_factory=None):
        self.config = config
        self.satellite_factory = satellite_factory or comp.SatelliteClient
        self.listeners = []
        self.connected = False
        self.port = None
        self.firmware = None
        self.layer = 0
        self.pressed = {}                 # key -> layer it was pressed on
        self.companion_states = {}        # (layer, key) -> state dict
        self.companion_connected = {}     # target -> bool
        self.companion_pages = {}         # layer -> Companion page shown on its surface
        self.companion_page_names = {}    # (target, page) -> page name from Companion
        self.satellites = {}              # target -> SatelliteClient
        self._device_layers = {}          # satellite device id -> layer index
        self.osc = OscSender()
        self._ma2 = None
        self._jobs = queue.Queue()
        self._worker = threading.Thread(target=self._work, name="pmk-bridge", daemon=True)
        self.link = link or DeviceLink(port, self._on_message, self._on_status)

    # ------------------------------------------------------------ lifecycle
    def start(self):
        self._worker.start()
        self.link.start()
        self._sync_satellites()

    def stop(self):
        self.link.stop()
        for sat in self.satellites.values():
            sat.stop()
        self.satellites.clear()
        self._jobs.put(None)
        if self._ma2 is not None:
            self._ma2.close()
        self.osc.close()

    def set_config(self, config):
        self.config = config
        self._ma2 = None
        if self.layer >= len(config["layers"]):
            self.layer = 0
        self._sync_satellites()

    def add_listener(self, fn):
        self.listeners.append(fn)

    def emit(self, event, **data):
        for fn in list(self.listeners):
            try:
                fn(event, data)
            except Exception:  # noqa: BLE001
                log.exception("listener failed")

    # ------------------------------------------------------------ commands
    def select_layer(self, index):
        if not self.link.send({"t": "layer", "i": int(index)}):
            # No keypad: still let the overlay/editor preview layers.
            self._set_layer(int(index))

    def press_key(self, key):
        if not self.link.send({"t": "press", "k": int(key)}):
            self._handle_key(int(key), True, self.layer)

    def release_key(self, key):
        if not self.link.send({"t": "release", "k": int(key)}):
            self._handle_key(int(key), False, self.pressed.get(int(key), self.layer))

    def layer_info(self, index=None):
        index = self.layer if index is None else index
        layers = self.config["layers"]
        index = min(max(index, 0), len(layers) - 1)
        return index, layers[index]

    # ------------------------------------------------------------ keypad events
    def _on_status(self, connected, port):
        self.connected, self.port = connected, port
        if not connected:
            self.firmware = None
            self.pressed.clear()
        self.emit("status", connected=connected, port=port, firmware=self.firmware)

    def _on_message(self, msg):
        kind = msg.get("t")
        if kind == "hello":
            self.firmware = msg.get("fw")
            if msg.get("config_error"):
                self.emit("log", level="error", message="keypad config error: %s" % msg["config_error"])
            self.emit("status", connected=True, port=self.port, firmware=self.firmware)
            self._push_companion_leds()
        elif kind == "layer":
            self._set_layer(int(msg.get("i", 0)))
        elif kind == "key":
            self._handle_key(int(msg.get("k", 0)), bool(msg.get("s")), int(msg.get("l", self.layer)))
        elif kind == "osc":
            self._send_osc(msg.get("target", "default"), msg.get("addr", "/"), msg.get("args") or [])
        elif kind == "ma":
            self._send_ma(msg.get("console", "ma3"), msg.get("cmd", ""))
        elif kind == "companion":
            self._jobs.put(("companion", msg))
        elif kind == "companion_page":
            self.change_companion_page(int(msg.get("l", self.layer)), bool(msg.get("dir", 1)))
        elif kind == "overlay":
            self.emit("overlay", op=msg.get("op", "cycle"), levels=msg.get("levels"))
        elif kind == "host":
            self.emit("host", event=msg.get("event"), data=msg.get("data"))
        elif kind == "log":
            self.emit("log", level=msg.get("level", "info"), message=msg.get("msg", ""))

    def _set_layer(self, index):
        layers = self.config["layers"]
        if not 0 <= index < len(layers):
            return
        self.layer = index
        self.emit("layer", index=index, name=layers[index].get("name", ""), count=len(layers))

    def _handle_key(self, key, pressed, layer_index):
        if pressed:
            self.pressed[key] = layer_index
        else:
            layer_index = self.pressed.pop(key, layer_index)
        self.emit("key", key=key, pressed=pressed, layer=layer_index)
        layers = self.config["layers"]
        if not 0 <= layer_index < len(layers):
            return
        layer = layers[layer_index]
        profile = self._profile()
        if in_companion_region(layer, key, profile, self._rotation()) and not key_is_assigned(
                (layer.get("keys") or {}).get(str(key))):
            sat = self.satellites.get(layer.get("companion_target", "default"))
            if sat is not None:
                sat.key_press(companion_device_id(layer, layer_index),
                              profile.satellite_index(key, self._rotation()), pressed)

    def change_companion_page(self, layer_index, forward=True):
        layers = self.config["layers"]
        if not 0 <= layer_index < len(layers) or layers[layer_index].get("mode") != "companion":
            self.emit("log", level="error", message="Companion page keys only work on a Companion layer")
            return
        layer = layers[layer_index]
        sat = self.satellites.get(layer.get("companion_target", "default"))
        if sat is None or not sat.connected:
            self.emit("log", level="error", message="Companion is not connected")
        elif not sat.change_page(companion_device_id(layer, layer_index), forward):
            self.emit("log", level="error",
                      message="Page change needs Companion 4.3 or newer (Satellite API 1.10)")

    # ------------------------------------------------------------ outputs
    def _profile(self):
        return profile_for(self.config)

    def _rotation(self):
        return int(self.config.get("overlay", {}).get("rotation", 0))

    def _bridge(self, name):
        return self.config.get("bridge", {}).get(name) or {}

    def _send_osc(self, target, address, args):
        targets = self._bridge("osc_targets")
        dest = targets.get(target)
        if dest is None:
            self.emit("log", level="error", message="unknown OSC target %r" % target)
            return
        try:
            self.osc.send(dest["host"], dest["port"], address, args)
        except (OSError, ValueError, TypeError) as err:
            self.emit("log", level="error", message="OSC send failed: %s" % err)

    def _send_ma(self, console, command):
        if console == "ma2":
            self._jobs.put(("ma2", command))
            return
        ma3 = self._bridge("ma3")
        try:
            self.osc.send(ma3.get("host", "127.0.0.1"), ma3.get("port", 8000),
                          grandma.ma3_address(ma3.get("prefix", "gma3")), [command])
        except OSError as err:
            self.emit("log", level="error", message="MA3 OSC failed: %s" % err)

    def _work(self):
        while True:
            job = self._jobs.get()
            if job is None:
                return
            kind, payload = job
            try:
                if kind == "ma2":
                    if self._ma2 is None:
                        ma2 = self._bridge("ma2")
                        self._ma2 = grandma.MA2Telnet(ma2.get("host", "127.0.0.1"),
                                                      ma2.get("port", 30000),
                                                      ma2.get("user", "administrator"),
                                                      ma2.get("password", ""))
                    self._ma2.send(payload)
                elif kind == "page_name":
                    self._fetch_page_name(*payload)
                elif kind == "companion":
                    target = self._bridge("companion").get(payload.get("target", "default"))
                    if target is None:
                        raise ValueError("unknown Companion target %r" % payload.get("target"))
                    comp.http_button(target.get("host", "127.0.0.1"), target.get("http_port", 8000),
                                     payload.get("page", 1), payload.get("row", 0),
                                     payload.get("column", 0), payload.get("op", "press"))
            except Exception as err:  # noqa: BLE001
                self.emit("log", level="error", message="%s failed: %s" % (kind, err))

    # ------------------------------------------------------------ companion
    def _sync_satellites(self):
        """Start/stop Satellite connections to match the companion layers."""
        wanted = {}
        self._device_layers = {}
        profile, rotation = self._profile(), self._rotation()
        width = profile.display_size(rotation)[1]
        for index, layer in enumerate(self.config["layers"]):
            if layer.get("mode") != "companion":
                continue
            target = layer.get("companion_target", "default")
            device_id = companion_device_id(layer, index)
            self._device_layers[device_id] = index
            name = "PMK %s" % (layer.get("name") or "layer %d" % index)
            rows = companion_rows(layer, profile, rotation)
            wanted.setdefault(target, {})[device_id] = (name, rows * width, width)
        targets = self._bridge("companion")
        for target in list(self.satellites):
            sat = self.satellites[target]
            conf = targets.get(target) or {}
            if target not in wanted or (sat.host, sat.port) != (
                    conf.get("host", "127.0.0.1"), int(conf.get("satellite_port", 16622))):
                sat.stop()
                del self.satellites[target]
        for target, devices in wanted.items():
            conf = targets.get(target)
            if conf is None:
                self.emit("log", level="error", message="unknown Companion target %r" % target)
                continue
            sat = self.satellites.get(target)
            if sat is None:
                sat = self.satellite_factory(
                    conf.get("host", "127.0.0.1"), conf.get("satellite_port", 16622),
                    on_key_state=self._on_companion_state,
                    on_status=lambda c, t=target: self._on_companion_status(t, c))
                self.satellites[target] = sat
                for device_id, spec in devices.items():
                    sat.add_device(device_id, *spec)
                sat.start()
            else:
                for device_id in list(sat.devices):
                    if device_id not in devices:
                        sat.remove_device(device_id)
                for device_id, spec in devices.items():
                    if sat.devices.get(device_id) != spec:
                        sat.add_device(device_id, *spec)
                        self._forget_companion_states(self._device_layers[device_id])

    def companion_status(self, target="default"):
        """"offline", "online" (all surfaces registered) or "busy" (rejected)."""
        sat = self.satellites.get(target)
        if sat is None or not sat.connected:
            return "offline"
        if any(ok is False for ok in sat.registered.values()):
            return "busy"
        return "online"

    def _on_companion_status(self, target, connected):
        self.companion_connected[target] = connected
        self.emit("companion", target=target, connected=connected)

    def _layer_target(self, layer):
        return self.config["layers"][layer].get("companion_target", "default")

    def companion_page_label(self, layer):
        """"PMK 1" (page name), "p.4" (number only) or None if unknown."""
        page = self.companion_pages.get(layer)
        if page is None:
            return None
        return self.companion_page_names.get((self._layer_target(layer), page)) or "p.%d" % page

    def _fetch_page_name(self, layer, target, page):
        conf = self._bridge("companion").get(target) or {}
        name = comp.page_name(conf.get("host", "127.0.0.1"), conf.get("http_port", 8000), page)
        self.companion_page_names[(target, page)] = name
        if self.companion_pages.get(layer) != page:
            return
        for (state_layer, key), state in list(self.companion_states.items()):
            if state_layer == layer and state.get("page") == page:
                self.companion_states[(layer, key)] = dict(state, page_name=name)
        self.emit("companion", layer=layer, key=None, state=None)

    def _forget_companion_states(self, layer):
        for key in [k for k in self.companion_states if k[0] == layer]:
            del self.companion_states[key]
            self.link.send({"t": "led", "l": layer, "k": key[1], "rgb": [0, 0, 0]})
        self.companion_pages.pop(layer, None)

    def _on_companion_state(self, device_id, index, state):
        layer = self._device_layers.get(device_id)
        if layer is None or index < 0:
            return
        key = self._profile().key_from_satellite(index, self._rotation())
        if key is None:
            return
        page = state.get("page")
        if page is not None:
            target = self._layer_target(layer)
            if self.companion_pages.get(layer) != page:
                self.companion_pages[layer] = page
                # Page names aren't part of the Satellite protocol; ask the HTTP API.
                self._jobs.put(("page_name", (layer, target, page)))
            name = self.companion_page_names.get((target, page))
            if name:
                state = dict(state, page_name=name)
        self.companion_states[(layer, key)] = state
        self.link.send({"t": "led", "l": layer, "k": key, "rgb": list(state.get("color") or (0, 0, 0))})
        self.emit("companion", layer=layer, key=key, state=state)

    def _push_companion_leds(self):
        for (layer, key), state in list(self.companion_states.items()):
            self.link.send({"t": "led", "l": layer, "k": key,
                            "rgb": list(state.get("color") or (0, 0, 0))})

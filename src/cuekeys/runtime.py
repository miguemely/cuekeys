# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Host-side runtime: keypads + OSC / grandMA / Companion bridges.

The keypads do HID and MIDI themselves. Everything that needs a network (OSC,
grandMA2 Telnet, grandMA3 OSC, Companion) is forwarded here over each keypad's
serial link and sent on.

* :class:`Hub` finds keypads (hot-plug), keeps one :class:`KeypadSession` per
  keypad, and owns the shared bridges: one OSC socket, one worker thread for
  blocking I/O, one Companion Satellite connection per Companion server that
  carries every keypad's surfaces.
* :class:`KeypadSession` is one keypad: its serial link, its layout, live state
  (layer, pressed keys, Companion button states) and its message handling.

Keypads are identified by their hardware id (the RP2040's unique id, also its
USB serial number). Companion surface ids are ``ck-<keypad>-<layer>``, so the
same layout on two keypads gives two surfaces, and a keypad keeps its surface
(and its Companion page settings) on any computer.

Listeners get ``listener(event, data)`` from background threads; every event's
``data`` includes ``keypad`` (the session's uid):

* ``status``    {"connected", "port", "firmware"}
* ``layer``     {"index", "name", "count"}
* ``key``       {"key", "pressed", "layer"}
* ``companion`` {"layer", "key", "state"} / {"connected", "target"}
* ``overlay``   {"op", "levels"}  (from an overlay action on the keypad)
* ``host``      {"event", "data"}
* ``log``       {"level", "message"}
* ``keypads``   {"added" | "removed": uid} (hub: sessions changed)
"""

import logging
import queue
import re
import socket
import threading

from . import companion as comp
from . import device, grandma
from .config import companion_rows, in_companion_region, key_is_assigned
from .devices import profile_for
from .keypads import VIRTUAL_UID, short_id
from .link import DeviceLink
from .osc import OscSender

log = logging.getLogger(__name__)

DISCOVERY_INTERVAL = 2.0


def host_slug():
    return re.sub(r"[^A-Za-z0-9]+", "-", socket.gethostname()).strip("-").lower() or "host"


def layer_key(layer, index):
    """Stable per-layer part of a Companion surface id."""
    key = str(layer.get("companion_id") or "l%d" % index)
    return re.sub(r"^(ck|cuekeys|pmk)-", "", key)   # ids from before keypad identity


def companion_device_id(uid, layer, index):
    keypad = host_slug() if uid == VIRTUAL_UID else short_id(uid)
    return "ck-%s-%s" % (keypad, layer_key(layer, index))


def _endpoint(config, target):
    conf = (config.get("bridge", {}).get("companion") or {}).get(target)
    if conf is None:
        return None
    return (conf.get("host", "127.0.0.1"), int(conf.get("satellite_port", 16622)))


# =============================================================================
class KeypadSession:
    """One keypad (or the virtual stand-in): link, layout and live state."""

    def __init__(self, hub, uid, config, link=None, port=None):
        self.hub = hub
        self.uid = uid
        self.config = config
        self.layout_path = None           # file the layout came from (None: unsaved/default)
        self.connected = False
        self.port = port
        self.firmware = None
        self.reported_uid = None
        self.layer = 0
        self.pressed = {}                 # key -> layer it was pressed on
        self.companion_states = {}        # (layer, key) -> state dict
        self.companion_pages = {}         # layer -> Companion page shown on its surface
        if link is not None:
            self.link = link
        elif uid == VIRTUAL_UID:
            self.link = _NoLink()
        else:
            self.link = DeviceLink(port, self._on_message, self._on_status)

    # -- identity ------------------------------------------------------------
    @property
    def name(self):
        return self.hub.store.name(self.uid) if self.hub.store else "Keypad %s" % short_id(self.uid)

    @property
    def settings(self):
        return self.hub.store.get(self.uid) if self.hub.store else {}

    # -- convenience for single-keypad use (CLI --port, tests) ---------------
    def start(self):
        self.hub.start()

    def stop(self):
        self.hub.stop()

    def add_listener(self, fn):
        self.hub.add_listener(fn)

    def emit(self, event, **data):
        self.hub.emit(event, keypad=self.uid, **data)

    @property
    def listeners(self):
        return self.hub.listeners

    # -- config ----------------------------------------------------------------
    def set_config(self, config):
        self.config = config
        if self.layer >= len(config["layers"]):
            self.layer = 0
        self.hub.sync_satellites()

    # -- commands --------------------------------------------------------------
    def select_layer(self, index):
        if not self.link.send({"t": "layer", "i": int(index)}):
            self._set_layer(int(index))          # no keypad: preview locally

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

    # -- keypad events -----------------------------------------------------------
    def _on_status(self, connected, port):
        self.connected, self.port = connected, port or self.port
        if not connected:
            self.firmware = None
            self.pressed.clear()
        else:
            self.hub.keypad_seen(self.uid)
        self.emit("status", connected=connected, port=port, firmware=self.firmware)

    def _on_message(self, msg):
        kind = msg.get("t")
        if kind == "hello":
            self.firmware = msg.get("fw")
            self.reported_uid = msg.get("uid")
            if self.reported_uid and self.uid != VIRTUAL_UID and self.reported_uid.upper() != self.uid:
                log.warning("keypad on %s reports id %s, expected %s", self.port, self.reported_uid, self.uid)
            if msg.get("config_error"):
                self.emit("log", level="error", message="keypad config error: %s" % msg["config_error"])
            self.emit("status", connected=True, port=self.port, firmware=self.firmware)
            self._push_companion_leds()
        elif kind == "layer":
            self._set_layer(int(msg.get("i", 0)))
        elif kind == "key":
            self._handle_key(int(msg.get("k", 0)), bool(msg.get("s")), int(msg.get("l", self.layer)))
        elif kind == "osc":
            self.hub.send_osc(self, msg.get("target", "default"), msg.get("addr", "/"), msg.get("args") or [])
        elif kind == "ma":
            self.hub.send_ma(self, msg.get("console", "ma3"), msg.get("cmd", ""))
        elif kind == "companion":
            self.hub.jobs.put(("companion", (self, msg)))
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
            sat = self.satellite_for(layer)
            if sat is not None:
                sat.key_press(self.device_id(layer_index), profile.satellite_index(key, self._rotation()), pressed)

    def change_companion_page(self, layer_index, forward=True):
        layers = self.config["layers"]
        if not 0 <= layer_index < len(layers) or layers[layer_index].get("mode") != "companion":
            self.emit("log", level="error", message="Companion page keys only work on a Companion layer")
            return
        sat = self.satellite_for(layers[layer_index])
        if sat is None or not sat.connected:
            self.emit("log", level="error", message="Companion is not connected")
        elif not sat.change_page(self.device_id(layer_index), forward):
            self.emit("log", level="error", message="Page change needs Companion 4.3 or newer (Satellite API 1.10)")

    # -- helpers ---------------------------------------------------------------
    def _profile(self):
        return profile_for(self.config)

    def _rotation(self):
        return int(self.config.get("overlay", {}).get("rotation", 0))

    def bridge(self, name):
        return self.config.get("bridge", {}).get(name) or {}

    def device_id(self, layer_index):
        return companion_device_id(self.uid, self.config["layers"][layer_index], layer_index)

    def satellite_for(self, layer):
        endpoint = _endpoint(self.config, layer.get("companion_target", "default"))
        return self.hub.satellites.get(endpoint) if endpoint else None

    # -- companion ---------------------------------------------------------------
    def companion_layers(self):
        return [(i, layer) for i, layer in enumerate(self.config["layers"]) if layer.get("mode") == "companion"]

    @property
    def satellites(self):
        """Companion target name -> client, for the targets this keypad's layers use."""
        out = {}
        for _index, layer in self.companion_layers():
            target = layer.get("companion_target", "default")
            endpoint = _endpoint(self.config, target)
            if endpoint in self.hub.satellites:
                out[target] = self.hub.satellites[endpoint]
        return out

    def companion_status(self, target="default"):
        """"offline", "online" (this keypad's surfaces registered) or "busy" (rejected)."""
        endpoint = _endpoint(self.config, target)
        sat = self.hub.satellites.get(endpoint) if endpoint else None
        if sat is None or not sat.connected:
            return "offline"
        mine = {self.device_id(i) for i, _layer in self.companion_layers()}
        if any(ok is False for dev, ok in sat.registered.items() if dev in mine):
            return "busy"
        return "online"

    def _layer_target(self, layer):
        return self.config["layers"][layer].get("companion_target", "default")

    def companion_page_label(self, layer):
        """"CueKeys 1" (page name), "p.4" (number only) or None if unknown."""
        page = self.companion_pages.get(layer)
        if page is None:
            return None
        endpoint = _endpoint(self.config, self._layer_target(layer))
        return self.hub.page_names.get((endpoint, page)) or "p.%d" % page

    def forget_companion_states(self, layer):
        for key in [k for k in self.companion_states if k[0] == layer]:
            del self.companion_states[key]
            self.link.send({"t": "led", "l": layer, "k": key[1], "rgb": [0, 0, 0]})
        self.companion_pages.pop(layer, None)

    def on_companion_state(self, layer, index, state):
        key = self._profile().key_from_satellite(index, self._rotation())
        if key is None:
            return
        page = state.get("page")
        if page is not None:
            endpoint = _endpoint(self.config, self._layer_target(layer))
            if self.companion_pages.get(layer) != page:
                self.companion_pages[layer] = page
                # Page names aren't part of the Satellite protocol; ask the HTTP API.
                self.hub.jobs.put(("page_name", (self, layer, page)))
            name = self.hub.page_names.get((endpoint, page))
            if name:
                state = dict(state, page_name=name)
        self.companion_states[(layer, key)] = state
        self.link.send({"t": "led", "l": layer, "k": key, "rgb": list(state.get("color") or (0, 0, 0))})
        self.emit("companion", layer=layer, key=key, state=state)

    def page_name_arrived(self, layer, page, name):
        if self.companion_pages.get(layer) != page:
            return
        for (state_layer, key), state in list(self.companion_states.items()):
            if state_layer == layer and state.get("page") == page:
                self.companion_states[(layer, key)] = dict(state, page_name=name)
        self.emit("companion", layer=layer, key=None, state=None)

    def _push_companion_leds(self):
        for (layer, key), state in list(self.companion_states.items()):
            self.link.send({"t": "led", "l": layer, "k": key, "rgb": list(state.get("color") or (0, 0, 0))})


class _NoLink:
    """Link of the virtual keypad: never connected, so commands preview locally."""

    connected = False

    def start(self):
        pass

    def stop(self):
        pass

    def send(self, message):
        return False


# =============================================================================
class Hub:
    """All keypads plus the shared network bridges."""

    def __init__(self, default_config=None, store=None, satellite_factory=None, discover=True,
                 layout_loader=None, link_factory=None):
        self.default_config = default_config
        self.default_path = None                    # file default_config came from, if any
        self.store = store
        self.satellite_factory = satellite_factory or comp.SatelliteClient
        self.discover = discover
        self.layout_loader = layout_loader          # path -> config (shared per path)
        self.link_factory = link_factory            # (session, port) -> link; tests
        self.sessions = {}                          # uid -> KeypadSession (insertion order)
        self.listeners = []
        self.satellites = {}                        # (host, port) -> SatelliteClient
        self.page_names = {}                        # ((host, port), page) -> name
        self.companion_connected = {}               # (host, port) -> bool
        self._devices = {}                          # satellite device id -> (session, layer)
        self._layouts = {}                          # layout path -> config (one dict per file)
        self.osc = OscSender()
        self._ma2 = {}
        self.jobs = queue.Queue()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._started = False
        self._worker = threading.Thread(target=self._work, name="cuekeys-bridge", daemon=True)
        self._discovery = threading.Thread(target=self._discover_loop, name="cuekeys-discovery", daemon=True)

    # -- lifecycle ---------------------------------------------------------------
    def start(self):
        if self._started:
            return
        self._started = True
        self._worker.start()
        with self._lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            session.link.start()
        if self.discover:
            self.scan()
            self._discovery.start()
        self._ensure_virtual()
        self.sync_satellites()

    def stop(self):
        self._stop.set()
        with self._lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            session.link.stop()
        for sat in list(self.satellites.values()):
            sat.stop()
        self.satellites.clear()
        self.jobs.put(None)
        for client in self._ma2.values():
            client.close()
        self.osc.close()

    def add_listener(self, fn):
        self.listeners.append(fn)

    def emit(self, event, **data):
        for fn in list(self.listeners):
            try:
                fn(event, data)
            except Exception:  # noqa: BLE001
                log.exception("listener failed")

    # -- sessions ------------------------------------------------------------------
    def add_session(self, uid, config=None, link=None, port=None):
        """Register a keypad (tests and single-keypad use pass a ``link``)."""
        uid = str(uid).upper() if uid != VIRTUAL_UID else uid
        with self._lock:
            if uid in self.sessions:
                return self.sessions[uid]
            path = None
            if config is None:
                config, path = self._config_for(uid)
            session = KeypadSession(self, uid, config, link=link, port=port)
            session.layout_path = path
            if link is None and self.link_factory is not None and uid != VIRTUAL_UID:
                session.link = self.link_factory(session, port)
            self.sessions[uid] = session
            if uid != VIRTUAL_UID:
                virtual = self.sessions.pop(VIRTUAL_UID, None)
            else:
                virtual = None
        if virtual is not None:
            self.emit("keypads", removed=VIRTUAL_UID, keypad=VIRTUAL_UID)
        if self._started:
            session.link.start()
        self.sync_satellites()
        self.emit("keypads", added=uid, keypad=uid)
        return session

    def remove_session(self, uid):
        with self._lock:
            session = self.sessions.pop(uid, None)
        if session is None:
            return
        session.link.stop()
        self.sync_satellites()
        self.emit("keypads", removed=uid, keypad=uid)
        self._ensure_virtual()

    def _ensure_virtual(self):
        """Keep an editable stand-in keypad while no real keypad is known."""
        if self.default_config is None:
            return
        with self._lock:
            empty = not self.sessions
        if empty:
            self.add_session(VIRTUAL_UID, self.default_config)

    def _config_for(self, uid):
        """(config, path) for a keypad: its assigned layout, else the default."""
        layout = self.store.get(uid).get("layout") if self.store else None
        if layout and self.layout_loader is not None:
            try:
                return self.load_layout(layout), layout
            except (OSError, ValueError) as err:
                log.warning("keypad %s: can't load layout %s (%s); using the default", uid, layout, err)
        if self.default_config is None:
            raise ValueError("no layout for keypad %s" % uid)
        return self.default_config, self.default_path

    # -- layouts ---------------------------------------------------------------------
    def load_layout(self, path):
        """Load a layout file once; keypads using the same file share one config."""
        key = str(path)
        with self._lock:
            if key in self._layouts:
                return self._layouts[key]
        config = self.layout_loader(key)
        with self._lock:
            return self._layouts.setdefault(key, config)

    def assign_layout(self, session, config, path=None):
        """Give a keypad a (new) layout; remembered for it when it has a file."""
        if path:
            with self._lock:
                self._layouts[str(path)] = config
        session.layout_path = str(path) if path else None
        if session.uid == VIRTUAL_UID:
            self.default_config, self.default_path = config, session.layout_path
        elif self.store is not None:
            self.store.update(session.uid, layout=session.layout_path)
        session.set_config(config)
        self.emit("config", keypad=session.uid)

    def sessions_using(self, config):
        with self._lock:
            return [s for s in self.sessions.values() if s.config is config]

    def config_changed(self, config):
        """A layout was edited: refresh every keypad that uses it."""
        for session in self.sessions_using(config):
            session.set_config(config)
            self.emit("config", keypad=session.uid)

    def rename(self, uid, name):
        if self.store is None or uid == VIRTUAL_UID:
            return
        self.store.update(uid, name=(name or "").strip() or None)
        self.sync_satellites()                     # surface names include the keypad name
        self.emit("keypads", renamed=uid, keypad=uid)

    def keypad_seen(self, uid):
        if self.store is not None and uid != VIRTUAL_UID:
            try:
                self.store.seen(uid)
            except OSError as err:
                log.debug("can't save keypad store: %s", err)

    # -- discovery -------------------------------------------------------------------
    def scan(self, keypads=None):
        """Open sessions for newly connected keypads; follow keypads to new ports."""
        keypads = device.list_keypads() if keypads is None else keypads
        for info in keypads:
            uid = info["uid"]
            with self._lock:
                session = self.sessions.get(uid)
            if session is None:
                self.add_session(uid, port=info["data_port"])
            elif session.port != info["data_port"] and not session.connected:
                # Re-plugged on another port name.
                session.port = info["data_port"]
                if hasattr(session.link, "set_port"):
                    session.link.set_port(info["data_port"])

    def _discover_loop(self):
        while not self._stop.wait(DISCOVERY_INTERVAL):
            try:
                self.scan()
            except Exception:  # noqa: BLE001 - discovery must keep running
                log.exception("keypad discovery failed")

    # -- bridges ------------------------------------------------------------------------
    def send_osc(self, session, target, address, args):
        dest = session.bridge("osc_targets").get(target)
        if dest is None:
            session.emit("log", level="error", message="unknown OSC target %r" % target)
            return
        try:
            self.osc.send(dest["host"], dest["port"], address, args)
        except (OSError, ValueError, TypeError) as err:
            session.emit("log", level="error", message="OSC send failed: %s" % err)

    def send_ma(self, session, console, command):
        if console == "ma2":
            self.jobs.put(("ma2", (session, command)))
            return
        ma3 = session.bridge("ma3")
        try:
            self.osc.send(ma3.get("host", "127.0.0.1"), ma3.get("port", 8000),
                          grandma.ma3_address(ma3.get("prefix", "gma3")), [command])
        except OSError as err:
            session.emit("log", level="error", message="MA3 OSC failed: %s" % err)

    def _work(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            kind, payload = job
            session = payload[0]
            try:
                if kind == "ma2":
                    _session, command = payload
                    ma2 = session.bridge("ma2")
                    key = (ma2.get("host", "127.0.0.1"), int(ma2.get("port", 30000)), ma2.get("user", "administrator"))
                    if key not in self._ma2:
                        self._ma2[key] = grandma.MA2Telnet(key[0], key[1], key[2], ma2.get("password", ""))
                    self._ma2[key].send(command)
                elif kind == "page_name":
                    _session, layer, page = payload
                    self._fetch_page_name(session, layer, page)
                elif kind == "companion":
                    _session, msg = payload
                    target = session.bridge("companion").get(msg.get("target", "default"))
                    if target is None:
                        raise ValueError("unknown Companion target %r" % msg.get("target"))
                    comp.http_button(target.get("host", "127.0.0.1"), target.get("http_port", 8000),
                                     msg.get("page", 1), msg.get("row", 0), msg.get("column", 0),
                                     msg.get("op", "press"))
            except Exception as err:  # noqa: BLE001
                session.emit("log", level="error", message="%s failed: %s" % (kind, err))

    # -- companion --------------------------------------------------------------------
    def sync_satellites(self):
        """One Satellite connection per Companion server, carrying every keypad's surfaces."""
        wanted = {}                 # endpoint -> {device_id: (name, keys, per_row)}
        devices = {}
        with self._lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            profile, rotation = session._profile(), session._rotation()
            width = profile.display_size(rotation)[1]
            for index, layer in session.companion_layers():
                target = layer.get("companion_target", "default")
                endpoint = _endpoint(session.config, target)
                if endpoint is None:
                    session.emit("log", level="error", message="unknown Companion target %r" % target)
                    continue
                device_id = session.device_id(index)
                devices[device_id] = (session, index)
                name = "CueKeys %s · %s" % (session.name, layer.get("name") or "layer %d" % index)
                rows = companion_rows(layer, profile, rotation)
                wanted.setdefault(endpoint, {})[device_id] = (name, rows * width, width)
        self._devices = devices
        for endpoint in list(self.satellites):
            if endpoint not in wanted:
                self.satellites.pop(endpoint).stop()
        for endpoint, specs in wanted.items():
            sat = self.satellites.get(endpoint)
            if sat is None:
                sat = self.satellite_factory(
                    endpoint[0], endpoint[1], on_key_state=self._on_companion_state,
                    on_status=lambda connected, e=endpoint: self._on_companion_status(e, connected))
                self.satellites[endpoint] = sat
                for device_id, spec in specs.items():
                    sat.add_device(device_id, *spec)
                if self._started:
                    sat.start()
            else:
                for device_id in list(sat.devices):
                    if device_id not in specs:
                        sat.remove_device(device_id)
                for device_id, spec in specs.items():
                    if sat.devices.get(device_id) != spec:
                        sat.add_device(device_id, *spec)
                        session, index = devices[device_id]
                        session.forget_companion_states(index)
                if self._started and hasattr(sat, "start"):
                    sat.start()

    def _on_companion_status(self, endpoint, connected):
        self.companion_connected[endpoint] = connected
        with self._lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            for _index, layer in session.companion_layers():
                target = layer.get("companion_target", "default")
                if _endpoint(session.config, target) == endpoint:
                    session.emit("companion", target=target, connected=connected)
                    break

    def _on_companion_state(self, device_id, index, state):
        entry = self._devices.get(device_id)
        if entry is None or index < 0:
            return
        session, layer = entry
        session.on_companion_state(layer, index, state)

    def _fetch_page_name(self, session, layer, page):
        target = session._layer_target(layer)
        conf = session.bridge("companion").get(target) or {}
        name = comp.page_name(conf.get("host", "127.0.0.1"), conf.get("http_port", 8000), page)
        self.page_names[(_endpoint(session.config, target), page)] = name
        session.page_name_arrived(layer, page, name)


# =============================================================================
def Runtime(config, port=None, link=None, satellite_factory=None, uid=None, store=None):  # noqa: N802
    """A single-keypad hub, returned as its session (CLI ``--port``, tests).

    Without ``link`` it opens ``port`` (or the first keypad found); the keypad's
    id is looked up from its USB serial number when possible.
    """
    if uid is None:
        uid = "LOCAL"
        if link is None:
            try:
                found = [k for k in device.list_keypads() if port in (None, k["data_port"])]
            except Exception:  # noqa: BLE001 - no pyserial/ports: keep the local id
                found = []
            if found:
                uid, port = found[0]["uid"], port or found[0]["data_port"]
    hub = Hub(satellite_factory=satellite_factory, discover=False, store=store)
    session = hub.add_session(uid, config, link=link or _NoLink(), port=port)
    if link is None:
        session.link = DeviceLink(port, session._on_message, session._on_status)
    return session

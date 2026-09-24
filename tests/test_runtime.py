import socket

from pmk_macro_manager import grandma
from pmk_macro_manager.config import default_config
from pmk_macro_manager.osc import encode_message
from pmk_macro_manager.runtime import Runtime, companion_device_id


class FakeLink:
    def __init__(self, connected=True):
        self.sent = []
        self.connected = connected

    def start(self):
        pass

    def stop(self):
        pass

    def send(self, msg):
        if self.connected:
            self.sent.append(msg)
        return self.connected


class FakeSatellite:
    """Stands in for SatelliteClient so tests never connect to a real Companion."""

    def __init__(self, host="127.0.0.1", port=16622, on_key_state=None, on_status=None, **_kw):
        self.presses, self.pages = [], []
        self.host, self.port, self.devices, self.registered = host, int(port), {}, {}
        self.connected = True

    def add_device(self, device_id, name, keys_total=16):
        self.devices[device_id] = (name, keys_total)

    def change_page(self, device_id, forward=True):
        self.pages.append((device_id, forward))
        return True

    def remove_device(self, device_id):
        self.devices.pop(device_id, None)

    def key_press(self, device_id, index, pressed):
        self.presses.append((device_id, index, pressed))

    def start(self):
        pass

    def stop(self):
        pass


def udp_listener():
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2)
    return rx, rx.getsockname()[1]


def make(config=None, link=None):
    config = config or default_config()
    rt = Runtime(config, link=link or FakeLink(), satellite_factory=FakeSatellite)
    events = []
    rt.add_listener(lambda name, data: events.append((name, data)))
    return rt, events


def test_osc_and_ma3_forwarding():
    rx, port = udp_listener()
    config = default_config()
    config["bridge"]["osc_targets"]["default"]["port"] = port
    config["bridge"]["ma3"].update(port=port, prefix="gma3")
    rt, events = make(config)
    rt._on_message({"t": "osc", "addr": "/fader", "args": [0.5], "target": "default"})
    assert rx.recv(1024) == encode_message("/fader", [0.5])
    rt._on_message({"t": "ma", "cmd": "Go+ Executor 201", "console": "ma3"})
    assert rx.recv(1024) == encode_message(grandma.ma3_address("gma3"), ["Go+ Executor 201"])
    rt._on_message({"t": "osc", "addr": "/x", "args": [], "target": "missing"})
    assert events[-1][0] == "log"


def test_layer_and_key_events():
    config = default_config()
    config["layers"].append({"name": "Two", "keys": {}})
    rt, events = make(config)
    rt._on_message({"t": "layer", "i": 1, "name": "Two"})
    rt._on_message({"t": "key", "k": 5, "s": 1, "l": 1})
    assert rt.layer == 1 and rt.pressed == {5: 1}
    rt._on_message({"t": "key", "k": 5, "s": 0, "l": 1})
    assert rt.pressed == {}
    assert [e[0] for e in events] == ["layer", "key", "key"]


def test_select_layer_without_keypad_previews_locally():
    config = default_config()
    config["layers"].append({"name": "Two", "keys": {}})
    rt, events = make(config, FakeLink(connected=False))
    rt.select_layer(1)
    assert rt.layer == 1


def test_companion_layer_forwards_unassigned_keys():
    config = default_config()
    config["layers"].append({"name": "C", "mode": "companion", "companion_id": "pad1",
                             "keys": {"0": {"press": [{"type": "layer", "op": "next"}]},
                                      "1": {"press": []}}})  # empty = unassigned
    rt, _ = make(config)
    sat = FakeSatellite()
    rt.satellites["default"] = sat
    rt._device_layers = {"pad1": 1}
    rt._on_message({"t": "key", "k": 3, "s": 1, "l": 1})
    rt._on_message({"t": "key", "k": 3, "s": 0, "l": 1})
    rt._on_message({"t": "key", "k": 1, "s": 1, "l": 1})
    rt._on_message({"t": "key", "k": 0, "s": 1, "l": 1})   # locally assigned
    rt._on_message({"t": "key", "k": 7, "s": 1, "l": 0})   # local layer
    assert sat.presses == [("pad1", 0, True), ("pad1", 0, False), ("pad1", 8, True)]


def test_bottom_row_stays_local_on_4x3_surface():
    config = default_config()
    config["layers"].append({"name": "C", "mode": "companion", "companion_id": "pad1", "keys": {}})
    rt, _ = make(config)
    sat = FakeSatellite()
    rt.satellites["default"] = sat
    rt._on_message({"t": "key", "k": 4, "s": 1, "l": 1})   # bottom row -> PMK only
    assert sat.presses == []
    config["layers"][1]["companion_rows"] = 4
    rt._on_message({"t": "key", "k": 4, "s": 1, "l": 1})
    assert sat.presses == [("pad1", 13, True)]


def test_companion_page_and_overlay_messages():
    config = default_config()
    config["layers"].append({"name": "C", "mode": "companion", "companion_id": "pad1", "keys": {}})
    rt, events = make(config)
    sat = FakeSatellite()
    rt.satellites["default"] = sat
    rt._on_message({"t": "companion_page", "l": 1, "dir": 0})
    rt._on_message({"t": "companion_page", "l": 1, "dir": 1})
    assert sat.pages == [("pad1", False), ("pad1", True)]
    rt._on_message({"t": "companion_page", "l": 0, "dir": 1})  # not a Companion layer
    assert events[-1][0] == "log"
    rt._on_message({"t": "overlay", "op": "cycle", "levels": [1, 0]})
    assert events[-1] == ("overlay", {"op": "cycle", "levels": [1, 0]})


def test_companion_page_tracked_from_location():
    config = default_config()
    config["layers"].append({"name": "C", "mode": "companion", "companion_id": "pad1", "keys": {}})
    rt, _ = make(config)
    rt._device_layers = {"pad1": 1}
    rt._on_companion_state("pad1", 0, {"color": (1, 1, 1), "page": 7})
    assert rt.companion_pages == {1: 7}


def test_companion_state_updates_leds():
    config = default_config()
    config["layers"].append({"name": "C", "mode": "companion", "companion_id": "pad1", "keys": {}})
    link = FakeLink()
    rt, events = make(config, link)
    rt._device_layers = {"pad1": 1}
    rt._on_companion_state("pad1", 0, {"color": (1, 2, 3), "text": "Hi"})
    assert link.sent[-1] == {"t": "led", "l": 1, "k": 3, "rgb": [1, 2, 3]}
    assert rt.companion_states[(1, 3)]["text"] == "Hi"
    link.sent.clear()
    rt._on_message({"t": "hello", "fw": "0.1.0"})
    assert link.sent == [{"t": "led", "l": 1, "k": 3, "rgb": [1, 2, 3]}]


def test_satellites_follow_companion_layers():
    config = default_config()
    rt, _ = make(config)
    rt.set_config(config)
    assert rt.satellites == {}
    config["layers"].append({"name": "C", "mode": "companion", "companion_id": "pad1", "keys": {}})
    rt.set_config(config)
    assert rt.satellites["default"].devices == {"pad1": ("PMK C", 12)}  # 4x3 by default
    config["layers"][-1]["companion_rows"] = 4
    rt.set_config(config)
    assert rt.satellites["default"].devices == {"pad1": ("PMK C", 16)}
    config["layers"][-1]["mode"] = "local"
    rt.set_config(config)
    assert rt.satellites == {}


def test_companion_device_id_default_is_stable():
    layer = {"name": "x"}
    assert companion_device_id(layer, 2) == companion_device_id(layer, 2)
    assert companion_device_id({"companion_id": "abc"}, 2) == "abc"


def test_companion_page_name_is_fetched_and_applied(monkeypatch):
    from pmk_macro_manager import companion as comp

    config = default_config()
    config["layers"].append({"name": "C", "mode": "companion", "companion_id": "pad1", "keys": {}})
    rt, events = make(config)
    rt._device_layers = {"pad1": 1}
    calls = []
    monkeypatch.setattr(comp, "page_name", lambda host, port, page: calls.append((host, port, page)) or "PMK 1")
    rt._on_companion_state("pad1", 1, {"type": "PAGENUM", "text": "", "page": 4})
    assert rt.companion_page_label(1) == "p.4"          # name not fetched yet
    job = rt._jobs.get_nowait()
    assert job == ("page_name", (1, "default", 4))
    rt._fetch_page_name(*job[1])
    assert calls == [("127.0.0.1", 8000, 4)]
    assert rt.companion_states[(1, 7)]["page_name"] == "PMK 1"
    assert rt.companion_page_label(1) == "PMK 1"
    assert events[-1][0] == "companion"
    # later updates for the same page keep the name without another fetch
    rt._on_companion_state("pad1", 1, {"type": "PAGENUM", "text": "", "page": 4, "color": (1, 2, 3)})
    assert rt.companion_states[(1, 7)]["page_name"] == "PMK 1" and rt._jobs.empty()

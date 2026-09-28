# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
import socket

from cuekeys import grandma
from cuekeys.config import default_config
from cuekeys.link import DeviceLink
from cuekeys.osc import encode_message
from cuekeys.runtime import Runtime, companion_device_id


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

    def add_device(self, device_id, name, keys_total=16, keys_per_row=4):
        self.devices[device_id] = (name, keys_total, keys_per_row)

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


def test_real_serial_link_requires_matching_keypad_identity():
    config = default_config()
    config["layers"].append({"name": "Two", "keys": {}})
    link = DeviceLink("/dev/fake")
    rt = Runtime(config, link=link, satellite_factory=FakeSatellite, uid="ABC123")
    rt._on_message({"t": "layer", "i": 1})
    assert rt.layer == 0
    events = []
    rt.add_listener(lambda name, data: events.append((name, data)))
    rt._on_message({"t": "hello", "uid": "WRONG", "fw": "0.1.0"})
    assert not rt._handshake_ok
    assert events[-1][0] == "log" and "WRONG" in events[-1][1]["message"]   # shown to the user
    rt._on_message({"t": "hello", "fw": "0.0.9"})                           # firmware without an id
    assert "Install / update firmware" in events[-1][1]["message"]
    rt._on_message({"t": "hello", "uid": "ABC123", "fw": "0.1.0"})
    rt._on_message({"t": "layer", "i": 1})
    assert rt.layer == 1


def test_select_layer_without_keypad_previews_locally():
    config = default_config()
    config["layers"].append({"name": "Two", "keys": {}})
    rt, events = make(config, FakeLink(connected=False))
    rt.select_layer(1)
    assert rt.layer == 1


ENDPOINT = ("127.0.0.1", 16622)
DEV = "ck-local-pad1"      # companion_device_id("LOCAL", layer with companion_id "pad1")


def make_companion(keys=None, **layer_extra):
    """A session with a Companion layer (index 1) and its FakeSatellite."""
    config = default_config()
    config["layers"].append(dict({"name": "C", "mode": "companion", "companion_id": "pad1",
                                  "keys": keys or {}}, **layer_extra))
    rt, events = make(config)
    rt.set_config(config)
    return rt, events, rt.hub.satellites[ENDPOINT]


def test_companion_layer_forwards_unassigned_keys():
    rt, _, sat = make_companion({"0": {"press": [{"type": "layer", "op": "next"}]},
                                 "1": {"press": []}})     # empty = unassigned
    rt._on_message({"t": "key", "k": 3, "s": 1, "l": 1})
    rt._on_message({"t": "key", "k": 3, "s": 0, "l": 1})
    rt._on_message({"t": "key", "k": 1, "s": 1, "l": 1})
    rt._on_message({"t": "key", "k": 0, "s": 1, "l": 1})   # locally assigned
    rt._on_message({"t": "key", "k": 7, "s": 1, "l": 0})   # local layer
    assert sat.presses == [(DEV, 0, True), (DEV, 0, False), (DEV, 8, True)]


def test_bottom_row_stays_local_on_4x3_surface():
    rt, _, sat = make_companion()
    rt._on_message({"t": "key", "k": 4, "s": 1, "l": 1})   # bottom row -> local only
    assert sat.presses == []
    rt.config["layers"][1]["companion_rows"] = 4
    rt._on_message({"t": "key", "k": 4, "s": 1, "l": 1})
    assert sat.presses == [(DEV, 13, True)]


def test_companion_page_and_overlay_messages():
    rt, events, sat = make_companion()
    rt._on_message({"t": "companion_page", "l": 1, "dir": 0})
    rt._on_message({"t": "companion_page", "l": 1, "dir": 1})
    assert sat.pages == [(DEV, False), (DEV, True)]
    rt._on_message({"t": "companion_page", "l": 0, "dir": 1})  # not a Companion layer
    assert events[-1][0] == "log"
    rt._on_message({"t": "overlay", "op": "cycle", "levels": [1, 0]})
    assert events[-1] == ("overlay", {"keypad": "LOCAL", "op": "cycle", "levels": [1, 0]})


def test_companion_page_tracked_from_location():
    rt, _, _ = make_companion()
    rt.hub._on_companion_state(DEV, 0, {"color": (1, 1, 1), "page": 7})
    assert rt.companion_pages == {1: 7}


def test_companion_state_updates_leds():
    rt, _, _ = make_companion()
    link = rt.link
    rt.hub._on_companion_state(DEV, 0, {"color": (1, 2, 3), "text": "Hi"})
    assert link.sent[-1] == {"t": "led", "l": 1, "k": 3, "rgb": [1, 2, 3]}
    assert rt.companion_states[(1, 3)]["text"] == "Hi"
    link.sent.clear()
    rt._on_message({"t": "hello", "fw": "0.1.0"})
    assert link.sent[0] == {"t": "led", "l": 1, "k": 3, "rgb": [1, 2, 3]}
    assert link.sent[1]["t"] == "colors"                  # editor colours re-sent after a restart


def test_colour_preview_follows_the_layout():
    config = default_config()
    config["layers"][0]["color"] = "#ff0000"
    config["layers"][0]["keys"] = {"0": {"press": [{"type": "text", "text": "x"}]},
                                   "1": {"color": "#00ff00", "press": []},
                                   "2": {"press": []}}                     # empty: not assigned
    link = FakeLink()
    rt = Runtime(config, link=link, satellite_factory=FakeSatellite)
    rt.push_colors()
    assert link.sent == [{"t": "colors", "layers": [{"c": "#ff0000", "k": {"0": None, "1": "#00ff00"}}]}]
    rt.push_colors()                                                       # unchanged: not re-sent
    assert len(link.sent) == 1
    config["layers"][0]["keys"]["0"]["color"] = "#0000ff"
    rt.push_colors()
    assert link.sent[-1]["layers"][0]["k"]["0"] == "#0000ff"


def test_satellites_follow_companion_layers():
    config = default_config()
    rt, _ = make(config)
    rt.set_config(config)
    assert rt.hub.satellites == {}
    config["layers"].append({"name": "C", "mode": "companion", "companion_id": "pad1", "keys": {}})
    rt.set_config(config)
    name = "CueKeys Keypad local · C"
    assert rt.hub.satellites[ENDPOINT].devices == {DEV: (name, 12, 4)}   # 4x3 by default
    config["layers"][-1]["companion_rows"] = 4
    rt.set_config(config)
    assert rt.hub.satellites[ENDPOINT].devices == {DEV: (name, 16, 4)}
    config["device"]["profile"] = "adafruit_macropad"   # 3 wide, 4 tall
    config["layers"][-1].pop("companion_rows")
    rt.set_config(config)
    assert rt.hub.satellites[ENDPOINT].devices == {DEV: (name, 9, 3)}
    config["layers"][-1]["mode"] = "local"
    rt.set_config(config)
    assert rt.hub.satellites == {}


def test_companion_device_ids_follow_the_keypad_not_the_layout():
    layer = {"name": "x", "companion_id": "pad1"}
    assert companion_device_id("E6617C93E35B8C2B", layer, 2) == "ck-e35b8c2b-pad1"
    assert companion_device_id("0123456789ABCDEF", layer, 2) == "ck-89abcdef-pad1"   # same layout, other pad
    assert companion_device_id("E6617C93E35B8C2B", {"companion_id": "cuekeys-example"}, 0) == "ck-e35b8c2b-example"
    assert companion_device_id("E6617C93E35B8C2B", {}, 3) == "ck-e35b8c2b-l3"


def test_macropad_companion_mapping():
    config = default_config()
    config["device"]["profile"] = "adafruit_macropad"
    config["layers"].append({"name": "C", "mode": "companion", "companion_id": "pad1", "keys": {}})
    rt, _ = make(config)
    rt.set_config(config)
    sat = rt.hub.satellites[ENDPOINT]
    rt._on_message({"t": "key", "k": 5, "s": 1, "l": 1})    # row 1, col 2 -> index 5 in a 3-wide surface
    rt._on_message({"t": "key", "k": 10, "s": 1, "l": 1})   # bottom row stays local
    assert sat.presses == [(DEV, 5, True)]
    rt.hub._on_companion_state(DEV, 8, {"color": (9, 9, 9)})
    assert (1, 8) in rt.companion_states
    rt.hub._on_companion_state(DEV, 40, {"color": (9, 9, 9)})  # outside the grid: ignored
    assert (1, 40) not in rt.companion_states


def test_companion_page_name_is_fetched_and_applied(monkeypatch):
    from cuekeys import companion as comp

    rt, events, _ = make_companion()
    calls = []
    monkeypatch.setattr(comp, "page_name", lambda host, port, page: calls.append((host, port, page)) or "CueKeys 1")
    rt.hub._on_companion_state(DEV, 1, {"type": "PAGENUM", "text": "", "page": 4})
    assert rt.companion_page_label(1) == "p.4"          # name not fetched yet
    kind, payload = rt.hub.jobs.get_nowait()
    assert kind == "page_name" and payload[1:] == (1, 4)
    rt.hub._fetch_page_name(*payload)
    assert calls == [("127.0.0.1", 8000, 4)]
    assert rt.companion_states[(1, 7)]["page_name"] == "CueKeys 1"
    assert rt.companion_page_label(1) == "CueKeys 1"
    assert events[-1][0] == "companion"
    # later updates for the same page keep the name without another fetch
    rt.hub._on_companion_state(DEV, 1, {"type": "PAGENUM", "text": "", "page": 4, "color": (1, 2, 3)})
    assert rt.companion_states[(1, 7)]["page_name"] == "CueKeys 1" and rt.hub.jobs.empty()

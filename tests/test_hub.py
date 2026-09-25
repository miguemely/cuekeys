"""Multi-keypad: identity, per-keypad settings, discovery and shared bridges."""

from types import SimpleNamespace

from cuekeys import config as cfg
from cuekeys import device
from cuekeys.config import default_config
from cuekeys.keypads import VIRTUAL_UID, KeypadStore, short_id
from cuekeys.runtime import Hub

from .test_runtime import FakeLink, FakeSatellite

A, B = "E6617C93E35B8C2B", "0123456789ABCDEF"
ENDPOINT = ("127.0.0.1", 16622)


def companion_config():
    config = default_config()
    config["layers"].append({"name": "C", "mode": "companion", "companion_id": "main", "keys": {}})
    return config


def make_hub(tmp_path, default=None, **kw):
    store = KeypadStore(tmp_path / "keypads.json")
    hub = Hub(default_config=default, store=store, satellite_factory=FakeSatellite, discover=False,
              link_factory=lambda session, port: FakeLink(), **kw)
    events = []
    hub.add_listener(lambda name, data: events.append((name, data)))
    return hub, store, events


# ------------------------------------------------------------------ store
def test_store_round_trip(tmp_path):
    store = KeypadStore(tmp_path / "keypads.json")
    assert store.get(A) == {} and store.name(A) == "Keypad e35b8c2b"
    store.update(A.lower(), name="FOH", led_balance=[0.7, 1.0, 0.8])     # ids are case-insensitive
    reopened = KeypadStore(tmp_path / "keypads.json")
    assert reopened.get(A) == {"name": "FOH", "led_balance": [0.7, 1.0, 0.8]}
    assert reopened.name(A) == "FOH" and reopened.name(VIRTUAL_UID) == "No keypad"
    reopened.update(A, name=None)
    assert "name" not in reopened.get(A)
    assert reopened.forget(A) and not reopened.forget(A)
    assert short_id(A) == "e35b8c2b"


# ------------------------------------------------------------------ discovery
def port(dev, serial, interface=None, location=None):
    return SimpleNamespace(device=dev, serial_number=serial, interface=interface, location=location,
                           manufacturer="Pimoroni", product="Keybow 2040", description="", vid=0x16D0,
                           hwid="USB")


def test_list_keypads_groups_ports_by_serial():
    ports = [
        port("/dev/cu.usbmodem1201", A, "CircuitPython CDC control"),
        port("/dev/cu.usbmodem1203", A, "CircuitPython CDC2 data"),
        port("COM7", B, location="1-2:x.0"), port("COM8", B, location="1-2:x.2"),   # Windows: no names
        port("/dev/ttyACM9", "FFFFFFFFFFFFFFFF", "CircuitPython CDC control"),     # console only
    ]
    found = device.list_keypads(ports)
    assert found == [
        {"uid": B, "data_port": "COM8", "console_port": "COM7"},
        {"uid": A, "data_port": "/dev/cu.usbmodem1203", "console_port": "/dev/cu.usbmodem1201"},
    ]


def test_drive_is_matched_by_uid(tmp_path, monkeypatch):
    drives = []
    for uid in (A, B):
        d = tmp_path / uid
        d.mkdir()
        (d / "boot_out.txt").write_text("Adafruit CircuitPython 9\nBoard ID:pimoroni_keybow2040\nUID:%s\n" % uid)
        drives.append(d)
    monkeypatch.setattr(device, "find_drives", lambda: drives)
    assert device.pick_drive(uid=B.lower()) == drives[1]
    assert device.board_uid(drives[0]) == A
    try:
        device.pick_drive()
    except RuntimeError as err:
        assert "--keypad" in str(err)
    else:
        raise AssertionError("two drives must be ambiguous without a keypad id")


# ------------------------------------------------------------------ hub
def test_two_keypads_one_layout_get_separate_surfaces(tmp_path):
    shared = companion_config()
    hub, store, _ = make_hub(tmp_path)
    store.update(A, name="FOH")
    a = hub.add_session(A, shared)
    b = hub.add_session(B, shared)
    sat = hub.satellites[ENDPOINT]                         # one connection for both keypads
    assert sat.devices == {"ck-e35b8c2b-main": ("CueKeys FOH · C", 12, 4),
                           "ck-89abcdef-main": ("CueKeys Keypad 89abcdef · C", 12, 4)}
    # key presses and Companion updates are routed per keypad
    b._on_message({"t": "key", "k": 3, "s": 1, "l": 1})
    assert sat.presses == [("ck-89abcdef-main", 0, True)]
    hub._on_companion_state("ck-e35b8c2b-main", 0, {"color": (1, 2, 3), "text": "A"})
    assert a.companion_states[(1, 3)]["text"] == "A" and b.companion_states == {}
    assert a.link.sent[-1] == {"t": "led", "l": 1, "k": 3, "rgb": [1, 2, 3]} and b.link.sent == []
    hub.remove_session(A)
    assert list(sat.devices) == ["ck-89abcdef-main"]


def test_virtual_keypad_until_a_real_one_arrives(tmp_path):
    hub, _, events = make_hub(tmp_path, default=companion_config())
    hub._ensure_virtual()
    assert list(hub.sessions) == [VIRTUAL_UID]
    assert list(hub.satellites[ENDPOINT].devices)[0].startswith("ck-")   # host-based id, still usable
    hub.scan([{"uid": A, "data_port": "/dev/x", "console_port": "/dev/y"}])
    assert list(hub.sessions) == [A]
    assert ("keypads", {"removed": VIRTUAL_UID, "keypad": VIRTUAL_UID}) in events
    assert ("keypads", {"added": A, "keypad": A}) in events
    hub.remove_session(A)
    assert list(hub.sessions) == [VIRTUAL_UID]


def test_scan_adds_keypads_and_follows_port_changes(tmp_path):
    hub, _, _ = make_hub(tmp_path, default=default_config())
    moves = []
    hub.scan([{"uid": A, "data_port": "/dev/a1", "console_port": None},
              {"uid": B, "data_port": "/dev/b1", "console_port": None}])
    assert sorted(hub.sessions) == sorted([A, B])
    session = hub.sessions[A]
    session.link.set_port = moves.append
    hub.scan([{"uid": A, "data_port": "/dev/a2", "console_port": None}])   # re-plugged elsewhere
    assert moves == ["/dev/a2"] and session.port == "/dev/a2"
    hub.scan([{"uid": A, "data_port": "/dev/a2", "console_port": None}])   # already known: no churn
    assert len(hub.sessions) == 2 and moves == ["/dev/a2"]


def test_keypad_layout_assignment_and_shared_layouts(tmp_path):
    layouts = {"/show.json": companion_config()}

    def load(path):                       # behaves like config.load: missing file -> FileNotFoundError
        if path not in layouts:
            raise FileNotFoundError(path)
        return layouts[path]

    hub, store, _ = make_hub(tmp_path, default=default_config(), layout_loader=load)
    store.update(A, layout="/show.json")
    store.update(B, layout="/show.json")
    a, b = hub.add_session(A), hub.add_session(B)
    assert a.config is b.config is layouts["/show.json"]   # same file -> edits apply to both
    store.update("C0FFEE00C0FFEE00", layout="/missing.json")
    c = hub.add_session("C0FFEE00C0FFEE00")
    assert c.config is hub.default_config                  # unreadable layout falls back


def test_keypad_calibration_wins_at_deploy():
    config = default_config()
    config["device"]["led_balance"] = [0.9, 0.9, 0.9]                  # layout's (older) calibration
    view = cfg.firmware_view(config, {"led_balance": [0.6, 1.0, 0.7], "led_gamma": 2.4})
    assert view["device"]["led_balance"] == [0.6, 1.0, 0.7] and view["device"]["led_gamma"] == 2.4
    assert cfg.firmware_view(config)["device"]["led_balance"] == [0.9, 0.9, 0.9]

"""Editor and overlays with several keypads on one hub."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from cuekeys import cli, device  # noqa: E402
from cuekeys import config as cfg  # noqa: E402
from cuekeys.config import default_config  # noqa: E402
from cuekeys.examples import example_config  # noqa: E402
from cuekeys.keypads import VIRTUAL_UID, KeypadStore  # noqa: E402
from cuekeys.runtime import Hub  # noqa: E402

from .test_runtime import FakeLink, FakeSatellite  # noqa: E402

A, B = "E6617C93E35B8C2B", "0123456789ABCDEF"


@pytest.fixture
def setup(qtbot, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    from cuekeys.gui.common import RuntimeSignals
    from cuekeys.gui.editor import MainWindow

    store = KeypadStore(tmp_path / "keypads.json")
    hub = Hub(default_config=example_config(), store=store, satellite_factory=FakeSatellite,
              discover=False, layout_loader=cfg.load, link_factory=lambda s, p: FakeLink())
    signals = RuntimeSignals(hub)
    hub.start()
    assert list(hub.sessions) == [VIRTUAL_UID]
    win = MainWindow(hub.sessions[VIRTUAL_UID], signals)
    monkeypatch.setattr(win, "_confirm_discard", lambda: True)
    qtbot.addWidget(win)
    yield win, hub, store
    win.overlays.close()
    hub.stop()


def test_virtual_keypad_hands_over_to_the_real_one(setup):
    win, hub, _ = setup
    assert win.keypad_combo.count() == 1 and win.keypad_combo.itemText(0) == "No keypad"
    layout = win.config
    hub.scan([{"uid": A, "data_port": "/dev/a", "console_port": None}])
    assert win.runtime.uid == A and win.config is layout          # same layout, now on the keypad
    assert [win.keypad_combo.itemData(i) for i in range(win.keypad_combo.count())] == [A]
    assert set(win.overlays.overlays) == {A}


def test_switching_keypads_edits_their_own_layouts(setup, tmp_path):
    win, hub, store = setup
    other = default_config()
    other["layers"][0]["name"] = "Other"
    path = tmp_path / "other.json"
    cfg.save(other, path)
    store.update(B, layout=str(path), name="Stage")
    hub.scan([{"uid": A, "data_port": "/dev/a", "console_port": None},
              {"uid": B, "data_port": "/dev/b", "console_port": None}])
    assert win.keypad_combo.count() == 2
    win.switch_keypad(B)
    assert win.runtime.uid == B and win.config["layers"][0]["name"] == "Other"
    assert win.path == path
    # events of the other keypad don't touch this view
    hub.sessions[A].emit("key", key=1, pressed=True, layer=0)
    assert win.pressed == set()
    hub.sessions[B].emit("key", key=2, pressed=True, layer=0)
    assert win.pressed == {2}
    # opening a new layout only changes the current keypad
    win._replace_config(default_config(), None)
    assert hub.sessions[A].config is hub.default_config and store.get(B).get("layout") is None


def test_overlays_stack_and_carry_keypad_names(setup):
    win, hub, store = setup
    store.update(A, name="FOH")
    hub.scan([{"uid": A, "data_port": "/dev/a", "console_port": None},
              {"uid": B, "data_port": "/dev/b", "console_port": None}])
    group = win.overlays
    first, second = group.get(A), group.get(B)
    assert first.label == "FOH" and second.label == "Keypad 89abcdef"
    assert first.stack_offset == 0 and second.stack_offset == first.height() + group.GAP
    # the keypad's overlay button only affects its own overlay
    hub.sessions[B].emit("overlay", op="hide")
    assert first.isVisible() and not second.isVisible()
    first.grab()                                   # paints with the keypad name in the header
    hub.remove_session(B)
    assert list(group.overlays) == [A] and first.label == ""


def test_rename_updates_picker_and_companion(setup):
    win, hub, _ = setup
    config = example_config()
    hub.scan([{"uid": A, "data_port": "/dev/a", "console_port": None}])
    hub.assign_layout(hub.sessions[A], config)
    hub.rename(A, "Front of house")
    assert "Front of house" in win.keypad_combo.itemText(0)
    names = [spec[0] for sat in hub.satellites.values() for spec in sat.devices.values()]
    assert names and all(n.startswith("CueKeys Front of house · ") for n in names)


def test_calibration_is_saved_per_keypad(setup, monkeypatch):
    from cuekeys.gui import calibration

    win, hub, store = setup
    hub.scan([{"uid": A, "data_port": "/dev/a", "console_port": None}])

    def fake_exec(dialog):
        dialog.gamma.set_value(240)
        dialog.done(calibration.QDialog.Accepted)
        return True

    monkeypatch.setattr(calibration.CalibrationDialog, "exec", fake_exec)
    before = dict(win.config["device"])
    win.calibrate_leds()
    assert store.get(A)["led_gamma"] == 2.4 and win.config["device"] == before


def test_cli_keypads(tmp_path, monkeypatch, capsys):
    store = KeypadStore(tmp_path / "keypads.json")
    monkeypatch.setattr(cli, "_store", lambda: store)
    monkeypatch.setattr(device, "list_keypads",
                        lambda ports=None: [{"uid": A, "data_port": "/dev/a", "console_port": "/dev/c"}])
    layout = tmp_path / "show.json"
    cfg.save(default_config(), layout)
    assert cli.main(["keypads", "rename", "e35b8c2b", "FOH"]) == 0
    assert cli.main(["keypads", "assign", "foh", str(layout)]) == 0
    assert store.get(A) == {"name": "FOH", "layout": str(layout)}
    capsys.readouterr()
    assert cli.main(["keypads"]) == 0
    out = capsys.readouterr().out
    assert A in out and "FOH" in out and "connected on /dev/a" in out and str(layout) in out
    assert cli.main(["keypads", "rename", "nope", "x"]) == 2
    assert cli.main(["keypads", "forget", A]) == 0 and store.get(A) == {}

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from cuekeys.examples import example_config  # noqa: E402
from cuekeys.runtime import Runtime  # noqa: E402

from .test_runtime import FakeLink, FakeSatellite  # noqa: E402


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    from cuekeys.gui.common import RuntimeSignals
    from cuekeys.gui.editor import MainWindow

    runtime = Runtime(example_config(), link=FakeLink(connected=False), satellite_factory=FakeSatellite)
    signals = RuntimeSignals(runtime)
    win = MainWindow(runtime, signals)
    monkeypatch.setattr(win, "_confirm_discard", lambda: True)  # no modal on close
    qtbot.addWidget(win)
    yield win
    win.overlay.close()
    runtime.stop()


def test_editor_edits_config(window):
    window.grid.select(4)
    press = window.slot_editors["press"]
    press.add({"type": "text", "text": "hi"})
    assert window.config["layers"][0]["keys"]["4"]["press"] == [{"type": "text", "text": "hi"}]
    assert window.dirty
    window.key_label.setText("Greeting")
    window._key_edited()
    assert window.config["layers"][0]["keys"]["4"]["label"] == "Greeting"


def test_layer_management(window):
    count = len(window.config["layers"])
    window.add_layer()
    assert len(window.config["layers"]) == count + 1
    window.layer_mode.setCurrentIndex(window.layer_mode.findData("companion"))
    assert window.config["layers"][-1]["mode"] == "companion"
    assert window.config["layers"][-1]["companion_id"].startswith("ck-")
    window.move_layer(-1)
    assert window.layer_index == count - 1


def test_overlay_renders_and_follows_layer(window, qtbot):
    overlay = window.overlay
    overlay.grab()  # exercises paintEvent
    window.runtime.select_layer(1)  # no keypad -> local preview
    assert window.runtime.layer == 1
    overlay.grab()


def test_action_form_updates_action(window):
    from cuekeys.gui.actions import ActionForm

    action = {"type": "midi_note", "note": 60, "velocity": 127, "mode": "momentary"}
    form = ActionForm(lambda: ["a"])
    form.set_action(action)
    form.editors["note"][1].setValue(64)
    assert action["note"] == 64
    form.editors["channel"][1].setText("3")
    assert action["channel"] == 3
    form.editors["channel"][1].setText("")
    assert "channel" not in action


def test_overlay_cycle_levels(window, qtbot):
    overlay = window.overlay
    window.config["overlay"]["opacity"] = 0.9
    overlay.apply_settings()
    overlay.show()
    seen = []
    for _ in range(4):
        overlay.run_command("cycle")
        seen.append(round(overlay.windowOpacity(), 1) if overlay.isVisible() else 0)
    assert seen == [0.6, 0.3, 0, 0.9]
    assert window.overlay_action.isChecked()
    overlay.run_command("hide")
    assert not overlay.isVisible() and not window.overlay_action.isChecked()


def test_companion_page_button_labels():
    from cuekeys.gui.common import companion_type_label

    assert companion_type_label({"type": "PAGENUM", "page": 4, "page_name": "CueKeys 1"}) == "CueKeys 1"
    assert companion_type_label({"type": "PAGENUM", "page": 4}) == "Page 4"
    assert companion_type_label({"type": "PAGENUM"}) == "Page"
    assert companion_type_label({"type": "PAGEUP"}) == "Page ▲"


def test_companion_location_badge_rules():
    from cuekeys.config import default_config
    from cuekeys.gui.common import cell_badge, cell_content

    config = default_config()
    config["layers"].append({"name": "C", "mode": "companion", "keys": {
        "7": {"press": [{"type": "text", "text": "x"}]}}})
    states = {
        (1, 3): {"type": "BUTTON", "text": "Go", "color": (0, 0, 0), "location": "5/0/0"},
        (1, 2): {"type": "PAGENUM", "text": "", "location": "5/1/0", "page_name": "CueKeys 2"},
        (1, 11): {"type": "BUTTON", "text": "", "color": (0, 0, 0), "location": "5/0/2"},
        (1, 15): {"type": "BUTTON", "text": "", "color": (0, 90, 0), "location": "5/0/3"},
        (1, 7): {"type": "BUTTON", "text": "Mine?", "location": "5/0/1"},
    }
    assert cell_badge(config, 1, 3, states) == "5/0/0"    # real (black) button with text
    assert cell_badge(config, 1, 15, states) == "5/0/3"   # coloured button without text
    assert cell_badge(config, 1, 2, states) is None       # page number button
    assert cell_badge(config, 1, 11, states) is None      # empty slot
    assert cell_badge(config, 1, 7, states) is None       # assigned locally
    assert cell_badge(config, 1, 0, states) is None       # bottom row is local
    label, color = cell_content(config, 1, 3, states)
    assert label == "Go" and color.name() != "#000000"   # drawn as a real button


def test_led_calibration_dialog(window):
    from PySide6.QtWidgets import QDialog

    from cuekeys.gui.calibration import CalibrationDialog

    link = FakeLink(connected=True)
    window.runtime.link = link
    dialog = CalibrationDialog(window.config, window.runtime)
    assert {"t": "led_test", "rgb": "#ffffff"} in link.sent          # white pattern shown at once
    dialog.channels[0].set_value(60)
    assert link.sent[-2] == {"t": "led_cal", "gamma": 2.2, "balance": [0.6, 1.0, 1.0]}
    dialog.done(QDialog.Accepted)
    assert window.config["device"]["led_balance"] == [0.6, 1.0, 1.0]
    assert link.sent[-1] == {"t": "led_test", "rgb": None}           # back to the layout

    link.sent.clear()
    dialog = CalibrationDialog(window.config, window.runtime)
    dialog.channels[2].set_value(10)
    dialog.done(QDialog.Rejected)                                     # cancel restores saved values
    assert link.sent[-1] == {"t": "led_cal", "gamma": 2.2, "balance": [0.6, 1.0, 1.0]}
    assert window.config["device"]["led_balance"] == [0.6, 1.0, 1.0]



def test_overlay_display_selection(window, monkeypatch):
    from PySide6.QtGui import QGuiApplication

    from cuekeys.gui.overlay import screen_names

    class FakeScreen:
        def __init__(self, name):
            self._name = name

        def name(self):
            return name_of[self]

    a, b, c = FakeScreen("Built-in"), FakeScreen("DELL"), FakeScreen("DELL")
    name_of = {a: "Built-in", b: "DELL", c: "DELL"}
    assert list(screen_names([a, b, c]).values()) == ["Built-in", "DELL", "DELL #2"]

    monkeypatch.setattr(QGuiApplication, "screens", staticmethod(lambda: [a, b, c]))
    monkeypatch.setattr(QGuiApplication, "primaryScreen", staticmethod(lambda: a))
    overlay = window.overlay
    settings = window.config["overlay"]
    settings["screens"] = "primary"
    assert overlay.target_screens() == [a]
    settings["screens"] = "all"
    assert overlay.target_screens() == [a, b, c]
    settings["screens"] = ["DELL #2", "Built-in"]
    assert overlay.target_screens() == [a, c]
    settings["screens"] = ["Unplugged monitor"]
    assert overlay.target_screens() == [a]        # falls back to the main display


def test_overlay_one_window_per_display(window):
    overlay = window.overlay
    window.config["overlay"]["screens"] = "all"
    overlay.apply_settings()
    overlay.show()
    assert len(overlay.windows) == len(QGuiApplication.screens())
    assert all(w.isVisible() for w in overlay.windows.values())
    overlay.run_command("hide")
    assert not any(w.isVisible() for w in overlay.windows.values())


def test_screen_picker_round_trip():
    from PySide6.QtCore import Qt

    from cuekeys.gui.settings import _ScreenPicker

    assert _ScreenPicker("all").value() == "all"
    picker = _ScreenPicker(["Old monitor"])                 # saved but not connected
    labels = [picker.list.item(i).text() for i in range(picker.list.count())]
    assert "Old monitor (not connected)" in labels
    assert picker.value() == ["Old monitor"]
    for i in range(picker.list.count()):
        picker.list.item(i).setCheckState(Qt.Unchecked)
    assert picker.value() == "primary"                      # nothing ticked -> main display


def test_marquee_offset_timing():
    from cuekeys.gui.overlay import marquee_offset

    # 60 px too wide at 30 px/s: hold 1.5 s, scroll for 2 s, hold 1.5 s, repeat
    assert marquee_offset(0, 60) == 0 and marquee_offset(1499, 60) == 0
    assert marquee_offset(2500, 60) == 30.0
    assert marquee_offset(3500, 60) == 60.0 and marquee_offset(4999, 60) == 60.0
    assert marquee_offset(5000, 60) == 0          # next cycle
    assert marquee_offset(9999, 0) == 0 and marquee_offset(9999, -5) == 0   # fits: never moves


def test_overlay_header_scrolls_only_when_too_long(window):
    overlay = window.overlay
    overlay.apply_settings()
    overlay.show()
    win = next(iter(overlay.windows.values()))
    runtime = window.runtime
    layer = window.config["layers"][runtime.layer]

    runtime.connected = True                      # no status text on a local layer
    layer["name"] = "A very long layer name that cannot possibly fit in the overlay header"
    win.grab()
    assert win.scrolling                          # the name is the only text: it scrolls
    layer["name"] = "Short"
    win.grab()
    assert not win.scrolling

    runtime.connected = False                     # status "keypad offline" appears
    win.grab()
    assert not win.scrolling                      # short name + status fit
    overlay.hide()
    assert not win.scrolling


def test_overlay_status_scrolls_but_layer_name_stays(window, monkeypatch):
    from cuekeys.gui import overlay as ov

    overlay = window.overlay
    overlay.apply_settings()
    overlay.show()
    win = next(iter(overlay.windows.values()))
    window.runtime.connected = False
    window.config["layers"][window.runtime.layer]["name"] = "Editing"
    drawn = []
    real = ov.OverlayWindow._draw_marquee
    monkeypatch.setattr(ov.OverlayWindow, "_draw_marquee",
                        lambda self, p, rect, text, *a: drawn.append(text) or real(self, p, rect, text, *a))
    win.grab()
    assert drawn == ["keypad offline"]            # only the status words go through the ticker

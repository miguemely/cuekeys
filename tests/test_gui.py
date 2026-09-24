import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from pmk_macro_manager.examples import example_config  # noqa: E402
from pmk_macro_manager.runtime import Runtime  # noqa: E402

from .test_runtime import FakeLink, FakeSatellite  # noqa: E402


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    from pmk_macro_manager.gui.common import RuntimeSignals
    from pmk_macro_manager.gui.editor import MainWindow

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
    assert window.config["layers"][-1]["companion_id"].startswith("pmk-")
    window.move_layer(-1)
    assert window.layer_index == count - 1


def test_overlay_renders_and_follows_layer(window, qtbot):
    overlay = window.overlay
    overlay.grab()  # exercises paintEvent
    window.runtime.select_layer(1)  # no keypad -> local preview
    assert window.runtime.layer == 1
    overlay.grab()


def test_action_form_updates_action(window):
    from pmk_macro_manager.gui.actions import ActionForm

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
    overlay.show()
    overlay.setWindowOpacity(0.9)
    seen = []
    for _ in range(4):
        overlay.run_command("cycle")
        seen.append(round(overlay.windowOpacity(), 1) if overlay.isVisible() else 0)
    assert seen == [0.6, 0.3, 0, 0.9]
    assert window.overlay_action.isChecked()
    overlay.run_command("hide")
    assert not overlay.isVisible() and not window.overlay_action.isChecked()


def test_companion_page_button_labels():
    from pmk_macro_manager.gui.common import companion_type_label

    assert companion_type_label({"type": "PAGENUM", "page": 4, "page_name": "PMK 1"}) == "PMK 1"
    assert companion_type_label({"type": "PAGENUM", "page": 4}) == "Page 4"
    assert companion_type_label({"type": "PAGENUM"}) == "Page"
    assert companion_type_label({"type": "PAGEUP"}) == "Page ▲"


def test_companion_location_badge_rules():
    from pmk_macro_manager.config import default_config
    from pmk_macro_manager.gui.common import cell_badge, cell_content

    config = default_config()
    config["layers"].append({"name": "C", "mode": "companion", "keys": {
        "7": {"press": [{"type": "text", "text": "x"}]}}})
    states = {
        (1, 3): {"type": "BUTTON", "text": "Go", "color": (0, 0, 0), "location": "5/0/0"},
        (1, 2): {"type": "PAGENUM", "text": "", "location": "5/1/0", "page_name": "PMK 2"},
        (1, 11): {"type": "BUTTON", "text": "", "color": (0, 0, 0), "location": "5/0/2"},
        (1, 15): {"type": "BUTTON", "text": "", "color": (0, 90, 0), "location": "5/0/3"},
        (1, 7): {"type": "BUTTON", "text": "Mine?", "location": "5/0/1"},
    }
    assert cell_badge(config, 1, 3, states) == "5/0/0"    # real (black) button with text
    assert cell_badge(config, 1, 15, states) == "5/0/3"   # coloured button without text
    assert cell_badge(config, 1, 2, states) is None       # page number button
    assert cell_badge(config, 1, 11, states) is None      # empty slot
    assert cell_badge(config, 1, 7, states) is None       # assigned locally
    assert cell_badge(config, 1, 0, states) is None       # bottom row is PMK's
    label, color = cell_content(config, 1, 3, states)
    assert label == "Go" and color.name() != "#000000"   # drawn as a real button


def test_led_calibration_dialog(window):
    from PySide6.QtWidgets import QDialog

    from pmk_macro_manager.gui.calibration import CalibrationDialog

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

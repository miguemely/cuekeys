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

import json
from pathlib import Path

import pytest

from pmk_macro_manager import config as cfg
from pmk_macro_manager.examples import example_config
from pmk_macro_manager.keycodes import parse_combo

ROOT = Path(__file__).resolve().parent.parent


def test_default_and_example_are_valid():
    assert cfg.validate(cfg.default_config()) == []
    assert cfg.validate(example_config()) == []


def test_every_default_action_is_valid():
    for kind in cfg.ACTION_SPECS:
        action = cfg.default_action(kind)
        if kind == "msc":
            continue  # go without cue is valid; checked below
        assert cfg.validate_action(action, kind) == [], kind
        assert cfg.describe_action(action)
    assert cfg.validate_action(cfg.default_action("msc"), "msc") == []


@pytest.mark.parametrize("action, fragment", [
    ({"type": "keys", "keys": ["NOPE"]}, "unknown key"),
    ({"type": "midi_note", "note": 200, "velocity": 1}, "out of range"),
    ({"type": "osc", "address": "x", "args": []}, "must start with /"),
    ({"type": "msc", "command": "fire", "device_id": 1, "command_format": "all"}, "needs a macro"),
    ({"type": "layer", "op": "goto", "layer": 5}, "out of range"),
    ({"type": "wat"}, "unknown action type"),
    ({"type": "overlay", "op": "cycle", "levels": [2]}, "levels"),
])
def test_validation_errors(action, fragment):
    errors = cfg.validate_action(action, "x", layer_count=2)
    assert any(fragment in e for e in errors), errors


def test_companion_rows_validation_and_region():
    config = cfg.default_config()
    layer = {"name": "C", "mode": "companion", "companion_rows": 5, "keys": {}}
    config["layers"].append(layer)
    assert any("companion_rows" in e for e in cfg.validate(config))
    layer["companion_rows"] = 3
    assert cfg.validate(config) == []
    # key 3 = top-left, key 0 = bottom-left
    assert cfg.in_companion_region(layer, 3) and not cfg.in_companion_region(layer, 0)
    assert not cfg.in_companion_region({"mode": "local"}, 3)


def test_validate_bad_key_number():
    config = cfg.default_config()
    config["layers"][0]["keys"]["16"] = {"press": []}
    assert any("invalid key number" in e for e in cfg.validate(config))


def test_prune_and_firmware_view():
    config = cfg.default_config()
    config["layers"][0]["keys"] = {"3": {"press": [], "hold": []},
                                   "1": {"press": [{"type": "text", "text": "x"}], "release": []}}
    pruned = cfg.prune(config)
    assert pruned["layers"][0]["keys"] == {"1": {"press": [{"type": "text", "text": "x"}]}}
    view = cfg.firmware_view(pruned)
    assert set(view) == {"version", "device", "layers"}  # no bridge secrets on the drive


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "layout.json"
    cfg.save(example_config(), path)
    assert cfg.load(path)["layers"] == cfg.prune(example_config())["layers"]


def test_merge_defaults_fills_sections():
    merged = cfg.merge_defaults({"layers": [{"name": "x", "keys": {}}], "device": {"brightness": 0.2}})
    assert merged["device"]["brightness"] == 0.2
    assert merged["device"]["hold_time_ms"] == 500
    assert "osc_targets" in merged["bridge"]


def test_parse_combo():
    assert parse_combo("ctrl+shift+s") == ["CONTROL", "SHIFT", "S"]
    assert parse_combo("Mod + 1") == ["PRIMARY", "ONE"]
    with pytest.raises(ValueError):
        parse_combo("ctrl+banana")


def test_shipped_firmware_config_matches_example():
    shipped = json.loads((ROOT / "firmware" / "config.json").read_text())
    assert shipped == cfg.firmware_view(cfg.prune(example_config()))

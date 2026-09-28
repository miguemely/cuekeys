# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
import json

import pytest

from cuekeys import devices

KEYBOW_GRID = [[3, 7, 11, 15], [2, 6, 10, 14], [1, 5, 9, 13], [0, 4, 8, 12]]


@pytest.fixture
def fresh(monkeypatch, tmp_path):
    """Isolate profile loading from the real user folder and environment."""
    monkeypatch.setattr(devices, "user_device_dir", lambda: tmp_path / "user")
    monkeypatch.setattr(devices, "_entry_point_dirs", lambda: [])
    monkeypatch.delenv("CUEKEYS_DEVICE_PATH", raising=False)
    devices.reload()
    yield tmp_path
    monkeypatch.undo()
    devices.reload()


def profile(**kw):
    data = {"id": "t", "grid": KEYBOW_GRID, "driver": "d"}
    data.update(kw)
    return devices.DeviceProfile(data)


def test_builtin_profiles(fresh):
    ids = set(devices.all_profiles())
    assert {"keybow2040", "rgbkeypad", "adafruit_macropad"} <= ids
    assert devices.load_errors() == []
    assert [p.id for p in devices.match_board("pimoroni_keybow2040")] == ["keybow2040"]


def test_keybow_geometry_matches_pmk_numbering():
    p = profile()
    assert p.key_to_cell(0) == (3, 0)   # bottom-left
    assert p.key_to_cell(3) == (0, 0)   # top-left
    assert p.key_to_cell(15) == (0, 3)  # top-right
    assert (p.satellite_index(3), p.satellite_index(15), p.satellite_index(0)) == (0, 3, 12)


@pytest.mark.parametrize("grid", [KEYBOW_GRID, [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11]],
                                  [[0, None, 1], [2, 3, 4]], [[0, 1, 2, 3, 4, 5, 6, 7]]])
def test_rotations_are_bijective_and_invertible(grid):
    p = profile(grid=grid)
    for rotation in (0, 90, 180, 270):
        rows, cols = p.display_size(rotation)
        cells = {p.key_to_cell(k, rotation) for k in p.keys()}
        assert len(cells) == p.num_keys
        assert all(0 <= r < rows and 0 <= c < cols for r, c in cells)
        for k in p.keys():
            assert p.cell_to_key(*p.key_to_cell(k, rotation), rotation) == k
            assert p.key_from_satellite(p.satellite_index(k, rotation), rotation) == k


def test_gaps_and_non_square():
    p = profile(grid=[[0, None, 1], [2, 3, 4]])
    assert (p.rows, p.cols, p.num_keys) == (2, 3, 5)
    assert p.cell_to_key(0, 1) is None
    assert p.display_size(90) == (3, 2)
    assert p.connector_side(90) == "right"


@pytest.mark.parametrize("grid, message", [
    ([[0, 1], [2]], "same length"),
    ([[0, 0]], "twice"),
    ([[0, 2]], "without gaps"),
    ([["a"]], "key numbers"),
    ([], "list of rows"),
])
def test_bad_grids(grid, message):
    with pytest.raises(devices.ProfileError, match=message):
        profile(grid=grid)


def test_user_plugins_override_and_bad_ones_are_reported(fresh, monkeypatch):
    user = fresh / "user"
    (user / "mypad").mkdir(parents=True)
    (user / "mypad" / "device.json").write_text(json.dumps(
        {"id": "mypad", "name": "My pad", "grid": [[0, 1, 2]], "driver": "mypad",
         "libraries": ["neopixel"]}))
    (user / "mypad" / "driver.py").write_text("class Hardware: pass\n")
    (user / "broken.json").write_text("{not json")
    extra = fresh / "extra"
    extra.mkdir()
    (extra / "keybow.json").write_text(json.dumps(
        {"id": "keybow2040", "name": "Overridden", "grid": KEYBOW_GRID, "driver": "pmk_keybow2040"}))
    monkeypatch.setenv("CUEKEYS_DEVICE_PATH", str(extra))
    profiles = devices.reload()
    assert profiles["mypad"].driver_file == user / "mypad" / "driver.py"
    assert profiles["mypad"].firmware_device() == {
        "profile": "mypad", "driver": "mypad", "driver_config": {}, "num_keys": 3,
        "led_gamma": 2.2, "led_balance": [1.0, 1.0, 1.0]}
    assert profiles["keybow2040"].name == "Overridden"          # $CUEKEYS_DEVICE_PATH wins
    assert any("broken.json" in e for e in devices.load_errors())


def test_profile_for_config_and_legacy(fresh):
    assert devices.profile_for({"device": {"profile": "adafruit_macropad"}}).num_keys == 12
    assert devices.profile_for({"device": {"hardware": "rgbkeypad"}}).id == "rgbkeypad"
    assert devices.profile_for({"device": {"profile": "missing"}}).id == devices.DEFAULT_PROFILE


def test_example_layout_adapts_to_each_device(fresh):
    from cuekeys import config as cfg
    from cuekeys.examples import example_config

    for profile_id in devices.all_profiles():
        config = example_config(profile_id)
        assert cfg.validate(config) == [], profile_id


def test_legacy_plugin_folder_is_still_searched(fresh, monkeypatch):
    legacy = fresh / "legacy"
    (legacy / "oldpad").mkdir(parents=True)
    (legacy / "oldpad" / "device.json").write_text(json.dumps(
        {"id": "oldpad", "grid": [[0, 1]], "driver": "keypad_keys"}))
    monkeypatch.setattr(devices, "legacy_device_dir", lambda: legacy)
    assert "oldpad" in devices.reload()

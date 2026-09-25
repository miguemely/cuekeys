from cuekeys import device


def test_install_firmware_replaces_pre_rename_folders(tmp_path):
    drive = tmp_path / "CIRCUITPY"
    (drive / "lib" / "pmkmacro").mkdir(parents=True)
    (drive / "lib" / "pmkmacro" / "engine.py").write_text("old")
    (drive / "lib" / "pmkdrivers").mkdir()
    (drive / "lib" / "pmk").mkdir()                     # Pimoroni's library: must stay
    (drive / "boot_out.txt").write_text("Adafruit CircuitPython 9\nBoard ID:pimoroni_keybow2040\n")
    device.install_firmware(drive, include_boot=False)
    lib = drive / "lib"
    assert not (lib / "pmkmacro").exists() and not (lib / "pmkdrivers").exists()
    assert (lib / "pmk").is_dir()
    assert (lib / "cuekeys_engine" / "engine.py").exists()
    assert (lib / "cuekeys_drivers" / "pmk_keybow2040.py").exists()
    assert (drive / "code.py").exists() and not (drive / "boot.py").exists()
    assert device.board_id(drive) == "pimoroni_keybow2040"

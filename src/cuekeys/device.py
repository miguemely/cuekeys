"""Find the keypad (CIRCUITPY drive + serial data port) and write files to it."""

import os
import shutil
import string
import sys
from pathlib import Path

from . import config as cfg
from . import devices

DRIVE_LABEL = "CIRCUITPY"
CONFIG_NAME = "config.json"


# ------------------------------------------------------------------ drives
def _windows_drives():
    import ctypes

    kernel32 = ctypes.windll.kernel32
    bitmask = kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not bitmask & (1 << i):
            continue
        root = "%s:\\" % letter
        name = ctypes.create_unicode_buffer(261)
        ok = kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), name, 261,
                                            None, None, None, None, 0)
        if ok and name.value.upper().startswith(DRIVE_LABEL):
            yield Path(root)


def _posix_mounts():
    mounts = Path("/proc/mounts")
    if mounts.exists():
        for line in mounts.read_text().splitlines():
            parts = line.split()
            if len(parts) > 1:
                # /proc/mounts escapes spaces as \040
                yield Path(parts[1].replace("\\040", " "))
    for base in ("/Volumes", "/media", "/run/media", "/mnt"):
        root = Path(base)
        if not root.is_dir():
            continue
        try:
            for entry in root.iterdir():
                yield entry
                if base in ("/media", "/run/media") and entry.is_dir() \
                        and not entry.name.upper().startswith(DRIVE_LABEL):
                    # /media/<user>/CIRCUITPY
                    try:
                        yield from entry.iterdir()
                    except OSError:
                        pass
        except OSError:
            pass


def find_drives():
    """Return a de-duplicated list of mounted CIRCUITPY drive paths."""
    if sys.platform == "win32":
        candidates = _windows_drives()
    else:
        candidates = (p for p in _posix_mounts() if p.name.upper().startswith(DRIVE_LABEL))
    seen, out = set(), []
    for path in candidates:
        try:
            real = path.resolve()
        except OSError:
            continue
        if real not in seen and (real / "boot_out.txt").exists():
            seen.add(real)
            out.append(real)
    return out


def board_info(drive):
    try:
        return (Path(drive) / "boot_out.txt").read_text(errors="replace").splitlines()[0]
    except (OSError, IndexError):
        return ""


def pick_drive(drive=None, uid=None):
    """The CIRCUITPY drive to use: ``drive`` if given, else the one of keypad ``uid``,
    else the only one connected."""
    if drive:
        path = Path(drive)
        if not path.is_dir():
            raise FileNotFoundError("drive not found: %s" % drive)
        return path
    drives = find_drives()
    if uid:
        for candidate in drives:
            if (board_uid(candidate) or "").upper() == uid.upper():
                return candidate
        raise FileNotFoundError("the CIRCUITPY drive of keypad %s isn't mounted" % uid)
    if not drives:
        raise FileNotFoundError("no CIRCUITPY drive found - is the keypad plugged in?")
    if len(drives) > 1:
        raise RuntimeError("several CIRCUITPY drives found, pick one with --keypad or --drive: %s"
                           % ", ".join("%s (%s)" % (d, board_uid(d)) for d in drives))
    return drives[0]


# ------------------------------------------------------------------ serial
def list_keypads(ports=None):
    """Connected CircuitPython keypads: ``[{"uid", "data_port", "console_port"}]``.

    CircuitPython uses the chip's unique id as the USB serial number, and with
    ``usb_cdc`` console+data enabled each keypad shows two serial ports that
    share it. Linux/macOS name the interfaces ("CircuitPython CDC2 data");
    Windows doesn't, so there the data port is the second one.
    """
    if ports is None:
        try:
            from serial.tools import list_ports
        except ImportError:
            return []
        ports = list(list_ports.comports())
    groups = {}
    for port in ports:
        text = " ".join(str(x) for x in (port.manufacturer, port.product, port.description, port.interface))
        if "circuitpython" in text.lower() or port.vid in (0x239A, 0x16D0, 0x2E8A):
            uid = (port.serial_number or port.hwid or port.device).upper()
            groups.setdefault(uid, []).append(port)
    keypads = []
    for uid, group in sorted(groups.items()):
        group.sort(key=lambda p: (p.location or "", p.device))
        data = [p for p in group if p.interface and "data" in p.interface.lower()]
        if data:
            data_port = data[0].device
        elif len(group) >= 2:
            data_port = group[-1].device
        else:
            continue  # console only: boot.py hasn't enabled the data port yet (needs a replug)
        console = [p.device for p in group if p.device != data_port]
        keypads.append({"uid": uid, "data_port": data_port, "console_port": console[0] if console else None})
    return keypads


def find_data_port():
    """The data port of the first connected keypad, or None."""
    keypads = list_keypads()
    return keypads[0]["data_port"] if keypads else None


# ------------------------------------------------------------------ files
def firmware_source():
    """Directory holding code.py/boot.py/lib (wheel or source checkout)."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "firmware", here.parent.parent / "firmware"):
        if (candidate / "code.py").exists():
            return candidate
    raise FileNotFoundError("bundled firmware not found")


def _write(path, data):
    with open(path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def deploy_config(config, drive=None, uid=None, keypad=None):
    """Write the firmware part of ``config`` to a keypad. Returns the path.

    ``uid`` picks that keypad's drive; ``keypad`` is its settings (LED calibration).
    CircuitPython auto-reloads when the file changes.
    """
    target = pick_drive(drive, uid) / CONFIG_NAME
    _write(target, cfg.dumps(cfg.firmware_view(cfg.prune(config), keypad)).encode("utf-8"))
    return target


def read_device_config(drive=None, uid=None):
    import json

    with open(pick_drive(drive, uid) / CONFIG_NAME, encoding="utf-8") as f:
        return cfg.merge_defaults(json.load(f))


def _sync_package(src_dir, dst_dir, prune=True):
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for file in sorted(src_dir.glob("*.py")):
        _write(dst_dir / file.name, file.read_bytes())
        copied.append(dst_dir / file.name)
    if prune:
        for stale in dst_dir.glob("*.py"):
            if not (src_dir / stale.name).exists():
                stale.unlink()
    return copied


def install_firmware(drive=None, include_boot=True, profile=None, uid=None):
    """Copy code.py, boot.py, lib/cuekeys_engine and lib/cuekeys_drivers to the drive.

    A plugin profile's own ``driver.py`` is installed as
    ``lib/cuekeys_drivers/<driver>.py``. Returns the copied paths.
    """
    src = firmware_source()
    dst = pick_drive(drive, uid)
    copied = []
    names = ["code.py"] + (["boot.py"] if include_boot else [])
    for name in names:
        _write(dst / name, (src / name).read_bytes())
        copied.append(dst / name)
    copied += _sync_package(src / "lib" / "cuekeys_engine", dst / "lib" / "cuekeys_engine")
    # Firmware folders from before the rename to CueKeys; code.py no longer imports them.
    for legacy in ("pmkmacro", "pmkdrivers"):
        if (dst / "lib" / legacy).is_dir():
            shutil.rmtree(dst / "lib" / legacy)
    # Don't prune drivers: plugin drivers installed earlier must survive.
    copied += _sync_package(src / "lib" / "cuekeys_drivers", dst / "lib" / "cuekeys_drivers", prune=False)
    if profile is not None and profile.driver_file is not None:
        target = dst / "lib" / "cuekeys_drivers" / (profile.driver + ".py")
        _write(target, profile.driver_file.read_bytes())
        copied.append(target)
    if not (dst / CONFIG_NAME).exists():
        example = src / CONFIG_NAME
        if example.exists():
            shutil.copyfile(example, dst / CONFIG_NAME)
            copied.append(dst / CONFIG_NAME)
    return copied


def required_libraries(profile):
    return ["adafruit_hid"] + [lib for lib in profile.libraries if lib != "adafruit_hid"]


def missing_libraries(drive=None, profile=None, uid=None):
    profile = profile or devices.get_profile(devices.DEFAULT_PROFILE)
    lib = pick_drive(drive, uid) / "lib"
    missing = []
    for name in required_libraries(profile):
        if not any((lib / n).exists() for n in (name, name + ".py", name + ".mpy")):
            missing.append(name)
    return missing


def _boot_out_field(drive, field):
    try:
        text = (Path(drive) / "boot_out.txt").read_text(errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith(field + ":"):
            return line.split(":", 1)[1].strip()
    return None


def board_uid(drive):
    """The keypad's unique id from boot_out.txt (matches its USB serial number)."""
    uid = _boot_out_field(drive, "UID")
    return uid.upper() if uid else None


def board_id(drive):
    """CircuitPython board id from boot_out.txt (e.g. "pimoroni_keybow2040")."""
    return _boot_out_field(drive, "Board ID")

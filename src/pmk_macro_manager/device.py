"""Find the keypad (CIRCUITPY drive + serial data port) and write files to it."""

import os
import shutil
import string
import sys
from pathlib import Path

from . import config as cfg

DRIVE_LABEL = "CIRCUITPY"
CONFIG_NAME = "config.json"

# Libraries the firmware needs in CIRCUITPY/lib, per hardware.
REQUIRED_LIBS = {
    "keybow2040": ["pmk", "adafruit_hid", "adafruit_is31fl3731"],
    "rgbkeypad": ["pmk", "adafruit_hid", "adafruit_dotstar"],
}


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


def pick_drive(drive=None):
    if drive:
        path = Path(drive)
        if not path.is_dir():
            raise FileNotFoundError("drive not found: %s" % drive)
        return path
    drives = find_drives()
    if not drives:
        raise FileNotFoundError("no CIRCUITPY drive found - is the keypad plugged in?")
    if len(drives) > 1:
        raise RuntimeError("several CIRCUITPY drives found, pick one with --drive: %s"
                           % ", ".join(str(d) for d in drives))
    return drives[0]


# ------------------------------------------------------------------ serial
def find_data_port():
    """Return the device name of the keypad's usb_cdc *data* port, or None."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    ports = list(list_ports.comports())

    # Linux/macOS expose interface names ("CircuitPython CDC2 data").
    for port in ports:
        if port.interface and "data" in port.interface.lower():
            return port.device

    # Windows: group CircuitPython ports by serial number; with console+data
    # enabled the data port is the second interface.
    groups = {}
    for port in ports:
        text = " ".join(str(x) for x in (port.manufacturer, port.product, port.description))
        if "circuitpython" in text.lower() or port.vid in (0x239A, 0x16D0, 0x2E8A):
            groups.setdefault(port.serial_number or port.hwid, []).append(port)
    for group in groups.values():
        if len(group) >= 2:
            group.sort(key=lambda p: (p.location or "", p.device))
            return group[-1].device
    return None


# ------------------------------------------------------------------ files
def firmware_source():
    """Directory holding code.py/boot.py/lib/pmkmacro (wheel or source checkout)."""
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


def deploy_config(config, drive=None):
    """Write the firmware part of ``config`` to the keypad. Returns the path.

    CircuitPython auto-reloads when the file changes.
    """
    target = pick_drive(drive) / CONFIG_NAME
    _write(target, cfg.dumps(cfg.firmware_view(cfg.prune(config))).encode("utf-8"))
    return target


def read_device_config(drive=None):
    import json

    with open(pick_drive(drive) / CONFIG_NAME, encoding="utf-8") as f:
        return cfg.merge_defaults(json.load(f))


def install_firmware(drive=None, include_boot=True):
    """Copy code.py, boot.py and lib/pmkmacro to the drive. Returns copied paths."""
    src = firmware_source()
    dst = pick_drive(drive)
    copied = []
    names = ["code.py"] + (["boot.py"] if include_boot else [])
    for name in names:
        _write(dst / name, (src / name).read_bytes())
        copied.append(dst / name)
    lib_src = src / "lib" / "pmkmacro"
    lib_dst = dst / "lib" / "pmkmacro"
    lib_dst.mkdir(parents=True, exist_ok=True)
    for file in sorted(lib_src.glob("*.py")):
        _write(lib_dst / file.name, file.read_bytes())
        copied.append(lib_dst / file.name)
    for stale in lib_dst.glob("*.py"):
        if not (lib_src / stale.name).exists():
            stale.unlink()
    if not (dst / CONFIG_NAME).exists():
        example = src / CONFIG_NAME
        if example.exists():
            shutil.copyfile(example, dst / CONFIG_NAME)
            copied.append(dst / CONFIG_NAME)
    return copied


def missing_libraries(drive=None, hardware="keybow2040"):
    lib = pick_drive(drive) / "lib"
    missing = []
    for name in REQUIRED_LIBS.get(hardware, REQUIRED_LIBS["keybow2040"]):
        if not any((lib / n).exists() for n in (name, name + ".py", name + ".mpy")):
            missing.append(name)
    return missing

#!/usr/bin/env python3
"""Build a drag-and-drop firmware zip for the CIRCUITPY drive.

The zip contains code.py, boot.py, config.json, lib/pmkmacro, lib/pmkdrivers and
the third-party libraries the built-in device drivers need:

* pmk                      (pimoroni/pmk-circuitpython)
* adafruit_hid             (Adafruit bundle)
* adafruit_is31fl3731      (Keybow 2040 LEDs)
* adafruit_dotstar + adafruit_pixelbuf (Pico RGB Keypad LEDs)
* adafruit_bus_device      (dependency of the LED drivers)
* neopixel                 (generic keypad_keys / keypad_matrix drivers)

The Adafruit "py" bundle is used so the zip works on any CircuitPython version.

    python scripts/build_firmware_bundle.py [--pmk-ref main] [--out dist]
"""

import argparse
import io
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADAFRUIT_RELEASES = "https://api.github.com/repos/adafruit/Adafruit_CircuitPython_Bundle/releases/latest"
PMK_ARCHIVE = "https://codeload.github.com/pimoroni/pmk-circuitpython/zip/{ref}"
ADAFRUIT_LIBS = ["adafruit_hid", "adafruit_is31fl3731", "adafruit_dotstar", "adafruit_pixelbuf",
                 "adafruit_bus_device", "neopixel"]
# Each bundled library's own license travels with it (MIT requires its notice).
LIBRARY_LICENSES = {
    "adafruit_hid": "https://raw.githubusercontent.com/adafruit/Adafruit_CircuitPython_HID/main/LICENSE",
    "adafruit_is31fl3731":
        "https://raw.githubusercontent.com/adafruit/Adafruit_CircuitPython_IS31FL3731/main/LICENSE",
    "adafruit_dotstar": "https://raw.githubusercontent.com/adafruit/Adafruit_CircuitPython_DotStar/main/LICENSE",
    "adafruit_pixelbuf": "https://raw.githubusercontent.com/adafruit/Adafruit_CircuitPython_Pixelbuf/main/LICENSE",
    "adafruit_bus_device":
        "https://raw.githubusercontent.com/adafruit/Adafruit_CircuitPython_BusDevice/main/LICENSE",
    "neopixel": "https://raw.githubusercontent.com/adafruit/Adafruit_CircuitPython_NeoPixel/main/LICENSE",
}


def fetch(url):
    headers = {"User-Agent": "pmk-macro-manager-build"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = "Bearer " + token
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as resp:
        return resp.read()


def version():
    text = (ROOT / "src" / "pmk_macro_manager" / "__init__.py").read_text()
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def adafruit_bundle(source):
    if source and Path(source).exists():
        return Path(source).read_bytes()
    if source:
        return fetch(source)
    release = json.loads(fetch(ADAFRUIT_RELEASES))
    for asset in release["assets"]:
        if re.match(r"adafruit-circuitpython-bundle-py-\d+\.zip$", asset["name"]):
            print("using %s" % asset["name"])
            return fetch(asset["browser_download_url"])
    sys.exit("py bundle not found in latest Adafruit release")


def extract_libs(zip_bytes, names, lib_dir, prefix_re):
    found = set()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            match = re.match(prefix_re, info.filename)
            if not match or info.is_dir():
                continue
            rel = info.filename[match.end():]
            top = rel.split("/")[0]
            name = top[:-3] if top.endswith(".py") else top
            if name not in names:
                continue
            target = lib_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
            found.add(name)
    missing = set(names) - found
    if missing:
        sys.exit("libraries not found: %s" % ", ".join(sorted(missing)))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT / "dist"))
    parser.add_argument("--pmk-ref", default=os.environ.get("PMK_REF", "main"),
                        help="git ref of pimoroni/pmk-circuitpython")
    parser.add_argument("--adafruit-bundle", default=os.environ.get("ADAFRUIT_BUNDLE"),
                        help="path or URL of an adafruit-circuitpython-bundle-py zip (default: latest)")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "CIRCUITPY"
        lib = stage / "lib"
        lib.mkdir(parents=True)
        fw = ROOT / "firmware"
        for name in ("code.py", "boot.py", "config.json"):
            shutil.copy(fw / name, stage / name)
        for package in ("pmkmacro", "pmkdrivers"):
            shutil.copytree(fw / "lib" / package, lib / package,
                            ignore=shutil.ignore_patterns("__pycache__"))

        extract_libs(adafruit_bundle(args.adafruit_bundle), ADAFRUIT_LIBS, lib,
                     r"adafruit-circuitpython-bundle-py-\d+/lib/")
        pmk_zip = fetch(PMK_ARCHIVE.format(ref=args.pmk_ref))
        extract_libs(pmk_zip, ["pmk"], lib, r"pmk-circuitpython-[^/]+/lib/")

        licenses = stage / "licenses"
        licenses.mkdir()
        for name, url in LIBRARY_LICENSES.items():
            (licenses / ("%s-LICENSE.txt" % name)).write_bytes(fetch(url))
        with zipfile.ZipFile(io.BytesIO(pmk_zip)) as zf:
            pmk_license = next(n for n in zf.namelist() if re.match(r"pmk-circuitpython-[^/]+/LICENSE$", n))
            (licenses / "pmk-LICENSE.txt").write_bytes(zf.read(pmk_license))
        shutil.copy(ROOT / "LICENSE", stage / "LICENSE.txt")
        shutil.copy(ROOT / "THIRD_PARTY_NOTICES.md", licenses / "THIRD_PARTY_NOTICES.md")

        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        target = out / ("pmk-macro-manager-firmware-%s.zip" % version())
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(stage))
        print("wrote %s" % target)


if __name__ == "__main__":
    main()

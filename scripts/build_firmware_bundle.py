#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
"""Build a drag-and-drop firmware zip for the CIRCUITPY drive.

The zip contains code.py, boot.py, config.json, lib/cuekeys_engine, lib/cuekeys_drivers and
the third-party libraries the built-in device drivers need:

* pmk                      (pimoroni/pmk-circuitpython)
* adafruit_hid             (Adafruit bundle)
* adafruit_is31fl3731      (Keybow 2040 LEDs)
* adafruit_dotstar + adafruit_pixelbuf (Pico RGB Keypad LEDs)
* adafruit_bus_device      (dependency of the LED drivers)
* neopixel                 (generic keypad_keys / keypad_matrix drivers)

The Adafruit "py" bundle is used so the zip works on any CircuitPython version.

    python scripts/build_firmware_bundle.py [--pmk-ref main] [--out dist]

Also writes a CycloneDX SBOM of the bundle, inside the zip (licenses/sbom.cdx.json)
and next to it (cuekeys-firmware-<version>.cdx.json).
"""

import argparse
import io
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sbom  # noqa: E402

ADAFRUIT_RELEASES = "https://api.github.com/repos/adafruit/Adafruit_CircuitPython_Bundle/releases/latest"
PMK_ARCHIVE = "https://codeload.github.com/pimoroni/pmk-circuitpython/zip/{ref}"
PMK_COMMIT = "https://api.github.com/repos/pimoroni/pmk-circuitpython/commits/{ref}"
ADAFRUIT_REPOS = {"adafruit_hid": "Adafruit_CircuitPython_HID",
                  "adafruit_is31fl3731": "Adafruit_CircuitPython_IS31FL3731",
                  "adafruit_dotstar": "Adafruit_CircuitPython_DotStar",
                  "adafruit_pixelbuf": "Adafruit_CircuitPython_Pixelbuf",
                  "adafruit_bus_device": "Adafruit_CircuitPython_BusDevice",
                  "neopixel": "Adafruit_CircuitPython_NeoPixel"}
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
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_EXTRACT_BYTES = 128 * 1024 * 1024


def fetch(url):
    headers = {"User-Agent": "cuekeys-build"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and urllib.parse.urlsplit(url).hostname == "api.github.com":
        headers["Authorization"] = "Bearer " + token
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as resp:
        length = resp.headers.get("Content-Length")
        if length and int(length) > MAX_DOWNLOAD_BYTES:
            raise ValueError("download is too large: %s" % url)
        chunks, size = [], 0
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_DOWNLOAD_BYTES:
                raise ValueError("download is too large: %s" % url)
            chunks.append(chunk)
        return b"".join(chunks)


def version():
    text = (ROOT / "src" / "cuekeys" / "__init__.py").read_text()
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
    extracted = 0
    root = Path(lib_dir).resolve()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            match = re.match(prefix_re, info.filename)
            if not match or info.is_dir():
                continue
            rel = info.filename[match.end():]
            parts = PurePosixPath(rel).parts
            if (not parts or PurePosixPath(rel).is_absolute() or PureWindowsPath(rel).drive
                    or ".." in parts or "\\" in rel or "\x00" in rel):
                raise ValueError("unsafe archive path: %s" % info.filename)
            top = parts[0]
            name = top[:-3] if top.endswith(".py") else top
            if name not in names:
                continue
            if info.file_size > MAX_MEMBER_BYTES or extracted + info.file_size > MAX_EXTRACT_BYTES:
                raise ValueError("archive contents are too large")
            target = (root / Path(*parts)).resolve()
            if target != root and root not in target.parents:
                raise ValueError("unsafe archive path: %s" % info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
            extracted += info.file_size
            found.add(name)
    missing = set(names) - found
    if missing:
        sys.exit("libraries not found: %s" % ", ".join(sorted(missing)))


def lib_version(lib_dir, name):
    """``__version__`` of a bundled library (Adafruit fills it in at release)."""
    candidates = [lib_dir / (name + ".py"), lib_dir / name / "__init__.py"]
    candidates += sorted((lib_dir / name).glob("*.py")) if (lib_dir / name).is_dir() else []
    for path in candidates:
        if path.is_file():
            match = re.search(r"""__version__\s*=\s*["']([^"']+)""", path.read_text(errors="replace"))
            if match and "0.0.0-auto" not in match.group(1):
                return match.group(1)
    return None


def pmk_commit(ref):
    try:
        return json.loads(fetch(PMK_COMMIT.format(ref=ref)))["sha"]
    except Exception as err:  # noqa: BLE001 - the SBOM then records the ref
        print("can't resolve pmk-circuitpython %s to a commit (%s)" % (ref, err))
        return None


def firmware_sbom(lib_dir, bundle_tag, pmk_ref, pmk_sha):
    root = sbom.component("cuekeys-firmware", version(), [sbom.PROJECT_LICENSE],
                          "pkg:github/miguemely/cuekeys@v%s#firmware" % version(), ctype="firmware",
                          supplier="Miguel Rodriguez",
                          description="code.py, boot.py, cuekeys_engine and cuekeys_drivers for CircuitPython")
    components = []
    for name in ADAFRUIT_LIBS:
        ver = lib_version(lib_dir, name) or bundle_tag or "unknown"
        repo = ADAFRUIT_REPOS[name]
        comp = sbom.component(name, ver, ["MIT"], "pkg:github/adafruit/%s@%s" % (repo.lower(), ver),
                              supplier="Adafruit Industries")
        if bundle_tag:
            comp["properties"] = [{"name": "cuekeys:adafruit-bundle", "value": bundle_tag}]
        components.append(comp)
    components.append(sbom.component("pmk", pmk_sha or pmk_ref, ["MIT"],
                                     "pkg:github/pimoroni/pmk-circuitpython@%s" % (pmk_sha or pmk_ref),
                                     supplier="Pimoroni"))
    deps = {root["bom-ref"]: [c["bom-ref"] for c in components]}
    return sbom.bom(root, components, deps, {"cuekeys:target": "circuitpython"})


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
        for package in ("cuekeys_engine", "cuekeys_drivers"):
            shutil.copytree(fw / "lib" / package, lib / package,
                            ignore=shutil.ignore_patterns("__pycache__"))

        bundle_zip = adafruit_bundle(args.adafruit_bundle)
        extract_libs(bundle_zip, ADAFRUIT_LIBS, lib, r"adafruit-circuitpython-bundle-py-\d+/lib/")
        with zipfile.ZipFile(io.BytesIO(bundle_zip)) as zf:
            tag = next((m.group(1) for m in (re.match(r"adafruit-circuitpython-bundle-py-(\d+)/", n)
                                             for n in zf.namelist()) if m), None)
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
        doc = firmware_sbom(lib, tag, args.pmk_ref, pmk_commit(args.pmk_ref))
        sbom.write(doc, licenses / "sbom.cdx.json")

        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        target = out / ("cuekeys-firmware-%s.zip" % version())
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(stage))
        print("wrote %s" % target)
        print("wrote %s" % sbom.write(doc, out / ("cuekeys-firmware-%s.cdx.json" % version())))


if __name__ == "__main__":
    main()

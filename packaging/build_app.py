#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Build the stand-alone CueKeys desktop app with PyInstaller for this OS.

    pip install -e ".[build]"
    python packaging/build_app.py [--arch universal2|arm64|x86_64]   # --arch: macOS only

Output: dist/cuekeys-<version>-<os>-<arch>.zip and its CycloneDX SBOM,
dist/cuekeys-<version>-<os>-<arch>.cdx.json (scripts/sbom.py --app).

The build is defined in packaging/cuekeys.spec (which also trims unused Qt
modules). macOS universal2 builds need a universal2 Python (python.org
installer) and universal2 wheels (PySide6 ships them).
"""

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "CueKeys"


def host_arch():
    machine = platform.machine().lower()
    return {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(machine, machine)


def folder_size(path):
    return sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file() and not f.is_symlink())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arch", help="macOS target architecture: universal2, arm64 or x86_64")
    args = parser.parse_args()

    version = re.search(r'__version__ = "([^"]+)"', (ROOT / "src/cuekeys/__init__.py").read_text()).group(1)
    os_name = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")
    arch = host_arch()
    env = dict(os.environ)
    if args.arch:
        if os_name != "macos":
            sys.exit("--arch is only supported on macOS; build on a machine of the target architecture")
        env["CUEKEYS_TARGET_ARCH"] = arch = args.arch

    subprocess.check_call([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                           "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
                           str(ROOT / "packaging" / "cuekeys.spec")], cwd=ROOT, env=env)

    dist = ROOT / "dist"
    built = dist / (NAME + ".app") if os_name == "macos" else dist / NAME
    archive = dist / ("cuekeys-%s-%s-%s" % (version, os_name, arch))
    if os_name == "macos":
        # ditto keeps the framework symlinks that zipfile would flatten.
        subprocess.check_call(["ditto", "-c", "-k", "--keepParent", str(built), str(archive) + ".zip"])
    else:
        shutil.make_archive(str(archive), "zip", root_dir=built.parent, base_dir=built.name)
    zip_path = Path(str(archive) + ".zip")
    print("wrote %s (app %.1f MB, zip %.1f MB)" % (zip_path, folder_size(built) / 2**20,
                                                   zip_path.stat().st_size / 2**20))
    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "sbom.py"), "--app",
                           "--target", "%s-%s" % (os_name, arch), "--out", str(archive) + ".cdx.json"])


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build a stand-alone desktop app with PyInstaller for the current OS.

    pip install -e ".[build]"
    python packaging/build_app.py

Output: dist/pmk-macro-manager-<version>-<os>-<arch>.zip
"""

import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "PMK Macro Manager"


def main():
    version = re.search(r'__version__ = "([^"]+)"',
                        (ROOT / "src/pmk_macro_manager/__init__.py").read_text()).group(1)
    os_name = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")
    arch = platform.machine().lower().replace("amd64", "x86_64").replace("aarch64", "arm64")
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", NAME,
        # PyInstaller >= 6 accepts ':' as the separator on every platform.
        "--add-data", "%s:pmk_macro_manager/firmware" % (ROOT / "firmware"),
        "--add-data", "%s:pmk_macro_manager/devices/builtin"
        % (ROOT / "src" / "pmk_macro_manager" / "devices" / "builtin"),
        "--collect-submodules", "pmk_macro_manager",
        "--osx-bundle-identifier", "io.gitlab.pmk-macro-manager",
        str(ROOT / "packaging" / "launcher.py"),
    ], cwd=ROOT)
    dist = ROOT / "dist"
    built = dist / (NAME + ".app") if os_name == "macos" else dist / NAME
    archive = dist / ("pmk-macro-manager-%s-%s-%s" % (version, os_name, arch))
    if os_name == "macos":
        # ditto keeps the framework symlinks that zipfile would flatten.
        subprocess.check_call(["ditto", "-c", "-k", "--keepParent", str(built), str(archive) + ".zip"])
    else:
        shutil.make_archive(str(archive), "zip", root_dir=built.parent, base_dir=built.name)
    print("wrote %s.zip" % archive)


if __name__ == "__main__":
    main()

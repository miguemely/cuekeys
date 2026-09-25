# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# PyInstaller spec for the CueKeys desktop app (all platforms).
#
# Driven by packaging/build_app.py. Environment:
#   CUEKEYS_TARGET_ARCH  macOS only: "universal2", "arm64" or "x86_64" (default: host arch)
#
# CueKeys only uses QtCore, QtGui and QtWidgets. PyInstaller's Qt hooks also
# collect plugins that drag in large unused Qt modules (the PDF image plugin
# pulls QtPdf, the virtual-keyboard input plugin pulls QtQuick/QtQml, the SVG
# icon engine pulls QtSvg, ...). They're dropped from the file lists below,
# before COLLECT/BUNDLE, so macOS code signing still covers the final bundle.

import os
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - SPECPATH is provided by PyInstaller
NAME = "CueKeys"
TARGET_ARCH = os.environ.get("CUEKEYS_TARGET_ARCH") or None

# Python modules the app never needs.
EXCLUDES = [
    "tkinter", "unittest", "pydoc", "doctest", "pdb", "lib2to3",
    "ssl", "_ssl", "_hashlib",          # only plain-HTTP calls (Companion); drops libssl/libcrypto
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.QtSvg",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtVirtualKeyboard",
]

# Qt libraries, plugins and data that come in through plugins rather than imports.
DROP = re.compile(
    r"(Qt6?(Pdf|Quick|Qml\w*|VirtualKeyboard\w*|Network|Svg|OpenGL\w*|WaylandClient|WaylandEgl\w*)\b"
    r"|[/\\]imageformats[/\\]\w*(pdf|svg)"
    r"|[/\\]iconengines[/\\]"
    r"|[/\\]platforminputcontexts[/\\]\w*virtualkeyboard"
    r"|[/\\](tls|networkinformation|qmltooling|wayland-\w+)[/\\]"
    r"|[/\\]platforms[/\\]\w*wayland"      # Linux: CueKeys runs on XWayland (see gui/app.py)
    r"|[/\\]translations[/\\]"             # Qt's own UI translations; the app is English
    r"|libcrypto|libssl)",
    re.IGNORECASE,
)

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=[
        (str(ROOT / "firmware"), "cuekeys/firmware"),
        (str(ROOT / "src" / "cuekeys" / "devices" / "builtin"), "cuekeys/devices/builtin"),
        # License texts ship with the binaries (ours, and LGPL-3.0 for PySide6/Qt).
        (str(ROOT / "LICENSE"), "."),
        (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
        (str(ROOT / "COMMERCIAL-LICENSE.md"), "."),
        (str(ROOT / "licenses"), "licenses"),
    ],
    hiddenimports=collect_submodules("cuekeys"),
    excludes=EXCLUDES,
    noarchive=False,
)

dropped = [entry[0] for entry in a.binaries + a.datas if DROP.search(entry[0])]
a.binaries = [entry for entry in a.binaries if not DROP.search(entry[0])]
a.datas = [entry for entry in a.datas if not DROP.search(entry[0])]
print("cuekeys.spec: dropped %d unused Qt/SSL files" % len(dropped))

pyz = PYZ(a.pure)  # noqa: F821
strip = sys.platform.startswith("linux")
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=False,
    strip=strip,
    upx=False,
    target_arch=TARGET_ARCH,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=strip, upx=False, name=NAME)  # noqa: F821

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name=NAME + ".app",
        bundle_identifier="io.github.miguemely.cuekeys",
        info_plist={"NSHighResolutionCapable": True, "LSMinimumSystemVersion": "13.0"},
    )

# Third-party notices

CueKeys's own code is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE).
The components below are **not** covered by that license. Each keeps its own license, and nothing in
this project restricts your rights under those licenses.

## Distributed with the desktop app and Python package

| Component | License | Source | Notes |
|---|---|---|---|
| PySide6, Shiboken6 and Qt 6 | LGPL-3.0-only (also GPL-2.0/3.0) | https://code.qt.io/cgit/pyside/pyside-setup.git, https://code.qt.io | Used as unmodified, dynamically loaded libraries |
| pyserial | BSD-3-Clause | https://github.com/pyserial/pyserial | |
| Python runtime (desktop builds only) | PSF-2.0 | https://www.python.org | Bundled by PyInstaller |
| PyInstaller bootloader (desktop builds only) | GPL-2.0 with bootloader exception | https://github.com/pyinstaller/pyinstaller | The exception allows bundling apps under any license |

The license texts are in [`licenses/`](licenses/): `LGPL-3.0-only.txt`, `GPL-3.0-only.txt` (the
LGPL-3.0 builds on it) and `pyserial-BSD-3-Clause.txt`.

### LGPL-3.0 (PySide6 / Qt)

- PySide6 and Qt are used without modification, as separate dynamically loaded libraries. In the
  desktop builds they're ordinary files next to the app (a PyInstaller *onedir* build), so you can
  replace them with your own compatible build.
- The source for the exact versions used is available from the Qt Project at the links above. The
  version is recorded in the app's `About` box and in `pyproject.toml`.
- The LGPL-3.0 lets you use PySide6/Qt for any purpose, including commercial use. This project's
  license doesn't restrict that. It applies only to CueKeys's own code.

## Distributed in the firmware bundle (`cuekeys-firmware-*.zip`)

The zip contains these CircuitPython libraries unmodified, with their license files in `licenses/`
inside the zip:

| Library | License | Source |
|---|---|---|
| pmk | MIT | https://github.com/pimoroni/pmk-circuitpython |
| adafruit_hid | MIT | https://github.com/adafruit/Adafruit_CircuitPython_HID |
| adafruit_is31fl3731 | MIT | https://github.com/adafruit/Adafruit_CircuitPython_IS31FL3731 |
| adafruit_dotstar | MIT | https://github.com/adafruit/Adafruit_CircuitPython_DotStar |
| adafruit_pixelbuf | MIT | https://github.com/adafruit/Adafruit_CircuitPython_Pixelbuf |
| adafruit_bus_device | MIT | https://github.com/adafruit/Adafruit_CircuitPython_BusDevice |
| neopixel | MIT | https://github.com/adafruit/Adafruit_CircuitPython_NeoPixel |

## Not distributed; used or talked to

- **CircuitPython** (MIT): you install it on the keypad yourself.
- **Bitfocus Companion**, **grandMA2 / grandMA3**, and OSC applications: only their public network
  protocols are used. None of their code is included.

## Trademarks

Pimoroni, Keybow, Adafruit, MacroPad, Bitfocus Companion, grandMA and other product names belong to
their owners. This project isn't affiliated with or endorsed by any of them. The names are used only
to say which hardware and software it works with.

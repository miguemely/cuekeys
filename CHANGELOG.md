# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/),
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Overlay on every macOS Space and over full-screen apps.** It's made a non-activating panel with
  all-Spaces collection behaviour. Setting: Overlay → "All desktops + full-screen apps".
- **Overlay display choice:** main display, all displays, the display with the mouse pointer, or
  selected displays (`overlay.screens`). It follows displays being plugged in and unplugged.
- **Developer documentation:** `AGENTS.md`, `CONTRIBUTING.md`, and `docs/` (architecture, protocol,
  extending, Companion, platform notes, roadmap).
- **GitHub support:**
  - GitHub Actions CI and a release workflow, alongside GitLab CI;
  - issue and pull request templates, Dependabot (grouped updates), and `SECURITY.md`;
  - a release dry run: starting the release workflow by hand builds, smoke-tests and collects every
    release asset without publishing.

- **More desktop builds:**
  - macOS **universal2** (Intel and Apple Silicon);
  - Windows **x64 and ARM64**;
  - Linux **x64 and ARM64**. The ARM64 build targets Raspberry Pi 4/5 on 64-bit Raspberry Pi OS
    bookworm and trixie, using Qt 6.8 LTS.
  - Each build is smoke-tested in CI before release.

### Changed
- **Smaller desktop apps:**
  - depend on `PySide6-Essentials` instead of the full `PySide6`;
  - the PyInstaller spec drops unused Qt modules (QtPdf, QtQuick/QtQml, QtNetwork, QtSvg, the
    virtual keyboard, translations) and SSL.
  - Result: the macOS app went from 99 MB to 61 MB (a 34 MB zip is now 21 MB).
- **Renamed from "PMK Macro Manager" to CueKeys.** The project supports much more than Pimoroni
  hardware, and "PMK" is the name of Pimoroni's library.
  - The Python package and command are now `cuekeys` (formerly `pmk_macro_manager` and `pmm`).
  - The firmware folders are now `lib/cuekeys_engine` and `lib/cuekeys_drivers`; installing the
    firmware removes the old `lib/pmkmacro` and `lib/pmkdrivers`.
  - Other renames: `$CUEKEYS_DEVICE_PATH`, the `cuekeys.devices` entry point, and the repo
    `miguemely/cuekeys`.
  - Saved app settings are migrated, and the old plugin folder is still searched.
  - Companion surface ids already in layouts are kept; new ones use `ck-…`.
  - The `pmk_*` drivers keep their names, because they wrap Pimoroni's `pmk` library.
- **Licensing:** the project is now source-available under the **PolyForm Noncommercial License
  1.0.0**, with separate commercial licenses (`COMMERCIAL-LICENSE.md`). The earlier MIT markings are
  replaced.
  - Third-party licenses are documented in `THIRD_PARTY_NOTICES.md` and `licenses/`.
  - The firmware zip and desktop apps now ship the relevant license texts.
  - The About box shows the license and the PySide6/Qt versions.

## [0.1.0]: first development version

### Added
- **CircuitPython firmware:**
  - a layer and macro engine: a single ordered timeline, tap/hold keys, and automatic release of
    held keys, notes, momentary layers and release payloads;
  - USB HID keyboard and media keys;
  - USB MIDI: notes, CC, program change, MIDI Show Control;
  - a JSON-lines link to the host.
- **Device profiles and firmware drivers**, so any keypad size or board can be used:
  - built-in profiles for the Keybow 2040 (tested), the Pico RGB Keypad Base, and the Adafruit
    MacroPad RP2040;
  - generic `keypad_keys` / `keypad_matrix` drivers with NeoPixel support;
  - a plugin folder, `$CUEKEYS_DEVICE_PATH`, and an entry point for adding more.
- **LED colour correction:** gamma and per-channel white balance, with a live calibration dialog.
- **Desktop app (PySide6):**
  - a layout editor with a macro recorder;
  - a dark theme and a custom-drawn keypad;
  - a floating, semi-transparent overlay showing the current layer and held keys;
  - deploying layouts and installing firmware to the CIRCUITPY drive.
- **Bridges:** OSC, grandMA3 (OSC `/cmd`), grandMA2 (Telnet), and Bitfocus Companion:
  - HTTP button presses;
  - Satellite surfaces sized to the keypad, with the bottom row kept for local keys;
  - page changes, page names, and location badges.
- **`cuekeys` CLI:** `gui`, `overlay`, `bridge`, `validate`, `deploy`, `install-firmware`, `devices`,
  `profiles`, `init`.
- **GitLab CI/CD:** lint, a test matrix, the wheel, the firmware zip, desktop apps, and releases.

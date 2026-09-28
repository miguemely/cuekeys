# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/),
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- **New license: CueKeys Source-Available Reciprocal License 1.0**, replacing PolyForm Noncommercial
  1.0.0. Personal, nonprofit and commercial use (including internal business use and paid services)
  are now allowed without a separate license. Distributing CueKeys or a modified version requires
  the complete source, the license and notices; selling CueKeys itself, renamed or modified, as a
  software product isn't allowed. Contributions are distributed under the same license (no CLA).
  Releases up to and including 0.1.0 remain available under PolyForm Noncommercial 1.0.0.
  - Every source file carries `SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0`;
    package metadata, SBOMs, the About box, release notes and the issue/PR templates follow it.

### Added
- **User guides** in `docs/guides/`, with screenshots for each step: getting started, locking your
  computer with one key, macros, layers, colours and LEDs, the overlay, lighting consoles (grandMA,
  MIDI, MSC), Companion, several keypads, and troubleshooting.
- **Screenshots** of the editor, overlays, settings and LED calibration in the README and docs
  (`docs/images/`). `scripts/screenshots.py` renders them offscreen from the demo layout with fake
  keypads and Companion data, so they can be regenerated after UI changes.

### Fixed
- The LED colour balance dialog could squash its intro text over the sliders.
- The key colour menu's "Key N colour" heading didn't show (the theme draws section titles as a line).
- The Companion surface size options were cut off in the layer panel; they're shorter now
  (`4×3 + 1 local row`), with the full description as a tooltip.
- Firmware bundle extraction rejects traversal paths and oversized archives; serial and Satellite
  protocol readers now bound frame sizes and discard malformed input.
- Physical keypad messages require a matching USB identity handshake before host bridges process them;
  malformed layouts now produce validation errors instead of crashing.

## [0.1.0] - 2026-09-25

First release.

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
- **Live colour preview:** layer and key colour changes show on the keypad as you make them (host
  `colors` message). **Deploy** is marked • while changes aren't deployed.
- **Easier key colours:** right-click a key on the editor's pad for a colour menu, and one-click
  colour swatches under the key and layer Colour fields.
- **SBOMs:** every release app zip and the firmware bundle come with a CycloneDX 1.5 SBOM
  (`*.cdx.json`): exact versions, licences and package URLs of what's shipped, including Qt, the
  Python runtime and the PyInstaller bootloader for the apps, and the Adafruit/Pimoroni libraries (with
  the pmk commit) for the firmware. `scripts/sbom.py`; checked in the release dry run.
- **Several keypads at once.** Keypads are identified by their hardware id (the RP2040 unique id,
  also their USB serial number), found automatically, and followed when re-plugged.
  - A keypad picker in the editor; each keypad has its own layout (keypads can share a file), and
    deploy, firmware install and LED calibration act on the selected keypad.
  - One overlay per keypad, stacked and labelled with the keypad's name.
  - Per-keypad name, layout and LED calibration in `keypads.json`; `cuekeys keypads`
    (list / rename / assign / forget) and `--keypad` for `deploy` and `install-firmware`.
  - The firmware reports its id in `hello` (`uid`).
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
- **Desktop apps for every platform:**
  - macOS **universal2** (Intel and Apple Silicon);
  - Windows **x64 and ARM64**;
  - Linux **x64 and ARM64**. The ARM64 build targets Raspberry Pi 4/5 on 64-bit Raspberry Pi OS
    trixie or newer.
  - All apps are built on the newest GitHub runner images with the newest PySide6/Qt. The Linux apps
    therefore need a current distribution (glibc 2.39+ today: Ubuntu 24.04+, Debian 13+, Raspberry
    Pi OS trixie+); on older ones, install with `pip install "cuekeys[gui]"` instead.
  - Each build is smoke-tested in CI before release.
  - Trimmed: `PySide6-Essentials` instead of the full `PySide6`, and the PyInstaller spec drops
    unused Qt modules (QtPdf, QtQuick/QtQml, QtNetwork, QtSvg, the virtual keyboard, translations)
    and SSL.

### Notes for anyone who ran development builds
- **Companion surface ids include the keypad:** `ck-<keypad>-<layer>` (e.g. `ck-e35b8c2b-example`),
  named `CueKeys <keypad> · <layer>`. Existing surfaces show up under the new id once; set its
  startup page and page permissions again in Companion and forget the old one.
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

[Unreleased]: https://github.com/miguemely/cuekeys/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/miguemely/cuekeys/releases/tag/v0.1.0

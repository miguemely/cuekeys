# AGENTS.md: working on CueKeys

Orientation for AI coding agents and new contributors. The project uses the CueKeys
Source-Available Reciprocal License; see invariant 8. Read this first, then
[docs/architecture.md](docs/architecture.md). Humans: [CONTRIBUTING.md](CONTRIBUTING.md) has the same
material with more narrative.

## What this is

A cross-platform (macOS / Windows / Linux) manager for CircuitPython macro keypads. It has two halves
that talk over USB serial:

- **Firmware** (`firmware/`, CircuitPython): runs on the keypad. It handles HID keyboard, media keys,
  USB-MIDI, layers, macros and LEDs, and works with no host app running.
- **Host app** (`src/cuekeys/`, Python 3.10+, PySide6): the layout editor, the on-screen
  overlay, and the bridges to OSC / grandMA2 / grandMA3 / Bitfocus Companion. It also deploys
  layouts and firmware to the pad.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # setup
.venv/bin/python -m pytest -q                                  # all tests (~1.5 s, no hardware needed)
.venv/bin/ruff check .                                         # lint (CI runs this too)
.venv/bin/cuekeys gui examples/demo-layout.json                    # run the editor
.venv/bin/cuekeys profiles | devices | validate FILE | deploy FILE # CLI
python scripts/build_firmware_bundle.py --out dist             # drag-and-drop firmware zip (+ its SBOM)
python scripts/sbom.py --app --out dist/app.cdx.json            # CycloneDX SBOM of the app (build_app.py runs this)
python scripts/screenshots.py                                   # docs/images/*.png; re-run after UI changes
```

Tests use Qt's offscreen platform (`tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen`) and bind
to 127.0.0.1. In a sandbox that blocks local sockets, some tests fail with `PermissionError`. That's
the sandbox, not the code.

## Code map

| Path | What |
|---|---|
| `firmware/code.py` | Keypad main loop: loads the driver, polls keys, runs the engine, serial link |
| `firmware/boot.py` | Enables the second USB CDC ("data") port and USB MIDI. Needs a hard reset to change |
| `firmware/lib/cuekeys_engine/engine.py` | **The macro/layer engine.** Pure Python, hardware-free, unit-tested on desktop |
| `firmware/lib/cuekeys_engine/midi.py` | Raw MIDI / MIDI Show Control byte builders |
| `firmware/lib/cuekeys_drivers/` | Hardware drivers (`poll` / `set_led` / `show` interface) |
| `src/cuekeys/config.py` | Layout schema (`ACTION_SPECS`), defaults, validation, prune, firmware view |
| `src/cuekeys/devices/` | Device profiles (grid geometry, driver, LEDs) and plugin loading |
| `src/cuekeys/runtime.py` | Host brain: `Hub` (keypad discovery, shared OSC/MA/Companion bridges) and one `KeypadSession` per keypad (serial link, layout, live state, events) |
| `src/cuekeys/keypads.py` | `KeypadStore`: per-keypad name, layout file and LED calibration, keyed by hardware id |
| `src/cuekeys/link.py` | Threaded JSON-lines serial link with auto-reconnect |
| `src/cuekeys/companion.py` | Companion HTTP API + Satellite protocol client |
| `src/cuekeys/grandma.py`, `osc.py` | grandMA2 Telnet, grandMA3 OSC address, dependency-free OSC encoder |
| `src/cuekeys/device.py` | Finds CIRCUITPY drives / serial ports; install and deploy |
| `src/cuekeys/cli.py` | `cuekeys` command |
| `src/cuekeys/gui/` | Qt UI: `editor.py` (main window), `overlay.py`, `actions.py` (macro editor), `settings.py`, `calibration.py`, `theme.py`, `macos.py` |
| `src/cuekeys/examples.py` | The demo layout (remapped per device profile) |
| `tests/` | pytest; `test_runtime.py` holds `FakeLink` / `FakeSatellite`, reused by the GUI tests |

## Invariants: don't break these

1. **The firmware is CircuitPython, not CPython.** In `firmware/` use only what CircuitPython supports: no
   `dataclasses`, `typing`, `functools.partial`, `enum`, walrus-heavy tricks or f-string `=`. Keep
   hot paths allocation-light. `engine.py` must stay hardware-free (all I/O through the backend), so
   it stays testable.
2. **Firmware and host share the action vocabulary.** `engine.ACTION_TYPES` must equal
   `config.ACTION_SPECS` keys (a test enforces this). Adding an action touches both. See
   [docs/extending.md](docs/extending.md#add-an-action-type).
3. **The keypad only ever receives `config.firmware_view(config)`.** Bridge settings and passwords
   stay on the host. The firmware view also resolves the device profile (driver, `num_keys`,
   `led_*`).
4. **`firmware/config.json` is generated** from `examples.example_config()`, and a test checks it.
   After changing the example, the schema defaults or a built-in profile, regenerate it:
   ```bash
   .venv/bin/python -c "from cuekeys import config as c; from cuekeys.examples import example_config as e; open('firmware/config.json','w').write(c.dumps(c.firmware_view(c.prune(e()))))"
   .venv/bin/cuekeys init --example examples/demo-layout.json
   ```
5. **Key numbers come from the device profile's grid**, never from 4×4 constants. Use
   `devices.profile_for(config)` and its `key_to_cell` / `cell_to_key` / `satellite_index` /
   `display_size` (all rotation-aware). There's no `layout.py` any more.
6. **Tests never touch real services or hardware.** Use `FakeLink`, and pass
   `satellite_factory=FakeSatellite` to `Runtime` / `Hub` (a real `SatelliteClient` would register surfaces
   on whatever Companion is running on 127.0.0.1). Don't write to `/Volumes/CIRCUITPY` in tests.
7. **GUI tests must not open modal dialogs.** A `QMessageBox` blocks forever under pytest. The
   `window` fixture patches `_confirm_discard`; do the same for anything new that can prompt.
8. **Licensing:** the project uses the CueKeys Source-Available Reciprocal License. New source
   files get `# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0`. Only add permissive or LGPL
   (as a replaceable library) dependencies, never GPL or AGPL, and record distributed ones in
   `THIRD_PARTY_NOTICES.md`.
9. **macOS native calls only under the Cocoa platform** (`gui/macos.available()`). Under the
   offscreen platform `winId()` isn't an `NSView`, and messaging it segfaults.

## Gotchas we already hit

- **Companion 5 ignores `ADD-DEVICE` sent before its `CAPS` line.** It also stays *silent* (no
  error) when another client holds the same surface id. The client waits for `CAPS` on API ≥ 1.10
  and resends after 5 s. See [docs/companion.md](docs/companion.md).
- **Every runtime event carries `keypad`.** Listeners that show one keypad (editor, `Overlay`) must
  ignore events for other keypads. Tests with several keypads use `Hub(..., discover=False,
  link_factory=…)` and `hub.scan([...])` with fake port lists (see `tests/test_hub.py`).
- **The Satellite protocol never sends page names.** They come from the HTTP variable
  `internal:page_number_<n>_name`.
- **AppKit throws if `CanJoinAllSpaces` is combined with Qt's `MoveToActiveSpace`.** Clear the
  conflicting flags first. Showing over *other apps'* full-screen Spaces also needs the
  non-activating panel style mask. See [docs/platform-notes.md](docs/platform-notes.md).
- **Qt toolbar widgets are hidden through their `QAction`**, not `widget.hide()`.
- **`str.replace` in scripted edits replaces every match.** Make patterns unique.
- **PMK's `key.pressed` is not debounced.** The `_pmk.py` driver debounces. The `keypad`-module
  drivers get debouncing from CircuitPython.
- **LEDs are gamma-corrected (2.2) and white-balanced per profile/layout.** Tests that assert exact
  LED values must pin `led_gamma: 1.0`.
- **`boot.py` changes only take effect after unplugging the keypad.** Use `install-firmware --no-boot`
  for everything else.

## Before you finish a change

- [ ] `ruff check .` is clean and `pytest -q` is green.
- [ ] New behaviour has a test (engine → `test_engine.py`, host logic → `test_runtime.py` /
      `test_config.py`, drivers → `test_drivers.py` with stubbed modules, UI → `test_gui.py`).
- [ ] Generated files are regenerated (invariant 4) if the schema, example or profiles changed.
- [ ] New files have the SPDX header, and any new distributed dependency is in `THIRD_PARTY_NOTICES.md`.
- [ ] Docs are updated: README (user-facing), `docs/protocol.md` (new messages), `docs/devices.md`
      (profile/driver fields), `CHANGELOG.md`.
- [ ] If you touched firmware or LED/key handling: test on real hardware if you can. The checklist is
      in [CONTRIBUTING.md](CONTRIBUTING.md#hardware-testing).

## Where to go next

- [docs/architecture.md](docs/architecture.md): components, threads, data flow, engine semantics
- [docs/protocol.md](docs/protocol.md): the keypad ↔ host serial protocol
- [docs/extending.md](docs/extending.md): recipes for actions, bridges, settings, CLI, drivers
- [docs/devices.md](docs/devices.md): device profiles and firmware drivers (the plugin system)
- [docs/companion.md](docs/companion.md), [docs/platform-notes.md](docs/platform-notes.md)
- [docs/roadmap.md](docs/roadmap.md): known gaps and good next tasks

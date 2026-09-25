# Extending PMK Macro Manager

Step-by-step recipes for the common kinds of change. Each one lists every file you'll touch and the test
to add. Keep [AGENTS.md](../AGENTS.md#invariants-dont-break-these) open while you work.

## Contents

- [Add a keypad (device profile / driver)](#add-a-keypad)
- [Add an action type](#add-an-action-type)
- [Add a network bridge / integration](#add-a-network-bridge)
- [Add a setting](#add-a-setting)
- [Add a CLI command](#add-a-cli-command)
- [Add an overlay or editor feature](#add-an-overlay-or-editor-feature)
- [Add a platform-specific tweak](#add-a-platform-specific-tweak)
- [Plugin mechanisms at a glance](#plugin-mechanisms-at-a-glance)

## Add a keypad

This is the most common extension. You usually only need JSON. The full guide is
[devices.md](devices.md).

1. Create `<plugin dir>/<id>/device.json` with the grid, driver and `driver_config`. Start from
   `examples/devices/diy_rp2040_3x3/`.
2. `pmm profiles` should list it. Errors are printed there.
3. If no built-in driver fits, add `driver.py` next to it (interface in
   `firmware/lib/pmkdrivers/__init__.py`), plus a test with stubbed CircuitPython modules modelled on
   `tests/test_drivers.py`.
4. To ship it built in: move it to `src/pmk_macro_manager/devices/builtin/<id>/` (and a new driver to
   `firmware/lib/pmkdrivers/`). Add the libraries it needs to `ADAFRUIT_LIBS` in
   `scripts/build_firmware_bundle.py`, and add a row to the supported-devices table in
   `docs/devices.md`. The existing tests check that it loads, that its driver exists and that the demo
   layout remaps onto it.

## Add an action type

Example: a `"serial_write"` action that sends text to the host, which writes it to another serial device.

1. **Schema:** in `src/pmk_macro_manager/config.py`, add an entry to `ACTION_SPECS` with a `label` and
   `fields` (built with the `F()` helper; kinds: `str text int bool choice keys json layer`). The
   editor form is generated from this. Add a summary line in `describe_action()`, and extra
   cross-field checks in `validate_action()` if needed.
2. **Firmware:** in `firmware/lib/pmkmacro/engine.py`, add the name to `ACTION_TYPES` and a branch in
   `Engine.execute()`. If the action has an "off" state, push an undo callable into `undo`, and it
   runs on release automatically. Keep to the CircuitPython subset.
3. **Host (only for network or host-side actions):** have the engine send
   `backend.host({"t": "<type>", ...})` and handle it in `Runtime._on_message`. Put blocking I/O on
   the worker thread with `self._jobs.put((kind, payload))`, and handle it in `Runtime._work`.
4. **UI colour:** map it to a category in `gui/theme.py` `ACTION_CATEGORY`.
5. **Tests:** engine behaviour in `test_engine.py` (fake backend and clock); host handling in
   `test_runtime.py`; `test_config.py` if validation changed. The action-parity test catches a
   type missing on either side.
6. **Docs:** add a row to the README's action reference, and a row to `docs/protocol.md` for any new
   message.
7. **Deploy:** firmware changes need `pmm install-firmware --no-boot` (or Keypad → Install / update
   firmware) on real hardware.

## Add a network bridge

Example: a vMix, OBS, QLab or ETC Eos integration.

1. Put the protocol client in its own module, `src/pmk_macro_manager/<name>.py`. Keep it free of Qt
   and threads, and make it testable against a local fake server (see `test_companion.py` /
   `test_osc_grandma.py`).
2. Add its settings under `bridge.<name>` in `config.default_config()`. Settings merge in
   automatically through `merge_defaults`.
3. Add an action type that sends a `host` message (recipe above), and route it in `Runtime`:
   non-blocking sends inline, blocking ones through `_jobs`.
4. For a long-lived connection (like Companion Satellite), follow `SatelliteClient`:
   - its own daemon thread with retry;
   - `on_status` / `on_key_state` callbacks into `Runtime`, which `emit`s events;
   - `start()` / `stop()` called from `Runtime.start()` / `Runtime.stop()` and re-synced in
     `set_config()`.
5. Add a settings tab or fields in `gui/settings.py` (declarative tuples), and a status pill in
   `MainWindow._update_status` if connection state matters.
6. Tests must use fakes or local servers only. Never a real instance.

## Add a setting

- **Keypad settings** (`device.*`): add a default in `default_config()`, validation in `validate()`,
  and a tuple in `gui/settings.py` `DEVICE_FIELDS`. Read it in `Engine.load()` or `code.py`.
- **Overlay settings** (`overlay.*`): default, `OVERLAY_FIELDS` tuple, then read it in
  `Overlay` / `OverlayWindow` through `self.settings`. Call `apply_settings()` when it changes.
- The field kinds in `_Section` are `choice bool int float str password profile screens`. Add a kind
  there if you need a new widget.
- Regenerate `firmware/config.json` if a `device` default changed
  ([AGENTS.md invariant 4](../AGENTS.md#invariants-dont-break-these)).

## Add a CLI command

In `src/pmk_macro_manager/cli.py`: write `cmd_<name>(args)` returning an exit code, and register it
in `build_parser()` with `add(...)`. `OSError`, `RuntimeError` and `KeyError` become clean
`error: …` messages in `main()`.

## Add an overlay or editor feature

- Key rendering is shared. Change `cell_content` / `cell_badge` / `paint_key` in `gui/common.py`, and
  the editor keypad and every overlay window follow.
- Live data arrives as runtime events. Connect to `signals.event` and react to `(name, data)`. Don't
  call Qt from `Runtime` threads.
- Any size, gap or rotation logic must use the device profile (`profile.display_size`,
  `key_to_cell`, …).
- Style comes from `gui/theme.py` tokens and QSS object names: `primary`, `flat`, `pill`, `muted`,
  `section`, `title`, `panel`.
- For headless verification, render with `widget.grab().save(...)` under `QT_QPA_PLATFORM=offscreen`
  (see [CONTRIBUTING.md](../CONTRIBUTING.md#visual-checks)).

## Add a platform-specific tweak

Follow `gui/macos.py`:
- put it in its own module, guarded by a real-platform check (`available()`);
- apply it from `showEvent`, because Qt recreates native windows when flags change;
- never let it raise into the UI;
- verify it on the real platform with a probe script. Unit tests run offscreen and can't.

Write down what you learned in [platform-notes.md](platform-notes.md).

## Plugin mechanisms at a glance

| Extend | How | Discovery |
|---|---|---|
| Keypad models | `device.json` (+ optional `driver.py`) | built-in dir, `pmk_macro_manager.devices` entry point, user plugin folder, `$PMM_DEVICE_PATH` |
| Firmware drivers | `lib/pmkdrivers/<name>.py` with a `Hardware` class | named by the profile's `driver`; copied to the pad by install |
| Actions / bridges | Code in this repo (see above) | Not pluggable at runtime yet. See [roadmap.md](roadmap.md) |

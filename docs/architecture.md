# Architecture

## The big picture

```
┌─────────────────────── keypad (CircuitPython) ───────────────────────┐
│ code.py main loop                                                    │
│   driver.poll() ──► Engine.press/release ──► timeline queue ──► tick │
│        ▲                     │                                       │
│   cuekeys_drivers/<driver>        ├── backend.key_down/…  → USB HID        │
│   (keys + LEDs)              ├── backend.midi(bytes) → USB MIDI       │
│        ▲                     ├── backend.set_led     → driver LEDs    │
│        └─ set_led/show ◄─────┘   backend.host(msg)   → usb_cdc.data ──┼──┐
│                                                                      │  │ JSON lines
│   HostLink.poll() ◄── host commands (layer, press, led, led_cal, …) ─┼──┤
└──────────────────────────────────────────────────────────────────────┘  │
                                                                          │
┌──────────────────────────── host app (Python) ───────────────────────┐  │
│ DeviceLink (reader thread) ◄─────────────────────────────────────────┼──┘
│      │ on_message                                                     │
│      ▼                                                                │
│ Runtime ── OSC (UDP) ─────────────► any OSC target / grandMA3 /cmd    │
│   │  ├──── worker thread ─────────► grandMA2 Telnet, Companion HTTP   │
│   │  └──── SatelliteClient(s) ◄───► Companion Satellite (TCP 16622)   │
│   │ emit(event, data)  (from background threads)                      │
│   ▼                                                                   │
│ RuntimeSignals (Qt signal, queued to the GUI thread)                  │
│   ├── MainWindow (editor)                                             │
│   └── Overlay ── OverlayWindow per display                            │
└──────────────────────────────────────────────────────────────────────┘
```

The keypad is self-sufficient for HID, media keys and MIDI. The host adds everything network-related,
editing, the overlay and deployment.

## Firmware

### Main loop (`firmware/code.py`)

1. Load `/config.json`. On error, fall back to an empty layer and light every key red.
2. `make_hardware(device)` imports `cuekeys_drivers.<device.driver>` and builds `Hardware(driver_config)`.
   Old layouts that only have `device.hardware` are mapped through `LEGACY_DRIVERS`.
3. Build the `Engine` with a `Backend` (HID keyboard + layout, consumer control, `usb_midi.ports[1]`,
   `HostLink`, driver LEDs) and a millisecond clock (`time.monotonic_ns() // 1_000_000`; integer ms,
   because CircuitPython floats lose precision after a few hours).
4. Loop: `hardware.poll(now)` → `engine.press/release` → `engine.tick()` → `hardware.show()`, then
   send `hello` when the serial port (re)connects, then handle host messages.

### Engine (`firmware/lib/cuekeys_engine/engine.py`)

- **One timeline.** Every action is scheduled on a single queue (`_schedule`). A `delay` action moves
  the cursor forward. Macros never interleave, and release/undo steps always run after their press
  steps, even if you let go mid-macro.
- **Undo stack per press.** Actions with a natural "off" push an undo callable into the press state:
  held key combos (`mode: hold`), momentary MIDI notes, `midi_cc.release_value`, momentary layers,
  `osc.release_args`, `ma.release_command`, and `companion` in hold mode. On release, one timeline
  entry pops them in reverse order.
- **Tap/hold.** A key with `hold` actions defers `press` until release (a tap). If it's held past
  `hold_time_ms`, `hold` runs instead (checked in `tick`).
- **Layers.** `goto / next / prev / toggle / momentary`. `set_layer` announces `layer` to the host and
  re-renders the LEDs.
- **Companion layers.** Unassigned keys in the Companion region do nothing locally. The host forwards
  their `key` events to Companion and pushes colours back with `led`, which are stored in
  `remote_colors`.
- **LEDs.** `key_color()` → `corrected()` applies three per-channel 256-entry lookup tables that fold
  brightness, gamma (`led_gamma`, default 2.2) and white balance (`led_balance`) together. The result
  goes to `backend.set_led`. `set_test_color` (used by calibration) overrides every key.
- **Errors never crash the loop.** A failing action is reported to the host as a `log` message.

### Drivers (`firmware/lib/cuekeys_drivers/`)

See [devices.md](devices.md#writing-a-driver). `poll()` returns debounced `(key, pressed)` changes,
and `set_led` / `show` drive the LEDs. Key numbers must match the profile's grid.

## Host

### Configuration lifecycle

```
layout.json (host file) ──load──► merge_defaults ──► in-memory config (shared dict)
      ▲                                                  │  edited in place by the GUI
      └───────────── save (prune: drop empty keys) ◄─────┤
                                                         ▼
                              firmware_view(prune(config)) ──deploy──► CIRCUITPY/config.json
                              (device + layers only, profile resolved to driver/num_keys/led_*)
```

- The GUI edits the **same dict** the keypad session holds, so changes show on the overlay
  immediately. Call `hub.config_changed(config)` after structural changes (layers added or removed,
  modes, the device) so every keypad using that layout re-syncs its Companion surfaces.
- One layout file is loaded **once** (`Hub.load_layout`, cached by path), so keypads that share a file
  share one dict and one set of edits.
- `validate()` checks everything against `ACTION_SPECS` and the device profile (key range,
  `companion_rows`, LED settings). The editor forms are *generated* from `ACTION_SPECS`.

### Hub and keypad sessions (`runtime.py`, `keypads.py`)

Several keypads can be connected at once.

- **Identity.** A keypad is its RP2040 hardware id (`microcontroller.cpu.uid`). The same value is the
  USB serial number of its serial ports and the `UID:` line of `boot_out.txt`, so the host matches
  ports and CIRCUITPY drives to a keypad without opening anything (`device.list_keypads()`,
  `device.pick_drive(uid=…)`). The firmware also reports it in `hello` (`uid`).
- **`Hub`** owns the shared parts: keypad discovery (a scan every 2 s; hot-plug and port renames),
  the OSC socket, the worker thread, and **one Satellite connection per Companion server** that
  carries every keypad's surfaces. While no keypad is known it keeps a **virtual keypad**
  (`VIRTUAL_UID`, shown as "No keypad") so the editor has something to edit; it's dropped when a real
  keypad arrives, and the editor moves to that keypad with the same layout.
- **`KeypadSession`** is one keypad: its `DeviceLink`, its layout (`config`, `layout_path`), and
  live state. The GUI edits one session at a time (toolbar picker).
- **`KeypadStore`** (`keypads.py`, `<config dir>/cuekeys/keypads.json`) keeps what belongs to the
  physical unit rather than the shareable layout: `name`, the assigned `layout` file, LED calibration
  (`led_gamma`, `led_balance`, which win over the layout's at deploy), and `last_seen`.
- `Runtime(config, port=…)` still exists for single-keypad use (`--port`, tests): it returns the
  session of a one-keypad hub without discovery.

- **Threads:**
  - one `DeviceLink` reader per keypad (serial);
  - `cuekeys-discovery` (keypad scan);
  - one `SatelliteClient` per Companion server;
  - `cuekeys-bridge` worker for blocking jobs: grandMA2 Telnet, Companion HTTP presses, page-name
    lookups.
  - OSC sends are non-blocking UDP and happen inline.
- **Events.** `session.emit(event, **data)` runs on those threads and adds `keypad` (the uid) to
  every event. The GUI wraps them with `RuntimeSignals`, a Qt signal that queues onto the GUI thread,
  and filters by `keypad`. Events: `status`, `layer`, `key`, `companion`, `overlay`, `host`, `log`,
  plus `keypads` (added / removed / renamed) and `config` (a keypad got a new layout). See the
  docstring at the top of `runtime.py`.
- **State per session.** `layer`, `pressed` (key → layer it was pressed on),
  `companion_states[(layer, key)]`, `companion_pages[layer]`, `connected`, `firmware`. Page names are
  cached on the hub per (Companion server, page).
- **Overlays.** `OverlayGroup` (`gui/overlay.py`) keeps one `Overlay` per keypad, stacked away from
  the corner; with several keypads each header starts with the keypad's name.
- **No keypad?** `select_layer` / `press_key` fall back to local previews, so overlay clicks can
  still drive Companion.

### Companion

See [companion.md](companion.md). In short:
- each Companion layer is one Satellite surface of `companion_rows × width` keys;
- keys are mapped through `profile.satellite_index()`;
- colours become key LEDs and overlay fills, and text becomes labels;
- `LOCATION` gives the page;
- page names come from HTTP.

### GUI

| Class | File | Role |
|---|---|---|
| `MainWindow` | `gui/editor.py` | Layers list, `KeyPad` (custom-painted grid), key editor with three `ActionListEditor` tabs, toolbar pills, menus |
| `ActionListEditor` / `ActionForm` | `gui/actions.py` | Action lists and generated forms; macro recorder |
| `Overlay` | `gui/overlay.py` | Picks displays (`screens`), owns one `OverlayWindow` per display, syncs opacity/visibility, handles `overlay` events |
| `OverlayWindow` | `gui/overlay.py` | Frameless, translucent, always-on-top tool window for one display |
| `SettingsDialog` | `gui/settings.py` | Device, overlay, grandMA, OSC/Companion settings (declarative field lists) |
| `CalibrationDialog` | `gui/calibration.py` | Live LED gamma / white balance against the real pad |
| `theme` | `gui/theme.py` | Colour tokens, Fusion palette and QSS; action category colours |
| `macos` | `gui/macos.py` | Objective-C runtime calls for all-Spaces / full-screen overlay |

Key drawing is shared: `common.cell_content()` gives the label and colour, `common.cell_badge()` gives
the Companion location, and `common.paint_key()` draws the key cap, for both the editor and the overlay.

## Device profiles

See [devices.md](devices.md). `devices.profile_for(config)` is the single source of truth for key
count, grid geometry (including rotation), Companion surface width, driver, required libraries and
default LED correction.

## Packaging and CI

- **Wheel:** hatchling. It bundles `firmware/` into `cuekeys/firmware`, and
  `device.firmware_source()` finds it in both a source checkout and an installed wheel.
- **Desktop apps:** `packaging/build_app.py` runs PyInstaller with `packaging/cuekeys.spec`.
  - The spec bundles `firmware/`, the built-in profiles and the license texts, and drops unused Qt
    modules and plugins before assembly, so macOS signing stays valid.
  - Targets: macOS universal2, Windows x64/ARM64, Linux x64/ARM64 (Raspberry Pi 4/5 on Qt 6.8 LTS).
- **Firmware zip:** `scripts/build_firmware_bundle.py` (the Adafruit *py* bundle plus `pmk`, so it
  works on any CircuitPython version).
- **CI/CD:** `.github/workflows/` (GitHub Actions) and `.gitlab-ci.yml` (GitLab CI). See
  [CONTRIBUTING.md](../CONTRIBUTING.md#ci-and-releases).

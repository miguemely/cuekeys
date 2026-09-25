# Roadmap, known gaps and good next tasks

Size is a rough guide: **S** is an afternoon, **M** a few days, **L** needs design first.

## Not yet verified

Code exists for these but hasn't been checked for real. Anyone with the setup can help.

| Item | What's needed |
|---|---|
| GitHub Actions workflows | Watch the first `ci.yml` run (especially the macOS and Windows test jobs) and a first `release.yml` tag build |
| GitLab CI pipeline | Push to a GitLab mirror and fix whatever the first run turns up (runner tags, apt packages, the Windows Python install) |
| Windows / macOS desktop builds (PyInstaller) | Run `packaging/build_app.py` on each OS and smoke-test the app |
| Pico RGB Keypad Base profile | Hardware test (`rgbkeypad`), then set `"tested": true` |
| Adafruit MacroPad RP2040 profile | Hardware test (`adafruit_macropad`) |
| grandMA3 command OSC (`/gma3/cmd`) | Test against MA3 onPC. The address format was written from memory of the MA3 docs |
| grandMA2 Telnet, MIDI Show Control | Test against MA2 onPC / console |
| Keybow 2040 LED colour balance | Calibrate a real unit and put the values in the profile's `led_balance` |

## Housekeeping

- **Contributor License Agreement:** the dual-licensing model needs a CLA text and a way to collect
  signatures (e.g. the CLA Assistant GitHub app). Have a lawyer review it, together with the
  commercial license terms.
- **`gui/editor.py` is large.** Split the key editor panel and layer panel into their own modules. (S)
- **OSC / Companion targets are edited as raw JSON** in Settings. Replace that with proper forms. (S)

## Feature ideas

| Idea | Notes | Size |
|---|---|---|
| MacroPad rotary encoder and OLED | Extend the driver interface with an optional `poll_encoders()` and `display_text()`. Add `rotate_cw` / `rotate_ccw` slots, or encoder actions. Show the layer name on the OLED | M |
| Host-side action and bridge plugins | An entry-point group, e.g. `pmk_macro_manager.actions`, that registers `ACTION_SPECS` entries plus a runtime handler for `host`-routed actions. The firmware side stays generic by routing through `{"t": "plugin", "name": …}` | L |
| Feedback into LEDs | MIDI in or OSC in (for example grandMA executor state or OBS scene) → key colours, like the Companion LED path (`led` message) | M |
| Companion button images | Register with `BITMAPS=<size>` and draw the images on the overlay | M |
| Overlay on all virtual desktops on Windows / Linux | Linux: `_NET_WM_STATE_STICKY` over X11. Windows: no public API; investigate | M |
| Overlay placement | Drag to position; per-display corner | S |
| Wide keys and key spans in profiles | e.g. 2u keys: let grid cells span. Touches `DeviceProfile`, the editor keypad and the overlay | M |
| Several keypads at once | Several `DeviceLink`s, per-keypad layouts, overlay per keypad | L |
| Automatic layer per foreground app | OS-specific "front app" detection → `select_layer` | M |
| Keyboard layout picker | Show the installed `keyboard_layout_*` options for non-US typing | S |
| Macro recording outside the app window | Needs a global key hook per OS | L |

## Design notes for plugin actions (sketch)

- Plugins would register `ACTION_SPECS` entries under a namespace (`"vmix.cut"`). The editor
  already builds forms from specs.
- The firmware engine doesn't need to know them: host-routed plugin actions go through a single
  firmware action type (e.g. `plugin`) that forwards `{"t": "plugin", "action": {...}}`, with the
  undo-on-release pattern for `release_*` fields.
- Validation: `validate_action()` would fall back to the plugin's spec.
- Keep the parity test: `engine.ACTION_TYPES` would include `plugin`, and specs would be split into
  core and plugin sets.

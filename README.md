# CueKeys

Create, edit and manage macros on CircuitPython macro keypads, on Windows, macOS and Linux. Pimoroni's **Keybow 2040** is tested, the **Pico RGB Keypad Base** and **Adafruit MacroPad RP2040** are included, and any other size or board can be added as a plugin (see [Adding a keypad](docs/devices.md)).

- **Macros**: key combos, typed text, delays, key down/up, media keys, all in one sequence. Keys can be tap/hold.
- **Layers**: any number of layers, switched by goto, next/prev, toggle or momentary (held) layer keys.
- **On-screen overlay**: a small floating window in the bottom-right corner, semi-transparent and always on top. It shows what every key does, the current layer, and which keys are held down.
- **MIDI / MIDI Show Control**: sent straight from the keypad over USB-MIDI, so it works with no software running.
- **OSC, grandMA2 and grandMA3**: MA3 command-line OSC (`/gma3/cmd`), MA2 Telnet commands, and any OSC message.
- **Bitfocus Companion**: press a Companion button over HTTP, or make a whole layer a Companion *Satellite surface*. Companion then controls those keys, and its button colours and text show on the keypad LEDs and on the overlay.
- **Any keypad**: device profiles describe each pad's key grid, LEDs and firmware driver. Generic drivers cover one-pin-per-key and diode-matrix builds with NeoPixels, so most DIY RP2040 pads need only a JSON file.
- **CI/CD on GitHub Actions and GitLab CI**: lint, tests on Python 3.10–3.13 (plus macOS and Windows), a wheel, a firmware zip, desktop apps for all three OSes, and releases.

```
 ┌──────────── keypad (CircuitPython) ────────────┐         ┌──────────── host app (Python / Qt) ─────────────┐
 │ code.py + lib/cuekeys_engine (layers, macro engine)  │  USB    │ editor ─ overlay ─ runtime                       │
 │   ├─ USB HID keyboard / media keys  ───────────┼────────▶│   ├─ OSC (UDP)             ─▶ anything OSC       │
 │   ├─ USB MIDI  (notes, CC, PC, MSC) ───────────┼────────▶│   ├─ grandMA3 OSC /cmd     ─▶ grandMA3           │
 │   └─ usb_cdc data: JSON lines  ◀───────────────┼────────▶│   ├─ grandMA2 Telnet       ─▶ grandMA2           │
 │      (layer, key events, osc/ma/companion)     │         │   └─ Companion HTTP + Satellite ◀▶ Companion     │
 └────────────────────────────────────────────────┘         └──────────────────────────────────────────────────┘
```

The keypad works on its own for keyboard, media and MIDI actions. The host app is only needed for the editor, the overlay and the network actions (OSC, grandMA, Companion).

## Install

**Desktop app**: download the zip for your computer from the project's **Releases** page:

| Download | For |
|---|---|
| `cuekeys-<v>-macos-universal2.zip` | macOS 13 or newer, Intel and Apple Silicon |
| `cuekeys-<v>-windows-x86_64.zip` | Windows 10/11 on Intel/AMD |
| `cuekeys-<v>-windows-arm64.zip` | Windows 11 on ARM (Snapdragon and similar) |
| `cuekeys-<v>-linux-x86_64.zip` | 64-bit Linux with glibc 2.35+ (Ubuntu 22.04+, Debian 12+, Fedora 36+) |
| `cuekeys-<v>-linux-arm64.zip` | **Raspberry Pi 4 / 5** with a 64-bit OS (Raspberry Pi OS bookworm or trixie, Ubuntu 22.04+), and other ARM64 Linux |

The builds aren't code-signed yet. macOS: right-click the app and choose **Open** the first time.
Windows: **More info → Run anyway**. The Raspberry Pi build uses Qt 6.8 LTS; 32-bit Raspberry Pi OS
isn't supported, because Qt has no 32-bit ARM packages.

**From source** (Python 3.10+):

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[gui]"
cuekeys            # opens the editor
```

## Set up the keypad

1. Flash CircuitPython 9 or newer: [Keybow 2040](https://circuitpython.org/board/pimoroni_keybow2040/) or [Raspberry Pi Pico](https://circuitpython.org/board/raspberry_pi_pico/) for the RGB Keypad Base.
2. Copy the contents of `cuekeys-firmware-<version>.zip` (from Releases, or built with `python scripts/build_firmware_bundle.py`) onto the `CIRCUITPY` drive. It contains the firmware and every library it needs (`pmk`, `adafruit_hid`, LED drivers).
   - Or, if the libraries are already on the drive: **Keypad → Install / update firmware** in the editor, or `cuekeys install-firmware`.
3. **Unplug and replug the keypad once.** `boot.py` turns on the second USB serial port that the host app uses, and that only takes effect after a hard reset.
4. Edit your layout and click **Keypad → Deploy layout to keypad** (Ctrl+D). The keypad reloads by itself.

Pick your keypad in **Settings → Keypad → Device**, or pass `cuekeys init --device <id>`. `cuekeys profiles` lists the supported devices; `cuekeys devices` shows which profile matches the board that's plugged in. To add a keypad that isn't listed, see [docs/devices.md](docs/devices.md).

## Using the editor

- **Layers** (left): add, duplicate, reorder, and set a name, colour and mode (`local` or `companion`).
- **Key grid** (centre): laid out like the physical pad, with the USB connector at the top. Click a key to edit it. Keys held down on the real keypad light up live.
- **Key editor** (right): label and colour, plus three action lists:
  - **Press / tap**: runs when pressed. If the key also has Hold actions, it runs on a short tap instead.
  - **Hold**: runs once the key has been held for `hold_time_ms` (500 ms by default).
  - **Release**: runs when the key is released.
  - **Record…** captures key combos as you type them. It can keep the delays between them.
- Actions that have a natural "off" undo themselves on release: held key combos, MIDI notes in `momentary` mode, momentary layers, and OSC `release_args` / MA `release_command`.
- `PRIMARY` is a cross-platform modifier. It sends Cmd on macOS and Ctrl on Windows and Linux. The host app tells the keypad which OS it is plugged into. Set `host_os` if the keypad runs without the app.

Layouts are plain JSON. Save them anywhere, keep them in git, and share them. Only the `device` and `layers` sections go onto the keypad, so network settings and passwords stay on the computer.

### Overlay

The overlay shows the current layer (`2/4 grandMA3`), each key's label and colour, held keys, and whether the keypad and Companion are connected. Change it in **Settings → Overlay**: opacity, corner, size, rotation, and click-through. When click-through is off, you can click keys to trigger them, scroll to change layer, and right-click for the next layer.

Run only the overlay and bridge, for example on a show machine, with `cuekeys overlay layout.json`. It puts an icon in the system tray.

On Linux Wayland sessions the app uses XWayland (`QT_QPA_PLATFORM=xcb`), because Wayland doesn't let windows stay on top or choose their own position.

## Action reference

| Type | Runs on | Fields |
|---|---|---|
| `keys` | keypad | `keys` (e.g. `["PRIMARY","SHIFT","S"]`), `mode` `tap`/`hold` |
| `text` | keypad | `text` (typed using `keyboard_layout`) |
| `delay` | keypad | `ms` |
| `key_down` / `key_up` / `release_all` | keypad | `keys` |
| `consumer` | keypad | `code` (PLAY_PAUSE, MUTE, VOLUME_INCREMENT, …) |
| `layer` | keypad | `op` goto/next/prev/toggle/momentary, `layer` |
| `midi_note` | keypad | `note`, `velocity`, `channel`, `mode` momentary/tap/toggle |
| `midi_cc` | keypad | `cc`, `value`, `release_value`, `channel` |
| `midi_pc` | keypad | `program`, `channel` |
| `msc` | keypad | MIDI Show Control: `command` (go, stop, resume, fire, set, …), `cue`, `cue_list`, `cue_path`, `macro`, `control`/`value`, `device_id`, `command_format` |
| `osc` | host | `address`, `args` (JSON list), `release_args`, `target` |
| `ma` | host | grandMA `command`, `release_command`, `console` `ma3`/`ma2` |
| `companion` | host | `page`, `row`, `column`, `mode` hold/press, `target` |
| `companion_page` | host | `direction` next/prev: pages the Companion surface of the current layer (Companion 4.3+) |
| `overlay` | host | `op` cycle/toggle/show/hide, `levels` (default `[0.9, 0.6, 0.3, 0]`, where 0 hides it) |
| `host` | host | `event`, `data` (goes to the host app's listeners) |

## grandMA2 / grandMA3

| Method | grandMA2 | grandMA3 | Setup |
|---|---|---|---|
| MIDI notes (`midi_note`, momentary) | ✔ MIDI Remotes | ✔ MIDI Remotes | Set the keypad as MIDI input and map notes to executors. |
| MIDI Show Control (`msc`) | ✔ | ✔ | Enable MSC In. Device ID and command format must match (`all` / 127 accepts everything). On MA2 in *Exec.Page* mode, `cue_list` is `executor.page` (e.g. `1.1`). |
| Command line (`ma`, console `ma3`) | – | ✔ OSC | Menu → In & Out → OSC: add an input on the port set under **Settings → grandMA**, tick *Receive* and *Receive Command*. The prefix (default `gma3`) gives `/gma3/cmd`. |
| Command line (`ma`, console `ma2`) | ✔ Telnet | – | Setup → Console → Global Settings → Telnet: *Login Enabled*. Port 30000, user `administrator`. |
| Raw OSC (`osc`) | – | ✔ | e.g. `/gma3/Page1/Fader201` `[100]`, with `release_args` `[0]` |

On MA3 `ma` keys, `release_command` works as a flash (for example `Go+ Executor 201` / `Off Executor 201`).

## Bitfocus Companion

Add a server under **Settings → OSC & Companion**, e.g. `{"default": {"host": "10.0.0.5", "http_port": 8000, "satellite_port": 16622}}`.

- **Companion button action**: presses `page/row/column` through Companion's HTTP remote API. In `hold` mode it sends down on press and up on release.
- **Companion layer** (layer mode `companion`): the host registers that layer with Companion as a **Satellite** surface (TCP 16622). The default size is **4×3**: the top three rows belong to Companion, and the **bottom row stays local**. Choose *4×4 · whole keypad* in the layer settings if you want Companion to have all 16 keys. In the Companion region, unassigned keys go to Companion. Companion's button colour drives the key LED, and its text becomes the overlay label. Keys you assign locally still override Companion. Each Companion layer is a separate surface with a stable ID (`companion_id`).
  - **Give the surface its own pages:** in Companion → Surfaces → your CueKeys surface, set *Startup Page* and turn on *Restrict pages accessible to this surface*. Companion's grid must be at least 4×3; use *Resize grid to fit* if Companion offers it.
  - **Bottom-row keys** in the demo layout: layer switch, `◀ Page` / `Page ▶` (`companion_page`, which pages through the allowed pages), and `Overlay opacity` (`overlay` cycle: 90 % → 60 % → 30 % → hidden). Page keys need Companion 4.3+ (Satellite API 1.10). The overlay header shows the surface's current page (`Companion p.4`).

The Satellite connection comes from the host app, so a Companion layer needs the app (or `cuekeys overlay` / `cuekeys bridge`) running.

## Command line

```bash
cuekeys                         # editor (last opened layout)
cuekeys gui layout.json         # editor with a file
cuekeys overlay layout.json     # overlay + bridge only
cuekeys bridge layout.json -v   # headless bridge (OSC / grandMA / Companion)
cuekeys init --example demo.json
cuekeys validate layout.json
cuekeys deploy layout.json [--drive /Volumes/CIRCUITPY] [--keypad FOH]
cuekeys install-firmware [layout.json] [--drive …] [--keypad …] [--no-boot]
cuekeys devices                 # CIRCUITPY drives (+ matching profile) and serial ports, with keypad ids
cuekeys keypads                 # connected and remembered keypads
cuekeys keypads rename e35b8c2b FOH
cuekeys keypads assign FOH show.json   # layout this keypad uses (omit the file to clear)
cuekeys profiles                # supported keypad models, and your plugin folder
```

## Several keypads

Plug in as many keypads as you like; CueKeys finds each one by its hardware id (the RP2040's unique
id, which is also its USB serial number).

- **Editor:** pick the keypad in the toolbar. Each keypad has its own layout, so opening or saving a
  file assigns it to the selected keypad; keypads can share one file. *Deploy*, *Install firmware*
  and *LED colour balance* act on the selected keypad.
- **Overlay:** one per keypad, stacked in the corner and labelled with the keypad's name.
- **Companion:** every Companion layer of every keypad is its own surface, `ck-<keypad>-<layer>`
  (for example `ck-e35b8c2b-example`), so the same layout on two keypads can show different pages.
- **Per keypad, not per layout:** its name, its layout file, and its LED calibration, stored in
  `keypads.json` in the CueKeys config folder. Rename a keypad under **Keypad → Rename keypad…**.

`--port` on `gui`, `overlay` and `bridge` limits CueKeys to the keypad on that port.

## Keypad ↔ host protocol

Newline-separated JSON over the CircuitPython `usb_cdc.data` port. The full message reference is in
[docs/protocol.md](docs/protocol.md).

## Documentation

| For | Read |
|---|---|
| Adding a keypad (device profiles, firmware drivers) | [docs/devices.md](docs/devices.md) |
| How it fits together | [docs/architecture.md](docs/architecture.md) |
| Serial protocol and layout file format | [docs/protocol.md](docs/protocol.md) |
| Recipes: new actions, bridges, settings, CLI commands | [docs/extending.md](docs/extending.md) |
| Companion integration details and quirks | [docs/companion.md](docs/companion.md) |
| macOS / Windows / Linux / CircuitPython notes | [docs/platform-notes.md](docs/platform-notes.md) |
| Known gaps and good next tasks | [docs/roadmap.md](docs/roadmap.md) |
| Contributing, testing, releases | [CONTRIBUTING.md](CONTRIBUTING.md) |
| AI coding agents (orientation, invariants, gotchas) | [AGENTS.md](AGENTS.md) |
| What changed | [CHANGELOG.md](CHANGELOG.md) |

## Development

```bash
pip install -e ".[dev]"
pytest            # includes the firmware engine, run on desktop Python
ruff check .
```

- `firmware/lib/cuekeys_drivers/` holds the hardware drivers. `src/cuekeys/devices/` holds the device profiles that pick them.
- `firmware/lib/cuekeys_engine/` is plain Python that doesn't depend on any hardware. It runs on the keypad and in the tests, with a fake clock and a fake backend.
- `src/cuekeys/config.py` holds the schema. The editor forms and validation are generated from `ACTION_SPECS`. A test checks that the firmware and the host support the same action types.
- `firmware/config.json` is the starter layout. It is generated from `examples.py`, and a test keeps the two in sync.

### CI/CD (GitHub Actions and GitLab CI)

The same pipeline is defined twice, so the project can live on GitHub, GitLab, or both:

| | GitHub | GitLab |
|---|---|---|
| Every push / PR | `.github/workflows/ci.yml`: ruff; pytest on Linux × Python 3.10–3.13 plus macOS and Windows; wheel and firmware zip | `.gitlab-ci.yml` lint / test / build stages |
| Tags `vX.Y.Z` | `.github/workflows/release.yml`: desktop apps for Linux, Windows and macOS, the wheel and the firmware zip, published as a GitHub Release; optional PyPI publishing via trusted publishing (set the repository variable `PUBLISH_PYPI=true`) | package and release stages: GitLab Release and Generic Package Registry |

Notes:
- GitHub's hosted macOS and Windows runners are free for public repos.
- On GitLab, macOS runners need Premium. Otherwise set `MACOS_RUNNER_TAG` to a self-hosted Mac.
- The firmware zip build uses `GITHUB_TOKEN`, which is automatic on GitHub, to avoid API rate
  limits. Set `ADAFRUIT_BUNDLE` / `PMK_REF` to pin library versions.

To release: bump `__version__` in `src/cuekeys/__init__.py`, update `CHANGELOG.md`, then tag `vX.Y.Z` and push the tag.

## License

CueKeys is **source-available**: free for **non-commercial** use under the
[PolyForm Noncommercial License 1.0.0](LICENSE). **Commercial use** needs a separate commercial
license; see [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md) for what counts as commercial and how to
get one. Third-party components keep their own licenses (PySide6/Qt under LGPL-3.0, pyserial under
BSD, the CircuitPython libraries under MIT); see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

This project isn't affiliated with or endorsed by Pimoroni, Adafruit, Bitfocus or MA Lighting.
Product names are used only to describe compatibility.

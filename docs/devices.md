# Adding a keypad

PMK Macro Manager isn't tied to Pimoroni hardware. Any CircuitPython board can be used: RP2040, RP2350, ESP32-S3, SAMD51 and so on. It needs native USB HID, and ideally two USB CDC ports for the host link. Each keypad model is described by a **device profile**.

A profile is a folder containing a `device.json`. It can also contain a `driver.py` if the built-in drivers don't fit your hardware.

```
my_pad/
  device.json    # required: grid, driver, libraries
  driver.py      # optional: custom firmware driver
```

## Where profiles are loaded from

Profiles are loaded in this order. When two profiles share an `id`, the later one wins.

1. **Built in**: `src/pmk_macro_manager/devices/builtin/`.
2. **Python packages** that declare an entry point in the `pmk_macro_manager.devices` group. The entry point should return a folder, or a list of folders:
   ```toml
   [project.entry-points."pmk_macro_manager.devices"]
   my-pads = "my_pads:profile_dirs"
   ```
3. **Your plugin folder**. `pmm profiles` prints its path:
   - macOS: `~/Library/Application Support/pmk-macro-manager/devices`
   - Windows: `%APPDATA%\pmk-macro-manager\devices`
   - Linux: `~/.config/pmk-macro-manager/devices`
4. **`$PMM_DEVICE_PATH`**: one or more folders, separated by `:` (`;` on Windows).

Each of these folders can hold profile folders (`<id>/device.json`) or plain `*.json` files.

To check your profile, run `pmm profiles`. It lists every profile it loaded and prints an error for each one it couldn't.

## `device.json`

```json
{
  "id": "diy_rp2040_3x3",
  "name": "DIY RP2040-Zero 3x3",
  "vendor": "Example",
  "board_ids": ["waveshare_rp2040_zero"],
  "grid": [[0, 1, 2],
           [3, 4, 5],
           [6, 7, 8]],
  "leds": "rgb",
  "connector": "top",
  "driver": "keypad_keys",
  "driver_config": {"pins": ["GP0", "GP1", "GP2", "GP3", "GP4", "GP5", "GP6", "GP7", "GP8"],
                    "pixels": {"pin": "GP16", "count": 9}},
  "libraries": ["neopixel"]
}
```

| Field | Meaning |
|---|---|
| `id` | Unique, stable id. It's stored in layouts. |
| `name`, `vendor`, `description` | Shown in the app. |
| `board_ids` | CircuitPython board ids, used to detect the keypad. The id is the `Board ID:` line in `CIRCUITPY/boot_out.txt`. |
| `grid` | The key numbers as they appear on the physical pad, **top row first**, with `null` for gaps. Keys must be numbered `0…n-1`. Any size or shape works: 3×4, 5×5, 2×8, and so on. |
| `leds` | `"rgb"` (one colour per key) or `"none"`. |
| `connector` | The side the USB port is on in the grid as drawn: `top`, `right`, `bottom` or `left`. The editor shows it as a hint. |
| `driver` | The firmware driver module in `CIRCUITPY/lib/pmkdrivers/`. |
| `driver_config` | Passed to the driver unchanged. |
| `libraries` | Extra `CIRCUITPY/lib` libraries the driver needs. `adafruit_hid` is always required. |
| `tested` | Set this to `true` once you've confirmed the profile works on real hardware. Untested profiles are labelled as such in the app. |

Everything else adapts to the grid: the editor, the overlay, validation, and Companion surfaces. For example, a Companion layer on a 3-wide pad registers as a 3×N surface.

## Built-in drivers

| Driver | For | `driver_config` |
|---|---|---|
| `keypad_keys` | One GPIO pin per key | `pins`, `value_when_pressed` (false = the key pulls the pin to GND), `pull`, `key_map`, `pixels` |
| `keypad_matrix` | A diode matrix | `rows`, `columns`, `columns_to_anodes`, `key_map`, `pixels` |
| `pmk_keybow2040` | Pimoroni Keybow 2040 | none |
| `pmk_rgbkeypad` | Pimoroni Pico RGB Keypad Base | none |

Details for the two generic drivers:
- **Pin names** are the names in CircuitPython's `board` module, such as `GP0` or `KEY1`.
- **`pixels`** takes `{"pin", "count", "order", "brightness", "map"}` for WS2812/NeoPixel LEDs. `map` gives the pixel index for each key number, with `null` for keys that have no LED.
- **`key_map`** maps the physical input order (pin index, or matrix `row * columns + col`) to key numbers. It's the way to match how your switches are wired to the grid's numbering.
- **Debouncing and event queuing** are done by CircuitPython's `keypad` module.

## Writing a driver

If your hardware needs something else, such as an I/O expander, a shift register, or a different LED chip, put a `driver.py` next to `device.json`. **Install / update firmware** copies it onto the keypad as `lib/pmkdrivers/<driver>.py`.

```python
class Hardware:
    def __init__(self, config):        # config = driver_config (+ "debounce_ms")
        self.num_keys = 9
        self.has_leds = True

    def poll(self, now_ms):            # -> [(key, pressed), ...] changes since last call
        return []

    def set_led(self, key, rgb):       # rgb = (r, g, b) 0-255, brightness already applied
        pass

    def show(self):                    # flush buffered LED writes, once per loop
        pass
```

Keep the driver to plain CircuitPython: no f-strings with `=`, no dataclasses, no typing. `firmware/lib/pmkdrivers/keypad_keys.py` is a short example to copy from. You can unit-test a driver on desktop Python by stubbing `board`, `keypad` and `neopixel`, as `tests/test_drivers.py` does.

## Sharing a profile

To add a profile to the project, open a merge request with:
- the profile under `src/pmk_macro_manager/devices/builtin/<id>/`;
- the driver under `firmware/lib/pmkdrivers/`, if it needs a new one;
- a line in the README's supported-devices table.

The test suite automatically checks that every built-in profile loads, that its driver exists, and that the demo layout remaps onto it.

## Supported devices

| Profile | Size | Driver | Status |
|---|---|---|---|
| `keybow2040`: Pimoroni Keybow 2040 | 4×4 | `pmk_keybow2040` | Tested |
| `rgbkeypad`: Pimoroni Pico RGB Keypad Base | 4×4 | `pmk_rgbkeypad` | Untested |
| `adafruit_macropad`: Adafruit MacroPad RP2040 | 3×4 | `keypad_keys` | Untested; the encoder and OLED aren't used yet |
| `examples/devices/diy_rp2040_3x3` | 3×3 | `keypad_keys` | Example to copy |

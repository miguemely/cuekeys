# Keypad ↔ host protocol

**Transport:** the keypad's second USB CDC serial port, `usb_cdc.data`. `firmware/boot.py` enables it,
and it appears after a hard reset.

**Framing:** one JSON object per line (`\n`), UTF-8. Every message has a `"t"` (type) field. Unknown
types and unknown fields must be ignored, which keeps old and new firmware and hosts compatible.

**Finding the port:** the host picks the port whose USB interface name contains "data"
(Linux/macOS). On Windows it takes the higher-numbered of the two ports that share one USB serial
number (`device.find_data_port`). Override it with `--port`.

**Connecting:** on connect, the host sends `os`, then `hello?`. The keypad also sends `hello` by itself
whenever the port (re)connects.

## Keypad → host

| `t` | Fields | Meaning |
|---|---|---|
| `hello` | `fw` (version), `uid` (hardware id, = USB serial number), `profile`, `num_keys`, `config_error` (string or null) | Keypad is up. The host re-pushes Companion LED colours after this |
| `layer` | `i`, `name`, `count` | Current layer changed (or was announced) |
| `key` | `k` key number, `s` 1 = pressed / 0 = released, `l` layer at the time | Every physical (or host-injected) key edge |
| `osc` | `addr`, `args` (list), `target` (name in `bridge.osc_targets`) | Send an OSC message |
| `ma` | `cmd`, `console` (`ma3` or `ma2`) | Run a grandMA command line |
| `companion` | `page`, `row`, `column`, `op` (`down`/`up`/`press`), `target` | Press a Companion button over HTTP |
| `companion_page` | `l` layer, `dir` 1 = next / 0 = previous | Page the Companion surface of layer `l` |
| `overlay` | `op` (`cycle`/`toggle`/`show`/`hide`), `levels` (list or null) | Control the on-screen overlay |
| `host` | `event`, `data` | Custom event for host listeners (`session.emit("host", …)`) |
| `log` | `level`, `msg` | An action failed on the keypad (never fatal) |

## Host → keypad

| `t` | Fields | Effect |
|---|---|---|
| `hello?` | none | Keypad replies with `hello` and `layer` |
| `os` | `os`: `mac` / `windows` / `linux` | Resolves the `PRIMARY` modifier (Cmd on mac, Ctrl elsewhere) |
| `layer` | `i` | Switch layer (editor "Sync selected layer", overlay scroll) |
| `press` / `release` | `k` | Inject a key press or release (overlay clicks) |
| `led` | `l` layer, `k` key, `rgb` [r, g, b] | Companion button colour for a key on a Companion layer |
| `led_cal` | `gamma`, `balance` [r, g, b] (0-1) | Live LED colour correction (calibration dialog) |
| `led_test` | `rgb` (`"#rrggbb"`, [r, g, b] or null) | Show one colour on every key; null goes back to the layout |
| `reload` | none | `supervisor.reload()`: restart the firmware |

## Adding a message

1. Keypad → host: send it from the engine (`backend.host({...})`) or from `code.py`. Handle it in
   `KeypadSession._on_message`, and emit an event if the UI cares.
2. Host → keypad: send it with `session.link.send({...})`. Handle it in `code.py`'s message loop and
   put the logic in the engine, so it's testable.
3. Keep it backward compatible: new optional fields are fine. Don't change the meaning of existing
   fields.
4. Add a row to this file and a test (`test_engine.py` for keypad behaviour, `test_runtime.py` for
   host handling).

## Layout file (`config.json` / `*.json`)

Schema summary; `config.py` is authoritative.

```jsonc
{
  "version": 1,
  "device": {                         // → keypad
    "profile": "keybow2040",          // device profile id (docs/devices.md)
    "brightness": 0.5, "hold_time_ms": 500, "debounce_ms": 15, "midi_channel": 1,
    "keyboard_layout": "us", "host_os": "auto", "pressed_color": "#ffffff",
    "led_gamma": 2.2, "led_balance": [1, 1, 1]      // optional; override the profile
    // deploy adds: driver, driver_config, num_keys (resolved from the profile)
  },
  "layers": [{                        // → keypad
    "name": "Main", "color": "#3050ff", "mode": "local",   // or "companion"
    "companion_id": "ck-…", "companion_target": "default", "companion_rows": 3,
    "keys": {"0": {"label": "…", "color": "#…", "press": [ACTION], "release": [ACTION], "hold": [ACTION]}}
  }],
  "bridge": {                         // host only
    "osc_targets": {"default": {"host": "127.0.0.1", "port": 8000}},
    "ma3": {"host": "…", "port": 8000, "prefix": "gma3"},
    "ma2": {"host": "…", "port": 30000, "user": "administrator", "password": ""},
    "companion": {"default": {"host": "127.0.0.1", "http_port": 8000, "satellite_port": 16622}}
  },
  "overlay": {                        // host only
    "enabled": true, "opacity": 0.8, "corner": "bottom-right", "margin": 24, "key_size": 64,
    "click_through": true, "all_spaces": true, "rotation": 0,
    "screens": "primary"              // "primary" | "all" | "mouse" | ["Display name", …]
  }
}
```

The action types and their fields are listed in the README's action reference and defined in
`config.ACTION_SPECS`.

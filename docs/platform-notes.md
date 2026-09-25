# Platform notes

Things that are non-obvious per OS, CircuitPython or tooling, and how the code handles them.

## macOS

### Overlay on every Space and over full-screen apps (`gui/macos.py`)

Qt can't do this, so the overlay's `NSWindow` is modified through the Objective-C runtime with
`ctypes` (no PyObjC dependency). It's applied in `OverlayWindow.showEvent()` every time, because Qt
recreates the native window when window flags change.

| Setting | Why |
|---|---|
| `collectionBehavior` \|= `CanJoinAllSpaces \| Stationary \| IgnoresCycle \| FullScreenAuxiliary` | Visible on every Space (Ctrl+←/→), not moved by Mission Control, not in Cmd+` cycling, allowed next to full-screen apps |
| clear `MoveToActiveSpace \| Managed \| Transient` first | Qt sets `MoveToActiveSpace` on tool windows, and AppKit **throws** (killing the app) if it's combined with `CanJoinAllSpaces`. Managed/Transient/Stationary are mutually exclusive |
| `styleMask` \|= `NonactivatingPanel` (only if the window `isKindOfClass: NSPanel`) | A regular app's window is only allowed into **another app's full-screen Space** if it's a non-activating panel. Qt makes `Qt::Tool` windows `NSPanel`s but not non-activating ones |
| `level` = 25 (`NSStatusWindowLevel`) | Floats above normal and full-screen app windows |

**Guard:** `macos.available()` requires `QGuiApplication.platformName() == "cocoa"`. Under the
offscreen platform (tests), `winId()` isn't an `NSView`, and messaging it segfaults.

**How it was verified:** a probe script showed the overlay, launched a second process that went full
screen, and read `NSWindow.isOnActiveSpace` (False before the style-mask fix, True after). Reuse this
approach to check any future window-level change, because unit tests can't see Spaces.

### Other macOS notes

- `Qt.WA_MacAlwaysShowToolWindow` stops tool windows hiding when the app is in the background.
- In Qt's macOS key events, `Qt.ControlModifier` is **Cmd** and `Qt.MetaModifier` is Ctrl. The macro
  recorder maps Cmd to `PRIMARY` (see `gui/actions.py`).
- USB serial port interface names aren't exposed, so the data port is found by grouping ports by
  serial number.

## Windows

- COM ports carry no interface names. The data port is the second port with the keypad's USB serial
  number (`device.find_data_port`). Use `--port COMx` if detection picks the wrong one.
- The CIRCUITPY drive is found through `GetVolumeInformationW` volume labels.
- **Not done yet:** keeping the overlay on every virtual desktop (Windows has no public API for
  pinning another process's windows to all desktops).

## Linux

- On Wayland sessions the app sets `QT_QPA_PLATFORM=xcb` (XWayland) unless you've set it yourself,
  because Wayland doesn't let clients stay on top or position their own windows.
- CIRCUITPY drives are found through `/proc/mounts` and `/media/<user>`, `/run/media/<user>`.
- **Not done yet:** "sticky" on all workspaces (`_NET_WM_STATE_STICKY`).

## Multiple displays

`Overlay` creates one `OverlayWindow` per target display. `overlay.screens` is one of:
- `"primary"`;
- `"all"`;
- `"mouse"` (polled every 400 ms);
- a list of display names from `screen_names()`, e.g. `"DELL U2720Q"`, or `"DELL U2720Q #2"` for
  identical models.

It rebuilds when displays are added or removed, or the main display changes. If none of the chosen
displays are connected, it falls back to the main display.

## CircuitPython

- **Supported Python subset:** no `dataclasses`, `typing`, `functools.partial` or `enum`.
  `__import__("pkg.mod")` returns the top-level package, so use `getattr(pkg, "mod")`.
- **Time:** floats lose precision on long uptimes, so use `time.monotonic_ns() // 1_000_000` for
  integer ms.
- **`boot.py` only takes effect after a hard reset** (unplugging). `usb_cdc.enable(console=True,
  data=True)` gives the REPL port plus the data port the app uses.
- **Auto-reload:** writing any file on CIRCUITPY restarts `code.py`. Deploys rely on this.
- **Debugging:** open the console port (the *other* CDC port) at 115200. Ctrl+C then Ctrl+D
  soft-reloads and prints tracebacks. `pmm` doesn't use the console port.
- **Libraries:** the firmware zip uses Adafruit's **py** bundle (not mpy), so it works on any
  CircuitPython major version, at the cost of a little RAM.

## LEDs

- The PMK / IS31FL3731 PWM is linear, but eyes aren't. Without gamma correction, mid-tones wash
  out: `#20c050` looked cyan on the Keybow 2040. The default gamma is 2.2.
- Channel brightness varies by LED type. On the tested Keybow 2040, equal R=G=B looked pink/purple.
  Per-profile `led_balance` defaults, per-layout overrides and **Keypad → LED colour balance…**
  handle it.
- `engine.color_lut()` builds 256-entry `bytearray` tables per channel (brightness × gamma ×
  balance), so the correction costs nothing per frame.

## Development environment

- `pip` behind a TLS-intercepting proxy or sandbox can fail with `SSLCertVerificationError`. Install
  outside the sandbox.
- Sandboxes that forbid binding local sockets make the socket-based tests fail with
  `PermissionError`.
- Writing to `/Volumes/CIRCUITPY` from a sandboxed shell fails with `Operation not permitted`.

# Troubleshooting

## The Keypad pill stays red ("No keypad connected")

Work down this list:

1. **Did you unplug and replug the keypad after installing the firmware?** The firmware's `boot.py`
   turns on the serial port CueKeys uses, and only a real restart applies it. Pressing reset or
   saving files isn't enough.
2. **Try another USB cable.** Many cables only carry power. If the **CIRCUITPY** drive doesn't
   appear either, the cable (or port) is the problem.
3. **Is something else using the keypad's serial port?** A serial monitor, Mu, Thonny, or a second
   copy of CueKeys can hold it open. Close them.
4. **Check what CueKeys sees.** From a terminal:

   ```bash
   cuekeys devices
   ```

   You should see a `serial` line with your keypad's ID. No `serial` line but a `drive` line means
   the firmware's `boot.py` hasn't taken effect: see step 1.
5. **Linux: permission to use serial ports.** Add yourself to the serial group, then log out and in
   again:

   ```bash
   sudo usermod -aG dialout "$USER"      # Arch Linux: uucp instead of dialout
   ```

6. **Windows: wrong COM port.** Each keypad has two COM ports and Windows doesn't say which is which.
   If CueKeys picks the wrong one, start it with the other: `cuekeys gui --port COM7`.

## The keypad is connected but its keys are ignored

CueKeys only accepts a keypad that tells it its hardware ID, so one device can't pose as another.
The status bar says why a keypad was ignored:

- **"…runs older firmware without a keypad id"**: update the firmware with
  **Keypad → Install / update firmware…**, then unplug and replug the keypad.
- **"…reports id X, but its USB port belongs to Y"**: the firmware and the USB port disagree about
  which keypad this is, which shouldn't happen with CueKeys firmware on a normal board. Reinstall the
  firmware; if it persists, open an issue.

## My changes don't reach the keypad

- Colour changes show straight away, but **what a key does only changes after Deploy to keypad**
  (the button shows **•** while there are undeployed changes). See
  [Colours and LEDs](colours-and-leds.md#changes-show-on-the-keypad-straight-away).
- If the status bar says **keypad config error**, the keypad couldn't read the layout; the message
  says why. **Deploy** checks the layout first and lists anything it can't use (*Fix these first*);
  from a terminal, `cuekeys validate my-layout.json` does the same.
- **Deploy says the drive is read-only (macOS).** Recent macOS versions sometimes mount the
  **CIRCUITPY** drive read-only. Remount it writable from Terminal. Find the disk name with
  `diskutil list` (the `CIRCUITPY` volume, e.g. `disk4s1`), then:

  ```bash
  diskutil unmount /Volumes/CIRCUITPY
  sudo mkdir -p /Volumes/CIRCUITPY
  sudo mount -v -o noasync -t msdos /dev/disk4s1 /Volumes/CIRCUITPY
  ```

  Unplugging and replugging the keypad goes back to the normal (possibly read-only) mount.

## Keys type the wrong characters

**Type text** assumes a US keyboard layout. Set **Settings → Keypad → Keyboard layout** to your
layout (e.g. `win_de`, `mac_fr`) and copy the matching `keyboard_layout_*` file from the CircuitPython
community bundle to the keypad's `lib` folder. Key combos (`PRIMARY+S` …) aren't affected.

Shortcuts use Cmd on a Mac and Ctrl elsewhere only if they use `PRIMARY` and CueKeys knows which
computer the keypad is plugged into. Without the app running, set **Settings → Keypad → Host OS**.

## Colours look wrong on the keypad

White looks pink, green looks cyan: run **Keypad → LED colour balance…**. See
[Colours and LEDs](colours-and-leds.md#led-colour-balance).

A layer colour that doesn't change some keys: those keys have their own colour. Right-click them →
**Same as layer**.

## The overlay isn't on top, or disappears

- **macOS:** turn on **Settings → Overlay → All desktops + full-screen apps** to keep it on every
  Space and above full-screen apps.
- **Windows:** it stays on the virtual desktop where it opened.
- **Linux (Wayland):** CueKeys uses XWayland for the overlay. If you set `QT_QPA_PLATFORM` yourself,
  set it to `xcb`.
- It's hidden if **Show overlay** is off for the layout, or if an overlay key cycled it to 0 %: press
  that key again, or click **Overlay** in the toolbar.

## Companion

| The Companion pill is… | Meaning | Fix |
|---|---|---|
| red | CueKeys can't reach Companion | check the host and ports in **Settings → OSC & Companion**, and that Companion is running |
| amber (*busy*) | Companion refused the surface because a surface with the same ID is already connected | usually the same keypad connected from another computer or a second copy of CueKeys; close the other one |
| green | connected | |

**Page keys do nothing:** they need Companion 4.3 or newer, and the surface must be allowed more than
one page (see [Companion, step 3](companion.md#3-give-the-surface-its-own-pages-in-companion)).

## Seeing what the firmware is doing

The keypad has a second serial port, the CircuitPython console. Open it at 115200 baud (for example
`screen /dev/cu.usbmodem1201 115200` on a Mac, or PuTTY on Windows) and press Ctrl+C, then Ctrl+D:
the keypad restarts and prints any error with its line number. CueKeys doesn't use that port, so you
can keep the app open.

## The app won't open (macOS)

The app isn't code-signed yet. Right-click **CueKeys** → **Open**, then **Open** again. If macOS says
the app is damaged, it was quarantined when you downloaded it:

```bash
xattr -dr com.apple.quarantine /Applications/CueKeys.app
```

## Still stuck?

Open an issue on the project's GitHub page with what you tried, the output of `cuekeys devices`, and
your operating system.

# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Runs once at power-up, before USB is set up. Changes here need a hard reset
# (unplug/replug) to take effect.
import usb_cdc
import usb_midi

# Console = REPL (for debugging); data = JSON-lines link to the host app.
usb_cdc.enable(console=True, data=True)
usb_midi.enable()

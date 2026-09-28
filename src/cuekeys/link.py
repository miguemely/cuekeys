# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
"""JSON-lines link to the keypad over its usb_cdc data port."""

import json
import logging
import sys
import threading

from . import device

log = logging.getLogger(__name__)

MAX_LINE_BYTES = 64 * 1024
MAX_READ_BYTES = 4 * 1024


def host_os():
    if sys.platform == "darwin":
        return "mac"
    if sys.platform == "win32":
        return "windows"
    return "linux"


class DeviceLink:
    """Background reader with automatic (re)connection.

    ``on_message(dict)`` is called from the reader thread for every line the
    keypad sends; ``on_status(connected: bool, port: str | None)`` on changes.
    """

    def __init__(self, port=None, on_message=None, on_status=None, retry=2.0):
        self.fixed_port = port
        self.on_message = on_message or (lambda msg: None)
        self.on_status = on_status or (lambda connected, port: None)
        self.retry = retry
        self.serial = None
        self.port = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    @property
    def connected(self):
        return self.serial is not None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="cuekeys-link", daemon=True)
            self._thread.start()

    def set_port(self, port):
        """Follow the keypad to a new port name (re-plugged); reconnects on the next retry."""
        self.fixed_port = port
        self._close()

    def stop(self):
        self._stop.set()
        self._close()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def send(self, message):
        data = (json.dumps(message) + "\n").encode("utf-8")
        with self._lock:
            if self.serial is None:
                return False
            try:
                self.serial.write(data)
                return True
            except Exception as err:  # noqa: BLE001 - any serial error means disconnect
                log.warning("write failed: %s", err)
                return False

    # ------------------------------------------------------------ internals
    def _open(self):
        import serial

        port = self.fixed_port or device.find_data_port()
        if not port:
            return False
        try:
            ser = serial.Serial(port, 115200, timeout=0.2)
        except (serial.SerialException, OSError) as err:
            log.debug("open %s failed: %s", port, err)
            return False
        with self._lock:
            self.serial, self.port = ser, port
        log.info("connected to keypad on %s", port)
        self.on_status(True, port)
        self.send({"t": "os", "os": host_os()})
        self.send({"t": "hello?"})
        return True

    def _close(self):
        with self._lock:
            ser, self.serial = self.serial, None
        if ser is not None:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass
            self.on_status(False, None)

    def _run(self):
        buffer = b""
        while not self._stop.is_set():
            if self.serial is None and not self._open():
                self._stop.wait(self.retry)
                continue
            try:
                chunk = self.serial.read(min(self.serial.in_waiting or 1, MAX_READ_BYTES))
            except Exception as err:  # noqa: BLE001
                log.info("keypad disconnected: %s", err)
                self._close()
                buffer = b""
                continue
            if not chunk:
                continue
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if len(line) > MAX_LINE_BYTES:
                    log.warning("discarding oversized line from keypad")
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    log.debug("bad line from keypad: %r", line)
                    continue
                if not isinstance(msg, dict):
                    log.debug("ignoring non-object message from keypad")
                    continue
                try:
                    self.on_message(msg)
                except Exception:  # noqa: BLE001
                    log.exception("message handler failed")
            if len(buffer) > MAX_LINE_BYTES:
                log.warning("discarding oversized unterminated line from keypad")
                buffer = b""

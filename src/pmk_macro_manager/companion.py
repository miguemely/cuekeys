"""Bitfocus Companion integration.

Two ways to drive Companion:

* :func:`http_button` - press/release a specific button through the HTTP remote
  API (``POST /api/location/<page>/<row>/<column>/<down|up|press>``).
* :class:`SatelliteClient` - register keypad layers as Companion *Satellite*
  surfaces (TCP, default port 16622). Companion then decides what every key
  does and pushes back each button's colour and text, which the host shows on
  the overlay and mirrors to the keypad LEDs.
"""

import base64
import logging
import re
import socket
import threading
import time
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

HTTP_OPS = ("down", "up", "press")


def http_button(host, port, page, row, column, op="press", timeout=2.0):
    if op not in HTTP_OPS:
        raise ValueError("op must be one of %s" % ", ".join(HTTP_OPS))
    url = "http://%s:%d/api/location/%s/%d/%d/%s" % (host, int(port), page, int(row), int(column), op)
    req = urllib.request.Request(url, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


def variable_value(host, port, connection, name, timeout=2.0):
    """Read a Companion variable, e.g. ("internal", "page_number_4_name")."""
    url = "http://%s:%d/api/variable/%s/%s/value" % (
        host, int(port), urllib.parse.quote(connection), urllib.parse.quote(name))
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace").strip()


def page_name(host, port, page, timeout=2.0):
    return variable_value(host, port, "internal", "page_number_%d_name" % int(page), timeout)


# ------------------------------------------------------------------ satellite
_PARAM = re.compile(r'([A-Za-z_]+)=("(?:[^"\\]|\\.)*"|\S*)')


def parse_line(line):
    """``'KEY-STATE DEVICEID=x KEY=3 TEXT="..."'`` -> ("KEY-STATE", {...})."""
    line = line.strip()
    if not line:
        return None, {}
    command, _, rest = line.partition(" ")
    params = {}
    for name, value in _PARAM.findall(rest):
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        params[name] = value
    return command, params


def parse_color(value):
    """"#rrggbb" or "rgb(r,g,b)" -> (r, g, b); None if unparseable."""
    if not value:
        return None
    value = value.strip()
    if value.startswith("#") and len(value) == 7:
        try:
            return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            return None
    match = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", value)
    if match:
        return tuple(min(255, int(x)) for x in match.groups())
    return None


def parse_version(text):
    parts = []
    for piece in (text or "").split(".")[:3]:
        digits = re.match(r"\d+", piece)
        parts.append(int(digits.group()) if digits else 0)
    return tuple(parts + [0] * (3 - len(parts)))


# Satellite API 1.10 (Companion 4.3 / 5.x) added CHANGE-PAGE and the CAPS line
# the server sends right after BEGIN; it ignores ADD-DEVICE sent before CAPS.
CHANGE_PAGE_API = (1, 10, 0)
CAPS_API = (1, 10, 0)
ADD_TIMEOUT = 5.0


def decode_text(value):
    try:
        return base64.b64decode(value).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return value


class SatelliteClient:
    """Keeps one TCP connection to Companion and registers N 4x4 surfaces.

    ``on_key_state(device_id, index, state)`` receives
    ``{"color", "text", "text_color", "type", "pressed"}`` (only the fields
    Companion sent so far); ``on_status(connected: bool)`` is called on
    (dis)connect and whenever a surface registration succeeds or fails
    (see ``registered``).
    """

    def __init__(self, host, port=16622, on_key_state=None, on_status=None,
                 keys_per_row=4, retry=3.0):
        self.host, self.port = host, int(port)
        self.on_key_state = on_key_state or (lambda *a: None)
        self.on_status = on_status or (lambda connected: None)
        self.keys_per_row = keys_per_row
        self.retry = retry
        self.api_version = (0, 0, 0)
        self.devices = {}          # device_id -> (product name, keys_total)
        self.registered = {}       # device_id -> True (OK) / False (rejected, retrying)
        self.states = {}           # (device_id, index) -> state
        self._retry_at = {}        # device_id -> monotonic time to retry a rejected ADD
        self._pending = {}         # device_id -> monotonic time an ADD was sent (no reply yet)
        self._ready = False        # handshake done (BEGIN, and CAPS on newer servers)
        self.sock = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    @property
    def connected(self):
        return self.sock is not None

    @property
    def can_change_page(self):
        return self.api_version >= CHANGE_PAGE_API

    def add_device(self, device_id, name, keys_total=16):
        known = device_id in self.devices
        self.devices[device_id] = (name, int(keys_total))
        if self.sock is not None and self._ready:
            if known:
                # Companion rejects a second ADD for a live ID; re-add to change it.
                self._send("REMOVE-DEVICE DEVICEID=%s" % device_id)
                for key in [k for k in self.states if k[0] == device_id]:
                    del self.states[key]
            self._register(device_id)

    def change_page(self, device_id, forward=True):
        """Next/previous Companion page on this surface. False if unsupported."""
        if not self.can_change_page:
            log.warning("Companion page change needs Satellite API 1.10+ (Companion 4.3+); "
                        "server has %s", ".".join(map(str, self.api_version)))
            return False
        return self._send("CHANGE-PAGE DEVICEID=%s DIRECTION=%d" % (device_id, 1 if forward else 0))

    def remove_device(self, device_id):
        if self.devices.pop(device_id, None) is not None:
            self.registered.pop(device_id, None)
            self._retry_at.pop(device_id, None)
            self._send("REMOVE-DEVICE DEVICEID=%s" % device_id)

    def key_press(self, device_id, index, pressed):
        self._send("KEY-PRESS DEVICEID=%s KEY=%d PRESSED=%s"
                   % (device_id, index, "true" if pressed else "false"))

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="companion-satellite",
                                            daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        for device_id in list(self.devices):
            self._send("REMOVE-DEVICE DEVICEID=%s" % device_id)
        self._close()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    # ----------------------------------------------------------- internals
    def _send(self, line):
        if not line.startswith(("PING", "PONG", "KEY-PRESS")):
            log.debug("companion -> %s", line[:200])
        with self._lock:
            if self.sock is None:
                return False
            try:
                self.sock.sendall((line + "\n").encode("utf-8"))
                return True
            except OSError:
                return False

    def _register(self, device_id):
        name, keys_total = self.devices[device_id]
        extra = " CAN_CHANGE_PAGE=true" if self.can_change_page else ""
        self._pending[device_id] = time.monotonic()
        self._send('ADD-DEVICE DEVICEID=%s PRODUCT_NAME="%s" KEYS_TOTAL=%d KEYS_PER_ROW=%d '
                   'BITMAPS=0 COLORS=hex TEXT=true TEXT_STYLE=true%s'
                   % (device_id, name.replace('"', "'"), keys_total, self.keys_per_row, extra))

    def _close(self):
        self.registered.clear()
        self._retry_at.clear()
        self._pending.clear()
        self._ready = False
        with self._lock:
            sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
            self.on_status(False)

    def handle_line(self, line):
        command, params = parse_line(line)
        if command not in ("KEY-STATE", "PING", "PONG", None):
            log.debug("companion <- %s", line.strip()[:200])
        if command == "BEGIN":
            self.api_version = parse_version(params.get("ApiVersion"))
            if self.api_version < CAPS_API:
                self._handshake_done()
        elif command == "CAPS":
            self._handshake_done()
        elif command == "PING":
            self._send("PONG " + line.strip()[5:])
        elif command == "ADD-DEVICE":
            device_id = params.get("DEVICEID")
            ok = line.split()[1:2] == ["OK"]
            self._pending.pop(device_id, None)
            if device_id in self.devices:
                self.registered[device_id] = ok
                if ok:
                    self._retry_at.pop(device_id, None)
                    log.info("Companion surface %s registered", device_id)
                else:
                    # Usually a stale session from a previous run; Companion drops
                    # it after its keep-alive timeout, so keep trying.
                    log.warning("Companion rejected surface %s: %s (retrying)",
                                device_id, params.get("MESSAGE", ""))
                    self._retry_at[device_id] = time.monotonic() + max(self.retry, 10)
                self.on_status(True)
        elif command == "KEY-STATE":
            device_id = params.get("DEVICEID")
            try:
                index = int(params.get("KEY", "-1"))
            except ValueError:
                return  # row/column addressing is only used if we ask for it
            state = dict(self.states.get((device_id, index), {}))
            if "COLOR" in params:
                state["color"] = parse_color(params["COLOR"])
            if "TEXT" in params:
                state["text"] = decode_text(params["TEXT"])
            if "TEXTCOLOR" in params:
                state["text_color"] = parse_color(params["TEXTCOLOR"])
            if "TYPE" in params:
                state["type"] = params["TYPE"]
            if "PRESSED" in params:
                state["pressed"] = params["PRESSED"] in ("1", "true")
            if "LOCATION" in params:
                page = params["LOCATION"].split("/")[0]
                if page.isdigit():
                    state["page"] = int(page)
            self.states[(device_id, index)] = state
            self.on_key_state(device_id, index, state)
        elif command == "KEYS-CLEAR":
            device_id = params.get("DEVICEID")
            for (dev, index) in list(self.states):
                if dev == device_id:
                    self.states[(dev, index)] = {"color": None, "text": "", "text_color": None}
                    self.on_key_state(dev, index, self.states[(dev, index)])

    def _handshake_done(self):
        self._ready = True
        for device_id in list(self.devices):
            self._register(device_id)

    def _run(self):
        while not self._stop.is_set():
            try:
                sock = socket.create_connection((self.host, self.port), timeout=3)
            except OSError as err:
                log.debug("satellite connect %s:%s failed: %s", self.host, self.port, err)
                self._stop.wait(self.retry)
                continue
            sock.settimeout(1.0)
            with self._lock:
                self.sock = sock
            self.on_status(True)
            log.info("connected to Companion satellite %s:%s", self.host, self.port)
            buffer = b""
            last_ping = time.monotonic()
            while not self._stop.is_set():
                now = time.monotonic()
                if now - last_ping > 2:
                    self._send("PING pmk")
                    last_ping = now
                for device_id, when in list(self._retry_at.items()):
                    if now >= when and device_id in self.devices:
                        del self._retry_at[device_id]
                        self._register(device_id)
                for device_id, sent_at in list(self._pending.items()):
                    if now - sent_at > ADD_TIMEOUT and device_id in self.devices:
                        # Companion 5 stays silent (instead of "exists elsewhere") when
                        # another client already holds this surface id.
                        log.warning("no reply to ADD-DEVICE %s - is another app using this surface "
                                    "id? retrying", device_id)
                        self._register(device_id)
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    try:
                        self.handle_line(raw.decode("utf-8", errors="replace"))
                    except Exception:  # noqa: BLE001
                        log.exception("bad satellite line: %r", raw)
            self._close()
            if not self._stop.is_set():
                self._stop.wait(self.retry)

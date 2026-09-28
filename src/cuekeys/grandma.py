# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
"""grandMA2 / grandMA3 command-line remotes.

* grandMA3 accepts commands over OSC: ``/<prefix>/cmd "<command>"``. Enable
  OSC input in *Menu > In & Out > OSC* and tick "Receive Command".
* grandMA2 has no OSC; commands go over Telnet (Setup > Console > Global
  Settings > Telnet: Login Enabled, port 30000).
"""

import logging
import socket
import threading
import time

log = logging.getLogger(__name__)


def ma3_address(prefix):
    prefix = (prefix or "").strip("/")
    return "/%s/cmd" % prefix if prefix else "/cmd"


def quote(text):
    return '"%s"' % str(text).replace('"', "'")


class MA2Telnet:
    """Persistent Telnet session with lazy (re)login."""

    def __init__(self, host, port=30000, user="administrator", password="", timeout=3.0):
        self.host, self.port = host, int(port)
        self.user, self.password = user, password
        self.timeout = timeout
        self.sock = None
        self._lock = threading.Lock()

    def _connect(self):
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(0.5)
        self._drain(sock)
        login = "Login %s %s\r\n" % (quote(self.user), quote(self.password))
        sock.sendall(login.encode("utf-8"))
        self._drain(sock)
        self.sock = sock

    @staticmethod
    def _drain(sock, wait=0.3):
        end = time.monotonic() + wait
        while time.monotonic() < end:
            try:
                if not sock.recv(4096):
                    break
            except (socket.timeout, BlockingIOError):
                break

    def send(self, command):
        data = (command.strip() + "\r\n").encode("utf-8")
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self.sock is None:
                        self._connect()
                    self.sock.sendall(data)
                    self._drain(self.sock, 0.05)
                    return
                except OSError as err:
                    log.warning("MA2 telnet %s:%s failed (%s), attempt %d",
                                self.host, self.port, err, attempt)
                    self.close()
                    if attempt == 2:
                        raise

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

"""Minimal OSC 1.0 encoder + UDP sender (no dependencies)."""

import socket
import struct


def _pad(data):
    return data + b"\0" * (4 - len(data) % 4)


def _string(text):
    return _pad(text.encode("utf-8"))


def encode_message(address, args=()):
    if not address.startswith("/"):
        raise ValueError("OSC address must start with /")
    tags = ","
    payload = b""
    for arg in args:
        if arg is True:
            tags += "T"
        elif arg is False:
            tags += "F"
        elif arg is None:
            tags += "N"
        elif isinstance(arg, int):
            if -(2 ** 31) <= arg < 2 ** 31:
                tags += "i"
                payload += struct.pack(">i", arg)
            else:
                tags += "h"
                payload += struct.pack(">q", arg)
        elif isinstance(arg, float):
            tags += "f"
            payload += struct.pack(">f", arg)
        elif isinstance(arg, str):
            tags += "s"
            payload += _string(arg)
        elif isinstance(arg, (bytes, bytearray)):
            tags += "b"
            payload += struct.pack(">i", len(arg)) + bytes(arg)
            if len(arg) % 4:
                payload += b"\0" * (4 - len(arg) % 4)
        else:
            raise TypeError("unsupported OSC argument: %r" % (arg,))
    return _string(address) + _string(tags) + payload


class OscSender:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, host, port, address, args=()):
        self.sock.sendto(encode_message(address, list(args)), (host, int(port)))

    def close(self):
        self.sock.close()

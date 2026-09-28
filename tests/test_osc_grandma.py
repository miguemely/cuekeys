# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
import socket

from cuekeys import grandma
from cuekeys.osc import OscSender, encode_message


def test_encode_message():
    data = encode_message("/gma3/cmd", ["Go+ Executor 201"])
    assert data.startswith(b"/gma3/cmd\x00\x00\x00,s\x00\x00Go+ Executor 201\x00\x00\x00\x00")
    assert len(data) % 4 == 0
    data = encode_message("/a", [1, 0.5, True, None])
    assert b",ifTN\x00\x00\x00" in data


def test_ma3_address():
    assert grandma.ma3_address("gma3") == "/gma3/cmd"
    assert grandma.ma3_address("/x/") == "/x/cmd"
    assert grandma.ma3_address("") == "/cmd"


def test_udp_send():
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2)
    OscSender().send("127.0.0.1", rx.getsockname()[1], "/x", [1])
    assert rx.recv(1024) == encode_message("/x", [1])


def test_ma2_telnet_login_and_command():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(3)
    client = grandma.MA2Telnet("127.0.0.1", server.getsockname()[1], "administrator", "")
    import threading

    received = []

    def serve():
        conn, _ = server.accept()
        conn.sendall(b"Welcome to grandMA2\r\n")
        conn.settimeout(2)
        data = b""
        while data.count(b"\r\n") < 2:
            chunk = conn.recv(1024)
            if not chunk:
                break
            data += chunk
        received.append(data)
        conn.close()

    t = threading.Thread(target=serve)
    t.start()
    client.send("Go Executor 1.1")
    t.join(5)
    client.close()
    assert received[0] == b'Login "administrator" ""\r\nGo Executor 1.1\r\n'

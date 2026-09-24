import base64
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from pmk_macro_manager import companion as comp


def test_parse_line():
    cmd, params = comp.parse_line('ADD-DEVICE DEVICEID=abc PRODUCT_NAME="My Pad" KEYS_TOTAL=16')
    assert cmd == "ADD-DEVICE"
    assert params == {"DEVICEID": "abc", "PRODUCT_NAME": "My Pad", "KEYS_TOTAL": "16"}


def test_parse_color():
    assert comp.parse_color("#ff8000") == (255, 128, 0)
    assert comp.parse_color("rgb(1, 2, 3)") == (1, 2, 3)
    assert comp.parse_color("nonsense") is None


def test_key_state_and_ping():
    states, sent = [], []
    client = comp.SatelliteClient("127.0.0.1", on_key_state=lambda *a: states.append(a))
    client._send = lambda line: sent.append(line)
    text = base64.b64encode("Go 1".encode()).decode()
    client.handle_line("KEY-STATE DEVICEID=d KEY=4 TYPE=BUTTON COLOR=#00ff00 TEXT=%s" % text)
    assert states == [("d", 4, {"color": (0, 255, 0), "text": "Go 1", "type": "BUTTON"})]
    client.handle_line("PING abc")
    assert sent == ["PONG abc"]


def test_add_device_rejection_and_rename():
    sent, status = [], []
    client = comp.SatelliteClient("127.0.0.1", on_status=status.append)
    client._send = lambda line: sent.append(line)
    client.sock = object()  # pretend connected
    client._ready = True
    client.add_device("d", "One")
    client.handle_line('ADD-DEVICE ERROR DEVICEID="d" MESSAGE="Device exists elsewhere"')
    assert client.registered == {"d": False} and "d" in client._retry_at
    client.handle_line('ADD-DEVICE OK DEVICEID="d"')
    assert client.registered == {"d": True} and "d" not in client._retry_at
    sent.clear()
    client.add_device("d", "Two")  # rename -> remove + add
    assert sent[0] == "REMOVE-DEVICE DEVICEID=d"
    assert sent[1].startswith('ADD-DEVICE DEVICEID=d PRODUCT_NAME="Two"')
    client.sock = None


def test_api_version_page_change_and_location():
    sent = []
    client = comp.SatelliteClient("127.0.0.1")
    client._send = lambda line: sent.append(line) or True
    client.add_device("d", "Pad", keys_total=12)
    client.handle_line('BEGIN CompanionVersion="4.2.0" ApiVersion="1.9.0"')
    assert "KEYS_TOTAL=12" in sent[-1] and "CAN_CHANGE_PAGE" not in sent[-1]
    assert client.change_page("d") is False
    client._close()
    sent.clear()
    client.handle_line('BEGIN CompanionVersion="5.0.6+9750" ApiVersion="1.12.0"')
    assert sent == []  # newer servers: wait for CAPS before registering
    client.handle_line('CAPS SUBSCRIPTIONS=0 NONSQUARE=1')
    assert client.api_version == (1, 12, 0) and sent[-1].endswith("CAN_CHANGE_PAGE=true")
    client.handle_line('ADD-DEVICE OK DEVICEID="d"')
    assert client._pending == {}
    assert client.change_page("d", forward=False) is True
    assert sent[-1] == "CHANGE-PAGE DEVICEID=d DIRECTION=0"
    states = []
    client.on_key_state = lambda *a: states.append(a)
    client.handle_line('KEY-STATE DEVICEID="d" KEY=2 LOCATION="3/0/2" TYPE="PAGEUP" PRESSED=0')
    assert states[-1][2]["page"] == 3 and states[-1][2]["type"] == "PAGEUP"


def test_satellite_end_to_end():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(5)
    port = server.getsockname()[1]
    lines, states = [], []

    def serve():
        conn, _ = server.accept()
        conn.settimeout(5)
        conn.sendall(b"BEGIN CompanionVersion=4.0.0 ApiVersion=1.7.0\n")
        buf = b""
        sent_state = False
        while b"KEY-PRESS" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b"ADD-DEVICE" in buf and not sent_state:
                conn.sendall(b"ADD-DEVICE OK DEVICEID=pad\n")
                conn.sendall(b"KEY-STATE DEVICEID=pad KEY=0 COLOR=#123456 TEXT=" +
                             base64.b64encode(b"Hi") + b"\n")
                sent_state = True
        while not buf.endswith(b"\n"):
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
        lines.extend(buf.decode().splitlines())
        conn.close()

    t = threading.Thread(target=serve)
    t.start()
    client = comp.SatelliteClient("127.0.0.1", port, on_key_state=lambda *a: states.append(a), retry=0.2)
    client.add_device("pad", "PMK test", 16)
    client.start()
    deadline = time.time() + 5
    while not states and time.time() < deadline:
        time.sleep(0.02)
    client.key_press("pad", 0, True)
    t.join(5)
    client.stop()
    assert states[0] == ("pad", 0, {"color": (0x12, 0x34, 0x56), "text": "Hi"})
    add = next(line for line in lines if line.startswith("ADD-DEVICE"))
    assert "KEYS_TOTAL=16" in add and "KEYS_PER_ROW=4" in add and "BITMAPS=0" in add
    assert any(line.startswith("KEY-PRESS DEVICEID=pad KEY=0 PRESSED=true") for line in lines)


def test_http_button():
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.handle_request)
    t.start()
    assert comp.http_button("127.0.0.1", httpd.server_port, 2, 1, 3, "down") == 200
    t.join(5)
    httpd.server_close()
    assert hits == ["/api/location/2/1/3/down"]


def test_page_name_over_http():
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            paths.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"PMK 1")

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.handle_request)
    t.start()
    assert comp.page_name("127.0.0.1", httpd.server_port, 4) == "PMK 1"
    t.join(5)
    httpd.server_close()
    assert paths == ["/api/variable/internal/page_number_4_name/value"]

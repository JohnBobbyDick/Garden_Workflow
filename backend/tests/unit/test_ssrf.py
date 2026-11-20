import asyncio
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.core.ssrf import SSRFError, check_url, safe_request


def fake_resolver(mapping):
    def resolve(host, port):
        return mapping[host]
    return resolve


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost:8080/", "http://10.0.0.5/", "http://192.168.1.1/", "http://172.16.0.1/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[fe80::1]/", "http://0.0.0.0/",
    "http://100.64.0.1/", "http://[::ffff:127.0.0.1]/",
])
def test_internal_addresses_blocked(url):
    with pytest.raises(SSRFError):
        check_url(url, set())


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://x/", "ftp://example.org/", "http:///nohost"])
def test_non_http_schemes_blocked(url):
    with pytest.raises(SSRFError):
        check_url(url, set())


def test_public_address_allowed_with_fake_resolver():
    target = check_url("https://hooks.example.org/x", set(), resolver=fake_resolver({"hooks.example.org": ["93.184.216.34"]}))
    assert target.ip == "93.184.216.34" and target.port == 443


def test_dns_answer_with_any_private_ip_is_blocked():
    with pytest.raises(SSRFError):
        check_url("https://rebind.example.org/", set(),
                  resolver=fake_resolver({"rebind.example.org": ["93.184.216.34", "127.0.0.1"]}))


def test_explicit_allow_host_permits_local_receiver():
    t = check_url("http://127.0.0.1:9999/hook", {"127.0.0.1:9999"})
    assert t.ip == "127.0.0.1"


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://localhost:1/internal")
            self.end_headers()
            return
        if self.path == "/big":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"x" * 300_000)
            return
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"echo:" + body + b" host:" + self.headers["Host"].encode())


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), _H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_safe_request_to_allowed_local_server(server):
    resp = asyncio.run(safe_request("POST", f"http://{server}/hook", allow_hosts={server}, content=b"hi"))
    assert resp.status_code == 200 and resp.content.startswith(b"echo:hi host:127.0.0.1")


def test_redirect_to_disallowed_host_blocked(server):
    with pytest.raises(SSRFError):
        asyncio.run(safe_request("POST", f"http://{server}/redirect", allow_hosts={server}, content=b""))


def test_response_size_limited(server):
    with pytest.raises(SSRFError):
        asyncio.run(safe_request("POST", f"http://{server}/big", allow_hosts={server}, max_bytes=100_000))


def test_unresolvable_host_rejected():
    def boom(host, port):
        raise socket.gaierror("nope")
    with pytest.raises(SSRFError):
        check_url("https://does-not-exist.invalid/", set(), resolver=boom)

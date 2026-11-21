"""SSRF guard in proxy mode: both the target and the proxy must be public or explicitly allowed."""

import asyncio

import pytest

from app.core.ssrf import SSRFError, safe_request

PUBLIC = "93.184.216.34"


def resolver(host: str, port: int) -> list[str]:
    if host.replace(".", "").isdigit():
        return [host]
    return {"example.test": [PUBLIC], "intranet.test": ["10.0.0.7"]}[host]


async def _fake_http_proxy(seen: list[bytes]):
    async def handle(reader, writer):
        data = await reader.readuntil(b"\r\n\r\n")
        seen.append(data)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: text/plain\r\n\r\nok")
        await writer.drain()
        writer.close()

    srv = await asyncio.start_server(handle, "127.0.0.1", 0)
    return srv, srv.sockets[0].getsockname()[1]


async def test_proxy_to_private_host_blocked():
    with pytest.raises(SSRFError):
        await safe_request("GET", "http://example.test/", proxy="http://127.0.0.1:9", resolver=resolver, timeout=2)


async def test_target_private_blocked_even_via_proxy():
    with pytest.raises(SSRFError):
        await safe_request("GET", "http://intranet.test/", proxy="http://127.0.0.1:9",
                           allow_hosts={"127.0.0.1:9"}, resolver=resolver, timeout=2)


async def test_socks_proxy_host_checked_too():
    with pytest.raises(SSRFError):
        await safe_request("GET", "http://example.test/", proxy="socks5://u:p@127.0.0.1:1080",
                           resolver=resolver, timeout=2)


async def test_allowed_proxy_forwards_request_with_absolute_uri():
    seen: list[bytes] = []
    srv, port = await _fake_http_proxy(seen)
    async with srv:
        resp = await safe_request("GET", "http://example.test/path?q=1", proxy=f"http://127.0.0.1:{port}",
                                  allow_hosts={f"127.0.0.1:{port}"}, resolver=resolver, timeout=5,
                                  connect_timeout=2)
    assert resp.status_code == 200 and resp.text == "ok"
    assert seen[0].startswith(b"GET http://example.test/path?q=1 HTTP/1.1")


async def test_proxy_response_size_limit():
    seen: list[bytes] = []
    srv, port = await _fake_http_proxy(seen)
    async with srv:
        with pytest.raises(SSRFError):
            await safe_request("GET", "http://example.test/", proxy=f"http://127.0.0.1:{port}",
                               allow_hosts={f"127.0.0.1:{port}"}, resolver=resolver, timeout=5, max_bytes=1)


async def _gzip_server():
    import gzip

    body = gzip.compress(b'{"ok": true}')

    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Encoding: gzip\r\nContent-Length: "
                     + str(len(body)).encode() + b"\r\n\r\n" + body)
        await writer.drain()
        writer.close()

    srv = await asyncio.start_server(handle, "127.0.0.1", 0)
    return srv, srv.sockets[0].getsockname()[1]


async def test_gzip_response_is_decoded_once_direct():
    """Real APIs (Gemini, OpenRouter) answer gzip: the body must be decoded exactly once."""
    srv, port = await _gzip_server()
    async with srv:
        resp = await safe_request("GET", f"http://127.0.0.1:{port}/", allow_hosts={f"127.0.0.1:{port}"}, timeout=5)
    assert resp.status_code == 200 and resp.json() == {"ok": True}


async def test_gzip_response_is_decoded_once_via_proxy():
    srv, port = await _gzip_server()  # acts as an HTTP proxy answering itself
    async with srv:
        resp = await safe_request("GET", "http://example.test/", proxy=f"http://127.0.0.1:{port}",
                                  allow_hosts={f"127.0.0.1:{port}"}, resolver=resolver, timeout=5)
    assert resp.json() == {"ok": True}

"""Proxy protocol auto-detection (LLM_PROXY.md §3.2) against local fake proxies — no real network."""

import asyncio

import pytest

from app.ai import proxy_scheme as ps


@pytest.fixture(autouse=True)
def _clean_cache():
    ps.clear_cache()
    yield
    ps.clear_cache()


async def _server(reply: bytes | None, seen: list[bytes]):
    async def handle(reader, writer):
        try:
            data = await asyncio.wait_for(reader.read(1024), 1)
            seen.append(data)
            if reply is not None:
                writer.write(reply)
                await writer.drain()
            else:
                await asyncio.sleep(2)
        except (TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()

    srv = await asyncio.start_server(handle, "127.0.0.1", 0)
    return srv, srv.sockets[0].getsockname()[1]


async def test_sniff_detects_socks5():
    seen: list[bytes] = []
    srv, port = await _server(b"\x05\x00", seen)
    async with srv:
        assert await ps.sniff("127.0.0.1", port, timeout=1) == "socks5"
    assert seen[0] == b"\x05\x01\x00"


async def test_sniff_detects_http():
    srv, port = await _server(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n", [])
    async with srv:
        assert await ps.sniff("127.0.0.1", port, timeout=1) == "http"


async def test_sniff_silent_returns_none():
    srv, port = await _server(None, [])
    async with srv:
        assert await ps.sniff("127.0.0.1", port, timeout=0.3) is None


async def test_sniff_never_sends_credentials():
    seen: list[bytes] = []
    srv, port = await _server(None, seen)
    async with srv:
        await ps.resolve(f"auto://loginX:passY@127.0.0.1:{port}", set(), sniff_timeout=0.3)
    assert seen and all(b"loginX" not in s and b"passY" not in s for s in seen)


async def test_resolve_uses_cache_then_falls_through_order():
    tried: set[str] = set()
    ps.remember("socks5://u:p@127.0.0.1:9")
    assert await ps.resolve("auto://u:p@127.0.0.1:9", tried) == "socks5://u:p@127.0.0.1:9"
    # cache entry already tried → sniff (closed port → None) → first untried of http, socks5, https
    assert await ps.resolve("auto://u:p@127.0.0.1:9", tried, sniff_timeout=0.3) == "http://u:p@127.0.0.1:9"
    assert await ps.resolve("auto://u:p@127.0.0.1:9", tried, sniff_timeout=0.3) == "https://u:p@127.0.0.1:9"
    # all tried → start over
    assert (await ps.resolve("auto://u:p@127.0.0.1:9", tried, sniff_timeout=0.3)).startswith("socks5://")


async def test_forget_drops_cache():
    ps.remember("socks5://u:p@h:1")
    ps.forget("socks5://u:p@h:1")
    tried: set[str] = set()
    assert await ps.resolve("auto://u:p@127.0.0.1:9", tried, sniff_timeout=0.3) == "http://u:p@127.0.0.1:9"


async def test_explicit_scheme_passes_through():
    assert await ps.resolve("socks5://u:p@h:1", set()) == "socks5://u:p@h:1"


async def test_cache_expires(monkeypatch):
    ps.remember("socks5://u:p@127.0.0.1:9")
    monkeypatch.setattr(ps, "_now", lambda: ps._real_now() + ps.CACHE_TTL + 1)
    assert await ps.resolve("auto://u:p@127.0.0.1:9", set(), sniff_timeout=0.3) == "http://u:p@127.0.0.1:9"

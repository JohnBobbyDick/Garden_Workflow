"""Proxy protocol auto-detection for ``auto://`` entries (see ``LLM_PROXY.md`` §3.2).

The sniff never sends the proxy login/password: a SOCKS5 greeting "no authentication" and a bare ``CONNECT``.
A protocol that worked is cached per ``host:port`` for ``CACHE_TTL`` seconds in process memory."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit

CACHE_TTL = 600
ORDER = ("http", "socks5", "https")
SNIFF_TIMEOUT = 3.0
_SOCKS_HELLO = b"\x05\x01\x00"
_CONNECT = b"CONNECT integrate.api.nvidia.com:443 HTTP/1.1\r\nHost: integrate.api.nvidia.com:443\r\n\r\n"

_cache: dict[str, tuple[str, float]] = {}
_real_now = time.monotonic
_now = time.monotonic


def _key(url: str) -> str:
    p = urlsplit(url)
    return f"{(p.hostname or '').lower()}:{p.port or ''}"


def _with_scheme(url: str, scheme: str) -> str:
    return scheme + url[url.index("://"):]


def clear_cache() -> None:
    _cache.clear()


def remember(concrete_url: str) -> None:
    scheme = urlsplit(concrete_url).scheme
    if scheme and scheme != "auto":
        _cache[_key(concrete_url)] = (scheme, _now())


def forget(concrete_url: str) -> None:
    _cache.pop(_key(concrete_url), None)


async def _probe(host: str, port: int, payload: bytes, timeout: float) -> bytes:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    try:
        writer.write(payload)
        await writer.drain()
        return await asyncio.wait_for(reader.read(16), timeout)
    finally:
        writer.close()


async def sniff(host: str, port: int, timeout: float = SNIFF_TIMEOUT) -> str | None:
    """``socks5`` / ``http`` by the proxy's answer, ``None`` when it stays silent or answers something else."""
    try:
        data = await _probe(host, port, _SOCKS_HELLO, timeout)
        if data[:1] == b"\x05":
            return "socks5"
        if data.startswith(b"HTTP/"):
            return "http"
    except (TimeoutError, OSError):
        pass
    try:
        data = await _probe(host, port, _CONNECT, timeout)
        if data.startswith(b"HTTP/"):
            return "http"
    except (TimeoutError, OSError):
        pass
    return None


async def resolve(url: str, tried: set[str], sniff_timeout: float = SNIFF_TIMEOUT) -> str:
    """Concrete proxy URL for this attempt; adds the chosen scheme to ``tried`` (per ``generate`` call)."""
    if not url.startswith("auto://"):
        return url
    if tried >= set(ORDER):
        tried.clear()
    cached = _cache.get(_key(url))
    if cached and _now() - cached[1] < CACHE_TTL and cached[0] not in tried:
        tried.add(cached[0])
        return _with_scheme(url, cached[0])
    p = urlsplit(url)
    detected = await sniff(p.hostname or "", p.port or 1080, sniff_timeout) if p.hostname else None
    if detected:
        tried.add(detected)
        return _with_scheme(url, detected)
    scheme = next((s for s in ORDER if s not in tried), ORDER[0])
    tried.add(scheme)
    return _with_scheme(url, scheme)

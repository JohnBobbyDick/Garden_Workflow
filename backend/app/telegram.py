"""Telegram Bot API transport shared by notifications and private chat lookup."""

import asyncio
from urllib.parse import urlsplit

import httpx
import socksio

from app.ai.pool import get_llm_env, parse_proxy
from app.ai.proxy_scheme import forget, remember, resolve
from app.config import get_settings
from app.core.ssrf import DEFAULT_TIMEOUT, safe_request


async def telegram_request(token: str, method: str, *, timeout: float = DEFAULT_TIMEOUT, **body) -> httpx.Response:
    settings = get_settings()
    base = settings.telegram_api_base.rstrip("/")
    url = f"{base}/bot{token}/{method}"
    allow = settings.ssrf_allowed()
    entries = get_llm_env().proxy_entries if base == "https://api.telegram.org" else []
    if not entries:
        return await safe_request("POST", url, allow_hosts=allow, max_redirects=0, timeout=timeout, **body)

    sending = False

    async def trace(event: str, info: dict) -> None:
        nonlocal sending
        # CONNECT only establishes the tunnel. Once the POST begins a retry could duplicate delivery.
        if event.endswith(".send_request_headers.started") and info["request"].method == b"POST":
            sending = True

    reason = "некорректные настройки прокси"
    for entry in entries:
        try:
            raw = parse_proxy(entry)
            if not raw:
                continue
            parts = urlsplit(raw)
            if not parts.hostname or parts.scheme not in {"http", "https", "socks5", "socks5h", "auto"}:
                continue
            port = parts.port or (443 if parts.scheme == "https" else 1080 if parts.scheme.startswith("socks") else 80)
            proxy = await resolve(raw, set())
        except ValueError:
            continue
        try:
            # SOCKS negotiation in httpcore can outlive its connect timeout.
            async with asyncio.timeout(timeout + 5):
                response = await safe_request("POST", url, proxy=proxy, allow_hosts=allow | {f"{parts.hostname}:{port}"},
                                              timeout=timeout, connect_timeout=min(timeout, 5),
                                              max_redirects=0, proxy_trace=trace, **body)
        except (httpx.TransportError, socksio.ProtocolError, TimeoutError) as exc:
            if sending:
                raise httpx.TransportError("Соединение с Telegram прервано. Статус отправки неизвестен.") from None
            reason = type(exc).__name__
            forget(proxy)
            continue
        remember(proxy)
        return response
    raise httpx.ProxyError(f"Не удалось подключиться к Telegram через настроенные прокси ({reason}).")

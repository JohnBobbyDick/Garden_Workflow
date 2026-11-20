"""SSRF protection for every outgoing request (notify.webhook, LLM providers, CI status/comment APIs).

* only ``http``/``https``;
* the host is resolved once and **every** returned address must be public (loopback, private, link-local,
  metadata ``169.254.169.254``, CGNAT, multicast, reserved, IPv4-mapped IPv6 are blocked);
* the connection goes to the verified IP (Host header + TLS SNI keep the original name), so a DNS answer cannot
  change between check and connect (DNS rebinding);
* redirects are followed manually (limited) and every hop is re-checked; timeouts; response size limit;
* ``allow_hosts`` (``host:port`` entries from settings) explicitly permits local services such as Ollama or test
  servers."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

Resolver = Callable[[str, int], list[str]]
MAX_REDIRECTS = 3
DEFAULT_TIMEOUT = 15.0
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class SSRFError(ValueError):
    pass


@dataclass
class Target:
    scheme: str
    host: str
    port: int
    ip: str
    url: str


def _system_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(i[4][0] for i in infos))


def is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if isinstance(addr, ipaddress.IPv4Address) and addr in _CGNAT:
        return False
    flags = [addr.is_private, addr.is_loopback, addr.is_link_local, addr.is_multicast, addr.is_reserved,
             addr.is_unspecified]
    if isinstance(addr, ipaddress.IPv6Address):
        flags.append(addr.is_site_local)
    return not any(flags)


def check_url(url: str, allow_hosts: set[str], resolver: Resolver | None = None) -> Target:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise SSRFError("разрешены только http/https")
    host = (parts.hostname or "").lower()
    if not host:
        raise SSRFError("в URL нет хоста")
    if parts.username or parts.password:
        raise SSRFError("учётные данные в URL запрещены")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise SSRFError("некорректный порт") from exc
    allowed = f"{host}:{port}" in allow_hosts or host in allow_hosts
    try:
        ips = (resolver or _system_resolver)(host, port)
    except (socket.gaierror, UnicodeError, OSError) as exc:
        raise SSRFError(f"не удалось разрешить имя хоста {host}") from exc
    if not ips:
        raise SSRFError(f"не удалось разрешить имя хоста {host}")
    if not allowed:
        for ip in ips:
            try:
                public = is_public_ip(ip)
            except ValueError as exc:
                raise SSRFError("некорректный IP-адрес") from exc
            if not public:
                raise SSRFError(f"адрес {host} указывает во внутреннюю сеть ({ip}) — запрос заблокирован")
    return Target(parts.scheme, host, port, ips[0], url)


def _pinned_url(target: Target) -> str:
    parts = urlsplit(target.url)
    ip = f"[{target.ip}]" if ":" in target.ip else target.ip
    return urlunsplit((parts.scheme, f"{ip}:{target.port}", parts.path or "/", parts.query, ""))


async def safe_request(method: str, url: str, *, allow_hosts: set[str] | None = None, headers: dict | None = None,
                       content: bytes | None = None, json: object = None, data: dict | None = None,
                       files: dict | None = None, timeout: float = DEFAULT_TIMEOUT,
                       max_bytes: int = DEFAULT_MAX_BYTES, max_redirects: int = MAX_REDIRECTS,
                       resolver: Resolver | None = None, verify: bool = True) -> httpx.Response:
    allow = allow_hosts or set()
    current = url
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, verify=verify, trust_env=False) as client:
        for _hop in range(max_redirects + 1):
            target = check_url(current, allow, resolver)
            hdrs = dict(headers or {})
            default_port = 443 if target.scheme == "https" else 80
            hdrs["Host"] = target.host if target.port == default_port else f"{target.host}:{target.port}"
            req = client.build_request(method, _pinned_url(target), headers=hdrs, content=content, json=json,
                                       data=data, files=files,
                                       extensions={"sni_hostname": target.host} if target.scheme == "https" else {})
            resp = await client.send(req, stream=True)
            try:
                if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                    current = urljoin(current, resp.headers["location"])
                    if resp.status_code == 303:
                        method, content, json, data, files = "GET", None, None, None, None
                    continue
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise SSRFError("ответ превышает допустимый размер")
                return httpx.Response(resp.status_code, headers=resp.headers, content=bytes(body), request=req)
            finally:
                await resp.aclose()
    raise SSRFError("слишком много перенаправлений")

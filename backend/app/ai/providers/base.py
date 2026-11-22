"""LLM provider abstraction. A new provider = a new class in ``app/ai/providers/`` decorated ``@register_provider``.

All HTTP goes through the SSRF guard; local Ollama hosts must be listed in ``allow_hosts``
(the Ollama default ``localhost:11434`` is added automatically for the ``ollama`` provider only)."""

from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
import random
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar
from urllib.parse import unquote, urlsplit

import httpx
import socksio

from app.ai.pool import NEMOTRON_LIGHTNING, NVIDIA_BASE_URL, auto_retries, mask_proxy
from app.ai.proxy_scheme import forget, remember, resolve
from app.core.masking import Masker, global_masker
from app.core.ssrf import MAX_REDIRECTS, SSRFError, safe_request

logger = logging.getLogger("app.ai")
MAX_PAUSE = 10.0

RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    pass


class LLMTimeout(LLMError):
    pass


@dataclass
class ProviderConfig:
    provider: str
    base_url: str
    model: str
    api_key: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 90.0
    max_retries: int = 3
    backoff_base: float = 1.0
    json_mode: str = "auto"  # auto | schema | object | instruction
    allow_hosts: set[str] = field(default_factory=set)
    max_response_bytes: int = 4 * 1024 * 1024
    # key / proxy / model pool (LLM_PROXY.md): rotation over attempts
    api_keys: list[str] = field(default_factory=list)
    fallback_models: list[str] = field(default_factory=list)
    proxies: list[str] = field(default_factory=list)
    rotation_retries: int | None = None  # None -> auto_retries(keys, proxies)
    pause_first: float = 2.0
    pause_step: float = 2.0
    deadline_slack: float = 5.0  # hard deadline per attempt = timeout + slack

    @property
    def keys(self) -> list[str]:
        return list(self.api_keys) or ([self.api_key] if self.api_key else [])

    @property
    def models(self) -> list[str]:
        return [self.model] + [m for m in self.fallback_models if m and m != self.model]

    @property
    def pooled(self) -> bool:
        return len(self.keys) > 1 or bool(self.proxies) or bool(self.fallback_models)


@dataclass
class ChatResult:
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    json_mode: str = "none"


class LLMProvider(ABC):
    name: ClassVar[str]
    max_redirects: ClassVar[int] = MAX_REDIRECTS
    default_allow: ClassVar[set[str]] = set()

    def __init__(self, cfg: ProviderConfig) -> None:
        self.cfg = cfg

    @property
    def allow_hosts(self) -> set[str]:
        return set(self.cfg.allow_hosts) | self.default_allow

    @abstractmethod
    async def chat(self, messages: list[dict[str, str]], response_schema: dict | None = None,
                   temperature: float = 0.2, max_tokens: int = 2048, timeout: float | None = None,
                   validate: Callable[[str], bool] | None = None) -> ChatResult:
        """Send a chat completion; when ``response_schema`` is given, ask for JSON matching it. ``validate`` lets the
        caller reject an answer: in pooled mode that counts as a failed attempt and the next one is made."""

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Model ids the provider exposes (empty list if it does not tell)."""

    async def _request(self, method: str, url: str, *, json_body: Any = None, headers: dict | None = None,
                       timeout: float | None = None, proxy: str | None = None,
                       attempts: int | None = None) -> httpx.Response:
        """HTTP with retries/backoff on 429/5xx/timeouts; non-retryable HTTP errors are returned to the caller.
        In pooled mode the rotation loop owns the retries, so it calls this with ``attempts=1``."""
        attempts = attempts or self.cfg.max_retries + 1
        last: Exception | None = None
        t = timeout or self.cfg.timeout
        for i in range(attempts):
            try:
                resp = await safe_request(method, url, allow_hosts=self.allow_hosts, headers=headers, json=json_body,
                                          timeout=t, max_bytes=self.cfg.max_response_bytes, proxy=proxy,
                                          max_redirects=self.max_redirects,
                                          connect_timeout=min(t, 10.0) if proxy else None)
            except SSRFError as exc:
                raise LLMError(f"запрос к провайдеру заблокирован: {exc}") from exc
            except socksio.ProtocolError as exc:
                # httpcore can pass SOCKS handshake decoding errors through without wrapping them.
                last = LLMError("Прокси вернул некорректный ответ при установке соединения SOCKS5.")
                last.__cause__ = exc
            except httpx.TimeoutException as exc:
                last = LLMTimeout(f"провайдер не ответил за {timeout or self.cfg.timeout:g} с")
                last.__cause__ = exc
            except httpx.HTTPError as exc:
                last = LLMError(f"ошибка соединения с провайдером: {type(exc).__name__}")
                last.__cause__ = exc
            else:
                if resp.status_code not in RETRYABLE:
                    return resp
                last = LLMError(f"провайдер вернул HTTP {resp.status_code}")
                retry_after = resp.headers.get("retry-after", "")
                if i < attempts - 1 and retry_after.replace(".", "", 1).isdigit():
                    await asyncio.sleep(min(float(retry_after), 10.0))
                    continue
            if i < attempts - 1:
                await asyncio.sleep(min(self.cfg.backoff_base * (2 ** i), 10.0))
        assert last is not None
        raise last

    # ---- rotation over keys x proxies x models (LLM_PROXY.md section 4) ----

    def _pause(self, attempt: int) -> float:
        if attempt <= 0:
            return 0.0
        return min(self.cfg.pause_first + self.cfg.pause_step * (attempt - 1), MAX_PAUSE)

    def _scrubber(self) -> Callable[[str], str]:
        """Masks keys and proxy credentials in any text (proxy passwords may be shorter than the global minimum)."""
        masker = Masker()
        masker.register(*self.cfg.keys)
        global_masker.register(*self.cfg.keys)
        fragments: list[str] = []
        for p in self.cfg.proxies:
            parts = urlsplit(p)
            if parts.username or parts.password:
                user, pwd = parts.username or "", parts.password or ""
                fragments += [p, f"{user}:{pwd}", f"{unquote(user)}:{unquote(pwd)}", pwd, unquote(pwd)]
                global_masker.register(pwd, unquote(pwd))
        fragments = sorted({f for f in fragments if f}, key=len, reverse=True)

        def scrub(text: str) -> str:
            for f in fragments:
                text = text.replace(f, "\u2022\u2022\u2022")
            return masker.mask(text)
        return scrub

    async def _rotate(self, attempt: Callable[[str, str | None, str | None], Awaitable[ChatResult]],
                      validate: Callable[[str], bool] | None = None) -> ChatResult:
        """Each attempt: next model (the last one repeats), an unused key and proxy (then any), proxy protocol resolved
        for ``auto://``; any error, timeout or rejected answer moves on. Exhausted -> ``LLMError`` with the reason."""
        cfg = self.cfg
        keys: list[str | None] = list(cfg.keys) or [None]
        models = cfg.models
        n = cfg.rotation_retries or auto_retries(len(cfg.keys) or 1, cfg.proxies)
        scrub = self._scrubber()
        used_keys: set[int] = set()
        proxy_order = list(cfg.proxies)
        random.shuffle(proxy_order)
        tried: dict[str, set[str]] = {}
        reason = "нет попыток"

        def pick(pool: list, used: set[int]) -> int:
            free = [i for i in range(len(pool)) if i not in used]
            if not free:
                used.clear()
                free = list(range(len(pool)))
            i = random.choice(free)
            used.add(i)
            return i

        for i in range(n):
            pause = self._pause(i)
            if pause:
                await asyncio.sleep(pause)
            model = models[min(i, len(models) - 1)]
            key = keys[pick(keys, used_keys)]
            raw_proxy = proxy_order[i % len(proxy_order)] if proxy_order else None
            proxy = await resolve(raw_proxy, tried.setdefault(raw_proxy, set())) if raw_proxy else None
            shown = mask_proxy(proxy) if proxy else "direct"
            logger.info("LLM attempt %d/%d: model=%s key=...%s proxy=%s", i + 1, n, model, (key or "")[-4:], shown)
            try:
                res = await asyncio.wait_for(attempt(model, key, proxy), cfg.timeout + cfg.deadline_slack)
                if validate is not None and not validate(res.content):
                    raise LLMError("ответ модели не прошёл проверку формата")
            except (LLMError, httpx.HTTPError, TimeoutError) as exc:
                reason = scrub(str(exc) or f"таймаут {cfg.timeout:g} с: провайдер или прокси не отвечает")
                if proxy:
                    forget(proxy)
                logger.warning("LLM attempt %d/%d failed: %s", i + 1, n, reason)
                continue
            if proxy:
                remember(proxy)
            return res
        raise LLMError(reason if n == 1 else f"Все {n} попытки исчерпаны. Последняя ошибка: {reason}")

    def _auth_headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", **self.cfg.headers}
        if self.cfg.api_key:
            h["Authorization"] = f"Bearer {self.cfg.api_key}"
        return h


PROVIDERS: dict[str, type[LLMProvider]] = {}
_loaded = False


def register_provider(cls: type[LLMProvider]) -> type[LLMProvider]:
    PROVIDERS[cls.name] = cls
    return cls


def _load() -> None:
    global _loaded
    if _loaded:
        return
    pkg = importlib.import_module("app.ai.providers")
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name != "base":
            importlib.import_module(f"app.ai.providers.{info.name}")
    _loaded = True


def provider_names() -> list[str]:
    _load()
    return sorted(PROVIDERS)


def build_provider(cfg: ProviderConfig) -> LLMProvider:
    _load()
    cls = PROVIDERS.get(cfg.provider)
    if cls is None:
        raise LLMError(f"неизвестный провайдер LLM «{cfg.provider}»")
    if not cfg.base_url or not cfg.model:
        raise LLMError("у провайдера LLM не задан base_url или модель")
    if cfg.provider == "nvidia" and (cfg.base_url.rstrip("/") != NVIDIA_BASE_URL
                                     or cfg.models != [NEMOTRON_LIGHTNING]):
        raise LLMError("Для NVIDIA доступны только NVIDIA Build и Nemotron 3.5 Lightning")
    return cls(cfg)


JSON_INSTRUCTION = ("Отвечай строго одним JSON-объектом без пояснений и без markdown, соответствующим JSON Schema:\n"
                    "{schema}\nRespond with a single JSON object only, matching the schema above.")

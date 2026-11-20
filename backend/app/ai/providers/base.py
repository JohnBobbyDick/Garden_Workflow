"""LLM provider abstraction. A new provider = a new class in ``app/ai/providers/`` decorated ``@register_provider``.

All HTTP goes through the SSRF guard; local providers (Ollama, LM Studio) must be listed in ``allow_hosts``
(the Ollama default ``localhost:11434`` is added automatically for the ``ollama`` provider only)."""

from __future__ import annotations

import asyncio
import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx

from app.core.ssrf import SSRFError, safe_request

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


@dataclass
class ChatResult:
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    json_mode: str = "none"


class LLMProvider(ABC):
    name: ClassVar[str]
    default_allow: ClassVar[set[str]] = set()

    def __init__(self, cfg: ProviderConfig) -> None:
        self.cfg = cfg

    @property
    def allow_hosts(self) -> set[str]:
        return set(self.cfg.allow_hosts) | self.default_allow

    @abstractmethod
    async def chat(self, messages: list[dict[str, str]], response_schema: dict | None = None,
                   temperature: float = 0.2, max_tokens: int = 2048, timeout: float | None = None) -> ChatResult:
        """Send a chat completion; when ``response_schema`` is given, ask for JSON matching it."""

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Model ids the provider exposes (empty list if it does not tell)."""

    async def _request(self, method: str, url: str, *, json_body: Any = None, headers: dict | None = None,
                       timeout: float | None = None) -> httpx.Response:
        """HTTP with retries/backoff on 429/5xx/timeouts; non-retryable HTTP errors are returned to the caller."""
        attempts = self.cfg.max_retries + 1
        last: Exception | None = None
        for i in range(attempts):
            try:
                resp = await safe_request(method, url, allow_hosts=self.allow_hosts, headers=headers, json=json_body,
                                          timeout=timeout or self.cfg.timeout, max_bytes=self.cfg.max_response_bytes)
            except SSRFError as exc:
                raise LLMError(f"запрос к провайдеру заблокирован: {exc}") from exc
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
    return cls(cfg)


JSON_INSTRUCTION = ("Отвечай строго одним JSON-объектом без пояснений и без markdown, соответствующим JSON Schema:\n"
                    "{schema}\nRespond with a single JSON object only, matching the schema above.")

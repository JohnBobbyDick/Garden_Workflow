"""LLM key/proxy/model pool configuration (see ``LLM_PROXY.md``).

Environment variables keep the names of ``LLM_PROXY.md`` (no ``APP_`` prefix) and act as the platform default
provider for workspaces without their own AI settings. Secrets from the environment are never written to the DB."""

from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import quote, urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import BACKEND_DIR

SCHEMES = ("auto", "http", "https", "socks5", "socks5h")
MAX_AUTO_RETRIES = 6
MIN_AUTO_RETRIES = 3
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NEMOTRON_LIGHTNING = "nvidia/nemotron-3.5-lightning-30b-a3b"


def split_list(raw: str | None) -> list[str]:
    """Split by comma, semicolon or whitespace; drop empties and duplicates, keep order."""
    out: list[str] = []
    for item in re.split(r"[,;\s]+", raw or ""):
        if item and item not in out:
            out.append(item)
    return out


def parse_proxy(entry: str, scheme: str = "auto", default_port: str | None = None) -> str | None:
    """``host:port:login:password`` / ``host:login:password`` / full URL → proxy URL (``auto://`` when scheme=auto)."""
    entry = (entry or "").strip()
    if not entry:
        return None
    if "://" in entry:
        return entry
    parts = entry.split(":")
    if len(parts) >= 4 and parts[1].isdigit():
        host, port, login, password = parts[0], parts[1], parts[2], ":".join(parts[3:])
    elif len(parts) >= 3:
        host, port, login, password = parts[0], default_port or "", parts[1], ":".join(parts[2:])
    else:
        return None
    if not host or not login:
        return None
    netloc = f"{quote(login, safe='')}:{quote(password, safe='')}@{host}" + (f":{port}" if port else "")
    return f"{scheme if scheme in SCHEMES else 'auto'}://{netloc}"


def auto_retries(n_keys: int, proxies: list[str]) -> int:
    candidates = sum(2 if p.startswith("auto://") else 1 for p in proxies)
    return min(max(n_keys, candidates, MIN_AUTO_RETRIES), MAX_AUTO_RETRIES)


def mask_proxy(url: str) -> str:
    """``scheme://host:port`` only — never login/password."""
    p = urlsplit(url)
    host = p.hostname or ""
    return f"{p.scheme}://{host}" + (f":{p.port}" if p.port else "")


class LLMEnv(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BACKEND_DIR / ".env"), extra="ignore", case_sensitive=False)

    llm_enabled: bool = True
    llm_provider: str = "nvidia"
    nvidia_api_key: str = ""
    nvidia_proxies: str = ""
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"

    @property
    def enabled(self) -> bool:
        return self.llm_enabled

    @property
    def configured(self) -> bool:
        if self.provider == "ollama":
            return self.enabled and bool(self.ollama_url and self.ollama_model)
        return self.enabled and self.provider == "nvidia" and bool(self.keys)

    @property
    def provider(self) -> str:
        return self.llm_provider.strip().lower()

    @property
    def keys(self) -> list[str]:
        return split_list(self.nvidia_api_key) if self.provider == "nvidia" else []

    @property
    def models(self) -> list[str]:
        if self.provider == "nvidia":
            return [NEMOTRON_LIGHTNING]
        return [self.ollama_model] if self.provider == "ollama" else []

    @property
    def proxies(self) -> list[str]:
        return [p for entry in split_list(self.nvidia_proxies) if (p := parse_proxy(entry))] if self.provider == "nvidia" else []

    @property
    def retries(self) -> int:
        return auto_retries(len(self.keys), self.proxies)


def canonical_provider(provider: str, base_url: str, model: str) -> str | None:
    """Recognize the two supported backends, including stored NVIDIA settings from the generic adapter."""
    if not isinstance(base_url, str) or not isinstance(model, str):
        return None
    if provider == "ollama":
        return provider
    if provider == "openai_compat" and base_url.rstrip("/") == NVIDIA_BASE_URL and model == NEMOTRON_LIGHTNING:
        return "nvidia"
    if provider == "nvidia" and base_url.rstrip("/") in ("", NVIDIA_BASE_URL) and model in ("", NEMOTRON_LIGHTNING):
        return "nvidia"
    return None


@lru_cache
def get_llm_env() -> LLMEnv:
    return LLMEnv()

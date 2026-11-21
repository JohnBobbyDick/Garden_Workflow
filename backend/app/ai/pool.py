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

    llm_enabled: bool = False
    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_keys_count: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_fallback_models: str = "gemini-2.5-flash,gemini-2.5-flash-lite"
    gemini_max_retries: str = ""
    gemini_proxies: str = ""
    gemini_proxy_scheme: str = "auto"
    gemini_proxy_port: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "codellama:7b"

    @property
    def enabled(self) -> bool:
        return self.llm_enabled

    @property
    def provider(self) -> str:
        return (self.llm_provider or "gemini").strip().lower()

    @property
    def keys(self) -> list[str]:
        keys = split_list(self.gemini_api_key)
        n = self.gemini_keys_count.strip()
        return keys[: int(n)] if n.isdigit() and int(n) > 0 else keys

    @property
    def models(self) -> list[str]:
        out = [self.gemini_model.strip()] if self.gemini_model.strip() else []
        for m in split_list(self.gemini_fallback_models):
            if m not in out:
                out.append(m)
        return out

    @property
    def proxies(self) -> list[str]:
        scheme = self.gemini_proxy_scheme.strip().lower() or "auto"
        port = self.gemini_proxy_port.strip() or None
        return [p for p in (parse_proxy(e, scheme, port) for e in split_list(self.gemini_proxies)) if p]

    @property
    def retries(self) -> int:
        n = self.gemini_max_retries.strip()
        if n.isdigit() and int(n) > 0:
            return int(n)
        return auto_retries(len(self.keys), self.proxies)


@lru_cache
def get_llm_env() -> LLMEnv:
    return LLMEnv()

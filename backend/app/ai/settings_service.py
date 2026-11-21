"""Workspace AI settings → provider config (keys from the encrypted vault; local hosts only when admin allowed)."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlsplit

from app import models as m
from app.ai.pool import get_llm_env, parse_proxy
from app.ai.providers.base import ProviderConfig
from app.config import get_settings
from app.core.crypto import get_box
from app.core.masking import Masker

FREE_HINTS = [
    "NVIDIA Build: provider=openai_compat, base_url=https://integrate.api.nvidia.com/v1, "
    "модель nvidia/nemotron-3.5-lightning-30b-a3b",
    "Ollama локально (бесплатно, код не покидает машину): provider=ollama, base_url=http://localhost:11434, "
    "модель qwen2.5:7b или llama3.1:8b",
    "OpenRouter (есть бесплатные модели с суффиксом :free): provider=openai_compat, "
    "base_url=https://openrouter.ai/api/v1",
    "Google Gemini через OpenAI-совместимый endpoint: provider=openai_compat, "
    "base_url=https://generativelanguage.googleapis.com/v1beta/openai, модель gemini-2.0-flash",
    "LM Studio / vLLM / llama.cpp server: provider=openai_compat, base_url=http://localhost:1234/v1 "
    "(включите «разрешить локальный адрес»)",
    "Google Gemini нативно (несколько ключей, прокси, модели-фолбэки): provider=gemini, "
    "base_url=https://generativelanguage.googleapis.com/v1beta, модель gemini-2.5-flash",
]


def host_port(url: str) -> str:
    p = urlsplit(url)
    port = p.port or (443 if p.scheme == "https" else 80)
    return f"{(p.hostname or '').lower()}:{port}"


def _decrypt(s, workspace_id: str, credential_id: str | None, masker: Masker) -> str | None:  # noqa: ANN001
    if not credential_id:
        return None
    cred = s.get(m.Credential, credential_id)
    if cred is None or cred.workspace_id != workspace_id:
        raise LookupError("ключ AI-провайдера не найден в хранилище")
    value = get_box().decrypt(cred.ciphertext)
    masker.register(value)
    return value


def _register_proxy(masker: Masker, url: str) -> None:
    parts = urlsplit(url)
    masker.register(url, parts.password, unquote(parts.password or ""))


def _pool(s, workspace_id: str, extra: dict, main_key: str | None, masker: Masker) -> dict:  # noqa: ANN001
    """Extra keys, proxies (vault secrets of kind ``proxy``), fallback models and attempts from ``AISettings.extra``."""
    extra_keys = [k for k in (_decrypt(s, workspace_id, cid, masker) for cid in extra.get("credential_ids") or []) if k]
    proxies: list[str] = []
    for cid in extra.get("proxy_credential_ids") or []:
        raw = _decrypt(s, workspace_id, cid, masker) or ""
        url = parse_proxy(raw, extra.get("proxy_scheme") or "auto", extra.get("proxy_port") or None)
        if url:
            _register_proxy(masker, url)
            proxies.append(url)
    return {"api_keys": ([main_key] if main_key else []) + extra_keys if extra_keys else [],
            "proxies": proxies, "fallback_models": list(extra.get("fallback_models") or []),
            "rotation_retries": int(extra["max_retries"]) if extra.get("max_retries") else None}


def env_provider_config(masker: Masker) -> ProviderConfig | None:
    """Platform-default provider from the environment (``LLM_PROXY.md`` names). The operator configured these hosts,
    so the API base and the proxies are allowed even when they are local; secrets go to the masker, never to the DB."""
    env = get_llm_env()
    if not env.configured:
        return None
    allow = set(get_settings().ssrf_allowed())
    if env.provider == "ollama":
        allow.add(host_port(env.ollama_url))
        return ProviderConfig(provider="ollama", base_url=env.ollama_url, model=env.ollama_model, allow_hosts=allow)
    keys = env.keys
    masker.register(*keys)
    for p in env.proxies:
        _register_proxy(masker, p)
        allow.add(host_port("http://" + p.split("://", 1)[1].rsplit("@", 1)[-1]))
    provider, base_url = ("openai_compat", "https://integrate.api.nvidia.com/v1") if env.provider == "nvidia" else (
        "gemini", env.gemini_base_url)
    allow.add(host_port(base_url))
    return ProviderConfig(provider=provider, base_url=base_url, model=env.models[0], api_key=keys[0],
                          api_keys=keys, fallback_models=env.models[1:], proxies=env.proxies,
                          rotation_retries=env.retries, allow_hosts=allow)


def env_default_out() -> dict:
    env = get_llm_env()
    if not env.configured:
        return {"enabled": False, "provider": "", "model": ""}
    model = env.ollama_model if env.provider == "ollama" else (env.models[0] if env.models else "")
    return {"enabled": True, "provider": env.provider, "model": model}


def provider_config_for(s, workspace_id: str, override: dict[str, Any] | None, masker: Masker,  # noqa: ANN001
                        require_enabled: bool = True) -> ProviderConfig | None:
    ws_settings = s.get(m.AISettings, workspace_id)
    extra = dict(ws_settings.extra or {}) if ws_settings else {}
    allow = set(get_settings().ssrf_allowed())
    if extra.get("allow_host"):
        allow.add(extra["allow_host"])
    if override and override.get("provider"):
        return ProviderConfig(provider=override["provider"], base_url=override.get("base_url") or "",
                              model=override.get("model") or "",
                              api_key=_decrypt(s, workspace_id, override.get("api_key"), masker),
                              headers=dict(extra.get("headers") or {}), timeout=float(extra.get("timeout") or 90),
                              json_mode=extra.get("json_mode") or "auto", allow_hosts=allow)
    if ws_settings is None:
        return env_provider_config(masker)
    if not ws_settings.enabled:
        platform = env_provider_config(masker)
        if platform is not None or require_enabled:
            return platform
    if not ws_settings.base_url or not ws_settings.model:
        return env_provider_config(masker) if not require_enabled else None
    key = _decrypt(s, workspace_id, ws_settings.credential_id, masker)
    return ProviderConfig(provider=ws_settings.provider, base_url=ws_settings.base_url, model=ws_settings.model,
                          api_key=key, headers=dict(extra.get("headers") or {}),
                          timeout=float(extra.get("timeout") or 90), json_mode=extra.get("json_mode") or "auto",
                          allow_hosts=allow, **_pool(s, workspace_id, extra, key, masker))

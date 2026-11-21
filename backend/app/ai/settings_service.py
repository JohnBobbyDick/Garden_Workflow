"""Workspace AI settings → provider config (keys from the encrypted vault; local hosts only when admin allowed)."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlsplit

from app import models as m
from app.ai.pool import NEMOTRON_LIGHTNING, NVIDIA_BASE_URL, LLMEnv, canonical_provider, get_llm_env, parse_proxy
from app.ai.providers.base import ProviderConfig
from app.config import get_settings
from app.core.crypto import get_box
from app.core.masking import Masker

FREE_HINTS = [
    "NVIDIA Build — облачная модель Nemotron 3.5 Lightning.",
    "Ollama — сервер и модель задаются в настройках рабочего пространства.",
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
            "proxies": proxies,
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
    return _platform_nvidia(masker)


def _platform_proxies(env: LLMEnv, masker: Masker, allow: set[str]) -> list[str]:
    proxies = env.proxies
    for proxy in proxies:
        _register_proxy(masker, proxy)
        allow.add(host_port(proxy))
    return proxies


def _platform_nvidia(masker: Masker) -> ProviderConfig | None:
    # Workspace and node selections can explicitly request NVIDIA even if the operator defaults to Ollama.
    env = get_llm_env().model_copy(update={"llm_provider": "nvidia"})
    if not env.configured:
        return None
    keys = env.keys
    masker.register(*keys)
    allow = set(get_settings().ssrf_allowed())
    proxies = _platform_proxies(env, masker, allow)
    return ProviderConfig(provider="nvidia", base_url=NVIDIA_BASE_URL, model=NEMOTRON_LIGHTNING,
                          api_key=keys[0], api_keys=keys, proxies=proxies, rotation_retries=env.retries,
                          allow_hosts=allow)


def env_default_out() -> dict:
    env = get_llm_env()
    if not env.configured:
        return {"enabled": False, "provider": "", "model": ""}
    model = env.ollama_model if env.provider == "ollama" else (env.models[0] if env.models else "")
    return {"enabled": True, "provider": env.provider, "model": model}


def provider_config_for(s, workspace_id: str, override: dict[str, Any] | None, masker: Masker,  # noqa: ANN001
                        require_enabled: bool = True) -> ProviderConfig | None:
    row = s.get(m.AISettings, workspace_id)
    extra = dict(row.extra or {}) if row else {}
    if override and override.get("provider"):
        name = override["provider"]
        url, model = override.get("base_url") or "", override.get("model") or ""
        key_id = override.get("api_key")
        # A node can inherit the administrator's host allowance, never another provider's headers or keys.
        extra = {"allow_host": extra.get("allow_host")}
    else:
        if row is None:
            return env_provider_config(masker)
        name, url, model, key_id = row.provider, row.base_url, row.model, row.credential_id
        if not canonical_provider(name, url, model):
            return None  # Retired destinations require an explicit new workspace selection.
        if not row.enabled:
            platform = env_provider_config(masker)
            if require_enabled or platform is not None:
                return platform
    provider = canonical_provider(name, url, model)
    if not provider:
        return None
    if provider == "nvidia":
        url, model = NVIDIA_BASE_URL, NEMOTRON_LIGHTNING
        if not key_id and not extra.get("credential_ids"):
            return _platform_nvidia(masker)
    elif not url or not model:
        return None
    allow = set(get_settings().ssrf_allowed())
    if provider == "ollama" and extra.get("allow_host"):
        allow.add(extra["allow_host"])
    key = _decrypt(s, workspace_id, key_id, masker)
    pool = _pool(s, workspace_id, extra, key, masker) if provider == "nvidia" else {}
    if provider == "nvidia" and not pool["proxies"]:
        env = get_llm_env().model_copy(update={"llm_provider": "nvidia"})
        pool["proxies"] = _platform_proxies(env, masker, allow)
    return ProviderConfig(provider=provider, base_url=url, model=model, api_key=key,
                          headers=dict(extra.get("headers") or {}), timeout=float(extra.get("timeout") or 90),
                          json_mode=extra.get("json_mode") or "auto", allow_hosts=allow, **pool)

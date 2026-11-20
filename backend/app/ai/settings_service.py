"""Workspace AI settings → provider config (keys from the encrypted vault; local hosts only when admin allowed)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from app import models as m
from app.ai.providers.base import ProviderConfig
from app.config import get_settings
from app.core.crypto import get_box
from app.core.masking import Masker

FREE_HINTS = [
    "Ollama локально (бесплатно, код не покидает машину): provider=ollama, base_url=http://localhost:11434, "
    "модель qwen2.5:7b или llama3.1:8b",
    "OpenRouter (есть бесплатные модели с суффиксом :free): provider=openai_compat, "
    "base_url=https://openrouter.ai/api/v1",
    "Google Gemini через OpenAI-совместимый endpoint: provider=openai_compat, "
    "base_url=https://generativelanguage.googleapis.com/v1beta/openai, модель gemini-2.0-flash",
    "LM Studio / vLLM / llama.cpp server: provider=openai_compat, base_url=http://localhost:1234/v1 "
    "(включите «разрешить локальный адрес»)",
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
    if ws_settings is None or (require_enabled and not ws_settings.enabled):
        return None
    if not ws_settings.base_url or not ws_settings.model:
        return None
    return ProviderConfig(provider=ws_settings.provider, base_url=ws_settings.base_url, model=ws_settings.model,
                          api_key=_decrypt(s, workspace_id, ws_settings.credential_id, masker),
                          headers=dict(extra.get("headers") or {}), timeout=float(extra.get("timeout") or 90),
                          json_mode=extra.get("json_mode") or "auto", allow_hosts=allow)

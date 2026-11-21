"""Connection diagnostics (``LLM_PROXY.md`` §8): one small request with the first key through every proxy — every
protocol for ``auto://`` entries — and directly. Results never contain secrets."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from urllib.parse import urlsplit

from app.ai.pool import mask_proxy
from app.ai.providers.base import ChatResult, LLMError, LLMProvider, ProviderConfig, build_provider
from app.core.masking import Masker

AUTO_SCHEMES = ("http", "socks5", "https", "socks5h")
PROBE_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def _probe_answer(content: str) -> bool:
    if not isinstance(content, str):
        return False
    try:
        data = json.loads(content)
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("ok") is True


async def probe_chat(provider: LLMProvider, timeout: float) -> ChatResult:
    result = await provider.chat([{"role": "user", "content": 'Верни JSON {"ok": true}'}],
                                 response_schema=PROBE_SCHEMA, max_tokens=20, timeout=timeout, validate=_probe_answer)
    if not _probe_answer(result.content):
        raise LLMError('Ожидался JSON-объект с полем "ok" равным true.')
    return result


async def _probe(cfg: ProviderConfig, proxy: str | None, masker: Masker) -> dict:
    one = replace(cfg, api_key=cfg.keys[0] if cfg.keys else None, api_keys=[], fallback_models=[],
                  proxies=[proxy] if proxy else [], rotation_retries=1, max_retries=0, pause_first=0.0,
                  timeout=min(cfg.timeout, 20.0))
    started = time.monotonic()
    row = {"proxy": mask_proxy(proxy) if proxy else "direct", "scheme": urlsplit(proxy).scheme if proxy else None}
    try:
        await probe_chat(build_provider(one), one.timeout)
        row.update(ok=True, error=None)
    except (LLMError, ValueError, OSError) as exc:
        row.update(ok=False, error=masker.mask(str(exc))[:300] or type(exc).__name__)
    row["ms"] = int((time.monotonic() - started) * 1000)
    return row


async def diagnose(cfg: ProviderConfig, masker: Masker) -> list[dict]:
    rows: list[dict] = []
    for raw in cfg.proxies:
        if raw.startswith("auto://"):
            for scheme in AUTO_SCHEMES:
                rows.append(await _probe(cfg, scheme + raw[len("auto"):], masker))
        else:
            rows.append(await _probe(cfg, raw, masker))
    rows.append(await _probe(cfg, None, masker))
    return rows

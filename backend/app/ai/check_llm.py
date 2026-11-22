"""CLI diagnostics of the platform-default LLM from the environment: ``cd backend && python -m app.ai.check_llm``.

Prints the configuration (counts only, no secrets) and OK/FAIL per proxy × protocol and direct; at least one OK is
needed. Exit code 0 when something works, 1 otherwise."""

from __future__ import annotations

import asyncio
import sys

from app.ai.diagnose import diagnose
from app.ai.pool import get_llm_env
from app.ai.providers.base import LLMError
from app.ai.settings_service import env_provider_config
from app.core.masking import Masker


def main() -> int:
    env = get_llm_env()
    masker = Masker()
    cfg = env_provider_config(masker)
    print(f"LLM_ENABLED={env.enabled} provider={env.provider} keys={len(env.keys)} proxies={len(env.proxies)} "
          f"models={','.join(env.models)} retries={env.retries}")
    if cfg is None:
        print("LLM отключён или не настроен. Проверьте LLM_ENABLED, провайдер, его модель и ключ.")
        return 1
    try:
        rows = asyncio.run(diagnose(cfg, masker))
    except LLMError as exc:
        print(masker.mask(str(exc)))
        return 1
    for r in rows:
        status = "OK  " if r["ok"] else "FAIL"
        print(f"{status} {r['proxy']:<40} {r['scheme'] or '-':<8} {r['ms']:>6} мс  {r['error'] or ''}")
    return 0 if any(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())

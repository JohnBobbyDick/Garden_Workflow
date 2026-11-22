"""Проверка ключа NVIDIA из корневого .env. Запуск: python3 check_nvidia.py [--direct]."""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
if __name__ == "__main__":
    # An IDE may start the script with a system Python that lacks the backend dependencies.
    venv = ROOT / "backend" / ".venv"
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if python.is_file() and Path(sys.prefix).resolve() != venv.resolve():
        os.execv(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]])

sys.path.insert(0, str(ROOT / "backend"))

from app.ai.diagnose import probe_chat  # noqa: E402
from app.ai.pool import NEMOTRON_LIGHTNING, NVIDIA_BASE_URL, LLMEnv, parse_proxy  # noqa: E402
from app.ai.providers.base import LLMError, ProviderConfig, build_provider  # noqa: E402
from app.ai.settings_service import host_port  # noqa: E402
from app.config import get_settings  # noqa: E402


def failure(exc: Exception) -> str:
    # Only fixed categories can enter the shareable output, never upstream error bodies or proxy credentials.
    detail = str(exc)
    status = re.search(r"провайдер вернул HTTP (\d{3})", detail)
    if status:
        return f"NVIDIA вернул HTTP {status[1]}"
    if "SOCKS5" in detail:
        return "некорректный ответ SOCKS5"
    if isinstance(exc, TimeoutError) or "не ответил" in detail or "таймаут" in detail:
        return "истекло время ожидания"
    if "JSON" in detail or "формат" in detail:
        return "ответ модели не прошёл проверку JSON"
    for category in ("ProxyError", "ConnectError", "заблокирован"):
        if category in detail:
            return f"ошибка соединения ({category})"
    return "не удалось выполнить запрос"


async def check(key: str, entry: str | None) -> bool:
    allow = get_settings().ssrf_allowed()
    proxies = []
    try:
        if entry is not None:
            proxy = parse_proxy(entry)
            if not proxy or not urlsplit(proxy).hostname:
                raise ValueError
            allow.add(host_port(proxy))
            proxies.append(proxy)
        cfg = ProviderConfig(provider="nvidia", base_url=NVIDIA_BASE_URL, model=NEMOTRON_LIGHTNING,
                             api_key=key, proxies=proxies, allow_hosts=allow,
                             rotation_retries=1, max_retries=0, timeout=30)
        async with asyncio.timeout(45):
            reply = await probe_chat(build_provider(cfg), cfg.timeout)
    except (LLMError, TimeoutError) as exc:
        print(f"FAIL — {failure(exc)}", flush=True)
        return False
    except ValueError:
        print("FAIL — проверьте формат адреса и порт прокси", flush=True)
        return False
    print("OK — ответ модели", json.dumps({"ok": json.loads(reply.content)["ok"]}), flush=True)
    return True


async def run(direct: bool) -> int:
    env = LLMEnv(_env_file=ROOT / ".env", llm_provider="nvidia")
    if not env.keys:
        print("В корневом .env или окружении не задан NVIDIA_API_KEY.")
        return 1
    print(f"Модель {NEMOTRON_LIGHTNING}. Проверяется первый ключ NVIDIA_API_KEY.")
    print(f"POST {NVIDIA_BASE_URL}/chat/completions")
    entries = [] if direct else env.proxy_entries
    if not entries:
        print("Прямой HTTPS", flush=True)
        return 0 if await check(env.keys[0], None) else 1
    results = []
    for index, entry in enumerate(entries, 1):
        print(f"Прокси {index}/{len(entries)}", flush=True)
        results.append(await check(env.keys[0], entry))
    return 0 if any(results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Проверить ответ Nemotron через прокси из .env или напрямую.")
    parser.add_argument("--direct", action="store_true", help="проверить прямое HTTPS-соединение из коммита aabbd54")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    sys.exit(asyncio.run(run(args.direct)))

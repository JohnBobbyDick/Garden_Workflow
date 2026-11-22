from unittest.mock import AsyncMock

import httpx
import pytest

from app import telegram
from app.ai import diagnose
from app.ai.pool import NEMOTRON_LIGHTNING, NVIDIA_BASE_URL, get_llm_env
from app.ai.providers.base import LLMError, ProviderConfig, build_provider
from app.config import REPO_ROOT
from app.core.masking import Masker


@pytest.fixture
def proxy_only(monkeypatch):
    monkeypatch.setenv("NVIDIA_TELEGRAM_PROXY_ONLY", "true")
    for name in ("NVIDIA_PROXIES", "TELEGRAM_PROXIES", "GEMINI_PROXIES", "GEMENI_PROXIES"):
        monkeypatch.setenv(name, "")
    get_llm_env.cache_clear()
    return ProviderConfig(provider="nvidia", model=NEMOTRON_LIGHTNING, base_url=NVIDIA_BASE_URL)


async def test_nvidia_requires_proxy_before_chat(proxy_only, monkeypatch):
    provider = build_provider(proxy_only)
    request = AsyncMock()
    monkeypatch.setattr(provider, "_chat_once", request)
    with pytest.raises(LLMError, match="прокси"):
        await provider.chat([])
    request.assert_not_awaited()


async def test_telegram_requires_proxy_before_request(proxy_only, monkeypatch):
    request = AsyncMock()
    monkeypatch.setattr(telegram, "safe_request", request)
    with pytest.raises(httpx.ProxyError, match="прокси"):
        await telegram.telegram_request("unused", "getMe")
    request.assert_not_awaited()


async def test_diagnostics_only_select_configured_routes(proxy_only, monkeypatch):
    probe = AsyncMock()
    monkeypatch.setattr(diagnose, "_probe", probe)
    with pytest.raises(LLMError, match="прокси"):
        await diagnose.diagnose(proxy_only, Masker())
    proxy_only.proxies = ["http://proxy.test:3128"]
    await diagnose.diagnose(proxy_only, Masker())
    assert [call.args[1] for call in probe.await_args_list] == proxy_only.proxies


@pytest.mark.parametrize("direct", [True, False])
async def test_cli_blocks_direct_modes(proxy_only, monkeypatch, tmp_path, direct):
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    import check_nvidia

    monkeypatch.setattr(check_nvidia, "ROOT", tmp_path)
    monkeypatch.setenv("NVIDIA_API_KEY", "local-test-key")
    check = AsyncMock(return_value=True)
    monkeypatch.setattr(check_nvidia, "check", check)
    assert await check_nvidia.run(direct) == 1
    check.assert_not_awaited()

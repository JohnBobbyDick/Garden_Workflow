"""Retry/rotation loop over keys × proxies × models (LLM_PROXY.md §4) in the provider base class."""

import asyncio
import logging

import pytest

from app.ai.providers.base import ChatResult, LLMError, LLMProvider, ProviderConfig


class Fake(LLMProvider):
    name = "fake_rotation"

    async def chat(self, messages, response_schema=None, temperature=0.2, max_tokens=2048, timeout=None,
                   validate=None):
        raise NotImplementedError("test double: only _rotate is exercised")

    async def list_models(self):
        return []


def cfg(**kw) -> ProviderConfig:
    base = {"provider": "fake_rotation", "base_url": "https://llm.test", "model": "m1", "timeout": 1.0,
            "pause_first": 0.0, "pause_step": 0.0}
    base.update(kw)
    return ProviderConfig(**base)


async def test_rotates_keys_and_models_until_success():
    calls = []

    async def attempt(model, key, proxy):
        calls.append((model, key))
        if len(calls) < 3:
            raise LLMError("HTTP 429")
        return ChatResult("ok", model)

    p = Fake(cfg(api_keys=["k1", "k2"], fallback_models=["m2"]))
    res = await p._rotate(attempt)
    assert res.content == "ok"
    assert [c[0] for c in calls] == ["m1", "m2", "m2"]
    assert {calls[0][1], calls[1][1]} == {"k1", "k2"}  # unused keys first


async def test_proxies_alternate_across_retry_rounds():
    seen = []

    async def attempt(model, key, proxy):
        seen.append(proxy)
        raise LLMError("proxy down")

    p = Fake(cfg(api_key="k", proxies=["http://a:1", "http://b:2"], rotation_retries=4))
    with pytest.raises(LLMError):
        await p._rotate(attempt)
    assert set(seen) == {"http://a:1", "http://b:2"}
    assert seen[:2] == seen[2:]


async def test_validate_failure_counts_as_failed_attempt():
    texts = iter(["{}", '{"ok": true}'])

    async def attempt(model, key, proxy):
        return ChatResult(next(texts), model)

    p = Fake(cfg(api_key="k"))
    res = await p._rotate(attempt, validate=lambda t: '"ok"' in t)
    assert res.content == '{"ok": true}'


async def test_exhausted_message_masks_secrets(caplog):
    key, proxy = "sk-SECRETKEY1234", "socks5://user:pw%3Ax@proxy.test:1080"

    async def attempt(model, k, prx):
        raise LLMError(f"boom with {k} via {prx} and user:pw:x")

    p = Fake(cfg(api_keys=[key], proxies=[proxy], rotation_retries=2))
    caplog.set_level(logging.INFO)
    with pytest.raises(LLMError) as e:
        await p._rotate(attempt)
    msg = str(e.value)
    assert "исчерпаны" in msg and "SECRETKEY" not in msg and "pw" not in msg
    assert "SECRETKEY" not in caplog.text and "pw%3Ax" not in caplog.text and "proxy.test:1080" in caplog.text
    assert "...1234" in caplog.text


async def test_single_attempt_message_is_plain_reason():
    async def attempt(model, key, proxy):
        raise LLMError("HTTP 400 bad request")

    p = Fake(cfg(api_key="k", rotation_retries=1))
    with pytest.raises(LLMError, match="^HTTP 400 bad request$"):
        await p._rotate(attempt)


async def test_hard_deadline_cancels_hung_attempt():
    async def attempt(model, key, proxy):
        await asyncio.sleep(10)

    p = Fake(cfg(api_key="k", timeout=0.1, rotation_retries=1, deadline_slack=0.1))
    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(LLMError):
        await p._rotate(attempt)
    assert loop.time() - started < 2


def test_pooled_flag():
    assert Fake(cfg(api_key="k")).cfg.pooled is False
    assert Fake(cfg(api_keys=["a", "b"])).cfg.pooled is True
    assert Fake(cfg(api_key="k", proxies=["http://a:1"])).cfg.pooled is True
    assert Fake(cfg(api_key="k", fallback_models=["m2"])).cfg.pooled is True


def test_pause_schedule():
    p = Fake(cfg(pause_first=2.0, pause_step=2.0))
    assert [p._pause(i) for i in range(7)] == [0, 2, 4, 6, 8, 10, 10]

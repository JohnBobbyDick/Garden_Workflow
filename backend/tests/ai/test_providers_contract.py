import asyncio

import pytest

from app.ai.providers.base import LLMError, LLMTimeout, ProviderConfig, build_provider
from tests.ai.fake_llm import make_server

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


@pytest.fixture
def openai():
    srv, script, hp = make_server("openai")
    yield script, hp
    srv.shutdown()


@pytest.fixture
def ollama():
    srv, script, hp = make_server("ollama")
    yield script, hp
    srv.shutdown()


def cfg(hp, **kw):
    base = {"provider": "openai_compat", "base_url": f"http://{hp}/v1", "model": "test-model", "api_key": "sk-test-key-123",
            "headers": {"X-Title": "aisw"}, "timeout": 2, "backoff_base": 0.01, "allow_hosts": {hp}}
    base.update(kw)
    return ProviderConfig(**base)


def chat(c, **kw):
    return asyncio.run(build_provider(c).chat([{"role": "user", "content": "hi"}], **kw))


def test_openai_request_format_and_json_schema_mode(openai):
    script, hp = openai
    script.reply({"ok": True})
    res = chat(cfg(hp), response_schema=SCHEMA, temperature=0.1, max_tokens=300)
    req = script.requests[0]
    assert req["path"] == "/v1/chat/completions"
    assert req["headers"]["Authorization"] == "Bearer sk-test-key-123" and req["headers"]["X-Title"] == "aisw"
    assert req["body"]["model"] == "test-model" and req["body"]["temperature"] == 0.1
    assert req["body"]["max_tokens"] == 300
    assert req["body"]["response_format"]["type"] == "json_schema"
    assert req["body"]["response_format"]["json_schema"]["schema"] == SCHEMA
    assert res.content == '{"ok": true}' and res.usage["total_tokens"] == 33


def test_falls_back_to_instruction_mode_when_response_format_unsupported(openai):
    script, hp = openai
    script.reply(status=400, body={"error": {"message": "response_format is not supported"}})
    script.reply({"ok": True})
    res = chat(cfg(hp), response_schema=SCHEMA)
    assert "response_format" not in script.requests[1]["body"]
    assert "JSON" in script.requests[1]["body"]["messages"][0]["content"]
    assert res.json_mode == "instruction"


def test_nemotron_structured_reply_reserves_tokens_for_json(openai):
    script, hp = openai
    script.reply({"ok": True})
    chat(cfg(hp, model="nvidia/nemotron-3.5-lightning-30b-a3b"), response_schema=SCHEMA, max_tokens=20)
    assert script.requests[0]["body"].get("chat_template_kwargs") == {"enable_thinking": False}


def test_retries_on_429_and_5xx(openai):
    script, hp = openai
    script.reply(status=429, headers={"Retry-After": "0"}).reply(status=503).reply({"ok": True})
    assert chat(cfg(hp), response_schema=SCHEMA).content == '{"ok": true}'
    assert len(script.requests) == 3


def test_gives_up_after_retries(openai):
    script, hp = openai
    for _ in range(5):
        script.reply(status=500)
    with pytest.raises(LLMError):
        chat(cfg(hp, max_retries=2))
    assert len(script.requests) == 3


def test_timeout_raises_llm_timeout(openai):
    script, hp = openai
    script.reply({"ok": True}, delay=1.5).reply({"ok": True}, delay=1.5)
    with pytest.raises(LLMTimeout):
        chat(cfg(hp, timeout=0.3, max_retries=1))


def test_auth_error_is_not_retried(openai):
    script, hp = openai
    script.reply(status=401)
    with pytest.raises(LLMError, match="401"):
        chat(cfg(hp))
    assert len(script.requests) == 1


def test_list_models_openai(openai):
    _, hp = openai
    assert asyncio.run(build_provider(cfg(hp)).list_models()) == ["test-model", "other"]


def test_ollama_native_api(ollama):
    script, hp = ollama
    script.reply({"ok": True})
    c = cfg(hp, provider="ollama", base_url=f"http://{hp}", model="qwen2.5:3b", api_key=None)
    res = chat(c, response_schema=SCHEMA, max_tokens=100)
    req = script.requests[0]
    assert req["path"] == "/api/chat" and req["body"]["stream"] is False
    assert req["body"]["format"] == SCHEMA and req["body"]["options"]["num_predict"] == 100
    assert res.content == '{"ok": true}' and res.usage == {"prompt_tokens": 11, "completion_tokens": 22,
                                                            "total_tokens": 33}
    assert asyncio.run(build_provider(c).list_models()) == ["qwen2.5:3b"]


def test_ssrf_blocks_internal_provider_url_not_in_allowlist(openai):
    _, hp = openai
    with pytest.raises(LLMError, match="заблокирован|внутреннюю"):
        chat(cfg(hp, allow_hosts=set()))


def test_unknown_provider_rejected():
    with pytest.raises(LLMError):
        build_provider(ProviderConfig(provider="nope", base_url="http://x", model="m"))

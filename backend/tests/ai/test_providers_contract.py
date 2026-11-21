import asyncio

import pytest

from app.ai.pool import NEMOTRON_LIGHTNING, NVIDIA_BASE_URL
from app.ai.providers.base import LLMError, LLMTimeout, ProviderConfig, build_provider
from tests.ai.fake_llm import make_server

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


@pytest.fixture
def ollama():
    srv, script, hp = make_server("ollama")
    yield script, hp
    srv.shutdown()


def cfg(hp, **kw):
    base = {"provider": "nvidia", "base_url": NVIDIA_BASE_URL, "model": NEMOTRON_LIGHTNING, "api_key": "sk-test-key-123",
            "headers": {"X-Title": "aisw"}, "timeout": 2, "backoff_base": 0.01, "allow_hosts": {hp}}
    base.update(kw)
    return ProviderConfig(**base)


def chat(c, **kw):
    return asyncio.run(build_provider(c).chat([{"role": "user", "content": "hi"}], **kw))


def test_nvidia_server_request_format_and_json_schema_mode(nvidia_server):
    script, hp = nvidia_server
    script.reply({"ok": True})
    res = chat(cfg(hp), response_schema=SCHEMA, temperature=0.1, max_tokens=300)
    req = script.requests[0]
    assert req["path"] == "/v1/chat/completions"
    assert req["headers"]["Authorization"] == "Bearer sk-test-key-123" and req["headers"]["X-Title"] == "aisw"
    assert req["body"]["model"] == NEMOTRON_LIGHTNING and req["body"]["temperature"] == 0.1
    assert req["body"]["max_tokens"] == 300
    assert req["body"]["response_format"]["type"] == "json_schema"
    assert req["body"]["response_format"]["json_schema"]["schema"] == SCHEMA
    assert res.content == '{"ok": true}' and res.usage["total_tokens"] == 33


def test_falls_back_to_instruction_mode_when_response_format_unsupported(nvidia_server):
    script, hp = nvidia_server
    script.reply(status=400, body={"error": {"message": "response_format is not supported"}})
    script.reply({"ok": True})
    res = chat(cfg(hp), response_schema=SCHEMA)
    assert "response_format" not in script.requests[1]["body"]
    assert "JSON" in script.requests[1]["body"]["messages"][0]["content"]
    assert res.json_mode == "instruction"


def test_nemotron_structured_reply_reserves_tokens_for_json(nvidia_server):
    script, hp = nvidia_server
    script.reply({"ok": True})
    chat(cfg(hp, model="nvidia/nemotron-3.5-lightning-30b-a3b"), response_schema=SCHEMA, max_tokens=20)
    assert script.requests[0]["body"].get("chat_template_kwargs") == {"enable_thinking": False}


def test_retries_on_429_and_5xx(nvidia_server):
    script, hp = nvidia_server
    script.reply(status=429, headers={"Retry-After": "0"}).reply(status=503).reply({"ok": True})
    assert chat(cfg(hp), response_schema=SCHEMA).content == '{"ok": true}'
    assert len(script.requests) == 3


def test_gives_up_after_retries(nvidia_server):
    script, hp = nvidia_server
    for _ in range(5):
        script.reply(status=500)
    with pytest.raises(LLMError):
        chat(cfg(hp, max_retries=2))
    assert len(script.requests) == 3


def test_timeout_raises_llm_timeout(nvidia_server):
    script, hp = nvidia_server
    script.reply({"ok": True}, delay=1.5).reply({"ok": True}, delay=1.5)
    with pytest.raises(LLMTimeout):
        chat(cfg(hp, timeout=0.3, max_retries=1))


def test_auth_error_is_not_retried(nvidia_server):
    script, hp = nvidia_server
    script.reply(status=401)
    with pytest.raises(LLMError, match="401"):
        chat(cfg(hp))
    assert len(script.requests) == 1


def test_list_models_nvidia_server(nvidia_server):
    _, hp = nvidia_server
    assert asyncio.run(build_provider(cfg(hp)).list_models()) == [NEMOTRON_LIGHTNING]


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


def test_ssrf_blocks_internal_provider_url_not_in_allowlist(ollama):
    _, hp = ollama
    with pytest.raises(LLMError, match="заблокирован|внутреннюю"):
        chat(cfg(hp, provider="ollama", base_url=f"http://{hp}", allow_hosts=set()))


def test_unknown_provider_rejected():
    with pytest.raises(LLMError):
        build_provider(ProviderConfig(provider="nope", base_url="http://x", model="m"))

async def test_nvidia_rotates_workspace_keys(nvidia_server):
    script, hp = nvidia_server
    script.reply(status=401).reply({"ok": True})
    p = build_provider(cfg(hp, api_key=None, api_keys=["key-AAAA1111", "key-BBBB2222"], pause_first=0.0))
    res = await p.chat([{"role": "user", "content": "hi"}], response_schema=SCHEMA)
    auths = [r["headers"]["Authorization"] for r in script.requests]
    assert len(auths) == 2 and len(set(auths)) == 2
    assert res.content == '{"ok": true}'


async def test_nvidia_rotates_on_invalid_reply(nvidia_server):
    script, hp = nvidia_server
    script.reply("").reply({"ok": True})
    p = build_provider(cfg(hp, api_keys=["key-A", "key-B"], pause_first=0.0))
    res = await p.chat([{"role": "user", "content": "hi"}], validate=lambda t: t.startswith("{"))
    assert res.content == '{"ok": true}' and len(script.requests) == 2

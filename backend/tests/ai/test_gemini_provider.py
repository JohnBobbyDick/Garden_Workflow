"""Native Gemini provider (generateContent) and the pooled OpenAI-compatible path, on local HTTP servers."""

import pytest

from app.ai.providers.base import LLMError, ProviderConfig, build_provider
from tests.ai.fake_llm import make_server

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


@pytest.fixture
def gemini():
    srv, script, hp = make_server("gemini")
    yield script, hp
    srv.shutdown()


@pytest.fixture
def openai():
    srv, script, hp = make_server("openai")
    yield script, hp
    srv.shutdown()


def cfg(hp, provider="gemini", **kw):
    base = {"provider": provider, "base_url": f"http://{hp}/v1beta", "model": "gemini-2.5-flash",
            "api_key": "AIzaTESTKEY-0001", "timeout": 2, "allow_hosts": {hp}, "pause_first": 0, "pause_step": 0}
    base.update(kw)
    return ProviderConfig(**base)


async def test_gemini_generate_content_request_shape(gemini):
    script, hp = gemini
    script.reply({"ok": True})
    p = build_provider(cfg(hp))
    res = await p.chat([{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
                       response_schema=SCHEMA, temperature=0.1, max_tokens=50)
    req = script.requests[-1]
    assert req["path"] == "/v1beta/models/gemini-2.5-flash:generateContent"
    assert req["headers"]["x-goog-api-key"] == "AIzaTESTKEY-0001"
    assert "AIzaTESTKEY" not in req["path"] and "authorization" not in {k.lower() for k in req["headers"]}
    body = req["body"]
    assert body["generationConfig"] == {"temperature": 0.1, "maxOutputTokens": 50,
                                        "responseMimeType": "application/json"}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "hi"}]}]
    assert body["systemInstruction"]["parts"][0]["text"].startswith("sys")
    assert '"ok"' in body["systemInstruction"]["parts"][0]["text"]  # JSON schema instruction appended
    assert res.content == '{"ok": true}' and res.json_mode == "object" and res.usage["total_tokens"] == 33


async def test_gemini_falls_back_to_second_model_on_429(gemini):
    script, hp = gemini
    script.reply(status=429).reply({"ok": True})
    p = build_provider(cfg(hp, fallback_models=["gemini-2.5-flash-lite"]))
    res = await p.chat([{"role": "user", "content": "hi"}])
    assert [r["path"].split("/")[-1] for r in script.requests] == [
        "gemini-2.5-flash:generateContent", "gemini-2.5-flash-lite:generateContent"]
    assert res.model == "gemini-2.5-flash-lite"


async def test_gemini_empty_candidate_is_failure(gemini):
    script, hp = gemini
    script.reply(body={"candidates": [{"content": {"parts": [{"text": ""}]}}]})
    script.reply(body={"promptFeedback": {"blockReason": "SAFETY"}})
    p = build_provider(cfg(hp, rotation_retries=2))
    with pytest.raises(LLMError, match="исчерпаны"):
        await p.chat([{"role": "user", "content": "hi"}])


async def test_gemini_validate_rejects_and_retries(gemini):
    script, hp = gemini
    script.reply("not json").reply({"ok": True})
    p = build_provider(cfg(hp))
    res = await p.chat([{"role": "user", "content": "hi"}], validate=lambda t: t.startswith("{"))
    assert res.content == '{"ok": true}' and len(script.requests) == 2


async def test_gemini_list_models_strips_prefix(gemini):
    script, hp = gemini
    p = build_provider(cfg(hp))
    assert await p.list_models() == ["gemini-2.5-flash", "other"]
    assert script.requests[-1]["headers"]["x-goog-api-key"] == "AIzaTESTKEY-0001"


async def test_openai_compat_pooled_rotates_keys(openai):
    script, hp = openai
    script.reply(status=401).reply({"ok": True})
    p = build_provider(cfg(hp, provider="openai_compat", base_url=f"http://{hp}/v1", model="test-model",
                           api_key=None, api_keys=["key-AAAA1111", "key-BBBB2222"]))
    res = await p.chat([{"role": "user", "content": "hi"}], response_schema=SCHEMA)
    auths = [r["headers"]["Authorization"] for r in script.requests]
    assert len(auths) == 2 and len(set(auths)) == 2
    assert res.content == '{"ok": true}'

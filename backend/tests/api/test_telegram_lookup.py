import httpx

from app import telegram
from app.ai.pool import LLMEnv


def test_lookup_only_returns_the_requested_private_chat(client, alice, bob, monkeypatch):
    token = "123456789:TelegramLookupLocalCanary"
    cred = client.post("/api/credentials", headers=alice.headers, json={
        "kind": "telegram", "name": "Test bot", "value": token,
    }).json()["id"]
    url = f"/api/credentials/{cred}/telegram-chat"
    calls = []
    proxy = "http://proxy.test:8080"
    monkeypatch.setattr(telegram, "get_llm_env", lambda: LLMEnv(_env_file=None, nvidia_proxies=proxy))

    async def updates(method, target, **kwargs):
        assert method == "POST" and target.endswith(f"/bot{token}/getUpdates")
        assert kwargs["json"] == {"limit": 100, "timeout": 0}
        assert kwargs["proxy"] == proxy
        calls.append(method)
        return httpx.Response(200, json={"ok": True, "result": [
            {"message": {"chat": {"type": "private", "id": 31, "username": "AliceTest"}}},
            {"message": {"chat": {"type": "group", "id": -85, "username": "AliceTest"}}},
            {"message": {"chat": {"type": "private", "id": 91, "username": "OtherTest"}}},
        ]})

    monkeypatch.setattr(telegram, "safe_request", updates)
    assert client.post(url, headers=bob.headers, json={"username": "@alicetest"}).status_code == 404
    assert not calls
    got = client.post(url, headers=alice.headers, json={"username": "@alicetest"})
    assert got.json() == {"chat_id": "31"}
    missing = client.post(url, headers=alice.headers, json={"username": "Nobody"})
    assert missing.status_code == 404 and token not in missing.text and "OtherTest" not in missing.text

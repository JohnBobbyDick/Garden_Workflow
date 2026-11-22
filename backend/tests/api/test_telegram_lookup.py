import httpx
import pytest

from app import telegram
from app.ai.pool import LLMEnv


@pytest.fixture
def lookup(client, alice, monkeypatch):
    token = "123456789:TelegramLookupLocalCanary"
    cred = client.post("/api/credentials", headers=alice.headers, json={
        "kind": "telegram", "name": "Test bot", "value": token,
    }).json()["id"]
    url = f"/api/credentials/{cred}/telegram-chat"
    calls = []
    responses = []

    proxy = "http://telegram.test:8080"
    monkeypatch.setattr(telegram, "get_llm_env", lambda: LLMEnv(
        _env_file=None, telegram_proxies=proxy, nvidia_proxies="http://nvidia.test:8888"))

    async def request(method, target, **kwargs):
        assert kwargs["proxy"] == proxy
        assert method == "POST" and target.split("/")[-2] == f"bot{token}"
        calls.append((target.split("/")[-1], kwargs["json"]))
        return responses.pop(0)

    monkeypatch.setattr(telegram, "safe_request", request)

    def post(username="@alicetest", headers=None):
        result = client.post(url, headers=headers or alice.headers, json={"username": username})
        assert token not in result.text and "OtherTest" not in result.text
        return result

    return post, calls, responses


def missing_public():
    return httpx.Response(400, json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})


@pytest.mark.parametrize("kind", ["channel", "supergroup"])
def test_public_username_uses_get_chat(lookup, kind):
    post, calls, responses = lookup
    responses.append(httpx.Response(200, json={"ok": True, "result": {"type": kind, "id": -100777}}))
    assert post("AliceTest").json() == {"chat_id": "-100777"}
    assert calls == [("getChat", {"chat_id": "@AliceTest"})]


def test_lookup_only_returns_the_requested_private_chat(lookup, bob):
    post, calls, responses = lookup
    assert post(headers=bob.headers).status_code == 404
    assert not calls
    updates = [
        {"message": {"chat": {"type": "private", "id": 31, "username": "AliceTest"}}},
        {"message": {"chat": {"type": "group", "id": -85, "username": "AliceTest"}}},
        {"message": {"chat": {"type": "private", "id": 91, "username": "OtherTest"}}},
        {"message": {"chat": {"type": "private", "id": True, "username": "AliceTest"}}},
        None, {"message": None}, {"message": {"chat": []}},
    ]
    for name, status in [("@alicetest", 200), ("Nobody", 404)]:
        responses.extend([missing_public(), httpx.Response(200, json={"ok": True, "result": updates})])
        got = post(name)
        assert got.status_code == status
        if status == 200:
            assert got.json() == {"chat_id": "31"}
        assert calls[-1] == ("getUpdates", {"limit": 100, "timeout": 0})


@pytest.mark.parametrize(("responses", "status", "code"), [
    ([missing_public(), httpx.Response(409, text="123456789:TelegramLookupLocalCanary")], 409, "telegram_updates_busy"),
    ([httpx.Response(401, json={"ok": False, "description": "123456789:TelegramLookupLocalCanary"})],
     502, "telegram_lookup_failed"),
    ([httpx.Response(200, json={"ok": True, "result": []})], 502, "telegram_lookup_failed"),
    ([missing_public(), httpx.Response(200, json={"ok": True, "result": {}})], 502, "telegram_lookup_failed"),
])
def test_handles_remote_failures(lookup, responses, status, code):
    post, _, queue = lookup
    queue.extend(responses)
    got = post()
    assert got.status_code == status
    assert got.json()["error"]["code"] == code

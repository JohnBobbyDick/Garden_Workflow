"""AI settings with key/proxy/model pools, platform-default provider from the environment, connection diagnostics."""

import asyncio
import json
import logging
import threading

import pytest

from app.ai import settings_service
from app.ai.pool import LLMEnv
from app.config import get_settings
from tests.ai.fake_llm import make_server
from tests.ai.test_report_service import good_answer
from tests.api.conftest import drain
from tests.api.test_ai_api import ai_graph

KEY1 = "AIzaCanaryKeyNumberOne-000111"
KEY2 = "AIzaCanaryKeyNumberTwo-000222"
PROXY_PASSWORD = "Pr0xyCanary:Secret#9"


def gemini_answer(body):
    text = body["contents"][-1]["parts"][0]["text"]
    return good_answer({"messages": [{"role": "user", "content": text}]})


@pytest.fixture
def gemini():
    srv, script, hp = make_server("gemini")
    yield script, hp
    srv.shutdown()


def cred(client, user, name, kind, value) -> str:
    r = client.post("/api/credentials", json={"workspace_id": user.workspace_id, "name": name, "kind": kind,
                                              "value": value}, headers=user.headers)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


class FakeHttpProxy:
    """A real local HTTP proxy that answers every proxied request itself with a Gemini-shaped reply."""

    def __init__(self) -> None:
        self.requests: list[bytes] = []
        self.loop = asyncio.new_event_loop()
        ready = threading.Event()

        async def handle(reader, writer):
            head = await reader.readuntil(b"\r\n\r\n")
            self.requests.append(head)
            length = next((int(line.split(b":")[1]) for line in head.split(b"\r\n")
                           if line.lower().startswith(b"content-length")), 0)
            if length:
                await reader.readexactly(length)
            body = json.dumps({"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                         + str(len(body)).encode() + b"\r\n\r\n" + body)
            await writer.drain()
            writer.close()

        async def start():
            self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
            self.port = self.server.sockets[0].getsockname()[1]
            ready.set()
            try:
                await self.server.serve_forever()
            except asyncio.CancelledError:
                pass

        threading.Thread(target=lambda: self.loop.run_until_complete(start()), daemon=True).start()
        ready.wait(5)

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.server.close)


@pytest.fixture
def allow_local(monkeypatch):
    """Lets the SSRF guard reach the local fake proxies (in production proxies are public hosts)."""
    def apply(*hosts: str):
        monkeypatch.setenv("APP_SSRF_ALLOW_HOSTS", ",".join(hosts))
        get_settings.cache_clear()
    yield apply
    get_settings.cache_clear()


def test_put_and_get_pool_settings_roundtrip(client, alice, gemini):
    _, hp = gemini
    k1, k2 = cred(client, alice, "k1", "llm_api_key", KEY1), cred(client, alice, "k2", "llm_api_key", KEY2)
    px = cred(client, alice, "proxy", "proxy", f"203.0.113.10:1080:user:{PROXY_PASSWORD}")
    r = client.put("/api/settings/ai", json={
        "workspace_id": alice.workspace_id, "enabled": True, "provider": "gemini",
        "base_url": f"http://{hp}/v1beta", "model": "gemini-2.5-flash", "credential_id": k1,
        "credential_ids": [k2], "proxy_credential_ids": [px], "fallback_models": ["gemini-2.5-flash-lite"],
        "proxy_scheme": "socks5", "proxy_port": "1080", "max_retries": 4, "allow_local": True}, headers=alice.headers)
    assert r.status_code == 200, r.text
    got = client.get("/api/settings/ai", headers=alice.headers).json()
    assert got["credential_ids"] == [k2] and got["proxy_credential_ids"] == [px]
    assert got["fallback_models"] == ["gemini-2.5-flash-lite"] and got["proxy_scheme"] == "socks5"
    assert got["max_retries"] == 4 and "gemini" in got["providers"]
    assert KEY1 not in r.text + json.dumps(got) and "Pr0xyCanary" not in r.text + json.dumps(got)


def test_put_rejects_foreign_or_wrong_kind_proxy(client, alice, gemini):
    _, hp = gemini
    k = cred(client, alice, "k", "llm_api_key", KEY1)
    r = client.put("/api/settings/ai", json={
        "workspace_id": alice.workspace_id, "enabled": True, "provider": "gemini", "base_url": f"http://{hp}/v1beta",
        "model": "m", "credential_id": k, "proxy_credential_ids": [k]}, headers=alice.headers)
    assert r.status_code == 400


def test_pool_config_built_from_vault(client, alice, db, gemini):
    _, hp = gemini
    k1, k2 = cred(client, alice, "k1", "llm_api_key", KEY1), cred(client, alice, "k2", "llm_api_key", KEY2)
    px = cred(client, alice, "proxy", "proxy", f"203.0.113.10:user:{PROXY_PASSWORD}")
    client.put("/api/settings/ai", json={
        "workspace_id": alice.workspace_id, "enabled": True, "provider": "gemini", "base_url": f"http://{hp}/v1beta",
        "model": "gemini-2.5-flash", "credential_id": k1, "credential_ids": [k2], "proxy_credential_ids": [px],
        "proxy_scheme": "http", "proxy_port": "3128", "max_retries": 3}, headers=alice.headers)
    from app.core.masking import Masker
    with db.session() as s:
        cfg = settings_service.provider_config_for(s, alice.workspace_id, None, Masker())
    assert cfg.provider == "gemini" and cfg.keys == [KEY1, KEY2]
    assert cfg.proxies == ["http://user:Pr0xyCanary%3ASecret%239@203.0.113.10:3128"]
    assert cfg.rotation_retries == 3 and cfg.fallback_models == []


def test_env_default_used_when_workspace_unconfigured(client, db, alice, gemini, monkeypatch):
    script, hp = gemini
    script.dynamic = gemini_answer
    env = LLMEnv(_env_file=None, llm_enabled=True, llm_provider="gemini", gemini_api_key=KEY1,
                 gemini_base_url=f"http://{hp}/v1beta", gemini_model="gemini-2.5-flash", gemini_fallback_models="")
    monkeypatch.setattr(settings_service, "get_llm_env", lambda: env)
    assert client.get("/api/settings/ai", headers=alice.headers).json()["env_default"] == {
        "enabled": True, "provider": "gemini", "model": "gemini-2.5-flash"}
    wid = client.post("/api/workflows", json={"name": "ai", "graph": ai_graph(), "workspace_id": alice.workspace_id},
                      headers=alice.headers).json()["id"]
    rid = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
    drain(db)
    ai = client.get(f"/api/runs/{rid}/ai-report", headers=alice.headers).json()
    assert ai["ai_generated"] is True and ai["provider"] == "gemini"
    assert script.requests[-1]["headers"]["x-goog-api-key"] == KEY1
    assert KEY1 not in json.dumps(ai)


def test_env_disabled_means_no_provider(db, alice, monkeypatch):
    monkeypatch.setattr(settings_service, "get_llm_env", lambda: LLMEnv(_env_file=None, llm_enabled=False))
    from app.core.masking import Masker
    with db.session() as s:
        assert settings_service.provider_config_for(s, alice.workspace_id, None, Masker()) is None


def test_diagnose_reports_per_proxy_without_secrets(client, alice, gemini, allow_local, caplog):
    script, hp = gemini
    script.default = {"status": 200, "content": {"ok": True}, "delay": 0, "body": None, "headers": {}}
    live = FakeHttpProxy()
    try:
        allow_local(hp, f"127.0.0.1:{live.port}", "127.0.0.1:9")
        k = cred(client, alice, "k", "llm_api_key", KEY1)
        good = cred(client, alice, "good", "proxy", f"http://user:{PROXY_PASSWORD.replace(':', '%3A').replace('#', '%23')}@127.0.0.1:{live.port}")
        dead = cred(client, alice, "dead", "proxy", f"127.0.0.1:9:user:{PROXY_PASSWORD}")
        client.put("/api/settings/ai", json={
            "workspace_id": alice.workspace_id, "enabled": True, "provider": "gemini",
            "base_url": f"http://{hp}/v1beta", "model": "gemini-2.5-flash", "credential_id": k,
            "proxy_credential_ids": [good, dead], "proxy_scheme": "auto", "allow_local": True}, headers=alice.headers)
        caplog.set_level(logging.INFO)
        r = client.post("/api/settings/ai/diagnose", json={"workspace_id": alice.workspace_id},
                        headers=alice.headers)
        assert r.status_code == 200, r.text
        rows = r.json()["results"]
        assert rows[-1]["proxy"] == "direct" and rows[-1]["ok"] is True
        good_rows = [x for x in rows if x["proxy"] == f"http://127.0.0.1:{live.port}"]
        dead_rows = [x for x in rows if x["proxy"].endswith("127.0.0.1:9")]
        assert len(good_rows) == 1 and good_rows[0]["ok"] is True
        assert {x["scheme"] for x in dead_rows} == {"http", "socks5", "https", "socks5h"}
        assert not any(x["ok"] for x in dead_rows) and all(x["error"] for x in dead_rows)
        blob = r.text + caplog.text
        assert KEY1 not in blob and "Pr0xyCanary" not in blob and "Secret%239" not in blob
        assert live.requests and b"generateContent" in live.requests[0]
    finally:
        live.close()


def test_proxy_credential_kind_accepted(client, alice):
    cid = cred(client, alice, "p", "proxy", "203.0.113.5:1080:u:p")
    listed = client.get("/api/credentials", headers=alice.headers).json()
    assert any(c["id"] == cid and c["kind"] == "proxy" for c in listed)


def test_proxy_credential_display_shows_host_only(client, alice):
    cred(client, alice, "p2", "proxy", "203.0.113.5:1080:user:Secret:pw")
    row = next(c for c in client.get("/api/credentials", headers=alice.headers).json() if c["name"] == "p2")
    assert row["display"] == "203.0.113.5:1080" and "pw" not in row["display"]

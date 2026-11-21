import pytest

from app import models as m
from app.ai import settings_service
from app.ai.pool import LLMEnv
from app.core.masking import Masker
from app.engine.graph import GraphNode
from app.nodes.ai.ai_report import AIReport

URL = "https://integrate.api.nvidia.com/v1"
MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"


def test_advertised_defaults(client, alice):
    settings = client.get("/api/settings/ai", headers=alice.headers).json()
    assert settings["providers"] == ["nvidia", "ollama"]
    assert (settings["provider"], settings["base_url"], settings["model"]) == ("nvidia", URL, MODEL)
    assert settings["ollama_defaults"] == {"base_url": "http://localhost:11434", "model": "qwen2.5:3b"}


@pytest.mark.parametrize("bad", [
    {"provider": "openai_compat", "base_url": "http://localhost:8080", "model": "m"},
    {"provider": "gemini"}, {"provider": "nvidia", "model": "custom"},
    {"provider": "nvidia", "base_url": "https://example.org/v1"},
    {"provider": "nvidia", "fallback_models": ["other"]},
])
def test_put_rejects_unsupported_config(client, alice, bad):
    r = client.put("/api/settings/ai", headers=alice.headers, json={"enabled": True, **bad})
    assert r.status_code in (400, 422)


def test_workspace_can_use_platform_key_only_with_operator_routing(client, db, alice, monkeypatch):
    env = LLMEnv(_env_file=None, llm_enabled=True, llm_provider="ollama", nvidia_api_key="platform-test-key")
    monkeypatch.setattr(settings_service, "get_llm_env", lambda: env)
    r = client.put("/api/settings/ai", headers=alice.headers, json={"enabled": True, "provider": "nvidia"})
    assert r.status_code == 200, r.text
    with db.session() as s:
        row = s.get(m.AISettings, alice.workspace_id)
        row.extra = {"headers": {"X-Test": "user"}, "proxy_credential_ids": ["untrusted"], "allow_host": "malicious"}
        cfg = settings_service.provider_config_for(s, alice.workspace_id, None, Masker())
        assert cfg.keys == ["platform-test-key"] and cfg.base_url == URL and cfg.models == [MODEL]
        assert cfg.headers == {} and cfg.proxies == [] and "malicious" not in cfg.allow_hosts


@pytest.mark.parametrize("enabled", [True, False])
def test_retired_workspace_is_inactive_until_reconfigured(client, db, alice, monkeypatch, enabled):
    env = LLMEnv(_env_file=None, llm_enabled=True, nvidia_api_key="platform-test-key")
    monkeypatch.setattr(settings_service, "get_llm_env", lambda: env)
    with db.session() as s:
        s.add(m.AISettings(workspace_id=alice.workspace_id, provider="openai_compat",
                           base_url="http://localhost:8000", model="local", enabled=enabled))
        s.commit()
        for require_enabled in (True, False):
            assert settings_service.provider_config_for(s, alice.workspace_id, None, Masker(), require_enabled) is None
    out = client.get("/api/settings/ai", headers=alice.headers).json()
    assert out["requires_reconfiguration"] and not out["enabled"]
    assert out["credential_id"] is None and out["base_url"] == URL


def test_existing_nvidia_workspace_and_graph_are_recognized(db, alice, monkeypatch):
    env = LLMEnv(_env_file=None, llm_enabled=True, nvidia_api_key="platform-test-key")
    monkeypatch.setattr(settings_service, "get_llm_env", lambda: env)
    legacy = {"provider": "openai_compat", "base_url": URL + "/", "model": MODEL}
    with db.session() as s:
        s.add(m.AISettings(workspace_id=alice.workspace_id, enabled=True, **legacy))
        s.flush()
        cfg = settings_service.provider_config_for(s, alice.workspace_id, None, Masker())
        assert (cfg.provider, cfg.base_url, cfg.model) == ("nvidia", URL, MODEL)
    node = GraphNode(id="ai", type="ai.report", config=legacy)
    assert node.config["provider"] == "nvidia" and not AIReport.validate_config(node.config)


def test_report_node_validates_pinned_endpoint_and_model():
    assert AIReport.validate_config({"provider": "nvidia"}) == []
    assert AIReport.validate_config({"provider": "nvidia", "base_url": "https://example.org", "model": MODEL})
    assert AIReport.validate_config({"provider": "nvidia", "base_url": URL, "model": "other"})

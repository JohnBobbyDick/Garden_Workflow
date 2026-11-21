import pytest

from app.ai.pool import NEMOTRON_LIGHTNING
from tests.ai.test_report_service import good_answer
from tests.api.conftest import User, drain
from tests.engine.test_worker_scheduler import full_graph

KEY = "sk-or-v1-canaryApiKeyForLlmProvider000111"


@pytest.fixture
def llm(nvidia_server):
    script, hp = nvidia_server
    script.dynamic = good_answer
    return script, hp


def configure(client, user, hp, **kw):
    cid = client.post("/api/credentials", json={"workspace_id": user.workspace_id, "name": "llm", "kind": "llm_api_key",
                                                "value": KEY}, headers=user.headers).json()["id"]
    body = {"workspace_id": user.workspace_id, "enabled": True, "provider": "nvidia", "credential_id": cid}
    body.update(kw)
    return client.put("/api/settings/ai", json=body, headers=user.headers)


def ai_graph():
    g = full_graph()
    g["nodes"] = [n for n in g["nodes"] if n["id"] != "exp"]
    g["edges"] = [e for e in g["edges"] if e["target"] != "exp"]
    g["nodes"] += [{"id": "ai", "type": "ai.report", "config": {}},
                   {"id": "coverage", "type": "analysis.ai_coverage", "config": {}},
                   {"id": "exp", "type": "output.report_export", "config": {}}]
    g["edges"] += [{"id": "a1", "source": "if", "source_port": "true", "target": "ai", "target_port": "in"},
                   {"id": "a2", "source": "merge", "source_port": "out", "target": "exp", "target_port": "in"},
                   {"id": "a3", "source": "ai", "source_port": "out", "target": "exp", "target_port": "ai"},
                   {"id": "a4", "source": "ai", "source_port": "out", "target": "coverage", "target_port": "in"}]
    return g


def test_ai_settings_default_off_and_admin_only(client, alice, bob, llm):
    _, hp = llm
    s = client.get("/api/settings/ai", headers=alice.headers).json()
    assert s["enabled"] is False and {"nvidia", "ollama"} == set(s["providers"])
    assert any("Ollama" in h for h in s["hints"])
    client.post(f"/api/workspaces/{alice.workspace_id}/members", json={"email": bob.email, "role": "developer"},
                headers=alice.headers)
    r = client.put("/api/settings/ai", json={"workspace_id": alice.workspace_id, "enabled": True,
                                             "provider": "ollama", "base_url": "http://localhost:11434",
                                             "model": "m"}, headers=bob.headers)
    assert r.status_code == 403
    r = configure(client, alice, hp)
    assert r.status_code == 200 and r.json()["enabled"] is True and KEY not in r.text


def test_ai_connection_test_and_models(client, alice, llm):
    script, hp = llm
    configure(client, alice, hp)
    script.reply({"ok": True})
    r = client.post("/api/settings/ai/test", json={"workspace_id": alice.workspace_id}, headers=alice.headers).json()
    assert r["ok"] is True and r["models"] == [NEMOTRON_LIGHTNING]
    assert script.requests[-1]["headers"]["Authorization"] == f"Bearer {KEY}"
    assert KEY not in str(r)


@pytest.mark.parametrize("answer", ["", "broken-json", {"ok": False}, {"ok": 1}, {"other": True}])
def test_nemotron_probes_reject_incorrect_answers(client, alice, llm, answer):
    script, hp = llm
    configure(client, alice, hp, model=NEMOTRON_LIGHTNING)
    for path in ("test", "diagnose"):
        script.reply(answer)
        result = client.post(f"/api/settings/ai/{path}", json={"workspace_id": alice.workspace_id},
                             headers=alice.headers).json()
        row = result["results"][-1] if path == "diagnose" else result
        assert row["ok"] is False and row["error"]
        assert script.requests[-1]["body"]["chat_template_kwargs"] == {"enable_thinking": False}


def test_ai_report_end_to_end(client, db, alice, llm):
    script, hp = llm
    configure(client, alice, hp, model=NEMOTRON_LIGHTNING)
    wid = client.post("/api/workflows", json={"name": "ai", "graph": ai_graph(), "workspace_id": alice.workspace_id},
                      headers=alice.headers).json()["id"]
    rid = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
    drain(db)
    run = client.get(f"/api/runs/{rid}", headers=alice.headers).json()
    assert run["status"] == "success", run["error"]
    coverage = next(n for n in run["nodes"] if n["node_id"] == "coverage")
    assert coverage["output_summary"]["summary"] == "15/15"
    ai = client.get(f"/api/runs/{rid}/ai-report", headers=alice.headers).json()
    assert ai["ai_generated"] is True and ai["provider"] == "nvidia" and ai["model"] == NEMOTRON_LIGHTNING
    assert len(ai["report"]["findings"]) == 15 and ai["validation"]["metrics"]["valid_items"] == 15
    md = client.get(f"/api/runs/{rid}/export/report.md", headers=alice.headers).text
    assert "AI-объяснение" in md and "```diff" in md and "Доверие к ответу" in md
    art = client.get(f"/api/runs/{rid}/artifacts/report.md", headers=alice.headers).text
    assert "AI-объяснение" in art
    html = client.get(f"/api/runs/{rid}/export/report.html", headers=alice.headers).text
    assert "AI-объяснение" in html
    events = client.get(f"/api/runs/{rid}/events", headers=alice.headers).text
    assert KEY not in events and KEY not in md


def test_ai_report_falls_back_when_provider_down(client, db, alice, llm):
    script, hp = llm
    configure(client, alice, hp)
    script.dynamic = None
    for _ in range(10):
        script.reply(status=500)
    wid = client.post("/api/workflows", json={"name": "ai", "graph": ai_graph(), "workspace_id": alice.workspace_id},
                      headers=alice.headers).json()["id"]
    rid = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
    drain(db)
    run = client.get(f"/api/runs/{rid}", headers=alice.headers).json()
    assert run["status"] == "success"
    coverage = next(n for n in run["nodes"] if n["node_id"] == "coverage")
    assert coverage["output_summary"]["summary"] == "0/15"
    ai = client.get(f"/api/runs/{rid}/ai-report", headers=alice.headers).json()
    assert ai["ai_generated"] is False and ai["error"]
    md = client.get(f"/api/runs/{rid}/export/report.md", headers=alice.headers).text
    assert "без AI" in md


def test_ai_report_without_fallback_fails_node(client, db, alice):
    g = ai_graph()
    next(n for n in g["nodes"] if n["id"] == "ai")["config"] = {"fallback_to_deterministic": False}
    wid = client.post("/api/workflows", json={"name": "ai", "graph": g, "workspace_id": alice.workspace_id},
                      headers=alice.headers).json()["id"]
    rid = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
    drain(db)
    run = client.get(f"/api/runs/{rid}", headers=alice.headers).json()
    node = next(n for n in run["nodes"] if n["node_id"] == "ai")
    assert run["status"] == "failed" and node["status"] == "failed" and "не настроен" in node["error"]


def test_node_provider_override(client, db, alice, llm):
    script, hp = llm
    g = ai_graph()
    cid = client.post("/api/credentials", json={"workspace_id": alice.workspace_id, "name": "k2", "value": KEY},
                      headers=alice.headers).json()["id"]
    client.put("/api/settings/ai", json={"workspace_id": alice.workspace_id, "enabled": False, "provider": "ollama",
                                         "base_url": f"http://{hp}", "model": "x", "allow_local": True},
               headers=alice.headers)
    next(n for n in g["nodes"] if n["id"] == "ai")["config"] = {
        "provider": "nvidia", "api_key": cid}
    wid = client.post("/api/workflows", json={"name": "ai", "graph": g, "workspace_id": alice.workspace_id},
                      headers=alice.headers).json()["id"]
    rid = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
    drain(db)
    ai = client.get(f"/api/runs/{rid}/ai-report", headers=alice.headers).json()
    assert ai["ai_generated"] is True and ai["model"] == NEMOTRON_LIGHTNING


def test_ai_report_404_when_absent_and_cross_workspace(client, db, alice):
    wid = client.post("/api/workflows", json={"name": "x", "graph": full_graph(), "workspace_id": alice.workspace_id},
                      headers=alice.headers).json()["id"]
    rid = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
    drain(db)
    assert client.get(f"/api/runs/{rid}/ai-report", headers=alice.headers).status_code == 404
    other = User(client, "eve@example.org")
    assert client.get(f"/api/runs/{rid}/ai-report", headers=other.headers).status_code == 404

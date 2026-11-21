"""«Новая проверка» in one request: source → starter / template / blank graph, source written into every source.repo."""

import io
import zipfile

import pytest

from app.api import repos
from app.templates_lib import TemplateParamError, apply_parameters
from tests.api.conftest import drain


def create(client, user, **body):
    return client.post("/api/checks", json={"workspace_id": user.workspace_id, **body}, headers=user.headers)


def graph_of(client, user, wid):
    return client.get(f"/api/workflows/{wid}", headers=user.headers).json()["graph"]


def sources(graph):
    return [n["config"] for n in graph["nodes"] if n["type"] == "source.repo"]


def test_starters_listed_in_order(client, alice):
    r = client.get("/api/checks/starters", headers=alice.headers).json()
    assert [x["id"] for x in r] == ["full", "secrets", "pr"]
    assert all(x["title"] and x["description"] for x in r)


def test_training_full_check_is_valid_and_runs(client, db, alice):
    r = create(client, alice, source={"mode": "training"}, start={"starter": "full"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["needs_input"] == []
    wf = client.get(f"/api/workflows/{body['workflow_id']}", headers=alice.headers).json()
    assert wf["name"] == "Учебный проект"
    assert sources(wf["graph"])[0]["mode"] == "path" and sources(wf["graph"])[0]["path"].endswith("training-project")
    v = client.post("/api/workflows/validate", json={"workspace_id": alice.workspace_id, "graph": wf["graph"]},
                    headers=alice.headers).json()
    assert v["valid"] is True, v
    rid = client.post(f"/api/workflows/{wf['id']}/run", headers=alice.headers).json()["id"]
    drain(db)
    run = client.get(f"/api/runs/{rid}", headers=alice.headers).json()
    assert run["status"] == "success" and run["summary"]["total"] == 15


def test_git_url_requires_attestation(client, alice, monkeypatch):
    r = create(client, alice, source={"mode": "git_url", "url": "https://github.com/org/repo"}, start={"blank": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_attested"
    monkeypatch.setattr(repos, "RESOLVER", lambda host, port: ["140.82.121.4"])
    client.post("/api/repos/attest", json={"workspace_id": alice.workspace_id, "url": "https://github.com/org/repo",
                                           "confirm": True}, headers=alice.headers)
    r = create(client, alice, source={"mode": "git_url", "url": "https://github.com/Org/Repo.git", "ref": "dev",
                                      "subdir": "service"}, start={"starter": "secrets"})
    assert r.status_code == 201, r.text
    wid = r.json()["workflow_id"]
    assert client.get(f"/api/workflows/{wid}", headers=alice.headers).json()["name"] == "repo"
    assert sources(graph_of(client, alice, wid)) == [{"mode": "git_url", "git_url": "https://github.com/org/repo",
                                                      "ref": "dev", "subdir": "service"}]


def test_platform_repo_needs_no_attestation(client, alice):
    r = create(client, alice, source={"mode": "git_url", "url": "https://github.com/TBagirov/training"},
               start={"blank": True})
    assert r.status_code == 201, r.text


def test_blank_graph(client, alice):
    wid = create(client, alice, source={"mode": "training"}, start={"blank": True}).json()["workflow_id"]
    g = graph_of(client, alice, wid)
    assert [n["type"] for n in g["nodes"]] == ["trigger.manual", "source.repo"] and len(g["edges"]) == 1


def test_upload_source(client, alice):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("proj/build.gradle.kts", "plugins {}\n")
    up = client.post("/api/uploads", data={"workspace_id": alice.workspace_id},
                     files={"file": ("my-service.zip", buf.getvalue(), "application/zip")}, headers=alice.headers)
    assert up.status_code in (200, 201), up.text
    uid = up.json()["id"]
    r = create(client, alice, source={"mode": "upload", "upload_id": uid}, start={"starter": "full"})
    assert r.status_code == 201, r.text
    wid = r.json()["workflow_id"]
    assert client.get(f"/api/workflows/{wid}", headers=alice.headers).json()["name"] == "my-service"
    assert all(c == {"mode": "upload", "upload_id": uid} for c in sources(graph_of(client, alice, wid)))


def test_foreign_upload_rejected(client, alice, bob):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.kt", "fun main() {}\n")
    uid = client.post("/api/uploads", data={"workspace_id": bob.workspace_id},
                      files={"file": ("b.zip", buf.getvalue(), "application/zip")}, headers=bob.headers).json()["id"]
    r = create(client, alice, source={"mode": "upload", "upload_id": uid}, start={"blank": True})
    assert r.status_code == 422


def test_template_with_unfilled_notification_params_is_created(client, alice):
    tpl = next(t for t in client.get("/api/templates", params={"q": "Telegram"}, headers=alice.headers)
               .json()["templates"] if "Telegram" in t["name"])
    r = create(client, alice, source={"mode": "training"}, start={"template_id": tpl["id"]})
    assert r.status_code == 201, r.text
    needs = r.json()["needs_input"]
    assert {"node_id": "tg", "field": "bot_token"} in needs and {"node_id": "tg", "field": "chat_id"} in needs
    assert all(c["mode"] == "path" for c in sources(graph_of(client, alice, r.json()["workflow_id"])))


def test_prompt_without_llm_is_explained(client, alice):
    r = create(client, alice, source={"mode": "training"}, start={"prompt": "Проверь секреты каждый день в 14:00"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "ai_not_configured"


def test_bad_start_rejected(client, alice):
    assert create(client, alice, source={"mode": "training"}, start={}).status_code == 422
    assert create(client, alice, source={"mode": "training"}, start={"starter": "nope"}).status_code == 422


def test_apply_parameters_partial_mode():
    graph = {"nodes": [{"id": "tg", "type": "notify.telegram", "config": {"chat_id": "{{param:tg.chat_id}}"}}],
             "edges": []}
    params = [{"name": "tg.chat_id", "type": "string", "required": True}]
    with pytest.raises(TemplateParamError):
        apply_parameters(graph, params, {}, lambda c: True)
    missing: list = []
    g = apply_parameters(graph, params, {}, lambda c: True, missing=missing)
    assert g["nodes"][0]["config"] == {} and missing == [{"node_id": "tg", "field": "chat_id"}]

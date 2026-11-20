"""Phase-3 platform security: secret never leaks, roles/IDOR, allowlist, rate limit, CORS, limits."""

import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from app.config import get_settings
from tests.api.conftest import User, drain
from tests.engine.test_worker_scheduler import full_graph
from tests.nodes.conftest import TRAINING

SECRET = "123456789:AAInjectedCanarySecret_zz9QxWv8Tt7Ru6Sp"


class EvilTelegram(BaseHTTPRequestHandler):
    """Telegram mock that echoes the token back in its error (worst case for leaks)."""

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        token = self.path.split("/")[1].removeprefix("bot")
        body = json.dumps({"ok": False, "description": f"Unauthorized: bad token {token}"}).encode()
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def evil(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), EvilTelegram)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    hp = f"127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setenv("APP_SSRF_ALLOW_HOSTS", hp)
    monkeypatch.setenv("APP_TELEGRAM_API_BASE", f"http://{hp}")
    get_settings.cache_clear()
    yield hp
    srv.shutdown()
    get_settings.cache_clear()


def test_injected_secret_never_appears_in_db_api_events_logs(client, db, alice, evil, caplog):
    caplog.set_level(logging.DEBUG)
    cid = client.post("/api/credentials", json={"workspace_id": alice.workspace_id, "name": "tg", "kind": "telegram",
                                                "value": SECRET}, headers=alice.headers).json()["id"]
    g = full_graph()
    g["nodes"].append({"id": "tg", "type": "notify.telegram", "config": {"bot_token": cid, "chat_id": "1"}})
    g["edges"].append({"id": "etg", "source": "merge", "source_port": "out", "target": "tg", "target_port": "in"})
    wid = client.post("/api/workflows", json={"name": "leak", "graph": g, "workspace_id": alice.workspace_id},
                      headers=alice.headers).json()["id"]
    rid = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
    drain(db)
    responses = []
    for url in (f"/api/runs/{rid}", f"/api/runs/{rid}/events", f"/api/runs/{rid}/findings", "/api/credentials",
                f"/api/runs/{rid}/export/report.md", f"/api/runs/{rid}/export/report.html",
                f"/api/runs/{rid}/export/submission.json", f"/api/workspaces/{alice.workspace_id}/audit",
                f"/api/workflows/{wid}", "/api/runs"):
        r = client.get(url, headers=alice.headers)
        assert r.status_code == 200, url
        responses.append(r.text)
    run = client.get(f"/api/runs/{rid}", headers=alice.headers).json()
    tg = next(n for n in run["nodes"] if n["node_id"] == "tg")
    assert tg["status"] == "failed" and "Unauthorized: bad token" in tg["error"]  # the error is kept, masked
    assert run["notifications"][0]["status"] == "failed"
    blob = "\n".join(responses)
    with db.engine.connect() as c:
        for table in inspect(db.engine).get_table_names():
            for row in c.execute(text(f'SELECT * FROM "{table}"')):
                blob += "\n" + " ".join(str(v) for v in row)
    blob += "\n".join(r.getMessage() for r in caplog.records)
    assert SECRET not in blob
    assert SECRET.split(":")[1] not in blob


def test_masker_knows_stored_credentials_after_restart(client, db, alice):
    from app.core.masking import Masker
    from app.engine.services import preload_credentials

    client.post("/api/credentials", json={"workspace_id": alice.workspace_id, "name": "k", "value": "restart-canary-42"},
                headers=alice.headers)
    fresh = Masker()
    assert preload_credentials(db, fresh) == 1
    assert "restart-canary-42" not in fresh.mask("x restart-canary-42 y")


def test_login_rate_limit(client):
    User(client, "rl@example.org")
    codes = [client.post("/api/auth/login", json={"email": "rl@example.org", "password": "wrong-password"}).status_code
             for _ in range(get_settings().login_rate_limit + 1)]
    assert codes[:-1] == [401] * get_settings().login_rate_limit and codes[-1] == 429


def test_cors_only_for_configured_origins(client):
    ok = client.options("/api/healthz", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/api/healthz", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_body_size_limit(client, alice, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_body_bytes", 1000)
    r = client.post("/api/workflows", content=b"{" + b" " * 5000 + b"}",
                    headers={**alice.headers, "Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


def test_invitation_flow_and_roles(client, alice):
    r = client.post(f"/api/workspaces/{alice.workspace_id}/members", json={"email": "new@example.org", "role": "developer"},
                    headers=alice.headers)
    assert r.json()["status"] == "invited"
    token = r.json()["invite_token"]
    newbie = User(client, "new@example.org")
    assert client.post("/api/invitations/accept", json={"token": token}, headers=newbie.headers).status_code == 200
    assert client.get(f"/api/workspaces/{alice.workspace_id}", headers=newbie.headers).json()["role"] == "developer"
    # developer cannot manage members or credentials
    assert client.post(f"/api/workspaces/{alice.workspace_id}/members", json={"email": "x@example.org"},
                       headers=newbie.headers).status_code == 403
    assert client.post("/api/credentials", json={"workspace_id": alice.workspace_id, "name": "n", "value": "v12345"},
                       headers=newbie.headers).status_code == 403
    # token is single-use
    assert client.post("/api/invitations/accept", json={"token": token}, headers=newbie.headers).status_code == 404


def test_last_admin_cannot_be_demoted_or_removed(client, alice):
    r = client.patch(f"/api/workspaces/{alice.workspace_id}/members/{alice.id}", json={"role": "viewer"},
                     headers=alice.headers)
    assert r.status_code == 400 and r.json()["error"]["code"] == "last_admin"
    assert client.delete(f"/api/workspaces/{alice.workspace_id}/members/{alice.id}",
                         headers=alice.headers).status_code == 400


def test_allowlist_rules(client, alice, bob):
    ws = alice.workspace_id
    client.post(f"/api/workspaces/{ws}/members", json={"email": bob.email, "role": "developer"}, headers=alice.headers)
    body = {"workspace_id": ws, "entries": [{"url": "https://github.com/alice/own-training"}]}
    assert client.put("/api/settings/allowlist", json=body, headers=bob.headers).status_code == 403
    organizer = {"workspace_id": ws, "entries": [{"url": "https://github.com/TBagirov/training", "allow_write": True}]}
    r = client.put("/api/settings/allowlist", json=organizer, headers=alice.headers)
    assert r.status_code == 403 and r.json()["error"]["code"] == "readonly_repository"
    bad = client.post("/api/projects", json={"workspace_id": ws, "name": "x", "source_mode": "git_url",
                                             "git_url": "https://github.com/alice/own-training"}, headers=alice.headers)
    assert bad.status_code == 422 and "allowlist" in bad.json()["error"]["message"]
    r = client.put("/api/settings/allowlist", json={"workspace_id": ws, "entries": [
        {"url": "https://github.com/alice/own-training", "allow_write": True}]}, headers=alice.headers)
    assert r.status_code == 200 and r.json()["entries"][0]["allow_write"] is True
    ok = client.post("/api/projects", json={"workspace_id": ws, "name": "own", "source_mode": "git_url",
                                            "git_url": "https://github.com/alice/own-training"}, headers=alice.headers)
    assert ok.status_code == 201
    for scheme in ("file:///etc", "ssh://github.com/a/b", "http://github.com/a/b"):
        r = client.put("/api/settings/allowlist", json={"workspace_id": ws, "entries": [{"url": scheme}]},
                       headers=alice.headers)
        assert r.status_code == 400, scheme
    actions = [a["action"] for a in client.get(f"/api/workspaces/{ws}/audit", headers=alice.headers).json()]
    assert "allowlist.add" in actions and "credential.create" not in actions


def test_path_source_outside_scan_roots_rejected(client, alice, tmp_path):
    r = client.post("/api/projects", json={"workspace_id": alice.workspace_id, "name": "p", "source_mode": "path",
                                           "path": str(tmp_path)}, headers=alice.headers)
    assert r.status_code == 422
    r = client.post("/api/projects", json={"workspace_id": alice.workspace_id, "name": "p", "source_mode": "path",
                                           "path": str(TRAINING)}, headers=alice.headers)
    assert r.status_code == 201


def test_idor_matrix(client, db, alice, bob):
    ws = alice.workspace_id
    cred = client.post("/api/credentials", json={"workspace_id": ws, "name": "c", "value": "value-123456"},
                       headers=alice.headers).json()["id"]
    proj = client.post("/api/projects", json={"workspace_id": ws, "name": "p", "source_mode": "path",
                                              "path": str(TRAINING)}, headers=alice.headers).json()["id"]
    wid = client.post("/api/workflows", json={"name": "w", "graph": full_graph(), "workspace_id": ws},
                      headers=alice.headers).json()["id"]
    rid = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
    drain(db)
    own_wid = client.post("/api/workflows", json={"name": "b", "graph": full_graph()}, headers=bob.headers).json()["id"]
    own_rid = client.post(f"/api/workflows/{own_wid}/run", headers=bob.headers).json()["id"]
    drain(db)
    h = bob.headers
    checks = [
        client.get(f"/api/projects/{proj}", headers=h), client.patch(f"/api/projects/{proj}", json={"name": "x"}, headers=h),
        client.delete(f"/api/projects/{proj}", headers=h),
        client.put(f"/api/credentials/{cred}", json={"value": "zzzzzz"}, headers=h),
        client.delete(f"/api/credentials/{cred}", headers=h),
        client.get("/api/credentials", params={"workspace_id": ws}, headers=h),
        client.get(f"/api/workspaces/{ws}", headers=h), client.get(f"/api/workspaces/{ws}/members", headers=h),
        client.get(f"/api/workspaces/{ws}/audit", headers=h),
        client.get("/api/settings/allowlist", params={"workspace_id": ws}, headers=h),
        client.get(f"/api/workflows/{wid}/schedule", headers=h),
        client.post(f"/api/runs/{rid}/cancel", headers=h),
        client.get(f"/api/runs/{rid}/artifacts/report.md", headers=h),
        client.get("/api/runs/compare", params={"base": rid, "head": own_rid}, headers=h),
        client.get("/api/runs", params={"workspace_id": ws}, headers=h),
        client.get("/api/workflows", params={"workspace_id": ws}, headers=h),
    ]
    assert [r.status_code for r in checks] == [404] * len(checks)
    # bob cannot attach alice's project or credential to his own workflow
    r = client.put(f"/api/workflows/{own_wid}", json={"project_id": proj}, headers=h)
    assert r.status_code == 400
    g = full_graph()
    g["nodes"].append({"id": "tg", "type": "notify.telegram", "config": {"bot_token": cred, "chat_id": "1"}})
    g["edges"].append({"id": "x", "source": "merge", "source_port": "out", "target": "tg", "target_port": "in"})
    client.put(f"/api/workflows/{own_wid}", json={"graph": g}, headers=h)
    issues = client.post(f"/api/workflows/{own_wid}/validate", headers=h).json()["issues"]
    assert any(i["code"] == "unknown_credential" for i in issues)


def test_analyzers_never_execute_project_code():
    root = Path(__file__).resolve().parents[2] / "app" / "analyzers"
    forbidden = re.compile(r"\b(subprocess|os\.system|os\.popen|eval\(|exec\(|importlib|runpy|pickle\.load)")
    hits = [f"{p.name}:{i}" for p in root.rglob("*.py")
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if forbidden.search(line)]
    assert hits == []

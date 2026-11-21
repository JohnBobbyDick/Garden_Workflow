import io
import json
import zipfile

from sqlalchemy import select

from app import models as m
from app.export.validator import validate_submission
from tests.api.conftest import User, drain
from tests.engine.test_worker_scheduler import full_graph
from tests.nodes.conftest import TRAINING


def test_error_format_and_auth_required(client):
    r = client.get("/api/workflows")
    assert r.status_code == 401
    assert set(r.json()["error"]) == {"code", "message", "details"}


def test_register_login_me_and_bad_password(client):
    u = User(client, "carol@example.org")
    r = client.post("/api/auth/login", json={"email": "carol@example.org", "password": "wrong-password-1"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    r = client.post("/api/auth/login", json={"email": "carol@example.org", "password": u.password})
    assert r.status_code == 200 and r.json()["access_token"]
    assert client.post("/api/auth/register", json={"email": "carol@example.org", "password": "Another-pass1", "code": "000000"}
                       ).status_code == 409


def test_refresh_rotation_and_reuse_detection(client):
    u = User(client, "dave@example.org")
    r1 = client.post("/api/auth/refresh", json={"refresh_token": u.refresh})
    assert r1.status_code == 200
    new_refresh = r1.json()["refresh_token"]
    # reusing the rotated token revokes the whole family
    assert client.post("/api/auth/refresh", json={"refresh_token": u.refresh}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": new_refresh}).status_code == 401


def test_logout_revokes_refresh(client):
    u = User(client, "erin@example.org")
    assert client.post("/api/auth/logout", json={"refresh_token": u.refresh}, headers=u.headers).status_code == 204
    assert client.post("/api/auth/refresh", json={"refresh_token": u.refresh}).status_code == 401


def test_nodes_catalog(client, alice):
    r = client.get("/api/nodes", headers=alice.headers)
    types = {n["type"] for n in r.json()["nodes"]}
    assert {"trigger.manual", "scanner.sast", "notify.telegram", "logic.if_else"} <= types
    sch = next(n for n in r.json()["nodes"] if n["type"] == "notify.telegram")["config_schema"]
    assert sch["properties"]["bot_token"]["credential_ref"] is True


def create_wf(client, user, graph, name="audit"):
    r = client.post("/api/workflows", json={"name": name, "graph": graph, "workspace_id": user.workspace_id},
                    headers=user.headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_validate_reports_errors_with_node_ids(client, alice):
    g = full_graph()
    g["nodes"][6]["config"] = {"expression": "severity.max >"}
    wid = create_wf(client, alice, g)
    r = client.post(f"/api/workflows/{wid}/validate", headers=alice.headers)
    issues = r.json()["issues"]
    assert any(i["node_id"] == "if" and i["code"] == "invalid_config" for i in issues)
    r = client.post(f"/api/workflows/{wid}/run", headers=alice.headers)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_graph"


def test_end_to_end_run_findings_exports_and_sse(client, db, alice):
    wid = create_wf(client, alice, full_graph())
    r = client.post(f"/api/workflows/{wid}/run", headers=alice.headers)
    assert r.status_code == 202
    rid = r.json()["id"]
    drain(db)
    run = client.get(f"/api/runs/{rid}", headers=alice.headers).json()
    assert run["status"] == "success" and run["summary"]["total"] == 15
    assert {n["node_id"]: n["status"] for n in run["nodes"]}["exp"] == "success"
    fs = client.get(f"/api/runs/{rid}/findings", headers=alice.headers).json()["findings"]
    assert len(fs) == 15
    assert len(client.get(f"/api/runs/{rid}/findings?category=SCA", headers=alice.headers).json()["findings"]) == 5
    sub = client.get(f"/api/runs/{rid}/export/submission.json", headers=alice.headers)
    assert sub.status_code == 200 and validate_submission(sub.json()) == [] and len(sub.json()["findings"]) == 15
    md = client.get(f"/api/runs/{rid}/export/report.md", headers=alice.headers)
    assert md.status_code == 200 and "Отчёт анализа безопасности" in md.text
    html = client.get(f"/api/runs/{rid}/export/report.html", headers=alice.headers)
    assert html.headers["content-type"].startswith("text/html")
    art = client.get(f"/api/runs/{rid}/artifacts/submission.json", headers=alice.headers)
    assert art.status_code == 200
    with client.stream("GET", f"/api/runs/{rid}/events", headers=alice.headers) as s:
        body = "".join(s.iter_text())
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    ids = [int(line[4:]) for line in body.splitlines() if line.startswith("id: ")]
    assert ids == sorted(ids) and events[0]["type"] == "run.status" and events[-1]["data"]["status"] == "success"
    with client.stream("GET", f"/api/runs/{rid}/events", headers={**alice.headers, "Last-Event-ID": str(ids[-3])}) as s:
        tail = "".join(s.iter_text())
    assert [int(x[4:]) for x in tail.splitlines() if x.startswith("id: ")] == ids[-2:]
    listing = client.get("/api/runs", headers=alice.headers, params={"workflow_id": wid, "status": "success"}).json()
    assert [x["id"] for x in listing["runs"]] == [rid]


def test_compare_runs_shows_fixed_finding(client, db, alice):
    wid = create_wf(client, alice, full_graph())
    base = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
    drain(db)
    g = full_graph()
    g["nodes"][4]["config"] = {"disabled_rules": ["sql-injection"]}
    assert client.put(f"/api/workflows/{wid}", json={"graph": g}, headers=alice.headers).status_code == 200
    head = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
    drain(db)
    cmp_ = client.get("/api/runs/compare", params={"base": base, "head": head}, headers=alice.headers).json()
    assert len(cmp_["fixed"]) == 1 and cmp_["fixed"][0]["class"] == "sql-injection"
    assert cmp_["new"] == [] and len(cmp_["unchanged"]) == 14
    assert cmp_["by_category"]["SAST"]["fixed"] == 1


def test_cross_workspace_access_is_404(client, db, alice, bob):
    wid = create_wf(client, alice, full_graph())
    rid = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
    drain(db)
    for url in (f"/api/workflows/{wid}", f"/api/runs/{rid}", f"/api/runs/{rid}/findings",
                f"/api/runs/{rid}/export/submission.json", f"/api/runs/{rid}/events"):
        assert client.get(url, headers=bob.headers).status_code == 404, url
    assert client.post(f"/api/workflows/{wid}/run", headers=bob.headers).status_code == 404
    assert client.delete(f"/api/workflows/{wid}", headers=bob.headers).status_code == 404
    r = client.post("/api/workflows", json={"name": "x", "graph": full_graph(), "workspace_id": alice.workspace_id},
                    headers=bob.headers)
    assert r.status_code == 404
    assert bob.workspace_id not in [w["id"] for w in client.get("/api/workspaces", headers=alice.headers).json()]


def test_viewer_cannot_modify(client, db, alice, bob):
    r = client.post(f"/api/workspaces/{alice.workspace_id}/members", json={"email": bob.email, "role": "viewer"},
                    headers=alice.headers)
    assert r.status_code == 201
    wid = create_wf(client, alice, full_graph())
    assert client.get(f"/api/workflows/{wid}", headers=bob.headers).status_code == 200
    assert client.put(f"/api/workflows/{wid}", json={"name": "z"}, headers=bob.headers).status_code == 403
    assert client.post(f"/api/workflows/{wid}/run", headers=bob.headers).status_code == 403


def test_credentials_are_write_only_and_encrypted(client, db, alice):
    r = client.post("/api/credentials", json={"workspace_id": alice.workspace_id, "name": "tg", "kind": "telegram",
                                              "value": "123456789:AAsecretTokenValue_abcdefghijklmnop12"},
                    headers=alice.headers)
    assert r.status_code == 201
    body = r.json()
    assert "value" not in body and body["display"] == "••••op12"
    listing = client.get("/api/credentials", headers=alice.headers).text
    assert "AAsecretTokenValue" not in listing
    with db.session() as s:
        row = s.scalars(select(m.Credential)).one()
        assert "AAsecretTokenValue" not in row.ciphertext


def test_upload_project_and_run(client, db, alice):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in TRAINING.rglob("*"):
            if p.is_file():
                z.write(p, "training-project/" + p.relative_to(TRAINING).as_posix())
    r = client.post("/api/uploads", files={"file": ("training.zip", buf.getvalue(), "application/zip")},
                    data={"workspace_id": alice.workspace_id}, headers=alice.headers)
    assert r.status_code == 201, r.text
    up = r.json()["id"]
    with db.session() as s:
        stored = s.get(m.Upload, up).stored_path
    assert b"build.gradle.kts" not in open(stored, "rb").read()  # archive encrypted at rest
    pr = client.post("/api/projects", json={"workspace_id": alice.workspace_id, "name": "training",
                                            "source_mode": "upload", "upload_id": up}, headers=alice.headers)
    assert pr.status_code == 201
    g = full_graph()
    g["nodes"][1]["config"] = {"mode": "project"}
    r = client.post("/api/workflows", json={"name": "u", "graph": g, "workspace_id": alice.workspace_id,
                                            "project_id": pr.json()["id"]}, headers=alice.headers)
    rid = client.post(f"/api/workflows/{r.json()['id']}/run", headers=alice.headers).json()["id"]
    drain(db)
    run = client.get(f"/api/runs/{rid}", headers=alice.headers).json()
    assert run["status"] == "success" and run["summary"]["total"] == 15


def test_cancel_queued_run(client, db, alice):
    wid = create_wf(client, alice, full_graph())
    rid = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
    assert client.post(f"/api/runs/{rid}/cancel", headers=alice.headers).status_code == 202
    assert client.get(f"/api/runs/{rid}", headers=alice.headers).json()["status"] == "cancelled"


def test_schedule_endpoints(client, alice):
    g = full_graph()
    g["nodes"][0] = {"id": "t", "type": "trigger.schedule", "config": {"daily_at": "14:00"}}
    wid = create_wf(client, alice, g)
    r = client.get(f"/api/workflows/{wid}/schedule", headers=alice.headers).json()
    assert r["schedules"][0]["cron"] == "0 14 * * *" and r["schedules"][0]["next_run_at"]
    r = client.put(f"/api/workflows/{wid}/schedule", json={"enabled": False}, headers=alice.headers)
    assert r.json()["schedules"][0]["enabled"] is False


def test_security_headers(client):
    r = client.get("/api/healthz")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"

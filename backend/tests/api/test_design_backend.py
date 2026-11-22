"""Backend features required by the Garden Security design: dashboard period cards, real re-check of a patched
project ("Повторная проверка"), demo data setup ("Демо-данные")."""

from app.config import get_settings
from tests.api.conftest import drain
from tests.engine.test_worker_scheduler import full_graph
from tests.nodes.conftest import TRAINING


def run_training(client, db, user, graph=None):
    pr = client.post("/api/projects", json={"workspace_id": user.workspace_id, "name": "payments-api",
                                            "source_mode": "path", "path": str(TRAINING)}, headers=user.headers).json()
    g = graph or full_graph()
    g["nodes"][1]["config"] = {"mode": "project"}
    wid = client.post("/api/workflows", json={"name": "Проверка перед merge", "graph": g, "project_id": pr["id"]},
                      headers=user.headers).json()["id"]
    rid = client.post(f"/api/workflows/{wid}/run", headers=user.headers).json()["id"]
    drain(db)
    return wid, rid


def test_dashboard_period_cards(client, db, alice):
    wid, rid = run_training(client, db, alice)
    d = client.get("/api/dashboard", params={"period": "7d"}, headers=alice.headers).json()
    assert d["period"] == "7d"
    assert d["checks"] == 1
    assert d["open_findings"] == 15
    assert d["blocking_findings"] == 1  # one CRITICAL, no diff verdict → gate threshold CRITICAL
    assert d["validated_patches"] == 0
    assert d["findings_by_category"] == {"SCA": 5, "SAST": 5, "SECRET": 5}
    # severity levels describe the same run as the cards, even without a Security Score node
    assert sum(d["findings_by_severity"].values()) == 15 and d["findings_by_severity"]["CRITICAL"] >= 1
    assert d["recent_runs"][0]["id"] == rid and d["recent_runs"][0]["status"] == "success"
    assert set(d["recent_runs"][0]) >= {"workflow_name", "created_at", "score", "gate", "verdict", "commit"}
    assert client.get("/api/dashboard", params={"period": "30d"}, headers=alice.headers).json()["period"] == "30d"
    assert client.get("/api/dashboard", params={"period": "1y"}, headers=alice.headers).status_code == 422


def test_recheck_runs_the_workflow_on_patched_code(client, db, alice):
    wid, rid = run_training(client, db, alice)
    findings = client.get(f"/api/runs/{rid}/findings", headers=alice.headers).json()["findings"]
    sca = next(f for f in findings if f["category"] == "SCA" and f["autofix"] == "deterministic")
    af = client.post(f"/api/runs/{rid}/findings/{sca['id']}/autofix", headers=alice.headers)
    assert af.status_code == 201, af.text
    af = af.json()
    assert af["status"] == "validated", af
    r = client.post(f"/api/autofixes/{af['id']}/recheck", headers=alice.headers)
    assert r.status_code == 202, r.text
    new_rid = r.json()["run_id"]
    drain(db)
    new = client.get(f"/api/runs/{new_rid}", headers=alice.headers).json()
    assert new["status"] == "success", new["error"]
    assert new["trigger_payload"]["recheck_of"] == rid and new["trigger_payload"]["autofix_id"] == af["id"]
    ids = {f["id"] for f in client.get(f"/api/runs/{new_rid}/findings", headers=alice.headers).json()["findings"]}
    assert sca["id"] not in ids and len(ids) == 14
    cmp_ = client.get("/api/runs/compare", params={"base": rid, "head": new_rid}, headers=alice.headers).json()
    assert [f["id"] for f in cmp_["fixed"]] == [sca["id"]] and cmp_["new"] == []
    d = client.get("/api/dashboard", params={"period": "7d"}, headers=alice.headers).json()
    assert d["validated_patches"] == 1 and d["checks"] == 2


def test_recheck_rejected_for_unvalidated_or_foreign(client, db, alice, bob):
    wid, rid = run_training(client, db, alice)
    findings = client.get(f"/api/runs/{rid}/findings", headers=alice.headers).json()["findings"]
    sca = next(f for f in findings if f["category"] == "SCA" and f["autofix"] == "deterministic")
    af = client.post(f"/api/runs/{rid}/findings/{sca['id']}/autofix", headers=alice.headers).json()
    assert client.post(f"/api/autofixes/{af['id']}/recheck", headers=bob.headers).status_code == 404


def test_demo_setup_creates_real_project_and_runnable_workflow(client, db, alice, monkeypatch):
    monkeypatch.setattr(get_settings(), "scan_roots", str(TRAINING.parent.parent))
    r = client.post("/api/demo/setup", json={"workspace_id": alice.workspace_id}, headers=alice.headers)
    assert r.status_code == 201, r.text
    body = r.json()
    again = client.post("/api/demo/setup", json={"workspace_id": alice.workspace_id}, headers=alice.headers).json()
    assert again["workflow_id"] == body["workflow_id"] and again["project_id"] == body["project_id"]
    assert client.post(f"/api/workflows/{body['workflow_id']}/validate", headers=alice.headers).json()["valid"] is True
    rid = client.post(f"/api/workflows/{body['workflow_id']}/run", headers=alice.headers).json()["id"]
    drain(db)
    run = client.get(f"/api/runs/{rid}", headers=alice.headers).json()
    assert run["status"] == "success", run["error"]
    assert run["summary"]["total"] == 15


def test_demo_training_source_is_a_scannable_path(client, db, alice):
    r = client.get("/api/demo/training", headers=alice.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True and body["path"].endswith("training-project")
    # the editor puts this path into source.repo (mode=path): the workflow validates and runs on it
    g = {"schema_version": 1, "nodes": [
        {"id": "t", "type": "trigger.manual", "position": {"x": 0, "y": 0}, "config": {}},
        {"id": "src", "type": "source.repo", "position": {"x": 0, "y": 0}, "config": {"mode": "path", "path": body["path"]}},
        {"id": "sec", "type": "scanner.secrets", "position": {"x": 0, "y": 0}, "config": {}}],
        "edges": [{"id": "e0", "source": "t", "source_port": "out", "target": "src", "target_port": "in"},
                  {"id": "e1", "source": "src", "source_port": "out", "target": "sec", "target_port": "in"}]}
    v = client.post("/api/workflows/validate", json={"workspace_id": alice.workspace_id, "graph": g}, headers=alice.headers)
    assert v.json()["valid"] is True, v.json()
    assert client.get("/api/demo/training").status_code == 401


def test_combined_recheck_exports_the_scanned_project(client, db, alice, bob):
    import io
    import zipfile
    from datetime import UTC, datetime, timedelta

    from app import models as m
    from tests.api.test_autofix_api import PWD_FILE, SECRET

    _, rid = run_training(client, db, alice)
    base = f"/api/runs/{rid}"
    findings = client.get(base + "/findings", headers=alice.headers).json()["findings"]
    targets = [f for f in findings if f["autofix"] == "deterministic"]
    patches = [client.post(f"{base}/findings/{f['id']}/autofix", headers=alice.headers).json() for f in targets]
    ids = [p["id"] for p in patches if p["status"] == "validated"]
    assert len(ids) >= 2
    assert client.post(base + "/autofixes/recheck", json={"autofix_ids": ids}, headers=bob.headers).status_code == 404
    mixed = client.post(base + "/autofixes/recheck", json={"autofix_ids": [ids[0], "missing"]}, headers=alice.headers)
    assert mixed.status_code == 404
    res = client.post(base + "/autofixes/recheck", json={"autofix_ids": ids}, headers=alice.headers)
    assert res.status_code == 202, res.text
    new = "/api/runs/" + res.json()["run_id"]
    archive = client.get(new + "/fixed-project.zip", headers=alice.headers)
    assert archive.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
        assert "build.gradle.kts" in z.namelist()
        assert any(p.endswith(".kt") for p in z.namelist())
        assert b"commons-text:1.10.0" in z.read("build.gradle.kts")
        assert SECRET.encode() not in z.read(PWD_FILE)
    assert client.get(new + "/fixed-project.zip", headers=bob.headers).status_code == 404
    assert client.get(base + "/fixed-project.zip", headers=alice.headers).status_code == 404
    drain(db)
    remaining = client.get(new + "/findings", headers=alice.headers).json()["findings"]
    assert {p["finding_id"] for p in patches if p["status"] == "validated"}.isdisjoint(f["id"] for f in remaining)
    assert client.get(new, headers=alice.headers).json()["has_fixed_project"]
    assert len(client.get(base + "/findings", headers=alice.headers).json()["findings"]) == len(findings)
    with db.session() as s:
        upload_id = s.get(m.Run, res.json()["run_id"]).fixed_upload_id
        s.get(m.Upload, upload_id).expires_at = datetime.now(UTC) - timedelta(hours=1)
        s.commit()
    assert client.get(new + "/fixed-project.zip", headers=alice.headers).status_code == 410

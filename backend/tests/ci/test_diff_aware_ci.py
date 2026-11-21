"""Diff-aware end-to-end: PR webhook → FAIL + commit status «N new critical» + one PR comment (upserted on push) on a
real mock GitHub; CI verdict endpoint 200/422; CLI exit codes follow the diff verdict."""

import json
import os
import subprocess
import sys

from app.config import get_settings
from tests.api.conftest import drain
from tests.ci.test_ci import CLI, gh_sig, mk_token
from tests.engine.test_worker_scheduler import full_graph
from tests.nodes.test_diff_node import git_project, sh  # noqa: F401 - fixture reuse


def diff_graph(trigger: dict, src: dict):
    g = full_graph()
    g["nodes"][0] = {"id": "t", "type": "trigger.webhook", "position": {"x": 0, "y": 0}, "config": trigger}
    g["nodes"][1]["config"] = src
    g["nodes"].append({"id": "diff", "type": "scanner.diff", "position": {"x": 0, "y": 0}, "config": {}})
    g["edges"] += [{"id": "ed1", "source": "src", "source_port": "out", "target": "diff", "target_port": "repo"},
                   {"id": "ed2", "source": "merge", "source_port": "out", "target": "diff", "target_port": "findings"},
                   {"id": "ed3", "source": "diff", "source_port": "verdict", "target": "gate", "target_port": "verdict"}]
    return g


def pr_event(head: str, base: str, action: str):
    return {"action": action, "number": 12, "repository": {"full_name": "alice/shop",
                                                          "html_url": "https://github.com/alice/shop"},
            "pull_request": {"head": {"sha": head, "ref": "feature"}, "base": {"sha": base, "ref": "main"}}}


def test_pr_webhook_fail_comment_then_pass_updates_same_comment(client, db, alice, scm, git_project, monkeypatch):  # noqa: F811
    repo, root, target = git_project
    monkeypatch.setattr(get_settings(), "scan_roots", str(repo))
    scm_url, state = scm
    sec = client.post("/api/credentials", json={"workspace_id": alice.workspace_id, "name": "wh",
                                                "kind": "webhook_secret", "value": "whs-1"}, headers=alice.headers).json()["id"]
    tok = client.post("/api/credentials", json={"workspace_id": alice.workspace_id, "name": "gh",
                                                "kind": "repo_write_token", "value": "ghp_" + "q" * 36},
                      headers=alice.headers).json()["id"]
    client.put("/api/settings/allowlist", json={"workspace_id": alice.workspace_id, "entries": [
        {"url": "https://github.com/alice/shop", "allow_write": True, "provider": "github", "api_base": scm_url,
         "write_credential_id": tok}]}, headers=alice.headers)
    g = diff_graph({"provider": "github", "secret": sec, "repo_url": "https://github.com/alice/shop",
                    "events": ["pull_request"]}, {"mode": "path", "path": str(root)})
    assert client.post("/api/workflows", json={"name": "diff", "graph": g}, headers=alice.headers).status_code == 201

    def deliver(event, delivery):
        body = json.dumps(event).encode()
        r = client.post("/api/v1/webhooks/github", content=body, headers={
            "X-GitHub-Event": "pull_request", "X-GitHub-Delivery": delivery, "Content-Type": "application/json",
            "X-Hub-Signature-256": gh_sig("whs-1", body)})
        assert r.status_code == 202, r.text
        drain(db)
        return r.json()["run_ids"][0]

    base = sh(repo, "rev-parse", "main")
    rid = deliver(pr_event(sh(repo, "rev-parse", "HEAD"), base, "opened"), "p-1")
    run = client.get(f"/api/runs/{rid}", headers=alice.headers).json()
    assert run["status"] == "success", run.get("error")
    assert run["verdict"]["verdict"] == "FAIL" and run["verdict"]["existing_count"] == 15
    statuses = [q for q in state.requests if "/statuses/" in q["path"]]
    assert statuses[-1]["body"]["state"] == "failure" and "new critical" in statuses[-1]["body"]["description"]
    comments = state.comments["gh:alice/shop#12"]
    assert len(comments) == 1 and "<!-- aisw-report -->" in comments[0]["body"]
    assert "FAIL" in comments[0]["body"] and target.name in comments[0]["body"]
    assert "15 существующих" in comments[0]["body"]
    assert "AKIA" not in comments[0]["body"]  # secret values never leave masked
    findings = client.get(f"/api/runs/{rid}/findings", headers=alice.headers).json()
    items = findings if isinstance(findings, list) else findings["findings"]
    assert sum(1 for f in items if f.get("diff_status") == "new") >= 1

    sh(repo, "revert", "--no-edit", "HEAD")
    rid2 = deliver(pr_event(sh(repo, "rev-parse", "HEAD"), base, "synchronize"), "p-2")
    run2 = client.get(f"/api/runs/{rid2}", headers=alice.headers).json()
    assert run2["verdict"]["verdict"] == "PASS"
    statuses = [q for q in state.requests if "/statuses/" in q["path"]]
    assert statuses[-1]["body"]["state"] == "success"
    comments = state.comments["gh:alice/shop#12"]
    assert len(comments) == 1 and "PASS" in comments[0]["body"]  # same comment updated, no spam
    assert any(q["method"] == "PATCH" for q in state.requests)


def test_ci_verdict_endpoint_and_cli_exit_codes(client, alice, live_server, git_project):  # noqa: F811
    repo, root, _ = git_project
    g = diff_graph({"provider": "ci"}, {"mode": "project"})
    wid = client.post("/api/workflows", json={"name": "ci-diff", "graph": g}, headers=alice.headers).json()["id"]
    token = mk_token(client, alice)["token"]

    def cli():
        return subprocess.run([sys.executable, str(CLI), "--url", live_server, "--workflow", wid, "--out",
                               str(repo.parent / "out"), "--base", "main", "--no-comment"], cwd=root,
                              env={**os.environ, "AISW_TOKEN": token},  # Windows needs SYSTEMROOT etc. for SSL init
                              capture_output=True, text=True, timeout=300)

    p = cli()
    assert p.returncode == 1, p.stdout + p.stderr
    assert "Diff verdict:** FAIL" in p.stdout and "Новые находки в этом diff:** " in p.stdout
    rid = next(line.split()[2] for line in p.stdout.splitlines() if line.startswith("aisw: запуск"))
    h = {"Authorization": f"Bearer {token}"}
    v = client.get(f"/api/v1/ci/runs/{rid}/verdict", headers=h)
    assert v.status_code == 422 and v.json()["verdict"] == "FAIL" and v.json()["new_findings"]
    assert all("AKIA" not in (f["snippet"] or "") for f in v.json()["new_findings"])
    head_sha = sh(repo, "rev-parse", "HEAD")
    assert all(f["introduced_in_commit"] == head_sha for f in v.json()["new_findings"])  # blame uploaded by the CLI
    assert {f["category"] for f in v.json()["new_findings"]} == {"SECRET"}  # SCA unchanged vs base build files
    assert client.get(f"/api/v1/ci/runs/{rid}", headers=h).json()["verdict"]["verdict"] == "FAIL"
    sh(repo, "revert", "--no-edit", "HEAD")
    p2 = cli()
    assert p2.returncode == 0, p2.stdout + p2.stderr
    rid2 = next(line.split()[2] for line in p2.stdout.splitlines() if line.startswith("aisw: запуск"))
    ok = client.get(f"/api/v1/ci/runs/{rid2}/verdict", headers=h)
    assert ok.status_code == 200 and ok.json()["existing_count"] == 15 and ok.json()["new_findings"] == []


def test_platform_comment_upsert_on_gitlab(db, scm):
    import asyncio

    from app import models as m
    from app.ci.status import COMMENT_MARKER, ScmTarget, upsert_comment

    scm_url, state = scm
    with db.session() as s:
        ws = m.Workspace(name="W", timezone="UTC")
        s.add(ws)
        s.flush()
        run = m.Run(workspace_id=ws.id, status="success")
        s.add(run)
        s.commit()
        rid = run.id
    t = ScmTarget("gitlab", scm_url, "glpat-" + "k" * 20, "alice/shop", "https://gitlab.com/alice/shop")
    assert asyncio.run(upsert_comment(db, rid, t, 4, f"{COMMENT_MARKER}\nv1")) == 201
    assert asyncio.run(upsert_comment(db, rid, t, 4, f"{COMMENT_MARKER}\nv2")) == 200
    notes = state.comments["gl:alice/shop!4"]
    assert len(notes) == 1 and notes[0]["body"].endswith("v2")
    assert [q["method"] for q in state.requests if "/notes" in q["path"]] == ["GET", "POST", "GET", "PUT"]
    with db.session() as s:
        assert [r.state for r in s.query(m.CiStatusReport).order_by(m.CiStatusReport.created_at)] == ["created", "updated"]

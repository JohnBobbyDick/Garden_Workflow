import hashlib
import hmac
import io
import json
import shutil
import subprocess
import sys
import zipfile

import yaml

from app.config import REPO_ROOT
from tests.api.conftest import drain
from tests.engine.test_worker_scheduler import full_graph
from tests.nodes.conftest import TRAINING

CLI = REPO_ROOT / "cli" / "aisw_ci.py"


def ci_graph(fail_on="CRITICAL", provider="ci", extra=None):
    g = full_graph()
    g["nodes"][0] = {"id": "t", "type": "trigger.webhook", "config": {"provider": provider, **(extra or {})}}
    g["nodes"][1]["config"] = {"mode": "project"}
    next(n for n in g["nodes"] if n["id"] == "gate")["config"] = {"fail_on": fail_on}
    return g


def mk_token(client, user, workflow_id=None):
    r = client.post("/api/api-tokens", json={"workspace_id": user.workspace_id, "name": "ci",
                                             "workflow_id": workflow_id}, headers=user.headers)
    assert r.status_code == 201, r.text
    return r.json()


def zip_training() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in TRAINING.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(TRAINING).as_posix())
    return buf.getvalue()


def test_api_token_shown_once_hashed_and_revocable(client, db, alice):
    wid = client.post("/api/workflows", json={"name": "ci", "graph": ci_graph(), "workspace_id": alice.workspace_id},
                      headers=alice.headers).json()["id"]
    tok = mk_token(client, alice, wid)
    assert tok["token"].startswith("aisw_")
    listing = client.get("/api/api-tokens", headers=alice.headers).json()
    assert tok["token"] not in json.dumps(listing) and listing[0]["prefix"] == tok["token"][:10]
    h = {"Authorization": f"Bearer {tok['token']}"}
    assert client.post("/api/v1/ci/runs", files={"archive": ("p.zip", zip_training())},
                       data={"workflow_id": wid}, headers=h).status_code == 202
    assert client.delete(f"/api/api-tokens/{tok['id']}", headers=alice.headers).status_code == 204
    assert client.post("/api/v1/ci/runs", files={"archive": ("p.zip", zip_training())},
                       data={"workflow_id": wid}, headers=h).status_code == 401
    actions = [a["action"] for a in client.get(f"/api/workspaces/{alice.workspace_id}/audit", headers=alice.headers).json()]
    assert "api_token.create" in actions and "api_token.revoke" in actions


def test_token_restricted_to_workflow(client, alice):
    w1 = client.post("/api/workflows", json={"name": "a", "graph": ci_graph()}, headers=alice.headers).json()["id"]
    w2 = client.post("/api/workflows", json={"name": "b", "graph": ci_graph()}, headers=alice.headers).json()["id"]
    tok = mk_token(client, alice, w1)["token"]
    r = client.post("/api/v1/ci/runs", files={"archive": ("p.zip", zip_training())}, data={"workflow_id": w2},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403


def test_ci_run_status_gate_and_reports(client, db, alice, bob):
    wid = client.post("/api/workflows", json={"name": "ci", "graph": ci_graph()}, headers=alice.headers).json()["id"]
    h = {"Authorization": f"Bearer {mk_token(client, alice)['token']}"}
    r = client.post("/api/v1/ci/runs", files={"archive": ("p.zip", zip_training())},
                    data={"workflow_id": wid, "provider": "github", "repo": "me/app", "ref": "main",
                          "commit_sha": "a" * 40}, headers=h)
    rid = r.json()["id"]
    assert r.json()["links"]["status"].endswith(f"/api/v1/ci/runs/{rid}")
    drain(db)
    st = client.get(f"/api/v1/ci/runs/{rid}", headers=h).json()
    assert st["status"] == "success" and st["gate"] == "fail" and st["summary"]["by_severity"]["CRITICAL"] == 1
    assert st["links"]["report"] and st["links"]["ui"].endswith(f"/runs/{rid}")
    sub = client.get(f"/api/v1/ci/runs/{rid}/report", params={"format": "submission"}, headers=h).json()
    assert len(sub["findings"]) == 15
    md = client.get(f"/api/v1/ci/runs/{rid}/report", params={"format": "markdown"}, headers=h)
    assert "Отчёт анализа безопасности" in md.text
    assert client.get(f"/api/v1/ci/runs/{rid}", headers=bob.headers).status_code == 401


def test_yaml_generator_github_and_gitlab(client, alice):
    wid = client.post("/api/workflows", json={"name": "ci", "graph": ci_graph()}, headers=alice.headers).json()["id"]
    gh = yaml.safe_load(client.get("/api/ci/yaml", params={"provider": "github", "workflow_id": wid},
                                   headers=alice.headers).text)
    on = gh.get("on") or gh.get(True)
    assert "push" in on and "pull_request" in on
    steps = gh["jobs"]["aisw"]["steps"]
    checkout = next(s for s in steps if "actions/checkout" in s.get("uses", ""))
    assert checkout["with"]["fetch-depth"] == 0
    run_step = next(s for s in steps if "--workflow" in s.get("run", ""))
    assert "secrets.AISW_TOKEN" in json.dumps(run_step["env"]) and wid in run_step["run"]
    assert "GITHUB_STEP_SUMMARY" in json.dumps(steps)
    assert any("upload-artifact" in s.get("uses", "") for s in steps)
    gl = yaml.safe_load(client.get("/api/ci/yaml", params={"provider": "gitlab", "workflow_id": wid},
                                   headers=alice.headers).text)
    job = gl["aisw_security"]
    assert job["stage"] == "security" and job["allow_failure"] is False and job["variables"]["GIT_DEPTH"] == 0
    assert any("merge_request_event" in json.dumps(r) for r in job["rules"])
    assert "submission.json" in json.dumps(job["artifacts"])


def gh_sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def setup_webhook(client, alice, scm_url, write=True):
    sec = client.post("/api/credentials", json={"workspace_id": alice.workspace_id, "name": "whsec",
                                                "kind": "webhook_secret", "value": "gh-webhook-secret-42"},
                      headers=alice.headers).json()["id"]
    tok = client.post("/api/credentials", json={"workspace_id": alice.workspace_id, "name": "ghtok",
                                                "kind": "repo_write_token", "value": "ghp_" + "w" * 36},
                      headers=alice.headers).json()["id"]
    client.put("/api/settings/allowlist", json={"workspace_id": alice.workspace_id, "entries": [
        {"url": "https://github.com/alice/shop", "allow_write": write, "provider": "github", "api_base": scm_url,
         "write_credential_id": tok}]}, headers=alice.headers)
    g = ci_graph(provider="github", extra={"secret": sec, "repo_url": "https://github.com/alice/shop",
                                           "events": ["push", "pull_request"]})
    g["nodes"][1]["config"] = {"mode": "path", "path": str(TRAINING)}  # code from fixtures (no real clone in tests)
    return client.post("/api/workflows", json={"name": "wh", "graph": g}, headers=alice.headers).json()["id"]


def pr_payload(action="opened"):
    return {"action": action, "number": 7, "repository": {"full_name": "alice/shop", "html_url": "https://github.com/alice/shop",
                                                          "clone_url": "https://github.com/alice/shop.git"},
            "pull_request": {"head": {"sha": "b" * 40, "ref": "feature"}, "base": {"sha": "c" * 40, "ref": "main"}}}


def test_github_webhook_signature_idempotency_and_status(client, db, alice, scm):
    scm_url, state = scm
    setup_webhook(client, alice, scm_url)
    body = json.dumps(pr_payload()).encode()
    bad = client.post("/api/v1/webhooks/github", content=body, headers={
        "X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "d-1", "X-Hub-Signature-256": gh_sig("wrong", body),
        "Content-Type": "application/json"})
    assert bad.status_code == 401
    hdr = {"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "d-2",
           "X-Hub-Signature-256": gh_sig("gh-webhook-secret-42", body), "Content-Type": "application/json"}
    r = client.post("/api/v1/webhooks/github", content=body, headers=hdr)
    assert r.status_code == 202 and len(r.json()["run_ids"]) == 1
    dup = client.post("/api/v1/webhooks/github", content=body, headers=hdr)
    assert dup.json()["duplicate"] is True and dup.json()["run_ids"] == r.json()["run_ids"]
    drain(db)
    statuses = [q for q in state.requests if "/statuses/" in q["path"]]
    assert [q["body"]["state"] for q in statuses] == ["pending", "failure"]
    assert statuses[0]["path"] == f"/repos/alice/shop/statuses/{'b' * 40}"
    assert statuses[0]["headers"]["Authorization"] == "Bearer ghp_" + "w" * 36
    assert statuses[1]["body"]["target_url"].endswith(f"/runs/{r.json()['run_ids'][0]}")
    ignored = client.post("/api/v1/webhooks/github", content=json.dumps(pr_payload("closed")).encode(), headers={
        **hdr, "X-GitHub-Delivery": "d-3", "X-Hub-Signature-256": gh_sig("gh-webhook-secret-42",
                                                                         json.dumps(pr_payload("closed")).encode())})
    assert ignored.json()["run_ids"] == []


def test_webhook_status_endpoint_lists_deliveries_and_ci_statuses(client, db, alice, bob, scm):
    scm_url, _ = scm
    setup_webhook(client, alice, scm_url)
    body = json.dumps(pr_payload()).encode()
    r = client.post("/api/v1/webhooks/github", content=body, headers={
        "X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "deliv-77", "Content-Type": "application/json",
        "X-Hub-Signature-256": gh_sig("gh-webhook-secret-42", body)})
    run_id = r.json()["run_ids"][0]
    drain(db)
    st = client.get(f"/api/ci/webhooks/status?workspace_id={alice.workspace_id}", headers=alice.headers)
    assert st.status_code == 200, st.text
    data = st.json()
    assert data["deliveries"][0]["provider"] == "github"
    assert data["deliveries"][0]["event"] == "pull_request" and data["deliveries"][0]["run_ids"] == [run_id]
    states = [x["state"] for x in data["statuses"] if x["run_id"] == run_id and x["kind"] == "status"]
    assert sorted(states) == ["failure", "pending"]
    assert all(x["response_code"] in (200, 201) for x in data["statuses"])
    foreign = client.get(f"/api/ci/webhooks/status?workspace_id={alice.workspace_id}", headers=bob.headers)
    assert foreign.status_code == 404
    assert client.get(f"/api/ci/webhooks/status?workspace_id={bob.workspace_id}",
                      headers=bob.headers).json() == {"deliveries": [], "statuses": []}


def test_status_not_written_without_allow_write(client, db, alice, scm):
    scm_url, state = scm
    setup_webhook(client, alice, scm_url, write=False)
    body = json.dumps(pr_payload()).encode()
    client.post("/api/v1/webhooks/github", content=body, headers={
        "X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "x", "Content-Type": "application/json",
        "X-Hub-Signature-256": gh_sig("gh-webhook-secret-42", body)})
    drain(db)
    assert not [q for q in state.requests if "/statuses/" in q["path"]]


def test_gitlab_webhook_token_and_mr(client, db, alice, scm):
    scm_url, state = scm
    sec = client.post("/api/credentials", json={"workspace_id": alice.workspace_id, "name": "gl", "value": "gl-secret-77"},
                      headers=alice.headers).json()["id"]
    tok = client.post("/api/credentials", json={"workspace_id": alice.workspace_id, "name": "gltok",
                                                "value": "glpat-" + "x" * 20}, headers=alice.headers).json()["id"]
    client.put("/api/settings/allowlist", json={"workspace_id": alice.workspace_id, "entries": [
        {"url": "https://gitlab.com/alice/shop", "allow_write": True, "provider": "gitlab", "api_base": scm_url,
         "write_credential_id": tok}]}, headers=alice.headers)
    g = ci_graph(provider="gitlab", extra={"secret": sec, "repo_url": "https://gitlab.com/alice/shop",
                                           "events": ["merge_request"]})
    g["nodes"][1]["config"] = {"mode": "path", "path": str(TRAINING)}
    client.post("/api/workflows", json={"name": "gl", "graph": g}, headers=alice.headers)
    payload = {"object_kind": "merge_request", "project": {"id": 42, "web_url": "https://gitlab.com/alice/shop",
                                                           "path_with_namespace": "alice/shop"},
               "object_attributes": {"iid": 3, "action": "open", "source_branch": "f", "target_branch": "main",
                                     "last_commit": {"id": "d" * 40}},
               "diff_refs": {"base_sha": "e" * 40, "head_sha": "d" * 40}}
    body = json.dumps(payload).encode()
    assert client.post("/api/v1/webhooks/gitlab", content=body, headers={
        "X-Gitlab-Event": "Merge Request Hook", "X-Gitlab-Token": "nope", "Content-Type": "application/json"}
    ).status_code == 401
    r = client.post("/api/v1/webhooks/gitlab", content=body, headers={
        "X-Gitlab-Event": "Merge Request Hook", "X-Gitlab-Token": "gl-secret-77", "X-Gitlab-Event-UUID": "u1",
        "Content-Type": "application/json"})
    assert r.status_code == 202 and len(r.json()["run_ids"]) == 1
    drain(db)
    statuses = [q for q in state.requests if "/statuses/" in q["path"]]
    assert statuses[0]["path"] == f"/projects/alice/shop/statuses/{'d' * 40}"
    assert {k.lower(): v for k, v in statuses[0]["headers"].items()}["private-token"] == "glpat-" + "x" * 20
    assert [q["query"]["state"][0] for q in statuses] == ["pending", "failed"]


def test_webhook_body_limit(client):
    r = client.post("/api/v1/webhooks/github", content=b"x" * (2 * 1024 * 1024 + 10),
                    headers={"X-GitHub-Event": "push", "Content-Type": "application/json"})
    assert r.status_code == 413


def run_cli(cwd, url, token, workflow_id, *extra):
    return subprocess.run([sys.executable, str(CLI), "--url", url, "--workflow", workflow_id, "--out", str(cwd / "out"),
                           *extra], cwd=cwd, env={"AISW_TOKEN": token, "PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")},
                          capture_output=True, text=True, timeout=180)


def test_cli_end_to_end_exit_codes(client, alice, live_server, tmp_path):
    work = tmp_path / "repo"
    shutil.copytree(TRAINING, work)
    fail_wf = client.post("/api/workflows", json={"name": "ci", "graph": ci_graph("CRITICAL")}, headers=alice.headers).json()["id"]
    pass_wf = client.post("/api/workflows", json={"name": "ci2", "graph": ci_graph("none")}, headers=alice.headers).json()["id"]
    token = mk_token(client, alice)["token"]
    p = run_cli(work, live_server, token, fail_wf)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "gate: FAIL" in p.stdout and "CRITICAL" in p.stdout
    assert (work / "out" / "report.md").exists() and json.loads((work / "out" / "submission.json").read_text(
        encoding="utf-8"))["findings"]
    assert run_cli(work, live_server, token, pass_wf).returncode == 0
    assert run_cli(work, "http://127.0.0.1:9", token, pass_wf).returncode == 2
    assert run_cli(work, live_server, "aisw_wrong", pass_wf).returncode == 2

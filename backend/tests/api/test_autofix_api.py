"""AI AutoFix end-to-end on the API: mock LLM scenarios from 12A.3 (validated / every reject reason), deterministic
SCA bump without LLM, .patch download, PR/MR on local mock GitHub/GitLab (sequence, idempotency, masks), 403 rules."""

import pytest
from sqlalchemy import select

from app import models as m
from tests.api.test_ai_api import configure
from tests.api.test_score_api import llm, project_dir, run, setup_project  # noqa: F401 - fixture reuse
from tests.ci.conftest import scm  # noqa: F401 - fixture reuse

PWD_FILE = "src/main/kotlin/lab/repairdesk/integration/PartsImportSettings.kt"
SQL_FILE = "src/main/kotlin/lab/repairdesk/repair/RepairLookupController.kt"
SECRET = "cg26_parts_H9r4Vm2Kb6Qp"
MASKED_LINE = '    private val legacyImportPassword = "cg…(len=23)"'
ENV_FIX = '    private val legacyImportPassword: String = System.getenv("PARTS_IMPORT_PASSWORD") ?: error("PARTS_IMPORT_PASSWORD is not set")'


def fix(file, start, end, old, new, **kw):
    return {"file": file, "start_line": start, "end_line": end, "old_snippet": old, "new_snippet": new,
            "explanation": kw.get("explanation", "вынесено в переменную окружения"),
            "requires_config": kw.get("requires_config", [])}


@pytest.fixture
def ready(client, db, alice, project_dir, llm):  # noqa: F811
    script, hp = llm
    configure(client, alice, hp)
    _, wid = setup_project(client, alice, project_dir)
    r = run(client, db, alice, wid)
    fs = client.get(f"/api/runs/{r['id']}/findings", headers=alice.headers).json()["findings"]
    pwd = next(f for f in fs if f["category"] == "SECRET" and f["path"] == PWD_FILE)
    sql = next(f for f in fs if f["class"] == "sql-injection")
    sca = next(f for f in fs if f.get("artifact") == "commons-text")
    return script, r, pwd, sql, sca


def autofix(client, user, run_id, fid):
    return client.post(f"/api/runs/{run_id}/findings/{fid}/autofix", json={}, headers=user.headers)


def test_masked_context_and_validated_secret_fix(client, alice, ready):
    script, r, pwd, _, _ = ready
    script.reply(fix(PWD_FILE, 4, 4, MASKED_LINE, ENV_FIX,
                     requires_config=[{"name": "PARTS_IMPORT_PASSWORD", "description": "пароль импорта запчастей"}]))
    res = autofix(client, alice, r["id"], pwd["id"])
    assert res.status_code == 201, res.text
    a = res.json()
    assert a["status"] == "validated", a["steps"]
    assert [s["name"] for s in a["steps"]] == ["schema", "location", "old_snippet", "new_snippet", "apply", "syntax",
                                               "self_check"]
    assert all(s["ok"] for s in a["steps"]) and a["proposal"]["self_check"]["new_findings"] == []
    assert a["proposal"]["requires_config"][0]["name"] == "PARTS_IMPORT_PASSWORD"
    assert "System.getenv" in a["patch"] and SECRET not in a["patch"] and "+++ b/" + PWD_FILE in a["patch"]
    sent = script.requests[0]["body"]["messages"][-1]["content"]
    assert SECRET not in sent and "cg…(len=23)" in sent and "headersForLocalImport" in sent  # enclosing class
    assert SECRET not in str(a)
    assert a["can_create_pr"] is False and ".patch" in a["pr_unavailable_reason"]  # path-mode project
    p = client.get(f"/api/autofixes/{a['id']}/patch", headers=alice.headers)
    assert p.status_code == 200 and p.headers["content-type"].startswith("text/x-diff") and SECRET not in p.text


@pytest.mark.parametrize("case", ["no_old_snippet", "keeps_finding", "adds_finding", "breaks_syntax",
                                  "secret_in_new"])
def test_rejected_fixes(client, alice, ready, case):
    script, r, pwd, sql, _ = ready
    target, reply, step = {
        "no_old_snippet": (pwd, fix(PWD_FILE, 4, 4, '    private val password = "nope"', ENV_FIX), "old_snippet"),
        "keeps_finding": (sql, fix(SQL_FILE, 14, 14,
                                   '        jdbc.queryForList("SELECT ticket_code FROM repair_ticket WHERE frame_tag = '
                                   "'$frameTag'\", String::class.java)",
                                   '        jdbc.queryForList("SELECT ticket_code FROM repair_ticket WHERE frame_tag = '
                                   "'\" + frameTag + \"'\", String::class.java)"), "self_check"),
        "adds_finding": (pwd, fix(PWD_FILE, 4, 4, MASKED_LINE,
                                  ENV_FIX + '\n    private val partnerApiKey = "pk9Xv2Lm8Qw3Rt6Yz1Bn4Hc7Df0Gs5"'),
                         "self_check"),
        "breaks_syntax": (pwd, fix(PWD_FILE, 4, 4, MASKED_LINE,
                                   '    private val legacyImportPassword = System.getenv("X" ?: ('), "syntax"),
        "secret_in_new": (pwd, fix(PWD_FILE, 4, 4, MASKED_LINE,
                                   f'    private val legacyImportPassword = System.getenv("P") ?: "{SECRET}"'),
                          "new_snippet"),
    }[case]
    script.reply(reply).reply(reply)  # the repair attempt gets the same wrong answer
    a = autofix(client, alice, r["id"], target["id"]).json()
    assert a["status"] == "rejected" and a["reason"].startswith(step), a
    assert a["steps"][-1]["name"] == step and not a["steps"][-1]["ok"]
    assert len(script.requests) == 2 and "не прошёл проверку" in script.requests[1]["body"]["messages"][-1]["content"]
    assert a["patch"] is None and SECRET not in str(a)
    assert client.post(f"/api/autofixes/{a['id']}/pull-request", json={}, headers=alice.headers).status_code == 409


def test_repair_attempt_can_succeed(client, alice, ready):
    script, r, pwd, _, _ = ready
    script.reply(fix(PWD_FILE, 4, 4, "nope", ENV_FIX)).reply(fix(PWD_FILE, 4, 4, MASKED_LINE, ENV_FIX))
    a = autofix(client, alice, r["id"], pwd["id"]).json()
    assert a["status"] == "validated" and a["proposal"]["attempts"] == 2


def test_sca_bump_without_llm_and_not_applicable_rules(client, db, alice, project_dir):  # noqa: F811
    _, wid = setup_project(client, alice, project_dir)
    r = run(client, db, alice, wid)
    fs = client.get(f"/api/runs/{r['id']}/findings", headers=alice.headers).json()["findings"]
    sca = next(f for f in fs if f.get("artifact") == "commons-text")
    a = autofix(client, alice, r["id"], sca["id"]).json()
    assert a["kind"] == "deterministic" and a["status"] == "validated", a["steps"]
    assert "commons-text:1.10.0" in a["patch"] and "--write-locks" in a["proposal"]["explanation"]
    pwd = next(f for f in fs if f["category"] == "SECRET")
    assert autofix(client, alice, r["id"], pwd["id"]).json()["error"]["code"] == "ai_not_configured"
    cov = client.get("/api/autofix/coverage", headers=alice.headers).json()
    assert cov["text"] == f"AutoFix доступен для {cov['available']} из {cov['total']} правил"
    assert cov["available"] == sum(1 for x in cov["rules"] if x["autofix"] != "none")


def _as_webhook_run(db, run_id, provider, repo, project):
    with db.session() as s:
        row = s.get(m.Run, run_id)
        row.trigger_payload = {"base_ref": "main",
                               "scm": {"provider": provider, "repo_url": repo, "project": project, "sha": "a" * 40}}
        s.commit()


def _allow(client, user, scm_url, provider, repo, allow_write=True):
    tok = client.post("/api/credentials", json={"workspace_id": user.workspace_id, "name": f"w{provider}",
                                                "kind": "repo_write_token",
                                                "value": "ghp_" + "w" * 36 if provider == "github" else "glpat-" + "w" * 20},
                      headers=user.headers).json()["id"]
    return client.put("/api/settings/allowlist", json={"workspace_id": user.workspace_id, "entries": [
        {"url": repo, "allow_write": allow_write, "provider": provider, "api_base": scm_url,
         "write_credential_id": tok}]}, headers=user.headers)


def test_github_pr_sequence_idempotency_and_masks(client, db, alice, scm, ready):  # noqa: F811
    script, r, pwd, _, _ = ready
    scm_url, state = scm
    _allow(client, alice, scm_url, "github", "https://github.com/alice/shop")
    _as_webhook_run(db, r["id"], "github", "https://github.com/alice/shop", "alice/shop")
    script.reply(fix(PWD_FILE, 4, 4, MASKED_LINE, ENV_FIX,
                     requires_config=[{"name": "PARTS_IMPORT_PASSWORD", "description": "пароль"}]))
    a = autofix(client, alice, r["id"], pwd["id"]).json()
    assert a.get("can_create_pr") is True, a
    state.requests.clear()
    pr = client.post(f"/api/autofixes/{a['id']}/pull-request", json={}, headers=alice.headers)
    assert pr.status_code == 200, pr.text
    assert pr.json()["created"] is True and pr.json()["branch"] == f"autofix/{pwd['id']}"
    seq = [(q["method"], q["path"].split("/alice/shop", 1)[1]) for q in state.requests]
    assert seq == [("GET", "/git/ref/heads/main"), ("POST", "/git/refs"), ("GET", f"/contents/{PWD_FILE}"),
                   ("PUT", f"/contents/{PWD_FILE}"), ("GET", "/pulls"), ("POST", "/pulls"),
                   ("POST", f"/issues/{pr.json()['number']}/labels")]
    assert state.requests[1]["body"] == {"ref": f"refs/heads/autofix/{pwd['id']}", "sha": "a" * 40}
    assert state.requests[3]["body"]["sha"] == "b" * 40 and state.requests[3]["body"]["branch"] == pr.json()["branch"]
    assert state.requests[0]["headers"]["Authorization"] == "Bearer ghp_" + "w" * 36
    pull = state.pulls[0]
    assert pull["base"] == "main" and pull["labels"] == ["security-autofix"]
    assert "PARTS_IMPORT_PASSWORD" in pull["body"] and "0 новых" in pull["body"] and "Auto-merge не включён" in pull["body"]
    pushed = state.files[f"alice/shop:{PWD_FILE}"]
    assert "System.getenv" in pushed and SECRET not in pushed and "…(len=" not in pushed
    assert "package lab.repairdesk.integration" in pushed  # the real file, not a fragment
    assert SECRET not in str(state.requests) and "…(len=" not in pull["body"].replace(pwd["title"], "")
    # idempotent: second click updates the same branch/PR
    again = client.post(f"/api/autofixes/{a['id']}/pull-request", json={}, headers=alice.headers).json()
    assert again["created"] is False and again["url"] == pr.json()["url"] and len(state.pulls) == 1
    with db.session() as s:
        actions = [x.action for x in s.scalars(select(m.AuditLog).where(m.AuditLog.action.like("autofix.%")))]
    assert actions.count("autofix.pull_request") == 2


def test_gitlab_mr_sequence_and_idempotency(client, db, alice, scm, ready):  # noqa: F811
    script, r, _, _, sca = ready
    scm_url, state = scm
    _allow(client, alice, scm_url, "gitlab", "https://gitlab.com/alice/shop")
    _as_webhook_run(db, r["id"], "gitlab", "https://gitlab.com/alice/shop", "alice/shop")
    a = autofix(client, alice, r["id"], sca["id"]).json()
    state.requests.clear()
    mr = client.post(f"/api/autofixes/{a['id']}/pull-request", json={}, headers=alice.headers).json()
    seq = [(q["method"], q["path"].split("alice/shop", 1)[1]) for q in state.requests]
    assert seq == [("POST", "/repository/branches"), ("POST", "/repository/commits"), ("GET", "/merge_requests"),
                   ("POST", "/merge_requests")]
    commit = state.requests[1]["body"]
    assert {x["file_path"] for x in commit["actions"]} == {"build.gradle.kts", "gradle.lockfile"}
    assert all(x["action"] == "update" for x in commit["actions"])
    assert state.requests[0]["query"]["ref"] == ["main"]
    assert state.pulls[0]["labels"] == "security-autofix" and mr["created"] is True
    again = client.post(f"/api/autofixes/{a['id']}/pull-request", json={}, headers=alice.headers).json()
    assert again["created"] is False and len(state.pulls) == 1
    assert {k.lower(): v for k, v in state.requests[-1]["headers"].items()}["private-token"] == "glpat-" + "w" * 20


def test_pr_forbidden_without_allow_write_and_for_organizer_repo(client, db, alice, bob, scm, ready):  # noqa: F811
    script, r, _, _, sca = ready
    scm_url, state = scm
    _allow(client, alice, scm_url, "github", "https://github.com/alice/shop", allow_write=False)
    _as_webhook_run(db, r["id"], "github", "https://github.com/alice/shop", "alice/shop")
    a = autofix(client, alice, r["id"], sca["id"]).json()
    assert a["can_create_pr"] is False and "allow_write" in a["pr_unavailable_reason"]
    res = client.post(f"/api/autofixes/{a['id']}/pull-request", json={}, headers=alice.headers)
    assert res.status_code == 403 and res.json()["error"]["code"] == "write_forbidden"
    _as_webhook_run(db, r["id"], "github", "https://github.com/TBagirov/training", "TBagirov/training")
    res = client.post(f"/api/autofixes/{a['id']}/pull-request", json={}, headers=alice.headers)
    assert res.status_code == 403 and "организаторов" in res.json()["error"]["message"]
    assert state.requests == []  # nothing was ever sent to an SCM
    assert client.get(f"/api/autofixes/{a['id']}", headers=bob.headers).status_code == 404
    assert client.post(f"/api/runs/{r['id']}/findings/{sca['id']}/autofix", json={},
                       headers=bob.headers).status_code == 404


def test_uploaded_archive_restored_until_ttl_then_purged(client, db, alice):
    import io
    import zipfile
    from datetime import UTC, datetime, timedelta
    from pathlib import Path

    from app.autofix.source import purge_expired_uploads
    from tests.engine.test_worker_scheduler import full_graph
    from tests.nodes.conftest import TRAINING

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in TRAINING.rglob("*"):
            if p.is_file():
                z.write(p, "training-project/" + p.relative_to(TRAINING).as_posix())
    up = client.post("/api/uploads", files={"file": ("t.zip", buf.getvalue(), "application/zip")},
                     data={"workspace_id": alice.workspace_id}, headers=alice.headers).json()["id"]
    pid = client.post("/api/projects", json={"workspace_id": alice.workspace_id, "name": "zip", "source_mode": "upload",
                                             "upload_id": up}, headers=alice.headers).json()["id"]
    g = full_graph()
    g["nodes"][1]["config"] = {"mode": "project"}
    wid = client.post("/api/workflows", json={"workspace_id": alice.workspace_id, "name": "z", "graph": g,
                                              "project_id": pid}, headers=alice.headers).json()["id"]
    r = run(client, db, alice, wid)
    full = client.get(f"/api/runs/{r['id']}", headers=alice.headers).json()
    assert full["source"]["mode"] == "upload" and "scan_path" not in full["source"]
    fs = client.get(f"/api/runs/{r['id']}/findings", headers=alice.headers).json()["findings"]
    sca = next(f for f in fs if f.get("artifact") == "commons-text")
    a = autofix(client, alice, r["id"], sca["id"]).json()
    assert a["status"] == "validated" and "загруженного архива" in a["pr_unavailable_reason"]
    with db.session() as s:
        row = s.get(m.Upload, up)
        stored = row.stored_path
        row.expires_at = datetime.now(UTC) - timedelta(hours=1)
        s.commit()
        assert purge_expired_uploads(s) == 1
    assert not Path(stored).exists()
    res = autofix(client, alice, r["id"], sca["id"])
    assert res.status_code == 409 and "срока хранения" in res.json()["error"]["message"]


def test_organizer_fixture_run_offers_patch_only(client, db, alice, monkeypatch):
    from app.config import REPO_ROOT, get_settings
    from tests.nodes.conftest import TRAINING

    monkeypatch.setattr(get_settings(), "scan_roots", str(REPO_ROOT / "fixtures"))
    _, wid = setup_project(client, alice, TRAINING)
    r = run(client, db, alice, wid)
    sca = next(f for f in client.get(f"/api/runs/{r['id']}/findings", headers=alice.headers).json()["findings"]
               if f.get("artifact") == "commons-text")
    before = (TRAINING / "build.gradle.kts").read_text()
    a = autofix(client, alice, r["id"], sca["id"]).json()
    assert a["status"] == "validated" and "организаторов" in a["pr_unavailable_reason"]
    assert client.post(f"/api/autofixes/{a['id']}/pull-request", json={}, headers=alice.headers).status_code == 403
    assert client.get(f"/api/autofixes/{a['id']}/patch", headers=alice.headers).status_code == 200
    assert (TRAINING / "build.gradle.kts").read_text() == before  # fixtures are read-only

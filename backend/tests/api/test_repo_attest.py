"""«Это учебный / собственный проект»: attesting a public repository adds it to the workspace allowlist (variant A)."""

import pytest

from app.api import repos
from app.core.repo_guard import RepoGuardError, check_git_url, normalize_user_repo_url

PUBLIC = "140.82.121.4"


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    table = {"github.com": [PUBLIC], "gitlab.example": [PUBLIC], "evil.example": ["127.0.0.1"], "10.0.0.5": ["10.0.0.5"]}
    monkeypatch.setattr(repos, "RESOLVER", lambda host, port: table[host])


def attest(client, user, url, confirm=True):
    return client.post("/api/repos/attest", json={"workspace_id": user.workspace_id, "url": url, "confirm": confirm},
                       headers=user.headers)


def test_normalize_user_repo_url():
    assert normalize_user_repo_url("  https://github.com/Org/Repo.git ") == ("https://github.com/org/repo", None, None)
    assert normalize_user_repo_url("https://github.com/Org/Repo/tree/dev/src") == ("https://github.com/org/repo", "dev", "src")
    assert normalize_user_repo_url("https://github.com/org/repo/tree/main/a/b/") == ("https://github.com/org/repo", "main", "a/b")
    assert normalize_user_repo_url("https://github.com/org/repo/blob/main/a.kt") == ("https://github.com/org/repo", "main", None)
    assert normalize_user_repo_url("https://gitlab.example/g/sub/p/-/tree/feat") == ("https://gitlab.example/g/sub/p", "feat", None)
    with pytest.raises(RepoGuardError, match="https"):
        normalize_user_repo_url("http://github.com/org/repo")
    with pytest.raises(RepoGuardError):
        normalize_user_repo_url("github.com/org/repo")


def test_confirmation_required(client, alice):
    r = attest(client, alice, "https://github.com/org/repo", confirm=False)
    assert r.status_code == 422 and r.json()["error"]["code"] == "confirmation_required"


def test_attest_adds_to_allowlist_and_audits(client, alice, db):
    r = attest(client, alice, "https://github.com/Org/Repo/tree/dev/src")
    assert r.status_code == 200, r.text
    assert r.json() == {"url": "https://github.com/org/repo", "ref": "dev", "subdir": "src", "readonly": False}
    entries = client.get("/api/settings/allowlist", headers=alice.headers).json()["entries"]
    assert [e["url"] for e in entries] == ["https://github.com/org/repo"] and entries[0]["allow_write"] is False
    assert attest(client, alice, "https://github.com/org/repo.git").status_code == 200  # idempotent
    assert len(client.get("/api/settings/allowlist", headers=alice.headers).json()["entries"]) == 1
    check_git_url("https://github.com/org/repo", [e["url"] for e in entries])
    from sqlalchemy import select

    from app import models as m
    with db.session() as s:
        rows = s.scalars(select(m.AuditLog).where(m.AuditLog.action == "repo.attest")).all()
        assert len(rows) == 2 and rows[0].target == "https://github.com/org/repo"


def test_http_rejected_with_reason(client, alice):
    r = attest(client, alice, "http://github.com/org/repo")
    assert r.status_code == 422 and "https" in r.json()["error"]["message"]


@pytest.mark.parametrize("url", ["https://10.0.0.5/x/y", "https://evil.example/org/repo"])
def test_private_hosts_rejected(client, alice, url):
    r = attest(client, alice, url)
    assert r.status_code == 422 and r.json()["error"]["code"] == "private_host"


def test_organizer_repo_stays_readonly(client, alice):
    r = attest(client, alice, "https://github.com/TBagirov/training")
    assert r.status_code == 200 and r.json()["readonly"] is True


def test_viewer_forbidden(client, alice, bob):
    client.post(f"/api/workspaces/{alice.workspace_id}/members", json={"email": bob.email, "role": "viewer"},
                headers=alice.headers)
    r = client.post("/api/repos/attest", json={"workspace_id": alice.workspace_id, "url": "https://github.com/o/r",
                                               "confirm": True}, headers=bob.headers)
    assert r.status_code == 403

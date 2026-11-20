"""CLI-mode PR/MR comment: upsert by marker on a real local mock GitHub/GitLab HTTP server (no spam on re-runs)."""

import importlib.util
import json
import sys

import pytest

from app.config import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import mock_scm  # noqa: E402

spec = importlib.util.spec_from_file_location("aisw_ci", REPO_ROOT / "cli" / "aisw_ci.py")
aisw_ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aisw_ci)


@pytest.fixture
def scm():
    srv, state = mock_scm.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", state
    srv.shutdown()


def test_github_comment_is_created_then_updated(scm, tmp_path, monkeypatch):
    url, state = scm
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"number": 7, "pull_request": {"number": 7}}))
    for k, v in {"GITHUB_ACTIONS": "true", "GITHUB_API_URL": url, "GITHUB_REPOSITORY": "alice/shop",
                 "GITHUB_EVENT_PATH": str(event), "GITHUB_TOKEN": "ghs_" + "t" * 36}.items():
        monkeypatch.setenv(k, v)
    assert aisw_ci.publish_comment("## AI Security Workflow\nfirst") == "created"
    assert aisw_ci.publish_comment("## AI Security Workflow\nsecond") == "updated"
    comments = state.comments["gh:alice/shop#7"]
    assert len(comments) == 1 and "second" in comments[0]["body"] and aisw_ci.COMMENT_MARKER in comments[0]["body"]
    posts = [r for r in state.requests if r["method"] in ("POST", "PATCH")]
    assert posts[0]["headers"]["Authorization"] == "Bearer ghs_" + "t" * 36
    assert posts[1]["method"] == "PATCH" and posts[1]["path"].endswith(f"/issues/comments/{comments[0]['id']}")


def test_gitlab_note_upsert(scm, monkeypatch):
    url, state = scm
    for k, v in {"GITLAB_CI": "true", "CI_API_V4_URL": url, "CI_PROJECT_ID": "alice/shop",
                 "CI_MERGE_REQUEST_IID": "3", "GITLAB_TOKEN": "glpat-" + "z" * 20}.items():
        monkeypatch.setenv(k, v)
    assert aisw_ci.publish_comment("report v1") == "created"
    assert aisw_ci.publish_comment("report v2") == "updated"
    notes = state.comments["gl:alice/shop!3"]
    assert len(notes) == 1 and "report v2" in notes[0]["body"]
    hdr = {k.lower(): v for k, v in state.requests[-1]["headers"].items()}
    assert hdr["private-token"] == "glpat-" + "z" * 20


def test_no_comment_without_token_or_pr(monkeypatch):
    for k in ("GITHUB_ACTIONS", "GITLAB_CI", "GITHUB_TOKEN", "GITLAB_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    assert aisw_ci.publish_comment("x") == "skipped"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "alice/shop")
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_x")
    assert aisw_ci.publish_comment("x") == "skipped"  # push build: no PR to comment on

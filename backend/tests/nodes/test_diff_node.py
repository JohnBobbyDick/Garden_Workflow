import secrets
import shutil
import string
import subprocess

import pytest

from app.analyzers.diff.git import DiffContextError
from app.analyzers.runner import analyze_project
from app.engine.data import findings_envelope, findings_of
from app.nodes.base import Envelope
from tests.nodes.conftest import TRAINING, StubServices, run_node


def sh(repo, *args):
    return subprocess.run(["git", "-c", "user.name=Dev", "-c", "user.email=dev@example.com", "-c",
                           "commit.gpgsign=false", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


def synthetic_aws_key() -> tuple[str, str]:
    alnum = string.ascii_uppercase + string.digits
    return ("AKIA" + "".join(secrets.choice(alnum) for _ in range(16)),
            "".join(secrets.choice(string.ascii_letters + string.digits + "/+") for _ in range(40)))


@pytest.fixture
def git_project(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(TRAINING, repo / "training-project")
    sh(tmp_path, "init", "-q", "-b", "main", str(repo))
    sh(repo, "add", ".")
    sh(repo, "commit", "-q", "-m", "base: training project")
    sh(repo, "checkout", "-q", "-b", "feature")
    target = next((repo / "training-project" / "src" / "main" / "kotlin").rglob("*.kt"))
    key_id, key_secret = synthetic_aws_key()
    target.write_text(target.read_text() + f'\nval awsAccessKeyId = "{key_id}"\n'
                                           f'val awsSecretAccessKey = "{key_secret}"\n')
    sh(repo, "commit", "-q", "-am", "add cloud upload")
    return repo, repo / "training-project", target


def _run(root, boundary, config=None, services=None):
    findings = analyze_project(root).findings
    inputs = {"repo": Envelope.make("repo", {"root": str(root), "git": {"boundary": str(boundary)}}, "src"),
              "findings": findings_envelope(findings, "merge")}
    return run_node("scanner.diff", inputs, config or {}, services=services)


def test_new_secret_in_pr_fails_and_old_findings_are_existing(git_project, tmp_path):
    repo, root, target = git_project
    services = StubServices(tmp_path)
    out, _ = _run(root, repo, services=services)
    v = out["verdict"].data
    new = findings_of(out["new_findings"])
    assert v["verdict"] == "FAIL" and v["new_counts_by_severity"]["CRITICAL"] >= 1
    assert all(f.path == target.relative_to(root).as_posix() for f in new)
    assert any(f.cls == "aws-access-key" and f.author == "dev@example.com" and f.introduced_in_commit for f in new)
    assert len(findings_of(out["existing_findings"])) == 15 and v["existing_count"] == 15
    assert v["merge_base"] == sh(repo, "rev-parse", "main")
    assert services.run_fields["verdict"]["verdict"] == "FAIL"
    assert {a["diff_status"] for a in services.annotations.values()} == {"new", "existing"}


def test_key_removed_passes(git_project):
    repo, root, target = git_project
    sh(repo, "revert", "--no-edit", "HEAD")
    out, _ = _run(root, repo)
    assert out["verdict"].data["verdict"] == "PASS" and not findings_of(out["new_findings"])


def test_missing_git_fails_or_treats_all_as_new(tmp_path):
    root = tmp_path / "p"
    shutil.copytree(TRAINING, root)
    with pytest.raises(DiffContextError):
        _run(root, root)
    out, _ = _run(root, root, {"on_missing_diff": "treat_all_as_new"})
    assert len(findings_of(out["new_findings"])) == 15 and out["verdict"].data["verdict"] == "FAIL"
    assert out["verdict"].data["diff_available"] is False


def test_git_lookup_never_escapes_boundary(git_project):
    repo, root, _ = git_project
    with pytest.raises(DiffContextError):  # .git lives above the boundary → not used
        _run(root, root)

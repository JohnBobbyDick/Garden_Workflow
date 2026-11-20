import subprocess

import pytest

from app.analyzers.diff.blame import parse_porcelain
from app.analyzers.diff.git import DiffContextError, compute_platform, load_uploaded
from app.core.repo_guard import RepoGuardError


def sh(repo, *args, author="dev@example.com"):
    return subprocess.run(["git", "-c", "user.name=Dev", "-c", f"user.email={author}", "-c", "commit.gpgsign=false",
                           *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    (r / "app" / "src").mkdir(parents=True)
    sh(tmp_path, "init", "-q", "-b", "main", str(r))
    (r / "app" / "src" / "A.kt").write_text("package a\n\nfun a() = 1\n")
    (r / "app" / "gradle.properties").write_text("libVersion=1.0.0\n")
    (r / "app" / "build.gradle.kts").write_text('dependencies { implementation("g:a:${property("libVersion")}") }\n')
    sh(r, "add", ".")
    sh(r, "commit", "-q", "-m", "base")
    return r


def test_three_dots_exclude_commits_landed_on_base_after_branching(repo):
    sh(repo, "checkout", "-q", "-b", "feature")
    (repo / "app" / "src" / "A.kt").write_text("package a\n\nfun a() = 1\nval token = \"x\"\n")
    sh(repo, "commit", "-q", "-am", "feature change", author="alice@example.com")
    sh(repo, "checkout", "-q", "main")
    (repo / "app" / "src" / "B.kt").write_text("package b\n")
    sh(repo, "add", ".")
    sh(repo, "commit", "-q", "-m", "landed on main later")
    sh(repo, "checkout", "-q", "feature")
    dc = compute_platform(repo, repo / "app", "main")
    assert set(dc.changes) == {"src/A.kt"}  # B.kt from main is not part of the PR
    assert dc.changes["src/A.kt"].new_lines == {4}
    assert dc.merge_base != dc.base_sha  # main moved on after the branch point
    assert dc.base_files["gradle.properties"] == "libVersion=1.0.0\n"
    commit, author = dc.attribution("src/A.kt", 4)
    assert author == "alice@example.com" and commit == sh(repo, "rev-parse", "HEAD")
    two_dots = sh(repo, "diff", "--name-only", "main", "feature")
    assert "app/src/B.kt" in two_dots  # what a two-dot diff would have wrongly included


def test_whitespace_only_reformat_is_not_new(repo):
    sh(repo, "checkout", "-q", "-b", "fmt")
    (repo / "app" / "src" / "A.kt").write_text("package a\n\n\nfun  a()  =  1\n")
    sh(repo, "commit", "-q", "-am", "reformat")
    dc = compute_platform(repo, repo / "app", "main")
    assert not dc.changes.get("src/A.kt") or not dc.changes["src/A.kt"].new_lines
    dc2 = compute_platform(repo, repo / "app", "main", ignore_whitespace=False)
    assert dc2.changes["src/A.kt"].new_lines


def test_git_argument_injection_and_bad_refs_are_rejected(repo):
    with pytest.raises(RepoGuardError):
        compute_platform(repo, repo / "app", "--upload-pack=touch /tmp/pwned")
    with pytest.raises(RepoGuardError):
        compute_platform(repo, repo / "app", "main", head="not-a-sha;rm")
    with pytest.raises(DiffContextError):
        compute_platform(repo, repo / "app", "f" * 40)  # well-formed but unknown base commit, no remote


def test_no_git_history_is_an_error(tmp_path):
    with pytest.raises(DiffContextError):
        compute_platform(tmp_path, tmp_path, "main")


def test_uploaded_context_is_relativized_and_filtered_by_globs():
    diff = ("diff --git a/app/src/A.kt b/app/src/A.kt\n--- a/app/src/A.kt\n+++ b/app/src/A.kt\n@@ -1,0 +2 @@\n+x\n"
            "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-a\n+b\n")
    dc = load_uploaded({"base_sha": "a" * 40, "head_sha": "b" * 40, "merge_base": "c" * 40, "diff": diff,
                        "path_prefix": "app", "base_files": {"gradle.properties": "v=1\n"},
                        "blame": {"src/A.kt": {"2": ["d" * 40, "bob@example.com"]}}})
    assert set(dc.changes) == {"src/A.kt"} and dc.merge_base == "c" * 40
    assert dc.attribution("src/A.kt", 2) == ("d" * 40, "bob@example.com")
    with pytest.raises(DiffContextError):
        load_uploaded({"diff": 5})


def test_parse_porcelain_repeats_commit_info_once():
    sha = "a" * 40
    text = (f"{sha} 1 1 2\nauthor Dev\nauthor-mail <dev@example.com>\nsummary s\nfilename f\n\tline1\n"
            f"{sha} 2 2\n\tline2\n")
    assert parse_porcelain(text) == {1: (sha, "dev@example.com"), 2: (sha, "dev@example.com")}

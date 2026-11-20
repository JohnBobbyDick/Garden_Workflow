import io
import tarfile
import zipfile

import pytest

from app.core.repo_guard import (
    ExtractLimits,
    RepoGuardError,
    check_git_url,
    check_ref,
    check_scan_path,
    git_clone_command,
    is_readonly_repo,
    normalize_repo_url,
    safe_extract,
)

ALLOW = ["https://github.com/TBagirov/training"]


def test_allowlisted_url_accepted_with_normalization():
    assert check_git_url("https://github.com/TBagirov/training.git", ALLOW) == "https://github.com/tbagirov/training"
    assert check_git_url("https://GitHub.com/TBagirov/training/", ALLOW) == "https://github.com/tbagirov/training"


@pytest.mark.parametrize("url", [
    "https://github.com/someone/else", "http://github.com/TBagirov/training", "file:///etc/passwd",
    "ext::sh -c touch% /tmp/pwned", "git@github.com:TBagirov/training.git", "ssh://github.com/TBagirov/training",
    "https://user:pass@github.com/TBagirov/training", "https://github.com/TBagirov/training/../x",
    "--upload-pack=touch /tmp/x", "https://github.com/TBagirov/training-evil",
])
def test_foreign_or_dangerous_urls_rejected(url):
    with pytest.raises(RepoGuardError):
        check_git_url(url, ALLOW)


@pytest.mark.parametrize("ref", ["main", "feature/x-1", "v1.2.3", "a1b2c3d", "0" * 40])
def test_valid_refs(ref):
    assert check_ref(ref) == ref


@pytest.mark.parametrize("ref", ["--upload-pack=x", "-b", "a..b", "x y", "ref@{1}", "", "a" * 300, "x;rm"])
def test_invalid_refs(ref):
    with pytest.raises(RepoGuardError):
        check_ref(ref)


def test_clone_command_is_argument_list_with_hardening():
    cmd, env = git_clone_command("https://github.com/tbagirov/training", "main", "/tmp/dest")
    assert cmd[0] == "git" and "--" in cmd and cmd[-2:] == ["https://github.com/tbagirov/training", "/tmp/dest"]
    assert "core.hooksPath=/dev/null" in cmd and "--depth" in cmd
    assert env["GIT_ALLOW_PROTOCOL"] == "https" and env["GIT_TERMINAL_PROMPT"] == "0"


def test_scan_path_must_be_inside_roots(tmp_path):
    root = tmp_path / "root"
    (root / "proj").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    assert check_scan_path(str(root / "proj"), [root]) == (root / "proj").resolve()
    with pytest.raises(RepoGuardError):
        check_scan_path(str(tmp_path / "outside"), [root])
    with pytest.raises(RepoGuardError):
        check_scan_path(str(root / "proj" / ".." / ".." / "outside"), [root])


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_zip_extracts_normally(tmp_path):
    root = safe_extract(_zip({"proj/a.kt": b"val x = 1", "proj/sub/b.yml": b"k: v"}), "p.zip", tmp_path / "x")
    assert (root / "a.kt").read_text() == "val x = 1"  # single top-level dir is unwrapped


def test_zip_slip_rejected(tmp_path):
    with pytest.raises(RepoGuardError):
        safe_extract(_zip({"../evil.txt": b"x"}), "p.zip", tmp_path / "x")
    with pytest.raises(RepoGuardError):
        safe_extract(_zip({"/abs.txt": b"x"}), "p.zip", tmp_path / "x")


def test_zip_bomb_rejected(tmp_path):
    data = _zip({"big.txt": b"0" * (2 * 1024 * 1024)})
    with pytest.raises(RepoGuardError):
        safe_extract(data, "p.zip", tmp_path / "x", ExtractLimits(max_unpacked_bytes=1024 * 1024))


def test_too_many_files_rejected(tmp_path):
    data = _zip({f"f{i}.txt": b"x" for i in range(20)})
    with pytest.raises(RepoGuardError):
        safe_extract(data, "p.zip", tmp_path / "x", ExtractLimits(max_files=10))


def test_tar_symlink_rejected(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        t.addfile(info)
    with pytest.raises(RepoGuardError):
        safe_extract(buf.getvalue(), "p.tar.gz", tmp_path / "x")


def test_tar_regular_files_ok(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        payload = b"plugins {}"
        info = tarfile.TarInfo("build.gradle.kts")
        info.size = len(payload)
        t.addfile(info, io.BytesIO(payload))
    root = safe_extract(buf.getvalue(), "p.tgz", tmp_path / "x")
    assert (root / "build.gradle.kts").read_bytes() == b"plugins {}"


def test_unknown_archive_type_rejected(tmp_path):
    with pytest.raises(RepoGuardError):
        safe_extract(b"not an archive", "p.rar", tmp_path / "x")


def test_organizer_repository_is_readonly_by_code():
    assert is_readonly_repo("https://github.com/TBagirov/training.git")
    assert not is_readonly_repo("https://github.com/me/my-own-project")


def test_normalize_repo_url():
    assert normalize_repo_url("https://GitHub.com/A/B.git/") == "https://github.com/a/b"

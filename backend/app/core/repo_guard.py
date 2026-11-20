"""Technical ban on scanning anything except allowlisted repositories, allowed local roots and user uploads.

* ``git_url`` — https only, exact match against the workspace/platform allowlist, hardened ``git`` invocation
  (argument list, ``GIT_ALLOW_PROTOCOL=https``, no prompts, no hooks, shallow, timeout); refs/shas validated.
* ``path`` — only inside ``APP_SCAN_ROOTS``.
* ``upload`` — safe extraction: no absolute paths, no ``..``, no links/devices, file count and size limits
  (zip bombs are stopped while streaming, not by trusting headers).
* The organizer repository and our fixtures are read-only by code (never ``allow_write``)."""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from app.config import REPO_ROOT

READONLY_REPOS = {"https://github.com/tbagirov/training"}
READONLY_PATHS = [REPO_ROOT / "fixtures"]
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
REF_RE = re.compile(r"^[A-Za-z0-9._/\-]{1,200}$")
GIT_TIMEOUT = 180


class RepoGuardError(ValueError):
    pass


def normalize_repo_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return f"{parts.scheme.lower()}://{(parts.hostname or '').lower()}{path.rstrip('/').lower()}"


def check_git_url(url: str, allowlist: list[str]) -> str:
    if not isinstance(url, str) or not url or url.startswith("-") or len(url) > 500:
        raise RepoGuardError("недопустимый URL репозитория")
    if any(c in url for c in " \t\r\n\\"):
        raise RepoGuardError("URL репозитория содержит недопустимые символы")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise RepoGuardError("разрешены только https-URL репозиториев")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise RepoGuardError("URL репозитория не должен содержать учётные данные или нестандартный порт")
    if parts.query or parts.fragment or ".." in parts.path.split("/"):
        raise RepoGuardError("недопустимый путь в URL репозитория")
    norm = normalize_repo_url(url)
    allowed = {normalize_repo_url(a) for a in allowlist}
    if norm not in allowed:
        raise RepoGuardError("репозиторий не входит в allowlist: сканирование посторонних репозиториев запрещено")
    return norm


def check_ref(ref: str) -> str:
    if not isinstance(ref, str) or not REF_RE.match(ref) or ref.startswith(("-", "/")) or ".." in ref \
            or ref.endswith((".lock", "/")) or "@{" in ref:
        raise RepoGuardError(f"недопустимое имя ветки/ref: {ref[:60]!r}")
    return ref


def check_sha(sha: str) -> str:
    if not isinstance(sha, str) or not SHA_RE.match(sha):
        raise RepoGuardError("недопустимый commit sha")
    return sha


def is_readonly_repo(url: str) -> bool:
    return normalize_repo_url(url) in READONLY_REPOS


def is_readonly_path(path: str | Path) -> bool:
    p = Path(path).resolve()
    return any(p.is_relative_to(r.resolve()) for r in READONLY_PATHS)


def check_scan_path(path: str, roots: list[Path]) -> Path:
    if not path or "\x00" in path:
        raise RepoGuardError("пустой путь")
    p = Path(path).resolve()
    for root in roots:
        r = root.resolve()
        if p == r or p.is_relative_to(r):
            if not p.is_dir():
                raise RepoGuardError("путь не является каталогом")
            return p
    raise RepoGuardError("путь вне разрешённых корней APP_SCAN_ROOTS")


def git_env(token: str | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "HOME", "USERPROFILE", "TEMP", "TMP")}
    env.update({"GIT_ALLOW_PROTOCOL": "https", "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_ASKPASS": "", "SSH_ASKPASS": "", "GCM_INTERACTIVE": "never"})
    if token:
        # token travels in a header via env config, never in the URL / argv
        env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraHeader",
                    "GIT_CONFIG_VALUE_0": f"Authorization: Bearer {token}"})
    return env


def _git_base() -> list[str]:
    return ["git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.file.allow=never", "-c", "protocol.ext.allow=never",
            "-c", "core.symlinks=false", "-c", "credential.helper="]


def git_clone_command(url: str, ref: str | None, dest: str, depth: int = 1,
                      token: str | None = None) -> tuple[list[str], dict[str, str]]:
    cmd = _git_base() + ["clone", "--no-tags", "--depth", str(depth), "--single-branch"]
    if ref:
        cmd += ["--branch", check_ref(ref)]
    cmd += ["--", url, dest]
    return cmd, git_env(token)


def run_git(cmd: list[str], env: dict[str, str], cwd: str | None = None, timeout: int = GIT_TIMEOUT) -> str:
    try:
        proc = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RepoGuardError("git: превышено время ожидания") from exc
    except FileNotFoundError as exc:
        raise RepoGuardError("git не установлен") from exc
    if proc.returncode != 0:
        raise RepoGuardError(f"git завершился с ошибкой: {proc.stderr.strip()[-500:]}")
    return proc.stdout


def clone_repo(url: str, ref: str | None, dest: Path, allowlist: list[str], token: str | None = None,
               depth: int = 1) -> dict[str, str]:
    """Clone an allowlisted repository at a branch/tag or exact commit sha. Returns {url, ref, commit}."""
    norm = check_git_url(url, allowlist)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if ref and SHA_RE.match(ref) and len(ref) == 40:
        dest.mkdir(parents=True, exist_ok=True)
        env = git_env(token)
        run_git(_git_base() + ["init", "-q", "--", str(dest)], env)
        run_git(_git_base() + ["-C", str(dest), "remote", "add", "origin", "--", norm], env)
        run_git(_git_base() + ["-C", str(dest), "fetch", "--no-tags", "--depth", str(depth), "origin", check_sha(ref)],
                env)
        run_git(_git_base() + ["-C", str(dest), "checkout", "-q", "--detach", "FETCH_HEAD"], env)
    else:
        cmd, env = git_clone_command(norm, ref, str(dest), depth, token)
        run_git(cmd, env)
    commit = run_git(_git_base() + ["-C", str(dest), "rev-parse", "HEAD"], git_env()).strip()
    return {"url": norm, "ref": ref or "", "commit": commit}


@dataclass
class ExtractLimits:
    max_files: int = 20_000
    max_unpacked_bytes: int = 300 * 1024 * 1024
    max_file_bytes: int = 50 * 1024 * 1024


def _safe_member(name: str) -> PurePosixPath:
    name = name.replace("\\", "/")
    p = PurePosixPath(name)
    if not name or name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in p.parts or "\x00" in name:
        raise RepoGuardError(f"небезопасный путь в архиве: {name[:100]!r}")
    return p


def _copy_limited(src, dst_path: Path, budget: list[int], limits: ExtractLimits) -> None:  # noqa: ANN001
    written = 0
    with open(dst_path, "wb") as out:
        while True:
            chunk = src.read(64 * 1024)
            if not chunk:
                break
            written += len(chunk)
            budget[0] += len(chunk)
            if written > limits.max_file_bytes or budget[0] > limits.max_unpacked_bytes:
                raise RepoGuardError("архив слишком большой после распаковки (защита от zip-бомбы)")
            out.write(chunk)


def safe_extract(data: bytes, filename: str, dest: Path, limits: ExtractLimits | None = None) -> Path:
    """Extract a zip/tar(.gz) archive into ``dest``; returns the project root (a single top dir is unwrapped)."""
    limits = limits or ExtractLimits()
    dest.mkdir(parents=True, exist_ok=True)
    budget = [0]
    count = 0
    lower = filename.lower()
    try:
        if lower.endswith(".zip") or zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    rel = _safe_member(info.filename)
                    mode = (info.external_attr >> 16) & 0o170000
                    if mode in (0o120000,):
                        raise RepoGuardError("символические ссылки в архиве запрещены")
                    count += 1
                    if count > limits.max_files:
                        raise RepoGuardError("слишком много файлов в архиве")
                    target = dest.joinpath(*rel.parts)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src:
                        _copy_limited(src, target, budget, limits)
        elif lower.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")):
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as t:
                for m in t:
                    rel = _safe_member(m.name)
                    if not (m.isfile() or m.isdir()):
                        raise RepoGuardError("ссылки и специальные файлы в архиве запрещены")
                    count += 1
                    if count > limits.max_files:
                        raise RepoGuardError("слишком много файлов в архиве")
                    target = dest.joinpath(*rel.parts)
                    if m.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    src = t.extractfile(m)
                    if src is not None:
                        _copy_limited(src, target, budget, limits)
        else:
            raise RepoGuardError("поддерживаются только архивы zip и tar(.gz)")
    except (zipfile.BadZipFile, tarfile.TarError, EOFError, OSError) as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise RepoGuardError(f"повреждённый архив: {exc}") from exc
    except RepoGuardError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    entries = [p for p in dest.iterdir() if p.name not in ("__MACOSX",)]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return dest

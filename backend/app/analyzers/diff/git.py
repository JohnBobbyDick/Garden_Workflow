"""Diff context: from a CLI upload (``diff_context`` JSON) or computed on the platform from a git checkout.

Platform-side git is read-only and goes through ``repo_guard``: hardened ``git -c ...`` base, refs/shas validated,
arguments as a list with ``--`` separators, https-only fetch with the token in a header, no hooks / fsmonitor /
external diff / textconv. Shallow clones are deepened (bounded) until the merge base is reachable.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

from app.analyzers.diff.blame import parse_porcelain
from app.analyzers.diff.hunks import DEFAULT_GLOBS, FileChange, parse_unified_diff, relativize
from app.core.repo_guard import SHA_RE, RepoGuardError, _git_base, check_ref, check_sha, git_env, run_git

ZERO_SHA = "0" * 40
BUILD_FILE_NAMES = ("build.gradle.kts", "build.gradle", "settings.gradle.kts", "settings.gradle", "gradle.properties",
                    "gradle.lockfile", "libs.versions.toml")
DEEPEN_STEP = 200
DEEPEN_MAX_ROUNDS = 5
MAX_DIFF_BYTES = 5_000_000


class DiffContextError(RuntimeError):
    pass


@dataclass
class DiffContext:
    base_sha: str
    head_sha: str
    merge_base: str
    changes: dict[str, FileChange]
    base_files: dict[str, str] = field(default_factory=dict)  # project-relative path -> base content
    blame: dict[str, dict[int, tuple[str, str]]] = field(default_factory=dict)
    origin: str = "upload"  # upload | platform
    repo_dir: Path | None = None
    path_prefix: str = ""

    def attribution(self, path: str, line: int) -> tuple[str, str] | None:
        hit = self.blame.get(path, {}).get(line)
        if hit is not None or self.repo_dir is None:
            return hit
        try:
            out = _git(self.repo_dir, ["blame", "--porcelain", "-L", f"{int(line)},{int(line)}", self.head_sha, "--",
                                       f"{self.path_prefix}/{path}" if self.path_prefix else path])
        except RepoGuardError:
            return None
        parsed = parse_porcelain(out)
        hit = parsed.get(line)
        if hit is not None:
            self.blame.setdefault(path, {})[line] = hit
        return hit


def _git(repo: Path, args: list[str], token: str | None = None, timeout: int = 120) -> str:
    cmd = _git_base() + ["-c", "core.fsmonitor=false", "-c", "diff.external=", "-C", str(repo), *args]
    return run_git(cmd, git_env(token), timeout=timeout)


def _match_globs(path: str, globs: tuple[str, ...] | list[str]) -> bool:
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(name, g) or fnmatch.fnmatch(path, g) for g in globs)


def load_uploaded(dc: dict, globs: tuple[str, ...] | list[str] = DEFAULT_GLOBS) -> DiffContext:
    """Diff context computed by the CLI in CI (``git diff`` from the merge base, base build files, blame)."""
    if not isinstance(dc, dict) or not isinstance(dc.get("diff", ""), str):
        raise DiffContextError("diff_context: неверный формат")
    prefix = str(dc.get("path_prefix") or "").strip("/")
    changes = relativize(parse_unified_diff(dc.get("diff") or ""), prefix)
    changes = {p: c for p, c in changes.items() if _match_globs(p, globs)}
    blame: dict[str, dict[int, tuple[str, str]]] = {}
    for path, lines in (dc.get("blame") or {}).items():
        if isinstance(lines, dict):
            blame[str(path)] = {int(k): (str(v[0])[:40], str(v[1])[:200]) for k, v in lines.items()
                                if isinstance(v, list | tuple) and len(v) == 2 and str(k).isdigit()}
    base_files = {str(k): str(v) for k, v in (dc.get("base_files") or {}).items() if isinstance(v, str)}
    head = str(dc.get("head_sha") or "")[:64]
    mb = str(dc.get("merge_base") or dc.get("base_sha") or "")[:64]
    return DiffContext(base_sha=str(dc.get("base_sha") or mb)[:64], head_sha=head, merge_base=mb, changes=changes,
                       base_files=base_files, blame=blame, origin="upload", path_prefix=prefix)


def _has_commit(repo: Path, sha: str) -> bool:
    try:
        _git(repo, ["cat-file", "-e", f"{check_sha(sha)}^{{commit}}"])
        return True
    except RepoGuardError:
        return False


def _remote_exists(repo: Path) -> bool:
    try:
        return bool(_git(repo, ["remote"]).split())
    except RepoGuardError:
        return False


def _resolve_base(repo: Path, base: str | None, can_fetch: bool, token: str | None) -> str:
    """A base commit sha: explicit sha (fetched if missing) or branch (origin/<b> preferred)."""
    if base and SHA_RE.match(base) and base != ZERO_SHA and len(base) == 40:
        if not _has_commit(repo, base) and can_fetch:
            _git(repo, ["fetch", "--no-tags", "--depth", str(DEEPEN_STEP), "origin", check_sha(base)], token, 300)
        if _has_commit(repo, base):
            return base
        raise DiffContextError(f"base-коммит {base[:12]} недоступен в репозитории")
    branch = check_ref(base if base and base != ZERO_SHA and not SHA_RE.match(base) else "main")
    if branch.startswith("-"):
        raise RepoGuardError("недопустимое имя ветки")
    if can_fetch:
        try:
            _git(repo, ["fetch", "--no-tags", "--depth", str(DEEPEN_STEP), "origin",
                        f"refs/heads/{branch}:refs/remotes/origin/{branch}"], token, 300)
        except RepoGuardError:
            pass
    for cand in (f"refs/remotes/origin/{branch}", f"refs/heads/{branch}"):
        try:
            return _git(repo, ["rev-parse", "--verify", "--quiet", f"{cand}^{{commit}}"]).strip()
        except RepoGuardError:
            continue
    raise DiffContextError(f"базовая ветка {branch!r} не найдена")


def _merge_base(repo: Path, base: str, head: str, can_fetch: bool, token: str | None) -> str:
    for round_ in range(DEEPEN_MAX_ROUNDS + 1):
        try:
            return _git(repo, ["merge-base", base, head]).strip()
        except RepoGuardError:
            if not can_fetch or round_ == DEEPEN_MAX_ROUNDS:
                break
            _git(repo, ["fetch", "--no-tags", f"--deepen={DEEPEN_STEP}", "origin"], token, 300)
    raise DiffContextError("не удалось найти общего предка (merge-base) базы и head")


def compute_platform(repo_dir: Path, project_root: Path, base: str | None, head: str | None = None,
                     globs: tuple[str, ...] | list[str] = DEFAULT_GLOBS, ignore_whitespace: bool = True,
                     token: str | None = None) -> DiffContext:
    repo_dir = Path(repo_dir)
    if not (repo_dir / ".git").exists():
        raise DiffContextError("у источника нет истории git")
    can_fetch = _remote_exists(repo_dir)
    head_sha = _git(repo_dir, ["rev-parse", "--verify", f"{check_sha(head) if head else 'HEAD'}^{{commit}}"]).strip()
    base_sha = _resolve_base(repo_dir, base, can_fetch, token)
    mb = _merge_base(repo_dir, base_sha, head_sha, can_fetch, token)
    try:
        prefix = Path(project_root).resolve().relative_to(repo_dir.resolve()).as_posix()
    except ValueError as exc:
        raise DiffContextError("проект находится вне git-репозитория") from exc
    prefix = "" if prefix == "." else prefix
    args = ["diff", "--no-ext-diff", "--no-textconv", "--no-color", "--unified=0", "--find-renames"]
    if ignore_whitespace:
        args += ["-w", "--ignore-blank-lines"]
    # three dots: changes since the merge base only — commits that landed on base after branching are excluded
    args += [f"{base_sha}...{head_sha}", "--"]
    args += [f"{prefix}/" if prefix else "."]
    diff = _git(repo_dir, args)[:MAX_DIFF_BYTES]
    changes = {p: c for p, c in relativize(parse_unified_diff(diff), prefix).items() if _match_globs(p, globs)}
    base_files: dict[str, str] = {}
    try:
        listing = _git(repo_dir, ["ls-tree", "-r", "--name-only", mb, "--", f"{prefix}/" if prefix else "."])
    except RepoGuardError:
        listing = ""
    for full in listing.splitlines():
        if full.rsplit("/", 1)[-1] in BUILD_FILE_NAMES:
            rel = full[len(prefix) + 1:] if prefix else full
            try:
                base_files[rel] = _git(repo_dir, ["show", "--no-textconv", f"{mb}:{full}"])
            except RepoGuardError:
                continue
    return DiffContext(base_sha=base_sha, head_sha=head_sha, merge_base=mb, changes=changes, base_files=base_files,
                       origin="platform", repo_dir=repo_dir, path_prefix=prefix)

"""Project file walker shared by analyzers: relative `/` paths, ignores build output, binaries, large files."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SKIP_DIRS = {".git", ".gradle", ".idea", ".kotlin", "build", "out", "target", "node_modules", "__pycache__",
                     ".venv", "dist"}
DEFAULT_MAX_FILE_SIZE = 1_000_000


@dataclass(frozen=True)
class ProjectFile:
    rel: str
    abs: Path

    def read_text(self) -> str:
        return self.abs.read_text(encoding="utf-8", errors="replace")

    def read_bytes(self) -> bytes:
        return self.abs.read_bytes()

    @property
    def name(self) -> str:
        return self.abs.name

    @property
    def suffix(self) -> str:
        return self.abs.suffix.lower()


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            chunk = fh.read(8192)
    except OSError:
        return True
    return b"\x00" in chunk


def _load_gitignore(root: Path) -> list[str]:
    gi = root / ".gitignore"
    if not gi.is_file():
        return []
    pats = []
    for line in gi.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("!"):
            pats.append(line)
    return pats


def _gitignored(rel: str, is_dir: bool, patterns: list[str]) -> bool:
    name = rel.rsplit("/", 1)[-1]
    for p in patterns:
        dir_only = p.endswith("/")
        pat = p.strip("/")
        if dir_only and not is_dir:
            continue
        if p.startswith("/") or "/" in pat:
            if fnmatch.fnmatch(rel, pat):
                return True
        elif fnmatch.fnmatch(name, pat):
            return True
    return False


def _glob_match(rel: str, pattern: str) -> bool:
    if fnmatch.fnmatch(rel, pattern):
        return True
    if pattern.startswith("**/"):
        return fnmatch.fnmatch(rel, pattern[3:]) or fnmatch.fnmatch(rel.rsplit("/", 1)[-1], pattern[3:])
    return False


def walk_project(root: str | Path, include: list[str] | None = None, exclude: list[str] | None = None,
                 max_file_size: int = DEFAULT_MAX_FILE_SIZE) -> list[ProjectFile]:
    root = Path(root).resolve()
    ignore = _load_gitignore(root)
    out: list[ProjectFile] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = sorted(d for d in dirnames
                             if d not in DEFAULT_SKIP_DIRS and not _gitignored(rel_dir + d, True, ignore)
                             and not os.path.islink(os.path.join(dirpath, d)))
        for fn in sorted(filenames):
            full = Path(dirpath) / fn
            rel = rel_dir + fn
            if full.is_symlink() or _gitignored(rel, False, ignore):
                continue
            if include and not any(_glob_match(rel, p) for p in include):
                continue
            if exclude and any(_glob_match(rel, p) for p in exclude):
                continue
            try:
                if full.stat().st_size > max_file_size:
                    continue
            except OSError:
                continue
            if _is_binary(full):
                continue
            out.append(ProjectFile(rel, full))
    return out


def count_loc(files: list[ProjectFile]) -> int:
    total = 0
    for f in files:
        if f.suffix in (".kt", ".kts", ".java", ".yml", ".yaml", ".properties", ".toml", ".gradle", ".xml", ".sql"):
            total += sum(1 for line in f.read_text().splitlines() if line.strip())
    return total


def safe_file(root: str | Path, rel: str | Path) -> Path | None:
    """Path of a regular file under `root`, or None if it escapes the root, traverses a symlink or is missing."""
    root_resolved = Path(root).resolve()
    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        return None
    current = root_resolved
    for part in rel_path.parts:
        current = current / part
        if current.is_symlink():
            return None
    try:
        resolved = current.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_file() or (root_resolved not in resolved.parents and resolved != root_resolved):
        return None
    return resolved

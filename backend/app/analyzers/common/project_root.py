"""Where the checked project starts inside a repository or archive.

Organizer requirement: finding ``path`` is relative to the root of the checked project (``src/main/kotlin/…``), not to
the repository that contains it (``training-project/src/main/kotlin/…``). People hand over a whole repository, a
GitHub «Download ZIP» or a folder, so the Gradle project root is detected instead of assumed."""

from __future__ import annotations

from collections import deque
from pathlib import Path

SETTINGS_FILES = ("settings.gradle.kts", "settings.gradle")
BUILD_FILES = ("build.gradle.kts", "build.gradle")
SKIP_DIRS = {"node_modules", "build", "out", "target", "dist", "vendor", "__pycache__", "venv"}
MAX_DEPTH = 4
CODE_SUFFIXES = {".kt", ".kts", ".java"}


def _has(directory: Path, names: tuple[str, ...]) -> bool:
    return any((directory / n).is_file() for n in names)


def detect_project_root(root: str | Path) -> tuple[str | None, list[str]]:
    """``(subdir, candidates)``: the relative path of the single Gradle project below ``root``, or ``None`` when
    ``root`` already is a project, nothing Gradle-like is found, or several unrelated projects exist (then
    ``candidates`` lists them so the caller can tell the person to pick one)."""
    base = Path(root)
    if _has(base, SETTINGS_FILES + BUILD_FILES):
        return None, []
    found: list[tuple[Path, bool]] = []  # (directory, has settings.gradle*)
    queue: deque[tuple[Path, int]] = deque([(base, 0)])
    while queue:
        directory, depth = queue.popleft()
        if depth >= MAX_DEPTH:
            continue
        try:
            children = sorted(p for p in directory.iterdir() if p.is_dir() and not p.is_symlink())
        except OSError:
            continue
        for child in children:
            if child.name.startswith(".") or child.name in SKIP_DIRS:
                continue
            if _has(child, SETTINGS_FILES):
                found.append((child, True))
            elif _has(child, BUILD_FILES):
                found.append((child, False))
            else:
                queue.append((child, depth + 1))  # a project's own subprojects are not separate candidates
    with_settings = [d for d, s in found if s]
    pool = with_settings or [d for d, _ in found]
    candidates = sorted(d.relative_to(base).as_posix() for d in pool)
    if len(candidates) == 1 and not _code_outside(base, pool[0]):
        return candidates[0], candidates
    return None, candidates


def _code_outside(base: Path, project: Path) -> bool:
    """Kotlin/Java sources outside the found project mean it is a sample or a tool, not the code under check."""
    for p in base.rglob("*"):
        if p.suffix not in CODE_SUFFIXES or p.name in SETTINGS_FILES + BUILD_FILES or not p.is_file():
            continue  # Gradle build scripts of sibling tools are not code under check
        rel = p.relative_to(base).parts
        if any(part.startswith(".") or part in SKIP_DIRS for part in rel[:-1]):
            continue
        if not p.is_relative_to(project):
            return True
    return False

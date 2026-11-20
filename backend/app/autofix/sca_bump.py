"""Deterministic SCA AutoFix (12A.3): bump to the nearest fixed version of the branch at the place where the version
is defined — string literal, ``val``, ``gradle.properties``, version catalog, ``extra`` — plus the lockfile entry.

The definition sites come from the SCA analyzer (``alternate_locations`` + the dependency line), so the bump edits
exactly what the analyzer resolved. A shared version variable bumps every dependency using it (said in the note).
"""

from __future__ import annotations

import re
from pathlib import Path

from app.analyzers.common.finding import Finding
from app.analyzers.sca.versions import compare_versions, is_supported, nearest_fixed_version
from app.autofix.context import read_text
from app.autofix.validator import FileEdit

LOCK_NOTE = "перегенерируйте локи: ./gradlew dependencies --write-locks"


class BumpError(ValueError):
    pass


def _token(value: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w.\-+])" + re.escape(value) + r"(?![\w.\-+])")


def _bump_line(line: str, old: str, new: str) -> str | None:
    if line.lstrip().startswith(("//", "#")):
        return None
    m = _token(old).search(line)
    return line[: m.start()] + new + line[m.end():] if m else None


def plan_bump(root: Path, f: Finding) -> tuple[str, list[FileEdit], dict]:
    if f.category != "SCA" or not f.group or not f.artifact or not f.version:
        raise BumpError("детерминированный bump применим только к SCA-находкам")
    fix = nearest_fixed_version(f.version, f.fixed_versions)
    if fix is None:
        raise BumpError(f"в справочнике нет исправленной версии для {f.group}:{f.artifact}:{f.version}")
    texts: dict[str, list[str]] = {}
    changed: dict[str, set[int]] = {}

    def lines_of(rel: str) -> list[str] | None:
        if rel not in texts:
            t = read_text(root, rel)
            if t is None:
                return None
            texts[rel] = t.splitlines(keepends=True)
        return texts[rel]

    declared = f.declared_version
    sites = []
    if declared and is_supported(declared) and compare_versions(declared, fix) < 0:
        sites = [(loc.path, loc.line) for loc in f.alternate_locations if not loc.path.endswith("gradle.lockfile")]
        sites.append((f.path, f.line))
        for rel, line in sites:
            lines = lines_of(rel)
            if lines is None or not (1 <= line <= len(lines)) or line in changed.get(rel, set()):
                continue
            new = _bump_line(lines[line - 1], declared, fix)
            if new is not None:
                lines[line - 1] = new
                changed.setdefault(rel, set()).add(line)
        if not changed:
            raise BumpError(f"место определения версии {declared} не найдено ({f.version_source})")
    lock_note = None
    lock = lines_of("gradle.lockfile")
    if lock is not None:
        prefix = f"{f.group}:{f.artifact}:"
        for i, ln in enumerate(lock):
            if ln.startswith(prefix) and "=" in ln:
                ver = ln[len(prefix):].split("=", 1)[0]
                if is_supported(ver) and compare_versions(ver, fix) < 0:
                    lock[i] = prefix + fix + "=" + ln.split("=", 1)[1]
                    changed.setdefault("gradle.lockfile", set()).add(i + 1)
                    lock_note = LOCK_NOTE
    if not changed:
        raise BumpError("нечего менять: версия уже не ниже исправленной")
    edits = [FileEdit(rel, read_text(root, rel) or "", "".join(texts[rel])) for rel in sorted(changed)]
    shared = f.version_source and f.version_source.startswith(("variable:", "gradle.properties:", "extra:", "catalog"))
    explanation = (f"{f.group}:{f.artifact} {f.version} → {fix} (ближайшая исправленная версия ветки для "
                   f"{f.advisory_id}); версия изменена в месте определения ({f.version_source or 'literal'})"
                   + ("; переменная может использоваться и другими зависимостями" if shared else "")
                   + (f"; {lock_note}" if lock_note else "") + ".")
    proposal = {"kind": "deterministic", "fix_version": fix, "files": sorted(changed),
                "lines": {k: sorted(v) for k, v in changed.items()}, "explanation": explanation,
                "requires_config": [], "notes": [lock_note] if lock_note else []}
    return fix, edits, proposal

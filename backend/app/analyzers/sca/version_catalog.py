"""Gradle version catalog (`gradle/libs.versions.toml`) support."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from app.analyzers.common.files import safe_file


@dataclass
class CatalogLibrary:
    alias: str
    group: str
    artifact: str
    version: str | None
    version_ref: str | None
    line: int


@dataclass
class VersionCatalog:
    path: str
    libraries: dict[str, CatalogLibrary]
    versions: dict[str, tuple[str, int]]

    def by_accessor(self, accessor: str) -> CatalogLibrary | None:
        """`libs.commons.text` → alias `commons-text` / `commons_text` / `commons.text`."""
        key = accessor.replace("_", ".").replace("-", ".")
        for alias, lib in self.libraries.items():
            if alias.replace("_", ".").replace("-", ".") == key:
                return lib
        return None


def _find_line(lines: list[str], section: str, key: str) -> int:
    in_section = False
    for i, line in enumerate(lines, start=1):
        s = line.strip()
        if s.startswith("["):
            in_section = s == f"[{section}]"
            continue
        if in_section and (s.startswith(f"{key} ") or s.startswith(f"{key}=") or s.startswith(f'"{key}"')):
            return i
    return 1


def load_catalog(root: Path, rel: str = "gradle/libs.versions.toml") -> VersionCatalog | None:
    path = safe_file(root, rel)
    if path is None:
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    lines = text.splitlines()
    versions: dict[str, tuple[str, int]] = {}
    for k, v in (data.get("versions") or {}).items():
        if isinstance(v, str):
            versions[k] = (v, _find_line(lines, "versions", k))
        elif isinstance(v, dict) and isinstance(v.get("strictly") or v.get("require") or v.get("prefer"), str):
            versions[k] = (v.get("strictly") or v.get("require") or v.get("prefer"), _find_line(lines, "versions", k))
    libs: dict[str, CatalogLibrary] = {}
    for alias, spec in (data.get("libraries") or {}).items():
        group = artifact = version = ref = None
        if isinstance(spec, str):
            parts = spec.split(":")
            if len(parts) >= 2:
                group, artifact = parts[0], parts[1]
                version = parts[2] if len(parts) > 2 else None
        elif isinstance(spec, dict):
            if "module" in spec:
                group, _, artifact = str(spec["module"]).partition(":")
            else:
                group, artifact = spec.get("group"), spec.get("name")
            v = spec.get("version")
            if isinstance(v, str):
                version = v
            elif isinstance(v, dict):
                ref = v.get("ref")
                version = v.get("strictly") or v.get("require") or v.get("prefer")
            ref = ref or spec.get("version.ref")
        if group and artifact:
            libs[alias] = CatalogLibrary(alias, group, artifact, version, ref, _find_line(lines, "libraries", alias))
    return VersionCatalog(rel, libs, versions)

"""`gradle.lockfile` reader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class LockEntry:
    group: str
    artifact: str
    version: str
    configurations: list[str]
    line: int


def read_lockfile(path: Path | None) -> dict[tuple[str, str], LockEntry]:
    out: dict[tuple[str, str], LockEntry] = {}
    if path is None or not path.is_file():
        return out
    for i, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("empty="):
            continue
        coords, _, confs = line.partition("=")
        parts = coords.split(":")
        if len(parts) != 3:
            continue
        g, a, v = parts
        out[(g, a)] = LockEntry(g, a, v, [c for c in confs.split(",") if c], i)
    return out

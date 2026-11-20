"""`gradle.properties` reader with line numbers."""

from __future__ import annotations

from pathlib import Path


def read_properties(path: Path | None) -> dict[str, tuple[str, int]]:
    out: dict[str, tuple[str, int]] = {}
    if path is None or not path.is_file():
        return out
    for i, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(("#", "!")):
            continue
        for sep in ("=", ":"):
            if sep in line:
                k, v = line.split(sep, 1)
                out[k.strip()] = (v.strip(), i)
                break
    return out

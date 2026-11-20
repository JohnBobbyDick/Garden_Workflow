"""Version comparison for the `numeric-dot-separated` format of the vulnerability snapshot.

Only purely numeric dot-separated versions are in scope. Qualified (`-SNAPSHOT`, `.RELEASE`, `-rc1`),
dynamic (`1.+`, `[1,2)`, `latest.release`) and empty versions raise ``UnsupportedVersion`` so callers can
emit an informational note instead of a finding.
"""

from __future__ import annotations

import re

_NUMERIC = re.compile(r"^[0-9]+(\.[0-9]+)*$")


class UnsupportedVersion(ValueError):
    """Version cannot be compared within the numeric-dot-separated snapshot format."""


def parse_version(raw: str) -> tuple[int, ...]:
    value = (raw or "").strip()
    if not _NUMERIC.match(value):
        raise UnsupportedVersion(f"version {raw!r} is outside numeric-dot-separated format")
    parts = [int(p) for p in value.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def is_supported(raw: str) -> bool:
    try:
        parse_version(raw)
    except UnsupportedVersion:
        return False
    return True


def compare_versions(a: str, b: str) -> int:
    pa, pb = parse_version(a), parse_version(b)
    width = max(len(pa), len(pb))
    pa += (0,) * (width - len(pa))
    pb += (0,) * (width - len(pb))
    return (pa > pb) - (pa < pb)


def in_range(version: str, rng: dict) -> bool:
    lower, upper = rng.get("lower"), rng.get("upper")
    if lower is not None:
        c = compare_versions(version, lower)
        if c < 0 or (c == 0 and not rng.get("lowerInclusive", False)):
            return False
    if upper is not None:
        c = compare_versions(version, upper)
        if c > 0 or (c == 0 and not rng.get("upperInclusive", False)):
            return False
    return True


def is_vulnerable(version: str, ranges: list[dict]) -> bool:
    return any(in_range(version, r) for r in ranges)


def nearest_fixed_version(version: str, fixed_versions: list[str]) -> str | None:
    """Smallest fixed version strictly greater than the current version (closest upgrade of the branch)."""
    candidates = [f for f in fixed_versions if is_supported(f) and compare_versions(f, version) > 0]
    if not candidates:
        return None
    best = candidates[0]
    for c in candidates[1:]:
        if compare_versions(c, best) < 0:
            best = c
    return best

"""Helpers shared by the export formats: ordering, path checks, labels and location strings."""

from __future__ import annotations

import re
from collections import Counter

from app.analyzers.common.finding import SEVERITY_ORDER, Finding

CATEGORY_ORDER: tuple[str, ...] = ("SECRET", "SAST", "SCA")
SEVERITY_LEVELS: tuple[str, ...] = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
MAX_RANGE_LINES = 15

CATEGORY_TITLES: dict[str, str] = {
    "SECRET": "Секреты (SECRET)",
    "SAST": "Уязвимости кода (SAST)",
    "SCA": "Уязвимые зависимости (SCA)",
}

SEVERITY_TITLES: dict[str, str] = {
    "CRITICAL": "критическая",
    "HIGH": "высокая",
    "MEDIUM": "средняя",
    "LOW": "низкая",
}

DESCRIPTION_LIMIT = 300

_WHITESPACE = re.compile(r"\s+")


def path_problem(path: object) -> str | None:
    """Return a human-readable reason why ``path`` is not a valid relative project path, or None."""
    if not isinstance(path, str):
        return "должен быть строкой"
    if not path.strip():
        return "не должен быть пустым"
    if path.startswith(("/", "\\")):
        return "абсолютные пути недопустимы"
    if ":" in path:
        return "буквы дисков и двоеточие недопустимы"
    if ".." in re.split(r"[\\/]", path):
        return "компонент '..' недопустим"
    return None


def normalize_path(path: str) -> str:
    """Use forward slashes and drop leading './' segments."""
    out = path.replace("\\", "/")
    while out.startswith("./"):
        out = out[2:]
    return out


def sort_key(f: Finding) -> tuple:
    """Stable order: category, path, then coordinates (line range or Maven coordinates + advisory)."""
    cat = CATEGORY_ORDER.index(f.category) if f.category in CATEGORY_ORDER else len(CATEGORY_ORDER)
    path = normalize_path(f.path)
    if f.category == "SCA":
        coords: tuple = (0, 0, f.group or "", f.artifact or "", f.version or "", f.advisory_id or "")
    else:
        coords = (f.line, f.end_line or f.line, f.cls, "", "", "")
    return (cat, path, *coords, f.rule_id)


def report_order(findings: list[Finding]) -> list[Finding]:
    """Order for readable reports: category, most severe first, then the stable submission order."""
    return sorted(findings, key=lambda f: (sort_key(f)[0], -SEVERITY_ORDER[f.severity], sort_key(f)))


def has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def one_line(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def shorten(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    flat = one_line(text)
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"


def coordinates(f: Finding) -> str:
    return f"{f.group or '?'}:{f.artifact or '?'}:{f.version or '?'}"


def location(f: Finding) -> str:
    """file:line or file:line-endLine for SECRET/SAST; declaration file for SCA."""
    path = normalize_path(f.path)
    if f.category == "SCA":
        return path
    end = f.end_line or f.line
    return f"{path}:{f.line}" if end == f.line else f"{path}:{f.line}-{end}"


def secret_display(f: Finding) -> str:
    """Masked representation of a secret: only already-masked fields are used."""
    if has_text(f.masked_value):
        return one_line(f.masked_value or "")
    return one_line(f.snippet)


def severity_label(severity: str) -> str:
    return f"{severity} ({SEVERITY_TITLES.get(severity, severity.lower())})"


def summary(findings: list[Finding]) -> tuple[Counter, Counter]:
    by_category = Counter(f.category for f in findings)
    by_severity = Counter(f.severity for f in findings)
    return by_category, by_severity

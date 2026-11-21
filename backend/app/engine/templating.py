"""Safe message templates: ``{{dotted.path}}`` substitution from a prepared context, nothing else.

The context is built from findings summaries (already masked), score, verdict, run url and AI summary; credential
values are never part of it, and the rendered text is additionally passed through the run masker by callers."""

from __future__ import annotations

import re
from typing import Any

from app.engine.expressions import _MISSING, resolve_path

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*\}\}")


def _fmt(v: Any) -> str:
    if v is None or v is _MISSING:
        return ""
    if isinstance(v, bool):
        return "да" if v else "нет"
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, list):
        return ", ".join(_fmt(x) for x in v)
    if isinstance(v, dict):
        return ", ".join(f"{k}: {_fmt(x)}" for k, x in v.items())
    return str(v)


def render_template(template: str, ctx: dict[str, Any], *, max_length: int | None = None) -> str:
    size = 0
    end = 0

    def substitute(match: re.Match[str]) -> str:
        nonlocal size, end
        value = _fmt(resolve_path(ctx, match.group(1)))
        size += match.start() - end + len(value)
        end = match.end()
        if max_length is not None and size > max_length:
            raise ValueError("Текст превышает лимит длины шаблона.")
        return value

    result = _PLACEHOLDER.sub(substitute, template)
    if max_length is not None and len(result) > max_length:
        raise ValueError("Текст превышает лимит длины шаблона.")
    return result

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


def render_template(template: str, ctx: dict[str, Any]) -> str:
    return _PLACEHOLDER.sub(lambda m: _fmt(resolve_path(ctx, m.group(1))), template)

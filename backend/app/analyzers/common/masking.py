"""Secret value masking primitives. Raw secret values are never stored: only fingerprint + mask."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable


def mask_value(value: str) -> str:
    n = len(value)
    if n < 8:
        return f"…(len={n})"
    return f"{value[:2]}…(len={n})"


def fingerprint(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"sha256:{digest}:{len(value)}"


def mask_in_text(text: str, values: Iterable[str]) -> str:
    # longest first so that a value containing another value is masked as a whole
    for v in sorted({v for v in values if v and len(v) >= 4}, key=len, reverse=True):
        text = text.replace(v, mask_value(v))
    return text

"""Shannon entropy and character-class helpers for the unknown-secret heuristic."""

from __future__ import annotations

import math
import string
from collections import Counter

HEX = set(string.hexdigits)
B64 = set(string.ascii_letters + string.digits + "+/=_-")


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    n = len(value)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def char_classes(value: str) -> int:
    classes = 0
    classes += any(c.islower() for c in value)
    classes += any(c.isupper() for c in value)
    classes += any(c.isdigit() for c in value)
    classes += any(not c.isalnum() for c in value)
    return classes


def alphabet(value: str) -> str:
    s = set(value)
    if s <= HEX:
        return "hex"
    if s <= B64:
        return "base64"
    return "mixed"


def entropy_threshold_for(value: str, base: float) -> float:
    """Hex strings have a lower maximum entropy (4 bits/char) than base64 (6 bits/char)."""
    kind = alphabet(value)
    if kind == "hex":
        return base - 0.8
    return base

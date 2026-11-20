"""Central secret masker for logs, run events, errors, API responses, prompts, reports and notifications.

Known values (credential plaintexts, secret config values of a run) are registered explicitly; well-known
token shapes are masked by pattern even when nobody registered them."""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

from app.analyzers.common.masking import mask_value

MIN_SECRET_LEN = 4
MASK = "••••"

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"),
]
# group 1 is kept, group 2 is masked
_KEEP_PREFIX: list[re.Pattern[str]] = [
    re.compile(r"(\b[a-z][a-z0-9+.\-]{1,20}://[^\s:/@'\"]{1,64}:)([^\s@/'\"]{1,128})(?=@)"),
    re.compile(r"(\b(?:Bearer|Basic|token)\s+)([A-Za-z0-9._~+/=\-]{12,})", re.I),
    re.compile(r"((?:password|passwd|pwd|secret|token|api[_-]?key)[\"']?\s*[=:]\s*[\"']?)([^\s\"'&,;]{4,})", re.I),
]


def _already_masked(s: str) -> bool:
    return s.startswith(("•", "…")) or "…(len=" in s


def mask_tail(value: str) -> str:
    """API display of a stored secret: ``••••`` + last 2–4 characters (nothing for short values)."""
    if len(value) < 10:
        return MASK
    keep = 4 if len(value) >= 14 else 2
    return MASK + value[-keep:]


class Masker:
    def __init__(self) -> None:
        self._values: set[str] = set()
        self._lock = threading.Lock()

    def register(self, *values: str | None) -> None:
        with self._lock:
            for v in values:
                if isinstance(v, str) and len(v.strip()) >= MIN_SECRET_LEN:
                    self._values.add(v)
                    self._values.add(v.strip())

    def child(self) -> Masker:
        """A masker that knows everything this one knows plus what is registered on it later."""
        m = Masker()
        with self._lock:
            m._values = set(self._values)
        return m

    def mask_known(self, text: str) -> str:
        """Registered values + token shapes only, without the ``password=…`` heuristics: for validated code
        (AutoFix new_snippet) where ``val password: String`` is a type annotation, not a secret."""
        if not text:
            return text
        with self._lock:
            values = sorted(self._values, key=len, reverse=True)
        for v in values:
            if v in text:
                text = text.replace(v, mask_value(v))
        for p in _PATTERNS:
            text = p.sub(lambda m: mask_value(m.group(0)), text)
        return text

    def mask(self, text: str) -> str:
        if not text:
            return text
        text = self.mask_known(text)
        for p in _KEEP_PREFIX:
            text = p.sub(lambda m: m.group(1) + (m.group(2) if _already_masked(m.group(2)) else mask_value(m.group(2))),
                         text)
        return text

    def mask_obj(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.mask(obj)
        if isinstance(obj, dict):
            return {k: self.mask_obj(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self.mask_obj(v) for v in obj]
        return obj


global_masker = Masker()


class MaskingLogFilter(logging.Filter):
    """Masks application log records with the global masker (installed on the root logger at startup)."""

    def filter(self, record: logging.LogRecord) -> bool:
        # mask in place, keeping the args structure (formatters such as uvicorn's unpack record.args)
        if isinstance(record.msg, str):
            record.msg = global_masker.mask(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_mask_arg(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: _mask_arg(v) for k, v in record.args.items()}
        return True


def _mask_arg(a: Any) -> Any:
    """Strings are masked; numbers stay numbers (for %d); other objects (e.g. httpx.URL) are replaced by their
    masked string form only when it differs, so formatting keeps working."""
    if isinstance(a, str):
        return global_masker.mask(a)
    if a is None or isinstance(a, (int, float, bool)):
        return a
    text = str(a)
    masked = global_masker.mask(text)
    return masked if masked != text else a

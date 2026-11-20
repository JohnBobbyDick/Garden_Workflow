"""Export findings into the organizer submission JSON format (``{"findings": [...]}``)."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.analyzers.common.finding import Finding
from app.export.common import MAX_RANGE_LINES, has_text, normalize_path, path_problem, sort_key

logger = logging.getLogger(__name__)

# Default confidence threshold of the official export (docs/ANALYZERS.md): entropy heuristics (0.45) and findings
# in test/doc paths (x0.55–0.6) stay visible in the UI as low-confidence but are not exported.
OFFICIAL_MIN_CONFIDENCE = 0.6


def _skip_reason(f: Finding, path: str) -> str | None:
    problem = path_problem(path)
    if problem:
        return f"path {path!r}: {problem}"
    if f.category == "SCA":
        for name in ("group", "artifact", "version", "advisory_id"):
            if not has_text(getattr(f, name)):
                return f"SCA finding without {name}"
        return None
    if not has_text(f.cls):
        return "finding without class"
    return None


def _finding_to_item(f: Finding, path: str) -> dict[str, Any]:
    item: dict[str, Any] = {"category": f.category, "path": path}
    if f.category == "SCA":
        item["group"] = (f.group or "").strip()
        item["artifact"] = (f.artifact or "").strip()
        item["version"] = (f.version or "").strip()
        item["advisoryId"] = (f.advisory_id or "").strip()
    else:
        item["class"] = f.cls.strip()
        line = max(int(f.line), 1)
        item["line"] = line
        end = f.end_line
        if end is not None:
            end = min(max(int(end), line), line + MAX_RANGE_LINES - 1)
            if end != line:
                item["endLine"] = end
    item["severity"] = f.severity
    if has_text(f.description):
        item["description"] = f.description.strip()
    if has_text(f.remediation):
        item["remediation"] = f.remediation.strip()
    return item


def to_submission(findings: list[Finding], min_confidence: float = 0.0,
                  include_transitive: bool = False) -> dict[str, list[dict[str, Any]]]:
    """Build the official submission document.

    Findings below `min_confidence` and transitive dependencies (unless requested) are not part of the official
    export. Findings that cannot be expressed validly are skipped and logged."""
    items: list[dict[str, Any]] = []
    for f in sorted(findings, key=sort_key):
        if f.confidence < min_confidence or (f.scope == "transitive" and not include_transitive):
            continue
        path = normalize_path(f.path)
        reason = _skip_reason(f, path)
        if reason:
            logger.warning("submission export: skipping finding %s: %s", f.id, reason)
            continue
        items.append(_finding_to_item(f, path))
    return {"findings": items}


def dumps_submission(findings: list[Finding], min_confidence: float = 0.0, include_transitive: bool = False) -> str:
    """Serialize the submission document as UTF-8-friendly JSON text (no ASCII escaping)."""
    doc = to_submission(findings, min_confidence=min_confidence, include_transitive=include_transitive)
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"

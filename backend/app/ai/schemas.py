"""JSON schemas of LLM answers (strict contracts validated before anything is stored or shown)."""

from __future__ import annotations

FIX_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "start_line": {"type": "integer", "minimum": 1},
        "end_line": {"type": "integer", "minimum": 1},
        "before": {"type": "string"},
        "after": {"type": "string"},
    },
    "required": ["path", "start_line", "end_line", "before", "after"],
}

REPORT_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "finding_id": {"type": "string"},
        "explanation": {"type": "string"},
        "impact": {"type": "string"},
        "remediation_steps": {"type": "array", "items": {"type": "string"}},
        "safe_version": {"type": ["string", "null"]},
        "fix": {"anyOf": [FIX_SCHEMA, {"type": "null"}]},
    },
    "required": ["finding_id", "explanation", "impact", "remediation_steps"],
}

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "priority_order": {"type": "array", "items": {"type": "string"}},
        "findings": {"type": "array", "items": REPORT_ITEM_SCHEMA},
        "global_recommendations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "priority_order", "findings", "global_recommendations"],
}

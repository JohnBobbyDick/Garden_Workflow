"""Helpers for the data carried between nodes: findings envelopes and the expression/template context."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.analyzers.common.finding import SEVERITY_ORDER, Finding
from app.engine.context import RunInfo
from app.nodes.base import Envelope

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


def finding_dict(f: Finding) -> dict[str, Any]:
    return f.model_dump(by_alias=True, mode="json", exclude_none=True)


def findings_envelope(findings: list[Finding], node_id: str, summary: str | None = None,
                      extra: dict[str, Any] | None = None) -> Envelope:
    data: dict[str, Any] = {"findings": [finding_dict(f) for f in findings]}
    if extra:
        data.update(extra)
    return Envelope.make("findings", data, node_id, summary if summary is not None else findings_summary(findings))


def findings_of(env: Envelope | list[Envelope] | None) -> list[Finding]:
    if env is None:
        return []
    envs = env if isinstance(env, list) else [env]
    out: list[Finding] = []
    seen: set[str] = set()
    for e in envs:
        for raw in e.data.get("findings", []) if e.type in ("findings", "any") or "findings" in e.data else []:
            f = Finding.model_validate(raw)
            if f.id not in seen:
                seen.add(f.id)
                out.append(f)
    return out


def flatten_inputs(inputs: dict[str, Any]) -> list[Envelope]:
    out: list[Envelope] = []
    for v in inputs.values():
        out.extend(v if isinstance(v, list) else [v])
    return out


def severity_counts(findings: list[Finding]) -> dict[str, int]:
    c = Counter(f.severity for f in findings)
    return {s.lower(): c.get(s, 0) for s in SEVERITIES}


def max_severity(findings: list[Finding]) -> str | None:
    if not findings:
        return None
    return max(findings, key=lambda f: SEVERITY_ORDER[f.severity]).severity


def findings_summary(findings: list[Finding]) -> str:
    if not findings:
        return "находок нет"
    c = severity_counts(findings)
    parts = [f"{k.upper()} {v}" for k, v in c.items() if v]
    return f"найдено {len(findings)} ({', '.join(parts)})"


def summary_dict(findings: list[Finding]) -> dict[str, Any]:
    return {
        "total": len(findings),
        "by_severity": {s: c for s, c in Counter(f.severity for f in findings).items()},
        "by_category": dict(Counter(f.category for f in findings)),
        "max_severity": max_severity(findings),
    }


def build_context(inputs: dict[str, Any], run: RunInfo, state: dict[str, Any]) -> dict[str, Any]:
    """Context for ``logic.if_else`` expressions and message templates. Only masked/derived data, no secrets."""
    envs = flatten_inputs(inputs)
    findings = findings_of([e for e in envs if "findings" in e.data])
    data: dict[str, Any] = {}
    report: dict[str, Any] = {}
    for e in envs:
        if e.type == "json":
            data.update(e.data)
        if e.type == "report":
            report.update(e.data)
        if e.type == "text":
            data.setdefault("text", e.data.get("text", ""))
    verdict_info = state.get("verdict") or (data if "verdict" in data else {})
    sev = severity_counts(findings)
    categories = sorted({f.category for f in findings})
    score = state.get("score") or {}
    new_count = verdict_info.get("new_count")
    if new_count is None and isinstance(verdict_info.get("new_counts_by_severity"), dict):
        new_count = sum(verdict_info["new_counts_by_severity"].values())
    return {
        "findings": {"count": len(findings), **{k: v for k, v in sev.items()}},
        "severity": {"max": max_severity(findings), **sev},
        "categories": categories,
        "category": categories,
        "classes": sorted({f.cls for f in findings}),
        "new_findings": {"count": new_count if new_count is not None else len(findings)},
        "existing_findings": {"count": verdict_info.get("existing_count", 0)},
        "verdict": verdict_info.get("verdict"),
        "gate": state.get("gate"),
        "score": {"value": score.get("value"), "delta": score.get("delta")},
        "ai": {"summary": (state.get("ai") or {}).get("summary", ""),
               "generated": (state.get("ai") or {}).get("ai_generated")},
        "run": {"id": run.run_id, "url": run.run_url, "trigger": run.trigger_type},
        "project": {"name": run.project_name or (state.get("repo") or {}).get("project_name", "")},
        "workflow": {"name": run.workflow_name},
        "report": report,
        "data": data,
    }

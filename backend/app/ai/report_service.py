"""AI report generation: batching, one repair attempt, validation, deterministic fill/fallback (never silent)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.ai.deterministic import deterministic_item, deterministic_report, ordered
from app.ai.prompts import build_messages, finding_payload, repair_messages
from app.ai.providers.base import LLMError, LLMProvider
from app.ai.schemas import REPORT_SCHEMA
from app.ai.validator import AIFormatError, FileReader, ValidationLog, parse_json, validate_report
from app.analyzers.common.finding import Finding
from app.core.masking import Masker

logger = logging.getLogger(__name__)
DEFAULT_BATCH_CHARS = 14_000
METRIC_SUMS = ("total_items", "valid_items", "dropped", "duplicates", "fixes_kept", "fixes_dropped",
               "safe_version_corrected", "bad_references", "covered_findings", "input_findings")


@dataclass
class ReportOutcome:
    report: dict[str, Any]
    ai_generated: bool
    validation: dict[str, Any]
    provider: str | None = None
    model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    language: str = "ru"


def batches(findings: list[Finding], read: FileReader, limit: int) -> list[list[Finding]]:
    out: list[list[Finding]] = [[]]
    size = 0
    for f in findings:
        n = len(json.dumps(finding_payload(f, read), ensure_ascii=False))
        if out[-1] and size + n > limit:
            out.append([])
            size = 0
        out[-1].append(f)
        size += n
    return [b for b in out if b]


async def _one_batch(provider: LLMProvider, batch: list[Finding], read: FileReader, allowed_ids: set[str],
                     masker: Masker, language: str, project: str, gen_fix: bool, usage: dict[str, int]
                     ) -> tuple[dict, ValidationLog, int]:
    messages = build_messages(batch, read, language, project, gen_fix)
    messages = [{"role": m["role"], "content": masker.mask(m["content"])} for m in messages]
    repairs = 0
    error = ""
    for attempt in range(2):
        res = await provider.chat(messages, response_schema=REPORT_SCHEMA, temperature=0.2, max_tokens=4096)
        for k, v in res.usage.items():
            usage[k] = usage.get(k, 0) + v
        try:
            data = parse_json(res.content)
            if not gen_fix:
                for it in data.get("findings", []) if isinstance(data.get("findings"), list) else []:
                    if isinstance(it, dict):
                        it.pop("fix", None)
            report, log = validate_report(data, batch, read, allowed_ids)
            return report, log, repairs
        except AIFormatError as exc:
            error = str(exc)
            if attempt == 0:
                repairs += 1
                messages = repair_messages(messages, masker.mask(res.content), error, language)
    raise AIFormatError(f"ответ LLM невалиден после повторной попытки: {error}")


def _merge(parts: list[tuple[dict, ValidationLog]], repairs: int) -> tuple[dict, dict]:
    report = {"summary": parts[0][0]["summary"] if len(parts) == 1 else "", "priority_order": [],
              "findings": [], "global_recommendations": []}
    checks: list[dict] = []
    metrics: dict[str, Any] = dict.fromkeys(METRIC_SUMS, 0)
    metrics.update({"unknown_ids": [], "hallucinated_ids": []})
    flags = {"hallucinated_ids": False, "corrected": False}
    for i, (rep, log) in enumerate(parts):
        report["priority_order"] += rep["priority_order"]
        report["findings"] += rep["findings"]
        for g in rep["global_recommendations"]:
            if g not in report["global_recommendations"]:
                report["global_recommendations"].append(g)
        checks += [{**c, "batch": i + 1} for c in log.checks]
        for k in METRIC_SUMS:
            metrics[k] += log.metrics.get(k, 0)
        metrics["unknown_ids"] += log.metrics.get("unknown_ids", [])
        metrics["hallucinated_ids"] += log.metrics.get("hallucinated_ids", [])
        for k in flags:
            flags[k] = flags[k] or log.flags.get(k, False)
    if len(parts) > 1:
        # Batch summaries describe only their own inputs. Use validated explanations for the leading risks.
        explanations = {item["finding_id"]: item["explanation"] for item in report["findings"]}
        ranked = [explanations[fid] for fid in report["priority_order"] if explanations.get(fid)]
        report["summary"] = "\n".join(ranked[:3])
    metrics["repair_attempts"] = repairs
    metrics["batches"] = len(parts)
    return report, {"checks": checks, "metrics": metrics, "flags": flags}


async def generate_report(findings: list[Finding], provider: LLMProvider | None, *, read: FileReader,
                          allowed_ids: set[str], masker: Masker, language: str = "ru", generate_fix_diff: bool = True,
                          fallback: bool = True, project: str = "project", max_findings: int = 60,
                          batch_chars: int = DEFAULT_BATCH_CHARS) -> ReportOutcome:
    lang = language if language in ("ru", "en") else "ru"
    if provider is None:
        if not fallback:
            raise LLMError("AI-провайдер не настроен в рабочем пространстве")
        return ReportOutcome(deterministic_report(findings, lang), False,
                             {"checks": [{"check": "provider", "status": "skipped",
                                          "details": "AI-провайдер не настроен — детерминированный отчёт"}],
                              "metrics": {"input_findings": len(findings)}, "flags": {}},
                             error="AI-провайдер не настроен", language=lang)
    selected = ordered(findings)[:max_findings]
    usage: dict[str, int] = {}
    try:
        parts = []
        repairs = 0
        for batch in batches(selected, read, batch_chars):
            rep, log, r = await _one_batch(provider, batch, read, allowed_ids, masker, lang, project,
                                           generate_fix_diff, usage)
            parts.append((rep, log))
            repairs += r
    except (LLMError, AIFormatError) as exc:
        msg = masker.mask(str(exc))
        logger.warning("AI report failed: %s", msg)
        if not fallback:
            raise LLMError(msg) from exc
        return ReportOutcome(deterministic_report(findings, lang), False,
                             {"checks": [{"check": "provider", "status": "failed", "details": msg}],
                              "metrics": {"input_findings": len(findings)}, "flags": {}},
                             provider=provider.name, model=provider.cfg.model, usage=usage, error=msg, language=lang)
    report, validation = _merge(parts, repairs)
    covered = {i["finding_id"] for i in report["findings"]}
    missing = [f for f in ordered(findings) if f.id not in covered]
    report["findings"] += [deterministic_item(f, lang) for f in missing]
    report["priority_order"] += [f.id for f in missing if f.id not in report["priority_order"]]
    validation["metrics"]["filled_deterministic"] = len(missing)
    if missing:
        validation["checks"].append({"check": "coverage", "status": "corrected",
                                     "details": f"дополнено детерминированными объяснениями: {len(missing)}"})
    report = masker.mask_obj(report)
    return ReportOutcome(report, True, validation, provider.name, provider.cfg.model, usage, None, lang)

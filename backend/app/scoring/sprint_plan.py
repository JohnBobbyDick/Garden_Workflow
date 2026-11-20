"""AI sprint plan over the Priority Fix List — the LLM only orders and explains; numbers are recomputed here.

Input (masked, no paths/authors/snippets): ``{score, delta, trend, top_findings:[{finding_id, class, severity,
novelty, fix_effort, expected_gain}]}``. Output schema ``{summary, plan:[{finding_id, action, reason}],
defer:[{finding_id, reason}], projected_score, efforts?}``. Validator: unknown/duplicate ids dropped,
``projected_score`` recomputed deterministically from ``plan`` (difference > 1 → replaced, ``corrected_numbers``),
CVE/GHSA ids outside (database ∩ findings) scrubbed, ``fix_effort`` accepted only as an int 1..5 for a known id.
Without an LLM (or on failure) a deterministic plan with ``ai_generated: false`` is returned.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.ai.providers.base import LLMError, LLMProvider
from app.ai.validator import ADVISORY_RE, REMOVED_ID, AIFormatError, parse_json, schema_errors
from app.analyzers.common.finding import Finding
from app.core.masking import Masker
from app.scoring.formula import compute_score
from app.scoring.priority import priority_list, valid_efforts

logger = logging.getLogger(__name__)
TOP_FOR_PLAN = 15
SPRINT_BUDGET = 8  # effort points a small team closes in one sprint (deterministic plan)

SPRINT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary", "plan", "defer", "projected_score"],
    "properties": {
        "summary": {"type": "string"},
        "plan": {"type": "array", "items": {"type": "object", "required": ["finding_id", "action", "reason"],
                                            "properties": {"finding_id": {"type": "string"},
                                                           "action": {"type": "string"},
                                                           "reason": {"type": "string"}}}},
        "defer": {"type": "array", "items": {"type": "object", "required": ["finding_id", "reason"],
                                             "properties": {"finding_id": {"type": "string"},
                                                            "reason": {"type": "string"}}}},
        "projected_score": {"type": "number"},
        "efforts": {"type": "array", "items": {"type": "object", "required": ["finding_id", "fix_effort"],
                                               "properties": {"finding_id": {"type": "string"},
                                                              "fix_effort": {"type": "integer"}}}},
    },
}

PROMPT = {
    "ru": ("Ты — тимлид по безопасности. Тебе дан Security Score проекта и Priority Fix List (находки уже найдены "
           "сканерами, ты ничего не обнаруживаешь). Составь план на один спринт: что чинить сейчас (plan), что "
           "отложить (defer) и почему; оцени трудозатраты fix_effort 1..5 (efforts). Используй ТОЛЬКО finding_id из "
           "входа, не выдумывай CVE, файлы и строки. projected_score — ожидаемый score после выполнения plan. "
           "Ответ — строго JSON по схеме, на русском языке."),
    "en": ("You are a security team lead. You get the project's Security Score and the Priority Fix List (findings "
           "were already detected by scanners; you detect nothing). Make a one-sprint plan: what to fix now (plan), "
           "what to defer (defer) and why; estimate fix_effort 1..5 (efforts). Use ONLY finding_id values from the "
           "input, never invent CVEs, files or lines. projected_score is the expected score after the plan. "
           "Answer strictly as JSON matching the schema, in English."),
}


@dataclass
class PlanOutcome:
    plan: dict[str, Any]
    ai_generated: bool
    validation: dict[str, Any] = field(default_factory=dict)
    provider: str | None = None
    model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    error: str | None = None


def plan_input(score: int, delta: int | None, trend: dict | None, top: list[dict]) -> dict:
    return {"score": score, "delta": delta,
            "trend_per_week": (trend or {}).get("slope_per_week") if (trend or {}).get("enough_data") else None,
            "top_findings": [{"finding_id": i["finding_id"], "class": i["class"], "severity": i["severity"],
                              "novelty": i["novelty"], "fix_effort": i["fix_effort"],
                              "expected_gain": i["expected_gain"]} for i in top]}


def projected(findings: list[Finding], loc: int | None, params: dict, fixed_ids: set[str]) -> int:
    return compute_score([f for f in findings if f.id not in fixed_ids], loc, params).score


def deterministic_plan(findings: list[Finding], loc: int | None, params: dict, top: list[dict],
                       language: str) -> dict:
    plan, defer, spent = [], [], 0
    for i in top:
        if spent + i["fix_effort"] <= SPRINT_BUDGET:
            spent += i["fix_effort"]
            plan.append({"finding_id": i["finding_id"],
                         "action": "исправить в этом спринте" if language == "ru" else "fix in this sprint",
                         "reason": (f"приоритет {i['priority']}, ожидаемо +{i['expected_gain']} к score, "
                                    f"{i['effort_words']}" if language == "ru" else
                                    f"priority {i['priority']}, expected +{i['expected_gain']} score, "
                                    f"{i['effort_words']}")})
        else:
            defer.append({"finding_id": i["finding_id"],
                          "reason": "не помещается в бюджет спринта" if language == "ru" else "exceeds the sprint budget"})
    proj = projected(findings, loc, params, {p["finding_id"] for p in plan})
    summary = (f"План по Priority Fix List: {len(plan)} исправлений в спринте, ожидаемый score {proj}."
               if language == "ru" else f"Plan from the Priority Fix List: {len(plan)} fixes, expected score {proj}.")
    return {"summary": summary, "plan": plan, "defer": defer, "projected_score": proj}


def validate_plan(data: dict, findings: list[Finding], loc: int | None, params: dict, top_ids: set[str],
                  allowed_advisories: set[str]) -> tuple[dict, dict]:
    """Returns (clean plan, validation log). Raises AIFormatError when the structure is unusable."""
    errs = schema_errors(data, SPRINT_SCHEMA)
    if errs:
        raise AIFormatError("; ".join(errs[:5]))
    log: dict[str, Any] = {"dropped_ids": [], "duplicates": [], "hallucinated_ids": [], "corrected_numbers": False}
    seen: set[str] = set()

    def scrub(text: str) -> str:
        def repl(m):  # noqa: ANN001, ANN202
            if m.group(1).upper() in allowed_advisories:
                return m.group(1)
            log["hallucinated_ids"].append(m.group(1))
            return REMOVED_ID
        return ADVISORY_RE.sub(repl, str(text))[:2000]

    def keep(item: dict) -> bool:
        fid = str(item.get("finding_id", ""))
        if fid not in top_ids:
            log["dropped_ids"].append(fid)
            return False
        if fid in seen:
            log["duplicates"].append(fid)
            return False
        seen.add(fid)
        return True

    plan = [{"finding_id": i["finding_id"], "action": scrub(i["action"]), "reason": scrub(i["reason"])}
            for i in data["plan"] if keep(i)]
    defer = [{"finding_id": i["finding_id"], "reason": scrub(i["reason"])} for i in data["defer"] if keep(i)]
    calc = projected(findings, loc, params, {p["finding_id"] for p in plan})
    llm_value = data.get("projected_score")
    if not isinstance(llm_value, int | float) or abs(float(llm_value) - calc) > 1:
        log["corrected_numbers"] = True
        log["llm_projected_score"] = llm_value
    efforts = valid_efforts({str(e.get("finding_id")): e.get("fix_effort") for e in data.get("efforts") or []},
                            top_ids)
    log["efforts_accepted"] = len(efforts)
    log["efforts_rejected"] = len(data.get("efforts") or []) - len(efforts)
    return {"summary": scrub(data["summary"]), "plan": plan, "defer": defer, "projected_score": calc,
            "efforts": efforts}, log


async def generate_sprint_plan(findings: list[Finding], loc: int | None, params: dict, score: int,
                               delta: int | None, trend: dict | None, provider: LLMProvider | None, *,
                               allowed_advisories: set[str], masker: Masker, language: str = "ru") -> PlanOutcome:
    lang = language if language in ("ru", "en") else "ru"
    top = priority_list(findings, loc, params, language=lang)[:TOP_FOR_PLAN]
    fallback = deterministic_plan(findings, loc, params, top, lang)
    if provider is None:
        return PlanOutcome({**fallback, "priority": top}, False,
                           {"provider": "skipped", "details": "AI-провайдер не настроен — детерминированный план"},
                           error="AI-провайдер не настроен")
    payload = json.dumps(plan_input(score, delta, trend, top), ensure_ascii=False)
    messages = [{"role": "system", "content": PROMPT[lang]},
                {"role": "user", "content": masker.mask(payload)}]
    usage: dict[str, int] = {}
    last_error = ""
    for attempt in range(2):
        try:
            res = await provider.chat(messages, response_schema=SPRINT_SCHEMA, temperature=0.2, max_tokens=2048)
        except LLMError as exc:
            last_error = masker.mask(str(exc))
            break
        for k, v in res.usage.items():
            usage[k] = usage.get(k, 0) + v
        try:
            clean, log = validate_plan(parse_json(res.content), findings, loc, params, {i["finding_id"] for i in top},
                                       allowed_advisories)
        except AIFormatError as exc:
            last_error = masker.mask(str(exc))
            messages = messages + [{"role": "assistant", "content": masker.mask(res.content)[:4000]},
                                   {"role": "user", "content": f"Ответ не прошёл проверку: {last_error}. "
                                                               "Верни исправленный JSON строго по схеме."}]
            continue
        efforts = clean.pop("efforts")
        top_ai = priority_list(findings, loc, params, ai_efforts=efforts, language=lang)[:TOP_FOR_PLAN]
        log["repairs"] = attempt
        return PlanOutcome({**clean, "priority": top_ai}, True, log, provider.cfg.provider,
                           res.model or provider.cfg.model, usage)
    logger.warning("sprint plan fell back to deterministic: %s", last_error)
    return PlanOutcome({**fallback, "priority": top}, False, {"provider": "failed", "details": last_error},
                       error=last_error, usage=usage)

"""AutoFix orchestration: restore sources → baseline analysis → deterministic SCA bump or LLM patch (one repair
attempt with the validator's errors) → validator checklist → masked patch → ``autofixes`` row."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app import models as m
from app.ai.providers.base import LLMError, LLMProvider
from app.ai.validator import AIFormatError, parse_json
from app.analyzers.common.finding import Finding
from app.analyzers.runner import analyze_project
from app.autofix.context import SecretIndex, build_context
from app.autofix.sca_bump import BumpError, plan_bump
from app.autofix.source import SourceUnavailable, restored_source
from app.autofix.validator import FIX_SCHEMA, Validation, apply_and_check, masked_patch, validate_llm_fix
from app.core.masking import Masker

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 2

PROMPT = {
    "ru": ("Ты — инженер по безопасности Kotlin/Spring. Находка уже обнаружена сканером, ты ничего не ищешь — только "
           "предлагаешь минимальный патч, устраняющий именно её. Правила: меняй только строки из контекста; "
           "old_snippet — дословно строки файла start_line..end_line из контекста (без номеров строк); new_snippet — "
           "замена этих строк с правильными отступами; секреты выноси в переменные окружения БЕЗ значения по "
           "умолчанию и перечисли их в requires_config; не вставляй значения секретов и маски вида «…(len=N)»; "
           "SQL — параметризация; не меняй поведение сверх необходимого. Ответ — строго JSON по схеме, "
           "explanation на русском."),
    "en": ("You are a Kotlin/Spring security engineer. The finding was already detected by a scanner; you detect "
           "nothing and only propose a minimal patch that removes exactly this finding. Rules: change only lines from "
           "the context; old_snippet is verbatim file lines start_line..end_line from the context (no line numbers); "
           "new_snippet replaces them with correct indentation; move secrets to environment variables WITHOUT a "
           "default and list them in requires_config; never insert secret values or masks like «…(len=N)»; SQL — "
           "parameterize; do not change behaviour beyond what is needed. Answer strictly as JSON matching the "
           "schema, explanation in English."),
}


class AutofixError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class Outcome:
    validation: Validation
    patch: str
    kind: str
    provider: str | None = None
    model: str | None = None
    usage: dict | None = None
    attempts: int = 1
    masker: Masker | None = None

    def stored_proposal(self) -> dict:
        """Proposal safe to store: masked text fields; new_snippet (validated secret-free code) keeps its exact text
        except for known values — it is re-applied to real sources for a PR."""
        m = self.masker or Masker()
        prop = dict(self.validation.proposal)
        new = prop.pop("new_snippet", None)
        out = m.mask_obj({**prop, "self_check": self.validation.self_check, "attempts": self.attempts,
                          "usage": self.usage or {}})
        if new is not None:
            out["new_snippet"] = m.mask_known(new)
        return out


def _baseline(root: Path) -> list[Finding]:
    return analyze_project(root).findings


async def _llm_fix(provider: LLMProvider, root: Path, finding: Finding, secrets: SecretIndex,
                   baseline: list[Finding], masker: Masker, language: str) -> tuple[Validation, dict, str, int]:
    ctx = build_context(root, finding, secrets, masker)
    lang = language if language in PROMPT else "ru"
    payload = masker.mask(json.dumps(ctx, ensure_ascii=False))
    messages = [{"role": "system", "content": PROMPT[lang]}, {"role": "user", "content": payload}]
    usage: dict[str, int] = {}
    model = provider.cfg.model
    v = Validation()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            res = await provider.chat(messages, response_schema=FIX_SCHEMA, temperature=0.1, max_tokens=2048)
        except LLMError as exc:
            v = Validation()
            v.step("llm", False, masker.mask(str(exc))[:300])
            return v, usage, model, attempt
        model = res.model or model
        for k, n in res.usage.items():
            usage[k] = usage.get(k, 0) + n
        try:
            data = parse_json(res.content)
        except AIFormatError as exc:
            data = {"_error": str(exc)}
        v = await asyncio.to_thread(validate_llm_fix, data, ctx, root, finding, secrets, baseline, masker)
        if v.status == "validated" or attempt == MAX_ATTEMPTS:
            return v, usage, model, attempt
        messages = messages + [
            {"role": "assistant", "content": masker.mask(res.content)[:6000]},
            {"role": "user", "content": "Патч не прошёл проверку: " + "; ".join(v.errors())[:1500]
                                        + ". Исправь и верни JSON строго по схеме."}]
    return v, usage, model, MAX_ATTEMPTS


def check_applicable(finding: Finding, provider: LLMProvider | None) -> None:
    if finding.autofix == "none":
        raise AutofixError(409, "autofix_not_applicable",
                           "для этого правила AutoFix недоступен (архитектурное решение) — см. рекомендацию")
    if finding.autofix == "llm" and provider is None:
        raise AutofixError(400, "ai_not_configured", "AI-провайдер не настроен: AutoFix для этой находки требует LLM")


async def generate_at(root: Path, finding: Finding, provider: LLMProvider | None, language: str = "ru",
                      baseline: list[Finding] | None = None, secrets: SecretIndex | None = None) -> Outcome:
    """AutoFix on a project root (restored sources, or the live working copy inside a run). Never modifies ``root``."""
    check_applicable(finding, provider)
    masker = Masker()
    secrets = secrets or await asyncio.to_thread(SecretIndex.scan, root)
    masker.register(*secrets.all_values())
    baseline = baseline if baseline is not None else await asyncio.to_thread(_baseline, root)
    target = next((f for f in baseline if f.id == finding.id), None)
    if target is None:
        raise AutofixError(409, "finding_not_reproduced",
                           "находка не воспроизводится на исходниках запуска (код изменился или удалён)")
    if finding.autofix == "deterministic":
        v = Validation()
        try:
            _, edits, proposal = plan_bump(root, target)
        except BumpError as exc:
            v.step("bump", False, str(exc))
            return Outcome(v, "", "deterministic", masker=masker)
        v.step("bump", True, proposal["explanation"])
        v.proposal, v.edits = proposal, edits
        v = await asyncio.to_thread(apply_and_check, v, root, edits, target, baseline)
        return Outcome(v, masked_patch(v.edits, secrets, masker), "deterministic", masker=masker)
    v, usage, model, attempts = await _llm_fix(provider, root, target, secrets, baseline, masker, language)  # type: ignore[arg-type]
    patch = masked_patch(v.edits, secrets, masker) if v.status == "validated" else ""
    return Outcome(v, patch, "llm", provider.cfg.provider, model, usage, attempts,  # type: ignore[union-attr]
                   masker=masker)


async def generate(s, run: m.Run, finding: Finding, provider: LLMProvider | None, language: str = "ru") -> Outcome:  # noqa: ANN001
    check_applicable(finding, provider)
    try:
        with restored_source(s, run) as root:
            return await generate_at(root, finding, provider, language)
    except SourceUnavailable as exc:
        raise AutofixError(409, "source_unavailable", str(exc)) from exc

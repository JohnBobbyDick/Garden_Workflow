"""Usefulness evaluation of AI recommendations over a whole project (presentation requirement «оцените полезность
рекомендаций»): ``cd backend && python -m app.ai.eval_report [--project PATH] [--json OUT]``.

The model gets the same input as the ``ai.report`` node, its answer passes our validator, and then every accepted
explanation is checked against measurable criteria. Explanations the platform filled in itself (``source:
deterministic``) are not counted as the model's work. No provider → the command refuses instead of pretending."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from app.ai.providers.base import LLMError, LLMProvider, build_provider
from app.ai.report_service import generate_report
from app.ai.validator import masked_file_reader
from app.analyzers.common.finding import Finding
from app.analyzers.runner import analyze_project
from app.config import REPO_ROOT
from app.core.masking import Masker
from app.export.submission_json import OFFICIAL_MIN_CONFIDENCE

CATEGORIES = ("SECRET", "SAST", "SCA")
DEFAULT_PROJECT = REPO_ROOT / "fixtures" / "organizer-training" / "training-project"
CRITERIA = {
    "located": "объяснение называет конкретный файл; для SCA — файл объявления или артефакт",
    "actionable": "есть хотя бы один конкретный шаг исправления",
    "fix_or_version": "SECRET/SAST: принят diff исправления; SCA: безопасная версия из справочника",
}


def _text(item: dict) -> str:
    steps = " ".join(str(s) for s in item.get("remediation_steps") or [])
    return f"{item.get('explanation', '')} {item.get('impact', '')} {steps}".lower()


def _located(f: Finding, item: dict) -> bool:
    text = _text(item)
    tokens = [PurePosixPath(f.path.replace("\\", "/")).name]
    if f.category == "SCA":
        tokens.append(f.artifact or "")  # SCA: the declaration file or the artifact itself
    return any(t and t.lower() in text for t in tokens)


def _actionable(item: dict) -> bool:
    return any(isinstance(s, str) and s.strip() for s in item.get("remediation_steps") or [])


def _fix_or_version(f: Finding, item: dict) -> bool:
    if f.category == "SCA":
        return bool(item.get("safe_version")) and item["safe_version"] in f.fixed_versions
    return bool(item.get("fix"))


def evaluate_outcome(findings: list[Finding], report: dict, validation: dict, ai_generated: bool) -> dict[str, Any]:
    items = {i.get("finding_id"): i for i in report.get("findings", [])
             if ai_generated and i.get("source") != "deterministic"}
    by_cat: dict[str, dict[str, int]] = {c: {"n": 0, "ai": 0, "located": 0, "actionable": 0, "fix_or_version": 0}
                                         for c in CATEGORIES}
    rows = []
    for f in findings:
        row = by_cat.setdefault(f.category, {"n": 0, "ai": 0, "located": 0, "actionable": 0, "fix_or_version": 0})
        row["n"] += 1
        item = items.get(f.id)
        flags = {"ai": item is not None, "located": bool(item) and _located(f, item),
                 "actionable": bool(item) and _actionable(item), "fix_or_version": bool(item) and _fix_or_version(f, item)}
        for k, v in flags.items():
            row[k] += int(v)
        rows.append({"id": f.id, "category": f.category, "title": f.title, "path": f.path, **flags})
    m = validation.get("metrics", {})
    return {
        "ai_generated": ai_generated,
        "total": len(findings),
        "ai_explained": sum(r["ai"] for r in rows),
        "by_category": {c: v for c, v in by_cat.items() if v["n"]},
        "validator": {"accepted": f"{m.get('valid_items', 0)}/{m.get('total_items', 0)}",
                      "dropped": int(m.get("dropped", 0)), "hallucinated_ids": len(m.get("hallucinated_ids") or []),
                      "bad_references": int(m.get("bad_references", 0)), "fixes_kept": int(m.get("fixes_kept", 0)),
                      "fixes_dropped": int(m.get("fixes_dropped", 0))},
        "findings": rows,
        "criteria": CRITERIA,
    }


async def run_eval(project: str | Path, provider: LLMProvider, language: str = "ru") -> dict[str, Any]:
    """Analyze ``project`` with our scanners, ask ``provider`` exactly like the ``ai.report`` node does (official
    findings only, no deterministic fallback), validate and measure."""
    root = Path(project)
    findings = [f for f in analyze_project(root).findings if f.confidence >= OFFICIAL_MIN_CONFIDENCE]
    allowed = {f.advisory_id for f in findings if f.advisory_id} | {a for f in findings for a in f.aliases}
    outcome = await generate_report(findings, provider, read=masked_file_reader(root, findings), allowed_ids=allowed,
                                    masker=Masker(), language=language, fallback=False, project=root.name)
    result = evaluate_outcome(findings, outcome.report, outcome.validation, outcome.ai_generated)
    result.update(provider=outcome.provider, model=outcome.model, usage=outcome.usage, project=root.name)
    return result


def _pct(a: int, b: int) -> str:
    return f"{a}/{b} ({round(100 * a / b)}%)" if b else "—"


def render_markdown_table(r: dict[str, Any]) -> str:
    head = "| Категория | Находок | Объяснил AI | Указан файл / артефакт | Есть шаги | Diff / безопасная версия |"
    lines = [head, "| --- | --- | --- | --- | --- | --- |"]
    tot = {"n": 0, "ai": 0, "located": 0, "actionable": 0, "fix_or_version": 0}
    for cat, v in r["by_category"].items():
        for k in tot:
            tot[k] += v[k]
        lines.append(f"| {cat} | {v['n']} | {_pct(v['ai'], v['n'])} | {_pct(v['located'], v['n'])} | "
                     f"{_pct(v['actionable'], v['n'])} | {_pct(v['fix_or_version'], v['n'])} |")
    lines.append(f"| Итого | {tot['n']} | {_pct(tot['ai'], tot['n'])} | {_pct(tot['located'], tot['n'])} | "
                 f"{_pct(tot['actionable'], tot['n'])} | {_pct(tot['fix_or_version'], tot['n'])} |")
    v = r["validator"]
    lines += ["", f"Валидатор: принято {v['accepted']}, отброшено {v['dropped']}, выдуманных CVE/GHSA "
                  f"{v['hallucinated_ids']}, неверных ссылок на файл:строку {v['bad_references']}, diff принято "
                  f"{v['fixes_kept']}, отклонено {v['fixes_dropped']}."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from app.ai.settings_service import env_provider_config

    ap = argparse.ArgumentParser(description="Оценка полезности AI-рекомендаций на всём наборе находок")
    ap.add_argument("--project", default=str(DEFAULT_PROJECT), help="корень проверяемого проекта")
    ap.add_argument("--json", help="сохранить подробный результат в JSON-файл")
    ap.add_argument("--language", default="ru", choices=["ru", "en"])
    args = ap.parse_args(argv)
    cfg = env_provider_config(Masker())
    if cfg is None:
        print("LLM не настроен: задайте NVIDIA_API_KEY (или LLM_PROVIDER=ollama с OLLAMA_URL/OLLAMA_MODEL). "
              "Без модели оценивать нечего — детерминированный отчёт не выдаётся за ответ AI.")
        return 2
    try:
        result = asyncio.run(run_eval(args.project, build_provider(cfg), args.language))
    except LLMError as exc:
        print(f"Модель не ответила: {exc}")
        return 1
    print(f"Проект: {result['project']} · модель: {result['provider']}/{result['model']}\n")
    print(render_markdown_table(result))
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

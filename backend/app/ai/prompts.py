"""Prompts (RU/EN). The LLM only explains findings produced by our analyzers; it never detects anything.

Only masked data is sent: snippets and code context come from the masked file view, then pass the run masker."""

from __future__ import annotations

import json
from typing import Any

from app.ai.validator import FileReader
from app.analyzers.common.finding import Finding

CONTEXT_LINES = 3

SYSTEM = {
    "ru": """Ты — эксперт по безопасности приложений и объясняешь результаты статического анализа разработчику небольшой команды.
Ты НЕ ищешь новые уязвимости: работаешь только с находками из входного списка, их нашли наши анализаторы.

Строгие правила:
1. Используй только finding_id из входных данных. Не придумывай находки, файлы, строки и идентификаторы.
2. Не придумывай CVE и GHSA: упоминай только advisory_id/aliases, которые есть во входных данных.
3. Значения секретов замаскированы (вид «ab…(len=24)»). Не пытайся их восстановить; в исправлениях выноси секреты в переменные окружения без значения по умолчанию.
4. Поле fix необязательно. Если даёшь fix: path — файл находки, start_line/end_line — номера строк из поля code, before — ДОСЛОВНАЯ копия текста этих строк из поля code (не меняй ни символа), after — исправленный код.
5. safe_version (только для SCA) выбирай строго из fixed_versions.
6. Пиши простым языком: что не так, где, чем грозит, что сделать по шагам. Ответ — на русском языке.
7. Ответ — один JSON-объект по схеме: summary, priority_order (finding_id по убыванию срочности), findings[] (finding_id, explanation, impact, remediation_steps[], safe_version, fix), global_recommendations[].

Пример формата:
{"summary": "Главный риск — SQL-инъекция в публичном обработчике…", "priority_order": ["f_abc"],
 "findings": [{"finding_id": "f_abc", "explanation": "Параметр запроса подставляется в SQL строкой…",
   "impact": "Злоумышленник прочитает или изменит данные…", "remediation_steps": ["Передавайте значение как параметр ?"],
   "safe_version": null, "fix": {"path": "src/A.kt", "start_line": 12, "end_line": 12,
   "before": "    val sql = \\"select * from t where id = $id\\"", "after": "    val sql = \\"select * from t where id = ?\\""}}],
 "global_recommendations": ["Запускайте проверку в CI на каждый pull request"]}""",
    "en": """You are an application security expert explaining static analysis results to a developer of a small team.
You do NOT look for new vulnerabilities: you only work with the findings in the input list, produced by our analyzers.

Strict rules:
1. Use only finding_id values from the input. Do not invent findings, files, lines or identifiers.
2. Do not invent CVE or GHSA ids: mention only advisory_id/aliases present in the input.
3. Secret values are masked (like "ab…(len=24)"). Never try to recover them; fixes move secrets to environment variables without defaults.
4. fix is optional. If you give one: path is the finding's file, start_line/end_line are line numbers from the code field, before is a VERBATIM copy of those lines from the code field (do not change a single character), after is the fixed code.
5. safe_version (SCA only) must be one of fixed_versions.
6. Write plainly: what is wrong, where, what it can lead to, what to do step by step. Answer in English.
7. Answer with one JSON object: summary, priority_order (finding_id by urgency), findings[] (finding_id, explanation, impact, remediation_steps[], safe_version, fix), global_recommendations[].

Format example:
{"summary": "The main risk is SQL injection in a public handler…", "priority_order": ["f_abc"],
 "findings": [{"finding_id": "f_abc", "explanation": "A request parameter is concatenated into SQL…",
   "impact": "An attacker can read or change data…", "remediation_steps": ["Pass the value as a ? parameter"],
   "safe_version": null, "fix": {"path": "src/A.kt", "start_line": 12, "end_line": 12,
   "before": "    val sql = \\"select * from t where id = $id\\"", "after": "    val sql = \\"select * from t where id = ?\\""}}],
 "global_recommendations": ["Run the check in CI on every pull request"]}""",
}

USER_HEAD = {"ru": "Данные анализа для объяснения (JSON, все секреты замаскированы):\n",
             "en": "Analysis data to explain (JSON, all secrets masked):\n"}
NO_FIX = {"ru": "Поле fix не заполняй (null).", "en": "Leave fix empty (null)."}
REPAIR = {"ru": "Твой ответ не прошёл проверку: {error}. Верни исправленный ответ — один JSON-объект строго по схеме, "
                "без пояснений.",
          "en": "Your answer failed validation: {error}. Return a corrected answer — one JSON object strictly matching "
                "the schema, no explanations."}


def finding_payload(f: Finding, read: FileReader) -> dict[str, Any]:
    d: dict[str, Any] = {"finding_id": f.id, "category": f.category, "class": f.cls, "title": f.title,
                         "severity": f.severity, "severity_reason": f.severity_reason, "confidence": f.confidence,
                         "path": f.path, "line": f.line, "end_line": f.end_line, "cwe": f.cwe,
                         "description": f.description, "snippet": f.snippet}
    lines = read(f.path)
    if lines:
        start = max(1, f.line - CONTEXT_LINES)
        end = min(len(lines), (f.end_line or f.line) + CONTEXT_LINES)
        d["code"] = [{"line": n, "text": lines[n - 1]} for n in range(start, end + 1)]
    if f.alternate_locations:
        d["alternate_locations"] = [{"path": a.path, "line": a.line, "end_line": a.end_line}
                                    for a in f.alternate_locations]
    if f.category == "SCA":
        d.update({"group": f.group, "artifact": f.artifact, "version": f.version, "advisory_id": f.advisory_id,
                  "aliases": f.aliases, "fixed_versions": f.fixed_versions,
                  "cvss_score": f.cvss.score if f.cvss else None})
    return d


def build_messages(findings: list[Finding], read: FileReader, language: str, project: str,
                   generate_fix_diff: bool) -> list[dict[str, str]]:
    lang = language if language in SYSTEM else "ru"
    payload = {"project": project, "language": lang, "findings": [finding_payload(f, read) for f in findings]}
    system = SYSTEM[lang] + ("" if generate_fix_diff else "\n" + NO_FIX[lang])
    return [{"role": "system", "content": system},
            {"role": "user", "content": USER_HEAD[lang] + json.dumps(payload, ensure_ascii=False)}]


def repair_messages(messages: list[dict[str, str]], bad_answer: str, error: str, language: str) -> list[dict]:
    lang = language if language in REPAIR else "ru"
    return [*messages, {"role": "assistant", "content": bad_answer[:4000]},
            {"role": "user", "content": REPAIR[lang].format(error=error[:600])}]

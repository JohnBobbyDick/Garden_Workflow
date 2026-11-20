"""Deterministic report from analyzer data (no LLM, no invention). Used when no provider is configured or the
LLM answer failed validation; always marked ``ai_generated: false``."""

from __future__ import annotations

from collections import Counter

from app.analyzers.common.finding import SEVERITY_ORDER, Finding
from app.analyzers.sca.versions import UnsupportedVersion, nearest_fixed_version

IMPACT = {
    "ru": {
        "SECRET": "Любой, у кого есть доступ к коду или истории репозитория, получит действующий секрет и сможет "
                  "обращаться к сервису от имени приложения.",
        "SCA": "Известная уязвимость в зависимости может быть использована по опубликованному сценарию атаки.",
        "sql-injection": "Злоумышленник может читать, изменять или удалять данные в базе через параметр запроса.",
        "tls-verification": "Соединение можно перехватить (MITM): данные и учётные данные уйдут злоумышленнику.",
        "credentialed-cors": "Любой сайт сможет выполнять запросы от имени вошедшего пользователя и читать ответы.",
        "route-authorization": "Служебный или чувствительный маршрут доступен без входа в систему.",
        "object-authorization": "Пользователь может получить чужие данные, подставив другой идентификатор (IDOR).",
        "SAST": "Уязвимость в коде может быть использована для нарушения конфиденциальности или целостности данных.",
    },
    "en": {
        "SECRET": "Anyone with access to the code or repository history gets a working secret and can call the "
                  "service on behalf of the application.",
        "SCA": "A known vulnerability in the dependency can be exploited using a published attack scenario.",
        "sql-injection": "An attacker can read, change or delete database data through a request parameter.",
        "tls-verification": "The connection can be intercepted (MITM): data and credentials leak to an attacker.",
        "credentialed-cors": "Any website can send requests as the signed-in user and read the responses.",
        "route-authorization": "An internal or sensitive route is reachable without signing in.",
        "object-authorization": "A user can read other users' data by substituting another identifier (IDOR).",
        "SAST": "The code weakness can be used to break confidentiality or integrity of data.",
    },
}
STEPS = {
    "ru": {
        "SECRET": ["Отзовите и перевыпустите секрет у владельца сервиса.",
                   "Уберите значение из кода и конфигурации, читайте его из переменной окружения без значения по "
                   "умолчанию или из хранилища секретов.", "Очистите историю репозитория, если секрет был закоммичен."],
        "SCA": ["Обновите зависимость до исправленной версии ({version}).",
                "Перегенерируйте lock-файл (./gradlew dependencies --write-locks) и прогоните тесты."],
        "SAST": ["{remediation}"],
    },
    "en": {
        "SECRET": ["Revoke and reissue the secret with the service owner.",
                   "Remove the value from code and configuration; read it from an environment variable without a "
                   "default or from a secret store.", "Purge repository history if the secret was committed."],
        "SCA": ["Upgrade the dependency to a fixed version ({version}).",
                "Regenerate the lock file (./gradlew dependencies --write-locks) and run the tests."],
        "SAST": ["{remediation}"],
    },
}
EXPLAIN = {
    "ru": "{title}: {where}. Критичность {severity} — {reason}",
    "en": "{title} ({cls}): {where}. Severity {severity} — {reason}",
}
SUMMARY = {
    "ru": "Отчёт сформирован без AI по данным анализаторов: {total} находок ({sev}). В первую очередь исправьте "
          "находки уровня {top}.",
    "en": "Report built without AI from analyzer data: {total} findings ({sev}). Fix {top} findings first.",
}
GLOBAL = {
    "ru": ["Подключите проверку к CI/CD и блокируйте слияние при Critical.",
           "Храните секреты только в хранилище секретов или переменных окружения.",
           "Регулярно обновляйте зависимости и lock-файлы."],
    "en": ["Run the check in CI/CD and block merges on Critical.",
           "Keep secrets only in a secret store or environment variables.",
           "Update dependencies and lock files regularly."],
}


def safe_version(f: Finding) -> str | None:
    if not f.fixed_versions:
        return None
    try:
        return nearest_fixed_version(f.version or "", f.fixed_versions) or f.fixed_versions[0]
    except (UnsupportedVersion, ValueError):
        return f.fixed_versions[0]


def deterministic_item(f: Finding, language: str) -> dict:
    lang = language if language in IMPACT else "ru"
    where = (f"{f.group}:{f.artifact}:{f.version} ({f.advisory_id}), {f.path}:{f.line}" if f.category == "SCA"
             else f"{f.path}:{f.line}" + (f"–{f.end_line}" if f.end_line and f.end_line != f.line else ""))
    impact = IMPACT[lang].get(f.cls) or IMPACT[lang][f.category]
    sv = safe_version(f) if f.category == "SCA" else None
    steps = [s.format(version=sv or "—", remediation=f.remediation or "") for s in
             STEPS[lang].get(f.category, STEPS[lang]["SAST"])]
    item = {"finding_id": f.id, "explanation": EXPLAIN[lang].format(title=f.title, cls=f.cls, where=where,
                                                                      severity=f.severity,
                                                                      reason=f.severity_reason or f.description),
            "impact": impact, "remediation_steps": [s for s in steps if s.strip()], "source": "deterministic"}
    if sv:
        item["safe_version"] = sv
    return item


def ordered(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (-SEVERITY_ORDER[f.severity], -f.confidence, f.category, f.path, f.line))


def deterministic_report(findings: list[Finding], language: str) -> dict:
    lang = language if language in SUMMARY else "ru"
    fs = ordered(findings)
    sev = Counter(f.severity for f in fs)
    sev_text = ", ".join(f"{s} {sev[s]}" for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW") if sev.get(s))
    top = fs[0].severity if fs else "—"
    return {"summary": SUMMARY[lang].format(total=len(fs), sev=sev_text or "—", top=top),
            "priority_order": [f.id for f in fs], "findings": [deterministic_item(f, lang) for f in fs],
            "global_recommendations": GLOBAL[lang]}

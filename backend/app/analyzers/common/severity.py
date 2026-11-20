"""Severity classification: data tables + explanation functions (the explanation is stored in each finding)."""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.analyzers.common.finding import SEVERITY_ORDER
from app.analyzers.sca.cvss import severity_from_score

LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def _shift(level: str, delta: int) -> str:
    idx = max(0, min(len(LEVELS) - 1, LEVELS.index(level) + delta))
    return LEVELS[idx]


def max_severity(levels: Iterable[str]) -> str | None:
    best = None
    for lv in levels:
        if best is None or SEVERITY_ORDER[lv] > SEVERITY_ORDER[best]:
            best = lv
    return best


# --- SCA -----------------------------------------------------------------------------------------------------

def sca_severity(cvss_score: float | None, snapshot_severity: str | None) -> tuple[str, str]:
    if cvss_score is not None:
        sev = severity_from_score(cvss_score)
        reason = (f"CVSS v3 base score {cvss_score} рассчитан собственным калькулятором по вектору записи: "
                  f"≥9.0 CRITICAL, 7.0–8.9 HIGH, 4.0–6.9 MEDIUM, <4.0 LOW")
        if snapshot_severity and snapshot_severity != sev:
            reason += f"; в справочнике указан уровень {snapshot_severity}"
        return sev, reason
    sev = snapshot_severity or "MEDIUM"
    return sev, "Вектор CVSS отсутствует — использован уровень из справочника уязвимостей"


# --- SECRET --------------------------------------------------------------------------------------------------

SECRET_BASE: dict[str, tuple[str, str]] = {
    "private-key": ("CRITICAL", "приватный ключ даёт полный доступ к подписи/расшифрованию"),
    "aws-access-key": ("CRITICAL", "облачный ключ доступа даёт доступ к ресурсам аккаунта"),
    "github-token": ("HIGH", "токен репозитория даёт доступ к исходному коду и CI"),
    "telegram-token": ("HIGH", "токен бота позволяет читать и отправлять сообщения от имени бота"),
    "slack-token": ("HIGH", "токен Slack даёт доступ к переписке рабочего пространства"),
    "stripe-key": ("CRITICAL", "боевой платёжный ключ"),
    "google-api-key": ("MEDIUM", "API-ключ облачного сервиса"),
    "jwt": ("HIGH", "подписанный токен сессии/сервиса"),
    "db-credentials": ("HIGH", "учётные данные базы данных"),
    "url-credentials": ("HIGH", "учётные данные в URL подключения"),
    "basic-auth": ("HIGH", "учётные данные Basic-аутентификации"),
    "password": ("HIGH", "пароль служебной учётной записи в исходниках"),
    "api-key": ("MEDIUM", "ключ API внешнего сервиса"),
    "configuration-token": ("HIGH", "токен авторизации в файле конфигурации, попадает во все окружения"),
    "secret-fallback": ("MEDIUM", "встроенный секрет используется, когда переменная окружения не задана"),
    "recoverable-token": ("MEDIUM", "токен восстанавливается из фрагментов в исходниках"),
    "generic-secret": ("LOW", "строка с высокой энтропией в секретном контексте (эвристика)"),
}

_PROD = re.compile(r"(^|[/_.\-])prod(uction)?([/_.\-]|$)", re.I)
_TEST = re.compile(r"(^|/)(src/test|src/androidTest|test|tests|testFixtures|docs?|examples?|samples?)(/|$)|\.md$", re.I)


def is_test_or_doc_path(path: str) -> bool:
    return bool(_TEST.search(path))


def secret_severity(cls: str, path: str) -> tuple[str, str]:
    base, why = SECRET_BASE.get(cls, ("MEDIUM", "секрет"))
    sev, mods = base, []
    if _PROD.search(path):
        sev = _shift(sev, +1)
        mods.append("повышено: prod-контекст файла/профиля")
    elif is_test_or_doc_path(path):
        sev = _shift(sev, -1)
        mods.append("понижено: тестовый/документационный путь")
    reason = f"{cls}: базовый уровень {base} — {why}"
    if mods:
        reason += "; " + "; ".join(mods)
    return sev, reason


# --- SAST ----------------------------------------------------------------------------------------------------

# rule class -> (level when reachable without authentication, level inside protected area, explanation)
SAST_MATRIX: dict[str, tuple[str, str, str]] = {
    "sql-injection": ("CRITICAL", "HIGH", "внедрение SQL позволяет читать/менять данные БД"),
    "route-authorization": ("HIGH", "HIGH", "служебный маршрут доступен без нужной роли"),
    "object-authorization": ("HIGH", "HIGH", "доступ к чужим объектам по идентификатору (IDOR/BOLA)"),
    "credentialed-cors": ("HIGH", "MEDIUM", "любой сайт может читать ответы с cookie пользователя"),
    "tls-verification": ("HIGH", "MEDIUM", "отключённая проверка TLS делает возможным MITM"),
    "unsafe-deserialization": ("CRITICAL", "HIGH", "десериализация недоверенных данных ведёт к RCE"),
    "path-traversal": ("HIGH", "HIGH", "чтение/запись произвольных файлов сервера"),
    "weak-crypto": ("MEDIUM", "MEDIUM", "слабый алгоритм или предсказуемый генератор"),
    "hardcoded-credentials": ("HIGH", "HIGH", "учётные данные пользователей приложения в коде"),
    "missing-input-validation": ("MEDIUM", "LOW", "данные запроса без валидации"),
    "insecure-endpoint": ("MEDIUM", "LOW", "небезопасная настройка эндпоинта/отладки"),
    "csrf-disabled": ("MEDIUM", "LOW", "CSRF-защита отключена при сессионной аутентификации"),
}


def sast_severity(cls: str, unauthenticated: bool | None = None) -> tuple[str, str]:
    open_lv, protected_lv, why = SAST_MATRIX.get(cls, ("MEDIUM", "MEDIUM", "проблема безопасности кода"))
    if unauthenticated is True:
        return open_lv, f"{cls}: {why}; обработчик доступен без аутентификации → {open_lv}"
    if unauthenticated is False:
        return protected_lv, f"{cls}: {why}; код внутри защищённой области → {protected_lv}"
    return protected_lv, f"{cls}: {why}; достижимость не установлена → базовый уровень {protected_lv}"

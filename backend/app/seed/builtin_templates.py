"""Built-in template library (author «System»). Idempotent: existing built-ins (by name) are not duplicated."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app import models as m
from app.db import Database
from app.templates_lib import placeholder


def _graph(nodes: list[tuple[str, str, dict]], edges: list[tuple[str, str, str, str]]) -> dict:
    return {"schema_version": 1,
            "nodes": [{"id": i, "type": t, "position": {"x": 0, "y": 0}, "config": c} for i, t, c in nodes],
            "edges": [{"id": f"e{k}", "source": s, "source_port": sp, "target": d, "target_port": dp}
                      for k, (s, sp, d, dp) in enumerate(edges)]}


def _p(name: str, type_: str = "string", description: str = "", kind: str | None = None, default: Any = None,
       required: bool = True) -> dict:
    return {"name": name, "type": type_, "kind": kind, "description": description, "default": default,
            "required": required}


SRC_PATH = ("src", "source.repo", {"mode": "path", "path": placeholder("src.path")})
SRC_PATH_PARAM = _p("src.path", description="Каталог проекта внутри APP_SCAN_ROOTS (или замените режим источника)")
SRC_PROJECT = ("src", "source.repo", {"mode": "project"})
SCANNERS = [("sec", "scanner.secrets", {}), ("sca", "scanner.sca", {}), ("sast", "scanner.sast", {})]
SCAN_EDGES = [("src", "out", "sec", "in"), ("src", "out", "sca", "in"), ("src", "out", "sast", "in"),
              ("sec", "out", "merge", "in"), ("sca", "out", "merge", "in"), ("sast", "out", "merge", "in")]


def builtin_templates() -> list[dict]:
    single = []
    for name, cat, node, desc in [
        ("Проверка секретов", "Secrets", ("scan", "scanner.secrets", {}),
         "Поиск захардкоженных паролей, токенов и ключей (включая собранные из констант Kotlin) и отчёт в трёх форматах."),
        ("SCA зависимостей", "SCA", ("scan", "scanner.sca", {}),
         "Проверка зависимостей Gradle (Kotlin DSL, version catalog, lockfile) по справочнику CVE/GHSA."),
        ("SAST Kotlin/Spring", "SAST", ("scan", "scanner.sast", {}),
         "Статический анализ Kotlin/Spring Boot: SQL-инъекции, TLS, CORS, маршруты, IDOR и другие правила."),
    ]:
        single.append({"name": name, "category": cat, "description": desc, "tags": ["kotlin", cat.lower()],
                       "graph": _graph([("t", "trigger.manual", {}), SRC_PATH, node,
                                        ("exp", "output.report_export", {})],
                                       [("t", "out", "src", "in"), ("src", "out", "scan", "in"),
                                        ("scan", "out", "exp", "in")]),
                       "parameters": [SRC_PATH_PARAM]})
    return single + [
        {"name": "Полный аудит безопасности + AI + Telegram", "category": "Full Security Audit",
         "description": "Секреты, SCA и SAST, при находках уровня High и выше — AI-объяснение, отчёт и уведомление "
                        "в Telegram с report.md.",
         "tags": ["audit", "ai", "telegram"],
         "graph": _graph([("t", "trigger.manual", {}), SRC_PATH, *SCANNERS, ("merge", "logic.merge", {}),
                          ("if", "logic.if_else", {"expression": "severity.max >= HIGH"}), ("ai", "ai.report", {}),
                          ("exp", "output.report_export", {}),
                          ("tg", "notify.telegram", {"bot_token": placeholder("tg.bot_token"),
                                                     "chat_id": placeholder("tg.chat_id")})],
                         [("t", "out", "src", "in"), *SCAN_EDGES, ("merge", "out", "if", "in"),
                          ("if", "true", "ai", "in"), ("merge", "out", "exp", "in"), ("ai", "out", "exp", "ai"),
                          ("exp", "out", "tg", "in"), ("ai", "out", "tg", "in"), ("if", "true", "tg", "in")]),
         "parameters": [SRC_PATH_PARAM, _p("tg.bot_token", "credential", "Токен Telegram-бота", "telegram"),
                        _p("tg.chat_id", description="Chat ID получателя")]},
        {"name": "CI gate: упасть на Critical", "category": "CI/CD",
         "description": "Запуск из CI (CLI или вебхук): три сканера, официальный submission.json и gate, который "
                        "ломает сборку при Critical.",
         "tags": ["ci", "github", "gitlab", "gate"],
         "graph": _graph([("t", "trigger.webhook", {"provider": "ci"}), SRC_PROJECT, *SCANNERS,
                          ("merge", "logic.merge", {}), ("gate", "output.ci_gate", {"fail_on": "CRITICAL"}),
                          ("exp", "output.report_export", {})],
                         [("t", "out", "src", "in"), *SCAN_EDGES, ("merge", "out", "gate", "in"),
                          ("merge", "out", "exp", "in")]),
         "parameters": []},
        {"name": "Ежедневная проверка + e-mail", "category": "Notifications",
         "description": "Каждый день в 14:00 проверяет код на секреты и отправляет отчёт на почту.",
         "tags": ["schedule", "email", "secrets"],
         "graph": _graph([("t", "trigger.schedule", {"cron": "0 14 * * *"}), SRC_PATH, ("sec", "scanner.secrets", {}),
                          ("exp", "output.report_export", {}),
                          ("mail", "notify.smtp", {"host": placeholder("mail.host"), "port": 587,
                                                   "from_addr": placeholder("mail.from_addr"),
                                                   "to": placeholder("mail.to"),
                                                   "password": placeholder("mail.password")})],
                         [("t", "out", "src", "in"), ("src", "out", "sec", "in"), ("sec", "out", "exp", "in"),
                          ("exp", "out", "mail", "in"), ("sec", "out", "mail", "in")]),
         "parameters": [SRC_PATH_PARAM, _p("mail.host", description="SMTP-сервер"),
                        _p("mail.from_addr", description="Адрес отправителя"),
                        _p("mail.to", "array", "Получатели (через запятую)"),
                        _p("mail.password", "credential", "Пароль SMTP", "smtp", required=False)]},
        {"name": "Проверка по webhook + Webhook-уведомление", "category": "Notifications",
         "description": "Push/PR в GitHub запускает проверку; итог с маскированными находками уходит на ваш HTTP "
                        "webhook с подписью HMAC.",
         "tags": ["webhook", "github", "hmac"],
         "graph": _graph([("t", "trigger.webhook", {"provider": "github", "secret": placeholder("t.secret")}),
                          SRC_PROJECT, *SCANNERS, ("merge", "logic.merge", {}),
                          ("hook", "notify.webhook", {"url": placeholder("hook.url"),
                                                      "hmac_secret": placeholder("hook.hmac_secret")})],
                         [("t", "out", "src", "in"), *SCAN_EDGES, ("merge", "out", "hook", "in")]),
         "parameters": [_p("t.secret", "credential", "Секрет вебхука GitHub", "webhook_secret"),
                        _p("hook.url", description="URL получателя уведомления"),
                        _p("hook.hmac_secret", "credential", "Секрет подписи HMAC", "webhook_secret",
                           required=False)]},
    ]


def seed_builtin_templates(db: Database) -> int:
    created = 0
    with db.session() as s:
        existing = set(s.scalars(select(m.Template.name).where(m.Template.builtin.is_(True))))
        for t in builtin_templates():
            if t["name"] in existing:
                continue
            s.add(m.Template(name=t["name"], description=t["description"], category=t["category"], tags=t["tags"],
                             version="1.0.0", author_name="System", builtin=True, graph=t["graph"],
                             parameters=t["parameters"]))
            created += 1
        s.commit()
    return created

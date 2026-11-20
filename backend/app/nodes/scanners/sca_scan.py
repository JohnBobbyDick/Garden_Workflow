from __future__ import annotations

import asyncio
from pathlib import Path

from app.analyzers.sca.detector import scan_sca
from app.analyzers.sca.vulndb import VulnDB
from app.config import get_settings
from app.core.repo_guard import RepoGuardError, check_scan_path
from app.engine.data import findings_envelope
from app.nodes.base import BaseNode, Port, register_node
from app.nodes.schema import obj, prop


def _load_db(path: str | None) -> VulnDB:
    if not path:
        return VulnDB.load()
    p = Path(path).resolve()
    settings = get_settings()
    roots = settings.scan_root_paths() + [settings.data_dir.resolve()]
    if not any(p.is_relative_to(r) for r in roots):
        raise RepoGuardError("справочник уязвимостей должен лежать внутри APP_SCAN_ROOTS или каталога данных")
    check_scan_path(str(p.parent), roots)
    return VulnDB.load(p)


@register_node
class ScaScanner(BaseNode):
    type = "scanner.sca"
    category = "scanner"
    icon = "package"
    timeout_seconds = 600
    title = {"ru": "Проверка зависимостей (SCA)", "en": "Dependency check (SCA)"}
    description = {
        "ru": "Собственный разбор Gradle (Kotlin DSL, Groovy, version catalog, gradle.properties, lockfile) и "
              "сверка с локальным справочником уязвимостей; CVSS считается собственным калькулятором.",
        "en": "Own Gradle parsing (Kotlin DSL, Groovy, version catalog, gradle.properties, lockfile) matched "
              "against the local vulnerability database; CVSS computed by our own calculator."}
    inputs = [Port("in", "repo", title_ru="Код", title_en="Code")]
    outputs = [Port("out", "findings", title_ru="Находки", title_en="Findings")]
    config_schema = obj({
        "database_path": prop("string", "Справочник уязвимостей (JSON)", "Vulnerability database (JSON)",
                              "Пусто — встроенный справочник организаторов", "Empty — built-in organizer database"),
        "include_transitive": prop("boolean", "Транзитивные зависимости", "Transitive dependencies",
                                   "Записи lockfile без явного объявления", "Lockfile entries not declared",
                                   default=False),
        "include_test_scopes": prop("boolean", "Тестовые конфигурации", "Test configurations", default=True),
    })

    async def execute(self, ctx, inputs, config):
        root = inputs["in"].data["root"]
        db = _load_db(config.get("database_path"))
        result = await asyncio.to_thread(scan_sca, root, db, bool(config.get("include_transitive")),
                                         bool(config.get("include_test_scopes", True)))
        for f in result.findings:
            f.node_id = ctx.node_id
        for note in result.notes:
            ctx.log("info", f"{note.get('path')}:{note.get('line')}: {note.get('message')}")
        if ctx.has_services:
            ctx.services.record_findings(ctx.node_id, result.findings)
        ctx.log("info", f"SCA: {len(result.findings)} находок, справочник {db.source}")
        return {"out": findings_envelope(result.findings, ctx.node_id, extra={"notes": result.notes})}

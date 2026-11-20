from __future__ import annotations

import asyncio

from app.analyzers.sast.detector import ALL_RULES, SastConfig, scan_sast
from app.engine.data import findings_envelope
from app.nodes.base import BaseNode, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class SastScanner(BaseNode):
    type = "scanner.sast"
    category = "scanner"
    icon = "bug"
    timeout_seconds = 600
    title = {"ru": "SAST Kotlin / Spring", "en": "SAST Kotlin / Spring"}
    description = {
        "ru": "Собственный статический анализ Kotlin/Spring Boot на tree-sitter: taint, граф вызовов по DI, "
              "правила Spring Security (SQLi, TLS, CORS, маршруты, IDOR и др.).",
        "en": "Own tree-sitter based static analysis for Kotlin/Spring Boot: taint, DI call graph, Spring Security "
              "rules (SQLi, TLS, CORS, routes, IDOR and more)."}
    inputs = [Port("in", "repo", title_ru="Код", title_en="Code")]
    outputs = [Port("out", "findings", title_ru="Находки", title_en="Findings")]
    config_schema = obj({
        "disabled_rules": prop("array", "Отключённые правила", "Disabled rules",
                               items={"type": "string", "enum": list(ALL_RULES)}, default=[], uniqueItems=True),
        "min_confidence": prop("number", "Минимальная уверенность", "Minimum confidence", minimum=0, maximum=1,
                               default=0.0),
        "include": prop("array", "Включить (glob)", "Include (glob)", items={"type": "string"}, default=[]),
        "exclude": prop("array", "Исключить (glob)", "Exclude (glob)", items={"type": "string"}, default=[]),
    })

    async def execute(self, ctx, inputs, config):
        root = inputs["in"].data["root"]
        cfg = SastConfig(include=config.get("include") or None, exclude=config.get("exclude") or None,
                         disabled_rules=list(config.get("disabled_rules") or []),
                         min_confidence=float(config.get("min_confidence") or 0.0))
        findings = await asyncio.to_thread(scan_sast, root, cfg)
        for f in findings:
            f.node_id = ctx.node_id
        if ctx.has_services:
            ctx.services.record_findings(ctx.node_id, findings)
        ctx.log("info", f"SAST: {len(findings)} находок")
        return {"out": findings_envelope(findings, ctx.node_id)}

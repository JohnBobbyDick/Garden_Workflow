from __future__ import annotations

import asyncio

from app.analyzers.secrets.detector import SecretsConfig, scan_secrets
from app.engine.data import findings_envelope
from app.nodes.base import BaseNode, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class SecretsScanner(BaseNode):
    type = "scanner.secrets"
    category = "scanner"
    icon = "key"
    timeout_seconds = 600
    title = {"ru": "Поиск секретов", "en": "Secrets scanner"}
    description = {
        "ru": "Собственный детектор: сигнатуры токенов, контекст имён, разрешение констант Kotlin (AST), "
              "fallback-значения, энтропия. Значения маскируются.",
        "en": "Own detector: token signatures, name context, Kotlin constant resolution (AST), fallback values, "
              "entropy. Values are masked."}
    inputs = [Port("in", "repo", title_ru="Код", title_en="Code")]
    outputs = [Port("out", "findings", title_ru="Находки", title_en="Findings")]
    config_schema = obj({
        "include": prop("array", "Включить (glob)", "Include (glob)", items={"type": "string"}, default=[]),
        "exclude": prop("array", "Исключить (glob)", "Exclude (glob)", items={"type": "string"}, default=[]),
        "entropy_threshold": prop("number", "Порог энтропии", "Entropy threshold", minimum=2.5, maximum=6.0,
                                  default=4.0),
        "heuristics": prop("boolean", "Эвристика неизвестных секретов", "Unknown-secret heuristics", default=True),
    })

    async def execute(self, ctx, inputs, config):
        root = inputs["in"].data["root"]
        cfg = SecretsConfig(include=config.get("include") or None, exclude=config.get("exclude") or None,
                            entropy_threshold=float(config.get("entropy_threshold", 4.0)),
                            heuristics=bool(config.get("heuristics", True)))
        findings = await asyncio.to_thread(scan_secrets, root, cfg)
        for f in findings:
            f.node_id = ctx.node_id
        if ctx.has_services:
            ctx.services.record_findings(ctx.node_id, findings)
        ctx.log("info", f"секреты: {len(findings)} находок")
        return {"out": findings_envelope(findings, ctx.node_id)}

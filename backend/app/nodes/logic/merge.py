from __future__ import annotations

from app.analyzers.common.finding import dedupe_findings
from app.engine.data import findings_envelope, findings_of
from app.nodes.base import BaseNode, Port, register_node
from app.nodes.schema import obj


@register_node
class Merge(BaseNode):
    type = "logic.merge"
    category = "logic"
    icon = "merge"
    title = {"ru": "Объединение находок", "en": "Merge findings"}
    description = {"ru": "Объединяет несколько наборов находок и убирает дубликаты (одна проблема — одна находка).",
                   "en": "Merges several finding sets and removes duplicates (one problem — one finding)."}
    inputs = [Port("in", "findings", multiple=True, title_ru="Находки", title_en="Findings")]
    outputs = [Port("out", "findings", title_ru="Все находки", title_en="All findings")]
    config_schema = obj({})

    async def execute(self, ctx, inputs, config):
        merged = dedupe_findings(findings_of(inputs["in"]))
        return {"out": findings_envelope(merged, ctx.node_id)}

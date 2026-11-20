from __future__ import annotations

from app.analyzers.common.finding import SEVERITY_ORDER
from app.engine.data import findings_envelope, findings_of
from app.nodes.base import BaseNode, Port, register_node
from app.nodes.schema import SEVERITY_ENUM, obj, prop


@register_node
class SeverityFilter(BaseNode):
    type = "logic.severity_filter"
    category = "logic"
    icon = "filter"
    title = {"ru": "Фильтр по критичности", "en": "Severity filter"}
    description = {"ru": "Оставляет находки не ниже заданной критичности и выбранных категорий/классов.",
                   "en": "Keeps findings at or above a severity and of selected categories/classes."}
    inputs = [Port("in", "findings", title_ru="Находки", title_en="Findings")]
    outputs = [Port("out", "findings", title_ru="Отфильтровано", title_en="Filtered")]
    config_schema = obj({
        "min_severity": prop("string", "Минимальная критичность", "Minimum severity", enum=SEVERITY_ENUM,
                             default="LOW"),
        "categories": prop("array", "Категории (пусто — все)", "Categories (empty — all)",
                           items={"type": "string", "enum": ["SECRET", "SCA", "SAST"]}, default=[]),
        "classes": prop("array", "Классы (пусто — все)", "Classes (empty — all)", items={"type": "string"}, default=[]),
        "min_confidence": prop("number", "Минимальная уверенность", "Minimum confidence", minimum=0, maximum=1,
                               default=0.0),
    })

    async def execute(self, ctx, inputs, config):
        floor = SEVERITY_ORDER[config.get("min_severity", "LOW")]
        cats, classes = set(config.get("categories") or []), set(config.get("classes") or [])
        out = [f for f in findings_of(inputs["in"]) if SEVERITY_ORDER[f.severity] >= floor
               and (not cats or f.category in cats) and (not classes or f.cls in classes)
               and f.confidence >= float(config.get("min_confidence") or 0)]
        return {"out": findings_envelope(out, ctx.node_id)}

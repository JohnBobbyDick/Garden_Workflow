from app.engine.data import findings_of, severity_counts
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class SeverityBudget(BaseNode):
    type = "analysis.severity_budget"
    category = "analysis"
    icon = "scale"
    title = {"ru": "Лимиты по критичности", "en": "Severity budgets"}
    description = {"ru": "Сверяет число находок каждого уровня с лимитом. Возвращает within_budget и превышения в excess для ветвления.",
                   "en": "Compares counts per severity with configured limits. Returns within_budget and excess counts for routing."}
    inputs = [Port("in", "findings", title_ru="Находки", title_en="Findings")]
    outputs = [Port("out", "json", title_ru="Проверка лимитов", title_en="Budget check")]
    config_schema = obj({
        level: prop("integer", f"Лимит {level.upper()}", f"{level.upper()} limit",
                    "Пустое поле снимает лимит." if level != "critical" else "По умолчанию 0.",
                    "Leave empty for unlimited." if level != "critical" else "Defaults to 0.",
                    minimum=0, **({"default": 0} if level == "critical" else {}))
        for level in ("critical", "high", "medium", "low")
    })

    async def execute(self, ctx, inputs, config):
        counts = severity_counts(findings_of(inputs["in"]))
        excess = {level.upper(): counts[level] - limit for level, limit in config.items() if counts[level] > limit}
        return {"out": Envelope.make("json", {"within_budget": not excess, "excess": excess, "counts": counts},
                                     ctx.node_id)}

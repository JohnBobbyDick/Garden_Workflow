from app.nodes.base import BaseNode, Envelope, Port, register_node


@register_node
class AICoverage(BaseNode):
    type = "analysis.ai_coverage"
    category = "analysis"
    icon = "check"
    title = {"ru": "Покрытие AI-отчёта", "en": "AI report coverage"}
    description = {
        "ru": "Считает, для скольких находок валидатор принял объяснение модели. Поле needs_review истинно, "
              "если хотя бы одно объяснение сформировано детерминированно.",
        "en": "Counts findings with an accepted AI explanation. needs_review is true when at least one finding "
              "received a deterministic explanation.",
    }
    inputs = [Port("in", "report", title_ru="Отчёт ai.report", title_en="Report from ai.report")]
    outputs = [Port("out", "json", title_ru="Покрытие", title_en="Coverage")]

    async def execute(self, ctx, inputs, config):
        data = inputs["in"].data
        report = data.get("report")
        if not isinstance(report, dict) or not isinstance(report.get("findings"), list) or "ai_generated" not in data:
            raise ValueError("Подключите выход ноды ai.report.")
        total = len(report["findings"])
        accepted = data["validation"]["metrics"]["valid_items"] if data["ai_generated"] else 0
        result = {"total": total, "explained_by_ai": accepted, "deterministic": total - accepted,
                  "needs_review": accepted < total}
        return {"out": Envelope.make("json", result, ctx.node_id, f"{accepted}/{total}")}

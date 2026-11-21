from app.engine.data import findings_envelope, findings_of
from app.nodes.base import BaseNode, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class TopFindings(BaseNode):
    type = "analysis.top_findings"
    category = "analysis"
    icon = "filter"
    title = {"ru": "Первые N находок по риску", "en": "Top findings by risk"}
    description = {"ru": "Выбирает самые критичные находки. При равной критичности выше находки с большей уверенностью.",
                   "en": "Selects the highest-severity findings, breaking ties by confidence."}
    inputs = [Port("in", "findings", title_ru="Находки", title_en="Findings")]
    outputs = [Port("out", "findings", title_ru="Приоритетные", title_en="Prioritized")]
    config_schema = obj({"limit": prop("integer", "Количество находок", "Number of findings",
                                       minimum=1, maximum=1000, default=10)})

    async def execute(self, ctx, inputs, config):
        ranked = sorted(findings_of(inputs["in"]), key=lambda f: (-f.severity_rank, -f.confidence, f.path, f.line, f.id))
        return {"out": findings_envelope(ranked[:config.get("limit", 10)], ctx.node_id)}

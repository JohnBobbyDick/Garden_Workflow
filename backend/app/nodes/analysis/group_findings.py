from collections import Counter

from app.engine.data import findings_of
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class GroupFindings(BaseNode):
    type = "analysis.group_findings"
    category = "analysis"
    icon = "dashboard"
    title = {"ru": "Группировка находок", "en": "Group findings"}
    description = {"ru": "Считает находки по критичности, категории или правилу. Возвращает total и словарь counts.",
                   "en": "Counts findings by severity, category, or rule. Returns total and a counts object."}
    inputs = [Port("in", "findings", title_ru="Находки", title_en="Findings")]
    outputs = [Port("out", "json", title_ru="Сводка", title_en="Counts")]
    config_schema = obj({"group_by": prop("string", "Группировать по", "Group by",
                                           enum=["severity", "category", "rule_id"], default="severity")})

    async def execute(self, ctx, inputs, config):
        findings = findings_of(inputs["in"])
        field = config.get("group_by", "severity")
        counts = Counter(getattr(f, field) for f in findings)
        data = {"total": len(findings), "counts": dict(sorted(counts.items()))}
        return {"out": Envelope.make("json", data, ctx.node_id, str(len(findings)))}

from __future__ import annotations

from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class SetValue(BaseNode):
    type = "logic.set_value"
    category = "logic"
    icon = "variable"
    title = {"ru": "Задать значения", "en": "Set values"}
    description = {"ru": "Создаёт JSON со значениями (переменные для условий и шаблонов); объединяется с JSON-входом.",
                   "en": "Emits JSON values (variables for conditions and templates), merged with a JSON input."}
    inputs = [Port("in", "any", required=False, title_ru="Данные", title_en="Data")]
    outputs = [Port("out", "json", title_ru="Значения", title_en="Values")]
    config_schema = obj({
        "values": prop("object", "Значения", "Values", default={}, **{"x-widget": "keyvalue"}),
    })

    async def execute(self, ctx, inputs, config):
        base = dict(inputs["in"].data) if "in" in inputs and inputs["in"].type == "json" else {}
        base.update(config.get("values") or {})
        return {"out": Envelope.make("json", base, ctx.node_id, ", ".join(sorted(base))[:200])}

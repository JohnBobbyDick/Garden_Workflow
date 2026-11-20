from __future__ import annotations

from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj


@register_node
class ManualTrigger(BaseNode):
    type = "trigger.manual"
    category = "trigger"
    icon = "play"
    title = {"ru": "Ручной запуск", "en": "Manual trigger"}
    description = {"ru": "Запуск сценария кнопкой «Запустить» в редакторе или через API.",
                   "en": "Starts the workflow from the Run button or the API."}
    outputs = [Port("out", "trigger", title_ru="Старт", title_en="Start")]
    config_schema = obj({})

    async def execute(self, ctx, inputs, config):
        payload = {"trigger_type": ctx.run.trigger_type, "triggered_by": ctx.run.triggered_by,
                   "source": ctx.run.trigger_payload.get("source") or {}, "payload": ctx.run.trigger_payload}
        return {"out": Envelope.make("trigger", payload, ctx.node_id, "запуск вручную")}

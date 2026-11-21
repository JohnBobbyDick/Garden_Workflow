from app.engine.data import build_context
from app.engine.templating import render_template
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class RenderText(BaseNode):
    type = "logic.render_text"
    category = "logic"
    icon = "variable"
    title = {"ru": "Текст по шаблону", "en": "Render text template"}
    description = {"ru": "Формирует текст из полей входа и данных запуска. Подходит для сообщения или последующей обработки текста.",
                   "en": "Builds a text message from input fields and run metadata for reuse in later steps."}
    inputs = [Port("in", "any", title_ru="Данные", title_en="Data")]
    outputs = [Port("out", "text", title_ru="Текст", title_en="Text")]
    config_schema = obj({"template": prop("string", "Шаблон текста", "Text template",
                                          "Например, {{run.id}}, {{findings.count}}, {{data.total}}. До 65 536 символов результата.",
                                          "Use {{run.id}}, {{findings.count}} or {{data.total}}. Output limit is 65,536 characters.",
                                          default="{{workflow.name}} ({{run.id}})", minLength=1, maxLength=2048,
                                          **{"x-widget": "template"})})

    async def execute(self, ctx, inputs, config):
        # JSON keys belong to the input payload, including user-defined keys named "findings" or "verdict".
        if inputs["in"].type == "json":
            context = build_context({}, ctx.run, ctx.state)
            context["data"] = inputs["in"].data
        else:
            context = build_context(inputs, ctx.run, ctx.state)
        text = render_template(config["template"], context, max_length=65536)
        return {"out": Envelope.make("text", {"text": ctx.masker.mask(text)}, ctx.node_id)}

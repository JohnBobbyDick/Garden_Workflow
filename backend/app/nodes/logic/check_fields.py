from app.engine.expressions import _MISSING, resolve_path
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class CheckFields(BaseNode):
    type = "logic.check_fields"
    category = "logic"
    icon = "check"
    title = {"ru": "Проверка обязательных полей JSON", "en": "Check required JSON fields"}
    description = {"ru": "Проверяет наличие полей по путям через точку. Перечисляет отсутствующие поля и поля со значением null. Значения 0, false и пустая строка допустимы.",
                   "en": "Checks dotted paths, reporting missing and null fields separately. Zero, false and empty strings are valid."}
    inputs = [Port("in", "json", title_ru="Данные", title_en="Data")]
    outputs = [Port("out", "json", title_ru="Результат проверки", title_en="Check result")]
    config_schema = obj({
        "paths": prop("array", "Обязательные пути", "Required paths", "Например, counts.HIGH",
                      "For example, counts.HIGH", minItems=1, uniqueItems=True, maxItems=100,
                      items={"type": "string", "maxLength": 160, "pattern": r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$"}),
    }, required=["paths"])

    async def execute(self, ctx, inputs, config):
        missing = []
        null_fields = []
        for path in config["paths"]:
            value = resolve_path(inputs["in"].data, path)
            if value is _MISSING:
                missing.append(path)
            elif value is None:
                null_fields.append(path)
        data = {"valid": not (missing or null_fields), "missing": missing, "null_fields": null_fields}
        return {"out": Envelope.make("json", ctx.masker.mask_obj(data), ctx.node_id)}

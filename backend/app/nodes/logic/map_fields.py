from app.engine.expressions import ExpressionError, evaluate, parse, resolve_path
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop

# A scalar output cannot occupy the envelope's reserved findings collection.
OUTPUT_KEY = r"^[A-Za-z][A-Za-z0-9_]{0,63}$"
INPUT_PATH = r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$"
FIELDS = prop("object", "Соответствие полей", "Field mapping",
              "Ключ — имя поля результата, значение — путь (counts.HIGH) или условие (=total > 0).",
              "Use the output name as the key and a path (counts.HIGH) or a condition (=total > 0) as its value.",
              minProperties=1, maxProperties=24,
              propertyNames={"pattern": OUTPUT_KEY, "not": {"enum": ["findings", "constructor", "prototype"]}},
              additionalProperties={"type": "string", "maxLength": 512,
                                    "anyOf": [{"pattern": INPUT_PATH}, {"pattern": "^=."}]})


@register_node
class MapFields(BaseNode):
    type = "logic.map_fields"
    category = "logic"
    icon = "variable"
    title = {"ru": "Преобразование JSON", "en": "Map JSON fields"}
    description = {"ru": "Собирает JSON из выбранных полей. Отсутствующие поля, объекты и массивы дают null.",
                   "en": "Builds JSON from selected scalar fields. Missing fields, objects and arrays yield null."}
    inputs = [Port("in", "json", title_ru="Исходный JSON", title_en="Source JSON")]
    outputs = [Port("out", "json", title_ru="Результат", title_en="Result")]
    config_schema = obj({"fields": FIELDS}, required=["fields"])

    @classmethod
    def validate_config(cls, config):
        fields = config.get("fields")
        if isinstance(fields, dict):
            for name, source in fields.items():
                if isinstance(source, str) and source.startswith("="):
                    try:
                        parse(source[1:])
                    except ExpressionError as exc:
                        return [f"Ошибка в условии поля «{name}»: {exc}"]
        return []

    async def execute(self, ctx, inputs, config):
        result = {}
        for name, path in config["fields"].items():
            if path.startswith("="):
                result[name] = evaluate(path[1:], inputs["in"].data)
                continue
            value = resolve_path(inputs["in"].data, path)
            if isinstance(value, str):
                result[name] = ctx.masker.mask(value)
            else:
                result[name] = value if isinstance(value, (int, float, bool)) else None
        return {"out": Envelope.make("json", result, ctx.node_id)}

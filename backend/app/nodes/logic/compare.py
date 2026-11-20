from __future__ import annotations

import json
from typing import Any

from app.engine.data import build_context
from app.engine.expressions import _MISSING, _compare, resolve_path
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop

OPERATORS = ["==", "!=", ">", ">=", "<", "<=", "in", "contains"]


def _operand(raw: Any, ctx: dict) -> Any:
    """A dotted path into the context (``findings.count``, ``data.x``) or a literal (number/JSON/string)."""
    if isinstance(raw, str):
        v = resolve_path(ctx, raw.strip()) if raw.strip() else _MISSING
        if v is not _MISSING:
            return v
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return raw
    return raw


@register_node
class Compare(BaseNode):
    type = "logic.compare"
    category = "logic"
    icon = "scale"
    title = {"ru": "Сравнение", "en": "Compare"}
    description = {"ru": "Сравнивает два значения (числа, строки, уровни критичности): путь к данным или литерал.",
                   "en": "Compares two values (numbers, strings, severities): a data path or a literal."}
    inputs = [Port("in", "any", required=False, title_ru="Данные", title_en="Data")]
    outputs = [Port("result", "bool", title_ru="Результат", title_en="Result"),
               Port("true", "any", title_ru="Да", title_en="True"), Port("false", "any", title_ru="Нет", title_en="False")]
    config_schema = obj({
        "left": prop("string", "Слева", "Left", "Путь (findings.count, data.x) или значение"),
        "operator": prop("string", "Оператор", "Operator", enum=OPERATORS, default="=="),
        "right": prop("string", "Справа", "Right", "Путь или значение"),
    }, required=["left", "operator", "right"])

    async def execute(self, ctx, inputs, config):
        c = build_context(inputs, ctx.run, ctx.state)
        left, right = _operand(config["left"], c), _operand(config["right"], c)
        value = _compare(config["operator"], left, right)
        passthrough = inputs.get("in") or Envelope.make("bool", {"value": value}, ctx.node_id)
        ctx.log("info", f"{left!r} {config['operator']} {right!r} → {value}")
        return {"result": Envelope.make("bool", {"value": value, "left": left, "right": right}, ctx.node_id,
                                        str(value).lower()),
                ("true" if value else "false"): passthrough}

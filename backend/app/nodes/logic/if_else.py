from __future__ import annotations

from app.engine.data import build_context
from app.engine.expressions import ExpressionError, evaluate, parse
from app.nodes.base import BaseNode, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class IfElse(BaseNode):
    type = "logic.if_else"
    category = "logic"
    icon = "split"
    title = {"ru": "Условие IF/ELSE", "en": "IF / ELSE"}
    description = {
        "ru": "Ветвление по выражению: findings.count, severity.max, category, new_findings.count, verdict, "
              "score.value, score.delta; сравнения и and/or/not. Данные входа передаются в выбранную ветку.",
        "en": "Branches on an expression over findings.count, severity.max, category, new_findings.count, verdict, "
              "score.value, score.delta with comparisons and and/or/not. Input data flows into the chosen branch."}
    inputs = [Port("in", "any", title_ru="Данные", title_en="Data")]
    outputs = [Port("true", "any", title_ru="Да", title_en="True"), Port("false", "any", title_ru="Нет", title_en="False")]
    branch_outputs = ("true", "false")
    config_schema = obj({
        "expression": prop("string", "Условие", "Condition", "Например: severity.max >= HIGH and findings.count > 0",
                           "E.g. severity.max >= HIGH and findings.count > 0", minLength=1,
                           **{"x-widget": "expression"}),
    }, required=["expression"])

    @classmethod
    def validate_config(cls, config):
        try:
            parse(str(config.get("expression") or ""))
        except ExpressionError as exc:
            return [f"ошибка в условии: {exc}"]
        return []

    async def execute(self, ctx, inputs, config):
        env = inputs["in"]
        result = evaluate(config["expression"], build_context(inputs, ctx.run, ctx.state))
        ctx.log("info", f"условие «{config['expression']}» → {'да' if result else 'нет'}")
        return {"true" if result else "false": env}

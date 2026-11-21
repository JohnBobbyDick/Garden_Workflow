from app.engine.data import findings_envelope, findings_of
from app.nodes.base import BaseNode, Port, register_node


@register_node
class FindingDelta(BaseNode):
    type = "logic.finding_delta"
    category = "logic"
    icon = "scale"
    title = {"ru": "Сравнение наборов находок", "en": "Compare finding sets"}
    description = {"ru": "Сопоставляет два входа по стабильным ID. Общие находки содержат данные текущего набора.",
                   "en": "Compares two inputs by stable finding ID. Shared findings carry their current evidence."}
    inputs = [Port("baseline", "findings", title_ru="Базовый набор", title_en="Baseline"),
              Port("current", "findings", title_ru="Текущий набор", title_en="Current")]
    outputs = [Port("added", "findings", title_ru="Добавились", title_en="Added"),
               Port("retained", "findings", title_ru="Сохранились", title_en="Retained"),
               Port("removed", "findings", title_ru="Исчезли", title_en="Removed")]

    async def execute(self, ctx, inputs, config):
        baseline = {f.id: f for f in findings_of(inputs["baseline"])}
        current = {f.id: f for f in findings_of(inputs["current"])}
        return {
            "added": findings_envelope([f for key, f in current.items() if key not in baseline], ctx.node_id),
            "retained": findings_envelope([f for key, f in current.items() if key in baseline], ctx.node_id),
            "removed": findings_envelope([f for key, f in baseline.items() if key not in current], ctx.node_id),
        }

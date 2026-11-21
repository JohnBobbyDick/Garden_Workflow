from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class JoinJson(BaseNode):
    type = "logic.join_json"
    category = "logic"
    icon = "merge"
    title = {"ru": "Объединение двух JSON", "en": "Join JSON objects"}
    description = {"ru": "Соединяет поля верхнего уровня из двух входов. При совпадении имён можно выбрать приоритет или остановить ноду с ошибкой.",
                   "en": "Joins top-level fields from two inputs. Choose which side wins on duplicate keys or fail the node."}
    inputs = [Port("left", "json", title_ru="Левый", title_en="Left"),
              Port("right", "json", title_ru="Правый", title_en="Right")]
    outputs = [Port("out", "json", title_ru="Объединённый JSON", title_en="Joined JSON")]
    config_schema = obj({"conflict": prop("string", "При совпадении имён полей", "On duplicate keys",
                                          enum=["error", "left", "right"], default="error")})

    async def execute(self, ctx, inputs, config):
        left, right = inputs["left"].data, inputs["right"].data
        if config["conflict"] == "error" and left.keys() & right.keys():
            raise ValueError("Совпадают имена полей JSON. Выберите приоритет входа в настройках ноды.")
        merged = right | left if config["conflict"] == "left" else left | right
        return {"out": Envelope.make("json", merged, ctx.node_id)}

from app.analyzers.common.files import matches_path_glob
from app.engine.data import findings_envelope, findings_of
from app.nodes.base import BaseNode, Port, register_node
from app.nodes.schema import obj, prop

GLOB = {"type": "string", "minLength": 1, "maxLength": 256}


@register_node
class PathFilter(BaseNode):
    type = "logic.path_filter"
    category = "logic"
    icon = "folder"
    title = {"ru": "Отбор по пути файла", "en": "Filter by file path"}
    description = {"ru": "Отбирает находки по основному пути файла. Использует те же маски, что и сканеры. Исключения имеют приоритет.",
                   "en": "Matches each finding’s primary path with the scanner glob rules. Exclusions take precedence."}
    inputs = [Port("in", "findings", title_ru="Находки", title_en="Findings")]
    outputs = [Port("out", "findings", title_ru="Выбранные", title_en="Selected")]
    config_schema = obj({
        "include": prop("array", "Включить пути (пусто — все)", "Include paths (empty for all)",
                        "Например, src/** или **/*.kt", "For example, src/** or **/*.kt",
                        items=GLOB, maxItems=100, default=[]),
        "exclude": prop("array", "Исключить пути", "Exclude paths", items=GLOB, maxItems=100, default=[]),
    })

    async def execute(self, ctx, inputs, config):
        include = config["include"]
        exclude = config["exclude"]
        selected = [f for f in findings_of(inputs["in"])
                    if (not include or any(matches_path_glob(f.path, p) for p in include))
                    and not any(matches_path_glob(f.path, p) for p in exclude)]
        return {"out": findings_envelope(selected, ctx.node_id)}

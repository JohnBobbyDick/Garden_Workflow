from collections import defaultdict

from app.analyzers.common.finding import SEVERITY_ORDER
from app.engine.data import findings_of
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class FileHotspots(BaseNode):
    type = "analysis.file_hotspots"
    category = "analysis"
    icon = "folder"
    title = {"ru": "Файлы с наибольшим риском", "en": "File risk hotspots"}
    description = {"ru": "Ранжирует файлы по максимальной критичности, затем по числу находок. Учитывает основной путь находки.",
                   "en": "Ranks primary file paths by their highest severity, then by finding count."}
    inputs = [Port("in", "findings", title_ru="Находки", title_en="Findings")]
    outputs = [Port("out", "json", title_ru="Файлы", title_en="Files")]
    config_schema = obj({"limit": prop("integer", "Сколько файлов показать", "Maximum files",
                                       minimum=1, maximum=1000, default=10)})

    async def execute(self, ctx, inputs, config):
        by_path = defaultdict(list)
        for finding in findings_of(inputs["in"]):
            by_path[finding.path].append(finding.severity)
        rows = [{"path": path, "count": len(levels), "max_severity": max(levels, key=SEVERITY_ORDER.__getitem__)}
                for path, levels in by_path.items()]
        rows.sort(key=lambda r: (-SEVERITY_ORDER[r["max_severity"]], -r["count"], r["path"]))
        data = {"total_files": len(rows), "files": ctx.masker.mask_obj(rows[:config["limit"]])}
        return {"out": Envelope.make("json", data, ctx.node_id)}

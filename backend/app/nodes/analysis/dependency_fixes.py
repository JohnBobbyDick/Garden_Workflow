from collections import defaultdict

from app.engine.data import findings_of
from app.nodes.base import BaseNode, Envelope, Port, register_node


@register_node
class DependencyFixes(BaseNode):
    type = "analysis.dependency_fixes"
    category = "analysis"
    icon = "package"
    title = {"ru": "Исправленные версии зависимостей", "en": "Dependency fixes"}
    description = {"ru": "Собирает пути и известные исправленные версии по зависимости, установленной версии и бюллетеню SCA. Пустой список означает, что версия исправления неизвестна.",
                   "en": "Collects paths and known fixes per dependency, installed version and SCA advisory. An empty fix list means no fixed version is known."}
    inputs = [Port("in", "findings", title_ru="Находки", title_en="Findings")]
    outputs = [Port("out", "json", title_ru="Обновления", title_en="Updates")]

    async def execute(self, ctx, inputs, config):
        groups = defaultdict(list)
        for f in findings_of(inputs["in"]):
            if f.category == "SCA":
                key = (f.group or "", f.artifact or "", f.version or "", f.advisory_id or f.rule_id)
                groups[key].append(f)
        updates = []
        for (group, artifact, version, advisory), items in sorted(groups.items()):
            updates.append({
                "group": group or None, "artifact": artifact or None, "version": version or None, "advisory": advisory,
                "fixed_versions": sorted({v for f in items for v in f.fixed_versions}),
                "paths": sorted({f.path for f in items}),
            })
        return {"out": Envelope.make("json", {"updates": ctx.masker.mask_obj(updates)}, ctx.node_id)}

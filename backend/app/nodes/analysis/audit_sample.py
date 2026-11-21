from hashlib import sha256

from app.engine.data import findings_envelope, findings_of
from app.nodes.base import BaseNode, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class AuditSample(BaseNode):
    type = "analysis.audit_sample"
    category = "analysis"
    icon = "search"
    title = {"ru": "Выборка для ручной проверки", "en": "Audit sample"}
    description = {"ru": "Выбирает находки для ревью. При том же наборе ID и ключе выборка повторяется независимо от порядка входа.",
                   "en": "Samples findings for review. The same IDs and seed yield the same sample in any input order."}
    inputs = [Port("in", "findings", title_ru="Находки", title_en="Findings")]
    outputs = [Port("out", "findings", title_ru="Выборка", title_en="Sample")]
    config_schema = obj({
        "size": prop("integer", "Размер выборки", "Sample size", minimum=1, maximum=1000, default=10),
        "seed": prop("string", "Ключ выборки", "Sample seed", default="", maxLength=128),
    })

    async def execute(self, ctx, inputs, config):
        seed = config["seed"].encode() + b"\x00"
        ordered = sorted(findings_of(inputs["in"]), key=lambda f: sha256(seed + f.id.encode()).digest())
        return {"out": findings_envelope(ordered[:config["size"]], ctx.node_id)}

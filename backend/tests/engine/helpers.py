"""Small test-only nodes for exercising the engine in isolation from the product node catalog."""

from __future__ import annotations

import asyncio

from app.nodes.base import BaseNode, Envelope, NodeRegistry, Port


class TTrigger(BaseNode):
    type = "t.trigger"
    category = "trigger"
    title = {"ru": "Тестовый триггер", "en": "Test trigger"}
    outputs = [Port("out", "trigger")]

    async def execute(self, ctx, inputs, config):
        return {"out": Envelope.make("trigger", {"n": 0}, ctx.node_id)}


class TNumber(BaseNode):
    """Emits config.value (+ incoming value) as json."""

    type = "t.number"
    category = "logic"
    title = {"ru": "Число", "en": "Number"}
    inputs = [Port("in", "any")]
    outputs = [Port("out", "json")]
    config_schema = {"type": "object", "properties": {"value": {"type": "integer"}, "sleep": {"type": "number"}},
                     "required": ["value"]}

    async def execute(self, ctx, inputs, config):
        if config.get("sleep"):
            await asyncio.sleep(config["sleep"])
        prev = inputs["in"].data.get("n", 0) if "in" in inputs else 0
        ctx.log("info", f"value={config['value']}")
        return {"out": Envelope.make("json", {"n": prev + config["value"]}, ctx.node_id)}


class TSum(BaseNode):
    type = "t.sum"
    category = "logic"
    title = {"ru": "Сумма", "en": "Sum"}
    inputs = [Port("in", "json", multiple=True)]
    outputs = [Port("out", "json")]

    async def execute(self, ctx, inputs, config):
        return {"out": Envelope.make("json", {"n": sum(e.data["n"] for e in inputs["in"])}, ctx.node_id)}


class TBranch(BaseNode):
    type = "t.branch"
    category = "logic"
    title = {"ru": "Ветка", "en": "Branch"}
    inputs = [Port("in", "json")]
    outputs = [Port("true", "json"), Port("false", "json")]
    branch_outputs = ("true", "false")
    config_schema = {"type": "object", "properties": {"threshold": {"type": "integer"}}, "required": ["threshold"]}

    async def execute(self, ctx, inputs, config):
        env = inputs["in"]
        return {"true" if env.data["n"] >= config["threshold"] else "false": env}


class TFail(BaseNode):
    type = "t.fail"
    category = "logic"
    title = {"ru": "Сбой", "en": "Fail"}
    inputs = [Port("in", "any")]
    outputs = [Port("out", "json")]

    async def execute(self, ctx, inputs, config):
        raise RuntimeError("boom with secret hunter2-secret-value")


class TText(BaseNode):
    type = "t.text"
    category = "output"
    title = {"ru": "Текст", "en": "Text"}
    inputs = [Port("in", "text")]
    outputs = []
    config_schema = {"type": "object", "properties": {"token": {"type": "string", "credential_ref": True}}}

    async def execute(self, ctx, inputs, config):
        return {}


def make_registry() -> NodeRegistry:
    reg = NodeRegistry()
    for cls in (TTrigger, TNumber, TSum, TBranch, TFail, TText):
        reg.register(cls)
    return reg


def graph(nodes: list[tuple], edges: list[tuple]) -> dict:
    """nodes: (id, type, config); edges: (source, source_port, target, target_port)."""
    return {
        "schema_version": 1,
        "nodes": [{"id": i, "type": t, "position": {"x": 0, "y": 0}, "config": c} for i, t, c in nodes],
        "edges": [{"id": f"e{k}", "source": s, "source_port": sp, "target": t, "target_port": tp}
                  for k, (s, sp, t, tp) in enumerate(edges)],
    }

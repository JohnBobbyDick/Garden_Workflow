"""A new node type = one new file in app/nodes, no change to engine/API/frontend (prompt §5)."""

import uuid
from pathlib import Path

import app.nodes as nodes_pkg
from app.nodes.base import discover, get_registry
from tests.api.conftest import drain

PLUGIN = '''
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class Shout(BaseNode):
    type = "logic.shout_{suffix}"
    category = "logic"
    title = {{"ru": "Крик", "en": "Shout"}}
    description = {{"ru": "Тестовая нода расширяемости", "en": "Extensibility test node"}}
    inputs = [Port("in", "any")]
    outputs = [Port("out", "text")]
    config_schema = obj({{"word": prop("string", "Слово", "Word")}}, required=["word"])

    async def execute(self, ctx, inputs, config):
        return {{"out": Envelope.make("text", {{"text": config["word"].upper()}}, ctx.node_id, "крик")}}
'''


def test_new_node_in_single_file_is_discovered_listed_and_executed(client, db, alice):
    suffix = uuid.uuid4().hex[:8]
    path = Path(nodes_pkg.__file__).parent / "logic" / f"_ext_{suffix}.py"
    path.write_text(PLUGIN.format(suffix=suffix), encoding="utf-8")
    ntype = f"logic.shout_{suffix}"
    try:
        discover(force=True)
        catalog = client.get("/api/nodes", headers=alice.headers).json()["nodes"]
        spec = next(n for n in catalog if n["type"] == ntype)
        assert spec["config_schema"]["required"] == ["word"]
        graph = {"schema_version": 1, "nodes": [
            {"id": "t", "type": "trigger.manual", "config": {}},
            {"id": "s", "type": ntype, "config": {"word": "hello"}}],
            "edges": [{"id": "e", "source": "t", "source_port": "out", "target": "s", "target_port": "in"}]}
        wid = client.post("/api/workflows", json={"name": "ext", "graph": graph, "workspace_id": alice.workspace_id},
                          headers=alice.headers).json()["id"]
        rid = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
        drain(db)
        run = client.get(f"/api/runs/{rid}", headers=alice.headers).json()
        assert run["status"] == "success"
        node = next(n for n in run["nodes"] if n["node_id"] == "s")
        assert node["status"] == "success"
    finally:
        path.unlink(missing_ok=True)
        get_registry().unregister(ntype)

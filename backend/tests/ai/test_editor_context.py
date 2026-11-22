import json

from app.ai.providers.base import ChatResult
from app.ai.workflow_gen import apply_operations, propose_operations
from app.core.masking import Masker
from app.nodes.base import get_registry
from tests.engine.helpers import graph


async def test_followup_supplies_selection_labels_and_masked_conversation():
    requests = []

    class Provider:
        async def chat(self, messages, **kwargs):
            requests.append(messages)
            return ChatResult(json.dumps({"operations": [
                {"op": "update_node", "node_id": "second", "label": "Готово"},
            ]}), "test")

    registry = get_registry()
    g = graph([("t", "trigger.manual", {}), ("first", "logic.set_value", {}), ("second", "logic.set_value", {})],
              [("t", "out", "first", "in"), ("first", "out", "second", "in")])
    g["nodes"][1]["label"] = "Первая метка"
    masker = Masker()
    masker.register("private-context-canary")
    result, _, _ = await propose_operations(Provider(), g, "Теперь назови её Готово", registry, lambda _: False,
                                            masker, selected_node_id="second",
                                            history=[{"role": "user", "status": "applied",
                                                      "content": "Прошлый запрос private-context-canary"}])
    assert result.valid
    prompt = requests[0][-1]["content"]
    assert '"selected_node_id": "second"' in prompt and "Прошлый запрос" in prompt and "Первая метка" in prompt
    assert "private-context-canary" not in prompt


def test_disconnect_only_the_requested_target_port():
    g = graph([("left", "logic.set_value", {}), ("join", "logic.join_json", {})],
              [("left", "out", "join", "left"), ("left", "out", "join", "right")])
    result = apply_operations(g, [{"op": "disconnect", "source": "left", "source_port": "out",
                                   "target": "join", "target_port": "right"}], get_registry())
    assert result["edges"] == [g["edges"][0]]

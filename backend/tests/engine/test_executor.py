import asyncio
import time

from app.core.masking import Masker
from app.engine.context import RunInfo
from app.engine.executor import Executor, ListSink
from app.engine.graph import Graph
from tests.engine.helpers import graph, make_registry

REG = make_registry()


def run(g, **kw):
    sink = ListSink()
    masker = kw.pop("masker", Masker())
    ex = Executor(Graph.model_validate(g), REG, RunInfo(run_id="r1", workspace_id="w1"), sink, masker=masker, **kw)
    result = asyncio.run(ex.run())
    return result, sink


def test_linear_data_passing():
    g = graph([("t", "t.trigger", {}), ("a", "t.number", {"value": 2}), ("b", "t.number", {"value": 3})],
              [("t", "out", "a", "in"), ("a", "out", "b", "in")])
    res, _ = run(g)
    assert res.status == "success"
    assert res.outputs["b"]["out"].data == {"n": 5}
    assert res.node_status == {"t": "success", "a": "success", "b": "success"}


def test_independent_branches_run_in_parallel():
    g = graph([("t", "t.trigger", {}), ("a", "t.number", {"value": 1, "sleep": 0.4}),
               ("b", "t.number", {"value": 2, "sleep": 0.4}), ("s", "t.sum", {})],
              [("t", "out", "a", "in"), ("t", "out", "b", "in"), ("a", "out", "s", "in"), ("b", "out", "s", "in")])
    start = time.monotonic()
    res, _ = run(g)
    assert time.monotonic() - start < 0.75
    assert res.outputs["s"]["out"].data == {"n": 3}


def test_if_else_skips_untaken_branch_and_its_dependents():
    g = graph([("t", "t.trigger", {}), ("a", "t.number", {"value": 5}), ("b", "t.branch", {"threshold": 3}),
               ("yes", "t.number", {"value": 1}), ("no", "t.number", {"value": 1}), ("no2", "t.number", {"value": 1}),
               ("s", "t.sum", {})],
              [("t", "out", "a", "in"), ("a", "out", "b", "in"), ("b", "true", "yes", "in"), ("b", "false", "no", "in"),
               ("no", "out", "no2", "in"), ("yes", "out", "s", "in"), ("no2", "out", "s", "in")])
    res, _ = run(g)
    assert res.node_status["yes"] == "success"
    assert res.node_status["no"] == "skipped" and res.node_status["no2"] == "skipped"
    # join node waits only for active inputs
    assert res.node_status["s"] == "success" and res.outputs["s"]["out"].data == {"n": 6}
    assert res.status == "success"


def test_failure_marks_run_failed_skips_dependents_and_masks_error():
    masker = Masker()
    masker.register("hunter2-secret-value")
    g = graph([("t", "t.trigger", {}), ("f", "t.fail", {}), ("after", "t.number", {"value": 1}),
               ("other", "t.number", {"value": 1})],
              [("t", "out", "f", "in"), ("f", "out", "after", "in"), ("t", "out", "other", "in")])
    res, sink = run(g, masker=masker)
    assert res.status == "failed"
    assert res.node_status == {"t": "success", "f": "failed", "after": "skipped", "other": "success"}
    blob = repr(sink.events)
    assert "boom with secret" in blob and "hunter2-secret-value" not in blob


def test_node_timeout_fails_node():
    g = graph([("t", "t.trigger", {}), ("a", "t.number", {"value": 1, "sleep": 2})], [("t", "out", "a", "in")])
    res, sink = run(g, node_timeout=0.2)
    assert res.node_status["a"] == "failed"
    assert any(e["type"] == "node.status" and "timeout" in (e["data"].get("error") or "") for e in sink.events)


def test_run_timeout_cancels_everything():
    g = graph([("t", "t.trigger", {}), ("a", "t.number", {"value": 1, "sleep": 3})], [("t", "out", "a", "in")])
    res, _ = run(g, run_timeout=0.3)
    assert res.status == "failed"
    assert res.node_status["a"] == "cancelled"
    assert "timeout" in (res.error or "")


def test_cancel_request_cancels_running_nodes():
    flag = {"cancel": False}

    async def cancel_check():
        return flag["cancel"]

    g = graph([("t", "t.trigger", {}), ("a", "t.number", {"value": 1, "sleep": 3}),
               ("b", "t.number", {"value": 1})], [("t", "out", "a", "in"), ("a", "out", "b", "in")])
    sink = ListSink()
    ex = Executor(Graph.model_validate(g), REG, RunInfo(run_id="r", workspace_id="w"), sink, cancel_check=cancel_check,
                  poll_interval=0.05)

    async def main():
        task = asyncio.create_task(ex.run())
        await asyncio.sleep(0.2)
        flag["cancel"] = True
        return await task

    start = time.monotonic()
    res = asyncio.run(main())
    assert time.monotonic() - start < 1.5
    assert res.status == "cancelled"
    assert res.node_status["a"] == "cancelled" and res.node_status["b"] == "cancelled"


def test_event_order_and_previews():
    g = graph([("t", "t.trigger", {}), ("a", "t.number", {"value": 1})], [("t", "out", "a", "in")])
    _, sink = run(g)
    seq = [(e["type"], e["node_id"], e["data"].get("status")) for e in sink.events
           if e["type"] in ("run.status", "node.status")]
    assert seq[0] == ("run.status", None, "running")
    assert seq[-1] == ("run.status", None, "success")
    a = [s for s in seq if s[1] == "a"]
    assert a == [("node.status", "a", "running"), ("node.status", "a", "success")]
    assert any(e["type"] == "node.log" and e["node_id"] == "a" for e in sink.events)
    assert any(e["type"] == "edge.data" and e["data"]["edge_id"] == "e0" for e in sink.events)
    out = next(e for e in sink.events if e["type"] == "node.output" and e["node_id"] == "a")
    assert out["data"]["ports"]["out"]["preview"]


def test_disabled_node_is_skipped():
    g = graph([("t", "t.trigger", {}), ("a", "t.number", {"value": 1}), ("b", "t.number", {"value": 1})],
              [("t", "out", "a", "in"), ("a", "out", "b", "in")])
    g["nodes"][1]["disabled"] = True
    res, _ = run(g)
    assert res.node_status["a"] == "skipped" and res.node_status["b"] == "skipped"
    assert res.status == "success"


def test_only_selected_trigger_is_active():
    g = graph([("t1", "t.trigger", {}), ("t2", "t.trigger", {}), ("a", "t.number", {"value": 1}),
               ("b", "t.number", {"value": 1})], [("t1", "out", "a", "in"), ("t2", "out", "b", "in")])
    sink = ListSink()
    ex = Executor(Graph.model_validate(g), REG, RunInfo(run_id="r", workspace_id="w", trigger_node_id="t2"), sink)
    res = asyncio.run(ex.run())
    assert res.node_status == {"t1": "skipped", "t2": "success", "a": "skipped", "b": "success"}

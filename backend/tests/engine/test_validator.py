from app.engine.graph import Graph
from app.engine.validator import validate_graph
from tests.engine.helpers import graph, make_registry

REG = make_registry()


def codes(g, **kw):
    return sorted({e.code for e in validate_graph(Graph.model_validate(g), REG, **kw)})


def test_valid_linear_graph_has_no_errors():
    g = graph([("t", "t.trigger", {}), ("a", "t.number", {"value": 1})], [("t", "out", "a", "in")])
    assert codes(g) == []


def test_missing_trigger():
    assert "no_trigger" in codes(graph([("a", "t.number", {"value": 1})], []))


def test_unknown_node_type_reported_with_node_id():
    errs = validate_graph(Graph.model_validate(graph([("t", "t.trigger", {}), ("x", "nope", {})], [])), REG)
    assert any(e.code == "unknown_type" and e.node_id == "x" for e in errs)


def test_cycle_detected():
    g = graph([("t", "t.trigger", {}), ("a", "t.number", {"value": 1}), ("b", "t.number", {"value": 1})],
              [("t", "out", "a", "in"), ("a", "out", "b", "in"), ("b", "out", "a", "in")])
    assert "cycle" in codes(g)


def test_dangling_required_input():
    g = graph([("t", "t.trigger", {}), ("a", "t.number", {"value": 1})], [])
    errs = validate_graph(Graph.model_validate(g), REG)
    assert any(e.code == "input_not_connected" and e.node_id == "a" for e in errs)


def test_required_config_field_missing():
    g = graph([("t", "t.trigger", {}), ("a", "t.number", {})], [("t", "out", "a", "in")])
    assert "invalid_config" in codes(g)


def test_incompatible_port_types():
    g = graph([("t", "t.trigger", {}), ("a", "t.number", {"value": 1}), ("x", "t.text", {})],
              [("t", "out", "a", "in"), ("a", "out", "x", "in")])
    assert "incompatible_ports" in codes(g)


def test_unknown_port_and_duplicate_edge():
    g = graph([("t", "t.trigger", {}), ("a", "t.number", {"value": 1})],
              [("t", "out", "a", "in"), ("t", "out", "a", "in"), ("t", "nope", "a", "in")])
    c = codes(g)
    assert "duplicate_edge" in c and "unknown_port" in c


def test_single_input_port_rejects_second_edge_but_multiple_accepts():
    g = graph([("t", "t.trigger", {}), ("a", "t.number", {"value": 1}), ("b", "t.number", {"value": 2}),
               ("c", "t.number", {"value": 3}), ("s", "t.sum", {})],
              [("t", "out", "a", "in"), ("t", "out", "b", "in"), ("a", "out", "c", "in"), ("b", "out", "c", "in"),
               ("a", "out", "s", "in"), ("b", "out", "s", "in")])
    errs = validate_graph(Graph.model_validate(g), REG)
    assert [e.node_id for e in errs if e.code == "too_many_inputs"] == ["c"]


def test_credential_reference_must_exist():
    g = graph([("t", "t.trigger", {}), ("x", "t.text", {"token": "cred-1"})], [])
    errs = validate_graph(Graph.model_validate(g), REG, credential_exists=lambda cid: cid == "cred-2")
    assert any(e.code == "unknown_credential" and e.node_id == "x" for e in errs)
    errs = validate_graph(Graph.model_validate(g), REG, credential_exists=lambda cid: cid == "cred-1")
    assert not any(e.code == "unknown_credential" for e in errs)


def test_branch_node_needs_at_least_one_connected_branch():
    g = graph([("t", "t.trigger", {}), ("a", "t.number", {"value": 1}), ("b", "t.branch", {"threshold": 1})],
              [("t", "out", "a", "in"), ("a", "out", "b", "in")])
    assert "branch_not_connected" in codes(g)


def test_edge_to_missing_node():
    g = graph([("t", "t.trigger", {})], [("t", "out", "zz", "in")])
    assert "unknown_node" in codes(g)

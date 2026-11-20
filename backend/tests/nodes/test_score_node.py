from app.analyzers.runner import analyze_project
from app.engine.data import findings_envelope
from app.nodes.base import Envelope
from tests.nodes.conftest import TRAINING, StubServices, run_node


def test_score_node_value_delta_and_priority(tmp_path):
    findings = analyze_project(TRAINING).findings
    services = StubServices(tmp_path)
    services.previous = 25
    out, sink = run_node("analysis.security_score",
                         {"findings": findings_envelope(findings, "merge"),
                          "repo": Envelope.make("repo", {"root": str(TRAINING), "loc": 316}, "src")},
                         {"top_n": 3}, services=services,
                         state={"scanner_set": "scanner.sast+scanner.sca+scanner.secrets"})
    d = out["out"].data
    assert d["value"] == 31 and d["delta"] == 6 and d["loc"] == 316 and len(d["priority"]) == 3
    assert out["out"].meta.summary == "31/100 (+6)"


def test_if_else_routes_on_score_value():
    from app.engine.context import RunInfo
    from app.engine.data import build_context
    from app.engine.expressions import evaluate

    ctx = build_context({"in": Envelope.make("json", {}, "x")}, RunInfo(run_id="r", workspace_id="w"),
                        {"score": {"value": 31, "delta": -4}})
    assert evaluate("score.value < 50 and score.delta < 0", ctx) is True

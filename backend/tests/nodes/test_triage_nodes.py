import pytest
from jsonschema import Draft202012Validator

from app.analyzers.common.finding import Finding
from app.engine.data import findings_envelope, findings_of
from app.nodes.base import Envelope, get_registry
from tests.nodes.conftest import run_node


def test_top_findings_and_grouping():
    findings = [Finding(category="SAST", cls="sample", rule_id="s1", title="sample", path=path,
                        severity=severity, confidence=confidence)
                for path, severity, confidence in [("a", "LOW", 1), ("b", "HIGH", .8),
                                                   ("c", "HIGH", .9), ("d", "CRITICAL", .7)]]
    inputs = {"in": findings_envelope(findings, "scan")}
    top, _ = run_node("analysis.top_findings", inputs, {"limit": 2})
    assert [f.id for f in findings_of(top["out"])] == [findings[3].id, findings[2].id]
    grouped, _ = run_node("analysis.group_findings", inputs, {"group_by": "severity"})
    assert grouped["out"].data == {"total": 4, "counts": {"CRITICAL": 1, "HIGH": 2, "LOW": 1}}
    empty, _ = run_node("analysis.group_findings", {"in": findings_envelope([], "scan")}, {})
    assert empty["out"].data == {"total": 0, "counts": {}}


def test_projection_preserves_scalar_types_and_missing_values():
    data = {"counts": {"HIGH": 2}, "ignored": [42], "flag": False}
    fields = {"high": "counts.HIGH", "low": "counts.LOW", "valid": "flag"}
    out, _ = run_node("logic.map_fields", {"in": Envelope.make("json", data, "group")}, {"fields": fields})
    assert out["out"].data == {"high": 2, "low": None, "valid": False}


@pytest.mark.parametrize("fields", [{}, {"ok": "x()"}, {"a.b": "foo"}, {"ok": 42}, {"__proto__": "x"}])
def test_projection_rejects_invalid_graph_configuration(fields):
    schema = get_registry().get("logic.map_fields").config_schema
    assert not Draft202012Validator(schema).is_valid({"fields": fields})


def test_user_defined_rule_compares_two_input_fields():
    fields = {"escalate": "=counts.HIGH >= threshold and enabled"}
    for threshold, expected in [(2, True), (4, False)]:
        data = {"counts": {"HIGH": 3}, "enabled": True, "threshold": threshold}
        out, _ = run_node("logic.map_fields", {"in": Envelope.make("json", data, "group")}, {"fields": fields})
        assert out["out"].data == {"escalate": expected}
    assert get_registry().get("logic.map_fields").validate_config({"fields": {"bad": "=counts.HIGH >"}})

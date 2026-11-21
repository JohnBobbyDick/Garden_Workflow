import csv
import io

import pytest
from jsonschema import Draft202012Validator

from app.analyzers.common.finding import Finding
from app.core.masking import Masker
from app.engine.data import findings_envelope, findings_of
from app.nodes.base import Envelope, get_registry
from tests.nodes.conftest import run_node


def finding(path, severity="MEDIUM", **fields):
    return Finding(category="SAST", cls="test", rule_id="R", title="Issue", path=path, severity=severity, **fields)


def stream(*items):
    return findings_envelope(list(items), "scan")


def payload(data):
    return Envelope.make("json", data, "source")


def output(node, inputs, config=None, **kwargs):
    ports, _ = run_node(node, inputs, config or {}, **kwargs)
    return ports["out"]


def test_path_filter_uses_scanner_globs_and_exclusion_wins():
    items = [finding(p) for p in ["Main.kt", "src/App.kt", "test/Example.kt", "build.gradle"]]
    args = {"in": stream(*items)}
    selected = output("logic.path_filter", args, {"include": ["**/*.kt"], "exclude": ["test/*"]})
    assert findings_of(selected) == items[:2]
    assert findings_of(output("logic.path_filter", args)) == items


def test_finding_delta_preserves_current_evidence_and_emits_empty_sets():
    first, old, new = finding("old.kt"), finding("shared.kt"), finding("new.kt")
    updated = old.model_copy(update={"severity": "HIGH"})
    ports, _ = run_node("logic.finding_delta", {"baseline": stream(old, first), "current": stream(updated, new)}, {})
    assert {p: findings_of(e) for p, e in ports.items()} == {"added": [new], "retained": [updated], "removed": [first]}
    ports, _ = run_node("logic.finding_delta", {"baseline": stream(), "current": stream()}, {})
    assert len(ports) == 3 and all(not findings_of(e) for e in ports.values())


def test_audit_sample_is_reproducible_and_independent_of_input_order():
    items = [finding(f"file-{i}.kt") for i in range(40)]

    def sample(group, seed):
        result = output("analysis.audit_sample", {"in": stream(*group)}, {"size": 5, "seed": seed})
        return [f.id for f in findings_of(result)]

    selected = sample(items, "november")
    assert len(set(selected)) == 5 and selected == sample(reversed(items), "november")
    assert selected != sample(items, "december")
    assert sample(items[:1], "") == [items[0].id]
    assert sample([], "") == []


def test_file_hotspots_order_and_limit():
    items = [finding("b", "HIGH"), finding("b", "LOW", line=2), finding("a", "HIGH"), finding("c", "CRITICAL")]
    result = output("analysis.file_hotspots", {"in": stream(*items)}, {"limit": 2}).data
    assert result == {"total_files": 3, "files": [{"path": "c", "count": 1, "max_severity": "CRITICAL"},
                                                  {"path": "b", "count": 2, "max_severity": "HIGH"}]}


def test_dependency_fixes_preserve_advisory_and_version_boundaries():
    def dependency(path, advisory, version, fixes):
        return Finding(category="SCA", cls="sca", rule_id="sca", title="Library", path=path,
                       group="org.example", artifact="demo", advisory_id=advisory, version=version, fixed_versions=fixes)
    deps = [dependency("a/build", "A", "1.0", ["2.0"]), dependency("b/build", "A", "1.0", ["2.0"]),
            dependency("c/build", "B", "1.0", []), dependency("d/build", "A", "0.9", ["1.2"])]
    rows = output("analysis.dependency_fixes", {"in": stream(finding("code"), *deps)}).data["updates"]
    assert len(rows) == 3
    assert next(r for r in rows if r["advisory"] == "B")["fixed_versions"] == []
    assert next(r for r in rows if r["version"] == "0.9")["fixed_versions"] == ["1.2"]
    assert next(r for r in rows if r["paths"] == ["a/build", "b/build"]) == {
        "group": "org.example", "artifact": "demo", "version": "1.0", "advisory": "A",
        "paths": ["a/build", "b/build"], "fixed_versions": ["2.0"]}


def test_severity_budget_counts_only_excess_over_each_configured_limit():
    args = {"in": stream(finding("a", "HIGH"), finding("b", "MEDIUM"), finding("c", "MEDIUM"))}
    result = output("analysis.severity_budget", args, {"high": 1, "medium": 0}).data
    assert result["within_budget"] is False and result["excess"] == {"MEDIUM": 2}
    assert output("analysis.severity_budget", args, {"high": 1}).data["within_budget"] is True
    assert output("analysis.severity_budget", {"in": stream()}).data["excess"] == {}


def test_check_fields_distinguishes_null_missing_and_falsy_values():
    data = {"nested": {"count": 0}, "no": False, "empty": "", "value": None}
    config = {"paths": ["nested.count", "no", "empty", "value", "absent"]}
    result = output("logic.check_fields", {"in": payload(data)}, config).data
    assert result == {"valid": False, "missing": ["absent"], "null_fields": ["value"]}
    assert output("logic.check_fields", {"in": payload(data)}, {"paths": ["no"]}).data["valid"] is True


def test_join_json_explicit_precedence_and_no_input_mutation():
    args = {"left": payload({"a": 1, "both": {"a": True}}), "right": payload({"b": 2, "both": False})}
    with pytest.raises(ValueError):
        output("logic.join_json", args)
    assert output("logic.join_json", args, {"conflict": "right"}).data == {"a": 1, "b": 2, "both": False}
    assert output("logic.join_json", args, {"conflict": "left"}).data["both"] == {"a": True}
    assert args["left"].data == {"a": 1, "both": {"a": True}}


def test_render_text_uses_run_context_and_masks_secrets():
    masker = Masker()
    masker.register("sensitive-test-value")
    result = output("logic.render_text", {"in": payload({"status": "sensitive-test-value"})},
                    {"template": "{{run.id}} - {{data.status}}"}, masker=masker)
    assert result.type == "text" and result.data == {"text": f"r1 - {masker.mask('sensitive-test-value')}"}


def test_csv_artifact_is_parseable_masked_and_safe_to_open_in_spreadsheet(services):
    masker = Masker()
    masker.register("private-test-string")
    item = finding("file,one.kt").model_copy(update={"title": '  =private-test-string,"quoted"\nline'})
    report = output("output.findings_csv", {"in": stream(item)}, {"delimiter": ";"}, services=services, masker=masker)
    artifact = report.data["artifacts"][0]
    content, mime = services.artifacts[artifact["name"]]
    assert mime.startswith("text/csv") and b"private-test-string" not in content
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == 1 and rows[0]["id"] == item.id and rows[0]["path"] == "file,one.kt"
    assert rows[0]["title"] == "'" + masker.mask(item.title)


@pytest.mark.parametrize(("node", "config"), [
    ("logic.check_fields", {"paths": []}), ("logic.check_fields", {"paths": ["a..b"]}),
    ("analysis.audit_sample", {"size": 0}), ("analysis.file_hotspots", {"limit": -1}),
    ("analysis.severity_budget", {"critical": -1}), ("logic.join_json", {"conflict": "random"}),
    ("output.findings_csv", {"delimiter": "long"}),
])
def test_invalid_node_settings_are_rejected_by_graph_schema(node, config):
    assert not Draft202012Validator(get_registry().get(node).config_schema).is_valid(config)


def test_render_text_keeps_arbitrary_json_under_data_and_bounds_result():
    node = "logic.render_text"
    env = {"in": payload({"findings": "ready", "text": "x" * 35000})}
    assert output(node, env, {"template": "{{data.findings}}"}).data["text"] == "ready"
    with pytest.raises(ValueError, match="лимит"):
        output(node, env, {"template": "{{data.text}}{{data.text}}"})
    assert output(node, {"in": stream(finding("a"))}, {"template": "{{findings.count}}"}).data["text"] == "1"


@pytest.mark.parametrize(("ai", "accepted", "total", "review"), [
    (True, 2, 2, False), (True, 1, 3, True), (False, 0, 2, True), (False, 0, 0, False),
])
def test_ai_coverage_counts_all_findings_including_deterministic_fill(ai, accepted, total, review):
    report = Envelope.make("report", {"ai_generated": ai, "report": {"findings": [{} for _ in range(total)]},
                                      "validation": {"metrics": {"valid_items": accepted} if ai else {}}}, "ai")
    result = output("analysis.ai_coverage", {"in": report}).data
    assert result == {"total": total, "explained_by_ai": accepted, "deterministic": total - accepted,
                      "needs_review": review}


def test_ai_coverage_requires_an_ai_report():
    exported = Envelope.make("report", {"artifacts": []}, "csv")
    with pytest.raises(ValueError, match="ai.report"):
        output("analysis.ai_coverage", {"in": exported})

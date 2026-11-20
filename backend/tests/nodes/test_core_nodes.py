import io
import zipfile

import pytest

from app.engine.data import findings_envelope, findings_of
from app.nodes.base import Envelope, get_registry
from tests.nodes.conftest import TRAINING, run_node

EXPECTED_TYPES = {
    "trigger.manual", "trigger.schedule", "trigger.webhook", "source.repo", "scanner.secrets", "scanner.sca",
    "scanner.sast", "logic.if_else", "logic.compare", "logic.regex", "logic.severity_filter", "logic.merge",
    "logic.set_value", "output.report_export", "output.ci_gate", "notify.telegram", "notify.smtp", "notify.webhook",
}


def test_registry_discovers_all_phase2_nodes_with_bilingual_metadata():
    reg = get_registry()
    assert EXPECTED_TYPES <= reg.types()
    for cls in reg.all():
        spec = cls.spec()
        assert spec["title"]["ru"] and spec["title"]["en"], cls.type
        assert spec["description"]["ru"] and spec["description"]["en"], cls.type
        assert spec["config_schema"]["type"] == "object"


def repo_env(root):
    return Envelope.make("repo", {"root": str(root), "project_name": "training"}, "src")


def test_manual_trigger_outputs_trigger():
    out, _ = run_node("trigger.manual", {}, {})
    assert out["out"].type == "trigger"


def test_schedule_trigger_validates_cron_and_daily_time():
    cls = get_registry().get("trigger.schedule")
    assert cls.validate_config({"cron": "0 14 * * *"}) == []
    assert cls.validate_config({"daily_at": "14:00"}) == []
    assert cls.validate_config({"cron": "61 * * * *"})
    assert cls.validate_config({"daily_at": "25:00"})
    assert cls.validate_config({})
    assert cls.cron_of({"daily_at": "09:30"}) == "30 9 * * *"


def test_source_repo_path_mode_inside_scan_roots(services):
    out, _ = run_node("source.repo", {"in": Envelope.make("trigger", {}, "t")},
                      {"mode": "path", "path": str(TRAINING)}, services)
    assert out["out"].type == "repo" and out["out"].data["files"] > 5


def test_source_repo_path_mode_outside_roots_fails(services, tmp_path):
    with pytest.raises(Exception, match="APP_SCAN_ROOTS"):
        run_node("source.repo", {"in": Envelope.make("trigger", {}, "t")}, {"mode": "path", "path": str(tmp_path)},
                 services)


def test_source_repo_git_url_not_in_allowlist_fails(services):
    with pytest.raises(Exception, match="allowlist"):
        run_node("source.repo", {"in": Envelope.make("trigger", {}, "t")},
                 {"mode": "git_url", "git_url": "https://github.com/evil/repo"}, services)


def test_source_repo_upload_mode(services):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("p/build.gradle.kts", 'dependencies { implementation("org.jsoup:jsoup:1.14.1") }\n')
    services.uploads["u1"] = ("p.zip", buf.getvalue())
    out, _ = run_node("source.repo", {"in": Envelope.make("trigger", {}, "t")}, {"mode": "upload", "upload_id": "u1"},
                      services)
    assert out["out"].data["files"] == 1


def test_source_repo_trigger_payload_upload_overrides_config(services):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.kt", "val x = 1\n")
    services.uploads["u9"] = ("ci.zip", buf.getvalue())
    trig = Envelope.make("trigger", {"source": {"mode": "upload", "upload_id": "u9"}}, "t")
    out, _ = run_node("source.repo", {"in": trig}, {"mode": "project"}, services)
    assert out["out"].data["source"]["mode"] == "upload"
    # an explicitly fixed source is not replaced by the trigger payload
    out, _ = run_node("source.repo", {"in": trig}, {"mode": "path", "path": str(TRAINING)}, services)
    assert out["out"].data["source"]["mode"] == "path"


def test_three_scanners_on_training_project(services):
    total = []
    for t in ("scanner.secrets", "scanner.sca", "scanner.sast"):
        out, _ = run_node(t, {"in": repo_env(TRAINING)}, {}, services)
        fs = findings_of(out["out"])
        assert len(fs) == 5, t
        total += fs
    assert len(services.findings) == 15
    assert all(f.node_id == "n1" for f in services.findings)


def test_sast_rule_toggle(services):
    out, _ = run_node("scanner.sast", {"in": repo_env(TRAINING)}, {"disabled_rules": ["sql-injection"]}, services)
    assert "sql-injection" not in {f.cls for f in findings_of(out["out"])}


def _findings():
    from app.analyzers.runner import analyze_project
    return analyze_project(TRAINING).findings


def test_merge_dedupes_by_id():
    fs = _findings()
    a, b = findings_envelope(fs[:10], "a"), findings_envelope(fs[5:], "b")
    out, _ = run_node("logic.merge", {"in": [a, b]}, {})
    assert len(findings_of(out["out"])) == 15


def test_if_else_routes_by_expression():
    env = findings_envelope(_findings(), "m")
    out, _ = run_node("logic.if_else", {"in": env}, {"expression": "severity.max >= HIGH"})
    assert set(out) == {"true"} and out["true"].type == "findings"
    out, _ = run_node("logic.if_else", {"in": env}, {"expression": "findings.count > 100"})
    assert set(out) == {"false"}
    cls = get_registry().get("logic.if_else")
    assert cls.validate_config({"expression": "findings.count >"})


def test_compare_node():
    env = Envelope.make("json", {"a": 5, "s": "x"}, "j")
    out, _ = run_node("logic.compare", {"in": env}, {"left": "data.a", "operator": ">", "right": "3"})
    assert out["result"].data["value"] is True and "true" in out
    out, _ = run_node("logic.compare", {"in": env}, {"left": "data.s", "operator": "==", "right": "y"})
    assert out["result"].data["value"] is False and "false" in out


def test_regex_filter_findings_and_extract():
    env = findings_envelope(_findings(), "m")
    out, _ = run_node("logic.regex", {"in": env}, {"pattern": r"\.yml$", "field": "path", "mode": "filter"})
    fs = findings_of(out["out"])
    assert fs and all(f.path.endswith(".yml") for f in fs)
    txt = Envelope.make("text", {"text": "CVE-2022-42889 and CVE-2021-37714"}, "t")
    out, _ = run_node("logic.regex", {"in": txt}, {"pattern": r"CVE-\d{4}-\d+", "mode": "extract"})
    assert out["out"].data["matches"] == ["CVE-2022-42889", "CVE-2021-37714"]


def test_regex_catastrophic_pattern_is_stopped():
    txt = Envelope.make("text", {"text": "a" * 5000 + "!"}, "t")
    with pytest.raises(Exception, match="(?i)timeout|время"):
        run_node("logic.regex", {"in": txt}, {"pattern": r"(a+)+$", "mode": "match", "timeout_ms": 200})


def test_severity_filter():
    env = findings_envelope(_findings(), "m")
    out, _ = run_node("logic.severity_filter", {"in": env}, {"min_severity": "HIGH", "categories": ["SAST"]})
    fs = findings_of(out["out"])
    assert fs and all(f.category == "SAST" and f.severity in ("HIGH", "CRITICAL") for f in fs)


def test_set_value():
    out, _ = run_node("logic.set_value", {}, {"values": {"team": "core", "limit": 3}})
    assert out["out"].data == {"team": "core", "limit": 3}


def test_report_export_saves_three_valid_artifacts(services):
    import json

    from app.export.validator import validate_submission
    env = findings_envelope(_findings(), "m")
    out, _ = run_node("output.report_export", {"in": env}, {}, services)
    assert {"submission.json", "report.md", "report.html"} <= set(services.artifacts)
    doc = json.loads(services.artifacts["submission.json"][0])
    assert validate_submission(doc) == [] and len(doc["findings"]) == 15
    assert out["out"].type == "report" and out["out"].data["artifacts"]


def test_ci_gate():
    env = findings_envelope(_findings(), "m")
    out, _ = run_node("output.ci_gate", {"in": env}, {"fail_on": "CRITICAL"})
    crit = any(f.severity == "CRITICAL" for f in _findings())
    assert out["out"].data["gate"] == ("fail" if crit else "pass")
    out, _ = run_node("output.ci_gate", {"in": env}, {"fail_on": "none"})
    assert out["out"].data["gate"] == "pass"
    verdict = Envelope.make("json", {"verdict": "PASS", "new_counts_by_severity": {}}, "d")
    out, _ = run_node("output.ci_gate", {"in": env, "verdict": verdict}, {"fail_on": "LOW"})
    assert out["out"].data["gate"] == "pass" and out["out"].data["basis"] == "new_findings"


def test_context_project_name_falls_back_to_scanned_repo():
    from app.engine.context import RunInfo
    from app.engine.data import build_context
    ctx = build_context({}, RunInfo(run_id="r", workspace_id="w"), {"repo": {"project_name": "training-project"}})
    assert ctx["project"]["name"] == "training-project"

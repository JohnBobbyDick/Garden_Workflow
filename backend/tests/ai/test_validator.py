import pytest

from app.ai.validator import AIFormatError, masked_file_reader, parse_json, validate_report
from app.analyzers.runner import analyze_project
from tests.nodes.conftest import TRAINING


@pytest.fixture(scope="module")
def findings():
    return analyze_project(TRAINING).findings


def by_cls(findings, cls):
    return next(f for f in findings if f.cls == cls)


def reader(findings):
    return masked_file_reader(TRAINING, findings)


def allowed(findings):
    ids = set()
    for f in findings:
        if f.advisory_id:
            ids.add(f.advisory_id)
        ids.update(f.aliases)
    return ids


def item(fid, **kw):
    d = {"finding_id": fid, "explanation": "Объяснение", "impact": "Последствия", "remediation_steps": ["шаг"]}
    d.update(kw)
    return d


def test_parse_json_strips_fences_and_rejects_garbage():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(AIFormatError):
        parse_json("not json at all")


def test_schema_violation_reported(findings):
    with pytest.raises(AIFormatError):
        validate_report({"summary": 5, "findings": "x"}, findings, reader(findings), allowed(findings))


def test_unknown_and_duplicate_ids_dropped(findings):
    f = findings[0]
    data = {"summary": "s", "priority_order": [f.id, "f_doesnotexist"], "global_recommendations": [],
            "findings": [item(f.id), item(f.id), item("f_made_up_by_llm")]}
    report, log = validate_report(data, findings, reader(findings), allowed(findings))
    assert [x["finding_id"] for x in report["findings"]] == [f.id]
    assert report["priority_order"] == [f.id]
    assert log.metrics["dropped"] == 2 and log.metrics["unknown_ids"] == ["f_doesnotexist", "f_made_up_by_llm"]


def test_hallucinated_cve_removed_and_flagged(findings):
    sca = next(f for f in findings if f.category == "SCA")
    data = {"summary": f"Обновите зависимость ({sca.advisory_id}); также CVE-2099-99999 и GHSA-aaaa-bbbb-cccc.",
            "priority_order": [], "global_recommendations": ["Проверьте CVE-2098-12345"],
            "findings": [item(sca.id, explanation=f"Уязвимость {sca.advisory_id} и выдуманная CVE-2097-11111")]}
    report, log = validate_report(data, findings, reader(findings), allowed(findings))
    text = repr(report)
    assert sca.advisory_id in text
    for fake in ("CVE-2099-99999", "GHSA-aaaa-bbbb-cccc", "CVE-2098-12345", "CVE-2097-11111"):
        assert fake not in text
    assert log.flags["hallucinated_ids"] is True and len(log.metrics["hallucinated_ids"]) == 4


def test_fix_with_exact_before_is_kept(findings):
    sqli = by_cls(findings, "sql-injection")
    lines = reader(findings)(sqli.path)
    before = "\n".join(lines[sqli.line - 1:sqli.line])
    fix = {"path": sqli.path, "start_line": sqli.line, "end_line": sqli.line, "before": "  " + before.strip(),
           "after": "safe()"}
    report, log = validate_report({"summary": "s", "priority_order": [], "global_recommendations": [],
                                   "findings": [item(sqli.id, fix=fix)]}, findings, reader(findings), allowed(findings))
    assert report["findings"][0]["fix"]["after"] == "safe()"
    assert log.metrics["fixes_kept"] == 1


@pytest.mark.parametrize("mutation", ["path", "before", "lines"])
def test_fix_with_wrong_path_before_or_lines_is_dropped(findings, mutation):
    sqli = by_cls(findings, "sql-injection")
    lines = reader(findings)(sqli.path)
    fix = {"path": sqli.path, "start_line": sqli.line, "end_line": sqli.line, "before": lines[sqli.line - 1],
           "after": "x"}
    if mutation == "path":
        fix["path"] = "src/main/kotlin/Invented.kt"
    elif mutation == "before":
        fix["before"] = "val query = \"invented code that is not in the file\""
    else:
        fix["start_line"], fix["end_line"] = 9000, 9001
    report, log = validate_report({"summary": "s", "priority_order": [], "global_recommendations": [],
                                   "findings": [item(sqli.id, fix=fix)]}, findings, reader(findings), allowed(findings))
    assert "fix" not in report["findings"][0]
    assert log.metrics["fixes_dropped"] == 1


def test_secret_fix_before_matches_masked_view(findings):
    pw = by_cls(findings, "password")
    fix = {"path": pw.path, "start_line": pw.line, "end_line": pw.line, "before": pw.snippet,
           "after": '    private val legacyImportPassword = System.getenv("LEGACY_IMPORT_PASSWORD")'}
    report, log = validate_report({"summary": "s", "priority_order": [], "global_recommendations": [],
                                   "findings": [item(pw.id, fix=fix)]}, findings, reader(findings), allowed(findings))
    assert "fix" in report["findings"][0]


def test_safe_version_checked_against_fixed_versions(findings):
    sca = next(f for f in findings if f.category == "SCA" and f.fixed_versions)
    data = {"summary": "s", "priority_order": [], "global_recommendations": [],
            "findings": [item(sca.id, safe_version="0.0.1-invented")]}
    report, log = validate_report(data, findings, reader(findings), allowed(findings))
    assert report["findings"][0]["safe_version"] in sca.fixed_versions
    assert log.metrics["safe_version_corrected"] == 1


def test_inline_file_reference_to_unknown_file_is_removed(findings):
    f = findings[0]
    data = {"summary": "s", "priority_order": [], "global_recommendations": [],
            "findings": [item(f.id, explanation=f"См. {f.path}:{f.line} и src/Ghost.kt:12")]}
    report, log = validate_report(data, findings, reader(findings), allowed(findings))
    text = report["findings"][0]["explanation"]
    assert f"{f.path}:{f.line}" in text and "Ghost.kt" not in text
    assert log.metrics["bad_references"] == 1


def test_metrics_and_checks_recorded(findings):
    f = findings[0]
    _, log = validate_report({"summary": "s", "priority_order": [f.id], "global_recommendations": [],
                              "findings": [item(f.id)]}, findings, reader(findings), allowed(findings))
    assert log.metrics["valid_items"] == 1 and log.metrics["total_items"] == 1
    assert {c["check"] for c in log.checks} >= {"schema", "finding_ids", "fixes", "advisory_ids", "safe_versions",
                                                "references"}

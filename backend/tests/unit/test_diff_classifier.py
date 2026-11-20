import shutil

import pytest

from app.analyzers.common.finding import Finding, Location
from app.analyzers.diff.classifier import all_new, classify, verdict
from app.analyzers.diff.git import DiffContext
from app.analyzers.diff.hunks import FileChange, Hunk
from app.analyzers.diff.sca_diff import diff_sca, scan_base
from app.analyzers.sca.detector import scan_sca
from app.analyzers.sca.vulndb import VulnDB
from app.config import REPO_ROOT

TRAINING = REPO_ROOT / "fixtures" / "organizer-training" / "training-project"


def F(cls="password", category="SECRET", path="src/A.kt", line=10, end=None, sev="HIGH", alts=(), **kw):
    return Finding(category=category, cls=cls, rule_id=f"R-{cls}", title=cls, severity=sev, path=path, line=line,
                   end_line=end, context_key=f"{path}:{line}:{cls}",
                   alternate_locations=[Location(path=p, line=ln) for p, ln in alts], **kw)


def ctx(changes: dict[str, set[int]], blame=None):
    ch = {p: FileChange(path=p, new_lines=set(lines),
                        hunks=[Hunk(0, 0, min(lines), len(lines), f"@@ -0,0 +{min(lines)},{len(lines)} @@")]
                        if lines else []) for p, lines in changes.items()}
    return DiffContext(base_sha="a" * 40, head_sha="b" * 40, merge_base="c" * 40, changes=ch, blame=blame or {})


def test_changed_line_is_new_untouched_file_is_existing_with_attribution():
    c = ctx({"src/A.kt": {10}}, blame={"src/A.kt": {10: ("d" * 40, "dev@example.com")}})
    res = classify([F(line=10), F(path="src/B.kt", line=10)], c)
    assert [f.path for f in res.new] == ["src/A.kt"] and [f.path for f in res.existing] == ["src/B.kt"]
    assert res.new[0].diff_hunk == "@@ -0,0 +10,1 @@"
    assert res.new[0].introduced_in_commit == "d" * 40 and res.new[0].author == "dev@example.com"
    assert res.existing[0].author is None


def test_multiline_range_and_cross_file_alternate_location():
    c = ctx({"src/A.kt": {14}, "src/Ctl.kt": {33}})
    res = classify([F(line=10, end=15), F(line=20, end=22),
                    F(cls="object-authorization", category="SAST", path="src/Repo.kt", line=5,
                      alts=[("src/Ctl.kt", 33)])], c)
    assert sorted((f.path, f.line) for f in res.new) == [("src/A.kt", 10), ("src/Repo.kt", 5)]
    assert [(f.path, f.line) for f in res.existing] == [("src/A.kt", 20)]


def test_verdict_threshold_and_report_only():
    res = classify([F(line=10, sev="CRITICAL"), F(path="src/B.kt", sev="CRITICAL")], ctx({"src/A.kt": {10}}))
    v = verdict(res)
    assert v["verdict"] == "FAIL" and v["new_counts_by_severity"]["CRITICAL"] == 1 and v["existing_count"] == 1
    assert verdict(res, threshold="CRITICAL")["blocking_count"] == 1
    high_only = classify([F(line=10, sev="HIGH")], ctx({"src/A.kt": {10}}))
    assert verdict(high_only)["verdict"] == "PASS" and verdict(high_only, "HIGH")["verdict"] == "FAIL"
    ro = verdict(res, report_only=True)
    assert ro["verdict"] == "PASS" and "would_fail_reason" in ro
    assert all(f.diff_status == "new" for f in all_new([F(), F(path="x")]).new)


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "p"
    shutil.copytree(TRAINING, p)
    (p / "gradle.lockfile").unlink()  # version comes from gradle.properties only
    return p


def _json(findings):
    return [f for f in findings if f.artifact == "json"]


def test_sca_version_moved_into_vulnerable_range_only_via_gradle_properties_is_new(project):
    db = VulnDB.load()
    base_files = {r: (project / r).read_text() for r in ("build.gradle.kts", "settings.gradle.kts")}
    base_files["gradle.properties"] = "legacyManifestJsonVersion=20231013\n"  # fixed version in base
    head = scan_sca(project, db).findings
    base = scan_base(base_files, db)
    assert _json(head) and not _json(base)
    res = classify(head, ctx({"gradle.properties": {1}}), base)
    assert [f.artifact for f in res.new] == ["json"]
    assert all(f.diff_status == "existing" and f.version_changed is False for f in res.existing)


def test_sca_unchanged_is_existing_and_upgrade_is_fixed_in_diff(project):
    db = VulnDB.load()
    files = {r: (project / r).read_text() for r in ("build.gradle.kts", "settings.gradle.kts", "gradle.properties")}
    head = scan_sca(project, db).findings
    status, fixed = diff_sca(head, scan_base(files, db))
    assert status and all(s["diff_status"] == "existing" for s in status.values()) and fixed == []
    (project / "gradle.properties").write_text("legacyManifestJsonVersion=20231013\n")
    status, fixed = diff_sca(scan_sca(project, db).findings, scan_base(files, db))
    assert [(x["artifact"], x["advisory_id"]) for x in fixed] == [("json", "CVE-2023-5072")]


def test_scan_base_ignores_path_traversal_names():
    assert scan_base({"../../evil/build.gradle.kts": "x", "/abs/build.gradle.kts": "y"}, VulnDB.load()) == []

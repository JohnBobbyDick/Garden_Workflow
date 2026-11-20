import shutil

from app.analyzers.runner import analyze_project
from app.engine.data import findings_envelope
from tests.nodes.conftest import TRAINING, StubServices, run_node


def test_autofix_node_bumps_dependency_without_llm_and_opens_pr(tmp_path):
    root = tmp_path / "p"
    shutil.copytree(TRAINING, root)
    before = (root / "build.gradle.kts").read_text()
    findings = analyze_project(root).findings
    services = StubServices(tmp_path)
    out, _ = run_node("ai.autofix", {"in": findings_envelope(findings, "merge")},
                      {"max_findings": 3, "min_severity": "HIGH", "auto_create_pr": True, "pr_template": "Ревью: @sec"},
                      services=services, state={"repo": {"root": str(root)}})
    d = out["out"].data
    items = {i["title"]: i for i in d["autofix"]}
    sca = next(i for t, i in items.items() if "commons-text" in t)
    assert sca["status"] == "validated" and "1.10.0" in sca["patch"] and sca["pr_url"].startswith("http://mock/")
    secret_like = [i for i in d["autofix"] if i["status"] == "skipped"]
    assert all("AI-провайдер не настроен" in i["reason"] for i in secret_like)  # LLM rules without a provider
    assert services.prs[0][2] == "Ревью: @sec"
    assert (root / "build.gradle.kts").read_text() == before  # the working copy is never modified
    assert d["total"] == 3 and d["validated"] >= 1

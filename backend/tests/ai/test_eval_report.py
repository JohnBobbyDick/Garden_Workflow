"""AI recommendation usefulness evaluation (presentation requirement: «оцените полезность рекомендаций»):
measurable proxies over the whole finding set, computed after our validator."""

import pytest

from app.ai.eval_report import evaluate_outcome, render_markdown_table, run_eval
from app.ai.providers.base import ProviderConfig, build_provider
from app.analyzers.common.finding import Finding
from tests.ai.fake_llm import make_server
from tests.ai.test_report_service import good_answer
from tests.nodes.conftest import TRAINING


def mk(fid, category, path, line=3, **kw):
    base = {"id": fid, "category": category, "cls": kw.pop("cls", "password"), "rule_id": "r", "title": fid,
            "description": "d", "remediation": "r", "severity": "HIGH", "severity_reason": "", "confidence": 0.9,
            "path": path, "line": line, "end_line": line, "snippet": ""}
    base.update(kw)
    return Finding(**base)


def test_metrics_per_finding_and_category():
    fs = [mk("s1", "SECRET", "src/A.kt"), mk("s2", "SAST", "src/B.kt", cls="sql-injection"),
          mk("c1", "SCA", "build.gradle.kts", group="g", artifact="lib", version="1.0", advisory_id="CVE-1",
             fixed_versions=["1.2"], cls="known-vulnerable-dependency")]
    ids = {x.cls if x.category != "SCA" else "sca": x.id for x in fs}  # Finding.id is a stable computed hash
    report = {"findings": [
        {"finding_id": ids["password"], "explanation": "Пароль в A.kt:3", "impact": "x", "remediation_steps": ["Вынести в env"],
         "fix": {"path": "src/A.kt", "start_line": 3, "end_line": 3, "before": "a", "after": "b"}},
        {"finding_id": ids["sql-injection"], "explanation": "общие слова", "impact": "x", "remediation_steps": []},
        {"finding_id": ids["sca"], "explanation": "lib уязвима", "impact": "x", "remediation_steps": ["Обновить lib до 1.2"],
         "safe_version": "1.2"},
    ]}
    validation = {"metrics": {"total_items": 3, "valid_items": 3, "hallucinated_ids": [], "bad_references": 0,
                              "fixes_kept": 1, "fixes_dropped": 0, "dropped": 0}}
    r = evaluate_outcome(fs, report, validation, ai_generated=True)
    assert r["total"] == 3 and r["ai_explained"] == 3
    assert r["by_category"]["SECRET"] == {"n": 1, "ai": 1, "located": 1, "actionable": 1, "fix_or_version": 1}
    assert r["by_category"]["SAST"] == {"n": 1, "ai": 1, "located": 0, "actionable": 0, "fix_or_version": 0}
    assert r["by_category"]["SCA"] == {"n": 1, "ai": 1, "located": 1, "actionable": 1, "fix_or_version": 1}
    assert r["validator"]["accepted"] == "3/3" and r["validator"]["hallucinated_ids"] == 0


def test_deterministic_fill_is_not_counted_as_ai():
    fs = [mk("s1", "SECRET", "src/A.kt")]
    report = {"findings": [{"finding_id": fs[0].id, "explanation": "A.kt", "impact": "", "remediation_steps": ["x"],
                            "source": "deterministic"}]}
    r = evaluate_outcome(fs, report, {"metrics": {}}, ai_generated=True)
    assert r["ai_explained"] == 0 and r["by_category"]["SECRET"]["ai"] == 0


def test_without_provider_the_eval_refuses_to_pretend():
    fs = [mk("s1", "SECRET", "src/A.kt")]
    r = evaluate_outcome(fs, {"findings": []}, {"metrics": {}}, ai_generated=False)
    assert r["ai_generated"] is False and r["ai_explained"] == 0


@pytest.fixture
def ollama():
    srv, script, hp = make_server("ollama")
    script.dynamic = good_answer
    yield hp
    srv.shutdown()


async def test_end_to_end_on_the_training_set(ollama):
    provider = build_provider(ProviderConfig(provider="ollama", base_url=f"http://{ollama}", model="qwen2.5:3b",
                                             timeout=10, allow_hosts={ollama}))
    r = await run_eval(TRAINING, provider)
    assert r["total"] == 15 and r["ai_generated"] is True and r["ai_explained"] == 15
    assert r["validator"]["hallucinated_ids"] == 0 and r["validator"]["accepted"] == "15/15"
    assert r["by_category"]["SCA"]["n"] == 5 and r["by_category"]["SCA"]["located"] == 5
    table = render_markdown_table(r)
    assert "| SECRET |" in table and "| Итого |" in table and r["provider"] == "ollama"

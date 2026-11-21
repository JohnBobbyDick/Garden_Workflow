import asyncio
import json

import pytest

from app.ai.providers.base import LLMError, ProviderConfig, build_provider
from app.ai.report_service import generate_report
from app.ai.validator import masked_file_reader
from app.analyzers.runner import analyze_project
from app.core.masking import Masker
from tests.ai.fake_llm import make_server
from tests.nodes.conftest import TRAINING


@pytest.fixture(scope="module")
def findings():
    return analyze_project(TRAINING).findings


@pytest.fixture
def llm():
    srv, script, hp = make_server("ollama")
    yield script, hp
    srv.shutdown()


def provider(hp):
    return build_provider(ProviderConfig(provider="ollama", base_url=f"http://{hp}", model="m",
                                         timeout=5, backoff_base=0.01, allow_hosts={hp}))


def findings_in_request(body) -> list[dict]:
    user = next(m for m in body["messages"] if m["role"] == "user")["content"]
    return json.loads(user[user.index("{"):])["findings"]


def good_answer(body):
    items = findings_in_request(body)
    out = []
    for f in items:
        it = {"finding_id": f["finding_id"], "explanation": f"Объяснение {f['class']} в {f['path']}:{f['line']}",
              "impact": "Утечка данных", "remediation_steps": ["Исправьте код"]}
        if f["category"] == "SCA":
            it["safe_version"] = f["fixed_versions"][0] if f.get("fixed_versions") else None
            it["explanation"] += f" ({f['advisory_id']})"
        if f["class"] == "sql-injection":
            line = next(c for c in f["code"] if c["line"] == f["line"])
            it["fix"] = {"path": f["path"], "start_line": f["line"], "end_line": f["line"], "before": line["text"],
                         "after": "jdbc.queryForList(\"select * from t where tag = ?\", tag)"}
        out.append(it)
    return {"summary": "Найдено несколько серьёзных проблем.", "priority_order": [i["finding_id"] for i in out],
            "findings": out, "global_recommendations": ["Включите проверку в CI"]}


def run(findings, prov, **kw):
    kw.setdefault("language", "ru")
    kw.setdefault("generate_fix_diff", True)
    kw.setdefault("fallback", True)
    allowed = {f.advisory_id for f in findings if f.advisory_id} | {a for f in findings for a in f.aliases}
    return asyncio.run(generate_report(findings, prov, read=masked_file_reader(TRAINING, findings),
                                       allowed_ids=allowed, masker=kw.pop("masker", Masker()), **kw))


def test_valid_llm_report(findings, llm):
    script, hp = llm
    script.dynamic = good_answer
    out = run(findings, provider(hp))
    assert out.ai_generated is True and out.error is None and out.model == "m"
    assert len(out.report["findings"]) == 15
    sqli = next(i for i in out.report["findings"] if "fix" in i)
    assert sqli["fix"]["after"].startswith("jdbc.queryForList")
    assert out.validation["metrics"]["valid_items"] == 15 and out.validation["flags"]["hallucinated_ids"] is False
    assert out.usage["total_tokens"] >= 33


def test_prompt_contains_only_masked_values(findings, llm):
    script, hp = llm
    script.dynamic = good_answer
    raw = (TRAINING / next(f for f in findings if f.cls == "password").path).read_text(encoding="utf-8")
    import re
    literal = re.search(r'legacyImportPassword\s*=\s*"([^"]+)"', raw).group(1)
    run(findings, provider(hp))
    blob = json.dumps(script.requests, ensure_ascii=False)
    assert literal not in blob and "…(len=" in blob
    system = script.requests[0]["body"]["messages"][0]["content"]
    assert "не придумывай" in system.lower() or "не выдумывай" in system.lower()


def test_english_prompt(findings, llm):
    script, hp = llm
    script.dynamic = good_answer
    run(findings, provider(hp), language="en")
    assert "Do not invent" in script.requests[0]["body"]["messages"][0]["content"]


def test_invalid_json_gets_one_repair_attempt(findings, llm):
    script, hp = llm
    script.reply("this is not json")
    script.dynamic = good_answer
    out = run(findings[:3], provider(hp))
    assert out.ai_generated is True and out.validation["metrics"]["repair_attempts"] == 1
    repair = script.requests[1]["body"]["messages"]
    assert repair[-1]["role"] == "user" and "JSON" in repair[-1]["content"]


def test_invalid_twice_falls_back_to_deterministic(findings, llm):
    script, hp = llm
    script.reply("nope").reply("still nope")
    out = run(findings, provider(hp))
    assert out.ai_generated is False and "JSON" in out.error
    assert len(out.report["findings"]) == 15 and out.report["summary"]


def test_invalid_without_fallback_raises(findings, llm):
    script, hp = llm
    script.reply("nope").reply("still nope")
    with pytest.raises(LLMError):
        run(findings, provider(hp), fallback=False)


def test_no_provider_configured(findings):
    out = run(findings, None)
    assert out.ai_generated is False and out.provider is None and len(out.report["findings"]) == 15
    sca = next(i for i in out.report["findings"] if i.get("safe_version"))
    assert sca["safe_version"]
    with pytest.raises(LLMError):
        run(findings, None, fallback=False)


def test_batching_splits_large_input(findings, llm):
    script, hp = llm
    script.dynamic = good_answer
    out = run(findings, provider(hp), batch_chars=3000)
    assert len(script.requests) > 1 and len(out.report["findings"]) == 15
    first = out.report["priority_order"][0]
    explanation = next(item["explanation"] for item in out.report["findings"] if item["finding_id"] == first)
    assert explanation in out.report["summary"]
    assert "Найдено несколько серьёзных проблем." not in out.report["summary"]


def test_findings_missing_from_answer_are_filled_deterministically(findings, llm):
    script, hp = llm

    def partial(body):
        ans = good_answer(body)
        ans["findings"] = ans["findings"][:2]
        return ans
    script.dynamic = partial
    out = run(findings, provider(hp), batch_chars=1_000_000)
    assert len(out.report["findings"]) == 15
    assert sum(1 for i in out.report["findings"] if i.get("source") == "deterministic") == 13
    assert out.validation["metrics"]["filled_deterministic"] == 13

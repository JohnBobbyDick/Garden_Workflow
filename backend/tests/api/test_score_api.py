import shutil
from datetime import timedelta

import pytest

from app import models as m
from app.config import get_settings
from tests.ai.fake_llm import make_server
from tests.api.conftest import drain
from tests.api.test_ai_api import configure
from tests.engine.test_worker_scheduler import full_graph
from tests.nodes.conftest import TRAINING


@pytest.fixture
def llm():
    srv, script, hp = make_server("openai")
    yield script, hp
    srv.shutdown()


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    d = tmp_path / "scan" / "proj"
    shutil.copytree(TRAINING, d)
    monkeypatch.setattr(get_settings(), "scan_roots", str(tmp_path / "scan"))
    return d


def setup_project(client, user, path, graph=None):
    pid = client.post("/api/projects", json={"workspace_id": user.workspace_id, "name": "shop", "source_mode": "path",
                                             "path": str(path)}, headers=user.headers).json()["id"]
    g = graph or full_graph()
    g["nodes"][1]["config"] = {"mode": "project"}
    wid = client.post("/api/workflows", json={"workspace_id": user.workspace_id, "name": "audit", "graph": g,
                                              "project_id": pid}, headers=user.headers).json()["id"]
    return pid, wid


def run(client, db, user, wid):
    rid = client.post(f"/api/workflows/{wid}/run", json={}, headers=user.headers).json()["id"]
    drain(db)
    return client.get(f"/api/runs/{rid}", headers=user.headers).json()


def test_score_is_recorded_for_every_run_with_delta_and_priority(client, db, alice, bob, project_dir):
    pid, wid = setup_project(client, alice, project_dir)
    r1 = run(client, db, alice, wid)
    assert r1["status"] == "success" and r1["score"] == 31 and r1["score_delta"] is None
    # fix two findings (commons-text CRITICAL via version bump, jsoup HIGH) → green delta
    build = project_dir / "build.gradle.kts"
    build.write_text(build.read_text().replace("commons-text:1.9", "commons-text:1.10.0")
                     .replace("jsoup:1.14.1", "jsoup:1.15.3"))
    lock = project_dir / "gradle.lockfile"
    lock.write_text(lock.read_text().replace("commons-text:1.9=", "commons-text:1.10.0=")
                    .replace("jsoup:1.14.1=", "jsoup:1.15.3="))
    r2 = run(client, db, alice, wid)
    assert r2["score"] > r1["score"] and r2["score_delta"] == r2["score"] - r1["score"]
    sc = client.get(f"/api/runs/{r2['id']}/score", headers=alice.headers).json()
    assert sc["breakdown"]["by_severity"]["CRITICAL"]["count"] == 0 and sc["previous_run_id"] == r1["id"]
    top = sc["priority"][0]
    assert top["fix_effort_source"] == "default" and top["expected_gain"] >= 1 and top["cumulative_gain"] >= 1
    assert "не рейтинг" in sc["note"]
    hist = client.get(f"/api/projects/{pid}/score/history?period=7d", headers=alice.headers).json()
    assert [p["score"] for p in hist["points"]] == [r1["score"], r2["score"]]
    assert hist["trend"]["enough_data"] is False  # < 3 points
    r3 = run(client, db, alice, wid)
    assert r3["score_delta"] == 0  # same commit twice → same score
    trend = client.get(f"/api/projects/{pid}/score/history", headers=alice.headers).json()["trend"]
    assert trend["enough_data"] is False  # three runs within seconds: a weekly slope would be a fake extrapolation
    with db.session() as s:  # spread the same three runs over two days → a real trend
        for rid, days in ((r1["id"], 2), (r2["id"], 1)):
            row = s.get(m.Run, rid)
            row.created_at, row.finished_at = row.created_at - timedelta(days=days), row.finished_at - timedelta(days=days)
        s.commit()
    trend = client.get(f"/api/projects/{pid}/score/history", headers=alice.headers).json()["trend"]
    assert trend["enough_data"] is True and trend["slope_per_week"] > 0
    dash = client.get(f"/api/dashboard?workspace_id={alice.workspace_id}", headers=alice.headers).json()
    assert dash["score"]["value"] == r3["score"] and len(dash["score"]["top3"]) == 3 and dash["runs"] == 3
    assert client.get(f"/api/runs/{r3['id']}/score", headers=bob.headers).status_code == 404
    assert client.get(f"/api/projects/{pid}/score/history", headers=bob.headers).status_code == 404


def test_scanner_set_change_resets_delta_and_marks_history(client, db, alice, project_dir):
    pid, wid = setup_project(client, alice, project_dir)
    run(client, db, alice, wid)
    g = full_graph()
    g["nodes"] = [n for n in g["nodes"] if n["id"] != "sca"]
    g["edges"] = [e for e in g["edges"] if "sca" not in (e["source"], e["target"])]
    g["nodes"][1]["config"] = {"mode": "project"}
    client.put(f"/api/workflows/{wid}", json={"graph": g}, headers=alice.headers)
    r2 = run(client, db, alice, wid)
    assert r2["score_delta"] is None
    hist = client.get(f"/api/projects/{pid}/score/history", headers=alice.headers).json()
    assert [mk["kind"] for mk in hist["markers"]] == ["scanner_set"]


def test_sprint_plan_fallback_without_llm(client, db, alice, project_dir):
    _, wid = setup_project(client, alice, project_dir)
    r = run(client, db, alice, wid)
    p = client.post(f"/api/runs/{r['id']}/sprint-plan", json={}, headers=alice.headers).json()
    assert p["ai_generated"] is False and p["plan"]["plan"]
    ids = {i["finding_id"] for i in p["plan"]["plan"]}
    sc = client.get(f"/api/runs/{r['id']}/score", headers=alice.headers).json()
    assert p["plan"]["projected_score"] > r["score"] and ids <= {i["finding_id"] for i in sc["priority"]}


def test_sprint_plan_validator_corrects_numbers_drops_unknown_ids_and_cves(client, db, alice, project_dir, llm):
    script, hp = llm
    configure(client, alice, hp)
    _, wid = setup_project(client, alice, project_dir)
    r = run(client, db, alice, wid)
    top = client.get(f"/api/runs/{r['id']}/score", headers=alice.headers).json()["priority"]
    a, b = top[0]["finding_id"], top[1]["finding_id"]
    script.reply({"summary": "Сначала закройте CVE-2099-0001 и критичную зависимость.",
                  "plan": [{"finding_id": a, "action": "fix", "reason": "quick win"},
                           {"finding_id": "f_invented", "action": "fix", "reason": "?"},
                           {"finding_id": a, "action": "dup", "reason": "dup"}],
                  "defer": [{"finding_id": b, "reason": "later"}],
                  "projected_score": 99, "efforts": [{"finding_id": b, "fix_effort": 4},
                                                     {"finding_id": a, "fix_effort": 42}]})
    p = client.post(f"/api/runs/{r['id']}/sprint-plan", json={"language": "ru"}, headers=alice.headers).json()
    assert p["ai_generated"] is True
    v = p["validation"]
    assert v["corrected_numbers"] is True and v["llm_projected_score"] == 99
    assert v["dropped_ids"] == ["f_invented"] and v["duplicates"] == [a]
    assert v["hallucinated_ids"] == ["CVE-2099-0001"] and "CVE-2099-0001" not in p["plan"]["summary"]
    assert [i["finding_id"] for i in p["plan"]["plan"]] == [a] and p["plan"]["projected_score"] < 99
    by = {i["finding_id"]: i for i in p["plan"]["priority"]}
    assert by[b]["fix_effort"] == 4 and by[b]["fix_effort_source"] == "ai"
    assert by[a]["fix_effort_source"] == "default"  # 42 rejected
    import json
    sent = json.loads(script.requests[-1]["body"]["messages"][-1]["content"])
    assert set(sent) == {"score", "delta", "trend_per_week", "top_findings"}
    assert {k for i in sent["top_findings"] for k in i} == {"finding_id", "class", "severity", "novelty", "fix_effort",
                                                            "expected_gain"}  # no paths, snippets or authors


def test_score_settings_admin_only_and_applied(client, db, alice, bob, project_dir):
    r = client.put("/api/settings/score", json={"workspace_id": alice.workspace_id, "s0": 100}, headers=alice.headers)
    assert r.status_code == 200 and r.json()["params"]["s0"] == 100
    assert client.put("/api/settings/score", json={"workspace_id": alice.workspace_id, "s0": 10},
                      headers=bob.headers).status_code == 404
    assert client.put("/api/settings/score", json={"workspace_id": alice.workspace_id, "weights": {"BOGUS": 1}},
                      headers=alice.headers).status_code == 400
    _, wid = setup_project(client, alice, project_dir)
    assert run(client, db, alice, wid)["score"] == 55  # S0=100 → round(100·e^(−59/100))

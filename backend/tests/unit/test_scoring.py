import math
import random
from datetime import UTC, datetime, timedelta

from app.analyzers.common.finding import Finding
from app.scoring.formula import DEFAULT_PARAMS, compute_score, scale_for, score_params
from app.scoring.priority import fix_effort_default, priority_list
from app.scoring.trend import linear_trend, scanner_set_signature


def F(sev="HIGH", cls="password", line=1, conf=0.9, diff=None, category="SECRET"):
    return Finding(category=category, cls=cls, rule_id="R", title=cls, severity=sev, path="a.kt", line=line,
                   confidence=conf, context_key=f"{cls}{line}{sev}", diff_status=diff)


def test_formula_hand_examples():
    assert compute_score([], 500).score == 100
    # 1 CRITICAL + 7 HIGH + 7 MEDIUM, small project: penalty 10+35+14 = 59, S = 50 → round(100·e^(−1.18)) = 31
    fs = [F("CRITICAL", line=0)] + [F("HIGH", line=i) for i in range(1, 8)] + [F("MEDIUM", line=i) for i in range(8, 15)]
    r = compute_score(fs, 800)
    assert r.penalty == 59 and r.scale == 50 and r.score == round(100 * math.exp(-59 / 50)) == 31
    assert r.breakdown["by_severity"]["CRITICAL"] == {"count": 1, "penalty": 10.0}
    assert r.formula_version == DEFAULT_PARAMS["formula_version"]


def test_low_confidence_findings_do_not_count():
    assert compute_score([F("CRITICAL", conf=0.3)], 100).score == 100


def test_novelty_new_findings_weigh_more():
    assert compute_score([F("HIGH", diff="new")], 100).penalty == 7.5
    assert compute_score([F("HIGH", diff="existing")], 100).penalty == 5
    assert compute_score([F("HIGH")], 100).penalty == 5  # no diff context → 1.0


def test_loc_normalization():
    assert scale_for(500, 50) == 50 and scale_for(1000, 50) == 50
    assert scale_for(16000, 50) == 200
    one_small = compute_score([F("CRITICAL")], 300).score
    ten_big = compute_score([F("CRITICAL", line=i) for i in range(10)], 100_000).score
    assert one_small > 0 and ten_big < 100 and one_small == round(100 * math.exp(-10 / 50))


def test_deterministic_and_order_independent():
    fs = [F(random.choice(["LOW", "MEDIUM", "HIGH", "CRITICAL"]), line=i) for i in range(40)]
    a = compute_score(fs, 4321)
    shuffled = fs[:]
    random.shuffle(shuffled)
    b = compute_score(shuffled, 4321)
    assert a.score == b.score and a.penalty == b.penalty and a.breakdown == b.breakdown


def test_workspace_params_override():
    p = score_params({"score": {"s0": 100, "weights": {"CRITICAL": 20}}})
    assert p["s0"] == 100 and p["weights"]["CRITICAL"] == 20 and p["weights"]["HIGH"] == 5
    assert compute_score([F("CRITICAL")], 100, p).penalty == 20


def test_priority_list_expected_gain_and_order():
    fs = [F("CRITICAL", cls="object-authorization", line=1), F("HIGH", cls="password", line=2),
          F("MEDIUM", cls="known-vulnerable-dependency", category="SCA", line=3), F("HIGH", cls="password", line=4, diff="new")]
    base = compute_score(fs, 800)
    pl = priority_list(fs, 800)
    # priority = weight × novelty / effort: new HIGH password 5×1.5/1=7.5, HIGH password 5/1, CRITICAL IDOR 10/3, MEDIUM SCA 2/1
    assert [i["finding_id"] for i in pl] == [fs[3].id, fs[1].id, fs[0].id, fs[2].id]
    assert pl[0]["priority"] == 7.5 and pl[0]["fix_effort_source"] == "default"
    alone = compute_score([f for f in fs if f.id != fs[3].id], 800).score - base.score
    assert pl[0]["expected_gain"] == alone
    cumulative = compute_score([fs[0], fs[2]], 800).score - base.score
    assert pl[1]["cumulative_gain"] == cumulative
    assert fix_effort_default("object-authorization") == 3 and fix_effort_default("sql-injection") == 2
    assert fix_effort_default("known-vulnerable-dependency") == 1 and fix_effort_default("recoverable-token") == 2


def test_priority_uses_validated_ai_efforts():
    fs = [F("HIGH", line=1), F("HIGH", line=2)]
    pl = priority_list(fs, 100, ai_efforts={fs[1].id: 5, fs[0].id: 9, "unknown": 1})
    by = {i["finding_id"]: i for i in pl}
    assert by[fs[1].id]["fix_effort"] == 5 and by[fs[1].id]["fix_effort_source"] == "ai"
    assert by[fs[0].id]["fix_effort_source"] == "default"  # 9 is out of 1..5 → rejected


def test_linear_trend_slope_per_week_and_insufficient_data():
    t0 = datetime(2026, 11, 1, tzinfo=UTC)
    pts = [(t0 + timedelta(days=d), 40 + d) for d in range(0, 14, 2)]  # +1 point per day
    tr = linear_trend(pts)
    assert tr["enough_data"] and abs(tr["slope_per_week"] - 7.0) < 1e-6
    assert linear_trend(pts[:2]) == {"enough_data": False, "slope_per_week": None, "points": 2}


def test_linear_trend_needs_at_least_a_day_of_history():
    """Runs minutes apart must not be extrapolated to «+1964 points per week»."""
    t0 = datetime(2026, 11, 21, 14, 0, tzinfo=UTC)
    burst = [(t0 + timedelta(minutes=m), 17 + m) for m in (0, 5, 10)]
    assert linear_trend(burst) == {"enough_data": False, "slope_per_week": None, "points": 3}
    day = [(t0 + timedelta(hours=h), 17 + h / 24) for h in (0, 12, 24)]
    assert linear_trend(day)["enough_data"] is True


def test_scanner_set_signature_ignores_order_and_non_scanners():
    g1 = {"nodes": [{"type": "scanner.sca"}, {"type": "scanner.secrets"}, {"type": "logic.merge"}]}
    g2 = {"nodes": [{"type": "scanner.secrets"}, {"type": "scanner.sca"}, {"type": "scanner.diff"}]}
    assert scanner_set_signature(g1) == scanner_set_signature(g2) == "scanner.sca+scanner.secrets"
    assert scanner_set_signature({"nodes": [{"type": "scanner.sca", "disabled": True}]}) == ""

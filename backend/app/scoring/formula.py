"""Security Score — an explainable, deterministic metric of a project's internal trend (not a cross-project rating).

    penalty = Σ weight(severity) × novelty(f)      over findings with confidence ≥ the official export threshold
    weight:  CRITICAL=10, HIGH=5, MEDIUM=2, LOW=1
    novelty: new=1.5, existing=1.0 (no diff context → 1.0)
    S       = S0 × max(1, sqrt(LOC / 1000))          size normalization
    score   = round(100 × exp(−penalty / S))         0..100, smooth, never reaches 0

Depends only on the finding set and LOC (no LLM), independent of order. Parameters live in workspace settings
(``settings.score``); every run stores ``score_formula_version``.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any

from app.analyzers.common.finding import Finding
from app.export.submission_json import OFFICIAL_MIN_CONFIDENCE

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
DEFAULT_PARAMS: dict[str, Any] = {
    "formula_version": "1",
    "weights": {"CRITICAL": 10.0, "HIGH": 5.0, "MEDIUM": 2.0, "LOW": 1.0},
    "novelty": {"new": 1.5, "existing": 1.0},
    "s0": 50.0,
    "min_confidence": OFFICIAL_MIN_CONFIDENCE,
}


def score_params(workspace_settings: dict | None) -> dict[str, Any]:
    """Defaults overridden by ``workspace.settings['score']`` (only known keys, numeric values)."""
    p = copy.deepcopy(DEFAULT_PARAMS)
    over = (workspace_settings or {}).get("score") or {}
    for k in ("weights", "novelty"):
        for kk, v in (over.get(k) or {}).items():
            if kk in p[k] and isinstance(v, int | float) and v >= 0:
                p[k][kk] = float(v)
    for k in ("s0", "min_confidence"):
        v = over.get(k)
        if isinstance(v, int | float) and v > 0:
            p[k] = float(v)
    return p


def scale_for(loc: int | None, s0: float) -> float:
    return s0 * max(1.0, math.sqrt(max(int(loc or 0), 0) / 1000))


def counted(findings: list[Finding], params: dict) -> list[Finding]:
    return [f for f in findings if f.confidence >= params["min_confidence"] and f.scope != "transitive"]


def finding_penalty(f: Finding, params: dict) -> float:
    novelty = params["novelty"]["new"] if f.diff_status == "new" else params["novelty"]["existing"]
    return params["weights"].get(f.severity, 0.0) * novelty


@dataclass
class ScoreResult:
    score: int
    penalty: float
    scale: float
    loc: int
    formula_version: str
    breakdown: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"score": self.score, "penalty": self.penalty, "scale": self.scale, "loc": self.loc,
                "formula_version": self.formula_version, "breakdown": self.breakdown}


def compute_score(findings: list[Finding], loc: int | None, params: dict | None = None) -> ScoreResult:
    p = params or DEFAULT_PARAMS
    fs = counted(findings, p)
    by_sev = {s: {"count": 0, "penalty": 0.0} for s in SEVERITIES}
    by_cat: dict[str, float] = {}
    for f in fs:
        pen = finding_penalty(f, p)
        by_sev[f.severity]["count"] += 1
        by_sev[f.severity]["penalty"] += pen
        by_cat[f.category] = by_cat.get(f.category, 0.0) + pen
    penalty = round(sum(v["penalty"] for v in by_sev.values()), 6)
    scale = scale_for(loc, p["s0"])
    score = int(round(100 * math.exp(-penalty / scale)))
    new_count = sum(1 for f in fs if f.diff_status == "new")
    return ScoreResult(score=score, penalty=penalty, scale=round(scale, 4), loc=int(loc or 0),
                       formula_version=str(p["formula_version"]),
                       breakdown={"by_severity": {k: {"count": v["count"], "penalty": round(v["penalty"], 4)}
                                                  for k, v in by_sev.items()},
                                  "by_category": {k: round(v, 4) for k, v in sorted(by_cat.items())},
                                  "counted": len(fs), "ignored": len(findings) - len(fs), "new": new_count,
                                  "params": {"weights": p["weights"], "novelty": p["novelty"], "s0": p["s0"],
                                             "min_confidence": p["min_confidence"]}})

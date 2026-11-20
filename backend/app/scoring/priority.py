"""Priority Fix List: priority = weight × novelty / fix_effort; expected +score is deterministic (recompute the score
without the finding; cumulative for the top-N)."""

from __future__ import annotations

from app.analyzers.common.finding import Finding
from app.scoring.formula import DEFAULT_PARAMS, compute_score, counted, finding_penalty

# 1 — change a line, 5 — rewrite a module
DEFAULT_EFFORT = {
    "known-vulnerable-dependency": 1, "password": 1, "api-key": 1, "configuration-token": 1, "secret-fallback": 1,
    "private-key": 1, "aws-access-key": 1, "github-token": 1, "telegram-token": 1, "jwt": 1, "db-credentials": 1,
    "generic-secret": 1, "basic-auth": 1, "url-credentials": 1, "slack-token": 1, "stripe-key": 1,
    "google-api-key": 1, "recoverable-token": 2, "sql-injection": 2, "tls-verification": 2, "credentialed-cors": 2,
    "route-authorization": 2, "hardcoded-credentials": 2, "insecure-endpoint": 2, "weak-crypto": 2,
    "csrf-disabled": 2, "object-authorization": 3, "path-traversal": 3, "missing-input-validation": 3,
    "unsafe-deserialization": 4,
}
EFFORT_WORDS = {"ru": {1: "заменить строку", 2: "небольшая правка", 3: "правка нескольких мест", 4: "переработка",
                       5: "переписать модуль"},
                "en": {1: "change a line", 2: "small change", 3: "several places", 4: "rework", 5: "rewrite a module"}}


def fix_effort_default(cls: str) -> int:
    return DEFAULT_EFFORT.get(cls, 2)


def valid_efforts(ai_efforts: dict | None, ids: set[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for fid, v in (ai_efforts or {}).items():
        if fid in ids and isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 5:
            out[fid] = v
    return out


def priority_list(findings: list[Finding], loc: int | None, params: dict | None = None,
                  ai_efforts: dict | None = None, language: str = "ru") -> list[dict]:
    p = params or DEFAULT_PARAMS
    fs = counted(findings, p)
    efforts = valid_efforts(ai_efforts, {f.id for f in fs})
    base = compute_score(findings, loc, p).score
    rows = []
    for f in fs:
        effort = efforts.get(f.id, fix_effort_default(f.cls))
        rows.append((f, effort, round(finding_penalty(f, p) / effort, 4)))
    rows.sort(key=lambda r: (-r[2], -finding_penalty(r[0], p), r[0].path, r[0].line, r[0].id))
    out, removed = [], set()
    for rank, (f, effort, prio) in enumerate(rows, 1):
        alone = compute_score([g for g in findings if g.id != f.id], loc, p).score - base
        removed.add(f.id)
        cumulative = compute_score([g for g in findings if g.id not in removed], loc, p).score - base
        novelty = "new" if f.diff_status == "new" else "existing"
        out.append({"rank": rank, "finding_id": f.id, "title": f.title, "class": f.cls, "category": f.category,
                    "severity": f.severity, "path": f.path, "line": f.line, "group": f.group,
                    "artifact": f.artifact, "version": f.version, "advisory_id": f.advisory_id,
                    "novelty": novelty, "fix_effort": effort,
                    "fix_effort_source": "ai" if f.id in efforts else "default",
                    "effort_words": EFFORT_WORDS.get(language, EFFORT_WORDS["ru"])[effort],
                    "priority": prio, "expected_gain": alone, "cumulative_gain": cumulative})
    return out

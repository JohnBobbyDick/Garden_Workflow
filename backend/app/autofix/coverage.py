"""AutoFix coverage computed from rule metadata (never hand-written): «AutoFix доступен для N из M правил»."""

from __future__ import annotations

from app.analyzers.sast.detector import ALL_RULES, AUTOFIX
from app.analyzers.secrets.detector import CLASS_TITLES, SECRET_AUTOFIX

SCA_RULES = {"known-vulnerable-dependency": "deterministic"}


def rule_catalog() -> list[dict]:
    rules = [{"category": "SECRET", "class": c, "autofix": SECRET_AUTOFIX.get(c, "llm")} for c in sorted(CLASS_TITLES)]
    rules += [{"category": "SAST", "class": c, "autofix": AUTOFIX.get(c, "none")} for c in ALL_RULES]
    rules += [{"category": "SCA", "class": c, "autofix": k} for c, k in SCA_RULES.items()]
    return rules


def coverage() -> dict:
    rules = rule_catalog()
    by_kind: dict[str, int] = {"llm": 0, "deterministic": 0, "none": 0}
    for r in rules:
        by_kind[r["autofix"]] += 1
    available = by_kind["llm"] + by_kind["deterministic"]
    return {"available": available, "total": len(rules), "by_kind": by_kind, "rules": rules,
            "text": f"AutoFix доступен для {available} из {len(rules)} правил"}

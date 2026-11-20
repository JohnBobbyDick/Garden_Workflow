"""Score bookkeeping: computed at the end of every successful run that has analyzers (even without the score node),
so the project trend is continuous; delta is relative to the previous successful run of the same project with the
same scanner set."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.analyzers.common.finding import Finding
from app.db import Database
from app.scoring.formula import compute_score, score_params
from app.scoring.priority import priority_list
from app.scoring.trend import linear_trend, scanner_set_signature

logger = logging.getLogger(__name__)
PERIODS = {"7d": 7, "30d": 30, "90d": 90}
TOP_IN_DETAILS = 20


def _same_project(stmt, run: m.Run):  # noqa: ANN001, ANN202
    if run.project_id:
        return stmt.where(m.Run.project_id == run.project_id)
    return stmt.where(m.Run.project_id.is_(None), m.Run.workflow_id == run.workflow_id)


def previous_run(s: Session, run: m.Run, signature: str) -> m.Run | None:
    stmt = select(m.Run).where(m.Run.workspace_id == run.workspace_id, m.Run.id != run.id,
                               m.Run.status == "success", m.Run.score.is_not(None),
                               m.Run.scanner_set_signature == signature, m.Run.created_at < run.created_at)
    return s.scalars(_same_project(stmt, run).order_by(m.Run.created_at.desc()).limit(1)).first()


def score_run(s: Session, run: m.Run, findings: list[Finding]) -> dict | None:
    signature = scanner_set_signature(run.graph_snapshot)
    if not signature:
        return None
    ws = s.get(m.Workspace, run.workspace_id)
    params = score_params(ws.settings if ws else {})
    res = compute_score(findings, run.loc, params)
    prev = previous_run(s, run, signature)
    delta = res.score - prev.score if prev is not None else None
    lang = (ws.settings or {}).get("language", "ru") if ws else "ru"
    details = {**res.as_dict(), "previous_run_id": prev.id if prev else None,
               "priority": priority_list(findings, run.loc, params, language=lang)[:TOP_IN_DETAILS]}
    run.score, run.score_delta, run.score_details = res.score, delta, details
    run.score_formula_version, run.scanner_set_signature = res.formula_version, signature
    return details


def record_score(db: Database, run_id: str, findings: list[Finding]) -> None:  # post-run hook
    with db.session() as s:
        run = s.get(m.Run, run_id)
        if run is None or run.status != "success":
            return
        if score_run(s, run, findings) is not None:
            s.commit()


def history(s: Session, workspace_id: str, project_id: str, period: str = "30d",
            now: datetime | None = None) -> dict:
    days = PERIODS.get(period, 30)
    since = (now or datetime.now(UTC)) - timedelta(days=days)
    rows = s.scalars(select(m.Run).where(m.Run.workspace_id == workspace_id, m.Run.project_id == project_id,
                                         m.Run.status == "success", m.Run.score.is_not(None),
                                         m.Run.created_at >= since).order_by(m.Run.created_at)).all()
    points, markers = [], []
    prev_sig = prev_ver = None
    for r in rows:
        at = r.finished_at or r.created_at
        points.append({"run_id": r.id, "at": at, "score": r.score, "delta": r.score_delta,
                       "findings_by_severity": (r.summary or {}).get("by_severity", {}),
                       "verdict": (r.verdict or {}).get("verdict"), "loc": r.loc,
                       "commit": (r.source or {}).get("commit") or (r.trigger_payload or {}).get("head_sha"),
                       "formula_version": r.score_formula_version, "scanner_set": r.scanner_set_signature})
        if prev_sig is not None and r.scanner_set_signature != prev_sig:
            markers.append({"run_id": r.id, "at": at, "kind": "scanner_set", "value": r.scanner_set_signature})
        if prev_ver is not None and r.score_formula_version != prev_ver:
            markers.append({"run_id": r.id, "at": at, "kind": "formula", "value": r.score_formula_version})
        prev_sig, prev_ver = r.scanner_set_signature, r.score_formula_version
    # the trend uses the latest comparable segment only (same scanner set and formula)
    seg = [p for p in points if p["scanner_set"] == prev_sig and p["formula_version"] == prev_ver]
    trend = linear_trend([(p["at"], p["score"]) for p in seg])
    return {"period": period if period in PERIODS else "30d", "points": points, "markers": markers, "trend": trend,
            "note": "Security Score — метрика внутреннего тренда проекта, не рейтинг между проектами"}

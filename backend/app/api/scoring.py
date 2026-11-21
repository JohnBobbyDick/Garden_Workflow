"""Security Score API (12A.2): history + trend, run score with Priority Fix List, AI sprint plan, dashboard, settings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m
from app.ai.providers.base import build_provider
from app.ai.settings_service import provider_config_for
from app.ai.validator import allowed_advisories
from app.analyzers.sca.vulndb import VulnDB
from app.api.runs import _findings
from app.core.audit import audit
from app.core.errors import ApiError, not_found
from app.core.masking import Masker
from app.deps import client_ip, current_user, get_session, load_scoped, resolve_workspace
from app.scoring.formula import DEFAULT_PARAMS, score_params
from app.scoring.priority import priority_list
from app.scoring.service import PERIODS, history
from app.scoring.sprint_plan import generate_sprint_plan

router = APIRouter(tags=["score"])
NOTE = "Security Score — метрика внутреннего тренда проекта, не рейтинг между проектами"


def _params(s: Session, workspace_id: str) -> dict:
    ws = s.get(m.Workspace, workspace_id)
    return score_params(ws.settings if ws else {})


def _latest_plan(s: Session, run_id: str) -> m.AIReport | None:
    return s.scalars(select(m.AIReport).where(m.AIReport.run_id == run_id, m.AIReport.kind == "sprint_plan")
                     .order_by(m.AIReport.created_at.desc())).first()


def plan_out(r: m.AIReport) -> dict:
    return {"id": r.id, "run_id": r.run_id, "ai_generated": r.ai_generated, "provider": r.provider, "model": r.model,
            "language": r.language, "plan": r.report, "validation": r.validation, "usage": r.usage,
            "created_at": r.created_at}


@router.get("/projects/{project_id}/score/history")
def score_history(project_id: str, period: str = "30d", user: m.User = Depends(current_user),
                  s: Session = Depends(get_session)) -> dict:
    if period not in PERIODS:
        raise ApiError(400, "bad_period", "period: 7d | 30d | 90d")
    p = load_scoped(s, m.Project, project_id, user, what="проект")
    return {"project_id": p.id, **history(s, p.workspace_id, p.id, period)}


@router.get("/runs/{run_id}/score")
def run_score(run_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    run = load_scoped(s, m.Run, run_id, user, what="запуск")
    if run.score is None:
        raise not_found("score запуска (в запуске нет анализаторов или он не завершён)")
    params = _params(s, run.workspace_id)
    plan = _latest_plan(s, run.id)
    efforts = {}
    if plan is not None and plan.ai_generated:
        efforts = {i["finding_id"]: i["fix_effort"] for i in (plan.report or {}).get("priority", [])
                   if i.get("fix_effort_source") == "ai"}
    details = run.score_details or {}
    return {"run_id": run.id, "score": run.score, "delta": run.score_delta, "loc": run.loc,
            "penalty": details.get("penalty"), "scale": details.get("scale"), "breakdown": details.get("breakdown"),
            "formula_version": run.score_formula_version, "scanner_set": run.scanner_set_signature,
            "previous_run_id": details.get("previous_run_id"),
            "priority": priority_list(_findings(s, run.id), run.loc, params, ai_efforts=efforts),
            "sprint_plan": plan_out(plan) if plan else None, "note": NOTE}


class SprintIn(BaseModel):
    language: str | None = Field(default=None, pattern="^(ru|en)$")


@router.post("/runs/{run_id}/sprint-plan")
async def sprint_plan(run_id: str, request: Request, body: SprintIn | None = None,
                      user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    run = load_scoped(s, m.Run, run_id, user, "developer", "запуск")
    if run.score is None:
        raise ApiError(409, "no_score", "у запуска нет Security Score")
    findings = _findings(s, run.id)
    params = _params(s, run.workspace_id)
    masker = Masker()
    cfg = provider_config_for(s, run.workspace_id, None, masker)
    provider = build_provider(cfg) if cfg is not None else None
    trend = None
    if run.project_id:
        trend = history(s, run.workspace_id, run.project_id, "30d")["trend"]
    ws = s.get(m.Workspace, run.workspace_id)
    lang = (body.language if body and body.language else None) or (ws.settings or {}).get("language", "ru")
    out = await generate_sprint_plan(findings, run.loc, params, run.score, run.score_delta, trend, provider,
                                     allowed_advisories=allowed_advisories(findings, VulnDB.load().all_ids()),
                                     masker=masker, language=lang)
    row = m.AIReport(run_id=run.id, kind="sprint_plan", provider=out.provider, model=out.model, language=lang,
                     ai_generated=out.ai_generated, report=masker.mask_obj(out.plan),
                     validation={**out.validation, **({"error": out.error} if out.error else {})},
                     usage=out.usage)
    s.add(row)
    audit(s, "score.sprint_plan", user_id=user.id, workspace_id=run.workspace_id, target=run.id,
          details={"ai_generated": out.ai_generated}, ip=client_ip(request))
    s.commit()
    return plan_out(row)


def _commit(run: m.Run) -> str | None:
    sha = (run.source or {}).get("commit") or (run.trigger_payload or {}).get("head_sha")
    return sha[:7] if sha else None


def _blocking(run: m.Run) -> int:
    """New findings at/above the diff threshold if a diff verdict exists, otherwise CRITICAL findings (gate default)."""
    v = run.verdict or {}
    if v.get("new_counts_by_severity") is not None:
        order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        th = order.index(v.get("threshold", "CRITICAL")) if v.get("threshold") in order else 3
        return sum(int(c) for k, c in v["new_counts_by_severity"].items() if k in order and order.index(k) >= th)
    return int(((run.summary or {}).get("by_severity") or {}).get("CRITICAL", 0))


def _period_cards(s: Session, ws: str, period: str) -> dict:
    since = datetime.now(UTC) - timedelta(days=PERIODS[period])
    runs = s.scalars(select(m.Run).where(m.Run.workspace_id == ws, m.Run.created_at >= since)
                     .order_by(m.Run.created_at.desc())).all()
    last = next((r for r in runs if r.status == "success"), None)
    validated = s.scalar(select(func.count()).select_from(m.Autofix).join(m.Run, m.Run.id == m.Autofix.run_id)
                         .where(m.Run.workspace_id == ws, m.Autofix.status == "validated",
                                m.Autofix.created_at >= since)) or 0
    wf_names = {w.id: w.name for w in s.scalars(select(m.Workflow).where(m.Workflow.workspace_id == ws))}
    return {
        "period": period, "checks": len(runs),
        "open_findings": int((last.summary or {}).get("total", 0)) if last else 0,
        "blocking_findings": _blocking(last) if last else 0,
        "validated_patches": int(validated),
        "findings_by_category": dict((last.summary or {}).get("by_category") or {}) if last else {},
        # severity levels describe the same run as the cards above (not only runs that carry a score)
        "findings_by_severity": {k: int(((last.summary or {}).get("by_severity") or {}).get(k, 0)) if last else 0
                                 for k in ("CRITICAL", "HIGH", "MEDIUM", "LOW")},
        "last_run_id": last.id if last else None,
        "recent_runs": [{"id": r.id, "workflow_id": r.workflow_id, "workflow_name": wf_names.get(r.workflow_id),
                         "created_at": r.created_at, "status": r.status, "score": r.score, "score_delta": r.score_delta,
                         "gate": r.gate, "verdict": (r.verdict or {}).get("verdict"), "commit": _commit(r),
                         "pr_number": (r.trigger_payload or {}).get("pr_number"),
                         "total": (r.summary or {}).get("total")} for r in runs[:10]],
    }


@router.get("/dashboard")
def dashboard(workspace_id: str | None = None, period: Literal["7d", "30d"] = "7d",
              user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, workspace_id)
    count = lambda model: s.scalar(select(func.count()).select_from(model).where(model.workspace_id == ws))  # noqa: E731
    latest = s.scalars(select(m.Run).where(m.Run.workspace_id == ws, m.Run.status == "success",
                                           m.Run.score.is_not(None)).order_by(m.Run.created_at.desc()).limit(1)).first()
    score = None
    if latest is not None:
        hist = history(s, ws, latest.project_id, period) if latest.project_id else None
        plan = _latest_plan(s, latest.id)
        score = {"run_id": latest.id, "project_id": latest.project_id, "workflow_id": latest.workflow_id,
                 "value": latest.score, "delta": latest.score_delta,
                 "trend": hist["trend"] if hist else {"enough_data": False, "slope_per_week": None, "points": 0},
                 "history": hist["points"] if hist else [], "markers": hist["markers"] if hist else [],
                 "top3": (latest.score_details or {}).get("priority", [])[:3],
                 "sprint_plan": plan_out(plan) if plan else None, "note": NOTE}
    return {"workspace_id": ws, "projects": count(m.Project), "workflows": count(m.Workflow), "runs": count(m.Run),
            "score": score, **_period_cards(s, ws, period)}


class ScoreSettingsIn(BaseModel):
    workspace_id: str | None = None
    s0: float | None = Field(default=None, gt=0, le=10_000)
    weights: dict[str, float] | None = None
    novelty: dict[str, float] | None = None
    min_confidence: float | None = Field(default=None, gt=0, le=1)


@router.get("/settings/score")
def get_score_settings(workspace_id: str | None = None, user: m.User = Depends(current_user),
                       s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, workspace_id)
    return {"params": _params(s, ws), "defaults": DEFAULT_PARAMS}


@router.put("/settings/score")
def put_score_settings(body: ScoreSettingsIn, request: Request, user: m.User = Depends(current_user),
                       s: Session = Depends(get_session)) -> dict:
    ws_id = resolve_workspace(s, user, body.workspace_id, "admin")
    for group, keys in (("weights", DEFAULT_PARAMS["weights"]), ("novelty", DEFAULT_PARAMS["novelty"])):
        bad = set(getattr(body, group) or {}) - set(keys)
        if bad or any(v < 0 or v > 1000 for v in (getattr(body, group) or {}).values()):
            raise ApiError(400, "bad_score_params", f"{group}: допустимые ключи {sorted(keys)}, значения 0..1000")
    ws = s.get(m.Workspace, ws_id)
    over = body.model_dump(exclude_none=True, exclude={"workspace_id"})
    ws.settings = {**(ws.settings or {}), "score": over}
    audit(s, "settings.score", user_id=user.id, workspace_id=ws_id, details=over, ip=client_ip(request))
    s.commit()
    return {"params": score_params(ws.settings), "defaults": DEFAULT_PARAMS}

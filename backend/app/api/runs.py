from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.analyzers.common.finding import SEVERITY_ORDER, Finding
from app.core.errors import ApiError, bad_request, not_found
from app.db import get_db
from app.deps import current_user, get_session, load_scoped, require_role, resolve_workspace
from app.engine import runs as run_service
from app.engine.data import finding_dict
from app.export.submission_json import OFFICIAL_MIN_CONFIDENCE
from app.nodes.output.report_export import ExportValidationError, build_reports
from app.nodes.source.repo_source import INTERNAL_SOURCE_KEYS

router = APIRouter(tags=["runs"])
TERMINAL = {"success", "failed", "cancelled"}
EXPORTS = {"submission.json": ("submission_json", "application/json"),
           "report.md": ("markdown", "text/markdown; charset=utf-8"),
           "report.html": ("html", "text/html; charset=utf-8")}


def run_out(s: Session, r: m.Run, full: bool = False) -> dict:
    wf = s.get(m.Workflow, r.workflow_id) if r.workflow_id else None
    d = {"id": r.id, "workspace_id": r.workspace_id, "workflow_id": r.workflow_id,
         "workflow_name": wf.name if wf else None, "project_id": r.project_id, "status": r.status,
         "trigger_type": r.trigger_type, "triggered_by": r.triggered_by, "created_at": r.created_at,
         "started_at": r.started_at, "finished_at": r.finished_at,
         "duration_ms": int((r.finished_at - r.started_at).total_seconds() * 1000)
         if r.finished_at and r.started_at else None,
         "error": r.error, "summary": r.summary or {}, "gate": r.gate, "verdict": r.verdict, "score": r.score,
         "score_delta": r.score_delta}
    if full:
        d["graph_snapshot"] = r.graph_snapshot
        d["source"] = {k: v for k, v in (r.source or {}).items() if k not in INTERNAL_SOURCE_KEYS}
        d["trigger_payload"] = {k: v for k, v in (r.trigger_payload or {}).items() if k != "diff_context"}
        d["notifications"] = r.notifications or []
        d["nodes"] = [{"node_id": n.node_id, "node_type": n.node_type, "status": n.status, "started_at": n.started_at,
                       "finished_at": n.finished_at, "duration_ms": n.duration_ms, "error": n.error,
                       "output_summary": n.output_summary}
                      for n in s.scalars(select(m.NodeRun).where(m.NodeRun.run_id == r.id))]
        d["artifacts"] = [{"name": a.name, "content_type": a.content_type, "size": a.size, "node_id": a.node_id,
                           "url": f"/api/runs/{r.id}/artifacts/{a.name}"}
                          for a in s.scalars(select(m.Artifact).where(m.Artifact.run_id == r.id))]
        d["score_details"] = r.score_details
        d["loc"] = r.loc
    return d


@router.get("/runs")
def list_runs(workspace_id: str | None = None, workflow_id: str | None = None, status: str | None = None,
              trigger_type: str | None = None, triggered_by: str | None = None, project_id: str | None = None,
              since: datetime | None = None, until: datetime | None = None, limit: int = 50, offset: int = 0,
              user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, workspace_id)
    q = select(m.Run).where(m.Run.workspace_id == ws)
    if workflow_id:
        q = q.where(m.Run.workflow_id == workflow_id)
    if status:
        q = q.where(m.Run.status == status)
    if trigger_type:
        q = q.where(m.Run.trigger_type == trigger_type)
    if triggered_by:
        q = q.where(m.Run.triggered_by == triggered_by)
    if project_id:
        q = q.where(m.Run.project_id == project_id)
    if since:
        q = q.where(m.Run.created_at >= since)
    if until:
        q = q.where(m.Run.created_at <= until)
    rows = s.scalars(q.order_by(m.Run.created_at.desc()).offset(max(offset, 0)).limit(min(max(limit, 1), 200))).all()
    return {"runs": [run_out(s, r) for r in rows]}


def _findings(s: Session, run_id: str) -> list[Finding]:
    recs = s.scalars(select(m.FindingRecord).where(m.FindingRecord.run_id == run_id).order_by(m.FindingRecord.id))
    out: dict[str, Finding] = {}
    for r in recs:
        out[r.finding_id] = Finding.model_validate(r.data)
    return list(out.values())


def _brief(f: Finding) -> dict:
    return {"id": f.id, "category": f.category, "class": f.cls, "severity": f.severity, "title": f.title,
            "path": f.path, "line": f.line, "end_line": f.end_line, "group": f.group, "artifact": f.artifact,
            "version": f.version, "advisory_id": f.advisory_id}


@router.get("/runs/compare")
def compare_runs(base: str, head: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    rb = load_scoped(s, m.Run, base, user, what="запуск")
    rh = load_scoped(s, m.Run, head, user, what="запуск")
    if rb.workspace_id != rh.workspace_id:
        raise bad_request("запуски из разных рабочих пространств")
    fb = {f.id: f for f in _findings(s, rb.id)}
    fh = {f.id: f for f in _findings(s, rh.id)}
    new = [fh[i] for i in fh if i not in fb]
    fixed = [fb[i] for i in fb if i not in fh]
    unchanged = [fh[i] for i in fh if i in fb and fh[i].severity == fb[i].severity]
    changed = [{"finding": _brief(fh[i]), "from": fb[i].severity, "to": fh[i].severity}
               for i in fh if i in fb and fh[i].severity != fb[i].severity]
    cats: dict[str, Counter] = {}
    for name, items in (("new", new), ("fixed", fixed), ("unchanged", unchanged)):
        for f in items:
            cats.setdefault(f.category, Counter())[name] += 1
    for c in changed:
        cats.setdefault(c["finding"]["category"], Counter())["severity_changed"] += 1
    return {"base": run_out(s, rb), "head": run_out(s, rh), "new": [_brief(f) for f in new],
            "fixed": [_brief(f) for f in fixed], "unchanged": [_brief(f) for f in unchanged],
            "severity_changed": changed,
            "by_category": {k: {x: v.get(x, 0) for x in ("new", "fixed", "unchanged", "severity_changed")}
                            for k, v in cats.items()}}


@router.get("/runs/{run_id}")
def get_run(run_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    return run_out(s, load_scoped(s, m.Run, run_id, user, what="запуск"), full=True)


@router.post("/runs/{run_id}/cancel", status_code=202)
def cancel_run(run_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    r = load_scoped(s, m.Run, run_id, user, "developer", "запуск")
    if r.status in TERMINAL:
        raise ApiError(409, "run_finished", "запуск уже завершён")
    run_service.request_cancel(s, r)
    s.commit()
    return {"id": r.id, "status": r.status, "cancel_requested": r.cancel_requested}


@router.get("/runs/{run_id}/findings")
def run_findings(run_id: str, category: str | None = None, severity: str | None = None, cls: str | None = None,
                 min_confidence: float | None = None, diff_status: str | None = None, sort: str = "severity",
                 user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    r = load_scoped(s, m.Run, run_id, user, what="запуск")
    fs = _findings(s, r.id)
    if category:
        fs = [f for f in fs if f.category == category.upper()]
    if severity:
        fs = [f for f in fs if f.severity == severity.upper()]
    if cls:
        fs = [f for f in fs if f.cls == cls]
    if min_confidence is not None:
        fs = [f for f in fs if f.confidence >= min_confidence]
    if diff_status:
        fs = [f for f in fs if f.diff_status == diff_status]
    if sort == "path":
        fs.sort(key=lambda f: (f.path, f.line))
    else:
        fs.sort(key=lambda f: (-SEVERITY_ORDER[f.severity], f.category, f.path, f.line))
    return {"findings": [{**finding_dict(f), "official": f.confidence >= OFFICIAL_MIN_CONFIDENCE} for f in fs],
            "official_min_confidence": OFFICIAL_MIN_CONFIDENCE}


@router.get("/runs/{run_id}/artifacts/{name}")
def get_artifact(run_id: str, name: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)):
    r = load_scoped(s, m.Run, run_id, user, what="запуск")
    a = s.scalars(select(m.Artifact).where(m.Artifact.run_id == r.id, m.Artifact.name == name)).first()
    if a is None:
        raise not_found("артефакт")
    return Response(a.content, media_type=a.content_type,
                    headers={"Content-Disposition": f'attachment; filename="{a.name}"'})


@router.get("/runs/{run_id}/export/{fmt}")
def export_run(run_id: str, fmt: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)):
    r = load_scoped(s, m.Run, run_id, user, what="запуск")
    if fmt not in EXPORTS:
        raise not_found("формат экспорта")
    key, ctype = EXPORTS[fmt]
    project = s.get(m.Project, r.project_id).name if r.project_id and s.get(m.Project, r.project_id) else None
    wf = s.get(m.Workflow, r.workflow_id) if r.workflow_id else None
    ai = s.scalars(select(m.AIReport).where(m.AIReport.run_id == r.id, m.AIReport.kind == "report")
                   .order_by(m.AIReport.created_at.desc())).first()
    ai_payload = {"report": ai.report, "ai_generated": ai.ai_generated, "validation": ai.validation,
                  "model": ai.model, "provider": ai.provider, "error": (ai.validation or {}).get("error")}         if ai else None
    try:
        reports = build_reports(_findings(s, r.id), project or (wf.name if wf else "project"), OFFICIAL_MIN_CONFIDENCE,
                                False, ai_payload, {"Запуск": r.id, "Сценарий": wf.name if wf else "—"})
    except ExportValidationError as exc:
        raise ApiError(500, "export_invalid", str(exc)) from exc
    if key == "submission_json":
        return JSONResponse(json.loads(reports[key]),
                            headers={"Content-Disposition": 'attachment; filename="submission.json"'})
    return PlainTextResponse(reports[key], media_type=ctype)


def _sse(event_id: int, type_: str, payload: dict) -> str:
    return f"id: {event_id}\nevent: {type_}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request, last_event_id: int | None = None,
                     user: m.User = Depends(current_user), s: Session = Depends(get_session)):
    r = load_scoped(s, m.Run, run_id, user, what="запуск")
    require_role(s, user, r.workspace_id)
    header = request.headers.get("last-event-id")
    start = int(header) if header and header.isdigit() else (last_event_id or 0)
    db = get_db()

    async def stream():
        last = start
        idle = 0.0
        while True:
            with db.session() as ss:
                rows = ss.scalars(select(m.RunEvent).where(m.RunEvent.run_id == run_id, m.RunEvent.id > last)
                                  .order_by(m.RunEvent.id).limit(500)).all()
                status = ss.scalar(select(m.Run.status).where(m.Run.id == run_id))
            for e in rows:
                last = e.id
                yield _sse(e.id, e.type, {"id": e.id, "type": e.type, "node_id": e.node_id, "data": e.data,
                                          "at": e.created_at})
            if rows:
                idle = 0.0
                continue
            if status in TERMINAL:
                return
            if await request.is_disconnected():
                return
            await asyncio.sleep(0.4)
            idle += 0.4
            if idle >= 15:
                idle = 0.0
                yield ": keepalive\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

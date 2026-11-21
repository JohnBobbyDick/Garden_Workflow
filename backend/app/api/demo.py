"""«Демо-данные»: a real demo project on the organizer training fixture and a ready PR-check workflow.

Nothing is simulated: the project points at ``fixtures/organizer-training/training-project`` (read-only, inside
``APP_SCAN_ROOTS``) and the workflow runs the real analyzers, diff-aware verdict, AutoFix and Security Score."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.config import REPO_ROOT, get_settings
from app.core.audit import audit
from app.core.errors import ApiError
from app.core.repo_guard import RepoGuardError, check_scan_path
from app.deps import client_ip, current_user, get_session, resolve_workspace

router = APIRouter(tags=["demo"])
DEMO_PROJECT = "payments-api (демо)"
DEMO_WORKFLOW = "Проверка перед merge"
TRAINING = REPO_ROOT / "fixtures" / "organizer-training" / "training-project"


class DemoIn(BaseModel):
    workspace_id: str | None = None


def demo_graph() -> dict:
    nodes = [
        ("trigger", "trigger.manual", "Триггер", {}, (400, 0)),
        ("src", "source.repo", "Исходный код", {"mode": "project"}, (400, 150)),
        ("secrets", "scanner.secrets", "Secrets", {}, (80, 310)),
        ("sca", "scanner.sca", "SCA", {}, (400, 310)),
        ("sast", "scanner.sast", "SAST", {}, (720, 310)),
        ("merge", "logic.merge", "Все находки", {}, (400, 470)),
        ("diff", "scanner.diff", "Diff Scanner", {"on_missing_diff": "treat_all_as_new"}, (240, 630)),
        ("block", "logic.if_else", "Блокировать PR?", {"expression": "verdict == FAIL"}, (240, 790)),
        ("autofix", "ai.autofix", "AI AutoFix", {}, (240, 950)),
        ("score", "analysis.security_score", "Отчёт и Score", {}, (560, 630)),
        ("report", "output.report_export", "Отчёт", {}, (880, 630)),
    ]
    edges = [("trigger", "out", "src", "in"), ("src", "out", "secrets", "in"), ("src", "out", "sca", "in"),
             ("src", "out", "sast", "in"), ("secrets", "out", "merge", "in"), ("sca", "out", "merge", "in"),
             ("sast", "out", "merge", "in"), ("src", "out", "diff", "repo"), ("merge", "out", "diff", "findings"),
             ("diff", "verdict", "block", "in"), ("block", "true", "autofix", "in"), ("merge", "out", "score", "findings"),
             ("src", "out", "score", "repo"), ("merge", "out", "report", "in")]
    return {"schema_version": 1,
            "nodes": [{"id": i, "type": t, "label": lbl, "config": c, "position": {"x": x, "y": y}}
                      for i, t, lbl, c, (x, y) in nodes],
            "edges": [{"id": f"e{k}", "source": a, "source_port": ap, "target": b, "target_port": bp}
                      for k, (a, ap, b, bp) in enumerate(edges)]}


@router.post("/demo/setup", status_code=201)
def demo_setup(body: DemoIn, request: Request, user: m.User = Depends(current_user),
               s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, body.workspace_id, "developer")
    try:
        path = check_scan_path(str(TRAINING), get_settings().scan_root_paths())
    except RepoGuardError as exc:
        raise ApiError(422, "demo_unavailable", "учебный набор вне APP_SCAN_ROOTS: " + str(exc)) from exc
    project = s.scalars(select(m.Project).where(m.Project.workspace_id == ws, m.Project.name == DEMO_PROJECT)).first()
    if project is None:
        project = m.Project(workspace_id=ws, name=DEMO_PROJECT, description="Учебный проект организаторов (Kotlin, "
                            "Spring Boot, Gradle)", source_mode="path", path=str(path))
        s.add(project)
        s.flush()
    wf = s.scalars(select(m.Workflow).where(m.Workflow.workspace_id == ws, m.Workflow.project_id == project.id,
                                            m.Workflow.name == DEMO_WORKFLOW)).first()
    if wf is None:
        wf = m.Workflow(workspace_id=ws, project_id=project.id, name=DEMO_WORKFLOW,
                        description="Kotlin · Spring Boot · Gradle", graph=demo_graph(), created_by=user.id)
        s.add(wf)
        audit(s, "demo.setup", user_id=user.id, workspace_id=ws, target=DEMO_WORKFLOW, ip=client_ip(request))
    s.commit()
    return {"project_id": project.id, "workflow_id": wf.id}


@router.get("/demo/training")
def demo_training(user: m.User = Depends(current_user)) -> dict:
    """«Источник проверки → Учебный проект»: the server-side path of the read-only training fixture (if it is inside
    ``APP_SCAN_ROOTS``), so the editor can point ``source.repo`` at it in ``path`` mode."""
    try:
        path = check_scan_path(str(TRAINING), get_settings().scan_root_paths())
    except RepoGuardError:
        return {"available": False, "path": None}
    return {"available": True, "path": str(path)}

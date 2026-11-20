from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.core.errors import ApiError, bad_request
from app.deps import current_user, get_session, load_scoped, resolve_workspace
from app.engine import runs as run_service
from app.engine.graph import Graph
from app.engine.scheduler import sync_schedules
from app.engine.validator import validate_graph
from app.nodes.base import get_registry

router = APIRouter(tags=["workflows"])
MAX_NODES = 200


class WorkflowIn(BaseModel):
    workspace_id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    graph: dict = Field(default_factory=lambda: {"schema_version": 1, "nodes": [], "edges": []})
    project_id: str | None = None


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    graph: dict | None = None
    project_id: str | None = None


class RunIn(BaseModel):
    project_id: str | None = None
    trigger_node_id: str | None = None
    source: dict | None = None


class ScheduleUpdate(BaseModel):
    enabled: bool


class GraphIn(BaseModel):
    workspace_id: str | None = None
    graph: dict


def parse_graph(raw: dict) -> Graph:
    try:
        g = Graph.model_validate(raw)
    except ValidationError as exc:
        raise ApiError(422, "invalid_graph_format", "граф не соответствует формату",
                       [{"loc": [str(x) for x in e["loc"]], "msg": e["msg"]} for e in exc.errors()]) from exc
    if len(g.nodes) > MAX_NODES:
        raise bad_request(f"слишком много нод (максимум {MAX_NODES})")
    return g


def credential_checker(s: Session, workspace_id: str):  # noqa: ANN201
    ids = set(s.scalars(select(m.Credential.id).where(m.Credential.workspace_id == workspace_id)))
    return lambda cid: cid in ids


def issues_for(s: Session, workspace_id: str, graph: Graph) -> list[dict]:
    return [i.model_dump() for i in validate_graph(graph, get_registry(), credential_checker(s, workspace_id))]


def check_project(s: Session, ws: str, project_id: str | None) -> None:
    if project_id:
        p = s.get(m.Project, project_id)
        if p is None or p.workspace_id != ws:
            raise bad_request("проект не найден в этом рабочем пространстве")


def wf_out(s: Session, w: m.Workflow, full: bool = True) -> dict:
    last = s.scalars(select(m.Run).where(m.Run.workflow_id == w.id).order_by(m.Run.created_at.desc()).limit(1)).first()
    d = {"id": w.id, "workspace_id": w.workspace_id, "name": w.name, "description": w.description,
         "project_id": w.project_id, "version": w.version, "forked_from": w.forked_from, "created_at": w.created_at,
         "updated_at": w.updated_at, "node_count": len((w.graph or {}).get("nodes", [])),
         "last_run": {"id": last.id, "status": last.status, "created_at": last.created_at} if last else None}
    if full:
        d["graph"] = w.graph
    return d


@router.get("/workflows")
def list_workflows(workspace_id: str | None = None, user: m.User = Depends(current_user),
                   s: Session = Depends(get_session)) -> list[dict]:
    ws = resolve_workspace(s, user, workspace_id)
    rows = s.scalars(select(m.Workflow).where(m.Workflow.workspace_id == ws).order_by(m.Workflow.updated_at.desc()))
    return [wf_out(s, w, full=False) for w in rows]


@router.post("/workflows", status_code=201)
def create_workflow(body: WorkflowIn, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, body.workspace_id, "developer")
    graph = parse_graph(body.graph)
    check_project(s, ws, body.project_id)
    w = m.Workflow(workspace_id=ws, name=body.name, description=body.description,
                   graph=graph.model_dump(mode="json"), project_id=body.project_id, created_by=user.id)
    s.add(w)
    s.flush()
    sync_schedules(s, w)
    s.commit()
    return wf_out(s, w)


@router.post("/workflows/validate")
def validate_draft(body: GraphIn, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, body.workspace_id)
    issues = issues_for(s, ws, parse_graph(body.graph))
    return {"valid": not issues, "issues": issues}


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    return wf_out(s, load_scoped(s, m.Workflow, workflow_id, user, what="сценарий"))


@router.put("/workflows/{workflow_id}")
def update_workflow(workflow_id: str, body: WorkflowUpdate, user: m.User = Depends(current_user),
                    s: Session = Depends(get_session)) -> dict:
    w = load_scoped(s, m.Workflow, workflow_id, user, "developer", "сценарий")
    if body.name is not None:
        w.name = body.name
    if body.description is not None:
        w.description = body.description
    if "project_id" in body.model_fields_set:
        check_project(s, w.workspace_id, body.project_id)
        w.project_id = body.project_id
    if body.graph is not None:
        w.graph = parse_graph(body.graph).model_dump(mode="json")
        w.version += 1
        sync_schedules(s, w)
    s.commit()
    return wf_out(s, w)


@router.delete("/workflows/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> Response:
    w = load_scoped(s, m.Workflow, workflow_id, user, "developer", "сценарий")
    s.delete(w)
    s.commit()
    return Response(status_code=204)


@router.post("/workflows/{workflow_id}/validate")
def validate_workflow(workflow_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    w = load_scoped(s, m.Workflow, workflow_id, user, what="сценарий")
    issues = issues_for(s, w.workspace_id, parse_graph(w.graph))
    return {"valid": not issues, "issues": issues}


def start_run(s: Session, w: m.Workflow, user_id: str | None, trigger_type: str, *, project_id: str | None = None,
              trigger_node_id: str | None = None, payload: dict | None = None) -> m.Run:
    graph = parse_graph(w.graph)
    issues = issues_for(s, w.workspace_id, graph)
    if issues:
        raise ApiError(422, "invalid_graph", "сценарий содержит ошибки — исправьте их перед запуском", issues)
    if trigger_node_id and not graph.node(trigger_node_id):
        raise bad_request("указанный триггер не найден в графе")
    check_project(s, w.workspace_id, project_id)
    return run_service.create_run(s, w, trigger_type=trigger_type, triggered_by=user_id,
                                  trigger_node_id=trigger_node_id, payload=payload or {}, project_id=project_id)


@router.post("/workflows/{workflow_id}/run", status_code=202)
def run_workflow(workflow_id: str, body: RunIn | None = None, user: m.User = Depends(current_user),
                 s: Session = Depends(get_session)) -> dict:
    w = load_scoped(s, m.Workflow, workflow_id, user, "developer", "сценарий")
    body = body or RunIn()
    payload = {"source": body.source} if body.source else {}
    run = start_run(s, w, user.id, "manual", project_id=body.project_id, trigger_node_id=body.trigger_node_id,
                    payload=payload)
    s.commit()
    return {"id": run.id, "status": run.status}


def schedules_out(s: Session, w: m.Workflow) -> dict:
    rows = s.scalars(select(m.Schedule).where(m.Schedule.workflow_id == w.id)).all()
    return {"schedules": [{"id": r.id, "node_id": r.node_id, "cron": r.cron, "timezone": r.timezone,
                           "enabled": r.enabled, "next_run_at": r.next_run_at} for r in rows]}


@router.get("/workflows/{workflow_id}/schedule")
def get_schedule(workflow_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    return schedules_out(s, load_scoped(s, m.Workflow, workflow_id, user, what="сценарий"))


@router.put("/workflows/{workflow_id}/schedule")
def put_schedule(workflow_id: str, body: ScheduleUpdate, user: m.User = Depends(current_user),
                 s: Session = Depends(get_session)) -> dict:
    w = load_scoped(s, m.Workflow, workflow_id, user, "developer", "сценарий")
    for r in s.scalars(select(m.Schedule).where(m.Schedule.workflow_id == w.id)):
        r.enabled = body.enabled
    s.commit()
    return schedules_out(s, w)

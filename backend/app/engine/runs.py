"""Run lifecycle: create (graph snapshot), queue claim (``FOR UPDATE SKIP LOCKED``), execute, finalize, cancel."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text, update

from app import models as m
from app.analyzers.common.finding import Finding
from app.config import get_settings
from app.core.masking import global_masker
from app.db import Database
from app.engine.context import RunInfo
from app.engine.data import summary_dict
from app.engine.events import DbEventSink, emit_event
from app.engine.executor import Executor
from app.engine.graph import Graph
from app.engine.services import DbRunServices
from app.nodes.base import get_registry

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 10.0

# Post-run hooks (e.g. Security Score service) — called with (db, run_id, findings) after every run.
POST_RUN_HOOKS: list[Callable[[Database, str, list[Finding]], Any]] = []


def create_run(s, workflow: m.Workflow, *, trigger_type: str = "manual", triggered_by: str | None = None,  # noqa: ANN001
               trigger_node_id: str | None = None, payload: dict[str, Any] | None = None,
               project_id: str | None = None, graph: dict | None = None) -> m.Run:
    run = m.Run(workspace_id=workflow.workspace_id, workflow_id=workflow.id,
                project_id=project_id or workflow.project_id, graph_snapshot=graph or workflow.graph,
                trigger_type=trigger_type, triggered_by=triggered_by, trigger_node_id=trigger_node_id,
                trigger_payload=payload or {}, status="queued")
    s.add(run)
    s.flush()
    emit_event(s, run.id, "run.status", {"status": "queued"})
    return run


def claim_next(db: Database, worker_id: str) -> str | None:
    """Atomically take the oldest queued run. PostgreSQL: row lock with SKIP LOCKED; SQLite: guarded UPDATE."""
    now = datetime.now(UTC)
    with db.session() as s:
        if db.engine.dialect.name == "postgresql":
            row = s.execute(text("SELECT id FROM runs WHERE status = 'queued' ORDER BY created_at "
                                 "FOR UPDATE SKIP LOCKED LIMIT 1")).first()
            if row is None:
                s.rollback()
                return None
            rid = row[0]
            s.execute(update(m.Run).where(m.Run.id == rid).values(status="running", worker_id=worker_id,
                                                                    heartbeat_at=now, started_at=now,
                                                                    attempts=m.Run.attempts + 1))
            s.commit()
            return rid
        for _ in range(5):
            rid = s.scalars(select(m.Run.id).where(m.Run.status == "queued").order_by(m.Run.created_at)
                            .limit(1)).first()
            if rid is None:
                return None
            res = s.execute(update(m.Run).where(m.Run.id == rid, m.Run.status == "queued")
                            .values(status="running", worker_id=worker_id, heartbeat_at=now, started_at=now,
                                    attempts=m.Run.attempts + 1))
            s.commit()
            if res.rowcount == 1:
                return rid
        return None


def request_cancel(s, run: m.Run) -> None:  # noqa: ANN001
    if run.status == "queued":
        run.status = "cancelled"
        run.finished_at = datetime.now(UTC)
        emit_event(s, run.id, "run.status", {"status": "cancelled"})
    elif run.status == "running":
        run.cancel_requested = True


def unique_findings(db: Database, run_id: str) -> list[Finding]:
    with db.session() as s:
        recs = s.scalars(select(m.FindingRecord).where(m.FindingRecord.run_id == run_id)
                         .order_by(m.FindingRecord.id)).all()
        out: dict[str, Finding] = {}
        for r in recs:
            out[r.finding_id] = Finding.model_validate(r.data)
        return list(out.values())


async def execute_run(db: Database, run_id: str, poll_interval: float = 0.5) -> str:
    settings = get_settings()
    with db.session() as s:
        run = s.get(m.Run, run_id)
        wf = s.get(m.Workflow, run.workflow_id) if run.workflow_id else None
        project = s.get(m.Project, run.project_id) if run.project_id else None
        user = s.get(m.User, run.triggered_by) if run.triggered_by else None
        info = RunInfo(run_id=run.id, workspace_id=run.workspace_id, workflow_id=run.workflow_id,
                       project_id=run.project_id, trigger_type=run.trigger_type, trigger_node_id=run.trigger_node_id,
                       trigger_payload=dict(run.trigger_payload or {}), source=dict(run.source or {}),
                       triggered_by=run.triggered_by, language=(user.locale if user else "ru") or "ru",
                       public_url=settings.public_url, project_name=project.name if project else "",
                       workflow_name=wf.name if wf else "")
        graph = Graph.model_validate(run.graph_snapshot)
        services = DbRunServices(db, run, global_masker.child())
    masker = services.masker
    sink = DbEventSink(db, run_id, masker, {n.id: n.type for n in graph.nodes})

    async def cancel_check() -> bool:
        with db.session() as s:
            return bool(s.scalar(select(m.Run.cancel_requested).where(m.Run.id == run_id)))

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            with db.session() as s:
                s.execute(update(m.Run).where(m.Run.id == run_id).values(heartbeat_at=datetime.now(UTC)))
                s.commit()

    executor = Executor(graph, get_registry(), info, sink, masker=masker, services=services,
                        node_timeout=settings.node_timeout_seconds, run_timeout=settings.run_timeout_seconds,
                        cancel_check=cancel_check, poll_interval=poll_interval)
    hb = asyncio.create_task(heartbeat())
    try:
        result = await executor.run()
        status, error = result.status, result.error
    except Exception as exc:  # engine bug must not kill the worker
        logger.exception("run %s crashed", run_id)
        status, error = "failed", f"внутренняя ошибка движка: {type(exc).__name__}: {exc}"
    finally:
        hb.cancel()
        services.cleanup()
    findings = unique_findings(db, run_id)
    with db.session() as s:
        run = s.get(m.Run, run_id)
        run.status = status
        run.error = masker.mask(error) if error else None
        run.finished_at = datetime.now(UTC)
        run.summary = summary_dict(findings)
        s.commit()
    for hook in POST_RUN_HOOKS:
        try:
            res = hook(db, run_id, findings)
            if inspect.isawaitable(res):
                await res
        except Exception:
            logger.exception("post-run hook %s failed for run %s", getattr(hook, "__name__", hook), run_id)
    return status


def _register_builtin_hooks() -> None:
    from app.ci.status import report_run_status

    if report_run_status not in POST_RUN_HOOKS:
        POST_RUN_HOOKS.append(report_run_status)


_register_builtin_hooks()

"""Cron scheduler: schedules live in the DB (survive restarts); each fired slot is a unique row, so several
workers never create duplicate runs for the same slot."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import models as m
from app.db import Database
from app.engine import runs as run_service
from app.nodes.triggers.schedule import ScheduleTrigger

logger = logging.getLogger(__name__)


def next_fire(cron: str, tz: str, after: datetime) -> datetime:
    zone = ZoneInfo(tz or "UTC")
    it = croniter(cron, after.astimezone(zone))
    return it.get_next(datetime).astimezone(UTC)


def sync_schedules(s, workflow: m.Workflow, now: datetime | None = None) -> list[m.Schedule]:  # noqa: ANN001
    """Make the schedules table match the workflow's ``trigger.schedule`` nodes."""
    now = now or datetime.now(UTC)
    ws = s.get(m.Workspace, workflow.workspace_id)
    wanted: dict[str, tuple[str, str]] = {}
    for node in (workflow.graph or {}).get("nodes", []):
        if node.get("type") != "trigger.schedule" or node.get("disabled"):
            continue
        cfg = node.get("config") or {}
        if ScheduleTrigger.validate_config(cfg):
            continue
        cron = ScheduleTrigger.cron_of(cfg)
        wanted[node["id"]] = (cron, cfg.get("timezone") or (ws.timezone if ws else "UTC"))
    existing = {sc.node_id: sc for sc in s.scalars(select(m.Schedule).where(m.Schedule.workflow_id == workflow.id))}
    for node_id, sc in existing.items():
        if node_id not in wanted:
            s.delete(sc)
    out = []
    for node_id, (cron, tz) in wanted.items():
        sc = existing.get(node_id)
        if sc is None:
            sc = m.Schedule(workflow_id=workflow.id, workspace_id=workflow.workspace_id, node_id=node_id)
            s.add(sc)
        if sc.cron != cron or sc.timezone != tz or sc.next_run_at is None:
            sc.cron, sc.timezone = cron, tz
            sc.next_run_at = next_fire(cron, tz, now)
        out.append(sc)
    s.flush()
    return out


def scheduler_tick(db: Database, now: datetime | None = None) -> list[str]:
    """Fire due schedules; returns created run ids. Missed slots during downtime fire once (the latest)."""
    now = now or datetime.now(UTC)
    created: list[str] = []
    with db.session() as s:
        due = s.scalars(select(m.Schedule).where(m.Schedule.enabled.is_(True), m.Schedule.next_run_at <= now)).all()
        due_ids = [(d.id, d.next_run_at) for d in due]
    for sched_id, slot in due_ids:
        with db.session() as s:
            sc = s.get(m.Schedule, sched_id)
            if sc is None:
                continue
            s.add(m.ScheduleSlot(schedule_id=sc.id, slot=slot))
            try:
                s.flush()
            except IntegrityError:
                s.rollback()
                sc = s.get(m.Schedule, sched_id)
                if sc is not None and sc.next_run_at is not None and sc.next_run_at <= now:
                    sc.next_run_at = next_fire(sc.cron, sc.timezone, now)
                    s.commit()
                continue
            wf = s.get(m.Workflow, sc.workflow_id)
            if wf is not None:
                run = run_service.create_run(s, wf, trigger_type="schedule", trigger_node_id=sc.node_id,
                                             payload={"slot": slot.isoformat(), "cron": sc.cron})
                slot_row = s.scalars(select(m.ScheduleSlot).where(m.ScheduleSlot.schedule_id == sc.id,
                                                                  m.ScheduleSlot.slot == slot)).one()
                slot_row.run_id = run.id
                created.append(run.id)
            sc.next_run_at = next_fire(sc.cron, sc.timezone, now)
            s.commit()
    return created

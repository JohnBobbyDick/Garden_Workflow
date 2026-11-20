import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import models as m
from app.db import Database
from app.engine import runs as run_service
from app.engine.scheduler import scheduler_tick, sync_schedules
from app.engine.worker import Worker
from app.nodes.base import get_registry
from tests.engine.helpers import TNumber
from tests.nodes.conftest import TRAINING


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{(tmp_path / 'w.db').as_posix()}")
    d.create_all()
    return d


def full_graph(path=str(TRAINING)):
    nodes = [
        ("t", "trigger.manual", {}), ("src", "source.repo", {"mode": "path", "path": path}),
        ("sec", "scanner.secrets", {}), ("sca", "scanner.sca", {}), ("sast", "scanner.sast", {}),
        ("merge", "logic.merge", {}), ("if", "logic.if_else", {"expression": "severity.max >= HIGH"}),
        ("exp", "output.report_export", {}), ("gate", "output.ci_gate", {}),
    ]
    edges = [("t", "out", "src", "in"), ("src", "out", "sec", "in"), ("src", "out", "sca", "in"),
             ("src", "out", "sast", "in"), ("sec", "out", "merge", "in"), ("sca", "out", "merge", "in"),
             ("sast", "out", "merge", "in"), ("merge", "out", "if", "in"), ("if", "true", "exp", "in"),
             ("merge", "out", "gate", "in")]
    return {"schema_version": 1,
            "nodes": [{"id": i, "type": t, "position": {"x": 0, "y": 0}, "config": c} for i, t, c in nodes],
            "edges": [{"id": f"e{k}", "source": s, "source_port": sp, "target": tt, "target_port": tp}
                      for k, (s, sp, tt, tp) in enumerate(edges)]}


def seed(db, graph):
    with db.session() as s:
        ws = m.Workspace(name="W", timezone="UTC")
        s.add(ws)
        s.flush()
        wf = m.Workflow(workspace_id=ws.id, name="audit", graph=graph)
        s.add(wf)
        s.commit()
        return ws.id, wf.id


def test_full_run_through_queue(db):
    ws, wf = seed(db, full_graph())
    with db.session() as s:
        run = run_service.create_run(s, s.get(m.Workflow, wf), trigger_type="manual")
        s.commit()
        rid = run.id
    worker = Worker(db, "w1")
    assert asyncio.run(worker.run_once()) == rid
    with db.session() as s:
        run = s.get(m.Run, rid)
        assert run.status == "success", run.error
        assert run.summary["total"] == 15
        assert run.gate in ("pass", "fail")
        node_runs = {n.node_id: n.status for n in s.scalars(select(m.NodeRun).where(m.NodeRun.run_id == rid))}
        assert node_runs["exp"] == "success" and all(v == "success" for v in node_runs.values())
        names = {a.name for a in s.scalars(select(m.Artifact).where(m.Artifact.run_id == rid))}
        assert {"submission.json", "report.md", "report.html"} <= names
        events = s.scalars(select(m.RunEvent).where(m.RunEvent.run_id == rid).order_by(m.RunEvent.id)).all()
        assert events[0].type == "run.status" and events[0].data["status"] == "queued"
        assert events[-1].type == "run.status" and events[-1].data["status"] == "success"
        ids = [e.id for e in events]
        assert ids == sorted(ids)
        recs = s.scalars(select(m.FindingRecord).where(m.FindingRecord.run_id == rid)).all()
        assert len({r.finding_id for r in recs}) == 15 and {r.node_id for r in recs} == {"sec", "sca", "sast"}


def test_two_workers_never_claim_the_same_run(db):
    ws, wf = seed(db, full_graph())
    with db.session() as s:
        wfo = s.get(m.Workflow, wf)
        r1 = run_service.create_run(s, wfo, trigger_type="manual")
        r2 = run_service.create_run(s, wfo, trigger_type="manual")
        s.commit()
    a = run_service.claim_next(db, "A")
    b = run_service.claim_next(db, "B")
    c = run_service.claim_next(db, "C")
    assert {a, b} == {r1.id, r2.id} and c is None


def test_graph_snapshot_is_kept_after_workflow_edit(db):
    ws, wf = seed(db, full_graph())
    with db.session() as s:
        run = run_service.create_run(s, s.get(m.Workflow, wf), trigger_type="manual")
        s.get(m.Workflow, wf).graph = {"schema_version": 1, "nodes": [], "edges": []}
        s.commit()
        assert len(s.get(m.Run, run.id).graph_snapshot["nodes"]) == 9


def test_cancel_running_run(db):
    reg = get_registry()
    reg.register(TNumber)
    try:
        g = {"schema_version": 1, "nodes": [
            {"id": "t", "type": "trigger.manual", "config": {}},
            {"id": "slow", "type": "t.number", "config": {"value": 1, "sleep": 5}}],
             "edges": [{"id": "e", "source": "t", "source_port": "out", "target": "slow", "target_port": "in"}]}
        ws, wf = seed(db, g)
        with db.session() as s:
            run = run_service.create_run(s, s.get(m.Workflow, wf), trigger_type="manual")
            s.commit()

        async def main():
            w = Worker(db, "w1", poll_interval=0.05)
            task = asyncio.create_task(w.run_once())
            await asyncio.sleep(0.4)
            with db.session() as s:
                run_service.request_cancel(s, s.get(m.Run, run.id))
                s.commit()
            await task

        asyncio.run(main())
        with db.session() as s:
            assert s.get(m.Run, run.id).status == "cancelled"
    finally:
        reg.unregister("t.number")


def test_failed_run_records_masked_error(db):
    g = full_graph(path="/definitely/not/allowed")
    ws, wf = seed(db, g)
    with db.session() as s:
        run = run_service.create_run(s, s.get(m.Workflow, wf), trigger_type="manual")
        s.commit()
    asyncio.run(Worker(db, "w").run_once())
    with db.session() as s:
        r = s.get(m.Run, run.id)
        assert r.status == "failed"
        nr = s.scalars(select(m.NodeRun).where(m.NodeRun.run_id == run.id, m.NodeRun.node_id == "src")).one()
        assert nr.status == "failed" and "APP_SCAN_ROOTS" in nr.error
        sec = s.scalars(select(m.NodeRun).where(m.NodeRun.run_id == run.id, m.NodeRun.node_id == "sec")).one()
        assert sec.status == "skipped"


def sched_graph(cron="0 14 * * *"):
    g = full_graph()
    g["nodes"][0] = {"id": "t", "type": "trigger.schedule", "config": {"cron": cron}}
    return g


def test_scheduler_creates_one_run_per_slot_even_with_two_workers(db):
    ws, wf = seed(db, sched_graph())
    with db.session() as s:
        sync_schedules(s, s.get(m.Workflow, wf), now=datetime(2026, 1, 1, 13, 0, tzinfo=UTC))
        s.commit()
        sch = s.scalars(select(m.Schedule)).one()
        assert sch.next_run_at == datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
    now = datetime(2026, 1, 1, 14, 0, 5, tzinfo=UTC)
    created_a = scheduler_tick(db, now)
    # second worker sees a stale next_run_at (simulated by resetting it) and must not duplicate the slot
    with db.session() as s:
        s.scalars(select(m.Schedule)).one().next_run_at = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
        s.commit()
    created_b = scheduler_tick(db, now)
    assert len(created_a) == 1 and created_b == []
    with db.session() as s:
        runs = s.scalars(select(m.Run)).all()
        assert len(runs) == 1 and runs[0].trigger_type == "schedule" and runs[0].trigger_node_id == "t"
        assert s.scalars(select(m.Schedule)).one().next_run_at == datetime(2026, 1, 2, 14, 0, tzinfo=UTC)


def test_schedule_respects_timezone(db):
    g = sched_graph()
    g["nodes"][0]["config"] = {"daily_at": "14:00", "timezone": "Europe/Moscow"}
    ws, wf = seed(db, g)
    with db.session() as s:
        sync_schedules(s, s.get(m.Workflow, wf), now=datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
        s.commit()
        assert s.scalars(select(m.Schedule)).one().next_run_at == datetime(2026, 1, 1, 11, 0, tzinfo=UTC)


def test_schedule_removed_with_trigger(db):
    ws, wf = seed(db, sched_graph())
    with db.session() as s:
        wfo = s.get(m.Workflow, wf)
        sync_schedules(s, wfo)
        wfo.graph = full_graph()
        sync_schedules(s, wfo)
        s.commit()
        assert s.scalars(select(m.Schedule)).all() == []


def test_stale_running_run_is_recovered_after_restart(db):
    ws, wf = seed(db, full_graph())
    with db.session() as s:
        run = run_service.create_run(s, s.get(m.Workflow, wf), trigger_type="manual")
        s.commit()
    assert run_service.claim_next(db, "dead-worker") == run.id
    with db.session() as s:
        s.get(m.Run, run.id).heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        s.commit()
    w = Worker(db, "new")
    assert w.recover_stale(stale_after=60) == [run.id]
    asyncio.run(w.run_once())
    with db.session() as s:
        r = s.get(m.Run, run.id)
        assert r.status == "success" and r.attempts == 2

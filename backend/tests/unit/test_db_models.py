import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import models as m
from app.db import Database


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    d.create_all()
    return d


def test_all_tables_from_spec_exist(db):
    names = set(m.Base.metadata.tables)
    for t in ("users", "workspaces", "memberships", "projects", "workflows", "runs", "run_events", "node_runs",
              "findings", "ai_reports", "templates", "template_reviews", "credentials", "api_tokens",
              "webhook_deliveries", "autofixes", "repo_allowlist", "schedules", "schedule_slots", "audit_log",
              "artifacts", "refresh_tokens"):
        assert t in names, t


def test_run_with_events_and_findings_roundtrip(db):
    with db.session() as s:
        u = m.User(email="a@example.org", password_hash="x")
        ws = m.Workspace(name="W")
        s.add_all([u, ws])
        s.flush()
        wf = m.Workflow(workspace_id=ws.id, name="wf", graph={"schema_version": 1, "nodes": [], "edges": []})
        s.add(wf)
        s.flush()
        run = m.Run(workspace_id=ws.id, workflow_id=wf.id, graph_snapshot=wf.graph, trigger_type="manual")
        s.add(run)
        s.flush()
        s.add(m.RunEvent(run_id=run.id, type="run.status", data={"status": "queued"}))
        s.add(m.FindingRecord(run_id=run.id, node_id="n3", finding_id="f_1", category="SAST", cls="sql-injection",
                              severity="HIGH", confidence=0.9, path="a.kt", line=3, data={"x": 1}))
        s.commit()
        rid = run.id
    with db.session() as s:
        run = s.get(m.Run, rid)
        assert run.status == "queued"
        assert run.created_at is not None
        events = s.scalars(select(m.RunEvent).where(m.RunEvent.run_id == rid)).all()
        assert events[0].id >= 1 and events[0].data == {"status": "queued"}


def test_membership_is_unique_per_user_and_workspace(db):
    with db.session() as s:
        u = m.User(email="b@example.org", password_hash="x")
        ws = m.Workspace(name="W")
        s.add_all([u, ws])
        s.flush()
        s.add(m.Membership(workspace_id=ws.id, user_id=u.id, role="admin"))
        s.commit()
        s.add(m.Membership(workspace_id=ws.id, user_id=u.id, role="viewer"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_schedule_slot_is_unique(db):
    from datetime import UTC, datetime

    with db.session() as s:
        ws = m.Workspace(name="W")
        s.add(ws)
        s.flush()
        wf = m.Workflow(workspace_id=ws.id, name="wf", graph={})
        s.add(wf)
        s.flush()
        sch = m.Schedule(workflow_id=wf.id, workspace_id=ws.id, node_id="t", cron="0 14 * * *", timezone="UTC")
        s.add(sch)
        s.flush()
        slot = datetime(2026, 1, 1, 14, tzinfo=UTC)
        s.add(m.ScheduleSlot(schedule_id=sch.id, slot=slot))
        s.commit()
        s.add(m.ScheduleSlot(schedule_id=sch.id, slot=slot))
        with pytest.raises(IntegrityError):
            s.commit()

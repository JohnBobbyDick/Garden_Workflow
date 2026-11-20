import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text

from app import models as m
from app.config import BACKEND_DIR
from app.db import Database
from app.engine import runs as run_service
from app.engine.worker import Worker


def alembic_cfg(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_alembic_upgrade_matches_models_on_sqlite(tmp_path):
    url = f"sqlite:///{(tmp_path / 'mig.db').as_posix()}"
    command.upgrade(alembic_cfg(url), "head")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert set(m.Base.metadata.tables) <= tables
    command.check(alembic_cfg(url))  # raises if models and migrations diverge


PG_URL = os.environ.get("APP_TEST_DATABASE_URL", "")


def test_alembic_upgrade_creates_missing_sqlite_directory(tmp_path):
    """Fresh checkout: ``backend/data`` does not exist yet when ``alembic upgrade head`` runs first."""
    db_file = tmp_path / "not-created-yet" / "nested" / "aisw.db"
    command.upgrade(alembic_cfg(f"sqlite:///{db_file.as_posix()}"), "head")
    assert db_file.exists()


@pytest.mark.postgres
@pytest.mark.skipif(not PG_URL.startswith("postgresql"), reason="APP_TEST_DATABASE_URL (PostgreSQL) not set")
def test_postgres_migrations_queue_and_full_run():
    from tests.engine.test_worker_scheduler import full_graph

    eng = create_engine(PG_URL)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_cfg(PG_URL), "head")
    command.check(alembic_cfg(PG_URL))
    db = Database(PG_URL)
    with db.session() as s:
        ws = m.Workspace(name="pg", timezone="UTC")
        s.add(ws)
        s.flush()
        wf = m.Workflow(workspace_id=ws.id, name="pg", graph=full_graph())
        s.add(wf)
        s.flush()
        r1 = run_service.create_run(s, wf, trigger_type="manual")
        r2 = run_service.create_run(s, wf, trigger_type="manual")
        s.commit()
    # FOR UPDATE SKIP LOCKED: two claims → two distinct runs, third → none
    a, b, c = (run_service.claim_next(db, w) for w in ("A", "B", "C"))
    assert {a, b} == {r1.id, r2.id} and c is None
    with db.session() as s:
        for rid in (r1.id, r2.id):
            s.get(m.Run, rid).status = "queued"
        s.commit()
    w = Worker(db, "pg-worker")
    assert asyncio.run(w.run_once()) is not None
    with db.session() as s:
        done = s.scalars(select(m.Run).where(m.Run.status == "success")).all()
        assert len(done) == 1 and done[0].summary["total"] == 15
        assert s.scalar(select(m.RunEvent.id).order_by(m.RunEvent.id.desc()).limit(1)) > 0

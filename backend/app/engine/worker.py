"""Worker process: recovers stale runs, fires schedules, claims queued runs from the DB table and executes them.

Run as ``python -m app.engine.worker`` (a separate Compose service); in dev it can run inside the API process
(``APP_INPROCESS_WORKER=true``)."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import models as m
from app.db import Database, get_db
from app.engine import runs as run_service
from app.engine.events import emit_event
from app.engine.scheduler import scheduler_tick

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 2


class Worker:
    def __init__(self, db: Database, worker_id: str, poll_interval: float = 1.0, concurrency: int = 2) -> None:
        self.db = db
        self.worker_id = worker_id
        self.poll_interval = poll_interval
        self.concurrency = concurrency
        self._tasks: set[asyncio.Task] = set()

    async def run_once(self) -> str | None:
        rid = run_service.claim_next(self.db, self.worker_id)
        if rid is None:
            return None
        await run_service.execute_run(self.db, rid, poll_interval=min(self.poll_interval, 0.5))
        return rid

    def recover_stale(self, stale_after: float = 120.0) -> list[str]:
        """Runs whose worker died (no heartbeat) are re-queued once, then failed."""
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_after)
        recovered: list[str] = []
        with self.db.session() as s:
            stale = s.scalars(select(m.Run).where(m.Run.status == "running", m.Run.heartbeat_at < cutoff)).all()
            for run in stale:
                if run.attempts >= MAX_ATTEMPTS:
                    run.status, run.error, run.finished_at = "failed", "воркер остановился во время запуска", \
                        datetime.now(UTC)
                    emit_event(s, run.id, "run.status", {"status": "failed", "error": run.error})
                    continue
                for model in (m.NodeRun, m.FindingRecord, m.Artifact):
                    for row in s.scalars(select(model).where(model.run_id == run.id)):
                        s.delete(row)
                run.status, run.worker_id, run.notifications = "queued", None, []
                emit_event(s, run.id, "run.requeued", {"reason": "воркер перезапущен, запуск поставлен в очередь"})
                emit_event(s, run.id, "run.status", {"status": "queued"})
                recovered.append(run.id)
            s.commit()
        return recovered

    async def serve(self, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        logger.info("worker %s started", self.worker_id)
        last_recover = 0.0
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            try:
                if loop.time() - last_recover > 30:
                    self.recover_stale()
                    last_recover = loop.time()
                scheduler_tick(self.db)
                while len(self._tasks) < self.concurrency:
                    rid = run_service.claim_next(self.db, self.worker_id)
                    if rid is None:
                        break
                    task = asyncio.create_task(run_service.execute_run(self.db, rid))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
            except Exception:
                logger.exception("worker loop error")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.poll_interval)
            except TimeoutError:
                pass
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


def main() -> None:
    from app.config import get_settings

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from app.core.masking import MaskingLogFilter

    for h in logging.getLogger().handlers:
        h.addFilter(MaskingLogFilter())
    from app.engine.services import preload_credentials

    preload_credentials(get_db())
    worker = Worker(get_db(), f"{socket.gethostname()}-{os.getpid()}", get_settings().worker_poll_seconds)
    asyncio.run(worker.serve())


if __name__ == "__main__":
    main()

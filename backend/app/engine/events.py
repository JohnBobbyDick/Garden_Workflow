"""Persistent run events (``run_events``) + node run status rows; source of the SSE stream."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app import models as m
from app.core.masking import Masker
from app.db import Database


class DbEventSink:
    def __init__(self, db: Database, run_id: str, masker: Masker, graph_nodes: dict[str, str]) -> None:
        self.db = db
        self.run_id = run_id
        self.masker = masker
        self.node_types = graph_nodes
        self._lock = threading.Lock()

    def emit(self, type_: str, node_id: str | None, data: dict[str, Any]) -> None:
        data = self.masker.mask_obj(data)
        with self._lock, self.db.session() as s:
            s.add(m.RunEvent(run_id=self.run_id, type=type_, node_id=node_id, data=data))
            if type_ == "node.status" and node_id:
                self._node_run(s, node_id, data)
            if type_ == "run.status":
                run = s.get(m.Run, self.run_id)
                if run is not None:
                    run.heartbeat_at = datetime.now(UTC)
            s.commit()

    def _node_run(self, s, node_id: str, data: dict[str, Any]) -> None:  # noqa: ANN001
        nr = s.scalars(select(m.NodeRun).where(m.NodeRun.run_id == self.run_id, m.NodeRun.node_id == node_id)).first()
        if nr is None:
            nr = m.NodeRun(run_id=self.run_id, node_id=node_id, node_type=self.node_types.get(node_id, ""))
            s.add(nr)
        status = data.get("status", nr.status)
        nr.status = status
        now = datetime.now(UTC)
        if status == "running":
            nr.started_at = now
        if status in ("success", "failed", "skipped", "cancelled"):
            nr.finished_at = now
            nr.duration_ms = data.get("duration_ms")
        if data.get("error"):
            nr.error = data["error"]
        summary = {k: data[k] for k in ("summary", "reason", "ports") if k in data}
        if summary:
            nr.output_summary = summary
        run = s.get(m.Run, self.run_id)
        if run is not None:
            run.heartbeat_at = now


def emit_event(s, run_id: str, type_: str, data: dict[str, Any], node_id: str | None = None) -> None:  # noqa: ANN001
    s.add(m.RunEvent(run_id=run_id, type=type_, node_id=node_id, data=data))

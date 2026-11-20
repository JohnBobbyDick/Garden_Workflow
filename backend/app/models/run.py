"""Runs, node runs, events, findings, artifacts, AI reports, autofixes, CI webhook deliveries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin, UTCDateTime, utcnow

RUN_STATUSES = ("queued", "running", "success", "failed", "cancelled")
NODE_STATUSES = ("pending", "running", "success", "failed", "skipped", "cancelled")


class Run(IdMixin, CreatedMixin, Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_status_created", "status", "created_at"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    workflow_id: Mapped[str | None] = mapped_column(ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True,
                                                    index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True,
                                                   index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    graph_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    trigger_type: Mapped[str] = mapped_column(String(16), default="manual")  # manual|schedule|ci|webhook
    trigger_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    trigger_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[dict] = mapped_column(JSON, default=dict)  # mode, ref, commit, url/path/upload
    upload_id: Mapped[str | None] = mapped_column(ForeignKey("uploads.id", ondelete="SET NULL"), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)  # findings_by_severity/category, counts
    gate: Mapped[str | None] = mapped_column(String(8), nullable=True)  # pass | fail
    verdict: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notifications: Mapped[list] = mapped_column(JSON, default=list)
    # Security Score (12A.2)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    loc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_formula_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    scanner_set_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)


class NodeRun(IdMixin, Base):
    __tablename__ = "node_runs"
    __table_args__ = (UniqueConstraint("run_id", "node_id"),)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(String(64))
    node_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[dict] = mapped_column(JSON, default=dict)


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class FindingRecord(Base):
    __tablename__ = "findings"
    __table_args__ = (Index("ix_findings_run", "run_id", "finding_id"),)
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finding_id: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(8))
    cls: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(8))
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    path: Mapped[str] = mapped_column(String(1000))
    line: Mapped[int] = mapped_column(Integer, default=1)
    diff_status: Mapped[str | None] = mapped_column(String(8), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Artifact(IdMixin, CreatedMixin, Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("run_id", "name"),)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    content: Mapped[bytes] = mapped_column(LargeBinary)
    size: Mapped[int] = mapped_column(Integer, default=0)


class AIReport(IdMixin, CreatedMixin, Base):
    __tablename__ = "ai_reports"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="report")  # report | sprint_plan
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="ru")
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=True)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)


class Autofix(IdMixin, CreatedMixin, Base):
    __tablename__ = "autofixes"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    finding_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16), default="llm")  # llm | deterministic
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # validated | rejected | error
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    patch: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal: Mapped[dict] = mapped_column(JSON, default=dict)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    pr_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class WebhookDelivery(IdMixin, CreatedMixin, Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (UniqueConstraint("provider", "delivery_id"),)
    provider: Mapped[str] = mapped_column(String(16))
    delivery_id: Mapped[str] = mapped_column(String(200))
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True)
    event: Mapped[str] = mapped_column(String(64), default="")
    run_ids: Mapped[list] = mapped_column(JSON, default=list)


class CiStatusReport(IdMixin, CreatedMixin, Base):
    """Status/comment pushed back to a CI provider for a run (audit trail of outbound CI writes)."""

    __tablename__ = "ci_status_reports"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))  # status | comment
    state: Mapped[str] = mapped_column(String(16), default="")
    target: Mapped[str] = mapped_column(String(500), default="")
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

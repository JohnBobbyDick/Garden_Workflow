"""Projects, uploads, workflows, schedules, chat history."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin, UTCDateTime, utcnow


class Project(IdMixin, CreatedMixin, Base):
    __tablename__ = "projects"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    source_mode: Mapped[str] = mapped_column(String(16), default="upload")  # upload | git_url | path
    git_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    subdir: Mapped[str | None] = mapped_column(String(500), nullable=True)
    upload_id: Mapped[str | None] = mapped_column(ForeignKey("uploads.id", ondelete="SET NULL"), nullable=True)


class Upload(IdMixin, CreatedMixin, Base):
    __tablename__ = "uploads"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(String(1000))
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    encrypted: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class Workflow(IdMixin, CreatedMixin, Base):
    __tablename__ = "workflows"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    graph: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    forked_from: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Schedule(IdMixin, CreatedMixin, Base):
    __tablename__ = "schedules"
    __table_args__ = (UniqueConstraint("workflow_id", "node_id"),)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(String(64))
    cron: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)


class ScheduleSlot(IdMixin, CreatedMixin, Base):
    """One row per fired cron slot; the unique key prevents duplicate runs from several workers."""

    __tablename__ = "schedule_slots"
    __table_args__ = (UniqueConstraint("schedule_id", "slot"),)
    schedule_id: Mapped[str] = mapped_column(ForeignKey("schedules.id", ondelete="CASCADE"), index=True)
    slot: Mapped[datetime] = mapped_column(UTCDateTime)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WorkflowChatMessage(IdMixin, CreatedMixin, Base):
    __tablename__ = "workflow_chat_messages"
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    operations: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="proposed")  # proposed | applied | rejected | failed
    base_version: Mapped[int | None] = mapped_column(nullable=True)
    result_graph: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    user_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_chat_messages.id", ondelete="SET NULL", name="fk_chat_request"), nullable=True)
    proposal_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class CustomNode(IdMixin, Base):
    __tablename__ = "custom_nodes"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    fields: Mapped[dict] = mapped_column(JSON)

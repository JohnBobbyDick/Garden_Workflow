"""Public workflow template library: templates, ratings, reviews, favorites."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin, UTCDateTime, utcnow

TEMPLATE_CATEGORIES = ("Secrets", "SAST", "SCA", "Full Security Audit", "CI/CD", "Notifications", "Custom")


class Template(IdMixin, CreatedMixin, Base):
    __tablename__ = "templates"
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="Custom")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    author_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_name: Mapped[str] = mapped_column(String(200), default="")
    source_workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"),
                                                            nullable=True)
    graph: Mapped[dict] = mapped_column(JSON, default=dict)
    parameters: Mapped[list] = mapped_column(JSON, default=list)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    rating_avg: Mapped[float] = mapped_column(Float, default=0.0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    published: Mapped[bool] = mapped_column(Boolean, default=True)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class TemplateRating(IdMixin, CreatedMixin, Base):
    __tablename__ = "template_ratings"
    __table_args__ = (UniqueConstraint("template_id", "user_id"),)
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    stars: Mapped[int] = mapped_column(Integer)


class TemplateReview(IdMixin, CreatedMixin, Base):
    __tablename__ = "template_reviews"
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class TemplateFavorite(IdMixin, CreatedMixin, Base):
    __tablename__ = "template_favorites"
    __table_args__ = (UniqueConstraint("template_id", "user_id"),)
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

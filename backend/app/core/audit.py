"""Audit trail of security-relevant actions (login, credentials, allowlist, templates, API tokens, PRs)."""

from __future__ import annotations

from typing import Any

from app import models as m
from app.core.masking import global_masker


def audit(s, action: str, *, user_id: str | None = None, workspace_id: str | None = None,  # noqa: ANN001
          target: str = "", details: dict[str, Any] | None = None, ip: str | None = None) -> None:
    s.add(m.AuditLog(action=action, user_id=user_id, workspace_id=workspace_id, target=target[:300],
                     details=global_masker.mask_obj(details or {}), ip=ip))

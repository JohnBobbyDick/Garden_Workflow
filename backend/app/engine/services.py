"""DB-backed platform services for nodes (credentials, workdir, artifacts, findings, run fields, sources)."""

from __future__ import annotations

import shutil
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app import models as m
from app.analyzers.common.finding import Finding
from app.config import get_settings
from app.core.crypto import get_box
from app.core.masking import Masker
from app.db import Database
from app.engine.data import finding_dict

RUN_FIELDS = {"source", "gate", "verdict", "summary", "score", "score_delta", "score_details", "loc",
              "score_formula_version", "scanner_set_signature"}


class CredentialNotFound(LookupError):
    pass


def allowlist_for(s, workspace_id: str) -> list[str]:  # noqa: ANN001
    urls = [u.strip() for u in get_settings().default_allowlist.split(",") if u.strip()]
    urls += [r.url for r in s.scalars(select(m.RepoAllowlist).where(m.RepoAllowlist.workspace_id == workspace_id))]
    return urls


def read_upload(upload: m.Upload) -> bytes:
    data = Path(upload.stored_path).read_bytes()
    return get_box().decrypt_bytes(data) if upload.encrypted else data


class DbRunServices:
    def __init__(self, db: Database, run: m.Run, masker: Masker) -> None:
        self.db = db
        self.run_id = run.id
        self.workspace_id = run.workspace_id
        self.project_id = run.project_id
        self.masker = masker
        self._workdir: Path | None = None
        self._lock = threading.Lock()

    def get_credential(self, credential_id: str) -> str:
        with self.db.session() as s:
            cred = s.get(m.Credential, credential_id)
            if cred is None or cred.workspace_id != self.workspace_id:
                raise CredentialNotFound("секрет не найден в хранилище рабочего пространства")
            value = get_box().decrypt(cred.ciphertext)
        self.masker.register(value)
        return value

    def workdir(self) -> Path:
        if self._workdir is None:
            base = get_settings().data_dir / "work"
            base.mkdir(parents=True, exist_ok=True)
            self._workdir = Path(tempfile.mkdtemp(prefix=f"run-{self.run_id[:8]}-", dir=base))
        return self._workdir

    def cleanup(self) -> None:
        if self._workdir is not None:
            shutil.rmtree(self._workdir, ignore_errors=True)
            self._workdir = None

    def save_artifact(self, node_id: str, name: str, content: bytes, content_type: str) -> str:
        with self._lock, self.db.session() as s:
            art = s.scalars(select(m.Artifact).where(m.Artifact.run_id == self.run_id, m.Artifact.name == name)).first()
            if art is None:
                art = m.Artifact(run_id=self.run_id, name=name)
                s.add(art)
            art.node_id, art.content, art.content_type, art.size = node_id, content, content_type, len(content)
            s.commit()
        return f"/api/runs/{self.run_id}/artifacts/{name}"

    def record_findings(self, node_id: str, findings: list[Finding]) -> None:
        with self._lock, self.db.session() as s:
            for f in findings:
                s.add(m.FindingRecord(run_id=self.run_id, node_id=node_id, finding_id=f.id, category=f.category,
                                      cls=f.cls, severity=f.severity, confidence=f.confidence, path=f.path,
                                      line=f.line, diff_status=f.diff_status,
                                      data=self.masker.mask_obj(finding_dict(f))))
            s.commit()

    def update_run(self, **fields: Any) -> None:
        bad = set(fields) - RUN_FIELDS
        if bad:
            raise ValueError(f"cannot update run fields {sorted(bad)}")
        with self._lock, self.db.session() as s:
            run = s.get(m.Run, self.run_id)
            for k, v in fields.items():
                setattr(run, k, self.masker.mask_obj(v) if isinstance(v, (dict, list, str)) else v)
            s.commit()

    def add_notification(self, node_id: str, channel: str, status: str, detail: str = "") -> None:
        with self._lock, self.db.session() as s:
            run = s.get(m.Run, self.run_id)
            run.notifications = [*(run.notifications or []), {
                "node_id": node_id, "channel": channel, "status": status, "detail": self.masker.mask(detail),
                "at": datetime.now(UTC).isoformat()}]
            s.commit()

    def allowlist(self) -> list[str]:
        with self.db.session() as s:
            return allowlist_for(s, self.workspace_id)

    def open_upload(self, upload_id: str) -> tuple[str, bytes]:
        with self.db.session() as s:
            up = s.get(m.Upload, upload_id)
            if up is None or up.workspace_id != self.workspace_id:
                raise LookupError("загруженный архив не найден")
            return up.filename, read_upload(up)

    def project_source(self) -> dict[str, Any] | None:
        if not self.project_id:
            return None
        with self.db.session() as s:
            p = s.get(m.Project, self.project_id)
            if p is None or p.workspace_id != self.workspace_id:
                return None
            return {"mode": p.source_mode, "git_url": p.git_url, "ref": p.ref, "path": p.path,
                    "upload_id": p.upload_id, "subdir": p.subdir}

    def ai_provider_config(self, override: dict[str, Any] | None = None):  # noqa: ANN201
        from app.ai.settings_service import provider_config_for

        with self.db.session() as s:
            return provider_config_for(s, self.workspace_id, override, self.masker)

    def save_ai_report(self, node_id: str, kind: str, outcome) -> str:  # noqa: ANN001
        with self._lock, self.db.session() as s:
            row = m.AIReport(run_id=self.run_id, node_id=node_id, kind=kind, provider=outcome.provider,
                             model=outcome.model, language=outcome.language, ai_generated=outcome.ai_generated,
                             report=self.masker.mask_obj(outcome.report),
                             validation={**self.masker.mask_obj(outcome.validation),
                                         "error": self.masker.mask(outcome.error) if outcome.error else None},
                             metrics=(outcome.validation or {}).get("metrics", {}), usage=outcome.usage or {})
            s.add(row)
            s.commit()
            return row.id

    def workspace_settings(self) -> dict[str, Any]:
        with self.db.session() as s:
            ws = s.get(m.Workspace, self.workspace_id)
            return dict(ws.settings or {}) if ws else {}


def preload_credentials(db: Database, masker: Masker | None = None) -> int:
    """Register every stored credential value with the masker (after a restart nothing is known otherwise).

    Values are decrypted only into the masker's in-memory set; undecryptable rows (rotated-away key) are skipped."""
    from app.core.crypto import CryptoError
    from app.core.masking import global_masker

    target = masker or global_masker
    n = 0
    with db.session() as s:
        for c in s.scalars(select(m.Credential)):
            try:
                target.register(get_box().decrypt(c.ciphertext))
                n += 1
            except CryptoError:
                continue
    return n


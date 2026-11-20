"""Re-materialize the exact sources of a run for AutoFix (12A.3 §5): working copies are deleted after a run, so the
code is fetched again — a directory inside APP_SCAN_ROOTS (copied, never modified in place), the encrypted uploaded
archive (until its TTL, APP_UPLOAD_RETENTION_HOURS) or the allowlisted git repository at the exact commit of the run.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app import models as m
from app.config import get_settings
from app.core.crypto import get_box
from app.core.repo_guard import ExtractLimits, check_scan_path, clone_repo, safe_extract
from app.engine.services import allowlist_for, read_upload


class SourceUnavailable(Exception):
    pass


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def upload_expired(up: m.Upload) -> bool:
    exp = _aware(up.expires_at)
    return not up.stored_path or (exp is not None and exp < datetime.now(UTC))


def purge_expired_uploads(s) -> int:  # noqa: ANN001
    """Delete encrypted archives past their TTL (the row stays so that AutoFix can say why the code is gone)."""
    n = 0
    for up in s.scalars(select(m.Upload).where(m.Upload.expires_at.is_not(None), m.Upload.stored_path != "")):
        if upload_expired(up):
            Path(up.stored_path).unlink(missing_ok=True)
            up.stored_path = ""
            n += 1
    if n:
        s.commit()
    return n


def _subdir(root: Path, sub: str | None) -> Path:
    if not sub:
        return root
    p = (root / sub).resolve()
    if not p.is_relative_to(root.resolve()) or not p.is_dir():
        raise SourceUnavailable("подкаталог проекта не найден в восстановленных исходниках")
    return p


@contextmanager
def restored_source(s, run: m.Run) -> Iterator[Path]:  # noqa: ANN001
    src = dict(run.source or {})
    mode = src.get("mode")
    settings = get_settings()
    tmp = Path(tempfile.mkdtemp(prefix="aisw-src-"))
    try:
        dest = tmp / "src"
        if mode == "path":
            if not src.get("scan_path"):
                raise SourceUnavailable("у запуска нет сведений об исходном каталоге")
            root = check_scan_path(src["scan_path"], settings.scan_root_paths())
            shutil.copytree(root, dest, symlinks=True, ignore=shutil.ignore_patterns(".git"))
            base = dest
        elif mode == "upload":
            up = s.get(m.Upload, src.get("upload_id"))
            if up is None or up.workspace_id != run.workspace_id:
                raise SourceUnavailable("загруженный архив запуска не найден")
            if upload_expired(up):
                raise SourceUnavailable(f"архив удалён по истечении срока хранения ({settings.upload_retention_hours} ч)"
                                        " — загрузите код заново и повторите запуск")
            limits = ExtractLimits(settings.upload_max_files, settings.upload_max_unpacked_bytes)
            base = safe_extract(read_upload(up), up.filename, dest, limits)
        elif mode == "git_url":
            commit = src.get("commit")
            if not commit:
                raise SourceUnavailable("у запуска нет commit sha")
            token = None
            if src.get("token_ref"):
                cred = s.get(m.Credential, src["token_ref"])
                if cred is not None and cred.workspace_id == run.workspace_id:
                    token = get_box().decrypt(cred.ciphertext)
            clone_repo(src.get("url", ""), commit, dest, allowlist_for(s, run.workspace_id), token)
            base = dest
        else:
            raise SourceUnavailable(f"исходники запуска недоступны (режим {mode!r})")
        yield _subdir(base, src.get("subdir"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
